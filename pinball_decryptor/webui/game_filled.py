"""The lines of text the game writes itself as it plays, so new words for them in a scene would
never show (DragonRR, PAD-513: "Where it would be pointless to change the text in the scene ...
please don't allow the user to edit the text in the scene in those instances").

Only the PROVEN rule locks a line: the game finds a box by its path from the screen's root to
write in it, so a box whose path the game program points at is written by the game
(``engine.program_node_paths``, emulator-proven on stock Godzilla LE 1.16).  A project whose card
has not been read for those paths locks nothing: the older word-matching marks are guesses, and
a guess must not stop an edit that would show.
"""

import json
import os
import re

LOCKED_NOTE = ("The game writes this line itself as it plays (in the player's language), so "
               "words typed here would never show on the machine.")

# PAD-1261 (DragonRR): the note used to say "Change the game's own line instead: it is a game
# program row on the Text tab" for every locked line, but a shared screen's words are often only
# the designer's stand-in (Godzilla's award screen 293641e4 holds "IMPOSTER BATTLE" in a title
# box the game fills with whichever award was won), and the game has no line reading like it.
_GAME_ROW_NOTE = " To change it, change the game's own line: the game program row “{}” on the Text tab."
_STAND_IN_NOTE = (" “{}” is only a stand-in: the game puts its own words here, which change with "
                  "play, and no line of the game program reads like it, so there is no single line "
                  "to change. To change words the machine shows here, search the Text tab for them.")

_memo = {}


def _stamp(path):
    # size too: two quick rewrites can share a timestamp tick, and a
    # stale lock (or none) would then outlive the new reading
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def known_paths(assets_dir):
    """The node paths the game program points at (``engine.program_node_paths``), or None."""
    if not assets_dir:
        return None
    try:
        from ..plugins.stern import engine
        return engine.program_node_paths(assets_dir)
    except Exception:                                   # noqa: BLE001
        return None


def locked_lines(assets_dir):
    """``{scene card path: frozenset of manifest originals}``: a scene's lines of text every box
    of which the game writes (a line some box keeps as its own words is not locked: new words
    show there).  Empty without the program's node paths.  Cached until the reading or the
    scene trees change."""
    if not assets_dir:
        return {}
    from ..core import text_manifest
    tree_file = os.path.join(assets_dir, "images", "scene_textures", "scene_tree.json")
    modes_file = os.path.join(assets_dir, text_manifest.RELDIR, "program_modes.json")
    key = (os.path.normcase(os.path.abspath(assets_dir)), _stamp(tree_file), _stamp(modes_file))
    got = _memo.get(key[0])
    if got and got[0] == key:
        return got[1]
    out = {}
    known = known_paths(assets_dir)
    if known:
        from .text_scenes_tree import _kind_of, _text_of, _walk_man
        try:
            with open(tree_file, encoding="utf-8") as f:
                trees = json.load(f)
        except (OSError, ValueError):
            trees = {}
        for card, man in trees.items():
            parent, names, lines = {}, {}, {}
            for n, p, _depth in _walk_man(man):
                parent[n["id"]] = p["id"] if p else None
                names[n["id"]] = n.get("name") or ""
                if _kind_of(man, n) != "Text":
                    continue
                words = _text_of(man, n, "Text")
                if not (words or "").strip():
                    continue
                parts, cur = [], n["id"]
                while cur is not None:
                    parts.append(names[cur])
                    cur = parent.get(cur)
                orig = text_manifest.escape_cell(words)
                lines.setdefault(orig, []).append(".".join(reversed(parts)) in known)
            done = frozenset(o for o, filled in lines.items() if all(filled))
            if done:
                out[card] = done
    _memo[key[0]] = (key, out)
    return out


def is_locked(assets_dir, row):
    """Is manifest *row* a scene line the game writes in every box (see :func:`locked_lines`)?"""
    path = row.get("path") or ""
    if not path.lower().endswith(".radium"):
        return False
    return row.get("original") in locked_lines(assets_dir).get(path, ())


def game_row_for(rows, words):
    """The game-program row of manifest *rows* that reads like scene line *words* (spacing,
    case and a closing ``!``/``.``/``?`` aside, else with the row's printf fill-ins taken
    out: :func:`.text_rules.format_words`), the one the game puts on screen in its place,
    or None.  One mode's own text and a line the game never reads are not offered."""
    from . import text_rules as R
    want = R.stand_in_words(words, True).upper()
    if len(re.sub(r"\W", "", want)) < 2:          # a letter is no line (PAD-513's T boxes)
        return None
    near = fill = None
    for r in rows or ():
        if R.row_is_scene(r) or R.row_part(r) or r.get("unused"):
            continue
        got = R.stand_in_words(r.get("original"))
        if got.upper() == R.stand_in_words(words).upper():
            return r
        if near is None and R.stand_in_words(got, True).upper() == want:
            near = r
        # PAD-1256: the line with its printf fill-ins out (IMPOSTER BATTLE %d/%d)
        if fill is None and R.format_words(r.get("original")).upper() == want:
            fill = r
    return near or fill


# the Scenes Words box has room for a line or two (its tip had the same words before)
_SHORT_GAME_ROW = "The game writes this line itself as it plays: change the game program row “{}” on the Text tab"
_SHORT_STAND_IN = ("The game writes this line itself as it plays: “{}” is only a stand-in, with no "
                   "single game line to change")
SHORT_NOTE = "The game writes this line itself as it plays: change the game's own line on the Text tab"


def locked_note(words, rows=None, assets_dir=None, short=False):
    """The note for a locked scene line reading *words* (PAD-1261): it names the game's own
    line to change when the game program has one reading like it, and otherwise says the
    words are a stand-in with no single line behind them; *short* for the Scenes Words box.  *rows* is the project's manifest
    (read from *assets_dir* when not given)."""
    from . import text_rules as R
    if rows is None:
        try:
            from ..core import text_manifest
            rows = text_manifest.load(assets_dir) if assets_dir else []
        except (OSError, ValueError):
            rows = []
    r = game_row_for(rows, words)
    if r is not None:
        game = R.stand_in_words(r["original"])
        return _SHORT_GAME_ROW.format(game) if short else LOCKED_NOTE + _GAME_ROW_NOTE.format(game)
    shown = R.stand_in_words(words)
    if not shown:
        return SHORT_NOTE if short else LOCKED_NOTE
    return _SHORT_STAND_IN.format(shown) if short else LOCKED_NOTE + _STAND_IN_NOTE.format(shown)


# ---------------------------------------------------------------------------------------------
# PAD-1338 (DragonRR): "Is there a way to show what the machine might show in this location - it
# just shows 'Inactive Player' but the machine CAN display PLAYER 2 - LOG IN".  A box the game
# fills holds only a stand-in; the Scenes preview can draw it with words the game puts there
# instead (the preview only: nothing is written to the card), offered from the game program.
# ---------------------------------------------------------------------------------------------
_WORD = re.compile(r"[A-Za-z]{3,}")
_PLAYER_NO = re.compile(r"(?:^|[._])P(\d)_")
TRY_MAX = 40            # suggestions offered for one box
TRY_LONGEST = 60        # a longer line is help text, not a box's words


def sample_line(line, number="1"):
    """Game-program *line* as the machine might show it: its printf fill-ins filled with a
    sample (*number* for a number, the plural form for ``%P``, ``NAME`` for a name)."""
    from . import text_rules as R

    def fill(m):
        s = m.group(0)
        if s == "%%":
            return "%"
        if s.startswith("%P"):
            forms = s[2:-2].split("/")[1:]         # %P1//S/% -> ["", "S"]
            return (forms[-1] if number != "1" else forms[0]) if forms else ""
        if s[-1] in "sp":
            return "NAME"
        if s[-1] == "c":
            return "A"
        return number
    return " ".join(R._FILL_IN.sub(fill, (line or "").replace("\n", " ")).split())


def try_lines(rows, words, path=""):
    """What the game might write into a box whose own words are the stand-in *words*, for
    the Scenes "Show it with" list: the game-program lines of manifest *rows* sharing a word
    with the stand-in, most words shared first (lines with fill-ins, then the shorter, ahead),
    each filled with a sample (:func:`sample_line`; a player's number from a ``P<n>_`` part of
    the box's dotted *path*).  The game line reading like the stand-in itself leads."""
    from . import text_rules as R
    want = {w.upper() for w in _WORD.findall(R.stand_in_words(words))}
    got = _PLAYER_NO.search(path or "")
    number = got.group(1) if got else "1"
    own = game_row_for(rows, words)
    ranked = []
    for i, r in enumerate(rows or ()):
        if R.row_is_scene(r) or R.row_part(r) or r.get("unused"):
            continue
        orig = r.get("original") or ""
        if "&" in orig or "\n" in orig or "\n" in orig:
            continue                        # markup or several lines: not a box's one line
        shared = len(want & {w.upper() for w in _WORD.findall(R._FILL_IN.sub(" ", orig))})
        if r is not own and not shared:
            continue
        shown = sample_line(orig, number)
        if not shown or len(shown) > TRY_LONGEST:
            continue
        ranked.append(((r is not own, -shared, not R._FILL_IN.search(orig), len(shown), i),
                       shown))
    out, seen = [], set()
    for _k, shown in sorted(ranked):
        if shown not in seen:
            seen.add(shown)
            out.append(shown)
        if len(out) >= TRY_MAX:
            break
    return out


def try_lines_for(assets_dir, words, path=""):
    """:func:`try_lines` over the project's manifest in *assets_dir* (read once until it
    changes)."""
    if not assets_dir:
        return []
    from ..core import text_manifest
    mpath = text_manifest.manifest_path(assets_dir)
    stamp = _stamp(mpath)
    got = _memo.get(("try", assets_dir))
    if got is None or got[0] != stamp:
        try:
            rows = text_manifest.load(assets_dir)
        except (OSError, ValueError):
            rows = []
        got = _memo[("try", assets_dir)] = (stamp, rows, {})
    key = (words, path)
    if key not in got[2]:
        got[2][key] = try_lines(got[1], words, path)
    return got[2][key]
