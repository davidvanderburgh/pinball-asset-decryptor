#!/usr/bin/env python3
"""ledrec.py [va] [count] - dump the raw LED records word by word.

lednames.py reads these tables at a 0x18 stride and gets the names right, but
0x18 is NOT the record size - it is the size of the five-language name slot
INSIDE a larger record. msgtables.py made that obvious: scanning at 0x18 turns up
runs like `playfield / 8b / playfield`, i.e. the scan is landing on a different
field of the same repeating structure each time.

The full record carries the image the fixture is drawn on ("playfield",
"Test/scaled_godzilla_topper", "System/TestMode/..."), its connector, its name -
and, if the game can author a spatial sweep across the playfield, a POSITION.
That is what this dump is for: print every word with its string resolved and its
plausible-coordinate reading, and let the layout show itself.
"""
import struct
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gameinfo

GAME = gameinfo.elf()
VA_BIAS = 0x8000


def main():
    d = open(GAME, "rb").read()

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

    base = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x766FC0
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 96

    for i in range(count):
        va = base + i * 4
        w = struct.unpack_from("<I", d, va - VA_BIAS)[0]
        s = cstr(w)
        f = struct.unpack_from("<f", d, va - VA_BIAS)[0]
        halves = struct.unpack_from("<hh", d, va - VA_BIAS)
        note = ""
        if s:
            note = "-> %r" % s
        elif 0.0001 < abs(f) < 4000:
            note = "float %.3f" % f
        elif w and (0 < halves[0] < 1200 or 0 < halves[1] < 1200):
            note = "i16 %d,%d" % halves
        print("0x%06x  %08x  %s" % (va, w, note))


if __name__ == "__main__":
    main()
