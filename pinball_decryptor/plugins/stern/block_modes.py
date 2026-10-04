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
      "game_modes": "stack",      PAD-373: while it runs, the game's own modes may start ("stack"), may start
                                  and end it ("give_way": it also starts only while none runs), or cannot
                                  start ("block": as give_way, and the ones in block_modes are held off)
      "block_modes": [21, 23],    the title's mode ids it holds off ([] = the port's checked defaults)
      "vars": [{"name": "combo", "reset": "ball"}],   per player; reset "ball" | "mode" | "game"
      "clips": [{"name": "sever", "file": "sever.mp4"}],      PAD-374: its own clips and sounds,
      "sounds": [{"name": "roar", "file": "roar.wav", "priority": 4}],   files in its folder
      "music": "music.wav",       its own music bed while it runs ("" = the game's music)
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
the seconds left, a sum), a multiball, a line in the log, and (PAD-374) play one of the mode's
own clips (full screen, behind the HUD once, or behind the HUD over and over while it runs) or
one of its own sounds (with a callout of the game's when the card could not carry it). Values: a
number, a variable, a shot's hits this ball, how many shots the mode has scored, its points so
far, the seconds left, the balls in play, the player up, and + - x / of two values. Conditions:
compare two values, and / or / not, the mode is running, one of the game's own modes is running.

PAD-373: what it does about the game's own modes is the form's choice (PAD-363): they may start
(``stack``), it gives way (``give_way``: it starts only while none of them runs - a Start the mode
then waits, and the next one starts it - and one of them beginning ends it at once), or it holds
them off (``block``: as give_way, and while it runs the ones in ``block_modes``, or the port's
checked defaults, cannot start: ``pm_block_game_modes``), as the SDK's examples do with the kit's
kit_wait_game / kit_isolate_list / kit_game_began.

The C is the SDK's template (``sdk/template_mode.c``) in shape: static state, never blocking, a
0 from the game is carried on past, ``pm_begin`` / ``pm_end`` around a run, and the folder's own
test triggers (``/dump/<slug>.start`` / ``.stop``) so the tab's Start mode now and End mode reach
it. Its names follow ``mode_tryit.code_mode_text`` (``PadMode_<slug>_Screen``, ``<ident>_mode``)
so a rename rewrites it the way it rewrites any code mode.

ITS OWN CLIPS AND SOUNDS (PAD-374) are a code mode's: every save puts them in the mode's
``assets.json`` (``clips``, ``calls``, ``music``; :func:`_sync_assets`), so Write and Try it carry
them as they carry an example's, and the C plays them by name through ``pad_mode_assets.h``. A
clip's or sound's name is its cue there. The C starts the mode's own assets itself rather than
with ``pa_start``, so no name is special: a clip called "intro" or "loop" plays when a block
says, never on its own.
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
              "light_shot", "lights_off", "add_time", "set_time", "multiball", "log", "clip", "sound")
PATTERNS = {"solid": ("PM_LAMP_SOLID", 0), "blink": ("PM_LAMP_BLINK", 500),
            "pulse": ("PM_LAMP_PULSE", 1600), "chase": ("PM_LAMP_CHASE", 150)}
#: the game's own callouts a block can name by what they say (every port carries these roles)
CALLOUT_ROLES = {"ten_seconds": "Ten seconds left", "time_up": "Time is up"}
NUM_KINDS = ("num", "var", "hits", "scored", "total", "secs_left", "balls", "player", "op")
BOOL_KINDS = ("cmp", "and", "or", "not", "running", "stock")
OPS = {"+": "+", "-": "-", "*": "*", "/": "/"}
CMPS = {"<": "<", "<=": "<=", "=": "==", "!=": "!=", ">=": ">=", ">": ">"}
#: PAD-373: what the mode does about the game's own modes while it runs (the form's choice, PAD-363)
GAME_MODES = {"stack": "may start", "give_way": "may start, and end this one", "block": "cannot start"}
BLOCK_ID_MAX = 127
#: PAD-374: where a clip block plays the mode's own clip
CLIP_WHERE = {"full": "full screen", "behind": "behind the HUD, once",
              "loop": "behind the HUD, over and over"}
#: a clip's or sound's name: its cue in assets.json and <slug>.assets (code_modes.CUE_RE)
MEDIA_RE = re.compile(r"^[a-z][a-z0-9_]{0,14}$")
MAX_CLIPS = 12                   # pad_mode_assets.h PA_CLIPS_MAX
MAX_SOUNDS = 16                  # pad_mode_assets.h PA_CALLS_MAX
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm")
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
    if out.get("game_modes") not in GAME_MODES:          # PAD-373
        out["game_modes"] = "stack"
    ids = out.get("block_modes") if isinstance(out.get("block_modes"), list) else []
    out["block_modes"] = sorted({i for i in ids if isinstance(i, int) and not isinstance(i, bool)
                                 and 0 <= i <= BLOCK_ID_MAX})
    out["vars"] = [v for v in (out.get("vars") or []) if isinstance(v, dict)]
    out["clips"] = [c for c in (out.get("clips") or []) if isinstance(c, dict)]
    out["sounds"] = [c for c in (out.get("sounds") or []) if isinstance(c, dict)]
    out["music"] = str(out.get("music") or "")
    out["scripts"] = [s for s in (out.get("scripts") or []) if isinstance(s, dict)]
    for s in out["scripts"]:
        for b in _walk(s.get("do")):
            # PAD-372: Add seconds takes a value; one saved before held a plain number
            secs = b.get("seconds")
            if b.get("op") == "add_time" and isinstance(secs, (int, float)) and not isinstance(secs, bool):
                b["seconds"] = {"k": "num", "v": b["seconds"]}
    return out


def save(project, slug, program):
    """Write the program and the C it makes, the C first so a mode is never left with blocks
    that disagree with its C. Returns the C file's path."""
    program = normalize(program)
    folder = MP.mode_folder(project, slug)
    os.makedirs(folder, exist_ok=True)
    src = os.path.join(folder, slug + ".c")
    _write(src, to_c(program, slug))
    text = json.dumps(program, indent=2) + "\n"
    _write(blocks_path(project, slug), text)
    _sync_assets(project, slug, program)
    return src


def _write(path, text):
    with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def _sync_assets(project, slug, program):
    """The mode's assets.json says its name, its clock and whether it has a screen of its own
    (the build makes the screen: a panel with its name, and a line of words the blocks write),
    and (PAD-374) its own clips, sounds and music, so Write carries them as a code mode's."""
    from . import code_modes as CM
    try:
        spec = CM.load(project, slug)
    except (OSError, ValueError):
        spec = CM.CodeAssets(screen=False)
    clips, calls = media_assets(program)
    changed = (spec.name != (program["name"] or slug.upper()) or bool(spec.screen) != program["screen"]
               or spec.seconds != max(1, program["seconds"] or 60)
               or (spec.clips or {}) != clips or (spec.calls or {}) != calls
               or (spec.music or "") != program["music"])
    if changed or not os.path.isfile(os.path.join(MP.mode_folder(project, slug), CM.ASSETS_FILE)):
        spec.name = program["name"] or slug.upper()
        spec.screen = program["screen"]
        spec.seconds = max(1, program["seconds"] or 60)
        spec.clips = clips
        spec.calls = calls
        spec.music = program["music"]
        CM.save(project, slug, spec)


def media_assets(program):
    """``(clips, calls)`` as assets.json holds them: ``{name: file}`` and ``{name: {"wav",
    "priority"}}``, every well-named entry with a file (the first of a name wins)."""
    clips, calls = {}, {}
    for c in program.get("clips") or []:
        name, f = str(c.get("name") or ""), str(c.get("file") or "")
        if MEDIA_RE.match(name) and f and name not in clips and len(clips) < MAX_CLIPS:
            clips[name] = f
    for c in program.get("sounds") or []:
        name, f = str(c.get("name") or ""), str(c.get("file") or "")
        if MEDIA_RE.match(name) and f and name not in calls and len(calls) < MAX_SOUNDS:
            calls[name] = {"wav": f, "priority": _priority(c.get("priority"))}
    return clips, calls


def _priority(v):
    try:
        p = int(v)
    except (TypeError, ValueError):
        return 4
    return p if 1 <= p <= 7 else 4


def media_name(stem, taken=()):
    """A clip's or sound's name from its file's name: lower-case letters, digits and _, starting
    with a letter, 15 at most, and not one of ``taken``."""
    base = re.sub(r"[^a-z0-9_]+", "_", str(stem or "").lower()).strip("_")
    if not base or not base[0].isalpha():
        base = "s_" + base if base else "sound"
    base = base[:15].rstrip("_") or "sound"
    taken = {str(t).lower() for t in taken or ()}
    name, n = base, 2
    while name in taken:
        tail = "_%d" % n
        name = base[:15 - len(tail)] + tail
        n += 1
    return name


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
def problems(program, shots=None, events=None, folder=None):
    """Every reason the program cannot be built, as sentences (empty = it can). ``shots`` and
    ``events``, when given, are the card's: a block naming a shot or event the card does not
    have is named here; ``folder``, when given, is the mode's, where its own clips and sounds
    must be. The C is written anyway (a missing shot is 0 to the game, which never matches),
    so a half-made program always saves."""
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
    clips = _check_media(program["clips"], "clip", MAX_CLIPS, folder, out)
    sounds = _check_media(program["sounds"], "sound", MAX_SOUNDS, folder, out)
    if program["music"] and folder is not None and not os.path.isfile(os.path.join(folder, program["music"])):
        out.append("Its music %s is not in the mode's folder: pick it again." % program["music"])
    ctx = {"vars": set(n.lower() for n in names), "shots": set(shots) if shots is not None else None,
           "events": set(events) if events is not None else None, "count": 0, "out": out,
           "seconds": program["seconds"], "clips": clips, "sounds": sounds}
    for i, s in enumerate(program["scripts"]):
        _check_hat(s.get("hat") or {}, i + 1, ctx)
        _check_stack(s.get("do") or [], 1, "Script %d" % (i + 1), ctx)
    if ctx["count"] > MAX_BLOCKS:
        out.append("%d blocks: %d at most." % (ctx["count"], MAX_BLOCKS))
    return _unique(out)


def _check_media(items, what, most, folder, out):
    """The names of the mode's own clips (or sounds), saying what is wrong with the list."""
    names = set()
    if len(items) > most:
        out.append("%d %ss of its own: %d at most." % (len(items), what, most))
    for c in items:
        name, f = str(c.get("name") or ""), str(c.get("file") or "")
        if not MEDIA_RE.match(name):
            out.append("A %s's name %r is not one: start with a lower-case letter, then lower-case "
                       "letters, digits or _ (15 at most)." % (what, name))
        elif name in names:
            out.append("Two %ss are called %s." % (what, name))
        names.add(name)
        if not f:
            out.append("The %s %s has no file: pick one." % (what, name))
        elif folder is not None and not os.path.isfile(os.path.join(folder, f)):
            out.append("The %s %s's file %s is not in the mode's folder: pick it again." % (what, name, f))
        if what == "sound" and not _int_ok(c.get("priority", 4), 1, 7):
            out.append("The sound %s's priority is 1 to 7." % name)
    return names


def notes(program):
    """What is worth knowing but does not stop a build: nothing starts the mode, a timer block
    with no clock, words with no screen, a clip behind the HUD with no loop to play it in."""
    program = normalize(program)
    ops = set()
    kinds = set()
    wheres = set()
    for s in program["scripts"]:
        kinds.add((s.get("hat") or {}).get("kind"))
        for b in _walk(s.get("do") or []):
            ops.add(b.get("op"))
            if b.get("op") == "clip":
                wheres.add(b.get("where"))
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
    if "behind" in wheres and "loop" not in wheres:
        out.append("A clip behind the HUD, once, plays in the place of the mode's loop: start a "
                   "clip over and over behind the HUD first (When the mode starts is the place).")
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
        elif op == "clip":
            if not b.get("clip"):
                ctx["out"].append("%s plays a clip with none chosen." % where)
            elif b.get("clip") not in ctx["clips"]:
                ctx["out"].append("%s plays the clip %s, which the mode does not have: add it under "
                                  "Its own clips and sounds." % (where, b.get("clip")))
            if b.get("where") not in CLIP_WHERE:
                ctx["out"].append("%s plays a clip with no where." % where)
        elif op == "sound":
            if not b.get("sound"):
                ctx["out"].append("%s plays a sound with none chosen." % where)
            elif b.get("sound") not in ctx["sounds"]:
                ctx["out"].append("%s plays the sound %s, which the mode does not have: add it under "
                                  "Its own clips and sounds." % (where, b.get("sound")))
            fb = b.get("fallback")
            if fb not in (None, "") and fb not in CALLOUT_ROLES and not _int_ok(fb, 1, 65535):
                ctx["out"].append("%s falls back on a callout that is not one." % where)


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
                out.append(pad + 'start("a block", 1);')
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
                said = self.callout(b.get("role") if b.get("role") in CALLOUT_ROLES else b.get("id"))
                if said:
                    out.append(pad + said + ";")
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
                # PAD-373: its own multiball is not one of the game's modes beginning
                out.append(pad + "if (run.on && pm_multiball_start(%du, %du)) run.own_mball = 1;" % (balls, save))
            elif op == "log":
                out.append(pad + 'pm_log("%%s", %s);' % _c_str(str(b.get("text") or "")[:TEXT_MAX]))
            elif op == "clip":
                name = str(b.get("clip") or "")
                if MEDIA_RE.match(name):
                    fn = {"full": "clip_full", "behind": "clip_behind", "loop": "clip_loop"}.get(
                        b.get("where"), "clip_full")
                    out.append(pad + "%s(%s);" % (fn, _c_str(name)))
            elif op == "sound":
                name = str(b.get("sound") or "")
                if MEDIA_RE.match(name):
                    fb = self.callout(b.get("fallback"))
                    if fb:
                        out.append(pad + "if (!sound(%s)) %s;" % (_c_str(name), fb))
                    else:
                        out.append(pad + "sound(%s);" % _c_str(name))
        return out

    @staticmethod
    def callout(v):
        """The C that says a game's callout (a role's name or a number), or "" for none."""
        if v in CALLOUT_ROLES:
            return "pm_callout(pm_callout_id(%s))" % _c_str(v)
        if v in (None, ""):
            return ""
        try:
            return "pm_callout(%du)" % max(1, min(65535, int(v)))
        except (TypeError, ValueError):
            return ""


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
    media = uses_media(program)

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
    if media:
        L.append('#include "pad_mode_assets.h"     /* its own clips and sounds, as Write carried them */')
    L.append("")
    L.append('#define MODE_NAME        %s' % _c_str(title))
    L.append("#define RUN_SECONDS      %d          /* 0 = no clock */" % program["seconds"])
    L.append("#define ENDS_ON_DRAIN    %d" % (1 if program["ends_on_drain"] else 0))
    L.append("#define TICKS_PER_SECOND 60")
    L.append("#define CLOCK_MAX        %d         /* the most seconds the clock holds */" % SECONDS_MAX)
    L.append("#define UNUSED __attribute__((unused))   /* a helper the blocks may not call */")
    L.append("")
    gm = program["game_modes"]                           # PAD-373: as a form mode's (PAD-363)
    ids = program["block_modes"]
    L.append("/* While it runs, the game's own modes %s. */" % GAME_MODES[gm])
    L.append("#define GAME_MODES       %d          /* 0 = they may start, 1 = it starts only while none runs and one"
             % {"stack": 0, "give_way": 1, "block": 2}[gm])
    L.append("                                   * starting ends it, 2 = as 1, and the ones in BLOCK_IDS cannot start */")
    L.append("UNUSED static const unsigned char BLOCK_IDS[%d] = {%s};   /* the game's mode ids; none = the port's defaults */"
             % (max(1, len(ids)), ", ".join(str(i) for i in ids) or "0"))
    L.append("#define BLOCK_N          %d" % len(ids))
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
    L.append("    int own_mball;                    /* a Multiball block served balls: not the game's multiball */")
    L.append("    unsigned player, ticks_left, seconds_shown, elapsed, shots;")
    L.append("    uint64_t total;")
    L.append("} run;")
    L.append("static int sec_changed, was_in_game, ending;")
    L.append("static void *screen, *screen_words;")
    L.append("static unsigned hide_ticks, poll;")
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
    if media:
        L.extend((_MEDIA_C % {"slug": slug}).split("\n"))
    L.append("/* What of the game's own is running (a battle, a multiball, one of its timed modes), or 0. A port that")
    L.append(" * cannot tell answers none. */")
    L.append("UNUSED static const char *game_busy(void)")
    L.append("{")
    L.append("    int k = pm_stock_mode_running(PM_STOCK_BATTLE | PM_STOCK_MULTIBALL | PM_STOCK_ANY);")
    L.append("    if (k > 0) return pm_stock_mode_what((unsigned)k);")
    L.append("    if (pm_can(PM_CAN_MULTIBALL) && pm_balls_in_play() >= 2) return \"a multiball\";")
    L.append("    return 0;")
    L.append("}")
    L.append("")
    L.append("static void start(const char *why, int counted);")
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
    L.append("/* counted: a block asked (the tab's Start mode now does not wait for the game's modes) */")
    L.append("static void start(const char *why, int counted)")
    L.append("{")
    L.append("    if (run.on || !pm_in_game()) return;")
    L.append("    if (GAME_MODES && counted) {      /* it waits: the next Start the mode starts it */")
    L.append("        static unsigned long said_at;")
    L.append("        const char *what = game_busy();")
    L.append("        if (what) {")
    L.append("            if (!said_at || pm_ms() - said_at >= 10000)")
    L.append('                pm_log("not started (%s): %s is running - still ready: the next Start the mode starts it", why, what);')
    L.append("            said_at = pm_ms() ? pm_ms() : 1;")
    L.append("            return;")
    L.append("        }")
    L.append("    }")
    L.append("    if (!pm_begin()) return;          /* another of our modes is running */")
    L.append("    pm_running_name(MODE_NAME);")
    L.append("    if (GAME_MODES == 2) {            /* the game's modes it holds off cannot start while it runs */")
    L.append("        pm_block_list(BLOCK_IDS, BLOCK_N);")
    L.append("        if (pm_block_game_modes(1))")
    L.append("            pm_log(\"isolated: the game's modes it holds off cannot start while it runs (any other "
             "starting ends it)\");")
    L.append("        else")
    L.append("            pm_log(\"isolated: this port cannot hold the game's modes off - it gives way to them\");")
    L.append("    } else if (GAME_MODES == 1) {")
    L.append("        pm_log(\"isolated: gives way - one of the game's modes starting ends it\");")
    L.append("    }")
    L.append("    run.own_mball = 0;")
    L.append("    run.on = 1;")
    L.append("    run.player = pm_player();")
    L.append("    run.ticks_left = RUN_SECONDS * TICKS_PER_SECOND;")
    L.append("    run.seconds_shown = RUN_SECONDS;")
    L.append("    run.elapsed = 0;")
    L.append("    run.shots = 0;")
    L.append("    run.total = 0;")
    L.append("    hide_ticks = 0;")
    L.append('    reset_mode();')
    L.append("    if (screen) {")
    L.append("        words(MODE_NAME, 0, 0);")
    L.append("        pm_show(screen, 1);")
    L.append("    }")
    if media:
        L.append("    pa_load(&own);                    /* its own sounds' priorities, and its music */")
        L.append("    own.running = 1;")
        L.append("    if (own.loaded) {")
        L.append("        pa_priorities(&own);")
        L.append("        pa_music_begin(&own);")
        L.append("    }")
    L.append('    pm_log("START (%s): player %u", why, run.player);')
    L.append("    on_mode_start();")
    L.append("}")
    L.append("")
    L.append("static void end(const char *why)")
    L.append("{")
    L.append("    if (!run.on || ending) return;    /* an End block in When the mode ends */")
    L.append("    ending = 1;")
    L.append("    on_mode_end();")
    L.append("    ending = 0;")
    L.append("    run.on = 0;")
    if media:
        L.append("    loop_waiting = 0;")
        L.append("    if (looping) {                    /* the city behind the HUD again */")
        L.append("        pm_backdrop(0);")
        L.append("        looping = 0;")
        L.append("    }")
        L.append("    pa_end(&own);                     /* its music fades, the game's comes back */")
    L.append("    pm_lamp_release_all();")
    L.append("    if (screen) {")
    L.append('        words("TOTAL", (long long)run.total, 1);')
    L.append("        hide_ticks = 3 * TICKS_PER_SECOND;")
    L.append("    }")
    L.append("    if (GAME_MODES == 2) pm_block_game_modes(0);   /* the game's modes may start again */")
    L.append("    pm_end();")
    L.append('    pm_log("END (%s): %u scores, total %llu", why, run.shots, (unsigned long long)run.total);')
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
    if media:
        L.append("    pa_load(&own);")
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
    if media:
        L.append("    own_tick();                       /* every tick: an end call outlives the mode */")
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
    L.append('        if (pm_trigger("%s.start")) start("trigger file", 0);' % slug)
    L.append('        if (pm_trigger("%s.stop")) end("trigger file");' % slug)
    L.append("    }")
    L.append("    if (hide_ticks && --hide_ticks == 0 && !run.on && screen) pm_show(screen, 0);")
    L.append("    sec_changed = 0;")
    L.append("    if (!run.on) return;")
    L.append("    if (!in_game || pm_player() != run.player) {")
    L.append('        end("the game moved on");')
    L.append("        return;")
    L.append("    }")
    L.append("    if (run.own_mball && pm_balls_in_play() < 2) run.own_mball = 0;   /* its multiball is over */")
    L.append("    if (GAME_MODES && pm_aside() && !(run.own_mball && pm_aside() == (int)PM_STOCK_MULTIBALL)) {")
    L.append("        end(\"the game's own mode began\");   /* its screen goes at once, as a tilt's */")
    L.append("        hide_ticks = 0;")
    L.append("        if (screen) pm_show(screen, 0);")
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
    L.append("}")
    L.append("")
    L.append("static void on_ball_end(void)")
    L.append("{")
    L.extend(scripts_of("ball_end"))
    L.append("    if (ENDS_ON_DRAIN) end(\"ball ended\");")
    if media:
        L.append("    looping = 0;                      /* no backdrop outlives the ball */")
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


def uses_media(program):
    """1 when the mode has clips, sounds or music of its own, or a block that plays one."""
    if program.get("clips") or program.get("sounds") or program.get("music"):
        return True
    return any(b.get("op") in ("clip", "sound") for s in program.get("scripts") or []
               for b in _walk(s.get("do") or []))


#: the C of a mode with its own clips and sounds (pad_mode_assets.h); %(slug)s is its folder
_MEDIA_C = """/* ---- its own clips and sounds (PAD-374): what Write carried, named in %(slug)s.assets ---- */
static struct pa_assets own = { .folder = "%(slug)s" };
static const char *clip_waiting, *loop_waiting;   /* MODE_SDK.md "Clips race the game's own" */
static unsigned long clip_due;
static int looping;                     /* a clip of its own loops behind the HUD */

static int own_clip(const char *cue)
{
    pa_load(&own);
    if (pa_clip_name(&own, cue)) return 1;
    pm_log("own clip %%s: the build carried none", cue);
    return 0;
}

/* full screen, over everything: half a second from now, so the game's own clip for the shot
 * that asked does not take the one video surface; the newest asked for wins */
UNUSED static void clip_full(const char *cue)
{
    if (!own_clip(cue)) return;
    if (clip_waiting && clip_waiting != cue)
        pm_log("own clip %%s dropped before it played: %%s was asked for after it", clip_waiting, cue);
    clip_waiting = cue;
    clip_due = pm_ms() + PA_CLIP_AFTER_MS;
}

/* behind the HUD over and over while the mode runs (after a full-screen clip still waiting) */
UNUSED static void clip_loop(const char *cue)
{
    const char *n;
    if (!own_clip(cue)) return;
    if (!run.on) {
        pm_log("own clip %%s: not looped behind the HUD - the mode is not running", cue);
        return;
    }
    if (clip_waiting) {
        loop_waiting = cue;
        return;
    }
    n = pa_clip_name(&own, cue);
    looping = pm_backdrop(n);
    pm_log("own clip %%s (%%s) behind the HUD, over and over: %%s", cue, n,
           looping ? "asked" : "this port has no backdrop");
}

/* behind the HUD once, in the loop's place, then the loop again */
UNUSED static void clip_behind(const char *cue)
{
    if (!own_clip(cue)) return;
    if (!run.on || !looping || !pa_clip_event(&own, cue))
        pm_log("own clip %%s: not played behind the HUD - %%s", cue,
               !run.on ? "the mode is not running" : "no clip of its own loops there");
}

/* 1 = the build carried it (played now, or waiting for the voice bus); 0 = it did not */
UNUSED static int sound(const char *cue)
{
    if (pa_call(&own, cue)) return 1;
    pm_log("own sound %%s: the build carried none", cue);
    return 0;
}

static void own_tick(void)
{
    pa_tick(&own);
    if (!clip_waiting || pm_ms() < clip_due) return;
    pa_clip_full(&own, clip_waiting);
    clip_waiting = 0;
    if (loop_waiting && run.on) {
        const char *cue = loop_waiting;
        loop_waiting = 0;
        clip_loop(cue);
    }
}

"""


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
