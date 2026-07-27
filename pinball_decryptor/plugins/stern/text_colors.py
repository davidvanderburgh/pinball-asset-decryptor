"""The scene text-colour manifest: ``<assets>/text/colors.tsv`` (Peter).

A Spike 2 font atlas is white ink on black (or a black silhouette on
transparent) — deliberately, because the COLOUR is applied by the scene, which
multiplies the glyph bitmaps by an RGBA it carries per line of text.  So
"make this text turtle green" is not a font edit at all: painting the atlas
green only shows up where the scene happens to tint white, and on the 131 TMNT
lines the scene tints pure black nothing you do to the glyphs can ever show.
The colour has to be changed where the game keeps it, in the ``scene.radium``.

This module is the file format only — which line of which scene the user
recoloured, and from what to what::

    radium card path <TAB> string <TAB> from #RRGGBB <TAB> to #RRGGBB

``from`` is part of the key for the same reason the display-text manifest keeps
the original string: the on-card scene is untouched until Write, which
re-derives the authoritative byte offsets from it.  It also disambiguates —
one string can be drawn by several keyframes at different colours (an outline
instance under a fill), and only the ones that currently read *from* are the
ones the user was looking at when they picked.
"""

import os

RELDIR = "text"
FILENAME = "colors.tsv"
HEADER = (
    "# Scene text colours. Each row recolours one line of on-screen text in one\n"
    "# scene: the game multiplies the (white) font by this colour, so this is\n"
    "# where a text colour actually lives - not in the font.\n"
    "# Delete a row to leave that line the colour Stern shipped.\n"
    "# radium card path\tstring\tfrom\tto\n")


def manifest_path(assets_dir):
    """Absolute path of the manifest under *assets_dir* (it may not exist)."""
    return os.path.join(assets_dir, RELDIR, FILENAME)


def _cell(s):
    """One TSV cell: tabs and newlines become spaces so a row stays a row."""
    return (s or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")


def parse_hex(s):
    """``"#rrggbb"`` -> ``(r, g, b)``, or ``None`` if it isn't one."""
    s = (s or "").strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None


def to_hex(rgb):
    """``(r, g, b)`` (0-255) -> ``"#rrggbb"``."""
    r, g, b = (max(0, min(255, int(round(c)))) for c in tuple(rgb)[:3])
    return "#%02x%02x%02x" % (r, g, b)


def from_floats(rgba):
    """The 0..1 floats a layout carries -> a ``(r, g, b)`` 0-255 tuple."""
    try:
        return tuple(max(0, min(255, int(round(float(c) * 255.0))))
                     for c in tuple(rgba)[:3])
    except (TypeError, ValueError):
        return (255, 255, 255)


def load(assets_dir):
    """``{card path: {string: (from_rgb, to_rgb)}}`` — every row is an edit.

    Unreadable or malformed rows are skipped; a missing file yields ``{}``."""
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
                if len(cols) < 4:
                    continue
                src, dst = parse_hex(cols[2]), parse_hex(cols[3])
                if src is None or dst is None:
                    continue
                out.setdefault(cols[0], {})[cols[1]] = (src, dst)
    except OSError:
        return out
    return out


def save(assets_dir, edits):
    """Write *edits* (:func:`load`'s shape) back, or remove the manifest when
    there is nothing left in it."""
    path = manifest_path(assets_dir)
    if not any(v for v in edits.values()):
        try:
            os.remove(path)
        except OSError:
            pass
        return
    os.makedirs(os.path.join(assets_dir, RELDIR), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(HEADER)
        for card in sorted(edits):
            for text in sorted(edits[card]):
                src, dst = edits[card][text]
                f.write("%s\t%s\t%s\t%s\n" % (_cell(card), _cell(text),
                                              to_hex(src), to_hex(dst)))


def set_color(assets_dir, card_path, text, from_rgb, to_rgb):
    """Record (or, with *to_rgb* ``None``, drop) one line's colour.

    Picking the colour the line already has is the same as dropping it — there
    is nothing to patch, and a no-op row would make the project look edited."""
    edits = load(assets_dir)
    per = edits.setdefault(card_path, {})
    if to_rgb is None or tuple(to_rgb)[:3] == tuple(from_rgb)[:3]:
        per.pop(text, None)
    else:
        per[text] = (tuple(from_rgb)[:3], tuple(to_rgb)[:3])
    if not per:
        edits.pop(card_path, None)
    save(assets_dir, edits)


def colors_for(assets_dir, card_path):
    """``{string: to_rgb}`` for one scene — what a preview should draw."""
    return {t: dst for t, (_src, dst) in load(assets_dir).get(card_path,
                                                              {}).items()}


def count(assets_dir):
    """How many text lines have a colour edit, across every scene."""
    return sum(len(v) for v in load(assets_dir).values())


def clear_all(assets_dir):
    """Drop every colour edit.  Returns how many were cleared."""
    n = count(assets_dir)
    if n:
        save(assets_dir, {})
    return n
