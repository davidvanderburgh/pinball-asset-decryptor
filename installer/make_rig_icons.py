"""Regenerate the Spike 2 rig's window icons.

Two windows the emulator opens beside the app used to borrow an icon: the
virtual playfield took the app's own (so the taskbar showed two PAD buttons
nobody could tell apart), and the game's screen - an X window from
padglhost, shown on the Windows desktop by WSLg - set none, so WSLg drew its
Linux penguin. Each gets its own picture now, in the app icon's family (the
same rounded dark tile) but with a different subject and colour, so the three
buttons read apart at taskbar size:

  * playfield - a top-down playfield: green board, three pop bumpers, yellow
    flippers, a silver ball.
  * gamewin   - the backbox: a lit screen over two speakers.

Writes, all derived from the drawing code below:

  tools/spike2_emu/icons/playfield.ico   the pywebview window (Windows)
  tools/spike2_emu/icons/playfield.png   GTK window + app-mode favicon
  tools/spike2_emu/icons/gamewin.png     the game window's picture, for reference
  tools/spike2_emu/padicon.h             the game window's _NET_WM_ICON, as C

Run after changing a drawing:  python installer/make_rig_icons.py
Needs Pillow.
"""
import os

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.normpath(os.path.join(HERE, "..", "tools", "spike2_emu"))
OUT = os.path.join(RIG, "icons")

M = 1024                        # master size; every output is downsampled
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
#: _NET_WM_ICON sizes, LARGEST FIRST. WSLg hands the largest to Windows;
#: a Linux desktop's window manager picks whichever fits its slot.
X_SIZES = [64, 48, 32, 16]


def _px(v):
    return int(round(v * M))


def _box(x0, y0, x1, y1):
    return [_px(x0), _px(y0), _px(x1), _px(y1)]


def _vgrad(size, top, bot, y0=0, y1=None):
    """A size[0] x size[1] RGBA image graded top -> bot between rows y0 and
    y1, flat above and below."""
    w, h = size
    y1 = h - 1 if y1 is None else y1
    g = Image.new("RGBA", (1, h))
    for y in range(h):
        t = min(1.0, max(0.0, (y - y0) / max(1, y1 - y0)))
        g.putpixel((0, y), tuple(int(round(top[i] + (bot[i] - top[i]) * t))
                                 for i in range(3)) + (255,))
    return g.resize((w, h))


def _fill(im, mask, top, bot):
    """Paint a vertical gradient through a greyscale mask, top to bottom of
    the shape the mask holds (not of the whole icon)."""
    box = mask.getbbox() or (0, 0, im.width, im.height)
    im.alpha_composite(Image.composite(_vgrad(im.size, top, bot,
                                              box[1], box[3] - 1),
                                       Image.new("RGBA", im.size, (0, 0, 0, 0)),
                                       mask))


def _mask():
    return Image.new("L", (M, M), 0)


def _tile(im):
    """The app icon's rounded dark tile, so the family shows."""
    m = _mask()
    ImageDraw.Draw(m).rounded_rectangle(_box(0.01, 0.01, 0.99, 0.99),
                                        radius=_px(0.17), fill=255)
    _fill(im, m, (34, 38, 56), (14, 16, 26))
    # a hairline rim, lighter at the top, the way the app tile catches light
    rim = _mask()
    ImageDraw.Draw(rim).rounded_rectangle(_box(0.01, 0.01, 0.99, 0.99),
                                          radius=_px(0.17), outline=255,
                                          width=_px(0.008))
    _fill(im, rim, (86, 94, 124), (30, 34, 48))


def _ball(im, cx, cy, r):
    """A chrome ball: dark rim, bright upper-left highlight."""
    m = _mask()
    ImageDraw.Draw(m).ellipse(_box(cx - r, cy - r, cx + r, cy + r), fill=255)
    _fill(im, m, (255, 255, 255), (104, 110, 128))
    hl = _mask()
    hr = r * 0.42
    hx, hy = cx - r * 0.32, cy - r * 0.34
    ImageDraw.Draw(hl).ellipse(_box(hx - hr, hy - hr, hx + hr, hy + hr),
                               fill=200)
    hl = hl.filter(ImageFilter.GaussianBlur(_px(r * 0.25)))
    white = Image.new("RGBA", (M, M), (255, 255, 255, 255))
    im.alpha_composite(Image.composite(white, Image.new("RGBA", (M, M)), hl))


def _capsule(d, p0, p1, r0, r1, fill):
    """A tapered bar from p0 (radius r0) to p1 (radius r1): a flipper."""
    import math
    (x0, y0), (x1, y1) = p0, p1
    ang = math.atan2(y1 - y0, x1 - x0)
    nx, ny = -math.sin(ang), math.cos(ang)
    poly = [(x0 + nx * r0, y0 + ny * r0), (x1 + nx * r1, y1 + ny * r1),
            (x1 - nx * r1, y1 - ny * r1), (x0 - nx * r0, y0 - ny * r0)]
    d.polygon([(_px(x), _px(y)) for x, y in poly], fill=fill)
    d.ellipse(_box(x0 - r0, y0 - r0, x0 + r0, y0 + r0), fill=fill)
    d.ellipse(_box(x1 - r1, y1 - r1, x1 + r1, y1 + r1), fill=fill)


def draw_playfield():
    im = Image.new("RGBA", (M, M), (0, 0, 0, 0))
    _tile(im)
    # the board: portrait, arched top, chrome rail round it
    L, T, R, B = 0.15, 0.06, 0.85, 0.95
    rail = _mask()
    ImageDraw.Draw(rail).rounded_rectangle(_box(L, T, R, B), radius=_px(0.31),
                                           fill=255)
    _fill(im, rail, (214, 220, 232), (120, 126, 142))
    board = _mask()
    ImageDraw.Draw(board).rounded_rectangle(
        _box(L + 0.035, T + 0.035, R - 0.035, B - 0.025), radius=_px(0.28),
        fill=255)
    _fill(im, board, (46, 196, 140), (10, 92, 72))
    d = ImageDraw.Draw(im)
    # inlane / outlane guides down to the flipper pivots
    guide = (220, 236, 230, 255)
    w = _px(0.022)
    d.line([_px(0.235), _px(0.63), _px(0.235), _px(0.77), _px(0.34), _px(0.825)],
           fill=guide, width=w, joint="curve")
    d.line([_px(0.765), _px(0.63), _px(0.765), _px(0.77), _px(0.66), _px(0.825)],
           fill=guide, width=w, joint="curve")
    # three pop bumpers: white skirt, red cap, bright centre
    for cx, cy in ((0.37, 0.27), (0.63, 0.27), (0.50, 0.45)):
        r = 0.098
        d.ellipse(_box(cx - r, cy - r, cx + r, cy + r), fill=(250, 250, 250))
        r2 = 0.072
        d.ellipse(_box(cx - r2, cy - r2, cx + r2, cy + r2), fill=(236, 58, 58))
        r3 = 0.028
        d.ellipse(_box(cx - r3, cy - r3, cx + r3, cy + r3),
                  fill=(255, 196, 196))
    # flippers, yellow (the app's are red), pivots out, tips in
    fl = (255, 208, 48, 255)
    _capsule(d, (0.33, 0.825), (0.465, 0.89), 0.042, 0.023, fl)
    _capsule(d, (0.67, 0.825), (0.535, 0.89), 0.042, 0.023, fl)
    _ball(im, 0.62, 0.64, 0.068)
    return im


def draw_gamewin():
    im = Image.new("RGBA", (M, M), (0, 0, 0, 0))
    _tile(im)
    # the backbox head: a lighter frame round the screen and speaker panel
    head = _mask()
    ImageDraw.Draw(head).rounded_rectangle(_box(0.06, 0.09, 0.94, 0.91),
                                           radius=_px(0.08), fill=255)
    _fill(im, head, (92, 100, 132), (44, 48, 66))
    inner = _mask()
    ImageDraw.Draw(inner).rounded_rectangle(_box(0.09, 0.12, 0.91, 0.88),
                                            radius=_px(0.06), fill=255)
    _fill(im, inner, (22, 24, 36), (12, 13, 20))
    # the screen, 16:9, lit: a sunset the game might be drawing
    sx0, sy0, sx1, sy1 = 0.12, 0.15, 0.88, 0.62
    scr = _mask()
    ImageDraw.Draw(scr).rounded_rectangle(_box(sx0, sy0, sx1, sy1),
                                          radius=_px(0.025), fill=255)
    _fill(im, scr, (255, 70, 150), (255, 176, 52))
    # a glowing sun/ball on the horizon, and a gloss band across the glass
    glow = _mask()
    ImageDraw.Draw(glow).ellipse(_box(0.36, 0.29, 0.64, 0.57), fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(_px(0.03)))
    sun = Image.new("RGBA", (M, M), (255, 246, 196, 255))
    im.alpha_composite(Image.composite(sun, Image.new("RGBA", (M, M)),
                                       Image.composite(glow, _mask(), scr)))
    d = ImageDraw.Draw(im)
    for i, y in enumerate((0.50, 0.54, 0.58)):   # horizon bands
        d.rectangle(_box(sx0, y, sx1, y + 0.012 + i * 0.004),
                    fill=(214, 40, 110, 255))
    gl = _mask()
    ImageDraw.Draw(gl).polygon([(_px(sx0), _px(sy0)), (_px(0.42), _px(sy0)),
                                (_px(0.27), _px(sy1)), (_px(sx0), _px(sy1))],
                               fill=46)
    gl = Image.composite(gl, _mask(), scr)
    white = Image.new("RGBA", (M, M), (255, 255, 255, 255))
    im.alpha_composite(Image.composite(white, Image.new("RGBA", (M, M)), gl))
    # two speakers under the screen, and a lit strip between them
    for cx in (0.27, 0.73):
        cy, r = 0.75, 0.078
        d.ellipse(_box(cx - r, cy - r, cx + r, cy + r), fill=(120, 128, 156))
        r2 = 0.060
        d.ellipse(_box(cx - r2, cy - r2, cx + r2, cy + r2), fill=(28, 30, 44))
        r3 = 0.024
        d.ellipse(_box(cx - r3, cy - r3, cx + r3, cy + r3),
                  fill=(84, 90, 116))
    d.rounded_rectangle(_box(0.42, 0.73, 0.58, 0.77), radius=_px(0.02),
                        fill=(255, 150, 60, 255))
    return im


def _sized(master, n):
    return master.resize((n, n), Image.LANCZOS)


def _c_array(name, img_sizes, master):
    """_NET_WM_ICON data: for each size, width, height, then ARGB rows."""
    words = []
    for n in img_sizes:
        im = _sized(master, n)
        words += [n, n]
        raw = im.tobytes()                              # RGBA, row by row
        for i in range(0, len(raw), 4):
            r, g, b, a = raw[i:i + 4]
            words.append((a << 24) | (r << 16) | (g << 8) | b)
    lines = []
    for i in range(0, len(words), 8):
        lines.append("    " + " ".join("0x%08xu," % w for w in words[i:i + 8]))
    return ("static const unsigned int %s[%d] = {\n%s\n};\n"
            % (name, len(words), "\n".join(lines)))


def main():
    os.makedirs(OUT, exist_ok=True)
    pf = draw_playfield()
    gw = draw_gamewin()

    _sized(pf, 256).save(os.path.join(OUT, "playfield.png"))
    _sized(pf, 256).save(os.path.join(OUT, "playfield.ico"),
                         sizes=[(n, n) for n in ICO_SIZES])
    _sized(gw, 256).save(os.path.join(OUT, "gamewin.png"))

    h = os.path.join(RIG, "padicon.h")
    with open(h, "w", newline="\n") as f:
        f.write("/* GENERATED by installer/make_rig_icons.py - do not edit.\n"
                " *\n"
                " * The game window's own icon, as _NET_WM_ICON wants it: for\n"
                " * each size (largest first) width, height, then width*height\n"
                " * ARGB pixels, row by row. icons/gamewin.png is the same\n"
                " * picture. padglhost.c's win_set_icon() sets it. */\n"
                "#ifndef PADICON_H\n#define PADICON_H\n\n")
        f.write(_c_array("padicon_game", X_SIZES, gw))
        f.write("\n#endif\n")
    print("wrote %s, %s and %s" % (os.path.join(OUT, "playfield.ico"),
                                   os.path.join(OUT, "gamewin.png"), h))
    return pf, gw


if __name__ == "__main__":
    main()
