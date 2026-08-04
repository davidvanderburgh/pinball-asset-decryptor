#!/usr/bin/env python3
"""co5.py - locate the COIL NAME table.

The coil names ("COIL #33", "OPTIONAL COIL", "UP RIGHT FLIPPER", "POP BUMPER",
"3-BANK DROP TARGET RESET", "SHIELD MOTOR", "AUTO LAUNCH", "TROUGH UP-KICKER")
sit in .rodata with their German/French/Spanish/Italian translations immediately
after each one - the shape of a multi-language message row, not of the 24-byte
array at 0x748a10 (which does not contain them: co4.py comes up empty).

So find the table by scanning the whole image for a POINTER to one of those
strings, then dump the rows around the hit. Searching for the pointer is the
only reliable move here: litref.py over these addresses returns nothing,
the same dead end every other .rodata search in this binary hits.
"""
import struct, sys

PATH = '/home/david/spike2root/games/godzilla_pro/game'
SEGS = [(0x000000, 0x008000, 0x6e52c0), (0x6e52c0, 0x6f52c0, 0x9f460)]
img = open(PATH, 'rb').read()


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


def cstr(va):
    o = va2off(va)
    if o is None:
        return None
    e = img.find(b'\0', o, o + 400)
    if e < 0:
        return None
    return img[o:e].decode('utf-8', 'replace')


targets = [int(a, 16) for a in sys.argv[1:]] or [0x5e776c]   # "COIL #33"
for t in targets:
    print('=== pointers to 0x%06x  (%r) ===' % (t, cstr(t)))
    pat = struct.pack('<I', t)
    i = 0
    hits = 0
    while True:
        i = img.find(pat, i)
        if i < 0:
            break
        va = off2va(i)
        print('  at file 0x%06x  VA 0x%06x' % (i, va if va else 0))
        # dump the 12 words around it, resolved
        lo = max(0, i - 40)
        for j in range(lo, min(len(img), i + 44), 4):
            w = struct.unpack_from('<I', img, j)[0]
            s = cstr(w) if w else None
            mark = ' <==' if j == i else ''
            print('    +%3d 0x%06x = %08x  %s%s'
                  % (j - i, off2va(j) or 0, w,
                     ('%r' % s) if s and s.isprintable() and len(s) < 60 else '',
                     mark))
        i += 4
        hits += 1
        if hits > 4:
            break
    if not hits:
        print('  none')
