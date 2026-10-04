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
                                  ("shared": true = the same value in every mode that names it)
      "timers": [{"name": "window"}],  counts down in milliseconds (PAD-377)
      "wait_multiball": true,     a Start the mode while a multiball runs waits for the next one
      "priority": 180,            its display priority while it runs (0 = none)
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
one of its own sounds (with a callout of the game's when the card could not carry it), and
(PAD-376) run a light show (a ready-made one, or its own steps: the examples' kit_show) and light
a shot at a pace of its own (any value, in ms) or blinking faster as the clock runs down. Values: a
number, a variable, a shot's hits this ball, how many shots the mode has scored, its points so
far, the seconds left, the balls in play, the player up, and + - x / of two values. Conditions:
compare two values, and / or / not, the mode is running, one of the game's own modes is running,
the mode could start now.

What a mode in C does with the kit (``sdk/examples/intricate_kit.h``), PAD-377 gives the blocks:

- A SHARED variable is one value per player that every mode naming it reads and writes - the
  kit's ledger, with which FINAL WARS is lit by what the other modes did. It is a weak C global
  (``pad_shared_<name>``), so the linker keeps one for all the modes built into the card; a mode
  written in C shares it by declaring the same line. It resets each ball or each game.
- A TIMER counts down in milliseconds, not whole seconds: Start timer (any value, so a window can
  shrink), Stop timer, the milliseconds a timer has left, and a When a timer runs out hat. Timers
  run whether the mode does or not; a ball ending stops them.
- WAITS OUT A MULTIBALL (``wait_multiball``): Start the mode does nothing while a multiball or
  one of the game's own modes runs (the kit's ``kit_wait_game``); the mode stays ready, so the
  next block that starts it afterwards does. "the mode could start now" asks the same.
- A DISPLAY PRIORITY (``priority``): held while the mode runs (``kit_display``), kept for the
  total its own screen shows at the end, given back at once at a drain.

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

LIGHTS (PAD-376). The shots the blocks light are kept in a table (``LIT``), not only sent: a light
show (the kit's ``kit_show``, its engine written into the C only when a Light show block is there)
paints every placed insert while it runs, and at its end hands them back and sends the table
again; a blink that hurries is sent again each time the clock moves it to a faster pace; and the
same light lit again is not sent again, so a blink keeps its beat. A show started in When the
mode ends runs on after the mode, as the examples' end shows do.
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
MAX_TIMERS = 8
TIMER_MAX_MS = SECONDS_MAX * 1000
PRIORITY_MAX = 255
#: the display priorities the page offers (any 0..255 loads): MODE_SDK.md "Display priority"
PRIORITIES = {0: "none", 180: "a mode's (180)", 190: "a wizard mode's (190)"}
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
    "timer_done": "When a timer runs out",
}
#: a shot / event hat's "when": the mode's state it runs in
WHEN = {"any": "any time", "idle": "while the mode is not running", "running": "while the mode runs"}
RESETS = {"ball": "each ball", "mode": "each time the mode starts", "game": "each game"}
SHARED_RESETS = ("ball", "game")
STATEMENTS = ("start_mode", "end_mode", "score", "set", "change", "if", "callout", "words",
              "light_shot", "lights_off", "add_time", "set_time", "multiball", "log", "clip", "sound",
              "show", "timer_start", "timer_stop")
#: a lit shot's pattern: the SDK's, and its pace (ms) when the block gives none. "hurry" is a
#: blink that quickens as the clock runs down (PAD-376, the kit's kit_hurry_ms)
PATTERNS = {"solid": ("PM_LAMP_SOLID", 0), "blink": ("PM_LAMP_BLINK", 500),
            "pulse": ("PM_LAMP_PULSE", 1600), "chase": ("PM_LAMP_CHASE", 150),
            "hurry": ("PM_LAMP_BLINK", 0)}
RATE_MIN, RATE_MAX = 20, 5000    # a blink's, pulse's or chase's pace, ms
# ---- light shows (PAD-376): the kit's kit_show, steps of a pattern over the placed inserts ----
#: a step's pattern: its C name, and the words the page shows
FX = {"burst": ("FX_BURST", "a ring bursting out"), "implode": ("FX_IMPLODE", "a ring closing in"),
      "sweep_up": ("FX_SWEEP_UP", "a sweep up"), "sweep_down": ("FX_SWEEP_DOWN", "a sweep down"),
      "sweep_lr": ("FX_SWEEP_LR", "a sweep left to right"), "sweep_rl": ("FX_SWEEP_RL", "a sweep right to left"),
      "spin": ("FX_SPIN", "a turning beam"), "rainbow": ("FX_RAINBOW", "a turning rainbow"),
      "strobe": ("FX_STROBE", "a strobe"), "sparkle": ("FX_SPARKLE", "sparkles"),
      "fire": ("FX_FIRE", "fire"), "pulse": ("FX_PULSE", "breathing"),
      "chase": ("FX_CHASE_RING", "a chase round"), "fade": ("FX_FADE_OUT", "a fade to dark"),
      "bolts": ("FX_BOLTS", "lightning")}
#: where a step centres: a place on the playfield picture (x 0-300 across, y 0-600 down)
PLACES = {"center": ("the middle", 150, 330), "top": ("the top", 150, 120),
          "flippers": ("the flippers", 150, 560), "left": ("the left", 60, 330),
          "right": ("the right", 240, 330)}
#: what the general illumination does during a step (the kit's KIT_GI_*)
GI = {"keep": "GI: the game's", "dark": "GI: dark", "flash": "GI: flashing"}
SHOW_STEPS = 10                  # the kit's KIT_SHOW_STEPS
STEP_MS_MIN, STEP_MS_MAX = 50, 10000
FX_RATE_MAX = 2000


def _step(fx, ms, a, b, at, rate=0, gi="keep"):
    return {"fx": fx, "ms": ms, "a": a, "b": b, "at": at, "rate": rate, "gi": gi}


#: the ready-made shows a Light show block picks from (made after the examples' own)
SHOWS = {
    "burst": ("A burst of gold", [
        _step("strobe", 450, "#ffffff", "#ffb000", "center", 55, "flash"),
        _step("burst", 700, "#ffffff", "#ffb000", "center", 0, "dark"),
        _step("fade", 400, "#ffb000", "#000000", "center")]),
    "beams": ("Blue beams", [
        _step("strobe", 450, "#ffffff", "#0050ff", "center", 55, "flash"),
        _step("spin", 1600, "#a0e0ff", "#000000", "center", 110, "dark"),
        _step("sweep_lr", 500, "#ffffff", "#0050ff", "center", 0, "dark"),
        _step("sweep_rl", 500, "#ffffff", "#0050ff", "center", 0, "dark"),
        _step("fade", 400, "#0050ff", "#000000", "center")]),
    "lightning": ("Lightning", [
        _step("bolts", 1500, "#ffb000", "#000000", "center", 190, "dark"),
        _step("strobe", 500, "#ffffff", "#ffb000", "center", 60, "flash"),
        _step("burst", 800, "#ffb000", "#ff4000", "top", 0, "dark"),
        _step("fade", 400, "#ff4000", "#000000", "center")]),
    "fire": ("Fire", [
        _step("strobe", 500, "#ffffff", "#ff3000", "center", 60, "flash"),
        _step("fire", 1200, "#ffc000", "#ff3000", "center", 0, "dark"),
        _step("fade", 400, "#ff3000", "#000000", "center")]),
    "rainbow": ("A rainbow (a win)", [
        _step("burst", 800, "#ffffff", "#ffb000", "center", 0, "flash"),
        _step("rainbow", 1800, "#000000", "#000000", "center", 60),
        _step("fade", 500, "#ffb000", "#000000", "center")]),
    "sweep": ("Sweeps up and down", [
        _step("sweep_up", 600, "#ffffff", "#00c040", "center", 0, "dark"),
        _step("sweep_down", 600, "#ffffff", "#00c040", "center", 0, "dark"),
        _step("chase", 900, "#00ff60", "#000000", "center", 40),
        _step("fade", 400, "#00c040", "#000000", "center")]),
    "sparkle": ("Sparkles", [
        _step("sparkle", 1200, "#ffffff", "#4000a0", "center", 0, "dark"),
        _step("pulse", 1200, "#a040ff", "#200040", "center", 300),
        _step("fade", 500, "#a040ff", "#000000", "center")]),
    "fizzle": ("A fizzle (a loss)", [
        _step("spin", 1200, "#a000ff", "#000000", "center", 90, "dark"),
        _step("implode", 900, "#ffb000", "#a000ff", "center", 0, "dark"),
        _step("fade", 700, "#a000ff", "#000000", "center")]),
}
#: the game's own callouts a block can name by what they say (every port carries these roles)
CALLOUT_ROLES = {"ten_seconds": "Ten seconds left", "time_up": "Time is up"}
NUM_KINDS = ("num", "var", "hits", "scored", "total", "secs_left", "balls", "player", "op",
             "timer_left")
BOOL_KINDS = ("cmp", "and", "or", "not", "running", "stock", "can_start")
OPS = {"+": "+", "-": "-", "*": "*", "/": "/"}
CMPS = {"<": "<", "<=": "<=", "=": "==", "!=": "!=", ">=": ">=", ">": ">"}
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
    out["vars"] = [v for v in (out.get("vars") or []) if isinstance(v, dict)]
    out["timers"] = [t for t in (out.get("timers") or []) if isinstance(t, dict)]
    out["wait_multiball"] = bool(out.get("wait_multiball", False))
    try:
        out["priority"] = max(0, min(PRIORITY_MAX, int(out.get("priority", 0) or 0)))
    except (TypeError, ValueError):
        out["priority"] = 0
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
        "wait_multiball": True,         # as the examples: a multiball running, the next shot starts it
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
    for v, n in zip(program["vars"], names):
        if not VAR_RE.match(n):
            out.append("A variable's name %r is not one: start with a letter, then letters, "
                       "digits, spaces or _ (24 at most)." % n)
        elif n.lower() in seen or (v.get("shared") and shared_ident(n) in seen):
            out.append("Two variables are called %s." % n)
        seen.add(n.lower())
        if v.get("shared"):
            seen.add(shared_ident(n))       # "maser won" and "maser_won" are one shared value
            if v.get("reset", "ball") not in SHARED_RESETS:
                out.append("%s is shared with the other modes, so it resets each ball or each game, "
                           "not each time this mode starts." % n)
    if len(names) > MAX_VARS:
        out.append("%d variables: %d at most." % (len(names), MAX_VARS))
    timers = [str(t.get("name") or "") for t in program["timers"]]
    tseen = set()
    for n in timers:
        if not VAR_RE.match(n):
            out.append("A timer's name %r is not one: start with a letter, then letters, "
                       "digits, spaces or _ (24 at most)." % n)
        elif n.lower() in tseen:
            out.append("Two timers are called %s." % n)
        tseen.add(n.lower())
    if len(timers) > MAX_TIMERS:
        out.append("%d timers: %d at most." % (len(timers), MAX_TIMERS))
    if len(program["scripts"]) > MAX_SCRIPTS:
        out.append("%d scripts: %d at most." % (len(program["scripts"]), MAX_SCRIPTS))
    clips = _check_media(program["clips"], "clip", MAX_CLIPS, folder, out)
    sounds = _check_media(program["sounds"], "sound", MAX_SOUNDS, folder, out)
    if program["music"] and folder is not None and not os.path.isfile(os.path.join(folder, program["music"])):
        out.append("Its music %s is not in the mode's folder: pick it again." % program["music"])
    ctx = {"vars": set(n.lower() for n in names), "timers": tseen,
           "shots": set(shots) if shots is not None else None,
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
            if b.get("op") == "light_shot" and b.get("pattern") == "hurry":
                ops.add("hurry")
    out = []
    if "start_mode" not in ops:
        out.append("No block starts the mode yet: put Start the mode in a script (Start mode now "
                   "starts it for a test either way).")
    if not program["seconds"] and "end_mode" not in ops and not program["ends_on_drain"]:
        out.append("Nothing ends this mode: it has no clock, the ball draining does not end it, "
                   "and no End the mode block.")
    if not program["seconds"] and ({"seconds_left"} & kinds or {"add_time", "set_time"} & ops):
        out.append("The mode has no clock, so seconds-left, add-time and set-the-clock blocks do nothing.")
    if not program["seconds"] and "hurry" in ops:
        out.append("The mode has no clock, so a shot blinking faster as time runs out blinks at "
                   "an even pace.")
    if "words" in ops and not program["screen"]:
        out.append("Show words needs the mode's own screen: tick Its own screen.")
    if "timer_done" in kinds and "timer_start" not in ops:
        out.append("No block starts a timer, so When a timer runs out never runs.")
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
    if kind == "timer_done":
        _check_timer(hat.get("timer"), where + "'s When", ctx)


def _check_timer(name, where, ctx):
    if not name:
        ctx["out"].append("%s has no timer chosen." % where)
    elif str(name).lower() not in ctx["timers"]:
        ctx["out"].append("%s names a timer that is not there: make it under Timers." % where)


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
                rate = b.get("rate")
                if rate is not None and b.get("pattern") not in ("solid", "hurry"):
                    _check_num(rate, where, ctx)
                    if (isinstance(rate, dict) and rate.get("k") == "num"
                            and _int_ok(rate.get("v"), -NUMBER_MAX, NUMBER_MAX)
                            and not _int_ok(rate.get("v"), RATE_MIN, RATE_MAX)):
                        ctx["out"].append("%s lights a shot at a pace of %d to %d ms." % (where, RATE_MIN, RATE_MAX))
        elif op == "show":
            _check_show(b, where, ctx)
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
        elif op in ("timer_start", "timer_stop"):
            _check_timer(b.get("timer"), where + "'s timer", ctx)
            if op == "timer_start":
                ms = b.get("ms")
                _check_num(ms, where, ctx)
                if (isinstance(ms, dict) and ms.get("k") == "num"
                        and _int_ok(ms.get("v"), -NUMBER_MAX, NUMBER_MAX)
                        and not _int_ok(ms.get("v"), 1, TIMER_MAX_MS)):
                    ctx["out"].append("%s starts a timer: 1 to %d milliseconds." % (where, TIMER_MAX_MS))
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


def _check_show(b, where, ctx):
    show = b.get("show")
    if show in SHOWS:
        return
    if show != "own":
        ctx["out"].append("%s runs a light show with none chosen." % where)
        return
    steps = b.get("steps")
    if not isinstance(steps, list) or not steps:
        ctx["out"].append("%s runs a light show of its own with no steps." % where)
        return
    if len(steps) > SHOW_STEPS:
        ctx["out"].append("%s's light show has %d steps: %d at most." % (where, len(steps), SHOW_STEPS))
    for n, st in enumerate(steps, 1):
        here = "%s's light show, step %d," % (where, n)
        if not isinstance(st, dict) or st.get("fx") not in FX:
            ctx["out"].append("%s has no pattern." % here)
            continue
        if not _int_ok(st.get("ms"), STEP_MS_MIN, STEP_MS_MAX):
            ctx["out"].append("%s lasts %d to %d ms." % (here, STEP_MS_MIN, STEP_MS_MAX))
        if not (COLOR_RE.match(str(st.get("a") or "")) and COLOR_RE.match(str(st.get("b") or ""))):
            ctx["out"].append("%s has a colour missing." % here)
        if st.get("at", "center") not in PLACES:
            ctx["out"].append("%s has no place." % here)
        if not _int_ok(st.get("rate", 0), 0, FX_RATE_MAX):
            ctx["out"].append("%s has a pace of 0 to %d ms." % (here, FX_RATE_MAX))
        if st.get("gi", "keep") not in GI:
            ctx["out"].append("%s says nothing of the lights between the inserts." % here)


def show_steps(b):
    """The steps a Light show block runs: its ready-made show's, or its own."""
    if b.get("show") in SHOWS:
        return SHOWS[b["show"]][1]
    steps = b.get("steps") if b.get("show") == "own" else None
    return [st for st in (steps or []) if isinstance(st, dict) and st.get("fx") in FX][:SHOW_STEPS]


def show_choices():
    """What the Light show block's boxes offer: the ready-made shows (with their steps, so "its
    own steps" can start from one), the patterns, the places and the GI's settings."""
    return {"shows": [{"key": k, "label": label, "steps": copy.deepcopy(steps)}
                      for k, (label, steps) in SHOWS.items()],
            "fx": [[k, words] for k, (_c, words) in FX.items()],
            "places": [[k, p[0]] for k, p in PLACES.items()],
            "gi": [[k, words] for k, words in GI.items()]}


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
    elif k == "timer_left":
        _check_timer(e.get("timer"), where + "'s time left", ctx)
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
        self.shared = set()             # indices of the shared variables
        for v in program["vars"]:
            n = str(v.get("name") or "")
            if VAR_RE.match(n) and n.lower() not in self.vars:
                reset = v.get("reset") if v.get("reset") in RESETS else "ball"
                if v.get("shared"):
                    if reset not in SHARED_RESETS:
                        reset = "game"
                    self.shared.add(len(self.var_names))
                self.vars[n.lower()] = len(self.var_names)
                self.var_names.append((n, reset))
        self.timers = {}                # lower name -> index
        self.timer_names = []
        for t in program["timers"]:
            n = str(t.get("name") or "")
            if VAR_RE.match(n) and n.lower() not in self.timers:
                self.timers[n.lower()] = len(self.timer_names)
                self.timer_names.append(n)
        self.hits = []                  # shots whose hits this ball the program reads
        self.shows = []                 # each Light show block's steps, in order: SHOW_<n>

    def var(self, i, p="P()"):
        """Variable ``i`` of player ``p``, as C: its own row, or the shared global."""
        if i in self.shared:
            return "%s[%s]" % (shared_ident(self.var_names[i][0]), p)
        return "V[%d][%s]" % (i, p)

    def timer(self, name):
        return self.timers.get(str(name or "").lower())

    def shot(self, name):
        return "S[%d]" % self.shot_i(name)

    def shot_i(self, name):
        name = str(name or "")
        if name not in self.shots:
            self.shots.append(name)
        return self.shots.index(name)

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
            return self.var(i) if i is not None else "0LL"
        if k == "timer_left":
            i = self.timer(e.get("timer"))
            return "timer_left(%d)" % i if i is not None else "0LL"
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
        if k == "can_start":
            return "can_start()"
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
                    out.append(pad + "%s = %s;" % (self.var(i), self.num(b.get("value"))))
            elif op == "change":
                i = self.vars.get(str(b.get("var") or "").lower())
                if i is not None:
                    out.append(pad + "%s += %s;" % (self.var(i), self.num(b.get("by"))))
            elif op == "timer_start":
                i = self.timer(b.get("timer"))
                if i is not None:
                    out.append(pad + "timer_start(%d, %s);" % (i, self.num(b.get("ms"))))
            elif op == "timer_stop":
                i = self.timer(b.get("timer"))
                if i is not None:
                    out.append(pad + "T[%d] = 0;" % i)
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
                pattern = b.get("pattern") if b.get("pattern") in PATTERNS else "solid"
                pat, ms = PATTERNS[pattern]
                color = str(b.get("color") or "#ffffff")
                rgb = int(color[1:], 16) if COLOR_RE.match(color) else 0xFFFFFF
                rate = b.get("rate")
                pace = self.num(rate) if rate is not None and pattern not in ("solid", "hurry") else "%dLL" % ms
                out.append(pad + "light(%d, 0x%06xu, %s, %s, %d);"
                           % (self.shot_i(b.get("shot")), rgb, pat, pace, 1 if pattern == "hurry" else 0))
            elif op == "lights_off":
                if b.get("shot") == "*":
                    out.append(pad + "unlight_all();")
                else:
                    out.append(pad + "unlight(%d);" % self.shot_i(b.get("shot")))
            elif op == "show":
                steps = show_steps(b)
                if steps:
                    self.shows.append(steps)
                    name = b.get("show") if b.get("show") in SHOWS else "its own"
                    out.append(pad + "show_start(SHOW_%d, %d, %s);" % (len(self.shows) - 1, len(steps), _c_str(name)))
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


def shared_ident(name):
    """The C global a shared variable is in every mode that names it: case, spaces and _ aside,
    the same name is the same value (``"Maser won"`` -> ``pad_shared_maser_won``)."""
    return "pad_shared_" + re.sub(r"[^a-z0-9]", "_", str(name or "").lower())


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
            elif kind == "timer_done":
                t = g.timer(hat.get("timer"))
                test = "(due[%d])" % t if t is not None else "(0)"
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
    L.append("#define WAITS_OUT_MULTIBALL %d       /* 1 = a start while a multiball runs waits for the next */"
             % (1 if program["wait_multiball"] else 0))
    L.append("#define DISPLAY_PRIORITY %d          /* held while it runs; 0 = none (MODE_SDK.md) */"
             % program["priority"])
    L.append("#define TIMER_MAX_MS     %dL" % TIMER_MAX_MS)
    L.append("#define ENDING_MS        3000        /* the total its own screen shows at the end */")
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
    for i in sorted(g.shared):
        n, reset = g.var_names[i]
        L.append("/* %s: SHARED - one value per player for every mode that names it, reset %s. The linker"
                 % (_comment(n), RESETS[reset]))
        L.append(" * keeps one of these weak lines for all the modes built in; a mode in C shares it by"
                 " declaring the same. */")
        L.append('__attribute__((weak, visibility("hidden"))) long long %s[5];' % shared_ident(n))
    ntimers = max(1, len(g.timer_names))
    for i, n in enumerate(g.timer_names):
        L.append("/* T[%d] = the timer %s */" % (i, _comment(n)))
    L.append("UNUSED static unsigned long T[%d];           /* each timer's end, pm_ms(); 0 = not running */"
             % ntimers)
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
    L.append("/* a timer: ms from now (0 or less stops it); the milliseconds it has left */")
    L.append("UNUSED static void timer_start(int i, long long ms)")
    L.append("{")
    L.append("    if (ms <= 0) {")
    L.append("        T[i] = 0;")
    L.append("        return;")
    L.append("    }")
    L.append("    if (ms > TIMER_MAX_MS) ms = TIMER_MAX_MS;")
    L.append("    T[i] = pm_ms() + (unsigned long)ms;")
    L.append("    if (!T[i]) T[i] = 1;")
    L.append("}")
    L.append("")
    L.append("UNUSED static long long timer_left(int i)")
    L.append("{")
    L.append("    long left = T[i] ? (long)(T[i] - pm_ms()) : 0;")
    L.append("    return left > 0 ? left : 0;")
    L.append("}")
    L.append("")
    L.append("/* a multiball or one of the game's own modes runs (the kit's kit_game_busy): two balls in")
    L.append(" * play count as one; a port that cannot tell counts as none */")
    L.append("UNUSED static int game_busy(void)")
    L.append("{")
    L.append("    if (pm_stock_mode_running(PM_STOCK_BATTLE | PM_STOCK_MULTIBALL | PM_STOCK_ANY) > 0) return 1;")
    L.append("    return pm_can(PM_CAN_MULTIBALL) && pm_balls_in_play() >= 2;")
    L.append("}")
    L.append("")
    L.append("/* \"the mode could start now\": in a game, not running, and no multiball to wait out */")
    L.append("UNUSED static int can_start(void)")
    L.append("{")
    L.append("    return !run.on && pm_in_game() && !(WAITS_OUT_MULTIBALL && game_busy());")
    L.append("}")
    L.append("")
    for when in ("ball", "mode"):
        L.append("static void reset_%s(void)          /* the variables reset %s */" % (when, RESETS[when]))
        L.append("{")
        L.append("    unsigned p = P();")
        for i, (_n, reset) in enumerate(g.var_names):
            if reset == when:
                L.append("    %s = 0;" % g.var(i, "p"))
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
    if g.shows:
        L.extend(_show_decls(g.shows))
    else:
        L.append("#define SHOWING 0                         /* no Light show block */")
        L.append("")
    L.extend((_LAMPS_C % {"n": len(g.shots), "size": nshots, "lo": RATE_MIN, "hi": RATE_MAX}).split("\n"))
    if g.shows:
        L.extend(_SHOW_C.split("\n"))
    if media:
        L.extend((_MEDIA_C % {"slug": slug}).split("\n"))
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
    L.append("    static unsigned long said_at;")
    L.append("    if (run.on || !pm_in_game()) return;")
    L.append("    if (WAITS_OUT_MULTIBALL && game_busy()) {   /* it stays ready: the next start after it */")
    L.append("        if (!said_at || pm_ms() - said_at >= 10000)")
    L.append('            pm_log("not started (%s): a multiball or one of the game\'s modes is running - still ready", why);')
    L.append("        said_at = pm_ms() ? pm_ms() : 1;")
    L.append("        return;")
    L.append("    }")
    L.append("    if (!pm_begin()) return;          /* another of our modes is running */")
    L.append("    if (DISPLAY_PRIORITY) pm_display_priority(DISPLAY_PRIORITY);   /* first: before the screen */")
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
    L.append("    unlight_all();                    /* a show it ends with paints on, then hands back */")
    L.append("    if (screen) {")
    L.append('        words("TOTAL", (long long)run.total, 1);')
    L.append("        hide_ticks = 3 * TICKS_PER_SECOND;")
    L.append("    }")
    L.append("    /* a priority is kept for the total on its own screen (pm_end_holding); a drain hands it")
    L.append("     * back at once (end_now) */")
    L.append("    if (!(DISPLAY_PRIORITY && screen && pm_end_holding(ENDING_MS))) {")
    L.append("        pm_display_priority(0);")
    L.append("        pm_end();")
    L.append("    }")
    L.append('    pm_log("END (%s): %u scores, total %llu", why, run.shots, (unsigned long long)run.total);')
    L.append("}")
    L.append("")
    L.append("static void end_now(const char *why)   /* ended by the game: its display back at once */")
    L.append("{")
    L.append("    end(why);")
    L.append("    if (DISPLAY_PRIORITY) pm_display_priority(0);")
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
    if g.shows:
        L.append("    show_tick();                      /* every tick: an end show outlives the mode */")
    L.append("    if (in_game && !was_in_game) {    /* a new game: every player's \"each game\" values */")
    L.append("        unsigned p, v;")
    L.append("        for (p = 0; p < 5; p++) {")
    L.append("            for (v = 0; v < %d; v++) H[v][p] = 0;" % nhits)
    for i, (_n, reset) in enumerate(g.var_names):
        L.append("            %s = 0;" % g.var(i, "p"))
    L.append("        }")
    L.append("    }")
    L.append("    if (!in_game && was_in_game) {    /* the game is over: no timer runs on */")
    L.append("        unsigned t;")
    L.append("        for (t = 0; t < %d; t++) T[t] = 0;" % ntimers)
    L.append("    }")
    L.append("    was_in_game = in_game;")
    L.append("    if (++poll % 30 == 0) {            /* the tab's Start mode now / End mode */")
    L.append('        if (pm_trigger("%s.start")) start("trigger file");' % slug)
    L.append('        if (pm_trigger("%s.stop")) end("trigger file");' % slug)
    L.append("    }")
    L.append("    if (hide_ticks && --hide_ticks == 0 && !run.on && screen) pm_show(screen, 0);")
    timer_scripts = scripts_of("timer_done")
    if timer_scripts:
        L.append("    if (in_game) {                    /* the timers that ran out, then their scripts */")
        L.append("        int due[%d], t;" % ntimers)
        L.append("        unsigned long now = pm_ms();")
        L.append("        for (t = 0; t < %d; t++) {" % ntimers)
        L.append("            due[t] = T[t] && (long)(now - T[t]) >= 0;")
        L.append("            if (due[t]) T[t] = 0;")
        L.append("        }")
        L.extend("    " + line if line else line for code in timer_scripts for line in code.split("\n"))
        L.append("    }")
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
    L.append("    lamps_tick();")
    L.extend(scripts_of("every", "seconds_left"))
    L.append("    if (run.on && RUN_SECONDS && run.ticks_left == 0)")
    L.append('        end("time ran out");')
    L.append("}")
    L.append("")
    L.append("static void on_ball_end(void)")
    L.append("{")
    L.append("    unsigned t;")
    L.append("    for (t = 0; t < %d; t++) T[t] = 0;   /* a ball ending stops every timer */" % ntimers)
    L.extend(scripts_of("ball_end"))
    L.append("    if (ENDS_ON_DRAIN) end_now(\"ball ended\");")
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


#: the C that holds the shots' lights (PAD-376); %(n)d shots named, LIT sized %(size)d
_LAMPS_C = """/* ---- the shots' lights the blocks hold (PAD-376): kept, so a light show gives them back when
 * it is over, and a blink that hurries follows the clock ---- */
#define N_SHOTS   %(n)d
#define RATE_MIN  %(lo)d                     /* a blink's, pulse's or chase's pace, ms */
#define RATE_MAX  %(hi)d
UNUSED static struct { unsigned rgb, ms, sent; int pattern, hurry, on; } LIT[%(size)d];

/* the kit's kit_hurry_ms: slow with most of the time left, faster as it runs down, a flicker in
 * the last three seconds */
UNUSED static unsigned hurry_ms(void)
{
    unsigned long left = (unsigned long)run.ticks_left * 1000u / TICKS_PER_SECOND;
    unsigned long total = (unsigned long)RUN_SECONDS * 1000u;
    if (!run.on || !RUN_SECONDS) return 500;
    if (left * 3 > total * 2) return 700;
    if (left * 3 > total) return 400;
    if (left > 3000) return 200;
    return 100;
}

UNUSED static void lamp_send(int i)
{
    unsigned ms;
    if (i < 0 || i >= N_SHOTS || !S[i] || !LIT[i].on || SHOWING) return;
    ms = LIT[i].hurry ? hurry_ms() : LIT[i].ms;
    pm_lamp_shot(S[i], LIT[i].rgb, LIT[i].pattern, ms);
    LIT[i].sent = ms;
}

/* a shot's inserts lit; the same light again is left alone (a blink keeps its beat) */
UNUSED static void light(int i, unsigned rgb, int pattern, long long ms, int hurry)
{
    if (i < 0 || i >= N_SHOTS) return;
    if (pattern == PM_LAMP_SOLID || hurry) ms = 0;
    else if (ms < RATE_MIN) ms = RATE_MIN;
    else if (ms > RATE_MAX) ms = RATE_MAX;
    if (LIT[i].on && LIT[i].rgb == rgb && LIT[i].pattern == pattern && LIT[i].ms == (unsigned)ms
        && LIT[i].hurry == hurry) return;
    LIT[i].rgb = rgb;
    LIT[i].pattern = pattern;
    LIT[i].ms = (unsigned)ms;
    LIT[i].hurry = hurry;
    LIT[i].on = 1;
    lamp_send(i);
}

UNUSED static void unlight(int i)
{
    if (i < 0 || i >= N_SHOTS) return;
    LIT[i].on = 0;
    if (S[i]) pm_lamp_release_shot(S[i]);
}

static void unlight_all(void)
{
    int i;
    for (i = 0; i < N_SHOTS; i++) LIT[i].on = 0;
    pm_lamp_release_all();
}

UNUSED static void relight_all(void)                /* after a show: every light the blocks hold */
{
    int i;
    for (i = 0; i < N_SHOTS; i++) lamp_send(i);
}

static void lamps_tick(void)                        /* a hurrying blink follows the clock */
{
    int i;
    for (i = 0; i < N_SHOTS; i++)
        if (LIT[i].on && LIT[i].hurry && !SHOWING && hurry_ms() != LIT[i].sent) lamp_send(i);
}
"""


def _show_decls(shows):
    """The C of the light shows' steps (one table per Light show block) and their state."""
    out = ["/* ---- light shows (PAD-376): the kit's kit_show (intricate_kit.h). A show is a few STEPS,",
           " * each a pattern over the playfield's inserts by their PLACE (the port's \"at X,Y\": x 0-300",
           " * across, y 0-600 down) for some ms, in its two colours; the GI strings follow each step. A",
           " * port with no placed inserts runs a show on the GI only. ---- */",
           "enum { %s };" % ", ".join(c for c, _w in FX.values()),
           "#define GI_KEEP   0                       /* the GI does what the game says */",
           "#define GI_DARK   1                       /* the GI off: only the show lights the playfield */",
           "#define GI_FLASH  2                       /* the GI flashing white with a strobe */",
           "struct fx_step { int fx; unsigned ms, a, b; int x, y; unsigned rate; int gi; };"]
    gi_c = {"keep": "GI_KEEP", "dark": "GI_DARK", "flash": "GI_FLASH"}
    for n, steps in enumerate(shows):
        out.append("static const struct fx_step SHOW_%d[] = {" % n)
        for st in steps:
            at = PLACES.get(st.get("at"), PLACES["center"])
            col = [int(str(st.get(k))[1:], 16) if COLOR_RE.match(str(st.get(k) or "")) else 0 for k in ("a", "b")]
            try:
                ms = max(STEP_MS_MIN, min(STEP_MS_MAX, int(st.get("ms"))))
            except (TypeError, ValueError):
                ms = 500
            try:
                rate = max(0, min(FX_RATE_MAX, int(st.get("rate") or 0)))
            except (TypeError, ValueError):
                rate = 0
            out.append("    { %s, %d, 0x%06xu, 0x%06xu, %d, %d, %d, %s },   /* %s, at %s */" % (
                FX[st["fx"]][0], ms, col[0], col[1], at[1], at[2], rate,
                gi_c.get(st.get("gi"), "GI_KEEP"), FX[st["fx"]][1], at[0]))
        out.append("};")
    out += ["#define SHOW_LAMPS 256",
            "static struct {",
            "    const struct fx_step *steps;",
            "    const char *name;",
            "    int n, step, on, gi[8], n_gi, placed;",
            "    unsigned long t0, step_t0;",
            "    unsigned seed;",
            "} show;",
            "#define SHOWING show.on",
            ""]
    return out


#: the light-show engine: intricate_kit.h's kit_show, on the lights above (relight_all at its end)
_SHOW_C = r"""static unsigned fx_mix(unsigned a, unsigned b, int f256)       /* a..b by f/256 */
{
    int k, out = 0;
    if (f256 < 0) f256 = 0;
    if (f256 > 256) f256 = 256;
    for (k = 0; k < 3; k++) {
        int ca = (int)((a >> (16 - 8 * k)) & 255u), cb = (int)((b >> (16 - 8 * k)) & 255u);
        out |= ((ca + (cb - ca) * f256 / 256) & 255) << (16 - 8 * k);
    }
    return (unsigned)out;
}

static unsigned fx_scale(unsigned c, int f256) { return fx_mix(0, c, f256); }

static unsigned fx_hue(int h)             /* 0..1535 round the colour wheel, full brightness */
{
    int s = ((h % 1536) + 1536) % 1536, i = s / 256, f = s % 256;
    switch (i) {
    case 0: return PM_RGB(255, f, 0);
    case 1: return PM_RGB(255 - f, 255, 0);
    case 2: return PM_RGB(0, 255, f);
    case 3: return PM_RGB(0, 255 - f, 255);
    case 4: return PM_RGB(f, 0, 255);
    default: return PM_RGB(255, 0, 255 - f);
    }
}

static unsigned fx_rand(void)
{
    show.seed = show.seed * 1103515245u + 12345u;
    return (show.seed >> 16) & 0x7fffu;
}

static int fx_isqrt(int v)
{
    int r = 0, b = 1 << 14;
    if (v <= 0) return 0;
    while (b > v) b >>= 2;
    while (b) {
        if (v >= r + b) { v -= r + b; r = (r >> 1) + b; } else r >>= 1;
        b >>= 2;
    }
    return r;
}

static int fx_angle(int dx, int dy)        /* atan2 in 1/1536 turns (the hue wheel's) */
{
    int ax = dx < 0 ? -dx : dx, ay = dy < 0 ? -dy : dy, a;
    if (!ax && !ay) return 0;
    a = ax >= ay ? (ay * 192) / (ax ? ax : 1) : 384 - (ax * 192) / (ay ? ay : 1);
    if (dx < 0) a = 768 - a;
    if (dy < 0) a = 1536 - a;
    return a % 1536;
}

static int is_gi(const char *s)            /* a GI string: "GI" a word of its own in the name */
{
    int i;
    for (i = 0; s && s[i] && s[i + 1]; i++)
        if (s[i] == 'G' && s[i + 1] == 'I' && (i == 0 || s[i - 1] < 'A' || s[i - 1] > 'Z')
            && (s[i + 2] < 'A' || s[i + 2] > 'Z'))
            return 1;
    return 0;
}

static void show_start(const struct fx_step *steps, int n, const char *name)
{
    int k, cnt = pm_lamp_count();
    show.steps = steps;
    show.n = n;
    show.name = name;
    show.step = 0;
    show.on = pm_can(PM_CAN_LAMPS) && n > 0;
    show.t0 = show.step_t0 = pm_ms();
    show.seed = (unsigned)show.t0 | 1u;
    show.n_gi = show.placed = 0;
    for (k = 0; k < cnt && k < SHOW_LAMPS; k++) {
        int x, y;
        if (pm_lamp_xy(k, &x, &y)) show.placed++;
        else if (show.n_gi < 8 && is_gi(pm_lamp_at(k, 0))) show.gi[show.n_gi++] = k;
    }
    if (show.on) pm_log("show %s: %d step(s) over %d placed inserts, %d GI string(s)", name, n, show.placed, show.n_gi);
}

/* the colour of the insert at (x, y) for step st at `t` ms into it */
static unsigned fx_colour(const struct fx_step *st, int x, int y, int idx, unsigned t)
{
    int f = st->ms ? (int)((unsigned long)t * 256u / st->ms) : 256;     /* 0..256 through the step */
    int dx = x - st->x, dy = y - st->y, d, r, w, v;
    unsigned rate = st->rate ? st->rate : 100;
    switch (st->fx) {
    case FX_BURST:
    case FX_IMPLODE:
        d = fx_isqrt(dx * dx + dy * dy);
        r = st->fx == FX_BURST ? f * 700 / 256 : (256 - f) * 700 / 256;
        w = d - r;
        if (w > 0 && w < 60) return fx_scale(st->a, 256 - w * 4);          /* the ring's leading edge */
        if (w <= 0 && w > -140) return fx_mix(st->a, st->b, -w * 256 / 140); /* its wake */
        return w <= 0 ? st->b : 0;
    case FX_SWEEP_UP:
    case FX_SWEEP_DOWN:
        r = st->fx == FX_SWEEP_UP ? 640 - f * 720 / 256 : f * 720 / 256 - 40;
        w = st->fx == FX_SWEEP_UP ? y - r : r - y;
        if (w >= 0 && w < 50) return st->a;
        if (w >= 50) return fx_mix(st->a, st->b, (w - 50) * 3);
        return 0;
    case FX_SWEEP_LR:
    case FX_SWEEP_RL:
        r = st->fx == FX_SWEEP_LR ? f * 380 / 256 - 40 : 340 - f * 380 / 256;
        w = st->fx == FX_SWEEP_LR ? r - x : x - r;
        if (w >= 0 && w < 30) return st->a;
        if (w >= 30) return fx_mix(st->a, st->b, (w - 30) * 4);
        return 0;
    case FX_SPIN:
        v = (fx_angle(dx, dy) - (int)(t * 1536u / (rate * 8u))) % 1536;
        if (v < 0) v += 1536;
        return v < 160 ? st->a : v < 400 ? fx_mix(st->a, st->b, (v - 160) * 256 / 240) : st->b;
    case FX_RAINBOW:
        return fx_hue(fx_angle(dx, dy) + (int)(t * 1536u / (rate * 10u)) + fx_isqrt(dx * dx + dy * dy) * 2);
    case FX_STROBE:
        return (t / rate) % 2 ? st->b : st->a;
    case FX_SPARKLE:
        return ((fx_rand() + (unsigned)idx * 7u) % 100u) < 18u ? st->a : st->b;
    case FX_FIRE:
        v = (int)(fx_rand() % 90u);
        w = (600 - y) * 256 / 600;                                           /* 0 at the flippers */
        return fx_scale(fx_mix(st->b, st->a, w + v - 45), 150 + v);
    case FX_PULSE:
        v = (int)((t % (rate * 2u)) * 512u / (rate * 2u));
        v = v < 256 ? v : 512 - v;
        return fx_mix(st->b, st->a, v);
    case FX_CHASE_RING:
        v = (fx_angle(dx, dy) * 12 / 1536 + 12 - (int)((t / rate) % 12u)) % 12;
        return v == 0 ? st->a : v == 1 ? fx_scale(st->a, 110) : st->b;
    case FX_FADE_OUT:
        return fx_scale(st->a, 256 - f);
    case FX_BOLTS:
        v = (int)((t / rate) % 5u);                                          /* five strikes */
        r = 40 + v * 55 + (int)((unsigned)(y * 13 + v * 71) % 40u) - 20;     /* the bolt's jagged x */
        w = x - r;
        if (w < 0) w = -w;
        return w < 18 && (t % rate) < rate * 2 / 3 ? st->a : st->b;
    }
    return 0;
}

/* every tick while the show runs: each placed insert painted, the GI as the step says; at its
 * end every insert goes back to the game and the blocks' own shot lights are sent again */
static void show_tick(void)
{
    const struct fx_step *st;
    unsigned long now = pm_ms();
    unsigned t;
    int k, cnt;
    if (!show.on) return;
    while (show.step < show.n && now - show.step_t0 >= show.steps[show.step].ms) {
        show.step_t0 += show.steps[show.step].ms;
        show.step++;
    }
    if (show.step >= show.n) {
        show.on = 0;
        pm_lamp_release_all();
        relight_all();
        pm_log("show %s: over, %lu ms", show.name, now - show.t0);
        return;
    }
    st = &show.steps[show.step];
    t = (unsigned)(now - show.step_t0);
    cnt = pm_lamp_count();
    for (k = 0; k < cnt && k < SHOW_LAMPS; k++) {
        int x, y;
        if (pm_lamp_xy(k, &x, &y)) pm_lamp_paint(k, fx_colour(st, x, y, k, t));
    }
    for (k = 0; k < show.n_gi; k++) {
        if (st->gi == GI_DARK) pm_lamp_paint(show.gi[k], 0);
        else if (st->gi == GI_FLASH) pm_lamp_paint(show.gi[k], ((t / (st->rate ? st->rate : 100)) % 2) ? 0 : 0xffffffu);
        else pm_lamp_release(pm_lamp_at(show.gi[k], 0));
    }
}
"""


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
    if kind == "timer_done":
        return "when the timer %s runs out" % (hat.get("timer") or "(no timer)")
    return HATS.get(kind, "?").lower()
