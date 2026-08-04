#!/usr/bin/env python3
"""nbtbl.py - the node board TYPE table at 0x69cc24.

0x5a2e10 asks a board who it is, takes LE32 of reply payload bytes [4..7] as a
type code, and linear-scans 28 entries of 28 bytes each looking for it. A hit
stores that descriptor pointer in the registry at 0x70a474+0x28+id*4; a miss
stores 0x69cc24-28 = 0x69cc08, the default, whose +20 is 0 - and +20 is exactly
the field the exchange wrapper tests at 0x59ec1c before it will talk to a board
with a subcommand <= 0xef.

So this table IS the list of board identities the game will accept.
"""
import struct
import sys

PATH = '/home/david/spike2root/games/godzilla_pro/game'
d = open(PATH, 'rb').read()


def va(a, n):
    return d[a - 0x8000:a - 0x8000 + n]          # R/E segment: VA = off + 0x8000


def cstr(p):
    if p < 0x8000 or p > 0x6d63d4:
        return None
    o = p - 0x8000
    e = d.find(b'\0', o)
    s = d[o:e]
    try:
        t = s.decode('ascii')
    except Exception:
        return None
    return t if all(32 <= c < 127 for c in s) else None


base = 0x69cc24
print('idx   va        type       +04..+13                        +14 +15..+1b   strings')
for i in range(-1, 29):
    a = base + i * 28
    b = va(a, 28)
    w = struct.unpack('<7I', b)
    strs = [cstr(x) for x in w]
    tag = 'DEFAULT' if i == -1 else '%2d' % i
    print('%-7s 0x%08x  %08x   %s  %s' % (
        tag, a, w[0],
        ' '.join('%08x' % x for x in w[1:]),
        ' | '.join('%d=%r' % (k + 1, s) for k, s in enumerate(strs[1:]) if s)))
