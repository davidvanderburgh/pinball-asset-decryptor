"""The editable on-screen-text manifest: ``<assets>/text/strings.tsv``.

Some plugins (Stern Spike 2) can pull the player-facing display strings out of
their scene files into a flat, human-editable TSV.  Each row is three columns::

    asset_path <TAB> original <TAB> replacement

``replacement`` left blank (or equal to ``original``) means *leave unchanged* --
the user fills in only the strings they want to change.  ``(asset_path,
original)`` is the stable key: the on-card asset is untouched until Write, which
re-derives the authoritative byte offsets from it, so only the original value
has to round-trip.

This module is the single source of truth for the file's name + layout so the
GUI that *writes* it (the Replace Text tab) and the plugin engine that *reads*
it at Write time can never drift apart.  It is format-only -- it knows nothing
about radium / ext4 / how the strings are patched back in.
"""

import os

RELDIR = "text"
FILENAME = "strings.tsv"
HEADER = (
    "# Edit on-screen text: put your new text in the 3rd (replacement) column.\n"
    "# Leave it BLANK to keep the original unchanged. The replacement must be no\n"
    "# longer than the original (it's space-padded to the exact length on Write).\n"
    "# asset_path\toriginal\treplacement\n")


def manifest_path(assets_dir):
    """Absolute path of the manifest under *assets_dir* (it may not exist)."""
    return os.path.join(assets_dir, RELDIR, FILENAME)


def escape_cell(s):
    """Make a string safe for one TSV cell: tabs / carriage returns / newlines
    (rare in display text, but possible) become spaces so each string stays on
    one line and the column layout is stable."""
    return s.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def load(assets_dir):
    """Return the manifest as a list of ``{path, original, replacement}`` dicts,
    in file order.  Comment (``#``) and blank lines are skipped; a missing file
    yields ``[]``.  A row with no replacement column reads ``replacement == ""``.
    """
    path = manifest_path(assets_dir)
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 2:
                continue
            rows.append({
                "path": cols[0],
                "original": cols[1],
                "replacement": cols[2] if len(cols) >= 3 else "",
            })
    return rows


def save(assets_dir, rows):
    """Write *rows* back to the manifest (creating ``<assets>/text/``).

    Each row is a ``{path, original, replacement}`` dict (or a
    ``(path, original, replacement)`` sequence); a missing/None replacement is
    written blank.  The whole file is rewritten so the on-disk manifest always
    mirrors the caller's full row set."""
    text_dir = os.path.join(assets_dir, RELDIR)
    os.makedirs(text_dir, exist_ok=True)
    with open(os.path.join(text_dir, FILENAME), "w", encoding="utf-8") as f:
        f.write(HEADER)
        for r in rows:
            if isinstance(r, dict):
                p = r.get("path", "")
                original = r.get("original", "")
                replacement = r.get("replacement", "") or ""
            else:
                seq = list(r) + ["", "", ""]
                p, original, replacement = seq[0], seq[1], seq[2] or ""
            f.write("%s\t%s\t%s\n" % (escape_cell(p), escape_cell(original),
                                      escape_cell(replacement)))


def changed(assets_dir):
    """Return the user's edits grouped by asset:
    ``{path: [(original, replacement), ...]}`` for every row whose non-blank
    ``replacement`` differs from ``original``.  Empty when there's no manifest
    or nothing was edited."""
    out = {}
    for r in load(assets_dir):
        rep = r["replacement"]
        if rep and rep != r["original"]:
            out.setdefault(r["path"], []).append((r["original"], rep))
    return out


def count_changed(assets_dir):
    """Total number of edited strings across all assets (for status / preview)."""
    return sum(len(v) for v in changed(assets_dir).values())
