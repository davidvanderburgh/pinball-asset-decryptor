"""The Replace Text tab's rules, free of any UI.

Moved here unchanged from the Tk window's Replace Text helpers
(``gui/main_window.py``: ``_text_scene_label`` .. ``_text_row_matches``,
``_text_program_note``, ``_text_too_long_message``,
``_pending_text_status``), because the Tk window goes away at the cut-over
and the web tab, its tests and the Write tab's pending list all need the
same verdicts: what a row's Max is, whether it grows, what a filter shows,
what Replace everywhere would do.

Rows are the manifest's dicts (``core.text_manifest.load``):
``{"path", "original", "replacement", ["budget"], ["grow"], ["fixed"],
["unused"]}``.
"""

import re

#: The longest a scene line may be typed: the same one-line cap as the game
#: program's (progtext.MAX_EDIT_LEN).  A scene string has no slot limit of its
#: own (Write re-serialises the scene at the new length) but its box on
#: screen is a fixed template, so a Max the user can see beats an open one.
TEXT_SCENE_MAX = 96

#: The two fixed entries in the Scene dropdown.  SCENE_PROGRAM doubles as the
#: "not a scene file" selector inside the row filter.
SCENE_ALL = "All scenes"
SCENE_PROGRAM = "Game program"

#: Show: All / Changed / Unchanged (the Replace tabs' shared values).
CHANGE_FILTER_VALUES = ("All", "Changed", "Unchanged")


def scene_label(path):
    """A compact, distinguishing label for a scene path.  Spike 2 scenes are
    all named ``scene.radium`` under an opaque hash dir, so show
    ``hash…/scene.radium``; the game program reads "game program"."""
    parts = [p for p in (path or "").replace("\\", "/").split("/") if p]
    if not parts:
        return path or ""
    name = parts[-1]
    if name in ("game", "game_real"):
        return "game program"
    parent = parts[-2] if len(parts) >= 2 else ""
    if len(parent) > 14:
        parent = parent[:5] + "…" + parent[-4:]
    return parent + "/" + name if parent else name


def byte_len(s):
    """Byte length of *s* as the engine measures it for the size budget."""
    return len(s.encode("latin1", "replace"))


def row_len(r, s):
    """Byte length of *s* for row *r*'s budget check.  Game-program rows (the
    ones carrying an explicit budget) write ``\\n`` as ONE byte."""
    if r.get("budget"):
        s = s.replace("\\n", "\n")
    return byte_len(s)


def row_is_scene(r):
    """True for a scene (.radium) row, False for a game-program row."""
    return (r.get("path") or "").lower().endswith(".radium")


def row_grows(r):
    """True when a replacement longer than the original's slot is still
    accepted: every scene row, a game-program row flagged ``grows``, and a
    game-program row with NO flag at all (nobody has looked yet; Write decides
    from the card).  A row a card scan found immovable carries ``fixed``."""
    if row_is_scene(r):
        return True
    if r.get("fixed"):
        return False
    return True


def row_budget(r):
    """The row's replacement byte budget: on a row that grows, its own budget
    or :data:`TEXT_SCENE_MAX`, whichever is longer; on a fixed program row,
    the explicit budget from the scan, else the original's own length."""
    own = len(r["original"].encode("latin1", "replace"))
    if row_grows(r):
        return max(r.get("budget") or own, TEXT_SCENE_MAX)
    return r.get("budget") or own


def row_max_label(r):
    """The Max column's cell: the budget, marked ``(grows)`` on a row whose
    longer text Write places in a new area / rewrites the scene for."""
    budget = row_budget(r)
    return "%d (grows)" % budget if row_grows(r) else "%d" % budget


def row_outgrows(r, s):
    """True when *s* is longer than row *r*'s ORIGINAL slot."""
    return row_len(r, s) > row_len(r, r["original"])


def is_edited(r):
    return bool(r.get("replacement")) and r["replacement"] != r["original"]


def replace_plan(rows, find, repl, match_case=True):
    """The Replace-everywhere plan: for every row whose ORIGINAL contains
    *find*, ``{"index", "row", "new", "fits"}``.  An empty *find* plans
    nothing."""
    out = []
    if not find:
        return out
    if match_case:
        def _hit(s):
            return find in s

        def _sub(s):
            return s.replace(find, repl)
    else:
        rx = re.compile(re.escape(find), re.IGNORECASE)

        def _hit(s):
            return rx.search(s) is not None

        def _sub(s):
            return rx.sub(lambda _m: repl, s)
    for i, r in enumerate(rows):
        orig = r["original"]
        if not _hit(orig):
            continue
        new = _sub(orig)
        out.append({"index": i, "row": r, "new": new,
                    "fits": row_len(r, new) <= row_budget(r)})
    return out


def split_edit(original, new):
    """``(find, repl)`` when *new* differs from *original* by exactly one
    contiguous run, else None (a pure insertion is not a search)."""
    if not original or not new or original == new:
        return None
    p = 0
    lim = min(len(original), len(new))
    while p < lim and original[p] == new[p]:
        p += 1
    s = 0
    while (s < lim - p and original[len(original) - 1 - s]
           == new[len(new) - 1 - s]):
        s += 1
    find = original[p:len(original) - s]
    repl = new[p:len(new) - s]
    if not find:
        return None
    return find, repl


def scene_key(path):
    """The shared container key for a scene path: the SAME key the Replace
    Images tab tags its radium groups under."""
    return "rad::" + (path or "")


def row_matches(r, query, want_changed, scene):
    """True when row *r* survives the three filters: *query* (lower-cased,
    "" = off) against the original or the new text; *want_changed*
    True/False/None; *scene* a card path, :data:`SCENE_PROGRAM` or None."""
    if query:
        if (query not in r["original"].lower()
                and query not in (r["replacement"] or "").lower()):
            return False
    if want_changed is not None:
        edited = bool(r["replacement"]) and r["replacement"] != r["original"]
        if edited != want_changed:
            return False
    if scene is not None:
        is_scene_file = (r["path"] or "").lower().endswith(".radium")
        if scene == SCENE_PROGRAM:
            return not is_scene_file
        return r["path"] == scene
    return True


def scene_menu(rows, names):
    """``([display…], {display: path})`` for the Scene dropdown: named scenes
    first, then the rest by their hash label, each with its string count."""
    counts, labels = {}, {}
    program = 0
    for r in rows:
        path = r["path"] or ""
        if not path.lower().endswith(".radium"):
            program += 1
            continue
        counts[path] = counts.get(path, 0) + 1
        if path not in labels:
            name = names.get(scene_key(path), "")
            labels[path] = (name, scene_label(path))
    order = sorted(counts,
                   key=lambda p: (not labels[p][0], labels[p][0].lower(),
                                  labels[p][1].lower()))
    values = [SCENE_ALL]
    by_display = {}
    if program:
        values.append(SCENE_PROGRAM)
    for path in order:
        name, label = labels[path]
        display = "%s — %s (%d)" % (name, label, counts[path]) if name \
            else "%s (%d)" % (label, counts[path])
        values.append(display)
        by_display[display] = path
    return values, by_display


def scene_note(r, name=""):
    """The note under the editor for a scene row."""
    return (("Scene “%s”: " % name if name else "Scene: ") + r["path"]
            + " — text that still fits is patched in place; a longer "
            "line has the scene rewritten at the new length on Write "
            "(image build, not a Direct-SD write; not yet booted on a "
            "machine). Its box is the scene's fixed template: check a "
            "longer line in the Scenes window.")


def program_note(r):
    """The note under the editor for a game-program row."""
    note = ("Game program: %s — drawn by game code (mode titles, battle "
            "names). \\n in a string is a real line break." % r["path"])
    if r.get("unused"):
        note += (" (not used by the game) — no reference to this line "
                 "was found in the game program, so changing it changes "
                 "nothing on screen.")
    if r.get("grow") or not r.get("fixed"):
        note += (" This row can grow: longer text is placed in a new "
                 "area of the game program and every reference is "
                 "pointed at it; that needs an image build (not a "
                 "Direct-SD write), and no machine has booted such a "
                 "build yet — text that still fits is patched in place "
                 "as before.")
        if not r.get("grow"):
            note += (" This project was extracted before the tool "
                     "measured which strings can move, so the exact "
                     "limit is checked against the card when you build "
                     "— a string the game reads in a way the tool "
                     "can't follow is left alone and the build says so. "
                     "Scan re-reads the limits when the card image is "
                     "still where it was.")
    else:
        note += (" Names shown on their own may be the END of a longer "
                 "line; edit both rows so the line ends with the new "
                 "name.")
    return note


def budget_readout(r, new):
    """``(text, over)`` for the 'N / M bytes' readout under the editor."""
    limit = row_budget(r)
    new_len = row_len(r, new)
    over = new_len > limit
    if over:
        tail = "  — too long"
    elif row_grows(r) and row_outgrows(r, new):
        tail = ("  — the scene is rewritten at the new length"
                if row_is_scene(r)
                else "  — placed in a new area of the game program")
    else:
        tail = ""
    if r.get("unused"):
        tail += "  (not used by the game)"
    return "%d / %d bytes%s" % (new_len, limit, tail), over


def too_long_message(r, new):
    """Why an edit is refused: a row that grows is capped only by the line
    limit; a program row the tool can't move must fit its slot."""
    new_len = row_len(r, new)
    budget = row_budget(r)
    if row_grows(r):
        return ("“%s” is %d bytes; the longest a line can be is %d "
                "bytes." % (new, new_len, budget))
    return ("“%s” is %d bytes but only %d fit. This line is used in "
            "a way the tool can't move, so it is patched in place "
            "and has to fit the available length — use a shorter "
            "string." % (new, new_len, budget))


PENDING_TEXT = "Pending (Replace Text)"
PENDING_TEXT_GROWS = "Pending (text, game program grows)"
PENDING_TEXT_GROWS_SCENE = "Pending (text, scene grows)"
PENDING_TEXT_GROW_OFF = "Pending (Replace Text — too long, grow is off)"


def pending_text_status(row, grow_on=True):
    """The Write tab's pending-list status for one text edit (the Tk
    ``MainWindow._pending_text_status``), shared so both tabs agree.  A
    longer edit on a row that grows names its path; with the Advanced grow
    option off the row says the build skips it."""
    rep = row.get("replacement") or ""
    if row_grows(row) and rep and row_outgrows(row, rep):
        if not grow_on:
            return PENDING_TEXT_GROW_OFF
        return (PENDING_TEXT_GROWS_SCENE if row_is_scene(row)
                else PENDING_TEXT_GROWS)
    return PENDING_TEXT


def ellipsize(s, n=40):
    """Trim a string for a one-line log message."""
    return s if len(s) <= n else s[:n - 1] + "…"
