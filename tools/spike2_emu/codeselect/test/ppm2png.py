#!/usr/bin/env python3
"""ppm2png.py IN.ppm OUT.png [--rot180-of OTHER.ppm]

Converts a binary P6 PPM to PNG (PIL when available, else a tiny zlib
writer). With --rot180-of, also asserts IN is exactly OTHER rotated 180
degrees (what codeselect --invert must produce)."""
import struct
import sys
import zlib


def read_ppm(path):
    with open(path, "rb") as f:
        data = f.read()
    # header: P6 <ws> w <ws> h <ws> maxval <single ws>
    parts = []
    pos = 0
    while len(parts) < 4:
        while data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b"#":
            while data[pos:pos + 1] not in (b"\n", b""):
                pos += 1
            continue
        start = pos
        while not data[pos:pos + 1].isspace():
            pos += 1
        parts.append(data[start:pos])
    pos += 1
    if parts[0] != b"P6":
        raise SystemExit("%s: not a P6 PPM" % path)
    w, h = int(parts[1]), int(parts[2])
    px = data[pos:pos + w * h * 3]
    if len(px) != w * h * 3:
        raise SystemExit("%s: short pixel data (%d of %d)" % (path, len(px), w * h * 3))
    return w, h, px


def write_png_zlib(path, w, h, px):
    raw = b"".join(b"\x00" + px[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(tag, body):
        c = tag + body
        return struct.pack(">I", len(body)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 6)))
        f.write(chunk(b"IEND", b""))


def write_png(path, w, h, px):
    try:
        from PIL import Image
        Image.frombytes("RGB", (w, h), px).save(path)
    except ImportError:
        write_png_zlib(path, w, h, px)


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        raise SystemExit(__doc__)
    w, h, px = read_ppm(args[0])
    write_png(args[1], w, h, px)
    if len(args) >= 4 and args[2] == "--rot180-of":
        w2, h2, px2 = read_ppm(args[3])
        if (w, h) != (w2, h2):
            raise SystemExit("size mismatch %dx%d vs %dx%d" % (w, h, w2, h2))
        # rotate OTHER by 180: reverse the pixel order
        rot = b"".join(px2[i * 3:i * 3 + 3] for i in range(w * h - 1, -1, -1))
        if rot != px:
            raise SystemExit("%s is NOT the 180-degree rotation of %s" % (args[0], args[3]))
        print("ppm2png: %s == rot180(%s)" % (args[0], args[3]))
    print("ppm2png: %s -> %s (%dx%d)" % (args[0], args[1], w, h))


if __name__ == "__main__":
    main()
