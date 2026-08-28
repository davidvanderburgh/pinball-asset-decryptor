#!/usr/bin/env python3
"""lcdframe.py <game> - pull the TV the game itself draws around the clip.

Item 83. The villain scene (the same bundle that owns the 137.asset clips)
carries the artwork for the physical set as inline BC1/BC3 textures: a
wood-cased TV with knobs, an antenna, and four frames of TV static. The
TV texture has a TRANSPARENT SCREEN HOLE - the video shows through it -
which is exactly what the panel needs to stop drawing a hand-made cabinet
and start showing the machine's own.

Writes, once, to <PAD_TABLES>/<game>/lcd/:

    tvframe.png   the TV, RGBA, screen hole transparent
    tvframe.txt   "x y w h" - the hole, so the panel knows where the
                  picture goes without re-deriving it every run

WHY THE HOLE IS FOUND BY FLOOD FILL. These textures are sprites on a
transparent background, so "transparent" alone selects the OUTSIDE as well
as the screen; a plain alpha bounding box returns the whole image and is
how the first attempt at this silently found nothing. Filling inward from
the border marks the exterior, and what is left transparent is interior -
the screen. The TV is then simply the candidate with the largest interior
hole.

Nothing here invents artwork: every pixel is the card's own, and if no
texture qualifies the file is not written and the panel keeps its drawn
cabinet.
"""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import padpath

SCENE_GLOB = "~/card/*/%s/assets/lcd/auto_loaded/*/scene.radium"
#: Only sprites that could plausibly BE the set. Below this a "hole" is a
#: letterform counter or a highlight; above it the texture is a full-screen
#: background whose transparent middle means nothing.
MIN_W, MAX_W = 150, 600
MIN_HOLE_FRAC = 0.15

#: The app owns the radium texture format; importing it keeps ONE decoder.
#: The rig scripts normally avoid depending on the app package (they run
#: inside WSL against the card), so this import is guarded and its failure
#: is a clean skip rather than a traceback - the panel just keeps drawing
#: its own cabinet.
APP = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def _app_bits():
    if APP not in sys.path:
        sys.path.insert(0, APP)
    from pinball_decryptor.plugins.stern.engine import parse_radium_images
    from pinball_decryptor.plugins.stern import dds
    return parse_radium_images, dds


def interior_hole(img):
    """(box, area) of the largest transparent region NOT touching the
    border, or None. See the module docstring for why the border matters."""
    w, h = img.size
    a = img.split()[3].load()
    seen = bytearray(w * h)
    q = deque()

    def push(x, y):
        if a[x, y] < 8 and not seen[y * w + x]:
            seen[y * w + x] = 1
            q.append((x, y))

    for x in range(w):
        push(x, 0)
        push(x, h - 1)
    for y in range(h):
        push(0, y)
        push(w - 1, y)
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h:
                push(nx, ny)
    xs, ys, n = [], [], 0
    for y in range(h):
        row = y * w
        for x in range(w):
            if a[x, y] < 8 and not seen[row + x]:
                xs.append(x)
                ys.append(y)
                n += 1
    if not n:
        return None
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1), n


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: lcdframe.py <game>")
    game = sys.argv[1]
    out_dir = os.path.join(padpath.tables() or "", game, "lcd")
    png = os.path.join(out_dir, "tvframe.png")
    txt = os.path.join(out_dir, "tvframe.txt")
    if os.path.isfile(png) and os.path.isfile(txt):
        print(png)
        return 0

    import glob
    hits = glob.glob(os.path.expanduser(SCENE_GLOB % game))
    if not hits:
        print("lcdframe.py: no scene.radium (card not mounted?)",
              file=sys.stderr)
        return 1
    try:
        parse_radium_images, dds = _app_bits()
        from PIL import Image
    except Exception as e:                       # app not importable here
        print("lcdframe.py: %s" % e, file=sys.stderr)
        return 1

    best = None
    for path in hits:
        with open(path, "rb") as f:
            data = f.read()
        for im in parse_radium_images(data):
            if not (MIN_W <= im["disp_w"] <= MAX_W):
                continue
            raw = data[im["data_off"]:im["data_off"] + im["length"]]
            try:
                dec = dds.decode_bc3 if im["fmt"] == 5 else dds.decode_bc1
                px = dec(raw, im["pad_w"], im["pad_h"])
                img = Image.frombytes(
                    "RGBA", (im["pad_w"], im["pad_h"]), bytes(px)
                ).crop((0, 0, im["disp_w"], im["disp_h"]))
            except Exception:
                continue
            r = interior_hole(img)
            if not r:
                continue
            box, n = r
            if n < MIN_HOLE_FRAC * im["disp_w"] * im["disp_h"]:
                continue
            if best is None or n > best[0]:
                best = (n, img, box)
    if best is None:
        print("lcdframe.py: no texture with a screen hole", file=sys.stderr)
        return 1

    n, img, box = best
    os.makedirs(out_dir, exist_ok=True)
    tmp = png + ".tmp"                  # atomic, like every artifact here
    img.save(tmp, format="PNG")         # ...which .tmp hides from PIL
    os.replace(tmp, png)
    with open(txt + ".tmp", "w", encoding="utf8") as f:
        f.write("%d %d %d %d\n" % (box[0], box[1],
                                   box[2] - box[0], box[3] - box[1]))
    os.replace(txt + ".tmp", txt)
    print("%s (%dx%d, screen %s)" % (png, img.width, img.height, box))
    return 0


if __name__ == "__main__":
    sys.exit(main())
