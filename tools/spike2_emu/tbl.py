#!/usr/bin/env python3
"""tbl.py <va> <count> - dump a table of 32-bit words at a virtual address and
resolve each one that points into the file to the string it names.

VA->offset is NOT a single constant in this binary: the R/E segment maps
offset 0 at 0x8000 and the RW segment maps 0x6e52c0 at 0x6f52c0, i.e. +0x10000.
Using +0x8000 everywhere silently reads the wrong bytes for anything in .data,
which is exactly the sort of thing that manufactures a confident wrong answer.
"""
import struct
import sys

PATH = '/home/david/spike2root/games/godzilla_pro/game'
SEGS = [(0x000000, 0x008000, 0x6e52c0), (0x6e52c0, 0x6f52c0, 0x9f460)]


def va2off(va):
    for off, vaddr, size in SEGS:
        if vaddr <= va < vaddr + size:
            return off + (va - vaddr)
    return None


def cstr(d, off, limit=120):
    end = d.find(b'\0', off)
    if end < 0 or end - off > limit:
        end = off + limit
    return d[off:end].decode('utf-8', 'replace')


def main():
    d = open(PATH, 'rb').read()
    va = int(sys.argv[1], 0)
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 32
    for i in range(n):
        a = va + 4 * i
        off = va2off(a)
        if off is None or off + 4 > len(d):
            print('%08x  <unmapped>' % a)
            continue
        w = struct.unpack_from('<I', d, off)[0]
        soff = va2off(w)
        txt = ''
        if soff is not None and 0 <= soff < len(d):
            s = cstr(d, soff)
            if s and all(32 <= ord(c) < 127 or c in '\n\t' for c in s):
                txt = '  "%s"' % s.replace('\n', '\\n')
        print('%08x  %08x%s' % (a, w, txt))


main()
