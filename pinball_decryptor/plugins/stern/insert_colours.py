"""The colours of a game's single-colour inserts, and the Real LEDs / All RGB switch (PAD-668).

A single-colour insert gets one level from its board and no colour: on the machine it glows in its own LED's and
lens's colour, which no file of the game names. So the user gives each one its colour, once, and both places that
draw inserts read it: the emulator's playfield window (tools/spike2_emu/playfield.py, which keeps it in its state
file) and the Modes tab's Light shows preview. This is the app's side of that one file - the same path and the same
keys, so a colour set in either place shows in both:

    {"lens_colours": {"<game>": {"<insert name>": "#rrggbb"}}, "insert_look": "real" | "rgb", ...}

``insert_look``: "real" draws a single-colour insert in its own colour (white until set) at the level the show gives
it; "rgb" draws it in the show's colour, as if every insert were RGB. The file's other keys are the window's and are
kept as they are.
"""
import json
import os
import re

LOOKS = ("real", "rgb")

#: PAD-1144: a one-colour lamp whose NAME says its colour ("TOP GI-BLU (x10)", "R2D2-WHT") glows in it until the user
#: sets another. The same rule as the emulator's tools/spike2_emu/cablights.py (NAMED_COLOURS, named_colour), which
#: cannot import this package; tests/test_pad1144_named_colours.py holds the two together.
NAMED_COLOURS = {
    "RED": "#ff2818", "GRN": "#28dc40", "GREEN": "#28dc40", "BLU": "#306eff", "BLUE": "#306eff", "WHT": "#ffffff",
    "WHITE": "#ffffff", "YEL": "#ffd600", "YLW": "#ffd600", "YELLOW": "#ffd600", "AMB": "#ffb000", "AMBER": "#ffb000",
    "ORG": "#ff7800", "ORANGE": "#ff7800", "PUR": "#a040ff", "PURPLE": "#a040ff", "PNK": "#ff5ab4", "PINK": "#ff5ab4",
    "CYN": "#20e0ff", "CYAN": "#20e0ff"}
_NAMED = re.compile(r"-\s*(%s)\s*(?:\(\s*X\s*\d+\s*\))?\s*$"
                    % "|".join(sorted(NAMED_COLOURS, key=len, reverse=True)), re.I)


def named_colour(name):
    """``"#rrggbb"`` the lamp's name says ("TOP GI-BLU (x10)" -> blue), or None: only after a dash, an "(xN)" count
    allowed after it."""
    m = _NAMED.search(str(name or ""))
    return NAMED_COLOURS[m.group(1).upper()] if m else None


def state_path():
    """The playfield window's state file (playfield.STATE): ``~/.pad_playfield.json``."""
    return os.path.join(os.path.expanduser("~"), ".pad_playfield.json")


def _load():
    try:
        with open(state_path(), encoding="utf-8") as f:
            st = json.load(f)
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(st):
    with open(state_path(), "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1)


def hex_colour(s):
    """'#rrggbb' in lower case, or None for anything else."""
    s = str(s or "").strip()
    if len(s) == 7 and s[0] == "#":
        try:
            int(s[1:], 16)
        except ValueError:
            return None
        return s.lower()
    return None


def table(game):
    """``{insert name: "#rrggbb"}`` the user set for ``game`` (its tables' name, e.g. ``godzilla_le``)."""
    got = (_load().get("lens_colours") or {}).get(str(game or "")) or {}
    return {str(n): h for n, h in ((n, hex_colour(v)) for n, v in got.items()) if h}


def set_colour(game, name, colour):
    """Set one insert's colour (``"#rrggbb"``) or put it back to white (None or anything else); returns the game's
    table."""
    st = _load()
    tab = st.setdefault("lens_colours", {}).setdefault(str(game or ""), {})
    h = hex_colour(colour)
    if h:
        tab[str(name)] = h
    else:
        tab.pop(str(name), None)
    _save(st)
    return table(game)


def look():
    """The Real LEDs / All RGB switch: "real" until it is first switched."""
    v = _load().get("insert_look")
    return v if v in LOOKS else LOOKS[0]


def set_look(value):
    value = value if value in LOOKS else LOOKS[0]
    st = _load()
    st["insert_look"] = value
    _save(st)
    return value
