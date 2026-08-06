#!/usr/bin/env python3
"""framewidth.py - recover the width the bytes behind a captured frame were
WRITTEN at, regardless of the width they were READ at.

    py tools/spike2_emu/framewidth.py C:\\tmp\\spike2_item6\\inset_native.png
    py tools/spike2_emu/framewidth.py --refold 1360 shot.png out.png

WHY THIS EXISTS. Item 6 spent five passes describing the pink/green TV inset
with adjectives - "horizontal noise", "a function of y", "no surviving
structure" - and every one of those is a statement about the PICTURE. The
question that mattered was about the BYTES: a raster read at the wrong width is
still a raster, so fold the stream back at the right width and the picture
returns. That turned four passes of argument into one number: 1360.

HOW. Undo the converter (i420.h is BT.601 limited range, and its inverse is
well conditioned wherever the forward direction did not saturate) to get the Y
bytes back, then fold the flat stream at every candidate width and score
vertical smoothness. Vertically adjacent samples of a real raster are similar
at the true width and unrelated at any other, so the true width is a sharp
minimum.

THE CONTROL IS NOT OPTIONAL. Three metrics on this item scored the CONTENT
instead of the DEFECT and ranked a known-good capture below a known-bad one. So
every score here is printed beside the same stream SHUFFLED and folded the same
way: a width that does not beat its own shuffled control has found nothing. On
the item-6 capture that reads 2.02 against 23.84 at width 1360, and 22.34
against 23.80 at width 520 - the read width is no better than noise.

VALIDATE IT BEFORE YOU BELIEVE IT. Run it on a frame you have the ground truth
for first (`vidcheck.py` renders one); it must return that frame's real width.

CAVEAT: a capture whose colours SATURATE cannot be inverted - the control
render of "a 1360x768 frame read as 520x294" comes out 89-100% green with red
and blue clamped at 0, and its recovered Y is meaningless. Saturation is
reported so this is visible rather than silent.
"""
import sys

import numpy as np
from PIL import Image


def y_plane(path):
    """Recover the Y bytes, and say how much of the image was saturated."""
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.float64)
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    sat = float(((R <= 0) | (R >= 255) | (B <= 0) | (B >= 255)).mean())
    Y = 16.0 + (65.738 * R + 129.057 * G + 25.064 * B) / 256.0
    return Y, sat


def fold_score(flat, w):
    rows = len(flat) // w
    if rows < 8:
        return None
    img = flat[:rows * w].reshape(rows, w)
    return float(np.abs(img[1:] - img[:-1]).mean())


def refold(path, w, out):
    Y, _ = y_plane(path)
    flat = Y.ravel()
    rows = len(flat) // w
    img = np.clip(flat[:rows * w].reshape(rows, w), 0, 255).astype(np.uint8)
    Image.fromarray(img, "L").save(out)
    print("refolded %d bytes at width %d -> %dx%d  %s" % (len(flat), w, w, rows, out))


def report(path, lo=64, hi=2400):
    Y, sat = y_plane(path)
    h, w = Y.shape
    flat = Y.ravel()
    control = np.random.default_rng(7).permutation(flat)
    print("\n=== %s ===" % path)
    print("read as %dx%d, %.1f%% of pixels saturated%s"
          % (w, h, sat * 100.0,
             "  ** too much to invert; treat the numbers below as junk **"
             if sat > 0.25 else ""))
    scored = [(fold_score(flat, cw), cw) for cw in range(lo, hi + 1)]
    scored = [s for s in scored if s[0] is not None]
    scored.sort()
    best_s, best_w = scored[0]
    ctrl = fold_score(control, best_w)
    print("TRUE WIDTH: %d   (score %.2f, shuffled control %.2f)" % (best_w, best_s, ctrl))
    if ctrl and best_s > 0.5 * ctrl:
        print("  ...but it does not beat its own control. No raster structure here.")
    print("runners-up: %s"
          % "  ".join("%d:%.2f" % (cw, s) for s, cw in scored[1:12]
                      if abs(cw - best_w) > 8)[:200])
    if w and best_w != w:
        print("READ WIDTH %d scores %.2f (control %.2f) - %s"
              % (w, fold_score(flat, w), fold_score(control, w),
                 "no better than noise" if fold_score(flat, w) > 0.5 * fold_score(control, w)
                 else "some structure"))


def main(argv):
    if len(argv) > 3 and argv[1] == "--refold":
        refold(argv[3], int(argv[2]), argv[4])
        return 0
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    for p in argv[1:]:
        report(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
