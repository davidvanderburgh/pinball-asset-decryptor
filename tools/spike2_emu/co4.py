#!/usr/bin/env python3
"""co4.py - find the message-table ROW INDEX of every coil name.

The coil names live in the same 3949-row x 24-byte localized message array at
0x748a10 that the switch names do (msgtbl2.py found it). Anything in the game
that names a coil therefore holds a ROW INDEX, and a table of row indices in
coil order is what the Coil Test screen must walk - the same shape as the switch
table's [[entry+12]+16].

Usage: co4.py [substring ...]     default: the coil-name set
"""
import struct, sys

PATH = '/home/david/spike2root/games/godzilla_pro/game'
SEGS = [(0x000000, 0x008000, 0x6e52c0), (0x6e52c0, 0x6f52c0, 0x9f460)]
BASE, ROWS, STRIDE = 0x748a10, 3949, 24

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
    e = img.find(b'\0', o)
    try:
        return img[o:e].decode('utf-8', 'replace')
    except Exception:
        return None


wanted = sys.argv[1:] or ['COIL #', 'FLIPPER', 'SLINGSHOT', 'POP BUMPER',
                          'TROUGH', 'AUTO LAUNCH', 'DROP TARGET RESET',
                          'SHIELD MOTOR', 'KNOCKER', 'SCOOP', 'MAGNET',
                          'PLUNGER', 'SHAKER', 'DIVERTER', 'VUK', 'EJECT',
                          'GATE', 'SAUCER', 'RAMP', 'MOTOR', 'BUILDING',
                          'BRIDGE', 'OPTIONAL COIL']

base_off = va2off(BASE)
for i in range(ROWS):
    o = base_off + i * STRIDE
    p = struct.unpack_from('<I', img, o + 4)[0]      # slot0 is at +4
    if not p:
        p = struct.unpack_from('<I', img, o)[0]
    s = cstr(p) if p else None
    if not s:
        continue
    if any(w in s for w in wanted):
        print('row %4d  0x%06x  %s' % (i, BASE + i * STRIDE, s))
