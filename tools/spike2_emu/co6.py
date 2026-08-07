#!/usr/bin/env python3
"""co6.py [lo_va] [hi_va] - dump rows of the SECOND message table (0x7150c8).

Rows are 24 bytes: five language-slot pointers and one runtime/zero word. The
coil names live here, not in the 3949-row array at 0x748a10 - which is why
co4.py, searching that one, found nothing.

Prints the row INDEX relative to 0x7150c8, because that index is the msgid a
coil table would hold.
"""
import struct, sys
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gameinfo

PATH = gameinfo.elf()
SEGS = [(0x000000, 0x008000, 0x6e52c0), (0x6e52c0, 0x6f52c0, 0x9f460)]
BASE, STRIDE = 0x7150c8, 24
img = open(PATH, 'rb').read()


def va2off(va):
    for off, vaddr, size in SEGS:
        if vaddr <= va < vaddr + size:
            return off + (va - vaddr)
    return None


def cstr(va):
    o = va2off(va)
    if o is None:
        return None
    e = img.find(b'\0', o, o + 400)
    return img[o:e].decode('utf-8', 'replace') if e > 0 else None


lo = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x716900
hi = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x716d00
i0 = (lo - BASE) // STRIDE
i1 = (hi - BASE) // STRIDE
for i in range(i0, i1 + 1):
    va = BASE + i * STRIDE
    o = va2off(va)
    if o is None:
        continue
    words = struct.unpack_from('<6I', img, o)
    s = None
    for w in words:
        if w:
            s = cstr(w)
            if s:
                break
    print('row %5d  0x%06x  %r' % (i, va, s))
