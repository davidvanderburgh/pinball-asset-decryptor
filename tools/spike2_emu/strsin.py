#!/usr/bin/env python3
"""strsin.py <dis-file> - resolve every movw/movt pair in a disassembly excerpt
to the string or symbol it builds.

findref.sh answers "who references THIS address"; this is the other direction,
"what does this function reference", which is what you want once you have
located a module and need to know what it is about. String references in this
binary are movw/movt immediate pairs only, so pairing them per register is the
whole job.
"""
import re
import struct
import sys

PATH = '/home/david/spike2root/games/godzilla_pro/game'
SEGS = [(0x000000, 0x008000, 0x6e52c0), (0x6e52c0, 0x6f52c0, 0x9f460)]
LINE = re.compile(r'^\s*([0-9a-f]+):\s+[0-9a-f]{8}\s+(movw|movt)\s+([a-z0-9]+),\s*#(\d+)')


def va2off(va):
    for off, vaddr, size in SEGS:
        if vaddr <= va < vaddr + size:
            return off + (va - vaddr)
    return None


def cstr(d, off, limit=90):
    end = d.find(b'\0', off)
    if end < 0 or end - off > limit:
        end = off + limit
    s = d[off:end].decode('utf-8', 'replace')
    return s if s and all(32 <= ord(c) < 127 or c in '\n\t' for c in s) else None


def main():
    d = open(PATH, 'rb').read()
    lo = {}
    for line in open(sys.argv[1], 'r', errors='replace'):
        m = LINE.match(line)
        if not m:
            continue
        addr, op, reg, val = m.group(1), m.group(2), m.group(3), int(m.group(4))
        if op == 'movw':
            lo[reg] = (addr, val)
            continue
        if reg not in lo:
            continue
        at, low = lo.pop(reg)
        va = (val << 16) | low
        off = va2off(va)
        if off is None:
            continue
        s = cstr(d, off)
        note = '  "%s"' % s.replace('\n', '\\n') if s else ''
        print('%s  %-3s = 0x%08x%s' % (at, reg, va, note))


main()
