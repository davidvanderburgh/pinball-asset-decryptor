#!/usr/bin/env python3
"""msgtbl2.py - find the TRUE base of the localized-message array.

msgtbl.py used a strict row test (one zero word then five IDENTICAL pointers),
which stops at the first row that has a real translation or a non-zero runtime
slot. Nothing in the whole binary points at the base it reported, so that base
is wrong. This relaxes the test to "five words that are all valid .rodata string
pointers" and reports the maximal run, then dumps the head and tail of it.
"""
import struct
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gameinfo

PATH = gameinfo.elf()
SEGS = [(0x000000, 0x008000, 0x6e52c0), (0x6e52c0, 0x6f52c0, 0x9f460)]
RODATA_LO, RODATA_HI = 0x5d3178, 0x6d63d4


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


def cstr(d, off, limit=70):
    end = d.find(b'\0', off)
    if end < 0 or end - off > limit:
        end = off + limit
    return d[off:end].decode('utf-8', 'replace').replace('\n', '\\n')


def strptr(w):
    return RODATA_LO <= w < RODATA_HI


def is_row(d, off):
    if off < 0 or off + 24 > len(d):
        return False
    w = struct.unpack_from('<6I', d, off)
    return all(strptr(x) for x in w[1:])


def main():
    d = open(PATH, 'rb').read()
    anchor = va2off(0x753480)
    lo = anchor
    while is_row(d, lo - 24):
        lo -= 24
    hi = anchor
    while is_row(d, hi + 24):
        hi += 24
    n = (hi - lo) // 24 + 1
    print('relaxed run: base VA %08x  rows=%d  anchor row index=%d'
          % (off2va(lo), n, (anchor - lo) // 24))
    for i in list(range(0, 6)) + list(range(n - 4, n)):
        off = lo + 24 * i
        w = struct.unpack_from('<6I', d, off)
        print('  [%3d] %08x slot0=%08x  "%s"'
              % (i, off2va(off), w[0], cstr(d, va2off(w[1]))))


main()
