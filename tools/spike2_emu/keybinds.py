"""keybinds.py - read the key binds padglhost exports (dump/padbinds).

REMAINING item 39. The keyboard->switch table lives in padglhost.c - binds[],
resolved per title by binds_resolve() - and the playfield window now draws it
in a panel instead of the old Controls X11 window, which no longer opens by
default. This module is the READING half of that split: padglhost writes
dump/padbinds at startup (tmp+rename, so a poll can never parse half a file)
and this turns it into rows, WITHOUT a second copy of the table. Which key
does what has exactly one home and it is still the C file; this only renders
what that wrote.

No tkinter on purpose, the same split as trough.py and coilmap.py: the parse
is testable without a display and importable from WSL-side tools.

The format, from binds_export(): one tab-separated line per bind -
key, flags, ids, label. Tabs because a key can be "KP Ent". flags is
`c` (cabinet section) and/or `t` (toggle), `-` for neither. ids is
comma-joined, and a literal `0` is a bind whose switch is not on this title
(binds_resolve found no name for it) - shown dim, never pressed.
"""
import os


def parse(lines):
    """Rows from padbinds lines, in file order, duplicates merged.

    MERGED, because the C table carries one row per KEYSYM and two keys can be
    one action - Enter and KP Ent are both Service Select, Bksp and Esc are
    both Service Back. Drawn as four rows that is noise; the panel wants
    "Enter/KP Ent  Service Select". Merging is on (label, ids) agreeing, and
    only for CONSECUTIVE rows, so two distinct actions that happen to share a
    label on some title cannot collapse across a section boundary.
    """
    out = []
    for line in lines:
        line = line.rstrip("\r\n")
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) != 4:
            continue
        key, flags, ids, label = p
        na = ids.strip() == "0"
        try:
            idlist = [] if na else [int(t) for t in ids.split(",")]
        except ValueError:
            continue
        row = dict(keys=[key], label=label, ids=idlist, na=na,
                   toggle="t" in flags, cabinet="c" in flags)
        last = out[-1] if out else None
        if (last and last["label"] == row["label"]
                and last["ids"] == row["ids"] and last["na"] == row["na"]
                and last["cabinet"] == row["cabinet"]):
            last["keys"].append(key)
        else:
            out.append(row)
    return out


def load(path):
    """parse() over a padbinds file, or [] - absent is the normal state until
    the renderer has started, so it is not an error, and the caller polls."""
    try:
        with open(path) as f:
            return parse(f)
    except OSError:
        return []


if __name__ == "__main__":
    import sys
    import padpath
    p = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        padpath.dump() or "", "padbinds")
    rows = load(p)
    print("%s: %d rows" % (p, len(rows)))
    for r in rows:
        print("  %-14s %-22s %s%s%s" % ("/".join(r["keys"]), r["label"],
                                        ",".join(str(i) for i in r["ids"]),
                                        "  [toggle]" if r["toggle"] else "",
                                        "  n/a" if r["na"] else ""))
