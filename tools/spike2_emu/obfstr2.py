#!/usr/bin/env python3
"""obfstr2.py <cipher_va> [...] - decrypt an obfuscated blob without its key.

    out[i] = key[i & 3] ^ c[i] ^ c[i-1]      for i >= 1
    out[0] = key[0] ^ c[0] ^ key[i2] ^ key[i3]

Each key byte only affects one residue class mod 4, so the key falls out of
"every character before the terminator must be printable". Search the LONGEST
terminator position first: a short string is always solvable (the very first
index can be forced to zero) and taking it is how the first version of this
script returned one-character garbage for every blob.

Most of these blobs are decrypted INLINE with the key constant-folded into
immediates, so recovering it from the ciphertext beats reading seven call sites.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gameinfo

PATH = gameinfo.elf()
SEGS = [(0x000000, 0x008000, 0x6e52c0), (0x6e52c0, 0x6f52c0, 0x9f460)]
OK = set(range(32, 127)) | {9, 10, 13}


def va2off(va):
    for off, vaddr, size in SEGS:
        if vaddr <= va < vaddr + size:
            return off + (va - vaddr)
    return None


def solve(d, c, maxlen=512):
    x = [d[c + i] ^ d[c + i - 1] for i in range(1, maxlen)]
    out = []
    for length in range(maxlen - 2, 0, -1):
        tcls = length % 4
        kt = x[length - 1]
        if any((x[i - 1] ^ kt) not in OK
               for i in range(1, length) if i % 4 == tcls):
            continue
        # The four residue classes are INDEPENDENT, so each key byte can be
        # chosen on its own by scoring only the characters it produces. That is
        # what makes this tractable: no cross-class search, no product blow-up.
        key = [None] * 4
        for cls in range(4):
            if cls == tcls:
                key[cls] = kt
                continue
            idxs = [i for i in range(1, length) if i % 4 == cls]
            if not idxs:
                key[cls] = 0
                continue
            best, bestk = None, None
            for k in range(256):
                ch = [x[i - 1] ^ k for i in idxs]
                if any(b not in OK for b in ch):
                    continue
                sc = sum(3 if 65 <= b <= 90 or 97 <= b <= 122
                         else 2 if b == 32 or 48 <= b <= 57
                         else 1 for b in ch)
                if best is None or sc > best:
                    best, bestk = sc, k
            if bestk is None:
                key = None
                break
            key[cls] = bestk
        if key is None:
            continue
        out.append((key, bytes((x[i - 1] ^ key[i % 4]) for i in range(1, length))))
        return out
    return out


# Keys seen in the binary: two in the descriptor table at 0x6438bc, one folded
# into the immediates at the inline site 0x24b624. Trying the known ones first
# beats guessing: the printability search recovers the terminator class exactly
# but can still pick a wrong byte for a class with few constraints.
KNOWN = (0x7e3241a9, 0x5d1bc2a4, 0x2c404b11, 0x52720ab8, 0x5d02e377,
         0x4fcd5236, 0xf85bcf7f)


def with_key(d, c, key, maxlen=512):
    kb = [(key >> (8 * i)) & 0xff for i in range(4)]
    out = bytearray()
    i = 1
    while i < maxlen:
        b = kb[i & 3] ^ d[c + i] ^ d[c + i - 1]
        if b == 0:
            return out.decode('utf-8', 'replace')
        if b not in OK:
            return None
        out.append(b)
        i += 1
    return None


def main():
    d = open(PATH, 'rb').read()
    for a in sys.argv[1:]:
        va = int(a, 0)
        off = va2off(va)
        hit = 0
        for key in KNOWN:
            t = with_key(d, off, key)
            if t:
                print('%08x  key=%08x  %r' % (va, key, '?' + t))
                hit = 1
        if hit:
            continue
        res = solve(d, off)
        if not res:
            print('%08x  <no solution>' % va)
            continue
        for k, txt in res:
            first = ''
            for i2 in range(4):
                for i3 in range(4):
                    b = k[0] ^ d[off] ^ k[i2] ^ k[i3]
                    if b in OK and b != 0:
                        first = chr(b)
                        break
                if first:
                    break
            print('%08x  key=%02x%02x%02x%02x  %r'
                  % (va, k[3], k[2], k[1], k[0],
                     first + txt.decode('utf-8', 'replace')))


main()
