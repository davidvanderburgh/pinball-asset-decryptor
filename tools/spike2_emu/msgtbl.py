#!/usr/bin/env python3
"""msgtbl.py - find the extent of the localized-message table that holds the
"GAME VALIDATION ERROR #N UPDATE SD CARD" rows, and print the row index of each
one. Rows are 24 bytes: one zero word (the runtime slot) then five pointers to
the same English string. Knowing the base plus the row size turns the on-screen
"#2" and "#3" into message ids the code can be searched for.
"""
import struct
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gameinfo

PATH = gameinfo.elf()
SEGS = [(0x000000, 0x008000, 0x6e52c0), (0x6e52c0, 0x6f52c0, 0x9f460)]


def va2off(va):
    for off, vaddr, size in SEGS:
        if vaddr <= va < vaddr + size:
            return off + (va - vaddr)
    return None


def off2va(off):
    for o, vaddr, size in SEGS:
        if o <= off < o + size:
            return vaddr + (off - o)
    return None


def cstr(d, off, limit=90):
    end = d.find(b'\0', off)
    if end < 0 or end - off > limit:
        end = off + limit
    return d[off:end].decode('utf-8', 'replace').replace('\n', '\\n')


def is_row(d, off):
    """Row = zero word then five equal pointers into the rodata string area."""
    if off + 24 > len(d):
        return None
    w = struct.unpack_from('<6I', d, off)
    if w[0] != 0:
        return None
    if not all(x == w[1] for x in w[1:]):
        return None
    so = va2off(w[1])
    if so is None:
        return None
    return cstr(d, so)


def main():
    d = open(PATH, 'rb').read()
    anchor = va2off(0x753480)          # the "#6 UPDATE SD CARD" row
    lo = anchor
    while is_row(d, lo - 24):
        lo -= 24
    hi = anchor
    while is_row(d, hi + 24):
        hi += 24
    print('table base VA %08x  end VA %08x  rows=%d'
          % (off2va(lo), off2va(hi + 24), (hi - lo) // 24 + 1))
    for i, off in enumerate(range(lo, hi + 24, 24)):
        s = is_row(d, off)
        va = off2va(off)
        mark = ' <==' if 'UPDATE SD CARD' in s or 'Tech' in s else ''
        print('  [%3d] %08x  "%s"%s' % (i, va, s, mark))


main()
