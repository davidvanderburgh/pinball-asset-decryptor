#!/usr/bin/env python3
"""repack.py <in.png> <out.png> [scale] - re-encode a glraster frame compactly.

glraster writes STORED (uncompressed) deflate so it needs no zlib inside the
guest, which makes every frame ~6 MB regardless of content. This re-encodes
with real deflate, and optionally downscales, for viewing.
"""
import sys, zlib, struct

def read_png(path):
    d = open(path, 'rb').read()
    assert d[:8] == b'\x89PNG\r\n\x1a\n'
    off, idat, w, h = 8, b'', 0, 0
    while off < len(d):
        n, tag = struct.unpack_from('>I4s', d, off)
        body = d[off + 8:off + 8 + n]
        if tag == b'IHDR':
            w, h = struct.unpack_from('>II', body, 0)
        elif tag == b'IDAT':
            idat += body
        off += 12 + n
    raw = zlib.decompress(idat)
    stride = w * 3
    return w, h, [raw[y * (stride + 1) + 1:y * (stride + 1) + 1 + stride] for y in range(h)]

def chunk(tag, data):
    return (struct.pack('>I', len(data)) + tag + data
            + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))

def main():
    src, dst = sys.argv[1], sys.argv[2]
    scale = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    w, h, rows = read_png(src)
    ow, oh = w // scale, h // scale
    out = bytearray()
    for y in range(oh):
        out.append(0)
        r = rows[y * scale]
        for x in range(ow):
            o = x * scale * 3
            out += r[o:o + 3]
    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', ow, oh, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(bytes(out), 9))
           + chunk(b'IEND', b''))
    open(dst, 'wb').write(png)
    print('%s -> %s  %dx%d  %d bytes' % (src, dst, ow, oh, len(png)))

main()
