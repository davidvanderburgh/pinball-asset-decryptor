"""PAD-1515 proof: the game drew its own parts where title.cfg's screen_move put them.
    python verify_screen.py <unmoved frame.png> <moved frame.png> <moved census.json> <title.cfg>
For each screen_move: the part's pixels in the unmoved frame (its census box, where the game draws
it), scaled by its scale, are searched for in the moved frame around where the layout editor shows it
(plugins/jjp/screen_layout.py: the box's centre moved by dx dy, its size times the scale): the best
match must be within 4 px of there, and match well (correlation >= 0.6).  For each screen_hide: the
part's spot must have changed outright (0.3 % of its box or more; a still HUD changes 0 %).  rc 0 = all of them.
"""
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "..")))
from pinball_decryptor.plugins.jjp import screen_layout as SL  # noqa: E402


def gray(img):
    return np.asarray(img.convert("L")).astype(float)


def ncc(a, b):
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d else 0.0


def main():
    unmoved, moved = Image.open(sys.argv[1]), Image.open(sys.argv[2])
    census = SL.read_census(sys.argv[3])
    title = {}
    for line in open(sys.argv[4], encoding="utf-8"):
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = [t.strip() for t in line.split("=", 1)]
            title[k] = title[k] + "\n" + v if k in title else v
    W, H = census["size"]
    boxes, rects = {}, {}
    for p in census["parts"]:                         # each name's biggest box, and its pieces (each draw's box)
        b = p["box"]
        if p["name"] not in boxes or b[2] * b[3] > boxes[p["name"]][2] * boxes[p["name"]][3]:
            boxes[p["name"]] = b
            rects[p["name"]] = [r for r in (p.get("rects") or [b]) if r[2] >= 8 and r[3] >= 8] or [b]
    bad = 0
    G = gray(moved)
    for name, mv in SL.screen_lines(title).items():
        o = boxes.get(name)
        if not o:
            print("%-26s not drawn on this screen" % name)
            bad += 1
            continue
        if mv["hide"]:                                # the piece that changed most: it is gone
            diff = 0.0
            for r in rects[name]:
                a = gray(unmoved.crop((int(r[0]), int(r[1]), int(r[0] + r[2]), int(r[1] + r[3]))))
                b = gray(moved.crop((int(r[0]), int(r[1]), int(r[0] + r[2]), int(r[1] + r[3]))))
                diff = max(diff, float((abs(a - b) > 40).mean() * 100))
            # what it drew is gone: a share of its box changed outright (by 40 levels or more). Wonka's HUD is
            # still: between two unmoved frames 4 s apart the same spot changed 0.00 % (2026-11-23)
            ok = diff >= 0.3
            bad += not ok
            print("%-26s hidden: %.1f%% of its box changed outright  %s" % (name, diff, "ok" if ok else "NOT HIDDEN"))
            continue
        sc = mv["scale"]
        # its biggest piece, about the part's centre: where the editor shows it
        r = max(rects[name], key=lambda q: q[2] * q[3])
        ocx, ocy = o[0] + o[2] / 2, o[1] + o[3] / 2
        o = r
        crop = unmoved.crop((int(o[0]), int(o[1]), int(o[0] + o[2]), int(o[1] + o[3])))
        tw, th = max(4, int(round(o[2] * sc))), max(4, int(round(o[3] * sc)))
        T = gray(crop.resize((tw, th), Image.BILINEAR))
        cx = ocx + (o[0] + o[2] / 2 - ocx) * sc + mv["dx"] * W / 100
        cy = ocy + (o[1] + o[3] / 2 - ocy) * sc + mv["dy"] * H / 100
        ex, ey = int(round(cx - tw / 2)), int(round(cy - th / 2))       # where the editor shows it
        best = (-2.0, 0, 0)
        for dy in range(-12, 13):
            for dx in range(-12, 13):
                x, y = ex + dx, ey + dy
                if x < 0 or y < 0 or x + tw > G.shape[1] or y + th > G.shape[0]:
                    continue
                c = ncc(T, G[y:y + th, x:x + tw])
                if c > best[0]:
                    best = (c, dx, dy)
        c, dx, dy = best
        ok = c >= 0.6 and abs(dx) <= 4 and abs(dy) <= 4
        bad += not ok
        print("%-26s moved %+.2f%% %+.2f%% x%.3g: found %+d,%+d px from the editor's place, match %.2f  %s"
              % (name, mv["dx"], mv["dy"], sc, dx, dy, c, "ok" if ok else "DIFFERS"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
