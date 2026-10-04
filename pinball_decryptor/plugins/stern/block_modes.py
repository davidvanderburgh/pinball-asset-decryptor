"""A mode made of BLOCKS: rules snapped together in the Modes tab, turned into C (PAD-232).

The third way to make a mode, beside the form (:mod:`.mode_project`) and C (:mod:`.code_modes`).
A blocks mode IS a code mode: its folder holds ``<slug>.c`` and no ``mode.json``, so Try it,
Write, Duplicate, Copy to and Delete treat it exactly as they treat a mode written in C. What
makes it a blocks mode is ``blocks.json`` beside the C file: the program the page edits. Every
save writes the program and then the C it makes (:func:`to_c`), so the C file is always the
program's; a person who wants to carry on in C presses "Edit as C" (:func:`detach`), which
takes ``blocks.json`` away and leaves an ordinary code mode.

THE PROGRAM (``blocks.json``)::

    {
      "format": 1,
      "name": "RAMP FRENZY",
      "seconds": 30,              the mode's clock; 0 = no clock (it runs until a block ends it)
      "ends_on_drain": true,      the ball draining ends it
      "vars": [{"name": "combo", "reset": "ball"}],   per player; reset "ball" | "mode" | "game"
      "hud": {"on": true, "line": "SHOOT THE RAMPS",    PAD-375: the mode's HUD at the glass's edges
              "counters": [{"label": "COMBO", "sub": "", "value": {...}}, ...],   three across the top
              "timer": {"on": true, "label": "RAMPS", "icon": "maser"},         the badge counting its clock
              "gauge": {"on": false, "label": "", "kind": "diamond", "count": 3, "color": "#ff7800",
                        "value": {...}}},                                       pips on the right edge
      "scripts": [
        {"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"},
         "do": [{"op": "if", "cond": {...}, "then": [...], "else": [...]}, ...]}
      ]
    }

A script is a HAT (what sets it off) and the blocks it runs, in order. Hats: the mode starts or
ends, a shot is made (any time, or only while the mode runs or does not), any shot, every N
seconds while it runs, N seconds left, the ball drains, one of the game's events. Blocks: start
or end the mode, score, set or change a variable, if / else, a callout, words on the mode's
screen, light or free a shot's inserts, add time or set the clock (to any value: a variable,
the seconds left, a sum), a multiball, a line in the log. Values: a
number, a variable, a shot's hits this ball, how many shots the mode has scored, its points so
far, the seconds left, the balls in play, the player up, and + - x / of two values. Conditions:
compare two values, and / or / not, the mode is running, one of the game's own modes is running.

THE HUD (PAD-375). Ticked on, the mode has what the examples have at the glass's edges, built by the
card build like theirs (:mod:`.mode_hud`, from the ``hud`` this module writes into assets.json): the
mode's name and an instruction line above the score panel, up to three counters across the top (each
can follow a value by itself), a timer badge counting the mode's clock, a gauge of pips on the right
edge, and an award line for a moment. Blocks write it: the title or instruction line, a counter, the
gauge, an award (on a mode that is not running, the award is a note: shown alone for its moment, when
no other HUD is up). The C drives it with the examples' own kit (``intricate_kit.h``'s ``struct
kit_hud``, copied into the folder at every save), so it steps aside exactly as theirs do: under a
display of the game's (``pm_display_covered``) its words are blank and the edges stay; while one of
the game's own modes runs (``pm_aside``) its lines go into the award line, the counters hide, and the
badge moves one slot down for a battle. The mode's own screen, when it has one, is hidden then too.
At the end the HUD shows the mode's TOTAL for three seconds (a drain or the game moving on takes it
down at once).

The C is the SDK's template (``sdk/template_mode.c``) in shape: static state, never blocking, a
0 from the game is carried on past, ``pm_begin`` / ``pm_end`` around a run, and the folder's own
test triggers (``/dump/<slug>.start`` / ``.stop``) so the tab's Start mode now and End mode reach
it. Its names follow ``mode_tryit.code_mode_text`` (``PadMode_<slug>_Screen``, ``<ident>_mode``)
so a rename rewrites it the way it rewrites any code mode.
"""
from __future__ import annotations

import copy
import json
import os
import re

from . import mode_project as MP

BLOCKS_FILE = "blocks.json"
FORMAT = 1
SECONDS_MAX = 600
MAX_SCRIPTS = 48
MAX_BLOCKS = 400
MAX_DEPTH = 10
MAX_VARS = 24
NUMBER_MAX = 10 ** 15            # points, counts and seconds: any sane number fits
TEXT_MAX = 60

#: what sets a script off, and the words the page shows for it
HATS = {
    "mode_start": "When the mode starts",
    "mode_end": "When the mode ends",
    "shot": "When a shot is made",
    "any_shot": "When any shot is made",
    "every": "Every few seconds while it runs",
    "seconds_left": "When seconds are left",
    "ball_end": "When the ball drains",
    "event": "When the game does something",
}
#: a shot / event hat's "when": the mode's state it runs in
WHEN = {"any": "any time", "idle": "while the mode is not running", "running": "while the mode runs"}
RESETS = {"ball": "each ball", "mode": "each time the mode starts", "game": "each game"}
STATEMENTS = ("start_mode", "end_mode", "score", "set", "change", "if", "callout", "words",
              "light_shot", "lights_off", "add_time", "set_time", "multiball", "log",
              "hud_text", "hud_counter", "hud_gauge", "hud_award")
#: PAD-375: the HUD's pieces (mode_hud.py draws them): the badge's icons, the gauge's pips
HUD_ICONS = ("xilien", "bolt", "ghidorah", "oxygen", "maser", "radiation", "anguirus")
GAUGE_KINDS = ("diamond", "segment", "spike")
GAUGE_MAX = 12                   # intricate_kit.h's KIT_HUD_PIPS
HUD_TEXT_MAX = 40                # a title or line (the kit's KIT_HUD_WORDS is 48, with its number)
COUNTER_MAX = 16                 # a counter's label or sub-label (the kit holds 23)
BADGE_MAX = 12                   # the badge's label, lettered on the stock BATTLE panel
AWARD_SECONDS_MAX = 10
KIT_FILE = "intricate_kit.h"
DISPLAY_PRIORITY = 180           # the kit's KIT_DISPLAY_MODE: what pm_display_covered watches for
TOTAL_MS = 3000                  # the HUD's TOTAL stays up this long after the end
PATTERNS = {"solid": ("PM_LAMP_SOLID", 0), "blink": ("PM_LAMP_BLINK", 500),
            "pulse": ("PM_LAMP_PULSE", 1600), "chase": ("PM_LAMP_CHASE", 150)}
#: the game's own callouts a block can name by what they say (every port carries these roles)
CALLOUT_ROLES = {"ten_seconds": "Ten seconds left", "time_up": "Time is up"}
NUM_KINDS = ("num", "var", "hits", "scored", "total", "secs_left", "balls", "player", "op")
BOOL_KINDS = ("cmp", "and", "or", "not", "running", "stock")
OPS = {"+": "+", "-": "-", "*": "*", "/": "/"}
CMPS = {"<": "<", "<=": "<=", "=": "==", "!=": "!=", ">=": ">=", ">": ">"}
VAR_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _]{0,23}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class BlocksError(ValueError):
    """A blocks.json that cannot be used; the message is a sentence."""


# ---- the project ------------------------------------------------------------------------------
def blocks_path(project, slug):
    return os.path.join(MP.mode_folder(project, slug), BLOCKS_FILE)


def is_blocks(project, slug):
    return bool(project and slug) and os.path.isfile(blocks_path(project, slug))


def load(project, slug):
    """The mode's program, as saved. Raises :class:`BlocksError` for a file that is not one."""
    try:
        with open(blocks_path(project, slug), "r", encoding="utf-8") as f:
            data = json.load(f)
    except ValueError as e:
        raise BlocksError("its %s is not JSON: %s" % (BLOCKS_FILE, e)) from None
    if not isinstance(data, dict):
        raise BlocksError("its %s holds no program" % BLOCKS_FILE)
    if int(data.get("format", 1) or 1) > FORMAT:
        raise BlocksError("these blocks were saved by a newer version of the app")
    return normalize(data)


def normalize(data):
    """``data`` with every top-level key present and of its kind (what the page and the
    translator can rely on). Blocks inside are left as they are; :func:`problems` names any
    that do not make sense."""
    out = copy.deepcopy(data) if isinstance(data, dict) else {}
    out["format"] = FORMAT
    out["name"] = str(out.get("name") or "").strip()[:40]
    try:
        out["seconds"] = max(0, min(SECONDS_MAX, int(out.get("seconds", 30))))
    except (TypeError, ValueError):
        out["seconds"] = 30
    out["ends_on_drain"] = bool(out.get("ends_on_drain", True))
    out["screen"] = bool(out.get("screen", False))
    out["vars"] = [v for v in (out.get("vars") or []) if isinstance(v, dict)]
    out["scripts"] = [s for s in (out.get("scripts") or []) if isinstance(s, dict)]
    out["hud"] = _norm_hud(out.get("hud"))
    for s in out["scripts"]:
        for b in _walk(s.get("do")):
            # PAD-372: Add seconds takes a value; one saved before held a plain number
            secs = b.get("seconds")
            if b.get("op") == "add_time" and isinstance(secs, (int, float)) and not isinstance(secs, bool):
                b["seconds"] = {"k": "num", "v": b["seconds"]}
    return out


def _norm_hud(h):
    """The HUD's settings with every key there: off, three empty counters, a timer badge and no
    gauge unless said. A value a counter or the gauge follows is kept as it is (problems names a
    bad one)."""
    h = h if isinstance(h, dict) else {}
    text = lambda v, n: str(v or "").strip()[:n]                     # noqa: E731
    value = lambda v: v if isinstance(v, dict) else None             # noqa: E731
    given = list(h.get("counters") or [])[:3]
    counters = []
    for i in range(3):
        c = given[i] if i < len(given) and isinstance(given[i], dict) else {}
        counters.append({"label": text(c.get("label"), COUNTER_MAX), "sub": text(c.get("sub"), COUNTER_MAX),
                         "value": value(c.get("value"))})
    t = h.get("timer") if isinstance(h.get("timer"), dict) else {}
    g = h.get("gauge") if isinstance(h.get("gauge"), dict) else {}
    try:
        count = max(1, min(GAUGE_MAX, int(g.get("count", 3))))
    except (TypeError, ValueError):
        count = 3
    return {"on": bool(h.get("on", False)), "line": text(h.get("line"), HUD_TEXT_MAX),
            "counters": counters,
            "timer": {"on": bool(t.get("on", True)), "label": text(t.get("label"), BADGE_MAX),
                      "icon": t.get("icon") if t.get("icon") in HUD_ICONS else HUD_ICONS[0]},
            "gauge": {"on": bool(g.get("on", False)), "label": text(g.get("label"), COUNTER_MAX),
                      "kind": g.get("kind") if g.get("kind") in GAUGE_KINDS else GAUGE_KINDS[0],
                      "count": count,
                      "color": g.get("color") if COLOR_RE.match(str(g.get("color") or "")) else "#ff7800",
                      "value": value(g.get("value"))}}


def hud_spec(program, slug=""):
    """The ``hud`` of the mode's assets.json: what the card build draws (:func:`.mode_hud.hud_group`),
    or {} with the HUD off. A counter with no label is left empty; the badge says the mode's name
    when it has no label of its own."""
    program = normalize(program)
    h = program["hud"]
    if not h["on"]:
        return {}
    title = program["name"] or slug.upper()
    counters = [[c["label"], "0", c["sub"] or " "] if c["label"] else [] for c in h["counters"]]
    while counters and not counters[-1]:
        counters.pop()
    out = {"title": title, "line": h["line"] or " ", "counters": counters}
    if h["timer"]["on"]:
        out["timer"] = {"label": h["timer"]["label"] or title[:BADGE_MAX], "icon": h["timer"]["icon"]}
    if h["gauge"]["on"]:
        rgb = int(h["gauge"]["color"][1:], 16)
        out["gauge"] = {"label": h["gauge"]["label"] or " ", "kind": h["gauge"]["kind"],
                        "count": h["gauge"]["count"],
                        "colours": [[rgb >> 16 & 255, rgb >> 8 & 255, rgb & 255]]}
    return out


def save(project, slug, program):
    """Write the program and the C it makes, the C first so a mode is never left with blocks
    that disagree with its C. Returns the C file's path."""
    program = normalize(program)
    folder = MP.mode_folder(project, slug)
    os.makedirs(folder, exist_ok=True)
    src = os.path.join(folder, slug + ".c")
    if program["hud"]["on"]:
        _copy_kit(folder)
    _write(src, to_c(program, slug))
    text = json.dumps(program, indent=2) + "\n"
    _write(blocks_path(project, slug), text)
    _sync_assets(project, slug, program)
    return src


def _write(path, text):
    with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def _copy_kit(folder):
    """The examples' kit beside the C (its HUD is the kit's): the SDK's copy at every save, so a
    blocks mode always builds against the kit of the app that saved it."""
    from . import code_modes as CM
    with open(os.path.join(CM.examples_dir(), KIT_FILE), "r", encoding="utf-8") as f:
        text = f.read()
    dst = os.path.join(folder, KIT_FILE)
    try:
        with open(dst, "r", encoding="utf-8") as f:
            if f.read() == text:
                return
    except OSError:
        pass
    _write(dst, text)


def _sync_assets(project, slug, program):
    """The mode's assets.json says its name, its clock and whether it has a screen of its own
    (the build makes the screen: a panel with its name, and a line of words the blocks write)."""
    from . import code_modes as CM
    try:
        spec = CM.load(project, slug)
    except (OSError, ValueError):
        spec = CM.CodeAssets(screen=False)
    hud = hud_spec(program, slug)
    changed = (spec.name != (program["name"] or slug.upper()) or bool(spec.screen) != program["screen"]
               or spec.seconds != max(1, program["seconds"] or 60) or dict(spec.hud or {}) != hud)
    if changed or not os.path.isfile(os.path.join(MP.mode_folder(project, slug), CM.ASSETS_FILE)):
        spec.name = program["name"] or slug.upper()
        spec.screen = program["screen"]
        spec.seconds = max(1, program["seconds"] or 60)
        spec.hud = hud
        CM.save(project, slug, spec)


def regenerate(project, slug, name=None):
    """Write the C again from the saved blocks (after the folder moved to ``slug``, or took a
    new ``name``). Returns True when there were blocks to write it from."""
    if not is_blocks(project, slug):
        return False
    program = load(project, slug)
    if name is not None:
        program["name"] = str(name)
    save(project, slug, program)
    return True


def detach(project, slug):
    """Edit as C: the mode keeps its C file (the one its blocks made) and loses its blocks, so
    it is an ordinary code mode from now on. The blocks are kept beside it as
    ``blocks.json.bak`` in case the person wants them back by hand."""
    path = blocks_path(project, slug)
    if os.path.isfile(path):
        os.replace(path, path + ".bak")
    return MP.mode_folder(project, slug)


# ---- a new mode --------------------------------------------------------------------------------
def starter(name, shots=()):
    """A new blocks mode's program: a whole, working mode to change, on the card's own shots.
    The first two shots are its start shot and a jackpot; with no shots known the shot boxes
    are empty for the person to fill."""
    names = [n for n in shots or () if n]
    start = names[0] if names else ""
    jack = names[1] if len(names) > 1 else start
    num = lambda v: {"k": "num", "v": v}                            # noqa: E731
    return normalize({
        "name": name, "seconds": 30, "ends_on_drain": True, "screen": False,
        "vars": [{"name": "combo", "reset": "mode"}],
        "scripts": [
            {"hat": {"kind": "shot", "shot": start, "when": "idle"}, "do": [
                {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": {"k": "hits", "shot": start},
                                      "b": num(3)},
                 "then": [{"op": "start_mode"}], "else": None}]},
            {"hat": {"kind": "mode_start"}, "do": [
                {"op": "set", "var": "combo", "value": num(1)},
                {"op": "light_shot", "shot": jack, "color": "#ffd000", "pattern": "blink"}]},
            {"hat": {"kind": "any_shot", "when": "running"}, "do": [
                {"op": "score", "points": {"k": "op", "op": "*", "a": num(500000),
                                           "b": {"k": "var", "name": "combo"}}},
                {"op": "change", "var": "combo", "by": num(1)}]},
            {"hat": {"kind": "shot", "shot": jack, "when": "running"}, "do": [
                {"op": "score", "points": num(5000000)},
                {"op": "add_time", "seconds": num(5)}]},
            {"hat": {"kind": "seconds_left", "seconds": 10}, "do": [
                {"op": "callout", "role": "ten_seconds"}]},
            {"hat": {"kind": "mode_end"}, "do": [
                {"op": "log", "text": "the mode ended"}]},
        ]})


def new_blocks_mode(project, name, shots=(), example=None):
    """A new blocks mode in ``modes/<slug>/``: its program (:func:`starter` on ``shots``), the C
    it makes and a default assets.json. Returns ``(slug, path of the C)``. Never overwrites a
    folder that exists."""
    from . import mode_tryit as MT
    if not project or not os.path.isdir(project):
        raise MT.TryItError(MP.NO_PROJECT_HELP)
    name = MT._c_title(str(name or "").strip()[:40], "mode") or "NEW MODE"
    slug = MT._free_slug(project, MP.slugify(name))
    if example == "ramps" and not shots:
        shots = [n for n, _m in MP.GODZILLA_PRO_1_15.shots]
    os.makedirs(MP.mode_folder(project, slug))
    path = save(project, slug, starter(name, shots))
    return slug, path


# ---- what is wrong with a program ----------------------------------------------------------------
def problems(program, shots=None, events=None):
    """Every reason the program cannot be built, as sentences (empty = it can). ``shots`` and
    ``events``, when given, are the card's: a block naming a shot or event the card does not
    have is named here. The C is written anyway (a missing shot is 0 to the game, which never
    matches), so a half-made program always saves."""
    program = normalize(program)
    out = []
    names = [str(v.get("name") or "") for v in program["vars"]]
    seen = set()
    for n in names:
        if not VAR_RE.match(n):
            out.append("A variable's name %r is not one: start with a letter, then letters, "
                       "digits, spaces or _ (24 at most)." % n)
        elif n.lower() in seen:
            out.append("Two variables are called %s." % n)
        seen.add(n.lower())
    if len(names) > MAX_VARS:
        out.append("%d variables: %d at most." % (len(names), MAX_VARS))
    if len(program["scripts"]) > MAX_SCRIPTS:
        out.append("%d scripts: %d at most." % (len(program["scripts"]), MAX_SCRIPTS))
    ctx = {"vars": set(n.lower() for n in names), "shots": set(shots) if shots is not None else None,
           "events": set(events) if events is not None else None, "count": 0, "out": out,
           "seconds": program["seconds"]}
    hud = program["hud"]
    if hud["on"]:
        for k, c in enumerate(hud["counters"]):
            if c["value"] is not None:
                _check_num(c["value"], "The HUD's counter %d" % (k + 1), ctx)
        if hud["gauge"]["on"] and hud["gauge"]["value"] is not None:
            _check_num(hud["gauge"]["value"], "The HUD's gauge", ctx)
    for i, s in enumerate(program["scripts"]):
        _check_hat(s.get("hat") or {}, i + 1, ctx)
        _check_stack(s.get("do") or [], 1, "Script %d" % (i + 1), ctx)
    if ctx["count"] > MAX_BLOCKS:
        out.append("%d blocks: %d at most." % (ctx["count"], MAX_BLOCKS))
    return _unique(out)


def notes(program):
    """What is worth knowing but does not stop a build: nothing starts the mode, a timer block
    with no clock, words with no screen."""
    program = normalize(program)
    ops = set()
    kinds = set()
    for s in program["scripts"]:
        kinds.add((s.get("hat") or {}).get("kind"))
        for b in _walk(s.get("do") or []):
            ops.add(b.get("op"))
    out = []
    if "start_mode" not in ops:
        out.append("No block starts the mode yet: put Start the mode in a script (Start mode now "
                   "starts it for a test either way).")
    if not program["seconds"] and "end_mode" not in ops and not program["ends_on_drain"]:
        out.append("Nothing ends this mode: it has no clock, the ball draining does not end it, "
                   "and no End the mode block.")
    if not program["seconds"] and ({"seconds_left"} & kinds or {"add_time", "set_time"} & ops):
        out.append("The mode has no clock, so seconds-left, add-time and set-the-clock blocks do nothing.")
    if "words" in ops and not program["screen"]:
        out.append("Show words needs the mode's own screen: tick Its own screen.")
    hud = program["hud"]
    if not hud["on"] and {"hud_text", "hud_counter", "hud_gauge", "hud_award"} & ops:
        out.append("The HUD blocks need the HUD: tick Its HUD.")
    if hud["on"]:
        named = set()
        for s in program["scripts"]:
            for b in _walk(s.get("do") or []):
                if b.get("op") == "hud_counter" and _int_ok(b.get("counter"), 1, 3):
                    named.add(int(b["counter"]))
        for k in sorted(named):
            if not hud["counters"][k - 1]["label"]:
                out.append("A block sets HUD counter %d, which has no label, so it is not shown: "
                           "give it one under Its HUD." % k)
        if "hud_gauge" in ops and not hud["gauge"]["on"]:
            out.append("A block fills the HUD's gauge, which is switched off: tick Gauge under Its HUD.")
        if hud["timer"]["on"] and not program["seconds"]:
            out.append("The HUD's timer badge counts the mode's clock, and it has none: it is not shown.")
    return out


def _unique(items):
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _walk(stack):
    for b in stack or []:
        if not isinstance(b, dict):
            continue
        yield b
        if b.get("op") == "if":
            yield from _walk(b.get("then"))
            yield from _walk(b.get("else"))


def _check_shot(shot, where, ctx):
    if not shot:
        ctx["out"].append("%s has no shot chosen." % where)
    elif ctx["shots"] is not None and shot not in ctx["shots"]:
        ctx["out"].append("%s names %s, a shot this card does not have." % (where, shot))


def _check_hat(hat, n, ctx):
    kind = hat.get("kind")
    where = "Script %d" % n
    if kind not in HATS:
        ctx["out"].append("%s starts with no When block." % where)
        return
    if kind in ("shot",):
        _check_shot(hat.get("shot"), where + "'s When", ctx)
    if kind in ("shot", "any_shot", "event") and hat.get("when", "any") not in WHEN:
        ctx["out"].append("%s's When has no while." % where)
    if kind == "event":
        ev = hat.get("event")
        if not ev:
            ctx["out"].append("%s's When has no event chosen." % where)
        elif ctx["events"] is not None and ev not in ctx["events"]:
            ctx["out"].append("%s waits for %s, which this card's game does not report."
                              % (where, MP.EVENT_LABELS.get(ev, ev)))
    if kind in ("every", "seconds_left"):
        if not _int_ok(hat.get("seconds"), 1, SECONDS_MAX):
            ctx["out"].append("%s's seconds must be 1 to %d." % (where, SECONDS_MAX))


def _int_ok(v, lo, hi):
    try:
        return lo <= int(v) <= hi and float(v) == int(v)
    except (TypeError, ValueError):
        return False


def _check_stack(stack, depth, where, ctx):
    if depth > MAX_DEPTH:
        ctx["out"].append("Blocks in %s are nested more than %d deep." % (where, MAX_DEPTH))
        return
    if not isinstance(stack, list):
        ctx["out"].append("%s holds something that is not a list of blocks." % where)
        return
    for b in stack:
        ctx["count"] += 1
        if not isinstance(b, dict) or b.get("op") not in STATEMENTS:
            ctx["out"].append("%s holds a block this version does not know." % where)
            continue
        op = b["op"]
        if op == "score":
            _check_num(b.get("points"), where, ctx)
        elif op in ("set", "change"):
            if str(b.get("var") or "").lower() not in ctx["vars"]:
                ctx["out"].append("%s sets a variable that is not there: make it under Variables."
                                  % where)
            _check_num(b.get("value" if op == "set" else "by"), where, ctx)
        elif op == "if":
            _check_bool(b.get("cond"), where, ctx)
            _check_stack(b.get("then") or [], depth + 1, where, ctx)
            _check_stack(b.get("else") or [], depth + 1, where, ctx)
        elif op == "callout":
            role = b.get("role")
            if role not in CALLOUT_ROLES and not _int_ok(b.get("id"), 1, 65535):
                ctx["out"].append("%s has a callout with none chosen." % where)
        elif op == "words":
            if len(str(b.get("text") or "")) > TEXT_MAX:
                ctx["out"].append("%s shows more than %d letters of words." % (where, TEXT_MAX))
            if b.get("value") is not None:
                _check_num(b.get("value"), where, ctx)
        elif op in ("light_shot", "lights_off"):
            if op == "lights_off" and b.get("shot") == "*":
                continue
            _check_shot(b.get("shot"), where + "'s lights", ctx)
            if op == "light_shot":
                if not COLOR_RE.match(str(b.get("color") or "")):
                    ctx["out"].append("%s lights a shot in no colour." % where)
                if b.get("pattern") not in PATTERNS:
                    ctx["out"].append("%s lights a shot in no pattern." % where)
        elif op in ("add_time", "set_time"):
            secs = b.get("seconds")
            _check_num(secs, where, ctx)
            lo = -SECONDS_MAX if op == "add_time" else 0
            if (isinstance(secs, dict) and secs.get("k") == "num"
                    and _int_ok(secs.get("v"), -NUMBER_MAX, NUMBER_MAX)
                    and not _int_ok(secs.get("v"), lo, SECONDS_MAX)):
                ctx["out"].append("%s %s: %d to %d seconds." % (
                    where, "adds a time" if op == "add_time" else "sets the clock", lo, SECONDS_MAX))
        elif op == "multiball":
            if not _int_ok(b.get("balls"), 2, 6):
                ctx["out"].append("%s asks for a multiball of 2 to 6 balls." % where)
            if not _int_ok(b.get("save", 0), 0, 60):
                ctx["out"].append("%s has a ball save of 0 to 60 seconds." % where)
        elif op == "log":
            if len(str(b.get("text") or "")) > TEXT_MAX:
                ctx["out"].append("%s logs more than %d letters." % (where, TEXT_MAX))
        elif op == "hud_text":
            if b.get("which") not in ("title", "line"):
                ctx["out"].append("%s writes the HUD's title or line: choose which." % where)
            if len(str(b.get("text") or "")) > HUD_TEXT_MAX:
                ctx["out"].append("%s puts more than %d letters on the HUD." % (where, HUD_TEXT_MAX))
            if b.get("value") is not None:
                _check_num(b.get("value"), where, ctx)
        elif op == "hud_counter":
            if not _int_ok(b.get("counter"), 1, 3):
                ctx["out"].append("%s sets a HUD counter: 1, 2 or 3." % where)
            _check_num(b.get("value"), where, ctx)
            if len(str(b.get("sub") or "")) > COUNTER_MAX:
                ctx["out"].append("%s has a counter's words of more than %d letters." % (where, COUNTER_MAX))
        elif op == "hud_gauge":
            _check_num(b.get("value"), where, ctx)
        elif op == "hud_award":
            for key in ("text", "sub"):
                if len(str(b.get(key) or "")) > HUD_TEXT_MAX:
                    ctx["out"].append("%s puts more than %d letters on the HUD." % (where, HUD_TEXT_MAX))
            if b.get("value") is not None:
                _check_num(b.get("value"), where, ctx)
            if not _int_ok(b.get("seconds"), 1, AWARD_SECONDS_MAX):
                ctx["out"].append("%s shows an award for 1 to %d seconds." % (where, AWARD_SECONDS_MAX))


def _check_num(e, where, ctx, depth=0):
    if depth > MAX_DEPTH:
        ctx["out"].append("A value in %s is nested too deep." % where)
        return
    if not isinstance(e, dict) or e.get("k") not in NUM_KINDS:
        ctx["out"].append("%s has an empty number slot." % where)
        return
    k = e["k"]
    if k == "num":
        if not _int_ok(e.get("v"), -NUMBER_MAX, NUMBER_MAX):
            ctx["out"].append("%s has a number that is not a whole number (%r)." % (where, e.get("v")))
    elif k == "var":
        if str(e.get("name") or "").lower() not in ctx["vars"]:
            ctx["out"].append("%s uses a variable that is not there: make it under Variables." % where)
    elif k == "hits":
        _check_shot(e.get("shot"), where + "'s hits", ctx)
    elif k == "op":
        if e.get("op") not in OPS:
            ctx["out"].append("%s has a sum with no + - x or /." % where)
        _check_num(e.get("a"), where, ctx, depth + 1)
        _check_num(e.get("b"), where, ctx, depth + 1)


def _check_bool(e, where, ctx, depth=0):
    if depth > MAX_DEPTH:
        ctx["out"].append("A condition in %s is nested too deep." % where)
        return
    if not isinstance(e, dict) or e.get("k") not in BOOL_KINDS:
        ctx["out"].append("%s has an If with no condition." % where)
        return
    k = e["k"]
    if k == "cmp":
        if e.get("op") not in CMPS:
            ctx["out"].append("%s compares with no < = or >." % where)
        _check_num(e.get("a"), where, ctx, depth + 1)
        _check_num(e.get("b"), where, ctx, depth + 1)
    elif k in ("and", "or"):
        _check_bool(e.get("a"), where, ctx, depth + 1)
        _check_bool(e.get("b"), where, ctx, depth + 1)
    elif k == "not":
        _check_bool(e.get("a"), where, ctx, depth + 1)


# ---- the words the list and the page show -----------------------------------------------------
def summary(program):
    """One line: how many scripts and blocks, and its clock."""
    program = normalize(program)
    n = sum(1 for s in program["scripts"] for _b in _walk(s.get("do") or []))
    clock = ("runs %d seconds" % program["seconds"]) if program["seconds"] else "no clock"
    return "%d script%s, %d block%s, %s" % (len(program["scripts"]),
                                            "" if len(program["scripts"]) == 1 else "s",
                                            n, "" if n == 1 else "s", clock)


# ---- the C -----------------------------------------------------------------------------------------
def _c_str(text):
    """``text`` as a C string literal: printable ASCII only, quotes and backslashes escaped, and
    nothing that could close a comment or start a trigraph."""
    s = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in str(text or ""))
    s = s.replace("\\", "\\\\").replace('"', '\\"').replace("??", "?\\?")
    return '"%s"' % s


def _comment(text):
    s = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in str(text or ""))
    return s.replace("*/", "* /").replace("/*", "/ *")


class _Gen:
    """The translator's tables: every shot, event and variable the program names gets one
    static of its own, looked up once in init."""

    def __init__(self, program, slug):
        self.p = program
        self.slug = slug
        self.shots = []                 # shot names, in first-use order
        self.events = []
        self.vars = {}                  # lower name -> index
        self.var_names = []
        for v in program["vars"]:
            n = str(v.get("name") or "")
            if VAR_RE.match(n) and n.lower() not in self.vars:
                self.vars[n.lower()] = len(self.var_names)
                self.var_names.append((n, v.get("reset") if v.get("reset") in RESETS else "ball"))
        self.hits = []                  # shots whose hits this ball the program reads

    def shot(self, name):
        name = str(name or "")
        if name not in self.shots:
            self.shots.append(name)
        return "S[%d]" % self.shots.index(name)

    def event(self, name):
        name = str(name or "")
        if name not in self.events:
            self.events.append(name)
        return "E[%d]" % self.events.index(name)

    def hit(self, name):
        name = str(name or "")
        idx = self.shot(name)
        if name not in self.hits:
            self.hits.append(name)
        return "H[%d][P()]" % self.hits.index(name), idx

    # values
    def num(self, e):
        if not isinstance(e, dict):
            return "0LL"
        k = e.get("k")
        if k == "num":
            try:
                v = max(-NUMBER_MAX, min(NUMBER_MAX, int(e.get("v"))))
            except (TypeError, ValueError):
                v = 0
            return "(%dLL)" % v
        if k == "var":
            i = self.vars.get(str(e.get("name") or "").lower())
            return "V[%d][P()]" % i if i is not None else "0LL"
        if k == "hits":
            return "(long long)" + self.hit(e.get("shot"))[0]
        if k == "scored":
            return "(long long)run.shots"
        if k == "total":
            return "(long long)run.total"
        if k == "secs_left":
            return "(long long)secs_left()"
        if k == "balls":
            return "(long long)pm_balls_in_play()"
        if k == "player":
            return "(long long)pm_player()"
        if k == "op":
            a, b = self.num(e.get("a")), self.num(e.get("b"))
            op = e.get("op")
            if op == "/":
                return "div0(%s, %s)" % (a, b)
            return "(%s %s %s)" % (a, OPS.get(op, "+"), b)
        return "0LL"

    def cond(self, e):
        if not isinstance(e, dict):
            return "0"
        k = e.get("k")
        if k == "cmp":
            return "(%s %s %s)" % (self.num(e.get("a")), CMPS.get(e.get("op"), "=="), self.num(e.get("b")))
        if k == "and":
            return "(%s && %s)" % (self.cond(e.get("a")), self.cond(e.get("b")))
        if k == "or":
            return "(%s || %s)" % (self.cond(e.get("a")), self.cond(e.get("b")))
        if k == "not":
            return "(!%s)" % self.cond(e.get("a"))
        if k == "running":
            return "run.on"
        if k == "stock":
            return "pm_stock_mode_running(PM_STOCK_ANY)"
        return "0"

    # blocks
    def stack(self, stack, ind):
        out = []
        pad = "    " * ind
        for b in stack or []:
            if not isinstance(b, dict):
                continue
            op = b.get("op")
            if op == "start_mode":
                out.append(pad + 'start("a block");')
            elif op == "end_mode":
                out.append(pad + 'end("a block");')
            elif op == "score":
                out.append(pad + "score(%s);" % self.num(b.get("points")))
            elif op == "set":
                i = self.vars.get(str(b.get("var") or "").lower())
                if i is not None:
                    out.append(pad + "V[%d][P()] = %s;" % (i, self.num(b.get("value"))))
            elif op == "change":
                i = self.vars.get(str(b.get("var") or "").lower())
                if i is not None:
                    out.append(pad + "V[%d][P()] += %s;" % (i, self.num(b.get("by"))))
            elif op == "if":
                out.append(pad + "if (%s) {" % self.cond(b.get("cond")))
                out.extend(self.stack(b.get("then"), ind + 1))
                if b.get("else"):
                    out.append(pad + "} else {")
                    out.extend(self.stack(b.get("else"), ind + 1))
                out.append(pad + "}")
            elif op == "callout":
                role = b.get("role")
                if role in CALLOUT_ROLES:
                    out.append(pad + "pm_callout(pm_callout_id(%s));" % _c_str(role))
                else:
                    try:
                        out.append(pad + "pm_callout(%du);" % max(1, min(65535, int(b.get("id")))))
                    except (TypeError, ValueError):
                        pass
            elif op == "words":
                value = b.get("value")
                out.append(pad + "words(%s, %s, %d);" % (
                    _c_str(str(b.get("text") or "")[:TEXT_MAX]),
                    self.num(value) if value is not None else "0LL", 0 if value is None else 1))
            elif op == "light_shot":
                pat, ms = PATTERNS.get(b.get("pattern"), PATTERNS["solid"])
                color = str(b.get("color") or "#ffffff")
                rgb = int(color[1:], 16) if COLOR_RE.match(color) else 0xFFFFFF
                out.append(pad + "if (%s) pm_lamp_shot(%s, 0x%06xu, %s, %du);"
                           % (self.shot(b.get("shot")), self.shot(b.get("shot")), rgb, pat, ms))
            elif op == "lights_off":
                if b.get("shot") == "*":
                    out.append(pad + "pm_lamp_release_all();")
                else:
                    s = self.shot(b.get("shot"))
                    out.append(pad + "if (%s) pm_lamp_release_shot(%s);" % (s, s))
            elif op in ("add_time", "set_time"):
                out.append(pad + "%s(%s);" % (op, self.num(b.get("seconds"))))
            elif op == "multiball":
                try:
                    balls = max(2, min(6, int(b.get("balls"))))
                    save = max(0, min(60, int(b.get("save", 0))))
                except (TypeError, ValueError):
                    balls, save = 2, 0
                out.append(pad + "if (run.on) pm_multiball_start(%du, %du);" % (balls, save))
            elif op == "log":
                out.append(pad + 'pm_log("%%s", %s);' % _c_str(str(b.get("text") or "")[:TEXT_MAX]))
            elif op.startswith("hud_") and not self.p["hud"]["on"]:
                out.append(pad + "/* %s: the mode has no HUD */" % op)
            elif op == "hud_text":
                value = b.get("value")
                out.append(pad + "hud_words(%d, %s, %s, %d);" % (
                    1 if b.get("which") == "line" else 0, _c_str(str(b.get("text") or "")[:HUD_TEXT_MAX]),
                    self.num(value) if value is not None else "0LL", 0 if value is None else 1))
            elif op == "hud_counter":
                try:
                    k = max(1, min(3, int(b.get("counter"))))
                except (TypeError, ValueError):
                    k = 1
                sub = b.get("sub")
                out.append(pad + "hud_counter(%d, %s, %s);" % (
                    k - 1, self.num(b.get("value")),
                    "0" if sub is None else _c_str(str(sub)[:COUNTER_MAX])))
            elif op == "hud_gauge":
                out.append(pad + "hud_level = %s;" % self.num(b.get("value")))
            elif op == "hud_award":
                value = b.get("value")
                try:
                    secs = max(1, min(AWARD_SECONDS_MAX, int(b.get("seconds"))))
                except (TypeError, ValueError):
                    secs = 2
                out.append(pad + "hud_award(%s, %s, %d, %s, %du);" % (
                    _c_str(str(b.get("text") or "")[:HUD_TEXT_MAX]),
                    self.num(value) if value is not None else "0LL", 0 if value is None else 1,
                    _c_str(str(b.get("sub") or "")[:HUD_TEXT_MAX]), secs * 1000))
        return out


def c_ident(slug):
    from . import mode_tryit as MT
    return MT._c_ident(slug)


def to_c(program, slug):
    """The C a program makes: one mode for the Mode SDK, in the template's shape."""
    program = normalize(program)
    g = _Gen(program, slug)
    name = program["name"] or slug.upper()
    from . import mode_tryit as MT
    title = MT._c_title(name, slug)
    ident = c_ident(slug)

    # every script's body first: that is when the tables fill
    bodies = {k: [] for k in HATS}
    for i, s in enumerate(program["scripts"]):
        hat = s.get("hat") or {}
        kind = hat.get("kind")
        if kind not in HATS:
            continue
        body = g.stack(s.get("do") or [], 2)
        bodies[kind].append((i + 1, hat, body))
    # the hats' own shots and events
    hat_code = {k: [] for k in HATS}
    for kind, items in bodies.items():
        for n, hat, body in items:
            head = "    /* script %d: %s */" % (n, _comment(_hat_words(hat)))
            when = hat.get("when", "any")
            # a shot or event is judged by the mode's state BEFORE it: the shot that starts
            # the mode is not also one "while it runs"
            gate = {"idle": "!was_on", "running": "was_on"}.get(when)
            if kind == "shot":
                test = "(%s && (shot & %s))" % (g.shot(hat.get("shot")), g.shot(hat.get("shot")))
                if gate:
                    test = "(%s && %s)" % (gate, test)
            elif kind == "any_shot":
                test = "(shot & named)"
                if gate:
                    test = "(%s && %s)" % (gate, test)
            elif kind == "event":
                test = "(%s >= 0 && id == (unsigned)%s)" % (g.event(hat.get("event")), g.event(hat.get("event")))
                if gate:
                    test = "(%s && %s)" % (gate, test)
            elif kind == "every":
                secs = max(1, min(SECONDS_MAX, int(hat.get("seconds") or 1)))
                test = "(run.on && run.elapsed %% %du == 0)" % (secs * 60)
            elif kind == "seconds_left":
                secs = max(1, min(SECONDS_MAX, int(hat.get("seconds") or 1)))
                test = "(run.on && sec_changed && run.seconds_shown == %du)" % secs
            else:
                test = None
            if test is None:
                hat_code[kind].append((n, "\n".join([head, "    {"] + body + ["    }"])))
            else:
                hat_code[kind].append((n, "\n".join([head, "    if %s {" % test] + body + ["    }"])))

    hud = program["hud"]
    has_hud = hud["on"]
    # PAD-375: a mode with a HUD or a screen of its own watches the game's displays (the kit's
    # kit_display): its words step aside under one, so it holds a display priority while it runs
    watch = has_hud or program["screen"]
    live = []                           # (counter 0-2, C of its value): counters that follow a value
    gauge_live = None
    if has_hud:
        for k, c in enumerate(hud["counters"]):
            if c["label"] and c["value"] is not None:
                live.append((k, g.num(c["value"])))
        if hud["gauge"]["on"] and hud["gauge"]["value"] is not None:
            gauge_live = g.num(hud["gauge"]["value"])

    def scripts_of(*kinds):
        """The scripts of these hats, in the order the page shows them: top to bottom."""
        return [code for _n, code in sorted(x for k in kinds for x in hat_code[k])]

    L = []
    L.append("/* %s.c - %s, a mode made of blocks in the Modes tab (PAD-232)" % (slug, _comment(title)))
    L.append(" *")
    L.append(" * MADE FROM blocks.json: the Modes tab writes this file again every time the blocks")
    L.append(" * change, so an edit here is lost at the next one. To carry on in C, press Edit as C")
    L.append(" * on the mode's page: the blocks are put away and this file is yours.")
    L.append(" *")
    L.append(" * " + _comment(summary(program)) + ".")
    L.append(" */")
    L.append('#include "pad_mode.h"')
    if has_hud:
        L.append('#include "%s"   /* the examples\' kit: the HUD (copied here at every save) */' % KIT_FILE)
    L.append("")
    L.append('#define MODE_NAME        %s' % _c_str(title))
    L.append("#define RUN_SECONDS      %d          /* 0 = no clock */" % program["seconds"])
    L.append("#define ENDS_ON_DRAIN    %d" % (1 if program["ends_on_drain"] else 0))
    L.append("#define TICKS_PER_SECOND 60")
    L.append("#define CLOCK_MAX        %d         /* the most seconds the clock holds */" % SECONDS_MAX)
    L.append("#define UNUSED __attribute__((unused))   /* a helper the blocks may not call */")
    L.append("")
    L.append("/* The screen a build added for this mode (its folder is \"%s\"). Not there = no screen. */" % slug)
    L.append('#define SCREEN_NODE  "PadMode_%s_Screen"' % slug)
    L.append('#define SCREEN_TEXT  "PadMode_%s_Screen.PadMode_%s_Screen_Words"' % (slug, slug))
    L.append("")
    L.append("/* ---- the shots, events and variables the blocks name ---- */")
    nshots, nevents, nvars, nhits = max(1, len(g.shots)), max(1, len(g.events)), max(1, len(g.var_names)), max(1, len(g.hits))
    L.append("UNUSED static const char *const SHOT_NAMES[%d] = {%s};" % (
        nshots, ", ".join(_c_str(s) for s in g.shots) or "0"))
    L.append("UNUSED static uint64_t S[%d];                /* each shot's mask; 0 = this game has none */" % nshots)
    L.append("static uint64_t named;               /* every named shot */")
    L.append("UNUSED static const char *const EVENT_NAMES[%d] = {%s};" % (
        nevents, ", ".join(_c_str(e) for e in g.events) or "0"))
    L.append("UNUSED static int E[%d];                     /* each event's id; -1 = this game has none */" % nevents)
    for i, (n, reset) in enumerate(g.var_names):
        L.append("/* V[%d] = %s, per player, reset %s */" % (i, _comment(n), RESETS[reset]))
    L.append("UNUSED static long long V[%d][5];            /* the variables, per player 1-4 */" % nvars)
    for i, n in enumerate(g.hits):
        L.append("/* H[%d] = hits of %s this ball */" % (i, _comment(n)))
    L.append("UNUSED static unsigned H[%d][5];             /* hits this ball, per player */" % nhits)
    L.append("UNUSED static const char HIT_OF[%d] = {%s};" % (
        nhits, ", ".join(str(g.shots.index(n)) for n in g.hits) or "0"))
    L.append("")
    L.append("static struct {")
    L.append("    int on;")
    L.append("    unsigned player, ticks_left, seconds_shown, elapsed, shots;")
    L.append("    uint64_t total;")
    L.append("} run;")
    L.append("static int sec_changed, was_in_game, ending;")
    L.append("static void *screen, *screen_words;")
    L.append("static unsigned hide_ticks, poll;")
    if watch:
        L.append("static int screen_away;                /* its screen hidden: a game display or mode has the middle */")
    if has_hud:
        L.append("")
        L.append("/* ---- the HUD at the glass's edges (PAD-375): the build's PadMode_%s_Hud group, driven by" % slug)
        L.append(" * the kit's struct kit_hud as the examples drive theirs - blank under a display of the game's,")
        L.append(" * aside while one of the game's modes runs. No HUD on the card: nothing shows, the mode runs. */")
        L.append('static struct kit_hud hud = { .slug = "%s" };' % slug)
        L.append("#define HUD_LINE   %s" % _c_str(hud["line"]))
        L.append("#define HUD_TIMER  %d          /* the badge counts the clock */" % (
            1 if hud["timer"]["on"] and program["seconds"] else 0))
        L.append("#define HUD_GAUGE  %d          /* pips of the gauge; 0 = no gauge */" % (
            hud["gauge"]["count"] if hud["gauge"]["on"] else 0))
        L.append("#define HUD_GAUGE_LABEL %s" % _c_str(hud["gauge"]["label"]))
        L.append("UNUSED static const char *const HUD_LABEL[3] = {%s};" % ", ".join(
            _c_str(c["label"]) for c in hud["counters"]))
        L.append("UNUSED static const char *const HUD_SUB[3] = {%s};" % ", ".join(
            _c_str(c["sub"]) for c in hud["counters"]))
        L.append("static char hud_val[3][24], hud_sub[3][24];   /* each counter's value and sub-label now */")
        L.append("UNUSED static long long hud_level;          /* the gauge's pips lit */")
    L.append("")
    L.append("static unsigned P(void)")
    L.append("{")
    L.append("    unsigned p = pm_player();")
    L.append("    return p <= 4 ? p : 0;")
    L.append("}")
    L.append("")
    L.append("UNUSED static long long div0(long long a, long long b)")
    L.append("{")
    L.append("    return b ? a / b : 0;")
    L.append("}")
    L.append("")
    L.append("UNUSED static unsigned secs_left(void)")
    L.append("{")
    L.append("    return run.on && RUN_SECONDS ? (run.ticks_left + TICKS_PER_SECOND - 1) / TICKS_PER_SECOND : 0;")
    L.append("}")
    L.append("")
    for when in ("ball", "mode"):
        L.append("static void reset_%s(void)          /* the variables reset %s */" % (when, RESETS[when]))
        L.append("{")
        L.append("    unsigned p = P();")
        for i, (_n, reset) in enumerate(g.var_names):
            if reset == when:
                L.append("    V[%d][p] = 0;" % i)
        L.append("    (void)p;")
        L.append("}")
        L.append("")
    L.append("UNUSED static void words(const char *text, long long value, int with_value)")
    L.append("{")
    L.append("    char number[32], line[96];")
    L.append("    if (!screen_words) return;")
    L.append("    if (with_value) {")
    L.append("        pm_commas(number, sizeof number, value < 0 ? 0 : (uint64_t)value);")
    L.append('        pm_snprintf(line, sizeof line, "%s%s%s", text, text[0] ? " " : "", number);')
    L.append("        pm_set_text(screen_words, line);")
    L.append("    } else {")
    L.append("        pm_set_text(screen_words, text);")
    L.append("    }")
    L.append("}")
    L.append("")
    L.append("UNUSED static void score(long long points)")
    L.append("{")
    L.append("    uint64_t got;")
    L.append("    if (!run.on || points <= 0) return;")
    L.append("    got = pm_score_add(run.player, (uint64_t)points);   /* the game may add less */")
    L.append("    run.total += got;")
    L.append("    run.shots++;")
    L.append("}")
    L.append("")
    L.append("/* The clock to this many ticks. Put UP, the second it lands on is not \"left\" again: a When N")
    L.append(" * seconds are left for it does not run (the kit's kit_timer_at_least); counting down past it")
    L.append(" * later, they run as ever. */")
    L.append("UNUSED static void clock_to(long long ticks)")
    L.append("{")
    L.append("    unsigned before = run.ticks_left;")
    L.append("    if (ticks < 0) ticks = 0;")
    L.append("    if (ticks > CLOCK_MAX * TICKS_PER_SECOND) ticks = CLOCK_MAX * TICKS_PER_SECOND;")
    L.append("    run.ticks_left = (unsigned)ticks;")
    L.append("    if (run.ticks_left > before) run.seconds_shown = secs_left();")
    L.append("}")
    L.append("")
    L.append("UNUSED static void add_time(long long seconds)   /* less than 0 takes time off; never to 0 */")
    L.append("{")
    L.append("    long long t;")
    L.append("    if (!run.on || !RUN_SECONDS) return;")
    L.append("    if (seconds > CLOCK_MAX) seconds = CLOCK_MAX;")
    L.append("    if (seconds < -CLOCK_MAX) seconds = -CLOCK_MAX;")
    L.append("    t = (long long)run.ticks_left + seconds * TICKS_PER_SECOND;")
    L.append("    clock_to(t > 0 ? t : 1);")
    L.append("}")
    L.append("")
    L.append("UNUSED static void set_time(long long seconds)   /* 0 = time is up */")
    L.append("{")
    L.append("    if (!run.on || !RUN_SECONDS) return;")
    L.append("    if (seconds > CLOCK_MAX) seconds = CLOCK_MAX;")
    L.append("    clock_to(seconds * TICKS_PER_SECOND);")
    L.append("}")
    L.append("")
    if has_hud:
        L.append("/* a counter (0-2) to a value, short enough for its 200 px (950,000 / 4.25M); sub 0 = as it is */")
        L.append("UNUSED static void hud_counter(int k, long long value, const char *sub)")
        L.append("{")
        L.append("    if (k < 0 || k > 2 || !HUD_LABEL[k][0]) return;      /* a counter with no label is not shown */")
        L.append("    kit_short(hud_val[k], sizeof hud_val[k], value < 0 ? 0 : (uint64_t)value);")
        L.append("    if (sub) kit_copy(hud_sub[k], sizeof hud_sub[k], sub);")
        L.append("}")
        L.append("")
        L.append("static void hud_line(char *line, unsigned cap, const char *text, long long value, int with_value)")
        L.append("{")
        L.append("    char number[32];")
        L.append("    if (!with_value) {")
        L.append("        kit_copy(line, cap, text);")
        L.append("        return;")
        L.append("    }")
        L.append("    pm_commas(number, sizeof number, value < 0 ? 0 : (uint64_t)value);")
        L.append('    pm_snprintf(line, cap, "%s%s%s", text, text[0] ? " " : "", number);')
        L.append("}")
        L.append("")
        L.append("/* the title (0) or the instruction line (1); kept until the mode starts again */")
        L.append("UNUSED static void hud_words(int which, const char *text, long long value, int with_value)")
        L.append("{")
        L.append("    char line[KIT_HUD_WORDS];")
        L.append("    hud_line(line, sizeof line, text, value, with_value);")
        L.append("    if (which) kit_hud_title(&hud, 0, line);")
        L.append("    else kit_hud_title(&hud, line, 0);")
        L.append("}")
        L.append("")
        L.append("/* the award line for a moment; on a mode not running, a note shown alone (kit_hud_note: not over")
        L.append(" * another mode's HUD) */")
        L.append("UNUSED static void hud_award(const char *text, long long value, int with_value, const char *sub,")
        L.append("                             unsigned ms)")
        L.append("{")
        L.append("    char line[KIT_HUD_WORDS];")
        L.append("    hud_line(line, sizeof line, text, value, with_value);")
        L.append("    if (run.on) kit_hud_award(&hud, ms, line, sub);")
        L.append("    else kit_hud_note(&hud, ms, line, sub[0] ? sub : MODE_NAME);")
        L.append("}")
        L.append("")
        L.append("/* every tick while it runs: the counters that follow a value, the badge, the gauge */")
        L.append("static void hud_show(void)")
        L.append("{")
        L.append("    int k;")
        for k, expr in live:
            L.append("    hud_counter(%d, %s, 0);" % (k, expr))
        if gauge_live is not None:
            L.append("    hud_level = %s;" % gauge_live)
        L.append("    for (k = 0; k < 3; k++)")
        L.append("        if (HUD_LABEL[k][0]) kit_hud_counter(&hud, k, HUD_LABEL[k], hud_val[k], hud_sub[k]);")
        L.append("    kit_hud_timer(&hud, HUD_TIMER ? (int)secs_left() : -1);")
        L.append("    if (HUD_GAUGE)")
        L.append("        kit_hud_gauge(&hud, hud_level < 0 ? 0 : hud_level > HUD_GAUGE ? HUD_GAUGE : (int)hud_level,")
        L.append("                      HUD_GAUGE_LABEL);")
        L.append("}")
        L.append("")
    L.append("static void start(const char *why);")
    L.append("static void end(const char *why);")
    L.append("")
    L.append("static void on_mode_start(void)")
    L.append("{")
    L.extend(scripts_of("mode_start") or ["    /* no script */"])
    L.append("}")
    L.append("")
    L.append("static void on_mode_end(void)")
    L.append("{")
    L.extend(scripts_of("mode_end") or ["    /* no script */"])
    L.append("}")
    L.append("")
    L.append("static void start(const char *why)")
    L.append("{")
    L.append("    if (run.on || !pm_in_game()) return;")
    L.append("    if (!pm_begin()) return;          /* another of our modes is running */")
    L.append("    run.on = 1;")
    L.append("    run.player = pm_player();")
    L.append("    run.ticks_left = RUN_SECONDS * TICKS_PER_SECOND;")
    L.append("    run.seconds_shown = RUN_SECONDS;")
    L.append("    run.elapsed = 0;")
    L.append("    run.shots = 0;")
    L.append("    run.total = 0;")
    L.append("    hide_ticks = 0;")
    L.append('    reset_mode();')
    if watch:
        L.append("    pm_display_priority(%d);         /* first: then pm_display_covered watches for it */"
                 % DISPLAY_PRIORITY)
        L.append("    screen_away = 0;")
    L.append("    if (screen) {")
    L.append("        words(MODE_NAME, 0, 0);")
    L.append("        pm_show(screen, 1);")
    L.append("    }")
    if has_hud:
        L.append("    {")
        L.append("        int k;")
        L.append("        for (k = 0; k < 3; k++) {")
        L.append('            kit_copy(hud_val[k], sizeof hud_val[k], "0");')
        L.append("            kit_copy(hud_sub[k], sizeof hud_sub[k], HUD_SUB[k]);")
        L.append("        }")
        L.append("    }")
        L.append("    hud_level = 0;")
        L.append("    kit_hud_pips(&hud, HUD_GAUGE);      /* the build's count: any more are hidden */")
        L.append("    kit_hud_begin(&hud, MODE_NAME, HUD_LINE);")
    L.append('    pm_log("START (%s): player %u", why, run.player);')
    L.append("    on_mode_start();")
    if has_hud:
        L.append("    if (run.on) hud_show();            /* what the start's blocks set, on the first frame */")
    L.append("}")
    L.append("")
    L.append("static void end(const char *why)")
    L.append("{")
    L.append("    if (!run.on || ending) return;    /* an End block in When the mode ends */")
    L.append("    ending = 1;")
    L.append("    on_mode_end();")
    L.append("    ending = 0;")
    L.append("    run.on = 0;")
    L.append("    pm_lamp_release_all();")
    L.append("    if (screen) {")
    L.append('        words("TOTAL", (long long)run.total, 1);')
    L.append("        hide_ticks = %d * TICKS_PER_SECOND;" % (TOTAL_MS // 1000))
    if watch:
        L.append("        if (screen_away) pm_show(screen, 1);")
        L.append("        screen_away = 0;")
    L.append("    }")
    if has_hud:
        L.append("    {                                 /* the TOTAL, as the examples end */")
        L.append("        char n[32];")
        L.append("        int k;")
        L.append('        kit_hud_title(&hud, MODE_NAME " TOTAL", "");')
        L.append("        for (k = 0; k < 3; k++) kit_hud_counter(&hud, k, 0, 0, 0);")
        L.append("        kit_hud_timer(&hud, -1);")
        L.append("        kit_hud_gauge(&hud, -1, 0);")
        L.append('        kit_hud_award(&hud, %du, kit_num(n, sizeof n, run.total), " ");' % TOTAL_MS)
        L.append("        kit_hud_hide_in(&hud, %du);" % TOTAL_MS)
        L.append("    }")
    if watch:
        L.append("    /* the total keeps the display watched for its moment (the kit's kit_end_after) */")
        L.append("    if (!pm_end_holding(%du)) {" % TOTAL_MS)
        L.append("        pm_display_priority(0);")
        L.append("        pm_end();")
        L.append("    }")
    else:
        L.append("    pm_end();")
    L.append('    pm_log("END (%s): %u scores, total %llu", why, run.shots, (unsigned long long)run.total);')
    L.append("}")
    L.append("")
    L.append("/* ended by a drain or the game moving on: the game's own screen (the bonus, the next player) comes")
    L.append(" * at once, so the total does not stay over it (the kit's kit_end_now) */")
    L.append("static void end_now(const char *why)")
    L.append("{")
    L.append("    if (!run.on) return;")
    L.append("    end(why);")
    L.append("    hide_ticks = 0;")
    L.append("    if (screen) pm_show(screen, 0);")
    if watch:
        L.append("    pm_display_priority(0);")
    if has_hud:
        L.append("    kit_hud_drop_now();")
    L.append("}")
    L.append("")
    L.append("/* ---- the callbacks ---- */")
    L.append("static void on_init(void)")
    L.append("{")
    L.append("    int i;")
    L.append("    uint64_t mask;")
    L.append("    for (i = 0; i < %d; i++)" % len(g.shots))
    L.append("        S[i] = SHOT_NAMES[i] && SHOT_NAMES[i][0] ? pm_shot(SHOT_NAMES[i]) : 0;")
    L.append("    for (i = 0; i < %d; i++)" % len(g.events))
    L.append("        E[i] = EVENT_NAMES[i] && EVENT_NAMES[i][0] ? pm_event(EVENT_NAMES[i]) : -1;")
    L.append("    for (i = 0; pm_shot_at(i, &mask); i++)")
    L.append("        named |= mask;")
    L.append('    pm_log("ready on %%s %%s: %%d shot(s) named by the blocks", pm_game(), pm_version(), %d);'
             % len(g.shots))
    L.append("    (void)E; (void)EVENT_NAMES; (void)HIT_OF; (void)H;")
    L.append("}")
    L.append("")
    L.append("static void find_screen(void)")
    L.append("{")
    L.append("    static unsigned tries;")
    L.append("    if (screen || !pm_can(PM_CAN_SCREENS) || (tries++ % 30) != 0) return;")
    L.append('    screen = pm_node("hud", SCREEN_NODE);')
    L.append("    if (!screen) return;")
    L.append('    screen_words = pm_text("hud", SCREEN_TEXT);')
    L.append("    if (!run.on) pm_show(screen, 0);")
    L.append("}")
    L.append("")
    L.append("static void on_shot(uint64_t shot)")
    L.append("{")
    L.append("    unsigned p = pm_player();")
    L.append("    int i, was_on = run.on;           /* the mode's state before this shot */")
    L.append("    if (!pm_in_game() || p < 1 || p > 4) return;")
    L.append("    if (!(shot & named)) return;      /* a switch's 0x1 dispatch, not a shot */")
    L.append("    for (i = 0; i < %d; i++)" % len(g.hits))
    L.append("        if (S[(int)HIT_OF[i]] & shot) H[i][p]++;")
    L.append("    (void)i; (void)was_on;")
    L.extend(scripts_of("shot", "any_shot"))
    L.append("}")
    L.append("")
    L.append("static void on_event(unsigned id)")
    L.append("{")
    L.append("    int was_on = run.on;")
    L.append("    if (!pm_in_game()) return;")
    L.append("    (void)was_on; (void)id;")
    L.extend(scripts_of("event"))
    L.append("}")
    L.append("")
    L.append("static void on_tick(void)")
    L.append("{")
    L.append("    unsigned seconds = 0;")
    L.append("    int in_game = pm_in_game();")
    L.append("    find_screen();")
    if has_hud:
        L.append("    kit_hud_tick(&hud);                /* finds it, expires an award, writes what changed */")
    L.append("    if (in_game && !was_in_game) {    /* a new game: every player's \"each game\" values */")
    L.append("        unsigned p, v;")
    L.append("        for (p = 0; p < 5; p++) {")
    L.append("            for (v = 0; v < %d; v++) H[v][p] = 0;" % nhits)
    for i, (_n, reset) in enumerate(g.var_names):
        L.append("            V[%d][p] = 0;" % i)
    L.append("        }")
    L.append("    }")
    L.append("    was_in_game = in_game;")
    L.append("    if (++poll % 30 == 0) {            /* the tab's Start mode now / End mode */")
    L.append('        if (pm_trigger("%s.start")) start("trigger file");' % slug)
    L.append('        if (pm_trigger("%s.stop")) end("trigger file");' % slug)
    L.append("    }")
    L.append("    if (hide_ticks && --hide_ticks == 0 && !run.on && screen) pm_show(screen, 0);")
    L.append("    sec_changed = 0;")
    L.append("    if (!run.on) return;")
    L.append("    if (!in_game || pm_player() != run.player) {")
    L.append('        end_now("the game moved on");')
    L.append("        return;")
    L.append("    }")
    L.append("    run.elapsed++;")
    L.append("    if (RUN_SECONDS) {")
    L.append("        if (run.ticks_left) run.ticks_left--;")
    L.append("        seconds = secs_left();")
    L.append("        if (seconds != run.seconds_shown) {")
    L.append("            run.seconds_shown = seconds;")
    L.append("            sec_changed = 1;")
    L.append("        }")
    L.append("    }")
    L.append("    (void)seconds;")
    L.extend(scripts_of("every", "seconds_left"))
    L.append("    if (run.on && RUN_SECONDS && run.ticks_left == 0)")
    L.append('        end("time ran out");')
    if watch:
        L.append("    if (run.on && screen) {           /* its screen out of the way of the game's (PAD-375) */")
        L.append("        int away = pm_display_covered() || pm_aside();")
        L.append("        if (away != screen_away) {")
        L.append("            pm_show(screen, !away);")
        L.append("            screen_away = away;")
        L.append("        }")
        L.append("    }")
    if has_hud:
        L.append("    if (run.on) hud_show();")
    L.append("}")
    L.append("")
    L.append("static void on_ball_end(void)")
    L.append("{")
    L.extend(scripts_of("ball_end"))
    L.append("    if (ENDS_ON_DRAIN) end_now(\"ball ended\");")
    L.append("    {")
    L.append("        unsigned p = P(), v;")
    L.append("        for (v = 0; v < %d; v++) H[v][p] = 0;" % nhits)
    L.append('        reset_ball();')
    L.append("    }")
    L.append("}")
    L.append("")
    L.append("static const struct pm_mode %s_mode = {" % ident)
    L.append("    .name = MODE_NAME,")
    L.append("    .init = on_init,")
    L.append("    .tick = on_tick,")
    L.append("    .shot = on_shot,")
    L.append("    .ball_end = on_ball_end,")
    L.append("    .event = on_event,")
    L.append("};")
    L.append("PM_REGISTER(%s_mode);" % ident)
    return "\n".join(L) + "\n"


def _hat_words(hat):
    kind = hat.get("kind")
    when = WHEN.get(hat.get("when", "any"), "")
    if kind == "shot":
        return "when %s is made, %s" % (hat.get("shot") or "(no shot)", when)
    if kind == "any_shot":
        return "when any shot is made, %s" % when
    if kind == "every":
        return "every %s seconds while it runs" % hat.get("seconds")
    if kind == "seconds_left":
        return "when %s seconds are left" % hat.get("seconds")
    if kind == "event":
        return "when %s, %s" % (MP.EVENT_LABELS.get(hat.get("event"), hat.get("event")), when)
    return HATS.get(kind, "?").lower()
