"""A mode's HUD pieces at the glass's EDGES, the way Stern lays out a battle (hud-layers).

David, 2026-09-26: "for persistant mode elements, can we add that feedback to the ui edges? (like how
the timers are displayed for example). it would be cool to show a gauge of like how many spikes for
anguirus in the ui while it's active (but out of the way) ... the modes need to blend in and look like
they were made by Stern."

What Stern does, read off Godzilla's own scenes (docs/plans/hud-layers.md):

* a battle's scene (the Ebirah battle's ``99cd5ccc/49ac2e40``) is TEXT over the battle's clip: three
  counters across the top (a label, a big value, a sub-label; columns at x 17.6 / 573.6 / 1123.6, 200 px
  wide), the battle's title above the score panel (y 444) and an instruction line under it (y 538), in
  the game's two fonts - GameFont_Primary, white with a black outline, and GameFont_Secondary, an orange
  gradient with a black outline;
* the running timers are badges on the LEFT edge of the slide-outs scene ``32e6ae28`` (BATTLE, DOUBLE
  SCORING, TESLA): a 210x102 panel with a green LED label and a dark number window, a glowing icon disc
  over its left end, the seconds in GameFont_Primary, stacked at y 267 / 376 / 485.

So a mode's HUD is ONE Sprite group in ``32e6ae28`` (drawn over a clip the backdrop puts in the city's
place, and over the city itself), ``PadMode_<slug>_Hud``, whose children the mode shows and writes by
name (:func:`hud_names`):

* ``_Title`` and ``_Line`` - the battle's title and instruction line;
* ``_C1`` .. ``_C3`` ``_Label`` / ``_Value`` / ``_Sub`` - the three counters;
* ``_Award`` and ``_AwardSub`` - a big line for a moment (a jackpot, a head severed);
* ``_Timer`` - the badge (``_Timer_Panel``, ``_Timer_Icon``) and its seconds (``_Timer_Num``), in the
  stock BATTLE badge's slot (y 267), under the counters; ``_Timer2`` the same badge one slot down (y 376),
  shown instead while one of the game's battles has its BATTLE badge up (PAD-347: a mode keeps running
  beside the game's own, its words aside);
* ``_Gauge`` - a label and N pips on the right edge, each an ``_On`` and an ``_Off`` picture
  (``_G1_On`` ...): ANGUIRUS's spikes, a meltdown's temperature.

The texts use the game's own font, carried into the HUD scene from the battle scene
(:func:`scene_write.carried_game_font`); the badge's panel is the stock BATTLE panel with the mode's own
label lettered in that same font; nothing here uses a desktop font, so a card built on any OS looks the
same. Everything is authored VISIBLE, as every screen is (scene_write's hazard): the mode hides it.
"""
from __future__ import annotations

import math
import struct

import numpy as np

from . import dds as _dds
from . import scene_write as SW

#: where the battle scene with the game's fonts sits on a Godzilla card (its first library entry is
#: the Font: HelveticaNeueBlack with GameFont_Primary 30/41/47 px and GameFont_Secondary 71/88 px)
GAME_FONT_SCENE = ("assets/lcd/auto_loaded/99cd5ccc01720c43f3d3bc1ccecd9cb40ae3f7e4/"
                   "49ac2e4041ae16eb56b2cf5484936ce1f6f271dd/scene.radium")
#: the carried font's ids start this far past the profile's first free id, and its library key
FONT_BASE_GAP = 0x1000
FONT_KEY = 20                        # 32e6ae28's library keys are 1..19
FONT_CLASS = 3                       # 32e6ae28 registers Font as class 3

GLASS_W, GLASS_H = 1360, 768
COUNTER_X = (17.6, 573.6, 1123.6)
TIMER_DY = 0.0                       # our badge sits in the stock BATTLE badge's slot, under the counters
TIMER2_DY = 109.0                    # PAD-347: its second slot, the next one down (y 376), while a battle runs
GAUGE_X = 1262.0                     # the pips' left edge on the right side of the glass


class HudError(ValueError):
    """The HUD cannot be built as asked; the message is a sentence."""


# ---- the game's font, read from a scene's first library entry ----------------------------------------
class GameFont:
    """Glyphs of one scene's first-entry Font: ``sizes[variant] = [(size id, px, {char: glyph})]``,
    ``pages[texture id] = RGBA array``. A glyph is (w, h, x offset, y offset, advance, pad, uv)."""

    def __init__(self, data):
        _k, (_a, cls_end), self.face, self.end, w = SW._walk_font(data, 9, variants=True)
        self.sizes, self.pages = {}, {}
        o = cls_end + 4                                   # the Font's own id
        o += 4                                            # its key
        o += 8 + struct.unpack_from("<Q", data, o)[0]     # name
        o += 8 + struct.unpack_from("<Q", data, o)[0]     # face
        o += 2
        o += 8 + 2 * struct.unpack_from("<Q", data, o)[0]
        o = self._sizes(data, o, "")
        nv = struct.unpack_from("<Q", data, o)[0]
        o += 8
        for _ in range(nv):
            n = struct.unpack_from("<Q", data, o)[0]
            name = data[o + 8:o + 8 + n].decode("latin1")
            o = self._sizes(data, o + 8 + n, name)
        if o != self.end:
            raise HudError("the game font's glyph walk ended at 0x%x, not 0x%x" % (o, self.end))

    def _sizes(self, d, o, variant):
        n = struct.unpack_from("<Q", d, o)[0]
        o += 8
        for _ in range(n):
            _mk, sid, _key = struct.unpack_from("<3I", d, o)
            px = struct.unpack_from("<f", d, o + 12)[0]
            o += 25
            glyphs = {}
            ng = struct.unpack_from("<Q", d, o)[0]
            o += 8
            for _g in range(ng):
                ch = struct.unpack_from("<H", d, o)[0]
                m = struct.unpack_from("<7f", d, o + 6)
                uv = struct.unpack_from("<4f", d, o + 35)
                page = struct.unpack_from("<I", d, o + 51)[0]
                o += 55
                if page & SW.FLAG:
                    tw, th, fmt = struct.unpack_from("<3I", d, o)
                    sl = struct.unpack_from("<Q", d, o + 12)[0]
                    ln = struct.unpack_from("<I", d, o + 20 + sl)[0]
                    blob = d[o + 24 + sl:o + 24 + sl + ln]
                    dec = _dds.decode_bc3 if fmt == SW.BC3 else _dds.decode_bc1
                    self.pages[page & ~SW.FLAG] = np.asarray(dec(blob, tw, th), dtype=np.uint8)
                    o += 24 + sl + ln
                    page &= ~SW.FLAG
                o += 8 + 6 * struct.unpack_from("<Q", d, o)[0]
                glyphs[ch] = (m, uv, page)
            self.sizes.setdefault(variant, []).append((sid & ~SW.FLAG, px, glyphs))
        return o

    def size(self, variant, px):
        """The size of ``variant`` nearest ``px``: (size id, px, glyphs)."""
        if variant not in self.sizes:
            raise HudError("the game font has no %s" % variant)
        return min(self.sizes[variant], key=lambda s: abs(s[1] - px))

    def render(self, text, variant, px, scale=1.0, tint=(255, 255, 255)):
        """``text`` in the game's own lettering, as an RGBA array (ink tinted, the outline kept)."""
        _sid, _px, glyphs = self.size(variant, px)
        pen, ink = 0.0, []
        for ch in text:
            g = glyphs.get(ord(ch)) or glyphs.get(ord(ch.upper()))
            if g is None:
                pen += px * 0.3
                continue
            m, uv, page = g
            gw, gh, xo, yo, adv, _z, pad = m
            if page in self.pages and gw > 1:
                ink.append((pen + xo - pad, -yo - pad, gw + 2 * pad, gh + 2 * pad, uv, page))
            pen += adv
        if not ink:
            raise HudError("nothing of %r is in the game font" % text)
        top = min(y for _x, y, _w, _h, _u, _p in ink)
        bot = max(y + h for _x, y, _w, h, _u, _p in ink)
        left = min(x for x, _y, _w, _h, _u, _p in ink)
        right = max(x + w for x, _y, w, _h, _u, _p in ink)
        from PIL import Image
        W = int(math.ceil((right - left) * scale)) + 2
        H = int(math.ceil((bot - top) * scale)) + 2
        out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for x, y, w, h, uv, page in ink:
            pg = self.pages[page]
            ph, pw = pg.shape[:2]
            crop = pg[int(uv[1] * ph):int(math.ceil(uv[3] * ph)), int(uv[0] * pw):int(math.ceil(uv[2] * pw))]
            if not crop.size:
                continue
            im = Image.fromarray(crop, "RGBA").resize((max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
                                                      Image.LANCZOS)
            out.alpha_composite(im, (int(round((x - left) * scale)) + 1, int(round((y - top) * scale)) + 1))
        a = np.asarray(out, dtype=np.float32)
        lum = a[..., :3].max(axis=2, keepdims=True) / 255.0            # white ink, black outline
        a[..., :3] = lum * np.asarray(tint, dtype=np.float32)
        return np.clip(a, 0, 255).astype(np.uint8)


# ---- art ---------------------------------------------------------------------------------------------
def _pil(a):
    from PIL import Image
    return Image.fromarray(np.asarray(a, dtype=np.uint8), "RGBA")


def _pad4(a):
    """An RGBA array grown to sides that are multiples of 4 (BC3), transparent."""
    h, w = a.shape[:2]
    H, W = (h + 3) // 4 * 4, (w + 3) // 4 * 4
    if (H, W) == (h, w):
        return a
    out = np.zeros((H, W, 4), dtype=np.uint8)
    out[:h, :w] = a
    return out


def stock_badge(hud_data):
    """(panel, disc) RGBA arrays of the stock BATTLE badge in ``32e6ae28`` (its first two textures)."""
    from .engine import parse_radium_images
    imgs = parse_radium_images(hud_data)
    if len(imgs) < 2:
        raise HudError("the HUD scene has no badge textures")
    out = []
    for im in imgs[:2]:
        raw = hud_data[im["data_off"]:im["data_off"] + im["length"]]
        dec = _dds.decode_bc3 if im["fmt"] == SW.BC3 else _dds.decode_bc1
        out.append(np.asarray(dec(raw, im["tex_w"], im["tex_h"]), dtype=np.uint8))
    if out[0].shape[:2] != (90, 94) or out[1].shape[:2] != (104, 212):
        raise HudError("the HUD scene's first textures are not the BATTLE badge (%s, %s)"
                       % (out[0].shape[:2], out[1].shape[:2]))
    return out[1], out[0]


#: the panel's LED label window (panel px) and its dark stripe colours
LABEL_BOX = (72, 7, 165, 26)


def badge_panel(panel, font, label):
    """The stock panel with ``label`` (one or two words) lettered in green in its LED window."""
    from PIL import Image, ImageFilter
    a = panel.copy()
    x0, y0, x1, y1 = LABEL_BOX
    win = a[y0:y1, x0:x1].astype(np.float32)
    dark = np.array([10, 30, 26], dtype=np.float32)
    stripes = np.where((np.arange(y1 - y0) % 2)[:, None, None] == 0, dark, dark * 0.7)
    win[..., :3] = stripes
    a[y0:y1, x0:x1] = win.astype(np.uint8)
    words = label.upper().split()
    lines = [label.upper()] if len(label) <= 10 or len(words) == 1 else [" ".join(words[:len(words) // 2 + len(words) % 2]),
                                                                            " ".join(words[len(words) // 2 + len(words) % 2:])]
    im = _pil(a)
    box_w, box_h = x1 - x0 - 4, y1 - y0 - 2
    rows = []
    for ln in lines:
        g = font.render(ln, "GameFont_Primary", 41, tint=(40, 255, 60))
        rows.append(_pil(g))
    total_h = sum(r.height for r in rows)
    s = min(box_w / max(r.width for r in rows), box_h / total_h)
    y = y0 + 1 + (box_h - total_h * s) / 2
    for r in rows:
        rr = r.resize((max(1, int(r.width * s)), max(1, int(r.height * s))), Image.LANCZOS)
        glow = rr.filter(ImageFilter.GaussianBlur(1.2))
        gx = int(x0 + 2 + (box_w - rr.width) / 2)
        im.alpha_composite(glow, (gx, int(y)))
        im.alpha_composite(rr, (gx, int(y)))
        y += rr.height
    return _pad4(np.asarray(im))


def badge_disc(disc, icon):
    """The stock glowing disc with its silhouette replaced by ``icon`` (an L array, 255 = ink)."""
    a = disc.astype(np.float32).copy()
    h, w = a.shape[:2]
    cy, cx = 46.0, 46.5
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.hypot(xx - cx, yy - cy)
    inside = r <= 24.5
    face = np.array([246, 226, 150], dtype=np.float32)
    rim = np.array([222, 182, 84], dtype=np.float32)
    t = np.clip(r / 24.5, 0, 1)[..., None]
    fill = face * (1 - t ** 3) + rim * t ** 3
    a[inside, :3] = fill[inside]
    a[inside, 3] = 255
    ic = np.asarray(icon, dtype=np.float32) / 255.0
    ih, iw = ic.shape
    oy, ox = int(cy - ih / 2), int(cx - iw / 2)
    sub = a[oy:oy + ih, ox:ox + iw]
    m = ic[..., None] * inside[oy:oy + ih, ox:ox + iw, None]
    sub[..., :3] = sub[..., :3] * (1 - m) + np.array([22, 16, 8], dtype=np.float32) * m
    return _pad4(np.clip(a, 0, 255).astype(np.uint8))


def _canvas(n=4 * 44):
    from PIL import Image, ImageDraw
    im = Image.new("L", (n, n), 0)
    return im, ImageDraw.Draw(im), n


def _done(im, size=44):
    from PIL import Image
    return np.asarray(im.resize((size, size), Image.LANCZOS))


def icon(kind):
    """A 44x44 silhouette (L array) for a badge disc: bolt, ghidorah, oxygen, maser, xilien, anguirus,
    radiation, or a letter."""
    im, d, n = _canvas()
    c = n / 2
    if kind == "radiation":
        d.ellipse((c - 14, c - 14, c + 14, c + 14), fill=255)
        for k in range(3):
            a0 = -90 + 120 * k - 30
            d.pieslice((c - 78, c - 78, c + 78, c + 78), a0, a0 + 60, fill=255)
            d.pieslice((c - 26, c - 26, c + 26, c + 26), a0 - 2, a0 + 62, fill=0)
        d.ellipse((c - 14, c - 14, c + 14, c + 14), fill=255)
    elif kind == "bolt":                                        # King Ghidorah's gravity beams
        d.polygon([(c + 10, 8), (c - 50, c + 10), (c - 6, c + 10), (c - 26, n - 8), (c + 52, c - 18),
                   (c + 8, c - 18), (c + 34, 8)], fill=255)
    elif kind == "ghidorah":
        for dx, top in ((-46, 26), (0, 10), (46, 26)):          # three necks, three heads
            pts = [(c + dx * t - 10 * math.sin(t * 3.1), n - 28 - (n - 28 - top) * t) for t in np.linspace(0, 1, 24)]
            d.line(pts, fill=255, width=18)
            hx, hy = pts[-1]
            d.polygon([(hx - 16, hy + 6), (hx + 20, hy - 4), (hx + 26, hy + 8), (hx - 10, hy + 18)], fill=255)
            d.polygon([(hx - 12, hy - 2), (hx - 4, hy - 22), (hx + 2, hy - 2)], fill=255)
        d.polygon([(c - 70, n - 70), (c - 16, n - 40), (c + 16, n - 40), (c + 70, n - 70), (c + 40, n - 14),
                   (c - 40, n - 14)], fill=255)
    elif kind == "oxygen":
        d.rounded_rectangle((c - 26, c - 60, c + 26, c + 60), radius=24, fill=255)
        d.rectangle((c - 34, c - 14, c + 34, c + 14), fill=255)
        for bx, by, br in ((c + 46, c - 50, 10), (c + 58, c - 18, 7), (c + 44, c + 20, 5)):
            d.ellipse((bx - br, by - br, bx + br, by + br), fill=255)
        d.rectangle((c - 12, c - 40, c + 12, c + 40), fill=0)
    elif kind == "maser":
        d.chord((c - 66, c - 76, c + 34, c + 24), 150, 330, fill=255)
        d.line((c - 16, c - 26, c + 60, c - 70), fill=255, width=8)
        d.polygon([(c - 22, c - 4), (c + 6, c - 4), (c + 22, c + 50), (c - 38, c + 50)], fill=255)
        d.rectangle((c - 60, c + 50, c + 40, c + 66), fill=255)
    elif kind == "xilien":
        d.line((c - 58, c - 58, c + 58, c + 58), fill=255, width=34)
        d.line((c + 58, c - 58, c - 58, c + 58), fill=255, width=34)
    elif kind == "anguirus":
        d.pieslice((c - 70, c - 20, c + 70, c + 100), 180, 360, fill=255)
        for k in range(7):
            a = math.radians(180 + 15 + k * 25)
            bx, by = c + 70 * math.cos(a), c + 40 + 60 * math.sin(a)
            tx, ty = c + 92 * math.cos(a), c + 40 + 84 * math.sin(a)
            nx, ny = -math.sin(a) * 12, math.cos(a) * 12
            d.polygon([(bx - nx, by - ny), (tx, ty), (bx + nx, by + ny)], fill=255)
    elif kind == "rage":                                        # PAD-379: a flame, his rage
        def flame(cx, base, h, w):
            pts = []
            for t in np.linspace(0, 1, 28):                    # the right edge up to the tip, curling over
                pts.append((cx + w * math.sin(math.pi * (1 - t)) * (1 - t) ** 0.6 + 10 * t, base - h * t))
            for t in np.linspace(1, 0, 28):                    # the left edge back down
                pts.append((cx - w * math.sin(math.pi * (1 - t)) * (1 - t) ** 0.4 + 10 * t * t, base - h * t))
            d.polygon(pts, fill=255)
        flame(c - 36, n - 12, 104, 30)
        flame(c + 36, n - 12, 104, 30)
        flame(c, n - 8, 150, 44)
        d.ellipse((c - 18, n - 70, c + 18, n - 22), fill=0)
    elif kind == "crystal":                                     # PAD-379: SpaceGodzilla's crystal towers
        for dx, h, w in ((-44, 96, 22), (0, 140, 28), (44, 110, 22)):
            base = n - 14
            d.polygon([(c + dx - w, base), (c + dx - w, base - h + w), (c + dx, base - h), (c + dx + w, base - h + w),
                       (c + dx + w, base)], fill=255)
            d.line((c + dx, base - h + 8, c + dx, base - 6), fill=0, width=5)
    elif kind == "snowflake":                                   # PAD-379: Kiryu's ABSOLUTE ZERO
        for k in range(6):
            a = math.radians(k * 60)
            ex, ey = c + 78 * math.cos(a), c + 78 * math.sin(a)
            d.line((c, c, ex, ey), fill=255, width=12)
            for t, br in ((0.5, 26), (0.78, 18)):
                bx, by = c + 78 * t * math.cos(a), c + 78 * t * math.sin(a)
                for s in (-1, 1):
                    b2 = a + s * math.radians(50)
                    d.line((bx, by, bx + br * math.cos(b2), by + br * math.sin(b2)), fill=255, width=9)
        d.ellipse((c - 16, c - 16, c + 16, c + 16), fill=255)
    elif kind == "rose":                                        # PAD-379: Biollante's rose
        d.line((c, c + 10, c - 6, n - 6), fill=255, width=12)
        d.ellipse((c - 54, c + 30, c - 8, c + 56), fill=255)       # a leaf
        for k in range(5):
            a = math.radians(-90 + k * 72)
            px, py = c + 34 * math.cos(a), c - 22 + 34 * math.sin(a)
            d.ellipse((px - 30, py - 30, px + 30, py + 30), fill=255)
        d.ellipse((c - 22, c - 44, c + 22, c), fill=0)
        d.arc((c - 16, c - 38, c + 16, c - 6), 0, 300, fill=255, width=8)
    elif kind == "claw":                                        # PAD-379: a Destoroyah aggregate's pincer
        d.ellipse((c - 78, c - 60, c + 38, c + 60), fill=255)    # the claw
        d.pieslice((c - 110, c - 92, c + 70, c + 92), 158, 202, fill=0)   # its open jaws
        d.ellipse((c - 30, c - 12, c - 6, c + 12), fill=0)       # the hinge of the bite
        d.polygon([(c + 20, c - 26), (c + 86, c - 14), (c + 86, c + 14), (c + 20, c + 26)], fill=255)   # the arm
    else:
        from PIL import ImageFont
        d.rectangle((0, 0, 0, 0), fill=0)
        d.text((c - 30, c - 50), str(kind)[:1], fill=255, font=ImageFont.load_default())
    return _done(im)


def gauge_pips(kind, n, colours):
    """[(on RGBA, off RGBA)] for ``n`` pips of a gauge: "spike" (ANGUIRUS), "segment" (a thermometer
    or a draining value: bottom to top), "diamond". ``colours`` = [(r, g, b)] per pip, cycled."""
    from PIL import Image, ImageDraw, ImageFilter
    out = []
    for i in range(n):
        col = tuple(int(c) for c in colours[i % len(colours)])
        if kind == "spike":
            W, H = 72, 72
            shape = [(8, 66), (36, 4), (64, 66)]
        elif kind == "segment":
            W, H = 88, 20
            shape = None
        else:
            W, H = 44, 44
            shape = [(22, 2), (42, 22), (22, 42), (2, 22)]
        pads = 10
        big = Image.new("RGBA", (W + 2 * pads, H + 2 * pads), (0, 0, 0, 0))
        on, off = big.copy(), big.copy()
        for img, lit in ((on, True), (off, False)):
            mask = Image.new("L", img.size, 0)
            md = ImageDraw.Draw(mask)
            if shape is None:
                md.rounded_rectangle((pads, pads, pads + W - 1, pads + H - 1), radius=6, fill=255)
            else:
                md.polygon([(x + pads, y + pads) for x, y in shape], fill=255)
            if lit:
                glow = Image.new("RGBA", img.size, col + (0,))
                glow.putalpha(mask.filter(ImageFilter.GaussianBlur(5)).point(lambda v: int(v * 0.9)))
                img.alpha_composite(glow)
                body = Image.new("RGBA", img.size, tuple(min(255, int(c * 0.55 + 115)) for c in col) + (255,))
                grad = Image.linear_gradient("L").resize(img.size).point(lambda v: 255 - v // 2)
                core = Image.composite(body, Image.new("RGBA", img.size, col + (255,)), grad)
                core.putalpha(mask)
                img.alpha_composite(core)
            else:
                dim = Image.new("RGBA", img.size, (38, 32, 30, 230))
                dim.putalpha(mask.point(lambda v: int(v * 0.85)))
                img.alpha_composite(dim)
            edge = mask.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 40 else 0)
            black = Image.new("RGBA", img.size, (0, 0, 0, 255))
            black.putalpha(edge)
            img.alpha_composite(black)
        out.append((_pad4(np.asarray(on)), _pad4(np.asarray(off))))
    return out


# ---- the scene nodes -----------------------------------------------------------------------------------
def hud_names(slug):
    """What a mode finds by name, keyed by role (the kit's struct kit_hud reads the same)."""
    g = "PadMode_%s_Hud" % slug
    names = {"group": g}
    for role in ("Title", "Line", "Award", "AwardSub", "Timer", "Timer_Num", "Timer2", "Timer2_Num", "Gauge",
                 "Gauge_Label"):
        names[role] = "%s_%s" % (g, role)
    return names


class _Ids:
    def __init__(self, first):
        self.n = first

    def take(self, k=1):
        v = list(range(self.n, self.n + k))
        self.n += k
        return v


def _text_node(p, ids, name, words, font, x, y, ltrb, rgba=(1.0, 1.0, 1.0, 1.0), flags=(0, 0), tail=None,
               scale=1.0):
    sid, variant = font
    pn, po = ids.take(2)
    t_flag, t_u32 = (0, 0) if tail is None else tail
    body = SW.text_body(p.symbol["text"], ltrb, rgba, words, sid, variant, 1, (2.0, 0.0), t_flag, t_u32,
                        flags=flags)
    return SW.node(SW.FLAG | pn, name, 1, [(1, 1)], [(1, SW.matrix(sx=scale, sy=scale, tx=x, ty=y))],
                   [(1, p.poly["text"], SW.FLAG | po, body)])


def _bitmap_node(p, ids, name, rgba, x, y, textures):
    """A Bitmap node; the same pixels already used in this HUD are referenced, not copied."""
    a = np.asarray(rgba, dtype=np.uint8)
    h, w = a.shape[:2]
    key = (w, h, a.tobytes())
    pn, po = ids.take(2)
    if key in textures:
        tex = SW.texture_ref(textures[key])
    else:
        tid = ids.take()[0]
        textures[key] = tid
        tex = SW.texture_new(tid, w, h, _dds.encode_bc3(a))
    return SW.node(SW.FLAG | pn, name, 1, [(1, 1)], [(1, SW.matrix(tx=x, ty=y))],
                   [(1, p.poly["bitmap"], SW.FLAG | po, SW.bitmap_body(p.symbol["bitmap"], w, h, tex))])


def _group_node(p, ids, name, kids, x=0.0, y=0.0):
    pn, po = ids.take(2)
    return SW.node(SW.FLAG | pn, name, 1, [(1, 1)], [(1, SW.matrix(tx=x, ty=y))],
                   [(1, p.poly["sprite"], SW.FLAG | po, SW.sprite_body(p.symbol["sprite"], kids))])


def hud_group(p, ids, slug, spec, fonts, art, textures):
    """The Sprite group ``PadMode_<slug>_Hud`` (bytes). ``spec`` (from a mode's assets.json "hud"):
    ``title``, ``line``, ``counters`` ([label, value, sub] x up to 3), ``timer`` (``label``, ``icon``),
    ``gauge`` (``label``, ``kind``, ``count``, ``colours``). ``fonts[variant][k]`` = (size id, variant)
    of the carried font, sizes in px order; ``art`` = {"panel", "disc"} stock badge arrays and the
    game font (``art["font"]``)."""
    names = hud_names(slug)
    g = names["group"]
    prim = lambda k: fonts["GameFont_Primary"][k]           # noqa: E731
    sec = lambda k: fonts["GameFont_Secondary"][k]          # noqa: E731
    kids = []
    title = spec.get("title") or spec.get("name") or slug.upper()
    kids.append(_text_node(p, ids, names["Title"], title, sec(0), 325.9, 444.0, (-245.9, 27.6, 954.1, 102.8),
                           flags=(1, 0)))
    kids.append(_text_node(p, ids, names["Line"], spec.get("line") or " ", prim(2), 325.9, 538.1,
                           (-245.9, -2.0, 954.1, 49.5), flags=(1, 0)))
    for k, c in enumerate((spec.get("counters") or [])[:3]):
        x = COUNTER_X[k]
        label, value, sub = (list(c) + ["", "", ""])[:3]
        kids.append(_text_node(p, ids, "%s_C%d_Label" % (g, k + 1), label or " ", prim(1), x, 103.8,
                               (-2.0, -2.0, 198.0, 43.5)))
        kids.append(_text_node(p, ids, "%s_C%d_Value" % (g, k + 1), value or "0", sec(1), x, 140.1,
                               (-2.0, -2.0, 198.0, 90.9)))
        kids.append(_text_node(p, ids, "%s_C%d_Sub" % (g, k + 1), sub or " ", prim(0), x, 223.9,
                               (-2.0, -2.0, 198.0, 31.6)))
    kids.append(_text_node(p, ids, names["Award"], spec.get("award") or " ", sec(1), 325.9, 262.0,
                           (-245.9, -2.0, 954.1, 90.9)))
    kids.append(_text_node(p, ids, names["AwardSub"], " ", prim(2), 325.9, 356.0, (-245.9, -2.0, 954.1, 49.5)))
    timer = spec.get("timer")
    if timer:
        panel = badge_panel(art["panel"], art["font"], timer.get("label") or title)
        disc = badge_disc(art["disc"], icon(timer.get("icon") or "xilien"))
        tk = [_bitmap_node(p, ids, names["Timer"] + "_Panel", panel, -21.0, 267.0, textures),
              _bitmap_node(p, ids, names["Timer"] + "_Icon", disc, 0.0, 281.8, textures),
              _text_node(p, ids, names["Timer_Num"], "00", (p.font[0], p.font[1]), 68.6, 295.4,
                         (18.0, -2.0, 98.0, 67.2), tail=tuple(p.text_tail))]
        kids.append(_group_node(p, ids, names["Timer"], tk, 0.0, TIMER_DY))
        tk2 = [_bitmap_node(p, ids, names["Timer2"] + "_Panel", panel, -21.0, 267.0, textures),
               _bitmap_node(p, ids, names["Timer2"] + "_Icon", disc, 0.0, 281.8, textures),
               _text_node(p, ids, names["Timer2_Num"], "00", (p.font[0], p.font[1]), 68.6, 295.4,
                          (18.0, -2.0, 98.0, 67.2), tail=tuple(p.text_tail))]
        kids.append(_group_node(p, ids, names["Timer2"], tk2, 0.0, TIMER2_DY))
    gauge = spec.get("gauge")
    if gauge:
        n = max(1, min(12, int(gauge.get("count") or 3)))
        kind = gauge.get("kind") or "spike"
        cols = [tuple(c) for c in (gauge.get("colours") or [(255, 120, 0)])]
        pips = gauge_pips(kind, n, cols)
        gk = [_text_node(p, ids, names["Gauge_Label"], gauge.get("label") or " ", prim(0), 1160.0, 300.0,
                         (-2.0, -2.0, 198.0, 31.6))]
        ph = pips[0][0].shape[0]
        step = ph - (18 if kind == "segment" else 14)
        top = 338.0                                  # under the right counter and the gauge's label
        for i, (on, off) in enumerate(pips):
            # a segment gauge fills from the BOTTOM: pip 1 is the lowest
            y = top + (n - 1 - i) * step if kind == "segment" else top + i * step
            x = GAUGE_X + 49.0 - on.shape[1] / 2.0
            # each picture its own Sprite group: only a Sprite can be shown and hidden by the mode
            gk.append(_group_node(p, ids, "%s_G%d_Off" % (g, i + 1),
                                  [_bitmap_node(p, ids, "%s_G%d_OffArt" % (g, i + 1), off, 0.0, 0.0, textures)], x, y))
            gk.append(_group_node(p, ids, "%s_G%d_On" % (g, i + 1),
                                  [_bitmap_node(p, ids, "%s_G%d_OnArt" % (g, i + 1), on, 0.0, 0.0, textures)], x, y))
        kids.append(_group_node(p, ids, names["Gauge"], gk))
    return _group_node(p, ids, g, kids)


def build_huds(p, data, huds, font_scene):
    """(library entry, [group bytes], {slug: hud_names}) for ``huds`` = [(slug, spec)] in the profiled
    scene ``data`` (``p`` its profile, rebased when ``data`` has grown): the game font carried from
    ``font_scene`` (the bytes of :data:`GAME_FONT_SCENE`) and one HUD group per mode. Called by
    :func:`scene_write.add_screens`, which splices them in with the screens and clips in one pass."""
    if not p.scene_id.startswith("32e6ae28"):
        raise HudError("a mode's HUD goes in Godzilla's slide-outs scene 32e6ae28, not %s" % p.label)
    base = p.first_free_id + FONT_BASE_GAP
    entry, sizes = SW.carried_game_font(font_scene, FONT_CLASS, FONT_KEY, base)
    fonts = {v: [(sid, v) for sid, _px in sorted(s, key=lambda t: t[1])] for v, s in sizes.items()}
    if len(fonts.get("GameFont_Primary", ())) < 3 or len(fonts.get("GameFont_Secondary", ())) < 2:
        raise HudError("the battle scene's font does not have the sizes a HUD uses")
    panel, disc = stock_badge(data)
    art = {"panel": panel, "disc": disc, "font": GameFont(font_scene)}
    ids = _Ids(base + 0x800)
    textures, groups, names = {}, [], {}
    for slug, spec in huds:
        name = hud_names(slug)["group"]
        if SW.string(name) in data:
            raise HudError("the HUD scene already has %s" % name)
        groups.append(hud_group(p, ids, slug, spec or {}, fonts, art, textures))
        names[slug] = hud_names(slug)
    # No byte search for the ids (a screen's seven are checked that way): two thousand FLAG|id words
    # meet the textures' random bytes. The profile's first_free_id is above every id the file uses,
    # and ours start FONT_BASE_GAP past it, clear of the screens' (7 each) and a graft's.
    if ids.n - p.first_free_id > 0x10000:
        raise HudError("the HUD takes too many object ids")
    return entry, groups, names
