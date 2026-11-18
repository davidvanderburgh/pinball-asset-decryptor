"""PAD-1405: a mode's bar meters and its screen fade, on every title that takes a mode's screens.

The HUD at the glass's edges (:mod:`.mode_hud`) has three counters, a timer badge and one gauge, and only on Godzilla.
A game made in PAD (the PAD-1398 analysis: 20SidedDies' Uncanny X-Men 2.0, rows 9 and 10) wants a health bar per
character, an energy meter and a fade to black with a red glow before a big move, on any title. Both are built here as
SCREENS (:func:`.scene_write.screen`), so they go wherever a mode's own screen goes:

* a METER (``PadMode_<slug>_Meter<k>``, up to :data:`METERS_MAX` a mode) is a frame picture with its label in the
  game's words font over it, and :data:`METER_LEVELS` fill pictures (``..._Meter<k>_L<j>``: the bar filled to j of
  them), of which the mode shows the one its value out of its most comes to (none at 0);
* a FADE layer (``PadMode_<slug>_Fade<k>``, up to :data:`FADES_MAX` a mode: one per colour and look its blocks fade
  to) holds :data:`FADE_LEVELS` pictures of one colour at stepped strengths, each a few pixels stretched over the
  whole glass (``flat``: even; ``glow``: strongest at the edges, clear in the middle), of which the mode shows one.

The runtime only shows, hides and words a node (pad_mode.h ``pm_show``/``pm_set_text``), so a level is a picture of its
own. Every screen is authored visible: the mode hides them all as soon as it finds them (intricate_kit.h
``kit_meter_find`` / ``kit_fade_find``)."""
import re

import numpy as np

from .mode_hud import GLASS_W, GLASS_H

METERS_MAX = 4
METER_LEVELS = 20                    # 5 % a step
METER_W, METER_H = 256, 60           # the meter's picture: its label's band, then the bar
BAR_TOP, BAR_H = 28, 28              # the bar inside it
METER_GAP = 70                       # one meter under another
METER_AT_DEFAULT = (GLASS_W - METER_W - 24.0, 100.0)    # the first one's top-left: the glass's right edge
METER_WORDS_SCALE = 0.62
LABEL_MAX = 24
FADES_MAX = 3
FADE_LEVELS = 16
FADE_STYLES = ("flat", "glow")
_FLAT = 8                            # a flat fade's picture, stretched over the glass
_GLOW_W, _GLOW_H = 172, 96           # a glow's (its gradient wants the pixels)
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def stem(slug):
    """The node names' stem, as :func:`.mode_project.asset_names` makes it."""
    return "PadMode_" + re.sub(r"[^A-Za-z0-9]", "_", slug)


def meter_names(slug, k):
    """A meter's nodes (k from 1): the group, its words (path from the group's scene) and level j's path."""
    g = "%s_Meter%d" % (stem(slug), k)
    return {"node": g, "text": "%s.%s_Words" % (g, g), "level": lambda j: "%s.%s_L%d" % (g, g, j)}


def fade_names(slug, k):
    g = "%s_Fade%d" % (stem(slug), k)
    return {"node": g, "level": lambda j: "%s.%s_L%d" % (g, g, j)}


def rgb(color, default=(255, 255, 255)):
    c = str(color or "")
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) if COLOR_RE.match(c) else default


# ---- the pictures ---------------------------------------------------------------------------------------------------
def _rounded_mask(w, h, r, k=4):
    from PIL import Image, ImageDraw
    m = Image.new("L", (w * k, h * k), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * k - 1, h * k - 1), radius=r * k, fill=255)
    return np.asarray(m.resize((w, h), Image.LANCZOS), dtype=np.float32) / 255.0


def meter_frame():
    """The meter's frame (RGBA, METER_W x METER_H): a dark glass tube with a light rim where the bar goes, the label's
    band above it clear (its words are the screen's own Text)."""
    a = np.zeros((METER_H, METER_W, 4), dtype=np.float32)
    outer = _rounded_mask(METER_W, BAR_H, BAR_H // 2)
    inner = np.zeros_like(outer)
    inner[3:-3, 3:-3] = _rounded_mask(METER_W - 6, BAR_H - 6, (BAR_H - 6) // 2)
    rim = np.clip(outer - inner, 0, 1)
    yy = np.linspace(0, 1, BAR_H)[:, None]
    body = np.dstack([np.broadcast_to(18 + 14 * (1 - yy), outer.shape)] * 3)
    rimc = np.dstack([np.broadcast_to(210 - 90 * yy, outer.shape)] * 3)
    col = body * (1 - rim[..., None]) + rimc * rim[..., None]
    alpha = inner * 0.78 + rim * 0.95
    a[BAR_TOP:BAR_TOP + BAR_H, :, :3] = col
    a[BAR_TOP:BAR_TOP + BAR_H, :, 3] = alpha * 255
    return np.clip(a, 0, 255).astype(np.uint8)


def meter_fill(color, j, n=METER_LEVELS):
    """The bar filled to ``j`` of ``n`` (RGBA, METER_W x BAR_H, placed at BAR_TOP): ``color`` lit from above, round."""
    r, g, b = rgb(color, (220, 30, 30))
    w = int(round((METER_W - 6) * j / float(n)))
    out = np.zeros((BAR_H, METER_W, 4), dtype=np.float32)
    if w <= 0:
        return out.astype(np.uint8)
    inside = np.zeros((BAR_H, METER_W), dtype=np.float32)       # the liquid: rounded at both its ends, as the tube
    inside[3:-3, 3:3 + w] = _rounded_mask(w, BAR_H - 6, min((BAR_H - 6) // 2, max(1, w // 2)))
    cut = 1.0
    yy = np.linspace(0, 1, BAR_H)[:, None]
    lum = 0.55 + 0.45 * np.sin(np.pi * np.clip(yy * 1.05, 0, 1)) ** 0.7
    shine = np.exp(-((yy - 0.3) / 0.1) ** 2) * 0.5
    for c, v in enumerate((r, g, b)):
        out[..., c] = np.clip(v * lum + 255 * shine, 0, 255)
    out[..., 3] = inside * cut * 255
    return np.clip(out, 0, 255).astype(np.uint8)


def fade_picture(color, style, j, n=FADE_LEVELS):
    """A fade's picture at step ``j`` of ``n`` (RGBA): ``flat`` an even tint, ``glow`` strongest at the glass's edges
    and clear in its middle; full strength at ``n``."""
    r, g, b = rgb(color, (0, 0, 0))
    k = j / float(n)
    if style == "glow":
        ys, xs = np.mgrid[0:_GLOW_H, 0:_GLOW_W].astype(np.float32)
        d = np.sqrt(((xs + 0.5) / _GLOW_W * 2 - 1) ** 2 + ((ys + 0.5) / _GLOW_H * 2 - 1) ** 2)    # 0 middle, ~1.41 corner
        t = np.clip((d - 0.4) / 0.8, 0, 1)
        alpha = (t * t * (3 - 2 * t)) * 0.92 * k
    else:
        alpha = np.full((_FLAT, _FLAT), k, dtype=np.float32)
    out = np.zeros(alpha.shape + (4,), dtype=np.uint8)
    out[..., 0], out[..., 1], out[..., 2] = r, g, b
    out[..., 3] = np.clip(alpha * 255 + 0.5, 0, 255).astype(np.uint8)
    return out


# ---- the screens ----------------------------------------------------------------------------------------------------
def meter_at(m, k):
    """Where meter ``k`` (from 0) goes on the glass: its own place, else down the right edge."""
    if isinstance(m.get("at"), (list, tuple)) and len(m["at"]) == 2:
        x, y = (float(v) for v in m["at"])
    else:
        x, y = METER_AT_DEFAULT[0], METER_AT_DEFAULT[1] + METER_GAP * k
    return min(max(x, 0.0), GLASS_W - METER_W), min(max(y, 0.0), GLASS_H - METER_H)


def meter_screens(slug, meters):
    """The screens of a mode's meters (``[{"label", "color", "at"}]``, the first METERS_MAX): each its frame, its
    label and a picture a level, for :func:`.scene_write.add_screens`."""
    out = []
    for k, m in enumerate((meters or [])[:METERS_MAX]):
        nm = meter_names(slug, k + 1)
        x, y = meter_at(m, k)
        layers = [{"name": nm["level"](j).split(".", 1)[1], "rgba": meter_fill(m.get("color"), j), "x": 0.0,
                   "y": float(BAR_TOP)} for j in range(1, METER_LEVELS + 1)]
        out.append(dict(name=nm["node"], art_rgba=meter_frame(), words=(m.get("label") or " ")[:LABEL_MAX] or " ",
                        words_name=nm["text"].split(".", 1)[1], x=x, y=y,
                        words_at=(0.0, BAR_TOP - 3.0), words_scale=METER_WORDS_SCALE,
                        words_rgba=(1.0, 1.0, 1.0, 1.0), layers=layers))
    return out


def fade_screens(slug, fades):
    """The screens of a mode's fade layers (``[{"color", "style"}]``, the first FADES_MAX): each a picture a step,
    stretched over the whole glass."""
    out = []
    for k, f in enumerate((fades or [])[:FADES_MAX]):
        nm = fade_names(slug, k + 1)
        style = f.get("style") if f.get("style") in FADE_STYLES else "flat"
        pw, ph = (_GLOW_W, _GLOW_H) if style == "glow" else (_FLAT, _FLAT)
        # a flat tint runs a little past the glass all round, so its stretched edge is never seen
        pad = 0.0 if style == "glow" else 16.0
        sx, sy = (GLASS_W + 2 * pad) / pw, (GLASS_H + 2 * pad) / ph
        layers = [{"name": nm["level"](j).split(".", 1)[1], "rgba": fade_picture(f.get("color"), style, j),
                   "x": -pad, "y": -pad, "sx": sx, "sy": sy} for j in range(1, FADE_LEVELS + 1)]
        out.append(dict(name=nm["node"], art_rgba=np.zeros((4, 4, 4), dtype=np.uint8), words=" ", x=0.0, y=0.0,
                        layers=layers))
    return out
