"""PAD-1404: a mode's menu the player picks from with the flippers, on every title that takes a mode's screens.

Row 8 of the PAD-1398 analysis (20SidedDies' Uncanny X-Men 2.0): an episode picked through the portal, a mutant or a
roster picked at the game's start, any "choose your mode" a maker wants. X-Men has no challenge route and the team
start menu skips it, so the menu is the mode's own, built here as SCREENS (:func:`.scene_write.screen`) in the title's
HUD scene, as the meters are (:mod:`.mode_meters`):

* the PANEL ``PadMode_<slug>_Menu<k>`` (up to :data:`MENUS_MAX` a mode): a dark rounded box in the middle of the glass,
  its words the menu's title, in the menu's colour;
* :data:`ROWS` ROWS ``..._Menu<k>_R<j>``: each a row's words (an item; white) over a highlight bar ``..._R<j>_Hi`` (a
  layer, so only it can be shown: the row the cursor is on), the bar in the menu's colour;
* the FOOT ``..._Menu<k>_Foot``: what the buttons do and the seconds left, small.

The mode writes the words and shows the bar (intricate_kit.h ``kit_menu``): a card built before a menu was added has
none of these and the menu runs unseen. Every picture is PREMULTIPLIED, as the game blends them (PAD-416)."""
import re

import numpy as np

from .mode_hud import GLASS_W, GLASS_H, premultiplied
from .mode_meters import _rounded_mask, rgb, stem

MENUS_MAX = 2
ROWS = 5                             # intricate_kit.h KIT_MENU_ROWS: more items scroll
ITEMS_MAX = 12                       # KIT_MENU_ITEMS
TITLE_MAX = 32
ITEM_MAX = 28
COLOR = "#ffb000"
PANEL_W, PANEL_H = 760, 476
ROW_W, ROW_H, ROW_GAP = 680, 52, 60  # a row's bar, and one row under the last
TITLE_Y = 70.0                       # the title's line in the panel (the text box: 40 px above it, 8 under)
ROWS_Y = 150.0                       # the first row's line
FOOT_Y = PANEL_H - 22.0
TITLE_SCALE, ROW_SCALE, FOOT_SCALE = 0.95, 0.78, 0.5
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def names(slug, k):
    """Menu ``k``'s (from 1) nodes: the panel, its title's words, row j's group, words and bar, the foot."""
    g = "%s_Menu%d" % (stem(slug), k)
    row = lambda j: "%s_R%d" % (g, j)                                            # noqa: E731
    return {"node": g, "title": "%s.%s_Words" % (g, g), "row": row,
            "row_words": lambda j: "%s.%s_Words" % (row(j), row(j)),
            "row_hi": lambda j: "%s.%s_Hi" % (row(j), row(j)),
            "foot": g + "_Foot", "foot_words": "%s_Foot.%s_Foot_Words" % (g, g)}


def panel_at():
    """The panel's top-left on the glass: in its middle."""
    return (GLASS_W - PANEL_W) / 2.0, (GLASS_H - PANEL_H) / 2.0


def panel_picture(color):
    """The panel (RGBA, PANEL_W x PANEL_H): near-black glass, a rim in the menu's colour and a line under the title."""
    r, g, b = rgb(color, rgb(COLOR))
    outer = _rounded_mask(PANEL_W, PANEL_H, 22)
    inner = np.zeros_like(outer)
    inner[4:-4, 4:-4] = _rounded_mask(PANEL_W - 8, PANEL_H - 8, 19)
    rim = np.clip(outer - inner, 0, 1)
    a = np.zeros((PANEL_H, PANEL_W, 4), dtype=np.float32)
    yy = np.linspace(0, 1, PANEL_H)[:, None]
    body = 10 + 16 * (1 - yy)
    for c, v in enumerate((r, g, b)):
        a[..., c] = body * (1 - rim) + v * rim
    a[..., 3] = (inner * 0.86 + rim) * 255
    line = slice(int(TITLE_Y) + 18, int(TITLE_Y) + 21)
    a[line, 40:PANEL_W - 40, :3] = (r, g, b)
    a[line, 40:PANEL_W - 40, 3] = 200
    return premultiplied(np.clip(a, 0, 255).astype(np.uint8))


def row_bar(color):
    """The highlight bar (RGBA, ROW_W x ROW_H): the menu's colour, rounded, lit from above."""
    r, g, b = rgb(color, rgb(COLOR))
    m = _rounded_mask(ROW_W, ROW_H, ROW_H // 2)
    yy = np.linspace(0, 1, ROW_H)[:, None]
    lum = 0.55 + 0.35 * (1 - yy)
    out = np.zeros((ROW_H, ROW_W, 4), dtype=np.float32)
    for c, v in enumerate((r, g, b)):
        out[..., c] = np.clip(v * lum, 0, 255)
    out[..., 3] = m * 0.62 * 255
    return premultiplied(np.clip(out, 0, 255).astype(np.uint8))


def _inset(w, scale):
    """Where words scaled by ``scale`` start so their box (the picture's width, scaled from its left edge) stays
    centred on the picture: a centred line stays in the middle."""
    return w * (1.0 - scale) / 2.0


def _clear(w, h=4):
    return np.zeros((h, w, 4), dtype=np.uint8)


def menu_screens(slug, menus):
    """The screens of a mode's menus (``[{"title", "color"}]``, the first MENUS_MAX), in drawing order (the panel under
    its rows), for :func:`.scene_write.add_screens`."""
    out = []
    px, py = panel_at()
    for k, m in enumerate((menus or [])[:MENUS_MAX]):
        nm = names(slug, k + 1)
        colour = m.get("color") if COLOR_RE.match(str(m.get("color") or "")) else COLOR
        cr, cg, cb = rgb(colour)
        title = (str(m.get("title") or "") or " ")[:TITLE_MAX]
        out.append(dict(name=nm["node"], art_rgba=panel_picture(colour), words=title,
                        words_name=nm["title"].split(".", 1)[1], x=px, y=py, words_at=(_inset(PANEL_W, TITLE_SCALE), TITLE_Y),
                        words_scale=TITLE_SCALE, words_rgba=(cr / 255.0, cg / 255.0, cb / 255.0, 1.0)))
        bx = (PANEL_W - ROW_W) / 2.0
        for j in range(1, ROWS + 1):
            row = nm["row"](j)
            out.append(dict(name=row, art_rgba=_clear(ROW_W), words=" ", words_name=row + "_Words",
                            x=px + bx, y=py + ROWS_Y + ROW_GAP * (j - 1), words_at=(_inset(ROW_W, ROW_SCALE), 0.0),
                            words_scale=ROW_SCALE, words_rgba=(1.0, 1.0, 1.0, 1.0),
                            layers=[{"name": row + "_Hi", "rgba": row_bar(colour), "x": 0.0, "y": -40.0}]))
        out.append(dict(name=nm["foot"], art_rgba=_clear(ROW_W), words=" ", words_name=nm["foot"] + "_Words",
                        x=px + bx, y=py + FOOT_Y, words_at=(_inset(ROW_W, FOOT_SCALE), 0.0), words_scale=FOOT_SCALE,
                        words_rgba=(0.78, 0.78, 0.78, 1.0)))
    return out
