#!/usr/bin/env python3
"""litscan.py <lo> <hi> - which addresses inside a VA range does .text actually
reference?

Rather than guessing a table base and asking "is this referenced", scan every
4-byte aligned word of .text for values landing in the range and report them
with counts. That finds the real entry points into a data structure even when
the base is not what you assumed.
"""
import struct
import sys
from collections import Counter

PATH = '/home/david/spike2root/games/godzilla_pro/game'
TEXT_OFF_LO, TEXT_OFF_HI = 0x16a00 - 0x8000, 0x5d3168 - 0x8000


def main():
    d = open(PATH, 'rb').read()
    lo = int(sys.argv[1], 0)
    hi = int(sys.argv[2], 0)
    c = Counter()
    where = {}
    for off in range(TEXT_OFF_LO & ~3, TEXT_OFF_HI, 4):
        w = struct.unpack_from('<I', d, off)[0]
        if lo <= w < hi:
            c[w] += 1
            where.setdefault(w, []).append(off + 0x8000)
    print('%d distinct values referenced from .text in %08x..%08x' % (len(c), lo, hi))
    for w, n in sorted(c.items()):
        print('  %08x  x%-3d  literal at %s'
              % (w, n, ' '.join('%08x' % a for a in where[w][:6])))


main()
