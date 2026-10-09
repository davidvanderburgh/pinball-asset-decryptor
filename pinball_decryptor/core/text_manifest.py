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
    "# Rows with a 4th (max_bytes) column may exceed the original's length up to\n"
    "# that budget (game-program strings; \\n in them is a real line break).\n"
    "# A 5th column holds flags: 'grows' = longer text is placed in a new area\n"
    "# of the game program on Write (needs an image build); 'fixed' = the game\n"
    "# reads the line in a way the tool can't move, so it is patched in place\n"
    "# and has to fit; 'unused' = no reference to the line was found in the\n"
    "# game program; 'in:<modes>' = the game's own modes that show the line.\n"
    "# A game-program path ending '#<mode>' is that mode's own text for a line\n"
    "# several modes show (blank = the same text as the line's main row).\n"
    "# asset_path\toriginal\treplacement\tmax_bytes\tflags\n")

#: 5th-column flag tokens (space-separated; unknown tokens are ignored, and a
#: manifest without the column loads with none of them set).
FLAG_GROWS = "grows"
FLAG_UNUSED = "unused"
#: Written for a game-program row a card scan found NOT growable.  It exists so
#: that "no flags at all" keeps its older meaning of "nobody has looked yet":
#: a manifest written before the flags existed must not read as "every program
#: string is stuck at its original length", which is exactly what made the Text
#: tab refuse longer text on a project extracted by an older build.
FLAG_FIXED = "fixed"
#: PAD-470: ``in:<mode class>,<mode class>`` - the game's own modes that show a
#: game-program row (``row["modes"]``).
FLAG_IN = "in:"
#: PAD-470: a game-program row's path ending ``#<mode class>`` is that mode's
#: own text for a line several modes show (:func:`split_part`).
PART_SEP = "#"


def split_part(path):
    """``(card path, mode class)`` of a manifest row's path: the mode is
    ``""`` for every row but one mode's own text (PAD-470)."""
    p = path or ""
    if PART_SEP in p:
        base, part = p.split(PART_SEP, 1)
        return base, part
    return p, ""


def join_part(path, part):
    """The manifest path of *part*'s own text for a line of *path*."""
    return "%s%s%s" % (path, PART_SEP, part) if part else path


def manifest_path(assets_dir):
    """Absolute path of the manifest under *assets_dir* (it may not exist)."""
    return os.path.join(assets_dir, RELDIR, FILENAME)


def escape_cell(s):
    """Make a string safe for one TSV cell: tabs / carriage returns / newlines
    (rare in display text, but possible) become spaces so each string stays on
    one line and the column layout is stable."""
    return s.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def card_form(card_text, replacement):
    r"""*replacement* the way the card should hold it in place of *card_text*.

    A scene line broken over several lines (Godzilla's "GODZILLA AND JET
    JAGUAR\nVS.\nMEGALON AND GIGAN") reaches the manifest with its breaks
    flattened to spaces by :func:`escape_cell`, so the replacement typed
    against it has none either.  A typed ``\n`` is a line break, as it is in
    a game-program row; with none typed, the original's breaks are put back
    where the words around them are the same (counted from the start, or
    from the end), or at the same word when the word count is unchanged.
    A break and a space are one byte each, so the length never changes
    (DragonRR, PAD-382)."""
    rep = replacement or ""
    if "\\n" in rep and "\\n" not in (card_text or ""):
        return rep.replace("\\n", "\n")
    if "\n" not in (card_text or "") or "\n" in rep:
        return rep
    import re
    parts = re.split(r"([ \n])", card_text)
    words_o, seps_o = parts[0::2], parts[1::2]
    words_r = rep.split(" ")
    seps_r = [" "] * (len(words_r) - 1)
    n_o, n_r = len(words_o), len(words_r)
    pre = 0
    while pre < min(n_o, n_r) and words_o[pre] == words_r[pre]:
        pre += 1
    suf = 0
    while (suf < min(n_o, n_r) - pre
           and words_o[n_o - 1 - suf] == words_r[n_r - 1 - suf]):
        suf += 1
    for i, sep in enumerate(seps_o):
        if sep != "\n":
            continue
        after = n_o - 1 - i                   # words that follow the break
        if i < pre and i < len(seps_r):
            seps_r[i] = "\n"
        elif after <= suf:
            seps_r[n_r - 1 - after] = "\n"
        elif n_o == n_r:
            seps_r[i] = "\n"
    out = [words_r[0]]
    for sep, w in zip(seps_r, words_r[1:]):
        out += [sep, w]
    return "".join(out)


def edit_for(edits, card_text):
    """The replacement *edits* (``{original: replacement}``) holds for the
    string *card_text* exactly as a scene draws it, in the form the card
    holds it (:func:`card_form`); ``None`` when it is not edited.  Matches the
    manifest's flattened form of a line that has line breaks."""
    if not edits or not card_text:
        return None
    rep = edits.get(card_text)
    if not rep:
        flat = escape_cell(card_text)
        rep = edits.get(flat) if flat != card_text else None
    return card_form(card_text, rep) if rep else None


def resolve(card_texts, pairs):
    """*pairs* (``[(original, replacement)]`` of one asset's manifest rows)
    keyed on the strings the asset really holds, *card_texts*: a manifest
    original that is a line-broken string flattened by :func:`escape_cell`
    becomes that string, and its replacement takes :func:`card_form`.  An
    original found nowhere is kept as it is (the caller reports it)."""
    flat = {}
    for t in card_texts:
        flat.setdefault(escape_cell(t), t)
    out = []
    for orig, rep in pairs:
        key = orig if orig in card_texts else flat.get(orig, orig)
        out.append((key, card_form(key, rep) if key in card_texts else rep))
    return out


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
            row = {
                "path": cols[0],
                "original": cols[1],
                "replacement": cols[2] if len(cols) >= 3 else "",
            }
            # Optional 4th column: explicit byte budget (game-program strings,
            # whose replacement may legitimately exceed the original's length
            # — e.g. a standalone name that lives inside a longer line).
            if len(cols) >= 4 and cols[3].strip().isdigit():
                row["budget"] = int(cols[3].strip())
            # Optional 5th column: flags.  ``grow`` = the replacement may run
            # past the original's slot (up to the budget) — Write places it
            # in a new area of the game program; ``unused`` = the scan found
            # no reference to the line, so an edit changes nothing on screen.
            # Only set when present, so older manifests load unchanged.
            if len(cols) >= 5:
                flags = set(cols[4].split())
                if FLAG_GROWS in flags:
                    row["grow"] = True
                if FLAG_FIXED in flags:
                    row["fixed"] = True
                if FLAG_UNUSED in flags:
                    row["unused"] = True
                for fl in flags:
                    if fl.startswith(FLAG_IN):
                        row["modes"] = [m for m in fl[len(FLAG_IN):].split(",")
                                        if m]
            rows.append(row)
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
            budget = None
            flags = []
            if isinstance(r, dict):
                p = r.get("path", "")
                original = r.get("original", "")
                replacement = r.get("replacement", "") or ""
                budget = r.get("budget")
                if r.get("grow"):
                    flags.append(FLAG_GROWS)
                if r.get("fixed"):
                    flags.append(FLAG_FIXED)
                if r.get("unused"):
                    flags.append(FLAG_UNUSED)
                if r.get("modes"):
                    flags.append(FLAG_IN + ",".join(r["modes"]))
            else:
                seq = list(r) + ["", "", ""]
                p, original, replacement = seq[0], seq[1], seq[2] or ""
            line = "%s\t%s\t%s" % (escape_cell(p), escape_cell(original),
                                   escape_cell(replacement))
            if budget:
                line += "\t%d" % budget
                # Flags ride on the budget column (they only mean anything
                # for a budgeted game-program row), so column 5 is always
                # column 5.
                if flags:
                    line += "\t" + " ".join(flags)
            f.write(line + "\n")


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


def revert_all(assets_dir):
    """Blank every replacement so the manifest records no edits (text reverts to
    the originals on the next build).  Returns the number of edits cleared."""
    rows = load(assets_dir)
    n = sum(1 for r in rows if r.get("replacement"))
    if n:
        for r in rows:
            r["replacement"] = ""
        save(assets_dir, rows)
    return n
