"""Render Spike 2 radium font text, and fit a desktop font into a glyph table.

Works entirely from an extract folder (no card needed): the per-character
glyph slice PNGs under ``images/scene_textures/glyphs/<atlas stem>/`` plus the
``glyph_images.txt`` manifest, whose trailing metrics columns (rot, glyph_w,
glyph_h, bearing_x, bearing_y, advance — appended by the same release that
added this module) carry the radium glyph-record layout floats.  See
``radium.py``'s format comment for how those were derived.

Two jobs, both feeding the GUI's Font Preview / Import window (a tester):

* :func:`render_text` — composite a string exactly the way the game lays it
  out (pen + bearing X, baseline − bearing Y, advance), reading the CURRENT
  slice PNGs so pending glyph edits show up live.  On an extract made before
  the metrics columns existed it falls back to approximate layout
  (``font["has_metrics"]`` is False — the caller should suggest re-extracting).

* :func:`rasterize_ttf` — fit a TTF/OTF font into an existing glyph table:
  one uniform pixel size chosen so every character's ink fits its atlas slot
  (the hard part of font swaps done by hand — a tester's turtle font), each glyph
  baseline-aligned into its slot and returned at as-stored orientation, ready
  to save over the slice PNGs (Write then splices only the changed BC blocks).

The game lays text out with the METRICS STORED IN THE RADIUM, which an import
does not touch — so spacing keeps the original font's rhythm and the swap is
size-neutral.  Rotated slots (``rot``) are un-rotated for rendering and
re-rotated on import (stored = upright turned 90° clockwise).
"""

import os
import re

from ...core.longpath import ext as _lp

GLYPH_MANIFEST = os.path.join("images", "scene_textures", "glyph_images.txt")
LINE_GAP = 2          # extra px between lines (display nicety, not from card)

#: Below this the letters are too few pixels tall for a desktop font to survive
#: the fit — a tester, who restyled a whole game: "smaller fonts do look more and
#: more strange the smaller they get… i guess they should be skipped and left
#: alone (about smaller 30 pixel)".  Advisory: the Fonts window says so and
#: asks, it never refuses.
MIN_RESTYLE_PX = 30


class FontError(Exception):
    pass


def _pil():
    try:
        from PIL import Image
    except Exception:
        raise FontError("Pillow is required for font rendering")
    return Image


# ---------------------------------------------------------------------------
# Loading the glyph tables from an extract folder
# ---------------------------------------------------------------------------

def load_fonts(assets_dir):
    """Parse ``glyph_images.txt`` into a list of font dicts, one per atlas
    (a typeface baked at several sizes is several atlases = several entries).

    Font dict keys: ``key`` (the manifest's table id — a glyph table can span
    several atlas pages, so the ATLAS is not the font), ``name`` (the radium's
    font name), ``atlas_rels`` (every atlas page's rel path), ``glyphs``
    ({char int: glyph dict}), ``has_metrics``, ``ascent``, ``descent``,
    ``px`` (nominal size label).
    Glyph dict keys: ``char, rel, abs, x, y, w, h`` (as-stored atlas rect),
    ``rot, lw, lh`` (logical/upright dims), ``bx, by, adv``."""
    path = os.path.join(assets_dir, GLYPH_MANIFEST)
    if not os.path.isfile(path):
        return []
    fmt_by_atlas = _atlas_formats(assets_dir)
    fonts = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 8:
                continue
            g_rel, atlas_rel, char_s, x, y, w, h, name = cols[:8]
            try:
                char = int(char_s, 16 if char_s.lower().startswith("0x")
                           else 10)
                x, y, w, h = int(x), int(y), int(w), int(h)
            except ValueError:
                continue
            has_metrics = len(cols) >= 14
            if has_metrics:
                try:
                    rot = bool(int(cols[8]))
                    lw, lh, bx, by, adv = (float(c) for c in cols[9:14])
                except ValueError:
                    has_metrics = False
            if not has_metrics:
                # Pre-metrics extract: approximate.  Upright, baseline at the
                # bitmap bottom, advance from the bitmap width.
                rot, lw, lh, bx, by = False, w, h, 0.0, float(h)
                adv = w + max(1.0, round(w * 0.15))
            stem = g_rel.replace("\\", "/").split("/")[-2]
            key = cols[14] if len(cols) >= 15 and cols[14] else stem
            # One atlas is commonly drawn at several sizes over the SAME art,
            # so rows are grouped by (font, size) — see radium.table_size_px.
            # Column 17 is absent in a pre-size extract, where every row falls
            # into one bucket and this behaves exactly as it always did.
            try:
                size_id = int(cols[16]) if len(cols) >= 17 else 0
            except ValueError:
                size_id = 0
            kern = {}
            if len(cols) >= 16 and cols[15]:
                for pair in cols[15].split(";"):
                    try:
                        c, v = pair.split(":")
                        kern[int(c, 16)] = float(v)
                    except ValueError:
                        continue
            fo = fonts.get((key, size_id))
            if fo is None:
                fo = fonts[(key, size_id)] = {
                    "key": key, "name": name, "atlas_rels": [],
                    "glyphs": {}, "has_metrics": has_metrics,
                    "size_id": size_id,
                }
            if atlas_rel not in fo["atlas_rels"]:
                fo["atlas_rels"].append(atlas_rel)
            fo["has_metrics"] = fo["has_metrics"] and has_metrics
            fo["glyphs"][char] = {
                "char": char, "rel": g_rel, "atlas_rel": atlas_rel,
                "fmt": fmt_by_atlas.get(atlas_rel, 5),
                "abs": os.path.join(assets_dir, "images", *g_rel.split("/")),
                "x": x, "y": y, "w": w, "h": h, "rot": rot,
                "lw": lw, "lh": lh, "bx": bx, "by": by, "adv": adv,
                "kern": kern,
            }
    by_key = {}
    for fo in fonts.values():
        gs = [g for g in fo["glyphs"].values() if g["lh"] > 1]
        fo["ascent"] = int(round(max((g["by"] for g in gs), default=8)))
        fo["descent"] = max(0, int(round(
            max((g["lh"] - g["by"] for g in gs), default=0))))
        fo["px"] = fo["ascent"] + fo["descent"]
        by_key.setdefault(fo["key"], []).append(fo)
    # One entry per FONT, not per size: the sizes share one atlas and one set
    # of glyph slices, so they are one thing to look at and one thing to
    # import into — splitting them would show the Fonts window several rows
    # whose edits all land on the same files.  The alternatives ride along in
    # ``sizes`` for the scene preview, which does need the exact metrics of the
    # size a given scene draws at.
    out = []
    for variants in by_key.values():
        # A NAMED variant represents the font: the outline/companion tables
        # that share an atlas are frequently anonymous, and letting one of
        # those win left the Fonts window listing a blank name.
        variants.sort(key=lambda f: (not f["name"], -len(f["glyphs"]),
                                     -f["px"]))
        rep = variants[0]
        rep["sizes"] = {v["size_id"]: v for v in variants}
        out.append(rep)
    out.sort(key=lambda fo: (fo["name"].lower(), -fo["px"]))
    return out


def font_at_size(font, size_id):
    """The variant of *font* whose metrics match *size_id*, or *font* itself.

    Scenes name the size they draw at; a project extracted before sizes were
    recorded has only the one, and every lookup falls back to it."""
    if not font or not size_id:
        return font
    return (font.get("sizes") or {}).get(size_id) or font


def _atlas_formats(assets_dir):
    """``{atlas out_rel: fmt}`` from ``radium_images.txt`` (fmt 4 = BC1 with
    no real alpha — those atlases keep an opaque black background, which an
    import must reproduce)."""
    path = os.path.join(assets_dir, "images", "scene_textures",
                        "radium_images.txt")
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) >= 7:
                try:
                    out.setdefault(cols[0], int(cols[6]))
                except ValueError:
                    pass
    return out


def load_slice(glyph, image=None):
    """The glyph's UPRIGHT bitmap as RGBA for DISPLAY, from its slice PNG on
    disk (so pending edits show) unless *image* supplies it.  Off-size files
    are scaled to the atlas rect first — mirroring what Write will do — then
    rotated slots are turned back counter-clockwise.

    BC1 (fmt 4) atlases have no usable alpha — ink sits on opaque black and
    the game draws it additively, so black contributes nothing on screen.
    The preview emulates that by keying alpha off luminance; the SAVE paths
    (:func:`save_slices` / :func:`revert_slices`) never do this — on-card
    bytes keep the opaque background."""
    Image = _pil()
    img = image if image is not None else Image.open(_lp(glyph["abs"]))
    img = img.convert("RGBA")
    if img.size != (glyph["w"], glyph["h"]):
        img = img.resize((glyph["w"], glyph["h"]), Image.LANCZOS)
    if glyph["rot"]:
        img = img.transpose(Image.ROTATE_90)      # CCW back to upright
    if glyph.get("fmt") == 4:
        try:
            import numpy as np
            arr = np.asarray(img).copy()
            lum = arr[..., :3].max(axis=2)
            arr[..., 3] = np.minimum(arr[..., 3], lum)
            img = Image.fromarray(arr, "RGBA")
        except Exception:
            pass
    return img


# ---------------------------------------------------------------------------
# Text rendering
# ---------------------------------------------------------------------------

def _space_advance(font):
    g = font["glyphs"].get(0x20)
    if g is not None and (font["has_metrics"] or g["adv"] > 3):
        return g["adv"]
    advs = [g["adv"] for g in font["glyphs"].values() if g["lh"] > 1]
    return 0.6 * (sum(advs) / len(advs)) if advs else 8.0


def _fit_to_metrics(img, glyph):
    """Scale a glyph's atlas bitmap to the box its METRICS say it occupies.

    The atlas cell is the font's master art and is not necessarily the size
    this table draws it at.  JAWS bakes one typeface at two point sizes over a
    SINGLE shared atlas: ``'0'`` is one 82x94 cell that one table draws at
    28x31 (advance 30) and the other at 54x64 (advance 60).  So the metrics box
    is the drawn size, and pasting the cell at its native resolution rendered
    every JAWS text line about 3x too big — glyphs overlapped their neighbours
    and lines ran off the stage, while the advances stayed correct.

    On TMNT and Munsters the cell already equals the metrics box exactly (ratio
    1.000 over all 113 glyphs of the clock screen's HelveticaNeueBlack), which
    is why drawing at native size looked right for two years and this went
    unnoticed.  There it is a no-op."""
    tw, th = int(round(glyph["lw"])), int(round(glyph["lh"]))
    if not (1 <= tw <= 4096 and 1 <= th <= 4096) or (tw, th) == img.size:
        return img
    Image = _pil()
    return img.resize((tw, th), Image.LANCZOS)


def render_text(font, text, slice_loader=None, tracking=0):
    """Composite *text* (``\\n`` = new line) with *font*'s current glyph
    bitmaps, laid out by the stored metrics: ink at ``pen + bearing_x``,
    ``baseline − bearing_y``; pen advances by ``advance``.

    *slice_loader* (glyph → RGBA or None) overrides the default disk loader —
    the import preview passes candidate bitmaps through here.  Returns
    ``(RGBA image, missing)`` where *missing* is the set of characters the
    font has no glyph for (rendered as a gap)."""
    Image = _pil()
    loader = slice_loader or (lambda g: load_slice(g))
    asc, desc = font["ascent"], font["descent"]
    line_h = asc + desc + LINE_GAP
    sp_adv = _space_advance(font)
    missing = set()
    placed = []                     # (x, y, img)
    min_x, max_x = 0.0, 1.0
    for li, line in enumerate(text.split("\n")):
        pen = 0.0
        base_y = li * line_h + asc
        for ci, ch in enumerate(line):
            g = font["glyphs"].get(ord(ch))
            # pair-kerning: the glyph's table adjusts the advance when THIS
            # right-hand character follows it
            nxt = ord(line[ci + 1]) if ci + 1 < len(line) else None
            kern = (g["kern"].get(nxt, 0.0)
                    if g is not None and nxt is not None else 0.0)
            if g is None or g["lh"] <= 1:
                if g is None and ch != " ":
                    missing.add(ch)
                pen += ((g["adv"] if g is not None else sp_adv)
                        + kern + tracking)
                continue
            try:
                img = loader(g)
            except (OSError, FontError):
                missing.add(ch)
                pen += g["adv"] + kern + tracking
                continue
            img = _fit_to_metrics(img, g)
            x = pen + g["bx"]
            y = base_y - g["by"]
            placed.append((x, y, img))
            min_x = min(min_x, x)
            max_x = max(max_x, x + img.size[0], pen + g["adv"])
            pen += g["adv"] + kern + tracking
        max_x = max(max_x, pen)
    n_lines = text.count("\n") + 1
    W = max(1, int(round(max_x - min_x)))
    H = max(1, n_lines * line_h - LINE_GAP)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for x, y, img in placed:
        ix, iy = int(round(x - min_x)), int(round(y))
        canvas.alpha_composite(img, (max(0, ix), max(0, iy)))
    return canvas, missing


def font_color(font, samples=8):
    """The font's dominant INK color over its widest glyphs — the default
    tint for an imported font, so a swap keeps the original's look.  Weighted
    by alpha x luminance: BC1 fonts are ink on an opaque black background, so
    plain alpha weighting would average the ink into gray.

    A font whose ink is genuinely BLACK defeats that weighting (every pixel
    scores zero), so it falls back to plain alpha weighting rather than to
    white — outline companions are solid black silhouettes, and answering
    "white" for one turned an import into a white halo where the game wanted a
    dark one.  Only a font with no readable ink at all returns white."""
    try:
        import numpy as np
    except Exception:
        return (255, 255, 255)
    gs = sorted((g for g in font["glyphs"].values() if g["lh"] > 1),
                key=lambda g: -(g["w"] * g["h"]))[:samples]
    tot = np.zeros(3)
    wsum = 0.0
    a_tot = np.zeros(3)
    a_sum = 0.0
    for g in gs:
        try:
            arr = np.asarray(load_slice(g), dtype=float)
        except (OSError, FontError):
            continue
        alpha = arr[..., 3] / 255.0
        lum = arr[..., :3].max(axis=2) / 255.0
        w2 = alpha * lum * lum
        if w2.sum() > 0:
            tot += (arr[..., :3] * w2[..., None]).sum(axis=(0, 1))
            wsum += w2.sum()
        if alpha.sum() > 0:
            a_tot += (arr[..., :3] * alpha[..., None]).sum(axis=(0, 1))
            a_sum += alpha.sum()
    if wsum > 0:
        return tuple(int(round(c)) for c in (tot / wsum))
    if a_sum > 0:
        return tuple(int(round(c)) for c in (a_tot / a_sum))
    return (255, 255, 255)


# ---------------------------------------------------------------------------
# Fitting a desktop font into the glyph table
# ---------------------------------------------------------------------------

def _fittable(font):
    """The glyphs an import should redraw: real bitmaps, not the 1px space."""
    return {g["char"]: g for g in font["glyphs"].values()
            if g["lw"] > 2 and g["lh"] > 2}


def _core_chars(slots):
    """The characters allowed to constrain the uniform import size: letters
    and digits.  Oddballs (underscore's 55x6 slot, dingbats) would otherwise
    throttle the whole font — they get per-glyph downscaling instead."""
    core = {ch: g for ch, g in slots.items() if chr(ch).isalnum()}
    return core or slots


def fit_size(measure, slots, lo=2, hi=512, squeeze=1.0):
    """Largest integer size for which ``measure(size)`` — ``{char: (ink_w,
    ink_h) or None}`` — fits every CORE slot's upright box (letters/digits;
    see :func:`_core_chars`).  0 when even *lo* doesn't fit.  Pure bisection
    so the sizing rule is unit-testable apart from any rasterizer.

    *squeeze* < 1 relaxes the WIDTH constraint: ink may be up to
    ``lw / squeeze`` wide because the rasterizer will compress it
    horizontally into the slot (a tester: a wide typeface otherwise lets its
    'W' crush the whole font to a fraction of the slot height — height
    should govern the size, width gets a bounded squeeze)."""
    core = _core_chars(slots)

    def ok(size):
        inks = measure(size)
        for ch, g in core.items():
            ink = inks.get(ch)
            if ink is None:
                continue                    # char unavailable: keep original
            if ink[0] > g["lw"] / squeeze or ink[1] > g["lh"]:
                return False
        return True
    if not ok(lo):
        return 0
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


def _draw_char(ch, ttf, color, stroke, stroke_color):
    """Rasterize one character on a loose canvas, baseline at a known row.
    Returns ``(RGBA crop, asc_ink, desc_ink)`` or None for empty ink."""
    Image = _pil()
    from PIL import ImageDraw
    pad = ttf.size + 2 * stroke + 8
    canvas = Image.new("RGBA", (3 * pad, 3 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    base = (pad, 2 * pad)               # x, baseline y
    d.text(base, ch, font=ttf, fill=tuple(color) + (255,),
           anchor="ls", stroke_width=stroke,
           stroke_fill=tuple(stroke_color) + (255,))
    box = canvas.getbbox()
    if box is None:
        return None
    x0, y0, x1, y1 = box
    return canvas.crop(box), base[1] - y0, y1 - base[1]


def rasterize_ttf(font, ttf_path, color=None, stroke=0, stroke_color=(0, 0, 0),
                  size_scale=1.0, squeeze=0.6, width_scale=1.0):
    """Fit the desktop font at *ttf_path* into *font*'s glyph slots.

    Picks ONE uniform pixel size — the largest at which every character's ink
    (including any outline stroke) fits its slot's upright box, scaled by
    *size_scale* (≤1 to taste) — then renders each character baseline-aligned
    into its slot, clamped inside it, centered horizontally.  Characters the
    TTF cannot draw keep their original bitmaps and are reported.

    HEIGHT governs the size: a letter whose ink is too WIDE for its slot is
    compressed horizontally at raster time, down to *squeeze* (0.6 = ink may
    be squeezed to 60% of its natural width before the whole font shrinks
    instead).  Without this, one wide 'W' crushes a wide typeface to a
    fraction of the slot height (a tester's turtle font).  ``squeeze=1.0``
    restores strict keep-aspect fitting.

    *width_scale* (< 1) draws each letter narrower than its slot, leaving a
    side bearing inside the SAME atlas rect.  The game lays text out with the
    card's own advances, which an import must not change, so a letter that
    fills its slot edge to edge sits hard against its neighbour — a tester, after
    restyling a card: "some of the letters are very near together".  Shrinking
    the whole font (*size_scale*) opens the gaps but throws away height too;
    this buys the gap for width alone.

    Returns ``(slices, size, kept)``: *slices* maps char → as-stored RGBA
    (rotated slots pre-rotated, exact atlas-rect dims — save these over the
    slice PNGs), *size* is the chosen pixel size, *kept* the characters left
    untouched."""
    Image = _pil()
    from PIL import ImageFont
    if color is None:
        color = font_color(font)
    slots = _fittable(font)
    if not slots:
        raise FontError("this font has no drawable glyph slots")

    cache = {}

    def ttf_at(size):
        f = cache.get(size)
        if f is None:
            try:
                f = cache[size] = ImageFont.truetype(ttf_path, size)
            except OSError as e:
                raise FontError("can't open font file: %s" % e)
        return f

    def measure(size):
        # getbbox is a no-raster metrics query (anchor "ls" = origin at the
        # baseline), so the size bisection costs nothing; the actual ink is
        # rasterized once, at the final size.
        t = ttf_at(size)
        out = {}
        for ch in slots:
            try:
                x0, y0, x1, y1 = t.getbbox(chr(ch), anchor="ls",
                                           stroke_width=stroke)
            except (OSError, ValueError):
                out[ch] = None
                continue
            out[ch] = (x1 - x0, y1 - y0) if x1 > x0 and y1 > y0 else None
        return out

    width_scale = max(0.1, min(1.0, float(width_scale)))
    # The FIT is untouched by the width budget on purpose: folding it in makes
    # the size width-bound, and the letters lose the height they were asked to
    # keep (measured — 80px became 63px at width 80%).  The budget is spent at
    # placement instead, so letters stay tall and get a little more of the
    # horizontal compression the squeeze rule already does.
    size = fit_size(measure, slots, squeeze=squeeze)
    if size <= 0:
        raise FontError("the font doesn't fit this glyph table even at 2px")
    size = max(2, int(round(size * size_scale)))
    t = ttf_at(size)

    slices, kept = {}, []
    for ch, g in slots.items():
        r = _draw_char(chr(ch), t, color, stroke, stroke_color)
        if r is None:
            kept.append(chr(ch))
            continue
        ink, asc_ink, _desc_ink = r
        lw, lh = int(g["lw"]), int(g["lh"])
        # The cell stays the slot's size (the atlas rect must not change); the
        # INK is what gets the narrower budget.
        aw = max(1, int(round(lw * width_scale)))
        if ink.size[0] > aw or ink.size[1] > lh:
            if ink.size[1] <= lh:
                # width-only overflow: SQUEEZE horizontally into the budget —
                # a wide typeface keeps its height instead of shrinking
                nw, nh = aw, ink.size[1]
            else:
                s = min(aw / ink.size[0], lh / ink.size[1])
                nw = max(1, int(ink.size[0] * s))
                nh = max(1, int(ink.size[1] * s))
            asc_ink = asc_ink * nh / ink.size[1]
            ink = ink.resize((nw, nh), Image.LANCZOS)
        x = max(0, (lw - ink.size[0]) // 2)
        y = int(round(g["by"] - asc_ink))            # baseline-aligned…
        y = max(0, min(y, lh - ink.size[1]))         # …clamped into the slot
        # BC1 atlases carry no usable alpha — stock keeps an opaque black
        # background there, so the import must too (a transparent background
        # would punch 1-bit holes stock doesn't have).
        bg = (0, 0, 0, 255) if g.get("fmt") == 4 else (0, 0, 0, 0)
        cell = Image.new("RGBA", (lw, lh), bg)
        cell.alpha_composite(ink, (x, y))
        if g["rot"]:
            cell = cell.transpose(Image.ROTATE_270)  # back to as-stored (CW)
        if cell.size != (g["w"], g["h"]):
            cell = cell.resize((g["w"], g["h"]), Image.LANCZOS)
        slices[ch] = cell
    return slices, size, kept


def save_slices(font, slices):
    """Write imported glyph bitmaps over the extract's slice PNGs (the normal
    glyph-edit path: Write composites them into the atlas and splices only
    the changed BC blocks).  Returns the file count."""
    n = 0
    for ch, img in slices.items():
        g = font["glyphs"].get(ch)
        if g is None:
            continue
        img.save(_lp(g["abs"]))
        n += 1
    return n


def tint_slice(img, rgb):
    """Repaint one DISPLAY bitmap (:func:`load_slice` output) in *rgb*.

    Display bitmaps are uniform in a way the stored files are not: ``load_slice``
    has already turned a BC1 slot's brightness into alpha, so for both formats
    the alpha is the letter and replacing the ink is all there is to it.  That
    makes the preview a per-glyph operation, which is what lets the colour
    follow a selection down a 300-font list without repainting whole fonts."""
    Image = _pil()
    try:
        import numpy as np
    except Exception:
        return img
    arr = np.asarray(img.convert("RGBA")).copy()
    arr[..., 0], arr[..., 1], arr[..., 2] = (
        max(0, min(255, int(c))) for c in tuple(rgb)[:3])
    return Image.fromarray(arr, "RGBA")


def recolor_slices(font, rgb):
    """Repaint the font's CURRENT letters in *rgb*, keeping their shape.

    The colour picker used to reach only an imported desktop font, so choosing
    a colour with no font file did nothing at all — the swatch turned green and
    the preview stayed white.  This is the other half: take the letters that
    are already there (stock, or a previous import, or a hand edit) and change
    their ink.

    Shape comes from whichever channel actually carries it, which is
    format-specific:

    * BC3 (fmt 5) glyphs are a flat ink colour with the letter cut out of the
      ALPHA, so the ink is replaced outright and the alpha kept.  That is what
      lets an outline companion — a solid BLACK silhouette — be recoloured at
      all; scaling it by its own brightness would multiply by zero.
    * BC1 (fmt 4) glyphs have no usable alpha (ink sits on opaque black and the
      machine adds it), so BRIGHTNESS is the shape: the new colour is scaled by
      it, which keeps the anti-aliased edges and leaves the black background
      black.

    Returns ``{char: RGBA image}`` in the same as-stored orientation and size
    as :func:`rasterize_ttf`, so :func:`save_slices` writes it unchanged."""
    Image = _pil()
    try:
        import numpy as np
    except Exception:
        raise FontError("Recolouring needs numpy, which isn't available here.")
    r, g_, b = (max(0, min(255, int(c))) for c in tuple(rgb)[:3])
    out = {}
    for ch, gl in font["glyphs"].items():
        try:
            img = Image.open(_lp(gl["abs"])).convert("RGBA")
        except (OSError, ValueError):
            continue
        arr = np.asarray(img).astype(np.float32)
        alpha = arr[..., 3]
        lum = arr[..., :3].max(axis=2)
        # A fmt-5 slot whose alpha is flat carries no shape there after all;
        # fall back to brightness rather than flooding the whole cell.
        by_alpha = gl.get("fmt") != 4 and alpha.min() != alpha.max()
        new = arr.copy()
        if by_alpha:
            new[..., 0], new[..., 1], new[..., 2] = r, g_, b
        else:
            k = lum / 255.0
            new[..., 0], new[..., 1], new[..., 2] = r * k, g_ * k, b * k
            new[..., 3] = 255 if gl.get("fmt") == 4 else alpha
        out[ch] = Image.fromarray(new.clip(0, 255).astype("uint8"), "RGBA")
    if not out:
        raise FontError("None of this font's letter files could be read.")
    return out


def blank_slices(font):
    """Slice bitmaps that draw NOTHING, one per glyph — how a font is removed
    from the screen without touching anything else.

    "Nothing" is format-specific: a BC3 (fmt 5) slot goes fully transparent,
    while a BC1 (fmt 4) slot has no usable alpha and must go opaque BLACK
    instead, because the machine adds BC1 art to the frame and black adds
    zero.  Punching transparency into a BC1 slot would instead write 1-bit
    holes the stock atlas doesn't have."""
    Image = _pil()
    out = {}
    for ch, g in font["glyphs"].items():
        bg = (0, 0, 0, 255) if g.get("fmt") == 4 else (0, 0, 0, 0)
        out[ch] = Image.new("RGBA", (max(1, int(g["w"])),
                                     max(1, int(g["h"]))), bg)
    return out


def clear_font(font):
    """Blank every glyph of *font* on disk.  Returns the file count.

    This is a tester's "removing the shadow font in total": a title is drawn as an
    outline instance UNDER a fill instance, so restyling only the fill leaves
    the ORIGINAL typeface's black silhouette behind the new letters — the
    "strange inconsistent black border" he could not place.  Blanking the
    companion removes it, and the imported font's own Outline setting can draw
    a new one.  Reversible with :func:`revert_slices`."""
    return save_slices(font, blank_slices(font))


def revert_slices(assets_dir, font):
    """Restore a font's slice PNGs by re-cutting them from their atlas PNGs
    (which stay pristine on disk — glyph edits are composited in memory at
    Write).  Returns the file count."""
    Image = _pil()
    atlases = {}
    n = 0
    for g in font["glyphs"].values():
        arel = g.get("atlas_rel")
        if not arel:
            continue
        atlas = atlases.get(arel)
        if atlas is None:
            try:
                atlas = atlases[arel] = Image.open(_lp(os.path.join(
                    assets_dir, "images", *arel.split("/")))).convert("RGBA")
            except OSError:
                continue
        tile = atlas.crop((g["x"], g["y"], g["x"] + g["w"], g["y"] + g["h"]))
        try:
            tile.save(_lp(g["abs"]))
            n += 1
        except OSError:
            pass
    return n


# ---------------------------------------------------------------------------
# Outline companions
# ---------------------------------------------------------------------------
#
# A Stern title is drawn TWICE: an outline instance, then a fill instance on
# top of it at the same spot (proven on the AWARD popup, whose two instances
# are `Instance_AwardTitle_Outline` and `Instance_AwardTitle`).  The outline
# comes from its OWN glyph table — `Stern_CCZoinks_OUTLINE4`,
# `Stern_Impact_Outline`, `Blackmoor_Outline` — whose glyphs are fattened BLACK
# silhouettes of the same letters, and 246 of TMNT's 282 font-bearing scenes
# carry one.
#
# So restyling the body font alone leaves the OLD typeface's silhouette drawn
# behind the new letters.  That is a tester's "strange inconsistent black border",
# his "everything else from white as black", and his "i do still see font
# glyphs on some places" — one cause, three symptoms, and no way to find it
# from the Fonts window because the companion is listed as an unrelated font.

_OUTLINE_RE = re.compile(r"^(?P<base>.+?)[_ ]?(?:OUTLINE|Outline)\d*(?:_\d+)?$")


def outline_base(name):
    """The body-font name an outline companion belongs to, or ``""``.

    Name-driven, and that is a deliberate limit: the suffix is Stern's
    authoring convention and could differ per game, so :func:`outline_companion`
    only ever accepts a match that is CORROBORATED by the two fonts appearing
    in the same scenes."""
    m = _OUTLINE_RE.match((name or "").strip())
    base = m.group("base").strip(" _") if m else ""
    return base if base and base.lower() != (name or "").strip().lower() else ""


def _scene_index(assets_dir, fonts):
    """``{font key: frozenset of scene card paths}`` in one pass over
    ``radium_images.txt`` (per-font scanning is O(fonts x rows), and a card has
    300+ fonts)."""
    path = os.path.join(assets_dir, "images", "scene_textures",
                        "radium_images.txt")
    by_atlas = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line or line.startswith("#"):
                    continue
                cols = line.rstrip("\r\n").split("\t")
                if len(cols) >= 2:
                    by_atlas.setdefault(cols[0], set()).add(cols[1])
    except OSError:
        return {}
    out = {}
    for fo in fonts:
        s = set()
        for a in fo["atlas_rels"]:
            s |= by_atlas.get(a, set())
        out[fo["key"]] = frozenset(s)
    return out


def _metric_match(a, b, tol=0.51):
    """How much of two fonts' shared alphabet has the SAME logical box.

    An outline companion is baked at its body font's size and carries the body
    font's metrics verbatim — measured on TMNT, `Stern_CCZoinks_OUTLINE6` and
    `Stern_CCZoinks` at 66px agree on lw/lh/by to the pixel for every letter,
    while the same typeface at another size does not.  Only the STORED bitmap
    is bigger, which is the outline spread.  So this, not the name and not the
    size label, is what says two fonts are the same letters."""
    shared = set(a["glyphs"]) & set(b["glyphs"])
    hits = tot = 0
    for ch in shared:
        ga, gb = a["glyphs"][ch], b["glyphs"][ch]
        if ga["lh"] <= 1 or gb["lh"] <= 1:
            continue
        tot += 1
        if (abs(ga["lw"] - gb["lw"]) < tol and abs(ga["lh"] - gb["lh"]) < tol
                and abs(ga["by"] - gb["by"]) < tol):
            hits += 1
    return (hits / tot) if tot else 0.0


def outline_companions(assets_dir, fonts, min_metric=0.6):
    """``{body font key: companion font}`` for every outline pair in *fonts*.

    Three things must agree before two fonts are called a pair, because acting
    on this modifies a font the user did not select:

    1. the name is a body font's name plus an outline suffix (Stern's
       convention — necessary, nowhere near sufficient);
    2. they are drawn in at least one scene TOGETHER;
    3. most of their shared letters have the identical logical box
       (:func:`_metric_match`), which is what actually makes them the same
       letters at the same size.

    Rule 3 is what stops a 54px outline being handed to an 88px body just
    because that body appears in more scenes.  A companion nothing corroborates
    (TMNT's `Blackmoor_Outline`, whose body font is on no shared screen) is
    simply left unpaired rather than guessed at."""
    scenes = _scene_index(assets_dir, fonts)
    if not scenes:
        return {}
    bodies = {}
    for fo in fonts:
        if not outline_base(fo.get("name")):
            bodies.setdefault((fo.get("name") or "").strip(), []).append(fo)
    out = {}
    for fo in fonts:
        base = outline_base(fo.get("name"))
        if not base:
            continue
        mine = scenes.get(fo["key"], frozenset())
        best = None
        for cand in bodies.get(base, ()):
            shared = len(mine & scenes.get(cand["key"], frozenset()))
            if not shared:
                continue
            m = _metric_match(fo, cand)
            if m < min_metric:
                continue
            rank = (m, shared, -abs(cand["px"] - fo["px"]))
            if best is None or rank > best[0]:
                best = (rank, cand)
        if best is not None:
            out[best[1]["key"]] = fo
    return out


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------
#
# "Revert" means back to STOCK (re-cut from the atlas).  That is not undo: a
# user two imports deep who wants the previous one back has nowhere to go, and
# "Revert all fonts" would otherwise be an unrecoverable click after an
# afternoon of restyling.  Slices are tiny — 27,567 of them total 20 MB on a
# TMNT project, 738 bytes each — so the previous bytes can simply be kept.

def snapshot_fonts(fonts, progress=None):
    """``{abs path: bytes or None}`` for every glyph slice of *fonts*, as they
    are on disk right now.  ``None`` records a file that does not exist yet, so
    restoring can delete it again.

    *progress* is called ``(done, total)`` per font.  It is worth having: the
    bytes are trivial (20 MB for a whole project) but the FILE COUNT is not —
    27,567 slices read cold off a OneDrive folder took 35 s here, against 1 s
    once the cache was warm."""
    snap = {}
    for i, fo in enumerate(fonts):
        if progress:
            progress(i, len(fonts))
        for g in fo["glyphs"].values():
            p = g["abs"]
            if p in snap:
                continue
            try:
                with open(_lp(p), "rb") as f:
                    snap[p] = f.read()
            except OSError:
                snap[p] = None
    return snap


def snapshot_bytes(snap):
    """How much memory a snapshot holds, so a caller can bound its history."""
    return sum(len(v) for v in snap.values() if v)


def restore_snapshot(snap):
    """Put a :func:`snapshot_fonts` result back on disk.  Returns the count of
    files restored."""
    n = 0
    for path, data in snap.items():
        try:
            if data is None:
                if os.path.isfile(_lp(path)):
                    os.remove(_lp(path))
                    n += 1
                continue
            with open(_lp(path), "wb") as f:
                f.write(data)
            n += 1
        except OSError:
            continue
    return n


def scenes_for_font(assets_dir, font):
    """The radium scene files whose atlases this font draws from, via
    ``radium_images.txt`` (one row per on-card occurrence).  Returns sorted
    unique card paths."""
    path = os.path.join(assets_dir, "images", "scene_textures",
                        "radium_images.txt")
    if not os.path.isfile(path):
        return []
    want = set(font["atlas_rels"])
    out = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) >= 2 and cols[0] in want:
                out.add(cols[1])
    return sorted(out)


# ---------------------------------------------------------------------------
# Which scenes a font edit lands in ("scope")
# ---------------------------------------------------------------------------
#
# Scenes embed their own copy of every atlas, but identical copies extract to
# ONE PNG (see ``extract_radium_images``), so by default editing a font
# rewrites it in every scene that uses it — usually what you want ("restyle
# the game"), sometimes not ("restyle only the training scene", a tester).
#
# The scope file is that opt-out: rows of ``atlas_rel <TAB> radium card path``
# naming the ONLY scenes an atlas's edits may be written to.  An atlas with no
# rows keeps the all-occurrences default, so the file is absent until someone
# narrows a font, and deleting it restores stock behaviour.
#
# Scope selects WHERE one set of glyph bitmaps lands; it cannot give two
# scenes DIFFERENT versions of the same font (that needs per-scene glyph PNGs,
# which the content-deduped extract has no room for).

SCOPE_MANIFEST = os.path.join("images", "scene_textures", "glyph_scope.txt")

_SCOPE_HEADER = (
    "# Font scope: limits an atlas's glyph edits to the scenes listed here.\n"
    "# An atlas with no row here is written to EVERY scene that uses it.\n"
    "# atlas_rel\tradium card path\n")


def load_scopes(assets_dir):
    """``{atlas_rel: set(radium card paths)}`` from the scope file — the
    atlases whose edits are limited to specific scenes.  Empty dict when no
    font has been narrowed (the normal case)."""
    path = os.path.join(assets_dir, SCOPE_MANIFEST)
    out = {}
    if not os.path.isfile(path):
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if not line or line.startswith("#"):
                    continue
                cols = line.split("\t")
                if len(cols) >= 2 and cols[0] and cols[1]:
                    out.setdefault(cols[0], set()).add(cols[1])
    except OSError:
        return {}
    return out


def get_font_scope(assets_dir, font):
    """The scenes *font*'s edits are limited to, or ``None`` when it applies
    to every scene that uses it (the default).  A font spanning several atlas
    pages is scoped as a whole, so the union is the answer."""
    scopes = load_scopes(assets_dir)
    cards = set()
    scoped = False
    for arel in font["atlas_rels"]:
        got = scopes.get(arel)
        if got:
            scoped = True
            cards |= got
    return sorted(cards) if scoped else None


def set_font_scope(assets_dir, font, cards):
    """Limit *font*'s glyph edits to the scene card paths *cards*; a falsy
    *cards* clears the limit (back to every scene that uses the font).

    Rewrites the scope file preserving every OTHER atlas's rows.  Returns the
    number of rows written for this font."""
    path = os.path.join(assets_dir, SCOPE_MANIFEST)
    mine = set(font["atlas_rels"])
    keep = []
    for arel, paths in sorted(load_scopes(assets_dir).items()):
        if arel not in mine:
            keep.extend((arel, p) for p in sorted(paths))
    rows = [(arel, p) for arel in sorted(mine) for p in sorted(cards or ())]
    keep.extend(rows)
    if not keep:
        try:
            os.remove(path)
        except OSError:
            pass
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(_SCOPE_HEADER)
        for arel, p in keep:
            f.write("%s\t%s\n" % (arel, p))
    return len(rows)
