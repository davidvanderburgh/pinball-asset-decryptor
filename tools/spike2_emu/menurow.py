#!/usr/bin/env python3
"""menurow.py <frame.png> - is this frame the game's Guided Setup / operator menu, and is its
LAST row (Save & Exit) the selected one?

Prints one line:
    menu last=yes     a menu, and the red (selected) row is the bottom row of text
    menu last=no      a menu, the red row is higher up
    none              not a menu (attract, a game, a video)

The menu (Guided Setup on a first boot, the operator menu) is white text, one row per setting
down the left third, the SELECTED row drawn in a colour, and "Save & Exit" last. Two themes, both
measured on first boots 2026-09-24: a dark screen with the row RED (Avengers, Guardians, Iron
Maiden, Mando, Stranger Things, Sword of Rage) and a red screen with the row CYAN (Jaws, James
Bond, Jurassic Park, King Kong). PLUS moves the row down, MINUS up, and SELECT on the last row
saves the settings and goes to attract. The rows sit 1-2 px apart, so they are not
counted: all this asks is where the red row is and whether any text is below it. cyanrow.py is the
same idea for menus drawn in cyan.

Frames are glshot.sh's stored-deflate RGB8 PNGs, read as cyanrow.py reads them.
"""
import struct
import sys
import zlib


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
    return w, h, [raw[y * (stride + 1) + 1:y * (stride + 1) + 1 + stride] for y in range(h)]


def classify(path):
    """None (not a menu), or True / False: the selected row is the last one."""
    w, h, rows = read_png(path)
    # the rows' labels start at the left edge (x ~ 20 of 1360) and run 200-600 px: only the left
    # fifth is read, so centred text (the Insider Connected QR prompt) and logos do not count
    x_end = int(w * 0.2) * 3
    red_lines, light_lines = [], []
    for y in range(int(h * 0.2), h):
        r = rows[y]
        red = light = 0
        for x in range(0, x_end, 3):
            R, G, B = r[x], r[x + 1], r[x + 2]
            if (R > 190 and G < 90 and B < 90) or (R < 90 and G > 190 and B > 190):
                red += 1                               # the selected row: red, or cyan
            elif R > 200 and G > 200 and B > 200:
                light += 1
        if red >= 6:
            red_lines.append(y)
        elif light >= 6:
            light_lines.append(y)
    runs, cur = [], None                          # runs of red scanlines, gaps up to 3 lines
    for y in red_lines:
        if cur is None or y - cur[1] > 3:
            cur = [y, y]
            runs.append(cur)
        cur[1] = y
    runs = [r for r in runs if r[1] - r[0] >= 20]          # a row of text, not a speck
    if len(runs) != 1 or len(light_lines) < 150:       # a menu has several white rows
        return None
    return not any(y > runs[0][1] + 12 for y in light_lines)


def main():
    got = classify(sys.argv[1])
    print("none" if got is None else "menu last=%s" % ("yes" if got else "no"))
    return 0 if got is not None else 1


if __name__ == "__main__":
    sys.exit(main())
