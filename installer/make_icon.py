"""Regenerate the app icon (pinball_decryptor/icon.png + icon.ico).

The artwork (rounded tile, metallic pinball, red flippers, dark gradient) is kept
as-is from the existing icon.png; only the top wordmark is redrawn.  Run after
changing WORDMARK below:  python installer/make_icon.py

Needs Pillow.  The macOS/Linux builds derive their .icns / hicolor PNGs from
icon.png, and the Windows installer + window use icon.ico, so regenerating these
two files updates every platform.
"""
import os

from PIL import Image, ImageDraw, ImageFont

WORDMARK = "PAD"                     # was "PB" (Pinball Brothers); now Pinball Asset Decryptor
HERE = os.path.dirname(os.path.abspath(__file__))
ICON_PNG = os.path.join(HERE, "..", "pinball_decryptor", "icon.png")
ICON_ICO = os.path.join(HERE, "..", "pinball_decryptor", "icon.ico")

# Text band + style measured from the original "PB" wordmark.
BAND_TOP, BAND_BOT = 13, 49         # rows the old wordmark occupied (inclusive-ish)
TEXT_CY = 31                        # vertical centre of the wordmark
BG_TOP = (27, 30, 46)              # background just above the band (y=12)
BG_BOT = (24, 28, 42)              # background just below the band (y=49)
TEXT_RGB = (245, 230, 220)         # cream, matched to the original
SHADOW_RGB = (10, 12, 20)


def _font(px):
    """A bold serif close to the original slab wordmark, with fallbacks."""
    for name in ("georgiab.ttf", "timesbd.ttf", "Georgia_Bold.ttf",
                 "DejaVuSerif-Bold.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def _erase_band(im):
    """Repaint the wordmark band with the (horizontally-uniform) vertical
    background gradient, preserving the original alpha so the rounded corners
    stay intact."""
    px = im.load()
    W = im.width
    span = max(1, BAND_BOT - BAND_TOP)
    for y in range(BAND_TOP, BAND_BOT + 1):
        t = (y - BAND_TOP) / span
        bg = tuple(int(round(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t)) for i in range(3))
        for x in range(W):
            a = px[x, y][3]
            if a:                           # inside the tile -> repaint background
                px[x, y] = (bg[0], bg[1], bg[2], a)


def _fit_font(text, max_w, max_h):
    """Largest font whose rendered text fits max_w x max_h."""
    size = max_h + 8
    while size > 8:
        f = _font(size)
        l, t, r, b = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), text, font=f)
        if (r - l) <= max_w and (b - t) <= max_h:
            return f, (r - l, b - t, l, t)
        size -= 1
    f = _font(12)
    l, t, r, b = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), text, font=f)
    return f, (r - l, b - t, l, t)


def main():
    im = Image.open(ICON_PNG).convert("RGBA")
    W, H = im.size
    _erase_band(im)

    # Draw the new wordmark centred where the old one was, sized to the icon.
    f, (tw, th, ox, oy) = _fit_font(WORDMARK, int(W * 0.78), BAND_BOT - BAND_TOP + 6)
    cx = W // 2
    tx = cx - tw // 2 - ox
    ty = TEXT_CY - th // 2 - oy
    txt = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(txt)
    d.text((tx + 2, ty + 2), WORDMARK, font=f, fill=SHADOW_RGB + (150,))   # drop shadow
    d.text((tx, ty), WORDMARK, font=f, fill=TEXT_RGB + (255,))
    im = Image.alpha_composite(im, txt)

    im.save(ICON_PNG)
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    im.save(ICON_ICO, sizes=sizes)
    print("wrote %s and %s with wordmark %r" % (ICON_PNG, ICON_ICO, WORDMARK))


if __name__ == "__main__":
    main()
