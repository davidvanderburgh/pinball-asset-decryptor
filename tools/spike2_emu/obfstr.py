#!/usr/bin/env python3
"""obfstr.py [base_va] [n] - decrypt the game's OBFUSCATED string table.

0x249f60(n) is not a message-table lookup, it is a decryptor. That is the whole
reason four static searches for "GAME VALIDATION ERROR" came back empty: the
validation raiser never names a message row, it decrypts a blob into a fixed
scratch buffer at 0x7b7bf0 and sprintf's that.

Descriptor, 16 bytes at BASE + n*16:
    +0  key      the 4 key bytes, little-endian
    +4  off      cipher text lives at BASE + 128 + off
    +8  i2       index into the key, used only for byte 0
    +12 i3       ditto

    out[0] = key[0] ^ c[0] ^ key[i2] ^ key[i3]
    out[i] = key[i & 3] ^ c[i] ^ c[i-1]        for i >= 1
    stop at the first zero byte

Transcribed from 249f60..24a010; the `add rX, sp+8, off` / `ldrb [rX,#-4]`
pairs are just key[off] with the key spilled at sp+4.
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


def decrypt(d, base_off, n):
    desc = base_off + n * 16
    key, off, i2, i3 = struct.unpack_from('<4I', d, desc)
    kb = struct.pack('<I', key)
    c = base_off + 128 + off
    out = bytearray()
    b = (kb[0] ^ d[c] ^ kb[i2 & 3] ^ kb[i3 & 3]) & 0xff
    if b == 0:
        return '', (key, off, i2, i3)
    out.append(b)
    i = 1
    while i < 4096:
        b = (kb[i & 3] ^ d[c + i] ^ d[c + i - 1]) & 0xff
        if b == 0:
            break
        out.append(b)
        i += 1
    return out.decode('utf-8', 'replace'), (key, off, i2, i3)


def main():
    d = open(PATH, 'rb').read()
    base_va = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x6438bc
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    base_off = va2off(base_va)
    print('base VA %08x -> file %08x' % (base_va, base_off))
    for i in range(n):
        try:
            s, desc = decrypt(d, base_off, i)
        except Exception as e:                                  # noqa: BLE001
            print('[%2d] <%s>' % (i, e))
            continue
        print('[%2d] key=%08x off=%-6d i2=%d i3=%d  %r'
              % (i, desc[0], desc[1], desc[2], desc[3], s))


main()
