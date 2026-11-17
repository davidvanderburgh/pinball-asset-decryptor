"""JJP custom modes in the app (PAD-1350): the Tk-free half of the Modes tab's JJP editor.

The JJP mode SDK (tools/jjp_emu: ``jjpmodes.c`` the runtime, ``mkjjpmodes.py`` the checker
and the install-ISO writer, ``jjpport.py`` a title's port report) runs custom modes inside a
retail Jersey Jack game, found by the game's own exported names.  A mode is a
``key = value`` file; a title's modes are one folder of them (``title.cfg`` + ``*.mode``).
This module is what the tab needs on top of that:

* the titles - every port report in ``tools/jjp_emu/modes/ports`` (``titles()``), the ones
  whose engine can run modes first;
* a mode folder per title, kept in the app's settings folder and seeded from the title's
  starter folder (``tools/jjp_emu/modes/examples/<title>``) the first time;
* reading and writing one mode as fields, new / duplicate / delete;
* the checker - ``mkjjpmodes.check_modes`` against the title's port report, in-process;
* which of a title's ``se_*`` sounds an extract folder holds (``sound_index``): the game's
  ``se_Fanfare_Jackpot`` is the extract's ``sound/fanfare/Fanfare_Jackpot.wav``;
* the stock install ISO in the library, and the argv of the build (``build_args``).

Nothing here starts a process; the tab runs the build (as root in WSL: it loop-mounts the
ISO's root) on a worker.
"""
import collections
import importlib.util
import json
import os
import re
import shutil

from . import block_modes as BM

#: the display names of the JJP titles, by GAMENAME (setenv.sh) - a port report carries the
#: GAMENAME; a label like "Wonka-v03.03" is the image's own file name
GAME_NAMES = {
    "GunsNRoses": "Guns N' Roses",
    "EltonJohn": "Elton John",
    "Godfather": "The Godfather",
    "TheGodfather": "The Godfather",
    "Pirates": "Pirates of the Caribbean",
    "Wonka": "Willy Wonka & the Chocolate Factory",
    "DialedIn": "Dialed In!",
    "Hobbit": "The Hobbit",
    "TheHobbit": "The Hobbit",
    "ToyStory": "Toy Story 4",
    "WizardOfOz": "The Wizard of Oz",
    "Avatar": "Avatar",
    "HarryPotter": "Harry Potter",
    "Sonic": "Sonic",
}
#: labels whose GAMENAME is another title's (a mod built on it)
LABEL_NAMES = {
    "CHAKAs_LOTLJ_V1.0_GNR_LE_3.03": "CHAKA's LOTLJ 1.0 (Guns N' Roses LE 3.03 mod)",
}
#: the runtime's limits (jjpmodes.c; mkjjpmodes.MAX_MODES)
MAX_MODES = 24
#: the keys a mode file takes, grouped as the form shows them (every key of
#: mkjjpmodes.KEYS appears exactly once - tests hold it to that)
FORM_GROUPS = (
    ("Mode", ("name", "title", "start", "start_count", "shots", "points", "seconds", "complete",
              "complete_points", "game_modes", "hold_multiballs", "allow_game_modes")),
    # PAD-1354: what else starts it, from the game's own events
    ("Starts", ("start_on", "start_after", "start_score", "start_combo", "combo_seconds",
                "start_count_reset", "start_once")),
    ("Sounds", ("sound_start", "sound_shot", "sound_complete", "sound_end", "sound_channel", "sound_like",
                "music", "music_like")),
    ("Picture and video", ("picture", "picture_at", "video", "video_at", "video_loop")),
    ("Lamps", ("lamps", "lamp_color", "lamp_blink")),
    ("Screen", ("font_title", "font_value", "font_timer", "title_color", "value_color", "timer_color",
                "panel_color", "panel")),
    ("Balls", ("multiball", "multiball_on", "add_ball", "ball_save")),                       # PAD-1353
    ("Coils", ("coil_start", "coil_shot", "coil_complete", "coil_hold", "coil_hold_on")),     # PAD-1353
)
#: mode keys the form does not show: ``code`` is set when a mode is made with blocks or in C++
#: (the New mode window, PAD-1384) and shown as how the mode is made
NOT_ON_FORM = ("code",)
#: the runtime's defaults (MODES.md "Mode keys"): what an empty key means
DEFAULTS = {
    "start_count": "1", "points": "1000000", "seconds": "20", "complete": "0", "complete_points": "0",
    "lamp_color": "ffffff", "lamp_blink": "4", "title_color": "ffffff", "value_color": "ffdc00",
    "timer_color": "ffffff", "panel_color": "000000b0", "panel": "middle", "game_modes": "hold",
    "hold_multiballs": "yes", "sound_channel": "fanfare", "picture_at": "0 0 100 100",
    "video_at": "0 0 100 100", "video_loop": "yes",
    "coil_hold_on": "shots", "coil_holds": "off",
    "combo_seconds": "5", "start_count_reset": "game", "start_once": "no",
}
LABELS = {
    "name": "Name", "title": "Title on the screen", "start": "Started by", "start_count": "Hits to start",
    "shots": "Scoring shots", "points": "Points a shot", "seconds": "Seconds", "complete": "Shots to complete",
    "complete_points": "Completion bonus", "game_modes": "When a game mode runs",
    "hold_multiballs": "Hold off multiballs too", "allow_game_modes": "Game modes still allowed",
    "sound_start": "Start sound", "sound_shot": "Shot sound", "sound_complete": "Completed sound",
    "sound_end": "End sound", "lamps": "Lamps", "lamp_color": "Lamp color", "lamp_blink": "Flashes a second",
    "font_title": "Title font", "font_value": "Total font", "font_timer": "Timer font",
    "title_color": "Title color", "value_color": "Total color", "timer_color": "Timer color",
    "panel_color": "Panel color", "panel": "Panel place",
    "sound_channel": "Channel for our sound files", "sound_like": "Our sounds set like",
    "music": "Music (a file of ours)", "music_like": "Our music set like",
    "picture": "Picture (a file of ours)", "picture_at": "Picture box (x y w h, % of screen)",
    "video": "Video (a file of ours)", "video_at": "Video box (x y w h, % of screen)", "video_loop": "Video loops",
    "game": "Game", "ingame_state": "Ball-in-play state", "background_modes": "Always-on game modes",
    "multiball": "Multiball", "multiball_on": "Multiball balls come on",
    "add_ball": "Add a ball on", "ball_save": "Ball save",
    "coil_start": "Coil at the start", "coil_shot": "Coil on each shot",
    "coil_complete": "Coil on completion", "coil_hold": "Hold a coil",
    "coil_hold_on": "Hold it on", "coil_holds": "Coil holds on this title",
    "start_on": "Starts on a game event", "start_after": "Starts after a game mode ends",
    "start_score": "Starts at a score", "start_combo": "Starts on a combo (in order)",
    "combo_seconds": "Combo seconds between shots", "start_count_reset": "Start count resets every",
    "start_once": "Starts at most once a", "code": "Its own code",
}
#: title.cfg keys the title settings show (game is fixed by the port report)
TITLE_FORM = ("font_title", "font_value", "font_timer", "title_color", "value_color", "timer_color",
              "panel_color", "panel", "game_modes", "hold_multiballs", "ingame_state", "coil_holds")


# ============================================================================ where things are
def tools_dir():
    """tools/jjp_emu, resolved from this file (a checkout or the installed app alike).  Not
    PAD_JJP_EMU_DIR: that moves the emulator rig (and the tests point it at no rig at all),
    while the SDK's checker, port reports and starter folders are data the app ships."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "tools", "jjp_emu")


def ports_dir():
    return os.path.join(tools_dir(), "modes", "ports")


def examples_dir():
    return os.path.join(tools_dir(), "modes", "examples")


def modes_root():
    """Where the app keeps the person's mode folders, one per title: the settings folder's
    ``jjp_modes`` (PAD_JJP_MODES_DIR moves it - the tests)."""
    env = os.environ.get("PAD_JJP_MODES_DIR")
    if env:
        return env
    from ...core import config
    return os.path.join(os.path.dirname(config.SETTINGS_FILE), "jjp_modes")


_MK = None


def mk():
    """tools/jjp_emu/mkjjpmodes.py as a module (the checker the build runs, so the tab and the
    build can never disagree about a mode file)."""
    global _MK
    path = os.path.join(tools_dir(), "mkjjpmodes.py")
    if _MK is None or getattr(_MK, "__file__", None) != path:
        spec = importlib.util.spec_from_file_location("pad_mkjjpmodes", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _MK = mod
    return _MK


# ============================================================================ titles
_PORTS = {}


def load_port(label):
    """A title's port report (cached by mtime), or None."""
    p = os.path.join(ports_dir(), label + ".json")
    try:
        st = os.stat(p).st_mtime
    except OSError:
        return None
    hit = _PORTS.get(p)
    if hit and hit[0] == st:
        return hit[1]
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    _PORTS[p] = (st, data)
    return data


def version_of(label):
    m = re.search(r"[-_]v?(\d+\.\d+)$", label)
    return m.group(1) if m else ""


def display_name(label, port=None):
    if label in LABEL_NAMES:
        return LABEL_NAMES[label]
    game = (port or {}).get("game") or re.sub(r"-v?\d+(\.\d+)*$", "", label)
    name = GAME_NAMES.get(game) or game
    ver = version_of(label)
    return "%s %s" % (name, ver) if ver else name


def titles():
    """Every port report: [{label, name, game, can_run, why, counts}], the ones that can run
    modes first, then by name."""
    out = []
    d = ports_dir()
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else ():
        # <title>.live.json is jjpstock.py's read of a running game (PAD-1351), not a title
        if not fn.endswith(".json") or fn.endswith(".live.json"):
            continue
        label = fn[:-5]
        try:
            p = load_port(label)
        except (OSError, ValueError):
            continue
        if not p:
            continue
        can = bool(p.get("can_run_modes"))
        why = ""
        if not can:
            why = ("its game does not export the engine (%d names)" % p.get("exported_symbols", 0)
                   if p.get("missing_required") else "its Mode class does not match")
        out.append({"label": label, "name": display_name(label, p), "game": p.get("game", ""),
                    "can_run": can, "why": why,
                    "counts": {k: len(p.get(k) or ()) for k in ("switches", "lamps", "lamp_groups", "sounds", "fonts")}})
    out.sort(key=lambda t: (not t["can_run"], t["name"].lower()))
    return out


# ============================================================================ a title's folder
def title_dir(label, seed=True):
    """The person's mode folder for *label*; made (from the title's starter folder when there
    is one, else a title.cfg naming the game) the first time."""
    d = os.path.join(modes_root(), label)
    if seed and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
        ex = os.path.join(examples_dir(), label)
        if os.path.isdir(ex):
            for fn in sorted(os.listdir(ex)):
                if fn == "title.cfg" or fn.endswith(".mode"):
                    shutil.copyfile(os.path.join(ex, fn), os.path.join(d, fn))
        if not os.path.isfile(os.path.join(d, "title.cfg")):
            p = load_port(label) or {}
            write_cfg(os.path.join(d, "title.cfg"), {"game": p.get("game", "")},
                      "%s - title-wide defaults for every mode in this folder" % label)
    return d


def read_cfg(path):
    """A mode file / title.cfg as {key: value} (the runtime's reading: mkjjpmodes.parse_cfg)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return collections.OrderedDict()
    return collections.OrderedDict((k, v) for _n, k, v in mk().parse_cfg(text))


def write_cfg(path, values, header=""):
    """Write *values* as ``key = value`` lines in the runtime's key order (unknown keys kept,
    after), empty ones left out; LF line ends (the machine is Linux)."""
    keys = list(mk().TITLE_KEYS) + list(mk().KEYS)
    order = [k for k in keys if k in values] + [k for k in values if k not in keys]
    lines = []
    if header:
        lines.append("# " + header)
    for k in order:
        v = str(values.get(k) if values.get(k) is not None else "").strip()
        if v != "":
            lines.append("%s = %s" % (k, v))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


def mode_files(label):
    d = title_dir(label)
    return sorted(f for f in os.listdir(d) if f.endswith(".mode"))


def list_modes(label):
    """[{file, name, start, starts, kind, code}] in the runtime's load order (file name); *starts*
    says everything that starts it, its switches and its start rules (PAD-1377); *kind* is how
    it is made: "form", "cpp" (its own C++) or "blocks" (PAD-1384)."""
    out = []
    d = title_dir(label)
    for fn in mode_files(label):
        v = read_cfg(os.path.join(d, fn))
        starts = mk().start_text(v)
        code = v.get("code", "")
        if not starts and code and mk().code_starts_itself(d, code):
            starts = "its own code"
        out.append({"file": fn, "name": v.get("name") or fn[:-5], "start": v.get("start", ""),
                    "starts": starts, "kind": kind_of(d, code), "code": code})
    return out


# ============================================================================ C++ and blocks (PAD-1384)
#: how a new mode is made, as the New mode window offers it (the Stern tab's three ways)
HOWS = ("blocks", "cpp", "form")


def sdk_dir():
    return os.path.join(tools_dir(), "modes", "sdk")


def api_header():
    """The C++ API a mode's code is written against (the "C++ API" button opens it)."""
    return os.path.join(sdk_dir(), "jjp_mode.h")


def kind_of(folder, code):
    if not code:
        return "form"
    return "blocks" if os.path.isfile(os.path.join(folder, code + BM.SUFFIX)) else "cpp"


def mode_kind(label, fn):
    return kind_of(title_dir(label), read_mode(label, fn).get("code", ""))


def code_of(label, fn):
    code = read_mode(label, fn).get("code", "")
    return code if mk().CODE_NAME.match(code or "") else ""


def code_path(label, fn, ext=".cpp"):
    code = code_of(label, fn)
    if not code:
        raise ValueError("%s has no code of its own" % fn)
    return os.path.join(title_dir(label), code + ext)


def _codes_used(label):
    return {read_mode(label, f).get("code", "") for f in mode_files(label)} - {""}


def _free_code(label, name):
    """A code name for a new mode: its slug, not used by a mode or a file of the folder."""
    d = title_dir(label)
    base = re.sub(r"^[^a-z_]+", "", _slug(name)) or "mode"
    used = _codes_used(label)
    code, n = base, 2
    while code in used or any(os.path.exists(os.path.join(d, code + e)) for e in (".cpp", ".so", BM.SUFFIX)):
        code, n = "%s_%d" % (base, n), n + 1
    return code


def template_text(name, title):
    with open(os.path.join(sdk_dir(), "template_mode.cpp"), encoding="utf-8") as f:
        text = f.read()
    return text.replace("MODE_NAME", name).replace("MODE_TITLE", title.replace('"', "'"))


def read_code(label, fn):
    with open(code_path(label, fn), encoding="utf-8", errors="replace") as f:
        return f.read()


def write_code(label, fn, text):
    if mode_kind(label, fn) == "blocks":
        raise ValueError("this mode is made of blocks: its C++ is written from them")
    p = code_path(label, fn)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text.replace("\r\n", "\n"))
    os.replace(tmp, p)


def read_blocks(label, fn):
    return BM.load(code_path(label, fn, BM.SUFFIX))


def save_blocks(label, fn, program):
    """The program saved, and the C++ it makes written again beside it."""
    if mode_kind(label, fn) != "blocks":
        raise ValueError("%s is not made of blocks" % fn)
    code = code_of(label, fn)
    BM.save(code_path(label, fn, BM.SUFFIX), program)
    v = read_mode(label, fn)
    with open(code_path(label, fn) + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        f.write(BM.to_cpp(program, v.get("name") or fn[:-5], code))
    os.replace(code_path(label, fn) + ".tmp", code_path(label, fn))


def blocks_to_cpp(label, fn):
    """A blocks mode becomes a C++ mode for good: its program is kept as <code>.blocks.json.bak."""
    p = code_path(label, fn, BM.SUFFIX)
    if os.path.isfile(p):
        os.replace(p, p + ".bak")


def blocks_names(port, folder):
    """What the Blocks editor offers for this title: its switches, lamps, sounds and coils."""
    return {"kit": "jjp", "shots": names_for(port, "switches"), "lamps": names_for(port, "lamps"),
            "sounds": names_for(port, "sound"), "coils": names_for(port, "coil_pulse")}


def code_stale(label):
    """The modes whose C++ is not built, or changed since: [(file, code)]."""
    d = title_dir(label)
    out = []
    for f in mode_files(label):
        code = code_of(label, f)
        src, so = os.path.join(d, code + ".cpp"), os.path.join(d, code + ".so")
        if code and os.path.isfile(src) and (not os.path.isfile(so) or os.path.getmtime(src) > os.path.getmtime(so) + 1):
            out.append((f, code))
    return out


def code_args(label, to_linux):
    """The mkjjpmodes.py code argv (as root, from the checkout root: it installs g++ the first time)."""
    return ["tools/jjp_emu/mkjjpmodes.py", "code", "--modes", to_linux(title_dir(label))]


def read_mode(label, fn):
    return read_cfg(os.path.join(title_dir(label), _safe(fn)))


def write_mode(label, fn, values):
    write_cfg(os.path.join(title_dir(label), _safe(fn)), values,
              "%s - made in the app's Modes tab. Every key: tools/jjp_emu/MODES.md" % (values.get("name") or fn))


def read_title(label):
    return read_cfg(os.path.join(title_dir(label), "title.cfg"))


def write_title(label, values):
    p = load_port(label) or {}
    values = collections.OrderedDict(values)
    if p.get("game"):
        values["game"] = p["game"]             # the modes load only into this game
    write_cfg(os.path.join(title_dir(label), "title.cfg"), values,
              "%s - title-wide defaults for every mode in this folder" % label)


def _safe(fn):
    fn = os.path.basename(fn or "")
    if not fn.endswith(".mode") or fn.startswith("."):
        raise ValueError("not a mode file: %r" % fn)
    return fn


def _slug(name):
    s = re.sub(r"[^a-z0-9]+", "_", (name or "mode").lower()).strip("_")
    return s[:40] or "mode"


def _next_file(label, name):
    used = mode_files(label)
    nums = [int(m.group(1)) for m in (re.match(r"^(\d+)_", f) for f in used) if m]
    n = (max(nums) + 1) if nums else 1
    fn = "%d_%s.mode" % (n, _slug(name))
    while fn in used:
        n += 1
        fn = "%d_%s.mode" % (n, _slug(name))
    return fn


def new_mode(label, name="New Mode", how="form"):
    """A new mode from the title's starter defaults (its port report's picks) -> its file.
    *how* (PAD-1384): "form", "cpp" (with the SDK's template C++) or "blocks" (a starter program
    and the C++ it makes)."""
    if how not in HOWS:
        raise ValueError("a mode is made with blocks, in C++ or with the form, not %r" % how)
    if len(mode_files(label)) >= MAX_MODES:
        raise ValueError("a title takes %d modes; delete one first" % MAX_MODES)
    d = (load_port(label) or {}).get("defaults") or {}
    v = collections.OrderedDict([("name", name), ("title", name.upper()), ("start", d.get("start", "")),
                                 ("shots", d.get("shots", "")), ("points", "1000000"), ("seconds", "20"),
                                 ("complete", "5"), ("complete_points", "5000000")])
    for k in ("sound_start", "sound_shot", "sound_end"):
        if d.get(k):
            v[k] = d[k]
    if d.get("lamps"):
        v["lamps"], v["lamp_color"], v["lamp_blink"] = d["lamps"], "ff2000", "4"
    fn = _next_file(label, name)
    if how != "form":
        code = _free_code(label, name)
        v["code"] = code
        v["complete"] = "0"         # its code decides when it is done (the form's completion off)
        folder = title_dir(label)
        if how == "blocks":
            prog = BM.starter(d, name)
            BM.save(os.path.join(folder, code + BM.SUFFIX), prog)
            text = BM.to_cpp(prog, name, code)
        else:
            text = template_text(name, v["title"])
        with open(os.path.join(folder, code + ".cpp"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    write_mode(label, fn, v)
    return fn


def duplicate_mode(label, fn):
    if len(mode_files(label)) >= MAX_MODES:
        raise ValueError("a title takes %d modes; delete one first" % MAX_MODES)
    v = read_mode(label, fn)
    v["name"] = (v.get("name") or fn[:-5]) + " copy"
    new = _next_file(label, v["name"])
    old = v.get("code", "")
    if old:                                 # its code goes with it, under a name of its own
        d = title_dir(label)
        code = _free_code(label, v["name"])
        for ext in (".cpp", BM.SUFFIX):
            if os.path.isfile(os.path.join(d, old + ext)):
                shutil.copyfile(os.path.join(d, old + ext), os.path.join(d, code + ext))
        v["code"] = code
        if os.path.isfile(os.path.join(d, code + BM.SUFFIX)):
            with open(os.path.join(d, code + ".cpp"), "w", encoding="utf-8", newline="\n") as f:
                f.write(BM.to_cpp(BM.load(os.path.join(d, code + BM.SUFFIX)), v["name"], code))
    write_mode(label, new, v)
    return new


def delete_mode(label, fn):
    code = code_of(label, fn)
    os.unlink(os.path.join(title_dir(label), _safe(fn)))
    if code and code not in _codes_used(label):     # its code, unless another mode shares it
        for ext in (".cpp", ".so", BM.SUFFIX):
            p = os.path.join(title_dir(label), code + ext)
            if os.path.isfile(p):
                os.unlink(p)


def check(label):
    """(modes, problems) - the build's own check of the title's folder against its port
    report."""
    return mk().check_modes(title_dir(label), load_port(label))


def key_kind(key):
    m = mk()
    return m.KEYS.get(key) or m.TITLE_KEYS.get(key)


def media_files(folder, kind):
    """The files of *kind* ('sound_file', 'picture_file', 'video_file') in a mode folder
    (PAD-1352: a mode's own media sits beside its .mode files)."""
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder)
                  if os.path.isfile(os.path.join(folder, f)) and mk().media_kind(f) == kind)


def names_for(port, kind, folder=None):
    """The names a picker offers for a key of *kind* (mkjjpmodes.KEYS' kinds); file kinds list
    the mode folder's own files, and a sound key offers those as well as the game's sounds."""
    if kind in ("sound_file", "picture_file", "video_file"):
        return media_files(folder, kind)
    if kind == "sound_or_file":
        return media_files(folder, "sound_file") + list(port.get("sounds") or ())
    if kind == "switches":
        return list(port.get("switches") or ())
    if kind == "lamps":
        return list(port.get("lamps") or ()) + list(port.get("lamp_groups") or ())
    if kind == "sound":
        return list(port.get("sounds") or ())
    if kind == "font":
        return list(port.get("fonts") or ())
    if kind == "events":            # start_on: the events this title's hook lists offer
        sr = port.get("start_rules") or {}
        return list(sr.get("start_on") or ()) if sr else list(mk().START_EVENTS)
    if kind in ("coil_pulse", "coil_hold"):     # PAD-1376: the port's coils a mode may pulse / hold
        want = "pulse" if kind == "coil_pulse" else "hold"
        return [c["symbol"] for c in port.get("coils") or () if c.get(want)]
    if kind == "after":             # start_after: the game's mode globals and classes, or any
        st = port.get("stock") or {}
        return ["any"] + sorted(st.get("objects") or ()) + sorted(
            set(st.get("classes") or ()) | set(port.get("mode_classes") or ())
            | set(port.get("proc_modes") or ()))   # PAD-1365: the proc engine's game modes
    return []


# ============================================================================ sounds to hear
_SND = {}


def sound_index(folder):
    """{stem lower: path} of every .wav / .ogg under an extract folder (cached per folder by
    its top-level mtime): a game's ``se_X`` is the file ``X.wav``."""
    if not folder or not os.path.isdir(folder):
        return {}
    try:
        key = (folder, os.stat(folder).st_mtime)
    except OSError:
        return {}
    hit = _SND.get(folder)
    if hit and hit[0] == key:
        return hit[1]
    idx = {}
    for d, _dirs, files in os.walk(folder):
        for f in files:
            stem, ext = os.path.splitext(f)
            if ext.lower() in (".wav", ".ogg"):
                idx.setdefault(stem.lower(), os.path.join(d, f))
    _SND[folder] = (key, idx)
    return idx


def sound_file(index, name):
    if not name or not name.startswith("se_"):
        return ""
    return index.get(name[3:].lower(), "")


# ============================================================================ the build
def find_stock_iso(label, folders):
    """The stock install ISO for *label* (``<label>.iso``) in the first of *folders* that has
    one, or ""."""
    want = (label + ".iso").lower()
    for d in folders:
        if not d or not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if fn.lower() == want:
                return os.path.join(d, fn)
    return ""


def default_out(iso, folder=""):
    stem = re.sub(r"\.iso$", "", os.path.basename(iso or "game.iso"), flags=re.I)
    return os.path.join(folder or os.path.dirname(iso or "") or ".", stem + ".modes.iso")


#: the build's scratch (a copy of the root, its re-imaged pieces): a Linux path, never beside
#: the output on a Windows drive, where a 16 GB sparse root crawls through WSL's file bridge
#: (multiboot_core.JJP_WORKDIR's rule)
WORKDIR = "/var/tmp/pad_jjpmodes_work"
#: what the build's command line carries, for finding (and stopping) it inside Linux; the
#: bracket keeps a pkill of it from matching the shell that runs the pkill
BUILD_PATTERN = "tools/jjp_emu/mkjjp[m]odes.py build"


def build_args(iso, label, out, to_linux):
    """The mkjjpmodes.py build argv (run from the checkout root, as root) with every path as
    the tool sees it (*to_linux*)."""
    tool = "tools/jjp_emu/mkjjpmodes.py"
    return [tool, "build", "--iso", to_linux(iso), "--modes", to_linux(title_dir(label)),
            "--out", to_linux(out), "--port", to_linux(os.path.join(ports_dir(), label + ".json")),
            "--workdir", WORKDIR, "--overwrite"]


# ============================================================================ the USB stick
# PAD-1375: the everyday way in - a folder the game's own Update USB hot fix runs
# (mkjjpmodes.py stick, PAD-1349): no reinstall, scores and settings kept.  The stick is plain
# files written in-process; only its runtime (jjpmodes.so, built against the game's own glibc)
# needs Linux as root, once per stock ISO, and is kept beside the mode folders after that.

#: what a stick can do, as the tab offers it (mkjjpmodes.STICK_ACTIONS)
STICK_ACTIONS = (
    ("install", "Install these modes"),
    ("off", "Turn the modes off"),
    ("on", "Turn the modes back on"),
    ("remove", "Take the modes out"),
)
#: the runtime build's command line, for stopping it inside Linux (see BUILD_PATTERN)
RUNTIME_PATTERN = "tools/jjp_emu/mkjjp[m]odes.py runtime"
#: what to do at the machine (MODES.md "A USB stick, no reinstall"; the stick's own README)
STICK_STEPS = (
    "Take the stick out and put it in the machine's USB port. Machine on, coin door open.",
    "Open the service menu and go to its USB update screen (Software Update > USB Update). "
    "It says \"No update data was found\": that is expected.",
    "Hold the LEFT FLIPPER button and, still holding it, press Plus, Minus, Plus, Minus. "
    "It asks \"Press ENTER to apply HOTFIX\".",
    "Press ENTER, then ENTER again. The game applies it and reboots. Take the stick out.",
    "Scores, audits and settings are kept. What happened is written to padmodes_install.log on the stick.",
)
#: the line every stick runme.sh starts its log with (mkjjpmodes.RUNME_SH)
_STICK_MARK = "PAD custom modes stick"


def runtime_path(iso):
    """Where the runtime built from *iso* is kept: one per stock ISO and per jjpmodes.c, so a
    changed runtime source or a different ISO builds again and nothing stale is installed."""
    import hashlib
    st = os.stat(iso)
    h = hashlib.sha256()
    h.update(("%s|%d|%d|" % (os.path.normcase(os.path.abspath(iso)), st.st_size, int(st.st_mtime))).encode())
    for src in ("jjpmodes.c", os.path.join("modes", "sdk", "jjp_mode.h")):    # PAD-1384: its API too
        with open(os.path.join(tools_dir(), src), "rb") as f:
            h.update(f.read())
    stem = re.sub(r"\.iso$", "", os.path.basename(iso), flags=re.I)
    return os.path.join(modes_root(), ".runtime", "%s-%s.so" % (stem, h.hexdigest()[:12]))


def runtime_args(iso, out, to_linux):
    """The mkjjpmodes.py runtime argv (as root, from the checkout root)."""
    return ["tools/jjp_emu/mkjjpmodes.py", "runtime", "--iso", to_linux(iso), "--out", to_linux(out),
            "--workdir", "/var/tmp/pad_jjpmodes_runtime"]


def removable_drives():
    """The removable drives Windows has now (USB sticks), e.g. ``["E:\\\\"]``; [] elsewhere."""
    if os.name != "nt":
        return []
    import ctypes
    k = ctypes.windll.kernel32
    out, mask = [], k.GetLogicalDrives()
    for i in range(26):
        if mask & (1 << i):
            root = "%s:\\" % chr(65 + i)
            if k.GetDriveTypeW(ctypes.c_wchar_p(root)) == 2:          # DRIVE_REMOVABLE
                out.append(root)
    return out


def stick_filesystem(path):
    """The file system of the drive *path* is on (``FAT32``, ``exFAT``, ``NTFS``), or ""."""
    if os.name != "nt" or not path:
        return ""
    import ctypes
    root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
    buf = ctypes.create_unicode_buffer(32)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(root), None, 0, None, None, None, buf, 32)
    return buf.value if ok else ""


def hotfix_on(stick):
    """What hot fix *stick* carries already: "" none, "pad" one of ours (replaced freely),
    "other" someone else's (never overwritten)."""
    hot = os.path.join(stick, "hotfix")
    if not os.path.exists(hot):
        return ""
    try:
        with open(os.path.join(hot, "runme.sh"), encoding="utf-8", errors="replace") as f:
            return "pad" if _STICK_MARK in f.read(4096) else "other"
    except OSError:
        return "other"


def write_stick(label, stick, action, so=""):
    """mkjjpmodes.py stick for *label*'s mode folder, in-process (plain files, no root).
    -> (ok, lines).  An existing hot fix of ours is replaced; anyone else's refuses."""
    import contextlib
    import io
    owner = hotfix_on(stick)
    if owner == "other":
        return False, ["refused: %s already has a hot fix that is not a modes stick - use another "
                       "stick, or delete its hotfix folder first" % stick]
    argv = ["stick", "--out", stick, "--action", action]
    if action == "install":
        argv += ["--modes", title_dir(label), "--so", so,
                 "--port", os.path.join(ports_dir(), label + ".json")]
    else:
        port = load_port(label) or {}
        game = read_title(label).get("game") or port.get("game") or ""
        argv += ["--game", game] if game else ["--any-game"]
    if owner == "pad":
        argv.append("--force")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            rc = mk().main(argv)
        except Exception as e:                              # noqa: BLE001
            print("refused: %s" % e)
            rc = 2
    return rc == 0, [ln for ln in buf.getvalue().splitlines() if ln.strip()]
