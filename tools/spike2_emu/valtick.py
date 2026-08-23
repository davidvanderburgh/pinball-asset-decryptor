#!/usr/bin/env python3
r"""valtick.py - is this title's GAME VALIDATION state machine alive or NOPPED?

    valtick.py                         # the active title, via gameinfo.py
    valtick.py --elf /path/to/game     # any extracted game ELF
    valtick.py --elf a --elf b         # compare several at once

WHAT IT ANSWERS. A modified SD card can disable the game's validation subsystem
with a FOUR-BYTE patch: replace the state machine tick's prologue with `bx lr`
and it returns before doing anything, every time. That is what the upscaled
turtles_pro card does and what the Heisei custom godzilla_le image does. Knowing
which side of that line a card is on changes how you read its Tech Alerts
screen, so it is worth one second of scanning rather than an afternoon of RE.

HOW IT FINDS THE TICK WITH NO ADDRESSES. The module moves with every title and
every build, so nothing can be hard-coded. But the tick always opens by reading
the state byte at MOD+0xc5 and testing it against the terminal state 8:

    ldrb  rX, [rY, #197]        e5dY X0c5
    cmp   rX, #8                e35X 0008

Those two encodings back to back are specific enough to hit exactly once in a
7 MB binary - measured on five different builds, one candidate each. From that
site it walks BACKWARDS to the function entry: a register-saving push (e92d....
with the LR bit) is healthy, and e12fff1e (`bx lr`) is defeated.

WHY "NOPPED" DOES NOT MEAN "NO BANNER" - the trap this tool exists beside.
The module initialises the three grade bytes to 1 ("P"), so it is tempting to
conclude that a dead tick leaves everything passing and silences the alert. It
does not. The module's start function RESTORES a persisted blob over the whole
struct and only initialises when that restore fails, so a dead tick freezes
whatever was last written to NVRAM - which can be a failure, and which nothing
is then alive to clear. A nopped tick makes the banner UNCLEARABLE rather than
absent. Verified the hard way: item 62 asserted the opposite and the next boot
of the Heisei image disproved it.

VALIDATED 2026-08-23 against four binaries whose answer was already known by
hand: turtles_pro stock healthy (0x2e15c4), turtles_pro upscaled NOPPED
(0x2e15c4), godzilla_pro stock healthy (0x24a4cc - which is also where the
independently-derived godzilla->turtles mapping of +0x970f8 predicts it), and
godzilla_le stock healthy (0x248834).
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gameinfo

BX_LR = 0xE12FFF1E
PUSH_LR = 0xE92D4000          # stmfd sp!, {..., lr}
STATE_OFF = 197               # MOD+0xc5, the state-machine state byte
TERMINAL = 8                  # the state the tick treats as "finished"


def phdrs(d):
    """[(file_off, vaddr, filesz)] for each PT_LOAD, read from the ELF itself."""
    if d[:4] != b"\x7fELF":
        raise ValueError("not an ELF")
    if d[4] != 1:
        raise ValueError("not 32-bit")
    e_phoff = struct.unpack_from("<I", d, 0x1C)[0]
    e_phentsize = struct.unpack_from("<H", d, 0x2A)[0]
    e_phnum = struct.unpack_from("<H", d, 0x2C)[0]
    out = []
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsize
        p_type, p_off, p_vaddr, _pa, p_filesz = struct.unpack_from("<5I", d, o)
        if p_type == 1:
            out.append((p_off, p_vaddr, p_filesz))
    return out


def find_ticks(d, seg):
    """[(file_off, dest_reg, base_reg)] for every tick signature in the segment."""
    o, _va, sz = seg
    hits = []
    for off in range(o, o + sz - 8, 4):
        w0 = struct.unpack_from("<I", d, off)[0]
        # ldrb rX, [rY, #197] - any base register, immediate 197 in the low 12 bits
        if (w0 & 0xFFF00FFF) != (0xE5D00000 | STATE_OFF):
            continue
        rx = (w0 >> 12) & 0xF
        w1 = struct.unpack_from("<I", d, off + 4)[0]
        if w1 != (0xE3500000 | (rx << 16) | TERMINAL):
            continue
        hits.append((off, rx, (w0 >> 16) & 0xF))
    return hits


def entry_of(d, site_off, seg_off, limit=64):
    """Walk back from a tick site to the function's first instruction."""
    for back in range(1, limit + 1):
        p = site_off - back * 4
        if p < seg_off:
            return None
        w = struct.unpack_from("<I", d, p)[0]
        if w == BX_LR:
            return (p, w, "NOPPED - the state machine never runs")
        if (w & 0xFFFF4000) == PUSH_LR:
            return (p, w, "healthy")
    return None


def scan(path):
    with open(path, "rb") as f:
        d = f.read()
    text = phdrs(d)[0]                  # the executable segment is always first here
    t_off, t_va, _sz = text

    def off2va(off):
        return t_va + (off - t_off)

    hits = find_ticks(d, text)
    print("%s" % path)
    if not hits:
        print("    no validation tick found - is this a Spike 2 game ELF?")
        return
    if len(hits) > 1:
        print("    NOTE: %d candidate sites. Every build measured so far has "
              "exactly one, so treat this as unmapped territory." % len(hits))
    for site, _rx, base in hits:
        ent = entry_of(d, site, t_off)
        if ent is None:
            print("    site 0x%06x  (base r%d)  - no prologue within 64 insns"
                  % (off2va(site), base))
            continue
        p, w, verdict = ent
        print("    tick 0x%06x   first insn %08x   %s"
              % (off2va(p), w, verdict))


def main():
    argv = sys.argv[1:]
    paths = []
    while argv and argv[0] == "--elf":
        if len(argv) < 2:
            raise SystemExit("valtick.py: --elf needs a path")
        paths.append(argv[1])
        argv = argv[2:]
    if argv:
        raise SystemExit("usage: valtick.py [--elf PATH]...")
    if not paths:
        p = gameinfo.elf()
        # A published path that no longer exists is the stale dump/title case:
        # after a card run ends its FUSE mount is gone but the file remains.
        if p and not os.path.exists(p):
            name = gameinfo.active()
            alt = os.path.join(gameinfo.root() or "", "games", name or "", "game")
            if os.path.exists(alt):
                p = alt
        if not p or not os.path.exists(p):
            raise SystemExit("valtick.py: no game ELF (set PAD_GAME or pass --elf)")
        paths = [p]
    for path in paths:
        try:
            scan(path)
        except (OSError, ValueError) as e:
            print("%s: %s" % (path, e))
        print()


if __name__ == "__main__":
    main()
