"""Render Spike 2 radium font text, and fit a desktop font into a glyph table.

Works entirely from an extract folder (no card needed): the per-character
glyph slice PNGs under ``images/scene_textures/glyphs/<atlas stem>/`` plus the
``glyph_images.txt`` manifest, whose trailing metrics columns (rot, glyph_w,
glyph_h, bearing_x, bearing_y, advance — appended by the same release that
added this module) carry the radium glyph-record layout floats.  See
``radium.py``'s format comment for how those were derived.

Two jobs, both feeding the GUI's Font Preview / Import window (Peter):

* :func:`render_text` — composite a string exactly the way the game lays it
  out (pen + bearing X, baseline − bearing Y, advance), reading the CURRENT
  slice PNGs so pending glyph edits show up live.  On an extract made before
  the metrics columns existed it falls back to approximate layout
  (``font["has_metrics"]`` is False — the caller should suggest re-extracting).

* :func:`rasterize_ttf` — fit a TTF/OTF font into an existing glyph table:
  one uniform pixel size chosen so every character's ink fits its atlas slot
  (the hard part of font swaps done by hand — Peter's turtle font), each glyph
  baseline-aligned into its slot and returned at as-stored orientation, ready
  to save over the slice PNGs (Write then splices only the changed BC blocks).

The game lays text out with the METRICS STORED IN THE RADIUM, which an import
does not touch — so spacing keeps the original font's rhythm and the swap is
size-neutral.  Rotated slots (``rot``) are un-rotated for rendering and
re-rotated on import (stored = upright turned 90° clockwise).
"""

import os

GLYPH_MANIFEST = os.path.join("images", "scene_textures", "glyph_images.txt")
LINE_GAP = 2          # extra px between lines (display nicety, not from card)


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
            fo = fonts.get(key)
            if fo is None:
                fo = fonts[key] = {
                    "key": key, "name": name, "atlas_rels": [],
                    "glyphs": {}, "has_metrics": has_metrics,
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
            }
    out = []
    for fo in fonts.values():
        gs = [g for g in fo["glyphs"].values() if g["lh"] > 1]
        fo["ascent"] = int(round(max((g["by"] for g in gs), default=8)))
        fo["descent"] = max(0, int(round(
            max((g["lh"] - g["by"] for g in gs), default=0))))
        fo["px"] = fo["ascent"] + fo["descent"]
        out.append(fo)
    out.sort(key=lambda fo: (fo["name"].lower(), -fo["px"]))
    return out


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
    img = image if image is not None else Image.open(glyph["abs"])
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
        for ch in line:
            g = font["glyphs"].get(ord(ch))
            if g is None or g["lh"] <= 1:
                if g is None and ch != " ":
                    missing.add(ch)
                pen += (g["adv"] if g is not None else sp_adv) + tracking
                continue
            try:
                img = loader(g)
            except (OSError, FontError):
                missing.add(ch)
                pen += g["adv"] + tracking
                continue
            x = pen + g["bx"]
            y = base_y - g["by"]
            placed.append((x, y, img))
            min_x = min(min_x, x)
            max_x = max(max_x, x + img.size[0], pen + g["adv"])
            pen += g["adv"] + tracking
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
    plain alpha weighting would average the ink into gray.  White when
    unreadable."""
    try:
        import numpy as np
    except Exception:
        return (255, 255, 255)
    gs = sorted((g for g in font["glyphs"].values() if g["lh"] > 1),
                key=lambda g: -(g["w"] * g["h"]))[:samples]
    tot = np.zeros(3)
    wsum = 0.0
    for g in gs:
        try:
            arr = np.asarray(load_slice(g), dtype=float)
        except (OSError, FontError):
            continue
        lum = arr[..., :3].max(axis=2) / 255.0
        w2 = (arr[..., 3] / 255.0) * lum * lum
        ws = w2.sum()
        if ws <= 0:
            continue
        tot += (arr[..., :3] * w2[..., None]).sum(axis=(0, 1))
        wsum += ws
    if wsum <= 0:
        return (255, 255, 255)
    return tuple(int(round(c)) for c in (tot / wsum))


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


def fit_size(measure, slots, lo=2, hi=512):
    """Largest integer size for which ``measure(size)`` — ``{char: (ink_w,
    ink_h) or None}`` — fits every CORE slot's upright box (letters/digits;
    see :func:`_core_chars`).  0 when even *lo* doesn't fit.  Pure bisection
    so the sizing rule is unit-testable apart from any rasterizer."""
    core = _core_chars(slots)

    def ok(size):
        inks = measure(size)
        for ch, g in core.items():
            ink = inks.get(ch)
            if ink is None:
                continue                    # char unavailable: keep original
            if ink[0] > g["lw"] or ink[1] > g["lh"]:
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
                  size_scale=1.0):
    """Fit the desktop font at *ttf_path* into *font*'s glyph slots.

    Picks ONE uniform pixel size — the largest at which every character's ink
    (including any outline stroke) fits its slot's upright box, scaled by
    *size_scale* (≤1 to taste) — then renders each character baseline-aligned
    into its slot, clamped inside it, centered horizontally.  Characters the
    TTF cannot draw keep their original bitmaps and are reported.

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

    size = fit_size(measure, slots)
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
        if ink.size[0] > lw or ink.size[1] > lh:
            # getbbox measured, the raster can bleed a px past it — shrink
            s = min(lw / ink.size[0], lh / ink.size[1])
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
        img.save(g["abs"])
        n += 1
    return n


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
                atlas = atlases[arel] = Image.open(os.path.join(
                    assets_dir, "images", *arel.split("/"))).convert("RGBA")
            except OSError:
                continue
        tile = atlas.crop((g["x"], g["y"], g["x"] + g["w"], g["y"] + g["h"]))
        try:
            tile.save(g["abs"])
            n += 1
        except OSError:
            pass
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
