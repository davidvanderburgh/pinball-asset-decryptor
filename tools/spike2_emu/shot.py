#!/usr/bin/env python3
"""shot.py <frame.png> - decode a glraster frame and say what is actually in it.

The rasteriser writes stored-deflate PNGs, so every file is the same size no
matter what it contains. File size therefore proves nothing; this reports the
lit-pixel count, the bounding box and a coarse ASCII view instead.
"""
import sys, zlib, struct

def read_png(path):
    d = open(path, 'rb').read()
    assert d[:8] == b'\x89PNG\r\n\x1a\n', 'not a png'
    off, idat, w, h = 8, b'', 0, 0
    while off < len(d):
        n, tag = struct.unpack_from('>I4s', d, off)
        body = d[off + 8:off + 8 + n]
        if tag == b'IHDR':
            w, h, bits, ctype = struct.unpack_from('>IIBB', body, 0)
            assert bits == 8 and ctype == 2, (bits, ctype)
        elif tag == b'IDAT':
            idat += body
        off += 12 + n
    raw = zlib.decompress(idat)
    stride = w * 3
    rows = []
    for y in range(h):
        base = y * (stride + 1)
        assert raw[base] == 0, 'unexpected png filter'
        rows.append(raw[base + 1:base + 1 + stride])
    return w, h, rows

def main():
    path = sys.argv[1]
    w, h, rows = read_png(path)
    lit = 0
    minx, miny, maxx, maxy = w, h, -1, -1
    colours = {}
    for y in range(0, h, 2):
        r = rows[y]
        for x in range(0, w, 2):
            p = r[x * 3:x * 3 + 3]
            if p[0] > 8 or p[1] > 8 or p[2] > 8:
                lit += 1
                if x < minx: minx = x
                if x > maxx: maxx = x
                if y < miny: miny = y
                if y > maxy: maxy = y
                colours[bytes(p)] = colours.get(bytes(p), 0) + 1
    total = (w // 2) * (h // 2)
    print('%s  %dx%d' % (path, w, h))
    print('  lit pixels : %d / %d sampled (%.2f%%)' % (lit, total, 100.0 * lit / total))
    if maxx < 0:
        print('  ENTIRELY BLACK')
        return
    print('  bounding box : x %d..%d   y %d..%d' % (minx, maxx, miny, maxy))
    print('  distinct colours : %d' % len(colours))
    top = sorted(colours.items(), key=lambda kv: -kv[1])[:6]
    print('  most common  : ' + ', '.join('#%02x%02x%02x x%d' % (c[0], c[1], c[2], n)
                                          for c, n in top))
    cols, lines = 78, 24
    print('  --- coarse view ---')
    for ly in range(lines):
        out = []
        for lx in range(cols):
            x = int(lx * w / cols)
            y = int(ly * h / lines)
            p = rows[y][x * 3:x * 3 + 3]
            v = (p[0] + p[1] + p[2]) // 3
            out.append(' .:-=+*#%@'[min(9, v * 10 // 256)])
        print('  |' + ''.join(out) + '|')

main()
