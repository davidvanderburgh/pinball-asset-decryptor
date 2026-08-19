#!/usr/bin/env python3
"""Decode an X11 ``xwd`` dump of the game window into a PNG.

WHY THIS EXISTS.  Under WSLg each X window is its own *Windows* window (RAIL);
the X root is never composited.  So ``ffmpeg -f x11grab -i :0`` returns a blank
frame even while the game is drawing perfectly - it grabs the empty root, not
the game.  The only reliable capture is ``xwd -id <window>`` on the game's own
window id, and the game image ships no converter, hence this.

Finding the window id needs ``xwininfo -root -TREE``, not ``-children``: the
game's window is a GRANDchild of the root (Weston nests it one level down), so
a depth-1 listing shows only Weston's own windows and reads as "no window".
That cost an hour on 2026-08-19 and a wrong conclusion in a status report.

Writes PNG with nothing but the standard library - the rig must not need pip.
"""

import pathlib
import struct
import sys
import zlib


def decode_xwd(data, step=1):
    """Return (width, height, list-of-RGB-rows) from xwd file bytes.

    ``step`` downsamples by simple decimation: a 3840x2160 frame is 33 MB and
    unreadable in a terminal-adjacent workflow; step=4 gives a 960x540 preview.
    """
    if len(data) < 100:
        raise ValueError("not an xwd file (too short)")
    h = struct.unpack(">25I", data[:100])
    hdr_sz, ver, _fmt, depth, w, hgt = h[0], h[1], h[2], h[3], h[4], h[5]
    bpp, bpl, ncolors = h[11], h[12], h[19]
    if ver != 7:
        raise ValueError(f"unsupported xwd version {ver}")
    if bpp != 32 or depth != 24:
        raise ValueError(f"expected 24-bit depth in 32bpp, got depth={depth} bpp={bpp}")

    off = hdr_sz + ncolors * 12
    px = data[off:]
    if len(px) < bpl * hgt:
        raise ValueError(f"truncated pixels: {len(px)} < {bpl * hgt}")

    ow, oh = w // step, hgt // step
    rows = []
    for y in range(oh):
        base = (y * step) * bpl
        row = bytearray()
        for x in range(ow):
            i = base + (x * step) * 4
            # X stores these little-endian as B,G,R,X.
            row += bytes((px[i + 2], px[i + 1], px[i]))
        rows.append(bytes(row))
    return ow, oh, rows


def write_png(path, w, h, rows):
    raw = b"".join(b"\x00" + r for r in rows)          # filter byte 0 per row

    def chunk(tag, payload):
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6))
           + chunk(b"IEND", b""))
    pathlib.Path(path).write_bytes(png)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        print("usage: shot.py <in.xwd> [out.png] [step]", file=sys.stderr)
        return 64
    src = argv[1]
    dst = argv[2] if len(argv) > 2 else src.rsplit(".", 1)[0] + ".png"
    step = int(argv[3]) if len(argv) > 3 else 4

    w, h, rows = decode_xwd(pathlib.Path(src).read_bytes(), step)
    write_png(dst, w, h, rows)

    # A blank grab is the failure this tool is most likely to hit, and a silent
    # black PNG reads like success - so always say how much of the frame is lit.
    lit = sum(1 for r in rows for i in range(0, len(r), 3) if r[i] or r[i + 1] or r[i + 2])
    total = w * h
    print(f"{dst}: {w}x{h}, {100 * lit / total:.1f}% non-black")
    if lit == 0:
        print("  WARNING: frame is entirely black - grabbed the root window?", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
