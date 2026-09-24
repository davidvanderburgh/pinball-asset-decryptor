#!/usr/bin/env python3
"""port_words.py - fill in, or check, a port's instruction words from the game's ELF.

    port_words.py <game ELF> <port file>            check: report every site that differs
    port_words.py <game ELF> <port file> --write    rewrite each `site` line's two words

A port's `site <name> <address> <w0> <w1>` lines carry the first two instruction words
the runtime compares before it touches that function - the safety gate that makes a
port for the wrong game or version hook nothing. Those words must come from the ELF,
never from a person, so this is how a port gets them.

It also refuses a HOOKED site (tick, shot_dispatch, ball_end, sound_lookup, switch_edge, every
switch_hit*, the display and roster hooks: portgen.is_hooked_site) whose first
two instructions depend on the program counter: those cannot be moved into a
trampoline, and hooking one would crash the game. A literal load (`ldr rd, [pc, #n]`) is
the exception: the runtime copies the literal and moves it (item 137).
"""
import os
import re
import struct
import sys

# the package this file ships beside (a checkout or an install: four folders up)
_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
if os.path.isdir(os.path.join(_ROOT, "pinball_decryptor")) and _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
# the checks themselves are the package's (the app checks a port it derives with them too)
from pinball_decryptor.plugins.stern.portgen import (  # noqa: E402,F401
    HOOKED_SITES as HOOKED, event_problems, is_hooked_site, literal_load, movable, pc_dependent)

__all__ = ["HOOKED", "is_hooked_site", "event_problems", "literal_load", "movable", "pc_dependent", "segments", "words_at", "main"]


def segments(elf):
    if elf[:4] != b"\x7fELF" or elf[4] != 1:
        raise SystemExit("not a 32-bit ELF")
    phoff, = struct.unpack_from("<I", elf, 0x1C)
    phentsize, phnum = struct.unpack_from("<HH", elf, 0x2A)
    out = []
    for i in range(phnum):
        p_type, p_off, p_vaddr, _pa, p_filesz, _ms, flags, _al = struct.unpack_from("<8I", elf, phoff + i * phentsize)
        if p_type == 1:
            out.append((p_vaddr, p_off, p_filesz, flags))
    return out


def words_at(elf, segs, va):
    for vaddr, off, size, flags in segs:
        if vaddr <= va and va + 8 <= vaddr + size:
            if not flags & 1:
                raise ValueError("0x%x is not in executable code" % va)
            return struct.unpack_from("<II", elf, off + va - vaddr)
    raise ValueError("0x%x is not in the ELF" % va)


SITE = re.compile(r"^(\s*site\s+)(\S+)(\s+)(0x[0-9a-fA-F]+|\d+)(.*)$")


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    elf = open(argv[0], "rb").read()
    segs = segments(elf)
    lines = open(argv[1], encoding="utf-8").read().splitlines()
    write = "--write" in argv
    bad = 0
    out = []
    # the runtime's fixed buffers (pad_mode_runtime.c): a longer entry would be cut short
    for n, line in enumerate(lines, 1):
        parts = line.split(None, 2)
        if len(parts) < 2 or parts[0].startswith("#"):
            continue
        key = parts[0]
        if key in ("site", "data", "value", "callout", "scene", "text") and len(parts[1]) > 39:
            print("line %d: the name %r is over 39 characters" % (n, parts[1]))
            bad += 1
        if key in ("text", "scene") and len(parts) == 3 and len(parts[2].strip()) > 159:
            print("line %d: the value is over 159 characters" % n)
            bad += 1
        if key == "shot" and len(parts) == 3 and len(parts[2].strip()) > 159:
            print("line %d: the shot name is over 159 characters" % n)
            bad += 1
        if key == "event":
            for problem in event_problems(n, parts, {l.split()[1] for l in lines if l.split()[:1] == ["site"] and len(l.split()) > 1}):
                print(problem)
                bad += 1
    # item 147: a site an `event <name> site <site>` line names is hooked too
    event_sites = {l.split()[3] for l in lines if l.split()[:1] == ["event"] and len(l.split()) > 3 and l.split()[2] == "site"}
    for line in lines:
        m = SITE.match(line)
        if not m:
            out.append(line)
            continue
        name, va = m.group(2), int(m.group(4), 0)
        try:
            w0, w1 = words_at(elf, segs, va)
        except ValueError as e:
            print("%-16s %s" % (name, e))
            bad += 1
            out.append(line)
            continue
        if (is_hooked_site(name) or name in event_sites) and not movable(w0, w1):
            print("%-16s 0x%08x starts %08x %08x - cannot be hooked (pc-relative)" % (name, va, w0, w1))
            bad += 1
        old = m.group(5).split()
        have = [int(x, 0) for x in old[:2]] if len(old) >= 2 else []
        if have != [w0, w1]:
            print("%-16s 0x%08x: port says %s, the ELF has %08x %08x"
                  % (name, va, " ".join(old[:2]) or "(nothing)", w0, w1))
            if not write:
                bad += 1
        tail = " ".join(old[2:])
        out.append("site %-16s 0x%08x 0x%08x 0x%08x%s" % (name, va, w0, w1, ("  " + tail) if tail else ""))
    if write:
        with open(argv[1], "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(out) + "\n")
        print("wrote %s" % argv[1])
    print("%d problem(s)" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
