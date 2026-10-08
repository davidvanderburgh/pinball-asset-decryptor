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

_LOCK = threading.Lock()
_FONTS = {}        # assets_dir -> (manifest stamp, {font key: font})
_ART = {}          # atlas path -> ((mtime, size), coloured?)


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
    box off; ``{"font_picture": rel, "font_pictures": [rel, ...], "font": name}`` for a line
    in a font with colours of its own (its switch is those pictures', every one of them:
    :func:`font_pictures`); ``None`` for a node that draws no line of its own (a drop shadow,
    which takes the colour of the line it copies)."""
    from ...core import colour_profile as cp
    oid, o = _text_of(man, n)
    if o is None:
        return None
    fonts = fonts if fonts is not None else fonts_by_key(assets_dir)
    font = fonts.get(o.get("font") or "")
    pics = font_pictures(assets_dir, font) if font is not None else []
    if pics:
        return {"font_picture": pics[0], "font_pictures": list(pics),
                "font": font.get("name") or o.get("font_name") or ""}
    rel = cp.text_rel(card, n["id"])
    if n.get("added"):
        op = next((op for op in ops or () if op.get("op") == "add_text"
                   and op.get("id") == n["id"]), None)
        if op is None:
            return None
        own = op.get("color")
        return {"line": True, "on": bool(own), "own": own is not None, "rel": rel,
                "added": True}
    if data is None:
        from ...core import staged_changes
        data = staged_changes.load(assets_dir)
    if not data.get(cp.STOCK_IMAGES_KEY):
        return {"locked": True, "line": True}
    return {"line": True, "on": rel in cp.text_lines_on(assets_dir, data), "own": True,
            "rel": rel, "stock": True}


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
    (the Text white), and each other node drawing that Text keeps its look."""
    from ...core import colour_profile as cp, staged_changes
    from . import text_colors
    if not assets_dir or man is None:
        return [], {}
    if data is None:
        data = staged_changes.load(assets_dir)
    fonts = fonts if fonts is not None else fonts_by_key(assets_dir)
    if record is None:
        record = load_record(assets_dir)
    rec = record.get(card) if isinstance(record.get(card), dict) else {}
    resolve = cp.asset_resolver(assets_dir, data)
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

    edits, written = {}, {}

    def put(nid, rgb=None, col=None, base_rgb=None, base_col=None):
        e = edits.setdefault(nid, {"op": "line_colour", "node": nid})
        w = written.setdefault(nid, {})
        if rgb is not None:
            e["rgb"] = [round(v, 4) for v in rgb]
            w.update(rgb=e["rgb"], base_rgb=[round(v, 4) for v in base_rgb])
        if col is not None:
            e["col"] = col
            w.update(col=col, base_col=base_col)

    for n in nodes:
        oid, o = _text_of(man, n)
        if o is None:
            continue
        sw = line_switch(assets_dir, card, man, n, ops, data, fonts)
        prof = (resolve("text", sw["rel"])
                if bake and sw and sw.get("line") and sw.get("on") else None)
        base_rgb, base_col = base_of(n, o)
        if prof is None:
            # off (or nothing to correct): a line a Write corrected gets its colours back
            w = rec.get(str(n["id"])) or {}
            if "rgb" in w and _close([float(v) for v in o["rgba"][:3]], w["rgb"]):
                edits.setdefault(n["id"], {"op": "line_colour", "node": n["id"]})["rgb"] = \
                    [float(v) for v in w["base_rgb"]]
            if "col" in w and _same_col(n.get("col"), w["col"]):
                edits.setdefault(n["id"], {"op": "line_colour", "node": n["id"]})["col"] = \
                    w["base_col"]
            continue
        steps = _steps(base_col)
        if o.get("styled"):
            col = [[f, corrected(prof, m[:3]) + [m[3]], a] for f, m, a in steps]
            if base_col or not _white(col):
                put(n["id"], col=col, base_col=base_col)
            continue
        shared = len(users.get(oid) or ()) > 1
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
    return list(edits.values()), written


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
