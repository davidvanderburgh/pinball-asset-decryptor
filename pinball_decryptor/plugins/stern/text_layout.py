"""The scene text-layout manifest: ``<assets>/text/layout.tsv``.

Where a line of scene text sits, how it is aligned and how big it is drawn
are all properties of the SCENE, not of the font — the ``scene.radium``
carries, per text keyframe, a rect and an alignment word, and bakes its own
glyph table for every face at the sizes it uses.  Moving a line, centring it
or making it 120 % bigger is therefore a size-neutral rewrite of those bytes,
the same shape as a colour edit (:mod:`text_colors`) on different bytes of the
same file.

This module is the file format only — which line of which scene the user
re-laid-out, and how::

    radium card path <TAB> string <TAB> dx <TAB> dy <TAB> align <TAB> size

``dx``/``dy`` are pixel offsets added to the line's rect (floats; empty or 0 =
unchanged), ``align`` is one of ``left``/``center``/``right`` (empty =
unchanged) and ``size`` is an integer percent of the size the scene bakes
(empty or 100 = unchanged).  A row every one of whose fields is neutral is
not an edit and is never written.
"""

import os

RELDIR = "text"
FILENAME = "layout.tsv"
HEADER = (
    "# Scene text layout. Each row re-lays-out one line of on-screen text in one\n"
    "# scene: dx/dy move it (pixels, blank or 0 = unchanged), align is one of\n"
    "# left/center/right (blank = unchanged) and size is a percent of the size\n"
    "# the scene draws it at (blank or 100 = unchanged).\n"
    "# Delete a row to leave that line where Stern put it.\n"
    "# radium card path\tstring\tdx\tdy\talign\tsize\n")

ALIGN_VALUES = ("left", "center", "right")
_ALIGN_ALIASES = {"centre": "center", "middle": "center", "l": "left",
                  "c": "center", "r": "right"}
FIELDS = ("dx", "dy", "align", "size")


def manifest_path(assets_dir):
    """Absolute path of the manifest under *assets_dir* (it may not exist)."""
    return os.path.join(assets_dir, RELDIR, FILENAME)


def _cell(s):
    """One TSV cell: tabs and newlines become spaces so a row stays a row."""
    return (s or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")


# ---------------------------------------------------------------------------
# field parsing / normalising
# ---------------------------------------------------------------------------

def align_code(name):
    """``'left'``/``'center'``/``'right'`` -> the u32 the keyframe carries
    (0/1/2).  ``None`` for anything else."""
    name = _norm_align(name)
    if name is None:
        return None
    return ALIGN_VALUES.index(name)


def align_name(code):
    """0/1/2 -> ``'left'``/``'center'``/``'right'``; ``None`` otherwise."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return None
    if 0 <= code < len(ALIGN_VALUES):
        return ALIGN_VALUES[code]
    return None


def _norm_align(v):
    """Whatever the caller or the file said -> a canonical name or ``None``."""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return align_name(v)
    s = str(v).strip().lower()
    if not s:
        return None
    s = _ALIGN_ALIASES.get(s, s)
    return s if s in ALIGN_VALUES else None


def _norm_offset(v):
    """A dx/dy cell -> float (``0.0`` for blank/garbage)."""
    if v is None:
        return 0.0
    try:
        f = float(str(v).strip() or 0)
    except ValueError:
        return 0.0
    if f != f or f in (float("inf"), float("-inf")):
        return 0.0
    return f


def _norm_size(v):
    """A size cell -> int percent, or ``None`` when neutral/garbage."""
    if v is None:
        return None
    try:
        s = str(v).strip().rstrip("%").strip()
        if not s:
            return None
        n = int(round(float(s)))
    except ValueError:
        return None
    if n <= 0 or n == 100:
        return None
    return n


def normalize(edit):
    """Any dict of the four fields -> the canonical edit dict."""
    edit = edit or {}
    return {"dx": _norm_offset(edit.get("dx")),
            "dy": _norm_offset(edit.get("dy")),
            "align": _norm_align(edit.get("align")),
            "size": _norm_size(edit.get("size"))}


def is_neutral(edit):
    """True when the edit changes nothing (and so is not worth a row)."""
    e = normalize(edit)
    return e["dx"] == 0.0 and e["dy"] == 0.0 and e["align"] is None \
        and e["size"] is None


def _fmt_offset(f):
    return ("%g" % f) if f else ""


def describe(edit):
    """A short human string: ``'moved +10,-4 · centred · 120 %'``."""
    e = normalize(edit)
    parts = []
    if e["dx"] or e["dy"]:
        parts.append("moved %+g,%+g" % (e["dx"], e["dy"]))
    if e["align"] is not None:
        parts.append({"left": "left", "center": "centred",
                      "right": "right"}[e["align"]])
    if e["size"] is not None:
        parts.append("%d %%" % e["size"])
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# the file
# ---------------------------------------------------------------------------

def load(assets_dir):
    """``{card path: {string: edit}}`` — only rows that change something.

    Unreadable or malformed rows are skipped; a missing file yields ``{}``.
    A row from an older manifest that is short of trailing columns loads with
    the missing fields neutral."""
    out = {}
    path = manifest_path(assets_dir)
    if not os.path.isfile(path):
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if not line or line.startswith("#"):
                    continue
                cols = line.split("\t")
                if len(cols) < 3:
                    continue
                cols += [""] * (6 - len(cols))
                edit = normalize({"dx": cols[2], "dy": cols[3],
                                  "align": cols[4], "size": cols[5]})
                if is_neutral(edit):
                    continue
                out.setdefault(cols[0], {})[cols[1]] = edit
    except OSError:
        return out
    return out


def save(assets_dir, edits):
    """Write *edits* (:func:`load`'s shape) back, or remove the manifest when
    there is nothing left in it.  Neutral rows are not written."""
    path = manifest_path(assets_dir)
    rows = []
    for card in sorted(edits or {}):
        for text in sorted(edits[card] or {}):
            e = normalize(edits[card][text])
            if is_neutral(e):
                continue
            rows.append("%s\t%s\t%s\t%s\t%s\t%s\n" % (
                _cell(card), _cell(text), _fmt_offset(e["dx"]),
                _fmt_offset(e["dy"]), e["align"] or "",
                "" if e["size"] is None else "%d" % e["size"]))
    if not rows:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    os.makedirs(os.path.join(assets_dir, RELDIR), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(HEADER)
        f.writelines(rows)


def set_layout(assets_dir, card_path, text, dx=None, dy=None, align=None,
               size=None):
    """Merge the given fields into one line's row (``None`` = leave that
    field as it is).  Pass ``0`` for dx/dy, ``''`` for align or ``100`` for
    size to put a field back.  The row is dropped once every field is
    neutral.  Returns the row as stored, or ``None`` when there is none."""
    edits = load(assets_dir)
    per = edits.setdefault(card_path, {})
    cur = dict(per.get(text) or normalize({}))
    if dx is not None:
        cur["dx"] = _norm_offset(dx)
    if dy is not None:
        cur["dy"] = _norm_offset(dy)
    if align is not None:
        cur["align"] = _norm_align(align)
    if size is not None:
        cur["size"] = _norm_size(size)
    cur = normalize(cur)
    if is_neutral(cur):
        per.pop(text, None)
        row = None
    else:
        per[text] = cur
        row = dict(cur)
    if not per:
        edits.pop(card_path, None)
    save(assets_dir, edits)
    return row


def reset(assets_dir, card_path, text):
    """Drop one line's layout edit (back to the original layout)."""
    edits = load(assets_dir)
    per = edits.get(card_path)
    if not per or text not in per:
        return
    per.pop(text, None)
    if not per:
        edits.pop(card_path, None)
    save(assets_dir, edits)


def layout_for(assets_dir, card_path):
    """``{string: edit}`` for one scene — what a preview should apply."""
    return dict(load(assets_dir).get(card_path, {}))


def count(assets_dir):
    """How many text lines have a layout edit, across every scene."""
    return sum(len(v) for v in load(assets_dir).values())


def clear_all(assets_dir):
    """Drop every layout edit.  Returns how many were cleared."""
    n = count(assets_dir)
    if n:
        save(assets_dir, {})
    return n
