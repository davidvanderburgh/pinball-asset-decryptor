"""Draw the icons Explorer shows on a card image PAD opens
(pinball_decryptor/card_image.ico + card_image.png, and
card_image_compact.ico + card_image_compact.png for a card stored compact).

    python installer/make_card_icon.py

A file is not the app: with the app's own icon on every .raw, a desktop of
card images read as a row of PAD shortcuts (PAD-1518).  This is an SD card
(pale body, cut corner, gold contacts) carrying the app's tile as a badge,
the way a document icon carries its program's.  A card stored compact
(PAD-1522) is the same card with a green "squeezed" badge on its corner, so
a folder of cards shows at a glance which ones are already compact.  Needs
Pillow.
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "..", "pinball_decryptor")
APP_PNG = os.path.join(PKG, "icon.png")
OUT_PNG = os.path.join(PKG, "card_image.png")
OUT_ICO = os.path.join(PKG, "card_image.ico")
OUT_COMPACT_PNG = os.path.join(PKG, "card_image_compact.png")
OUT_COMPACT_ICO = os.path.join(PKG, "card_image_compact.ico")

S = 1024                              # drawn big, shrunk for smooth edges
BODY = (226, 230, 238, 255)
BODY_EDGE = (120, 130, 150, 255)
LABEL = (27, 30, 46, 255)             # the app tile's navy
GOLD = (222, 176, 72, 255)
GOLD_EDGE = (150, 112, 30, 255)
BADGE = (34, 160, 84, 255)            # "compact": green, white ring
BADGE_RING = (255, 255, 255, 255)
BADGE_MARK = (255, 255, 255, 255)


def card(size=S):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    u = size / 1024.0
    left, right, top, bot = 172 * u, 852 * u, 40 * u, 984 * u
    cut = 190 * u                     # the SD card's cut corner, top right
    r = 56 * u
    edge = int(round(20 * u))
    shape = [(left + r, top), (right - cut, top), (right, top + cut),
             (right, bot - r), (right - r, bot), (left + r, bot),
             (left, bot - r), (left, top + r)]
    d.polygon(shape, fill=BODY)
    for cx, cy in ((left + r, top + r), (right - r, bot - r),
                   (left + r, bot - r)):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=BODY)
    d.line(shape + [shape[0]], fill=BODY_EDGE, width=edge, joint="curve")
    for cx, cy, a0, a1 in ((left + r, top + r, 180, 270),
                           (right - r, bot - r, 0, 90),
                           (left + r, bot - r, 90, 180)):
        d.arc([cx - r, cy - r, cx + r, cy + r], a0, a1, fill=BODY_EDGE,
              width=edge)
    # gold contacts along the top, stopping short of the cut corner
    n, gap = 5, 26 * u
    x0, x1 = left + 70 * u, right - cut - 10 * u
    w = (x1 - x0 - gap * (n - 1)) / n
    for i in range(n):
        x = x0 + i * (w + gap)
        d.rounded_rectangle([x, top + 70 * u, x + w, top + 290 * u],
                            radius=18 * u, fill=GOLD, outline=GOLD_EDGE,
                            width=max(1, int(round(8 * u))))
    # the label: the app's own tile
    side = int(round(520 * u))
    tile = Image.open(APP_PNG).convert("RGBA").resize((side, side),
                                                      Image.LANCZOS)
    tx = int(round((left + right) / 2 - side / 2))
    ty = int(round(bot - 70 * u - side))
    im.alpha_composite(tile, (tx, ty))
    return im


def compact_card(size=S):
    """The card with the "compact" badge: a green disc on its lower right
    corner holding two arrowheads squeezing a bar.  Big enough that the 16 px
    icon still shows a green corner."""
    im = card(size)
    d = ImageDraw.Draw(im)
    u = size / 1024.0
    cx, cy, r = 744 * u, 744 * u, 268 * u
    ring = 34 * u
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=BADGE_RING)
    d.ellipse([cx - r + ring, cy - r + ring, cx + r - ring, cy + r - ring],
              fill=BADGE)
    # the squeeze: an arrowhead from above and one from below, a bar between
    w, h, gap, bar = 120 * u, 104 * u, 30 * u, 22 * u
    d.rectangle([cx - w, cy - bar, cx + w, cy + bar], fill=BADGE_MARK)
    d.polygon([(cx - w, cy - gap - bar - h), (cx + w, cy - gap - bar - h),
               (cx, cy - gap - bar)], fill=BADGE_MARK)
    d.polygon([(cx - w, cy + gap + bar + h), (cx + w, cy + gap + bar + h),
               (cx, cy + gap + bar)], fill=BADGE_MARK)
    return im


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    for big, png, ico in ((card(), OUT_PNG, OUT_ICO),
                          (compact_card(), OUT_COMPACT_PNG, OUT_COMPACT_ICO)):
        big.resize((256, 256), Image.LANCZOS).save(png)
        big.resize((256, 256), Image.LANCZOS).save(
            ico, sizes=[(s, s) for s in sizes])
        print("wrote %s and %s" % (png, ico))


if __name__ == "__main__":
    main()
