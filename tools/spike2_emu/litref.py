#!/usr/bin/env python3
"""litref.py <va> ... - find pc-relative LITERAL POOL references to an address.

findref.sh only resolves movw/movt pairs, and grepping game.dis for the value
finds nothing either - .symtab is stripped, so objdump has no $a/$d/$t mapping
symbols and disassembles every pool word as if it were an instruction. The only
reliable way to find a literal is to search the raw bytes of .text for the
4-byte little-endian value.

Reports each hit as a file offset, a VA, and the 32 bytes around it.
"""
import struct
import sys

PATH = '/home/david/spike2root/games/godzilla_pro/game'
TEXT_VA_LO, TEXT_VA_HI = 0x16a00, 0x5d3168      # .text
RO_VA_HI = 0x6d63d4                              # end of .rodata-ish R/E segment


def main():
    d = open(PATH, 'rb').read()
    lo, hi = TEXT_VA_LO - 0x8000, RO_VA_HI - 0x8000
    for a in sys.argv[1:]:
        va = int(a, 0)
        pat = struct.pack('<I', va)
        hits = []
        i = lo
        while True:
            i = d.find(pat, i, hi)
            if i < 0:
                break
            hits.append(i)
            i += 1
        print('=== %08x : %d literal hit(s) in .text/.rodata' % (va, len(hits)))
        for h in hits[:12]:
            vaddr = h + 0x8000
            where = 'text' if vaddr < TEXT_VA_HI else 'rodata'
            ctx = d[h - 12:h + 16].hex()
            print('   off %08x  va %08x  (%s)  %s' % (h, vaddr, where, ctx))


main()
