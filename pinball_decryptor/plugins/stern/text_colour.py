"""The individual files colour profile on a line of text in a scene (PAD-438, DragonRR).

A Spike 2 line of text is its font's letters (glyph pictures cut from an atlas) times the
colours the scene gives it: the Text's own RGBA (which a styled game font ignores) and its
node's colour track.  So what a line looks like comes from one of two places:

* most fonts have WHITE letters (Godzilla's GameFont_Primary, every plain font) and the
  colour is the line's own.  A line switched on gets the profile in that colour, the way a
  picture's pixels get it: :func:`line_ops` turns each switched-on line into a
  ``line_colour`` scene edit (:mod:`scene_edit`) that SETS the corrected values, worked out
  from the project's scene, so the preview and every Write apply the very same numbers and
  a Write onto a card built with them changes nothing;
* a font whose letters carry their own colours (Godzilla's orange GameFont_Secondary) has
  them in its atlas, a picture shared by every line drawn in that font, in every scene.  Its
  switch IS that picture's (the Images tab's, with its lock and unlock; every one of the
  font's pictures, when its letters fill several): a line's colour cannot reach colours that
  live in the letters (:func:`font_pictures`).

A line's corrected colour is a number in the scene, so a project read again off a card
built with it would see the corrected number and correct it twice.  The Write keeps what it
wrote (:data:`RECORD`): a line that still shows it is worked out from the colour it had
before, and one switched off again gets that colour back.

PAD-514 (DragonRR: "a facility to directly control text colour"): a line can have a colour
of its own instead, set on the Scenes Font bar (a ``text_colour`` scene edit,
:func:`own_colours`).  It is drawn in exactly that colour and the profile does not reach it:
white is already full red, so the profile's red sliders could never turn white letters red.
It goes into the scene the same way, as ``line_colour`` edits (and, for a font whose letters
carry their own colours, the line's own copy of the font with its letters in that colour).
"""

import json
import os
import threading

#: What the Writes put on lines of text, per scene: ``{card: {node id: {"rgb", "base_rgb",
#: "col", "base_col"}}}`` (each pair only where it was set), next to ``scene_edits.json``.
RECORD = ("images", "scene_textures", "text_colours_written.json")

#: A share of a font atlas's solid pixels with a colour of their own above this (a
#: channel spread of :data:`_SPREAD` or more) makes it a coloured font.  GameFont_Secondary
#: is 0.55; white and grey fonts are 0.
_COLOURED_SHARE = 0.02
_SPREAD = 40

#: the colour track a node with none of its own has
_NEUTRAL = [1, [1.0, 1.0, 1.0, 1.0], [0.0, 0.0, 0.0, 0.0]]
_TOL = 2e-3

#: PAD-514: a font whose letters carry their own colours is drawn in a line's own colour by
#: their light and shade: their brightest is the colour, this far down the letters' pixels
#: (so a few white glints do not set it), never below the floor (a dark font stays a gain the
#: profile maths takes)
_PEAK_SHARE = 0.98
_PEAK_FLOOR = 0.25

_LOCK = threading.Lock()
_FONTS = {}        # assets_dir -> (manifest stamp, {font key: font})
_ART = {}          # atlas path -> ((mtime, size), coloured?)
_PEAKS = {}        # atlas path -> ((mtime, size), brightest letter luma 0..1)


# ---------------------------------------------------------------------------------------------
# fonts
# ---------------------------------------------------------------------------------------------
def fonts_by_key(assets_dir):
    """``{font key: font}`` (:func:`fontrender.load_fonts`), read again when the glyph
    manifest changes."""
    from . import fontrender as fr
    try:
        st = os.stat(os.path.join(assets_dir, fr.GLYPH_MANIFEST))
    except (OSError, TypeError):
        return {}
    stamp = (st.st_mtime_ns, st.st_size)
    with _LOCK:
        got = _FONTS.get(assets_dir)
        if got is not None and got[0] == stamp:
            return got[1]
    try:
        by = {f["key"]: f for f in fr.load_fonts(assets_dir)}
    except Exception:                                # noqa: BLE001
        by = {}
    with _LOCK:
        _FONTS[assets_dir] = (stamp, by)
    return by


def atlas_rels(font):
    """The pictures (rels under ``images/``) *font*'s letters are cut from, at every size
    it is drawn at."""
    out = []
    for f in [font or {}] + list(((font or {}).get("sizes") or {}).values()):
        for r in f.get("atlas_rels") or ():
            r = str(r).replace("\\", "/")
            if r not in out:
                out.append(r)
    return out


def _art_coloured(assets_dir, rel):
    """Are the solid pixels of atlas *rel* coloured, not white or grey?  Read from its
    pristine copy when there is one: a build may have corrected the project's file (a black
    and white profile would make it read grey)."""
    from ...core import staged_originals
    path = (staged_originals.snapshot_path(assets_dir, "images/" + rel)
            or os.path.join(assets_dir, "images", *rel.split("/")))
    try:
        st = os.stat(path)
    except OSError:
        return False
    stamp = (st.st_mtime_ns, st.st_size)
    with _LOCK:
        got = _ART.get(path)
        if got is not None and got[0] == stamp:
            return got[1]
    coloured = False
    try:
        import numpy as np
        from PIL import Image
        with Image.open(path) as im:
            arr = np.asarray(im.convert("RGBA"))
        solid = arr[..., 3] > 128
        if int(solid.sum()) >= 16:
            rgb = arr[..., :3][solid].astype(np.int16)
            spread = rgb.max(axis=1) - rgb.min(axis=1)
            coloured = float((spread >= _SPREAD).mean()) > _COLOURED_SHARE
    except Exception:                                # noqa: BLE001
        coloured = False
    with _LOCK:
        _ART[path] = (stamp, coloured)
    return coloured


def font_picture(assets_dir, font):
    """The atlas (rel under ``images/``) of a font whose letters carry their own colours, or
    ``None`` for a font of white letters the scene colours."""
    rels = font_pictures(assets_dir, font)
    return rels[0] if rels else None


def font_pictures(assets_dir, font):
    """EVERY picture (rels under ``images/``) a font whose letters carry their own colours
    cuts them from, or ``[]`` for a font of white letters.  A big font fills several:
    Godzilla's GameFont_Secondary keeps A-F on one, G, H, K and M-Z on the next and most of
    the small letters on a third (PAD-451), so a line's colours are in all of them."""
    rels = atlas_rels(font)
    if rels and any(_art_coloured(assets_dir, r) for r in rels):
        return rels
    return []


_SCENES = {}       # assets_dir -> ((mtime, size), {atlas rel: number of scenes})


def font_scenes(assets_dir, rels):
    """How many of the card's scenes draw from any of the pictures *rels* (rels under
    ``images/``): every line in that font, in each, shares their colours (PAD-451).  From
    the extract's ``radium_images.txt``, one row per picture per scene; 0 without it."""
    path = os.path.join(assets_dir or "", "images", "scene_textures", "radium_images.txt")
    try:
        st = os.stat(path)
    except OSError:
        return 0
    stamp = (st.st_mtime_ns, st.st_size)
    with _LOCK:
        got = _SCENES.get(assets_dir)
    if got is None or got[0] != stamp:
        by = {}
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    cols = line.rstrip("\r\n").split("\t")
                    if len(cols) >= 2 and cols[0] and not cols[0].startswith("#"):
                        by.setdefault(cols[0], set()).add(cols[1])
        except OSError:
            return 0
        got = (stamp, by)
        with _LOCK:
            _SCENES[assets_dir] = got
    cards = set()
    for r in rels or ():
        cards |= got[1].get(r) or set()
    return len(cards)


# ---------------------------------------------------------------------------------------------
# a line's own colour (PAD-514)
# ---------------------------------------------------------------------------------------------
def own_colours(ops):
    """``{node id: op}`` of the lines *ops* give a colour of their own (``text_colour``
    edits: ``rgb`` 0..1 as drawn, ``pick`` the colour picked and ``bright`` its brightness %,
    as the Font bar shows them); the last one of a line counts."""
    out = {}
    for op in ops or ():
        if op.get("op") != "text_colour" or op.get("node") is None:
            continue
        try:
            rgb = [min(1.0, max(0.0, float(c))) for c in op["rgb"][:3]]
        except (KeyError, TypeError, ValueError):
            continue
        if len(rgb) == 3:
            out[op["node"]] = dict(op, rgb=rgb)
    return out


def shade(rgb, bright):
    """*rgb* (0..1) at *bright* % (the Font bar's Brightness, 0..100): 100 is the colour
    itself, below it darker down to black.  (Lighter is toward the middle of the wheel: a
    line is its letters times its colour, which cannot go past full.)"""
    b = min(100.0, max(0.0, float(bright))) / 100.0
    return [round(float(c) * b, 4) for c in rgb[:3]]


def _art_peak(assets_dir, rel):
    """The brightest of atlas *rel*'s letter pixels, as luma 0..1 (:data:`_PEAK_SHARE` of
    the way up), from its pristine copy as :func:`_art_coloured` reads it."""
    from ...core import staged_originals
    from ...core.colour_profile import _LUMA
    path = (staged_originals.snapshot_path(assets_dir, "images/" + rel)
            or os.path.join(assets_dir, "images", *rel.split("/")))
    try:
        st = os.stat(path)
    except OSError:
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    with _LOCK:
        got = _PEAKS.get(path)
        if got is not None and got[0] == stamp:
            return got[1]
    peak = None
    try:
        import numpy as np
        from PIL import Image
        with Image.open(path) as im:
            arr = np.asarray(im.convert("RGBA"))
        solid = arr[..., 3] > 128
        if int(solid.sum()) >= 16:
            luma = arr[..., :3][solid].astype(np.float32) @ np.asarray(_LUMA, np.float32)
            peak = float(np.quantile(luma, _PEAK_SHARE)) / 255.0
    except Exception:                                # noqa: BLE001
        peak = None
    with _LOCK:
        _PEAKS[path] = (stamp, peak)
    return peak


def art_peak(assets_dir, font):
    """How bright a font whose letters carry their own colours is at its brightest (luma
    0..1, over all its pictures; 1.0 when none reads)."""
    peaks = [p for p in (_art_peak(assets_dir, r) for r in font_pictures(assets_dir, font))
             if p is not None]
    return max(_PEAK_FLOOR, max(peaks)) if peaks else 1.0


#: a saved text colour: a small text file of its own, one per colour, like a saved profile
COLOUR_FILE_HEAD = "# Pinball Asset Decryptor text color"


def save_colour_file(path, pick, bright=100):
    """Keep colour *pick* (``#rrggbb``) at *bright* % in the file *path*."""
    from . import text_colors
    rgb = text_colors.parse_hex(pick)
    if rgb is None:
        raise ValueError("not a color: %r" % (pick,))
    with open(path, "w", encoding="utf-8") as f:
        f.write("%s\ncolor %s\nbrightness %d\n" % (
            COLOUR_FILE_HEAD, text_colors.to_hex(rgb),
            int(round(min(100.0, max(0.0, float(bright)))))))


def read_colour_file(path):
    """``(#rrggbb, brightness %)`` kept in *path*, or None when it holds no colour.  A file
    with just a ``#rrggbb`` in it (written by hand) is that colour at 100 %."""
    from . import text_colors
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read(4096)
    except (OSError, UnicodeDecodeError):
        return None
    pick, bright = None, 100
    for line in text.splitlines():
        words = line.strip().split()
        if not words or words[0].startswith("#") and len(words) > 1:
            continue
        if words[0].lower() in ("color", "colour") and len(words) > 1:
            pick = text_colors.parse_hex(words[1])
        elif words[0].lower() == "brightness" and len(words) > 1:
            try:
                bright = int(round(min(100.0, max(0.0, float(words[1])))))
            except ValueError:
                pass
        elif pick is None and len(words) == 1:
            pick = text_colors.parse_hex(words[0])
    return (text_colors.to_hex(pick), bright) if pick is not None else None


def saved_colours(folders):
    """``[(name, path, #rrggbb, brightness %)]``: the text colours kept in *folders* (each
    ``.txt`` file holding one, by file name), the first folder's first."""
    out, seen = [], set()
    for d in folders or ():
        try:
            names = sorted(os.listdir(d), key=str.lower)
        except (OSError, TypeError):
            continue
        for name in names:
            path = os.path.join(d, name)
            key = os.path.normcase(os.path.abspath(path))
            if not name.lower().endswith(".txt") or key in seen:
                continue
            got = read_colour_file(path)
            if got is not None:
                seen.add(key)
                out.append((os.path.splitext(name)[0], path, got[0], got[1]))
    return out


def own_colour_profile(rgb, peak=1.0):
    """The profile that draws letters with colours of their own in *rgb* (0..1): their light
    and shade kept (black and white), their brightest (*peak*, :func:`art_peak`) the colour.
    Baked into the line's own copy of its font as any profile is (PAD-451)."""
    from ...core import colour_profile as cp
    k = 1.0 / max(_PEAK_FLOOR, min(1.0, float(peak)))
    lo, hi = cp.LIMITS["gain"]
    return cp.Profile(name="Own color", saturation=0.0,
                      gain=tuple(round(min(hi, max(lo, float(c) * k)), 4) for c in rgb[:3]))


# ---------------------------------------------------------------------------------------------
# the record of what was written
# ---------------------------------------------------------------------------------------------
def _record_path(assets_dir):
    return os.path.join(assets_dir, *RECORD)


def load_record(assets_dir):
    try:
        with open(_record_path(assets_dir), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def remember(assets_dir, card, entries):
    """Keep *entries* (``{node id: {...}}`` from :func:`line_ops`) for scene *card*.  An entry
    is never dropped: it only counts while a line still shows what it says was written."""
    if not assets_dir or not entries:
        return
    data = load_record(assets_dir)
    per = data.get(card) if isinstance(data.get(card), dict) else {}
    per.update({str(k): v for k, v in entries.items()})
    data[card] = per
    path = _record_path(assets_dir)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, sort_keys=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------------------------
# the maths
# ---------------------------------------------------------------------------------------------
def corrected(prof, rgb):
    """*rgb* (0..1) through *prof*, as a picture's pixel of that colour is."""
    import numpy as np
    px = np.asarray([[[int(round(min(1.0, max(0.0, float(c))) * 255.0))
                       for c in tuple(rgb)[:3]]]], np.uint8)
    return [round(float(v) / 255.0, 4) for v in prof.apply_array(px)[0, 0]]


def _close(a, b):
    return (a is not None and b is not None and len(a) == len(b)
            and all(abs(float(x) - float(y)) <= _TOL for x, y in zip(a, b)))


def _same_col(a, b):
    a, b = list(a or ()), list(b or ())
    if len(a) != len(b):
        return False
    for (fa, ma, aa), (fb, mb, ab) in zip(a, b):
        if int(fa) != int(fb) or not _close(ma, mb) or not _close(aa, ab):
            return False
    return True


def _steps(col):
    return [[int(f), [float(v) for v in m], [float(v) for v in a]]
            for f, m, a in (col or [_NEUTRAL])]


def _white(col):
    return all(abs(m[i] - 1.0) <= 1e-4 for _f, m, _a in _steps(col) for i in range(3))


def _text_of(man, n):
    for _s, oid in n["comps"]:
        o = man["objects"].get(str(oid)) or {}
        if o.get("kind") == "Text":
            return str(oid), o
    return None, None


def _walk(man):
    out, seen = [], set()

    def run(kids):
        for n in kids:
            out.append(n)
            for _s, oid in n["comps"]:
                o = man["objects"].get(str(oid)) or {}
                if o.get("kids") is not None and oid not in seen:
                    seen.add(oid)
                    run(o["kids"])
    run(man["root"]["kids"])
    return out


def line_switch(assets_dir, card, man, n, ops=(), data=None, fonts=None):
    """A line's colour switch, for the Layers list: ``{"line": True, "on", "own", "rel",
    "added" | "stock"}``; ``{"locked": True, "line": True}`` for a game line with the unlock
    box off; ``None`` for a node that draws no line of its own (a drop shadow, which takes the
    colour of the line it copies).  A line in a font with colours of its own has a switch of
    its own too (PAD-451: the Write gives it its own copy of the font, :mod:`font_copy`), with
    ``"art": True``, ``"font"`` (its name) and ``"font_pictures"`` (:func:`font_pictures`, the
    pictures every other line in the font shares)."""
    from ...core import colour_profile as cp
    oid, o = _text_of(man, n)
    if o is None:
        return None
    fonts = fonts if fonts is not None else fonts_by_key(assets_dir)
    font = fonts.get(o.get("font") or "")
    pics = font_pictures(assets_dir, font) if font is not None else []
    art = ({"art": True, "font": font.get("name") or o.get("font_name") or "",
            "font_pictures": list(pics)} if pics else {})
    rel = cp.text_rel(card, n["id"])
    if n.get("added"):
        op = next((op for op in ops or () if op.get("op") == "add_text"
                   and op.get("id") == n["id"]), None)
        if op is None:
            return None
        own = op.get("color")
        return dict({"line": True, "on": bool(own), "own": own is not None, "rel": rel,
                     "added": True}, **art)
    if data is None:
        from ...core import staged_changes
        data = staged_changes.peek(assets_dir)
    if not data.get(cp.STOCK_IMAGES_KEY):
        return dict({"locked": True, "line": True}, **art)
    # (cp.text_lines_on's test, looked up: Apply to all asks it of every line, PAD-471)
    slots = data.get(cp.TEXT_SLOTS_KEY)
    return dict({"line": True, "on": bool(isinstance(slots, dict) and slots.get(rel)),
                 "own": True, "rel": rel, "stock": True}, **art)


# ---------------------------------------------------------------------------------------------
# every line at once (PAD-471)
# ---------------------------------------------------------------------------------------------
#: the edits that change which lines a scene has, or a line's font (so whether its letters
#: carry colours of their own)
_LINE_OPS = ("add_text", "remove", "text_font")


def font_on(sw, data):
    """Do all of a line's font's pictures (*sw* :func:`line_switch`'s, a line in a font with
    colours of its own) have the profile attached on the Images tab?  Then every line in the
    font is corrected, this one too (PAD-451)."""
    from ...core import colour_profile as cp
    rels = (sw or {}).get("font_pictures") or []
    slots = data.get(cp.IMAGE_SLOTS_KEY)
    slots = slots if isinstance(slots, dict) else {}
    return bool(rels) and all(slots.get(r if r.startswith("images/") else "images/" + r)
                              for r in rels)


def font_looks(sw, data, resolve):
    """What each of a line's font's pictures (*sw* :func:`line_switch`'s, a line in a font
    with colours of its own) has baked in on the card: its profile, ``None`` where it is left
    as the game has it (switched off, or a profile that changes nothing).  *resolve* is
    :func:`colour_profile.asset_resolver`'s."""
    from ...core import colour_profile as cp
    slots = data.get(cp.IMAGE_SLOTS_KEY)
    slots = slots if isinstance(slots, dict) else {}
    out = []
    for r in (sw or {}).get("font_pictures") or []:
        r = r if r.startswith("images/") else "images/" + r
        out.append(resolve("images", r) if slots.get(r) else None)
    return out


def every_line(assets_dir, trees=None, data=None, fonts=None):
    """``{rel: switch}`` of every line of text in every scene of the project that is not
    locked, the ones added in Scenes too, as the user's edits leave them (PAD-471, DragonRR:
    Apply to all lines of text).  Each switch is :func:`line_switch`'s, a line in a font with
    colours of its own with ``"font_on"`` (:func:`font_on`).  *trees*: ``{card: stock
    manifest}``, read from the project when not given."""
    from ...core import staged_changes
    from . import scene_edit
    if not assets_dir:
        return {}
    if trees is None:
        try:
            with open(os.path.join(assets_dir, "images", "scene_textures", "scene_tree.json"),
                      encoding="utf-8") as f:
                trees = json.load(f)
        except (OSError, ValueError):
            trees = {}
    if data is None:
        data = staged_changes.peek(assets_dir)
    fonts = fonts if fonts is not None else fonts_by_key(assets_dir)
    edits = scene_edit.load(assets_dir)
    out = {}
    for card, man in (trees or {}).items():
        if not isinstance(man, dict) or "root" not in man:
            continue
        ops = edits.get(card) or []
        if any(op.get("op") in _LINE_OPS for op in ops):
            try:
                man, _n = scene_edit.apply_manifest(
                    man, scene_edit.to_apply(assets_dir, card, man, ops))
            except Exception:                        # noqa: BLE001
                pass                                 # its stock lines, as the game has them
        for n in _walk(man):
            sw = line_switch(assets_dir, card, man, n, ops, data, fonts)
            if sw is None or sw.get("locked"):
                continue
            if sw.get("art"):
                sw = dict(sw, font_on=font_on(sw, data))
            out[sw["rel"]] = sw
    return out


def put_line_switches(assets_dir, switches):
    """Lines' own switches set at once, ``{rel: True / False / None}`` (a game line: off and
    ``None`` are no switch at all; a line added in Scenes: its edit's ``color``), one save of
    each file.  Returns what each was, the same way (PAD-471: Apply to all lines of text, and
    its Undo).  A game line is switched only while the unlock box is ticked."""
    from ...core import colour_profile as cp, staged_changes
    from . import scene_edit
    if not assets_dir or not switches:
        return {}
    edits = scene_edit.load(assets_dir)
    added = {}
    for card, ops in edits.items():
        for op in ops:
            if op.get("op") == "add_text" and op.get("id") is not None:
                added[cp.text_rel(card, op["id"])] = op
    before, stock = {}, {}
    for rel, value in switches.items():
        rel = str(rel)
        op = added.get(rel)
        if op is not None:
            before[rel] = op.get("color")
            if value is None:
                op.pop("color", None)
            else:
                op["color"] = bool(value)
        elif "#" in rel:
            stock[rel] = value
    if any(rel in added for rel in before):
        scene_edit.save(assets_dir, edits)
    if stock:
        data = staged_changes.load(assets_dir)
        if data.get(cp.STOCK_IMAGES_KEY):
            m = data.get(cp.TEXT_SLOTS_KEY)
            m = dict(m) if isinstance(m, dict) else {}
            for rel, value in stock.items():
                before[rel] = True if m.get(rel) else None
                if value:
                    m[rel] = True
                else:
                    m.pop(rel, None)
            if m:
                data[cp.TEXT_SLOTS_KEY] = m
            else:
                data.pop(cp.TEXT_SLOTS_KEY, None)
            staged_changes.save(assets_dir, data)
    return before


def art_map(font):
    """``{char: picture rel}`` of *font*'s letters at every size: which of its pictures each
    is cut from, for a copy of it (``line_font``)."""
    out = {}
    for f in [font or {}] + list(((font or {}).get("sizes") or {}).values()):
        for ch, g in (f.get("glyphs") or {}).items():
            if g.get("atlas_rel"):
                out.setdefault(str(int(ch)), str(g["atlas_rel"]).replace("\\", "/"))
    return out


def line_ops(assets_dir, card, man, ops=(), data=None, fonts=None, record=None, bake=True):
    """``(edits, written)``: the ``line_colour`` scene edits that put the individual files
    profile into scene *card*'s switched-on lines of text, and what they write per node (for
    :func:`remember`).  *man* is the scene's manifest WITH the user's edits (*ops*, the
    stored list) applied.  Every edit sets absolute values.  *bake* False is the preview's
    Individual files switch off: every line is drawn in its own colours.

    A styled font's line (its Text colour ignored) is coloured by its node's colour track:
    each step's colour goes through the profile.  A plain font's line is its Text's colour
    times the track: with a white track (and no other node drawing the same Text) the Text's
    colour goes through it, size-neutral; otherwise the line's colours move into the track
    (the Text white), and each other node drawing that Text keeps its look.

    A line in a font whose letters carry their own colours (PAD-451) gets a ``line_font``
    edit instead: its own copy of the font, the profile baked into the copy's pictures, with a
    constant colour of its own (its track's; a plain font's Text colour) baked in first and
    set white, so the line looks as a picture of it would through the profile.

    A line given a colour of its own on the Font bar (PAD-514, :func:`own_colours`) is drawn
    in it whatever its switch, *bake* too: the colour is SET (each step of its track, keeping
    the step's opacity; a plain font's Text colour where that is size-neutral) and the profile
    is not applied to it.  In a font whose letters carry their own colours it gets its own
    copy of the font with them drawn in that colour by their light and shade."""
    from ...core import colour_profile as cp, staged_changes
    from . import text_colors
    if not assets_dir or man is None:
        return [], {}
    if data is None:
        data = staged_changes.peek(assets_dir)
    fonts = fonts if fonts is not None else fonts_by_key(assets_dir)
    if record is None:
        record = load_record(assets_dir)
    rec = record.get(card) if isinstance(record.get(card), dict) else {}
    resolve = cp.asset_resolver(assets_dir, data)
    exact = []                                    # the same, No change too (PAD-568)
    picks = text_colors.colors_for(assets_dir, card)
    nodes = _walk(man)
    users = {}
    for n in nodes:
        oid, _o = _text_of(man, n)
        if oid is not None:
            users.setdefault(oid, []).append(n)

    def base_of(n, o):
        """The node's colour track and its Text's colour as they were before any Write
        corrected them (the record), with a Text tab recolour on a plain font."""
        w = rec.get(str(n["id"])) or {}
        rgb = [float(v) for v in (o.get("rgba") or (1, 1, 1, 1))[:3]]
        if "rgb" in w and _close(rgb, w["rgb"]):
            rgb = [float(v) for v in w["base_rgb"]]
        col = n.get("col") or []
        if "col" in w and _same_col(col, w["col"]):
            col = w["base_col"]
        pick = picks.get(o.get("text"))
        if pick and not o.get("styled"):
            rgb = [c / 255.0 for c in pick[:3]]
        return rgb, _steps(col) if col else []

    edits, written, own_fonts = {}, {}, {}

    def put(nid, rgb=None, col=None, base_rgb=None, base_col=None):
        e = edits.setdefault(nid, {"op": "line_colour", "node": nid})
        w = written.setdefault(nid, {})
        if rgb is not None:
            e["rgb"] = [round(v, 4) for v in rgb]
            w.update(rgb=e["rgb"], base_rgb=[round(v, 4) for v in base_rgb])
        if col is not None:
            e["col"] = col
            w.update(col=col, base_col=base_col)

    # PAD-514: the lines with a colour of their own first, so a line the profile corrects
    # beside one of them in the same Text leaves it alone
    own = own_colours(ops)
    kept = set()
    for n in nodes:
        mine = own.get(n["id"])
        oid, o = _text_of(man, n) if mine else (None, None)
        if o is None:
            continue
        rgb = mine["rgb"]
        base_rgb, base_col = base_of(n, o)
        steps = _steps(base_col)
        shared = len(users.get(oid) or ()) > 1
        font = fonts.get(o.get("font") or "")
        if font is not None and font_pictures(assets_dir, font):
            # its letters' colours are in its font: its own copy, drawn in this colour
            if base_col and not _white(base_col):
                put(n["id"], col=[[f, [1.0, 1.0, 1.0, m[3]], a] for f, m, a in steps],
                    base_col=base_col)
            if not o.get("styled") and not shared and not _close(base_rgb, [1.0, 1.0, 1.0]):
                put(n["id"], rgb=[1.0, 1.0, 1.0], base_rgb=base_rgb)
            own_fonts[n["id"]] = {"op": "line_font", "node": n["id"], "mul": None,
                                  "profile": cp._profile_dict(own_colour_profile(
                                      rgb, art_peak(assets_dir, font))),
                                  "art": art_map(font)}
            written.setdefault(n["id"], {})["font"] = True
            continue
        if o.get("styled"):
            put(n["id"], col=[[f, list(rgb) + [m[3]], a] for f, m, a in steps],
                base_col=base_col)
            continue
        if not shared and _white(base_col):
            put(n["id"], rgb=rgb, base_rgb=base_rgb)
            continue
        # its colour goes into its track, the Text white; each other node drawing that Text
        # keeps its look
        put(n["id"], rgb=[1.0, 1.0, 1.0], col=[[f, list(rgb) + [m[3]], a] for f, m, a in steps],
            base_rgb=base_rgb, base_col=base_col)
        for s in users.get(oid) or ():
            if s is n or s["id"] in own or s["id"] in edits:
                continue
            _r, s_col = base_of(s, o)
            put(s["id"], col=[[f, [round(base_rgb[i] * m[i], 5) for i in range(3)] + [m[3]], a]
                              for f, m, a in _steps(s_col)], base_col=s_col)
            kept.add(s["id"])

    for n in nodes:
        if n["id"] in own:
            continue
        oid, o = _text_of(man, n)
        if o is None:
            continue
        sw = line_switch(assets_dir, card, man, n, ops, data, fonts)
        on = bool(bake and sw and sw.get("line") and sw.get("on"))
        prof = resolve("text", sw["rel"]) if on else None
        if (prof is None and on and sw.get("art")
                and any(p is not None for p in font_looks(sw, data, resolve))):
            # PAD-568 (DragonRR): No change on a line whose font's pictures are corrected
            # (Black and white on every image): its own copy of the font, as the game has it
            if not exact:
                exact.append(cp.asset_resolver(assets_dir, data, identity=True))
            prof = exact[0]("text", sw["rel"])
        base_rgb, base_col = base_of(n, o)
        if prof is None and n["id"] in kept:
            continue                              # it keeps its look beside one (PAD-514)
        if prof is None:
            # off (or nothing to correct): a line a Write corrected gets its colours back
            w = rec.get(str(n["id"])) or {}
            if w.get("font") and sw and sw.get("art"):
                # and its font: a card built with its own copy, read again (PAD-451)
                own_fonts[n["id"]] = {"op": "line_font", "node": n["id"], "off": True}
            if "rgb" in w and _close([float(v) for v in o["rgba"][:3]], w["rgb"]):
                edits.setdefault(n["id"], {"op": "line_colour", "node": n["id"]})["rgb"] = \
                    [float(v) for v in w["base_rgb"]]
            if "col" in w and _same_col(n.get("col"), w["col"]):
                edits.setdefault(n["id"], {"op": "line_colour", "node": n["id"]})["col"] = \
                    w["base_col"]
            continue
        steps = _steps(base_col)
        shared = len(users.get(oid) or ()) > 1
        if sw.get("art"):
            # PAD-451: its own copy of the font; a colour of its own that every frame keeps
            # is baked into the copy with the profile (a line sharing its Text keeps its own)
            mul = None
            if base_col and not shared and not _white(base_col) and len(
                    {tuple(round(m[i], 5) for i in range(3)) for _f, m, _a in steps}) == 1:
                mul = [round(v, 5) for v in steps[0][1][:3]]
                put(n["id"], col=[[f, [1.0, 1.0, 1.0, m[3]], a] for f, m, a in steps],
                    base_col=base_col)
            if not o.get("styled") and not shared and not _close(base_rgb, [1.0, 1.0, 1.0]):
                mul = [round((mul[i] if mul else 1.0) * base_rgb[i], 5) for i in range(3)]
                put(n["id"], rgb=[1.0, 1.0, 1.0], base_rgb=base_rgb)
            own_fonts[n["id"]] = {"op": "line_font", "node": n["id"],
                                  "profile": cp._profile_dict(prof), "mul": mul,
                                  "art": art_map(fonts.get(o.get("font") or ""))}
            written.setdefault(n["id"], {})["font"] = True
            continue
        if o.get("styled"):
            col = [[f, corrected(prof, m[:3]) + [m[3]], a] for f, m, a in steps]
            if base_col or not _white(col):
                put(n["id"], col=col, base_col=base_col)
            continue
        if not shared and _white(base_col):
            put(n["id"], rgb=corrected(prof, base_rgb), base_rgb=base_rgb)
            continue
        # the line's colours move into its track; the Text goes white
        col = [[f, corrected(prof, [base_rgb[i] * m[i] for i in range(3)]) + [m[3]], a]
               for f, m, a in steps]
        put(n["id"], rgb=[1.0, 1.0, 1.0], col=col, base_rgb=base_rgb, base_col=base_col)
        for s in users.get(oid) or ():
            if s is n or s["id"] in edits:
                continue
            ssw = line_switch(assets_dir, card, man, s, ops, data, fonts)
            if ssw and ssw.get("line") and ssw.get("on") and resolve("text", ssw["rel"]):
                continue                          # it gets its own correction
            _r, s_col = base_of(s, o)
            keep = [[f, [round(base_rgb[i] * m[i], 5) for i in range(3)] + [m[3]], a]
                    for f, m, a in _steps(s_col)]
            put(s["id"], col=keep, base_col=s_col)
    return list(edits.values()) + list(own_fonts.values()), written


def cards_with_lines(assets_dir, data=None):
    """The scenes (card paths) with a line of text switched on, or with one a Write corrected
    (it may need its colours back): the Write looks at these even with no other edit."""
    from ...core import colour_profile as cp
    from . import scene_edit
    out = {rel.rsplit("#", 1)[0] for rel in cp.text_lines_on(assets_dir, data)}
    for card, ops in scene_edit.load(assets_dir).items():
        if any(op.get("op") == "add_text" and op.get("color") for op in ops):
            out.add(card)
    out.update(k for k, v in load_record(assets_dir).items() if v)
    return out
