#!/usr/bin/env python3
"""bandmeasure.py - item 43: is the service-menu band a SQUASH or a CROP?

The two readings look identical by eye and are different faults:

  CROP   - the video is drawn at full scale and only its middle is visible.
           Fix would live in whatever clips it.
  SQUASH - the whole frame is drawn into a short quad.
           Fix lives in whatever chose that quad's height.

The discriminator is that `menu_page1_good.png` and `menu_deep_broken.png`
are THE SAME CLIP - the scrolling, tiled Stern-logo backdrop - one drawn full
size and one drawn in the band. The logo tile is therefore a RULER that does
not care which frame of the scroll was caught. Compare the artwork's VERTICAL
scale against the band's fraction of the screen:

  vertical scale ~= 1.0            => CROP   (full-size artwork, less of it)
  vertical scale ~= band fraction  => SQUASH (all the artwork, compressed)

Measuring the horizontal extent is not decoration, it is the CONTROL: the band
is full width, so horizontal scale MUST come back 1.0 either way. If it does
not, the two images are not the same artwork and none of the rest means
anything.

TWO WAYS THIS MEASUREMENT WAS WRONG BEFORE IT WAS RIGHT, both recorded so the
next reader does not repeat them:

  * COUNTING TILE ROWS does not work. The central logo's red region SPLITS in
    two where the chrome ball and the white outline cross it, so a naive run
    finder reads 4 tiles in the good image and 3 in the band and calls a squash
    a crop - which is exactly what the first version of this script did. Runs
    are merged across small gaps now.
  * TILE HEIGHT does not work either, because the top and bottom tiles are cut
    by the edge of the picture and a cut tile is short for a reason that has
    nothing to do with scale. The SPACING between consecutive tile starts is
    what survives cutting, so that is the ruler - and a tile whose start sits
    on the band edge is dropped, because its real start is off-picture.

Run it against the captures:

    python bandmeasure.py C:/tmp/item41/menu_page1_good.png \
                          C:/tmp/item41/menu_deep_broken.png

Measured 2026-08-11, and this is what the queue entry records:
  good   content rows 64..880, central logo 326 px wide, 81 rows tall, 3 tiles
  broken band    rows 292..653, central logo 329 px wide, 38 rows tall, 3 tiles
  => horizontal 1.00, vertical ~0.46, same tile count = SQUASH.
  Back through the letterbox (window 1445x827, fb 1360x768 -> 816 screen rows)
  the band is fb rows ~215..554: height 340 of 768, and 1360/340 = 4.007.
"""
import sys

try:
    from PIL import Image
except ImportError:                                  # pragma: no cover
    sys.exit("bandmeasure.py needs Pillow: pip install pillow")

# The window furniture in these captures, so the border does not get counted as
# content. Measured off the frame colour (luminance 191) rather than guessed.
BORDER_L, BORDER_R = 37, 1483
TITLE_BOT, FRAME_TOP = 58, 886


def lum(px):
    r, g, b = px
    return (r * 299 + g * 587 + b * 114) / 1000.0


def is_logo_red(px):
    """The Stern logo is dark red on near-black grey. Menu text is white or
    green and the QR code is black and white, so a red-dominance test picks out
    the backdrop and nothing else on these two screens."""
    r, g, b = px
    return r > 55 and r - g > 22 and r - b > 22


def runs(vals, lo, hi, thresh, minlen, merge=0):
    out, start, inrun = [], lo, False
    for i in range(lo, hi):
        if vals[i] > thresh and not inrun:
            start, inrun = i, True
        elif vals[i] <= thresh and inrun:
            if i - start >= minlen:
                out.append((start, i - 1))
            inrun = False
    if inrun and hi - start >= minlen:
        out.append((start, hi - 1))
    if merge:
        joined = []
        for a, b in out:
            if joined and a - joined[-1][1] <= merge:
                joined[-1] = (joined[-1][0], b)
            else:
                joined.append((a, b))
        out = joined
    return out


def median(xs):
    xs = sorted(xs)
    if not xs:
        return 0.0
    m = len(xs) // 2
    return float(xs[m]) if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2.0


def tile_pitch(tiles, band):
    """Spacing between consecutive tile starts, ignoring any tile whose start
    sits on the edge of the picture - that one begins off-screen and its start
    is the edge, not the tile."""
    starts = [a for a, b in tiles if a > band[0] + 2]
    if len(starts) < 2:
        return 0.0
    return median([starts[i + 1] - starts[i] for i in range(len(starts) - 1)])


def measure(path):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    px = im.load()

    # 1. The lit band: rows inside the client area that are not black.
    rows_l = [
        sum(lum(px[x, y]) for x in range(BORDER_L + 4, BORDER_R - 4, 7))
        / len(range(BORDER_L + 4, BORDER_R - 4, 7))
        for y in range(h)
    ]
    lit = runs(rows_l, TITLE_BOT + 1, FRAME_TOP, 6.0, 8)
    band = max(lit, key=lambda r: r[1] - r[0]) if lit else (0, 0)

    # 2. The logo ruler, measured only inside that band.
    red_rows = [
        sum(1 for x in range(BORDER_L, BORDER_R) if is_logo_red(px[x, y]))
        for y in range(h)
    ]
    red_cols = [
        sum(1 for y in range(band[0], band[1] + 1) if is_logo_red(px[x, y]))
        for x in range(w)
    ]
    # merge=24: the ball and the white outline cut the logo's red into pieces,
    # and a piece is not a tile. See the header.
    tiles = runs(red_rows, band[0], band[1] + 1, 12, 8, merge=24)
    cols = runs(red_cols, BORDER_L, BORDER_R, 8, 8)

    # The central logo: the widest cluster of red columns, joined across the
    # gaps the white outline and the ball cut into the script.
    span = (cols[0][0], cols[-1][1]) if cols else (0, 0)
    mid = [c for c in cols if 400 < c[0] < 1100]
    central = (mid[0][0], mid[-1][1]) if mid else span

    pitch = tile_pitch(tiles, band)
    print(f"\n=== {path}  {w}x{h} ===")
    print(f"  content band rows {band[0]}..{band[1]}   height {band[1]-band[0]+1}")
    print(f"  logo tile rows    {len(tiles)}: "
          + ", ".join(f"{a}..{b}({b-a+1})" for a, b in tiles))
    print(f"  tile pitch        {pitch:.1f} rows   (the vertical ruler)")
    print(f"  central logo      x {central[0]}..{central[1]}  "
          f"width {central[1]-central[0]+1}")
    return band, pitch, central


def main(paths):
    seen = [measure(p) for p in paths]
    if len(seen) != 2:
        return
    (b0, p0, c0), (b1, p1, c1) = seen
    hx = (c1[1] - c1[0] + 1) / max(1, c0[1] - c0[0] + 1)
    vy = p1 / p0 if p0 else 0.0
    frac = (b1[1] - b1[0] + 1) / max(1, b0[1] - b0[0] + 1)
    print("\n--- verdict ---")
    print(f"  horizontal scale (the control) : {hx:.3f}")
    print(f"  vertical scale of the artwork  : {vy:.3f}")
    print(f"  band as a fraction of the screen: {frac:.3f}")
    if abs(hx - 1.0) > 0.05:
        print("  CONTROL FAILED: not the same artwork at the same width, so")
        print("  nothing below this line can be trusted.")
    elif abs(vy - frac) < 0.06:
        print("  SQUASH: the artwork shrank by the same factor the band did,")
        print("  so the WHOLE frame is in the band, vertically compressed.")
    elif abs(vy - 1.0) < 0.06:
        print("  CROP: the artwork is still full size, so the band shows")
        print("  only part of the frame.")
    else:
        print("  NEITHER cleanly - do not report a verdict from this.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
