#!/usr/bin/env python3
"""cyanrow.py <frame.png>... - report the y-band of the cyan (highlighted) menu
row in each frame.

The Guided Setup / operator menu draws the SELECTED row in cyan and every other
row in white or grey, so the y position of the cyan band IS the cursor. Reading
it numerically beats looking at each picture: it turns "did the button do
anything" into a number per frame, across every frame of a run at once.

Frames are stored-deflate RGB8 PNGs (filter 0 on every row), same as shot.py.
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
    return w, h, [raw[y * (stride + 1) + 1:y * (stride + 1) + 1 + stride]
                  for y in range(h)]


for path in sys.argv[1:]:
    w, h, rows = read_png(path)
    bands, run = [], None
    for y in range(h):
        r = rows[y]
        n = 0
        for x in range(0, w, 3):
            p = r[x * 3:x * 3 + 3]
            if p[2] > 170 and p[1] > 170 and p[0] < 140 and (p[1] - p[0]) > 60:
                n += 1
        if n > 4:
            run = [y, y] if run is None else [run[0], y]
        elif run is not None:
            if run[1] - run[0] > 4:
                bands.append(tuple(run))
            run = None
    if run is not None and run[1] - run[0] > 4:
        bands.append(tuple(run))
    print('%-24s cyan y=%s' % (path.split('/')[-1],
          ', '.join('%d..%d' % b for b in bands) or 'none'))
