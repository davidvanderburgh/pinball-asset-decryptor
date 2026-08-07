#!/usr/bin/env python3
"""msgtables.py - enumerate the game's 0x18-stride message tables.

The LED names, the coil names and (it turns out) several other per-device tables
all live in the same shape: records of 0x18 bytes whose first word points at a
name, five language slots and a null. lednames.py reads one of them; this finds
all of them, so the next one does not have to be stumbled on.

Nothing here is reachable by findref.sh or litref.py - every reference to these
tables goes through the GOT - which is why enumerating them structurally is the
way in rather than searching for a name.
"""
import struct
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gameinfo

GAME = gameinfo.elf()
VA_BIAS = 0x8000
STRIDE = 0x18
LO, HI = 0x700000, 0x790000
MIN_RECORDS = 8


def main():
    d = open(sys.argv[1] if len(sys.argv) > 1 else GAME, "rb").read()

    def cstr(va):
        o = va - VA_BIAS
        if o < 0 or o >= len(d):
            return None
        e = d.find(b"\0", o)
        if e < 0 or e - o > 70:
            return None
        try:
            t = d[o:e].decode("ascii")
        except UnicodeDecodeError:
            return None
        return t if t and all(32 <= ord(c) < 127 for c in t) else None

    runs, start, n = [], None, 0
    va = LO
    while va < HI:
        o = va - VA_BIAS
        if o + 4 > len(d):
            break
        s = cstr(struct.unpack_from("<I", d, o)[0])
        if s is not None:
            if start is None:
                start, n = va, 0
            n += 1
        else:
            if start is not None and n >= MIN_RECORDS:
                runs.append((start, n))
            start = None
        va += STRIDE
    if start is not None and n >= MIN_RECORDS:
        runs.append((start, n))

    print("%d tables of >=%d records\n" % (len(runs), MIN_RECORDS))
    for base, cnt in runs:
        def at(i):
            return cstr(struct.unpack_from("<I", d, base + i * STRIDE - VA_BIAS)[0]) or ""
        print("VA 0x%06x  %4d records" % (base, cnt))
        for i in (0, 1, 2):
            if i < cnt:
                print("      [%d] %s" % (i, at(i)))
        if cnt > 4:
            print("      ...")
            print("      [%d] %s" % (cnt - 1, at(cnt - 1)))
        print()


if __name__ == "__main__":
    main()
