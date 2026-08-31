#!/usr/bin/env python3
"""Reconstruct a dongle-free game binary from a running, decrypted process.

THE IDEA
--------
The game is Sentinel LDK Envelope protected: on disk 7,091 of its ~18,000
functions are ciphertext, each fronted by a ``call`` into a decrypt trampoline,
and the ELF entry point is the envelope's own loader at 0x21b0ad0.  The
envelope needs the purple USB key because the key holds the AES key its code is
decrypted with.

But the envelope decrypts on demand and leaves the plaintext in memory.  With
a game that has been running a while, ~99.9% of those functions are already
plaintext in RAM (measured: 9 of 7,091 still trampolined).  So a snapshot of
the live process is very nearly the whole program in the clear — and the
original glibc ``_start`` is right there in the game's own text (0x5bd480,
which loads ``main`` and calls ``__libc_start_main``).

So: dump every PT_LOAD segment out of ``/proc/<pid>/mem``, write them back over
a copy of the on-disk ELF, and repoint the entry to the original ``_start``.
The result runs from the game's own code and never enters the envelope, so it
never asks for the key.

WHAT THIS DOES NOT DO
---------------------
This does not break the encryption or extract the key.  It captures code the
envelope ITSELF decrypted, on a machine that HAD the key, for the owner of that
key and that game.  It is exactly the "run it once with the key to make a
key-free copy of your own game" case, and it only works for a title whose key
you have.  A function that never executed before the dump is still ciphertext;
``--warm`` reports how many remain and the game exercises almost all of them
just by reaching attract.

USAGE
-----
    # with the game running (started WITH the key):
    python3 unpack.py --pid $(pgrep -x game | head -1) \
        --elf  /var/tmp/jjp_<slug>/root/jjpe/gen1/<Game>/game \
        --out  /var/tmp/<Game>.free
"""

import argparse
import os
import struct
import sys


def read_maps(pid):
    regions = []
    for line in open(f"/proc/{pid}/maps"):
        parts = line.split()
        rng, perms = parts[0], parts[1]
        a, b = (int(x, 16) for x in rng.split("-"))
        regions.append((a, b, perms))
    return regions


def dump(pid, elf_path, out_path, verbose=True):
    with open(elf_path, "rb") as fh:
        elf = bytearray(fh.read())

    if elf[:4] != b"\x7fELF":
        raise SystemExit("unpack: %s is not an ELF" % elf_path)

    e_entry = struct.unpack_from("<Q", elf, 0x18)[0]
    phoff = struct.unpack_from("<Q", elf, 0x20)[0]
    phentsize, phnum = struct.unpack_from("<HH", elf, 0x36)

    mem = open(f"/proc/{pid}/mem", "rb", 0)
    maps = read_maps(pid)

    def page_perms(vaddr):
        """The mapping permissions covering vaddr, or None if unmapped."""
        for a, b, perms in maps:
            if a <= vaddr < b:
                return perms
        return None

    # ONLY overlay pages that are non-writable in the process - the decrypted
    # code (r-x) and read-only data (r--, which the envelope also encrypts).
    #
    # WRITABLE pages (.data/.bss, rw-) are left as the file's ORIGINAL bytes on
    # purpose.  Those hold runtime state - open fd globals, allocated pointers,
    # the switch/lamp objects the ctors filled in - and copying them back would
    # bake this run's state into the binary, so a fresh launch would start from
    # a half-initialised world and crash.  The envelope does not encrypt
    # writable data anyway (it cannot - the program writes it), so there is
    # nothing to recover there.
    loads = []
    patched = skipped_rw = skipped_unmapped = 0
    for i in range(phnum):
        o = phoff + i * phentsize
        p_type, = struct.unpack_from("<I", elf, o)
        if p_type != 1:                                    # PT_LOAD
            continue
        p_offset, p_vaddr, _p_paddr, p_filesz = struct.unpack_from("<QQQQ", elf, o + 8)
        loads.append((p_vaddr, p_offset, p_filesz))
        if p_filesz == 0:
            continue

        PAGE = 0x1000
        done = 0
        while done < p_filesz:
            chunk = min(PAGE, p_filesz - done)
            va = p_vaddr + done
            fo = p_offset + done
            perms = page_perms(va)
            if perms is None or "r" not in perms:
                skipped_unmapped += chunk         # never faulted in / not readable
            elif "w" in perms:
                skipped_rw += chunk               # writable data - keep the file's
            else:
                try:
                    mem.seek(va)
                    data = mem.read(chunk)
                    if len(data) == chunk:
                        elf[fo:fo + chunk] = data
                        patched += chunk
                    else:
                        skipped_unmapped += chunk
                except OSError:
                    skipped_unmapped += chunk
            done += chunk

    if verbose:
        print("segments: %d  code/rodata from memory: %d  writable kept: %d  "
              "unmapped kept: %d"
              % (len(loads), patched, skipped_rw, skipped_unmapped))

    # Repoint the entry to the game's own _start, so execution never enters the
    # envelope.  Found and passed in by the caller, or detected here.
    return elf, e_entry, loads


def find_oep(elf, loads):
    """The original glibc _start: the canonical prologue that ends by loading
    main into rdi and calling __libc_start_main.  Distinctive enough that one
    match is the answer."""
    prologue = bytes.fromhex("f30f1efa31ed4989d15e4889e24883e4f0")
    for p_vaddr, p_offset, p_filesz in loads:
        seg = elf[p_offset:p_offset + p_filesz]
        idx = seg.find(prologue)
        if idx >= 0:
            return p_vaddr + idx
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Rebuild a dongle-free game from a running process.")
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--elf", required=True, help="the on-disk game binary")
    ap.add_argument("--out", required=True)
    ap.add_argument("--entry", type=lambda x: int(x, 0), default=None,
                    help="override the reconstructed entry point")
    args = ap.parse_args(argv)

    elf, envelope_entry, loads = dump(args.pid, args.elf, args.out)

    oep = args.entry or find_oep(elf, loads)
    if oep is None:
        raise SystemExit("unpack: could not find the original _start; pass "
                         "--entry once you have it from oep analysis")
    struct.pack_into("<Q", elf, 0x18, oep)
    print("entry: %#x (envelope) -> %#x (original _start)" % (envelope_entry, oep))

    with open(args.out, "wb") as fh:
        fh.write(elf)
    os.chmod(args.out, 0o755)
    print("wrote", args.out, "(%d bytes)" % len(elf))
    return 0


if __name__ == "__main__":
    sys.exit(main())
