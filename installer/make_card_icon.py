"""Draw the icon Explorer shows on a card image PAD opens
(pinball_decryptor/card_image.ico + card_image.png).

    python installer/make_card_icon.py

A file is not the app: with the app's own icon on every .raw, a desktop of
card images read as a row of PAD shortcuts (PAD-1518).  This is an SD card
(pale body, cut corner, gold contacts) carrying the app's tile as a badge,
the way a document icon carries its program's.  Needs Pillow.
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "..", "pinball_decryptor")
APP_PNG = os.path.join(PKG, "icon.png")
OUT_PNG = os.path.join(PKG, "card_image.png")
OUT_ICO = os.path.join(PKG, "card_image.ico")

S = 1024                              # drawn big, shrunk for smooth edges
BODY = (226, 230, 238, 255)
BODY_EDGE = (120, 130, 150, 255)
LABEL = (27, 30, 46, 255)             # the app tile's navy
GOLD = (222, 176, 72, 255)
GOLD_EDGE = (150, 112, 30, 255)


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


def main():
    big = card()
    big.resize((256, 256), Image.LANCZOS).save(OUT_PNG)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    big.resize((256, 256), Image.LANCZOS).save(
        OUT_ICO, sizes=[(s, s) for s in sizes])
    print("wrote %s and %s" % (OUT_PNG, OUT_ICO))


if __name__ == "__main__":
    main()
