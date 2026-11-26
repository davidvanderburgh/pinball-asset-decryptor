"""Spooky custom modes in the app (PAD-1417): the Tk-free half of the Modes tab on a Spooky game.

The same mode files as on Jersey Jack (``key = value``, tools/jjp_emu/MODES.md), run inside a
retail Spooky game by PAD's runtime: on the Unity titles tools/spooky_emu/modes/unity
(``padunity.so``, which the update's launch line preloads, and ``PadModes.dll``, which adds one
Mode of ours to the game's own mode list); on Looney Tunes (Godot, PAD-1419)
tools/spooky_emu/modes/godot (``pad_modes.gd``, one more autoload that an ``override.cfg``
beside main.x86_64 names); on Rick and Morty (P-ROC, PAD-1420) tools/spooky_emu/modes/proc
(``padmodes_proc.py``, a package ``pad/`` in the game's folder that one line of its config.yaml
loads as procgame's board class); on the pinHeck DMD games (Jetsons, Domino's, Rob Zombie;
PAD-1422, PAD-1423) tools/spooky_emu/modes/pinheck (compiled into the game's own PRG, the modes
packed after it).  ``tools/spooky_emu/modes/mkspkmodes.py`` is the checker and the build;
this module is what the tab needs on top of it:

* the titles - every port report in ``tools/spooky_emu/modes/ports`` (``titles()``): the game's
  switches, lights, callouts, fonts and modes, read from the running game by the runtime;
* the selected card's title (``label_for_card``: its game by the update's name, its version);
* a mode folder per title in the app's settings folder (``spooky_modes``), seeded from the
  title's starter folder (``modes/examples/<label>``) the first time;
* reading and writing one mode as fields, new / duplicate / delete; the checker in-process;
* the stock update in the library and where the new one goes; the build and the Try it folder.
"""
import collections
import importlib.util
import os
import re
import shutil

#: the title names, by the plugin's game key
GAME_NAMES = {"scooby_doo": "Scooby-Doo", "beetlejuice": "Beetlejuice",
              "texas_chainsaw": "Texas Chainsaw Massacre", "evil_dead": "Evil Dead",
              "halloween_78": "Halloween", "ultraman": "Ultraman", "legends_of_tera": "Looney Tunes",
              "rick_and_morty": "Rick and Morty", "alice_cooper": "Alice Cooper's Nightmare Castle",
              "jetsons": "Jetsons", "dominos": "Domino's Spectacular Pinball Adventure",
              "rob_zombie": "Rob Zombie's Spookshow International"}
MAX_MODES = 24
#: the form's groups: every key of mkspkmodes.KEYS once
FORM_GROUPS = (
    ("Mode", ("name", "title", "start", "start_count", "shots", "points", "seconds", "complete",
              "complete_points")),
    # PAD-1424: JJP's start rules, lamps, balls and coils (the JJP form's groups)
    ("Starts", ("start_hold", "start_on", "start_after", "start_score", "start_combo", "combo_seconds",
                "start_count_reset", "start_once")),
    ("Sounds", ("sound_start", "sound_shot", "sound_complete", "sound_end", "sound_channel", "music")),
    ("Picture and video", ("picture", "picture_at", "video", "video_at", "video_loop")),
    ("Lamps", ("lamps", "lamp_color", "lamp_blink")),
    ("Screen", ("panel", "font_title", "font_value", "font_timer", "title_color", "value_color",
                "timer_color", "panel_color")),
    ("Balls", ("multiball", "multiball_on", "add_ball", "ball_save")),
    ("Coils", ("coil_start", "coil_shot", "coil_complete", "coil_hold", "coil_hold_on")),
    # PAD-1508: Spike 2's rules (tools/jjp_emu/MODES.md "Spike 2's rules")
    ("Rules from Spike 2", ("shot_points", "points_ladder", "end_shots", "penalty", "start_also", "start_max",
                            "cooldown", "start_needs", "sound_at", "sound_shot_every", "lamp_pattern",
                            "inside", "in_place_of")),
)
TITLE_FORM = ("panel", "font_title", "font_value", "font_timer", "title_color", "value_color",
              "timer_color", "panel_color", "lamp_color", "lamp_blink", "coil_holds")


def screen_keys_out(port):
    """The form's keys this title cannot do: Alice Cooper's Unity player draws the game's own text
    in its one font with no box behind it (mkspkmodes.UNITY_SCREEN_NOT) and shows no picture or
    video of the mode's own (PAD-1424: the player loads the game's by name); a pinHeck title's
    runtime has no fonts or colours of its own and does not run PAD-1424's keys yet
    (mkspkmodes.keys_not_here)."""
    out = set(mk().keys_not_here(port))
    if (port or {}).get("screen") == "unity_player":
        out |= set(mk().UNITY_SCREEN_NOT) | {"picture", "picture_at", "video", "video_at", "video_loop"}
    return out


def form_groups(port=None):
    """FORM_GROUPS without the keys *port*'s screen cannot show (a group left empty goes)."""
    out = screen_keys_out(port)
    groups = ((g, tuple(k for k in ks if k not in out)) for g, ks in FORM_GROUPS)
    return tuple(g for g in groups if g[1])


def title_form(port=None):
    out = screen_keys_out(port)
    return tuple(k for k in TITLE_FORM if k not in out)


#: what an empty key means (PadModes.cs)
DEFAULTS = {
    "start_count": "1", "points": "1000000", "seconds": "20", "complete": "0", "complete_points": "0",
    "title_color": "ffffff", "value_color": "ffdc00", "timer_color": "ffffff", "panel_color": "000000b0",
    "panel": "middle", "sound_channel": "fanfare", "picture_at": "0 0 100 100", "video_at": "0 0 100 100",
    "video_loop": "yes", "lamp_color": "ffffff", "lamp_blink": "4", "coil_hold_on": "shots", "coil_holds": "off",
    "combo_seconds": "5", "start_count_reset": "game", "start_once": "no",
    "start_hold": "no",
    "points_ladder": "fixed",
}
LABELS = {
    "name": "Name", "title": "Title on the screen", "start": "Started by", "start_count": "Hits to start",
    "shots": "Scoring shots", "points": "Points a shot", "seconds": "Seconds (0: until the ball ends)",
    "complete": "Shots to complete", "complete_points": "Completion bonus",
    "sound_start": "Start sound", "sound_shot": "Shot sound", "sound_complete": "Completed sound",
    "sound_end": "End sound", "font_title": "Title font", "font_value": "Total font",
    "font_timer": "Timer font", "title_color": "Title color", "value_color": "Total color",
    "timer_color": "Timer color", "panel_color": "Panel color", "panel": "Panel place",
    "lamps": "Lamps", "lamp_color": "Lamp color", "lamp_blink": "Flashes a second",
    "multiball": "Multiball", "multiball_on": "Multiball balls come on",
    "add_ball": "Add a ball on", "ball_save": "Ball save",
    "coil_start": "Coil at the start", "coil_shot": "Coil on each shot",
    "coil_complete": "Coil on completion", "coil_hold": "Hold a coil",
    "coil_hold_on": "Hold it on", "coil_holds": "Coil holds on this title",
    "start_on": "Starts on a game event", "start_after": "Starts after a game mode ends",
    "start_score": "Starts at a score", "start_combo": "Starts on a combo (in order)",
    "combo_seconds": "Combo seconds between shots", "start_count_reset": "Start count resets every",
    "start_once": "Starts at most once a",
    # PAD-1623: Halloween, Ultraman
    "start_hold": "A challenge of its own (hold Start)",
    "sound_channel": "Channel for our sound files", "music": "Music (a file of ours)",
    "picture": "Picture (a file of ours)", "picture_at": "Picture box (x y w h, % of screen)",
    "video": "Video (a file of ours)", "video_at": "Video box (x y w h, % of screen)", "video_loop": "Video loops",
    # PAD-1508
    "shot_points": "Points per shot (one a line: switches points)", "points_ladder": "Each shot pays",
    "end_shots": "Shots that end it", "penalty": "Shots that take points (one a line: switches points)",
    "start_also": "Also needed to start (one a line: switches [hits])", "start_max": "Starts at most, a game",
    "cooldown": "Seconds before it can start again", "start_needs": "Only after my mode (name [ball|game])",
    "sound_at": "Sounds at seconds left (one a line: seconds sound)", "sound_shot_every": "Shot sound every Nth shot",
    "lamp_pattern": "Lamp pattern",
    "in_place_of": "Starts in place of the game's mode", "inside": "Runs inside my mode (name)",
}


# ============================================================================ where things are
def tools_dir():
    """tools/spooky_emu/modes, from this file (a checkout or the installed app alike)."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "tools", "spooky_emu", "modes")


def ports_dir():
    return os.path.join(tools_dir(), "ports")


def examples_dir():
    return os.path.join(tools_dir(), "examples")


def modes_root():
    """The person's mode folders, one per title: the settings folder's ``spooky_modes``
    (PAD_SPOOKY_MODES_DIR moves it - the tests)."""
    env = os.environ.get("PAD_SPOOKY_MODES_DIR")
    if env:
        return env
    from ...core import config
    return os.path.join(os.path.dirname(config.SETTINGS_FILE), "spooky_modes")


_MK = None


def mk():
    """mkspkmodes.py as a module: the tab and the build never disagree about a mode file."""
    global _MK
    path = os.path.join(tools_dir(), "mkspkmodes.py")
    if _MK is None or getattr(_MK, "__file__", None) != path:
        spec = importlib.util.spec_from_file_location("pad_mkspkmodes", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _MK = mod
    return _MK


# ============================================================================ titles
_PORTS = {}


def load_port(label):
    p = os.path.join(ports_dir(), (label or "") + ".json")
    try:
        st = os.stat(p).st_mtime
    except OSError:
        return None
    hit = _PORTS.get(p)
    if hit and hit[0] == st:
        return hit[1]
    import json
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    _PORTS[p] = (st, data)
    return data


def display_name(label, port=None):
    port = port or load_port(label) or {}
    game = port.get("game") or label.split("-")[0]
    name = port.get("title") or GAME_NAMES.get(game) or game
    ver = port.get("version") or ""
    return "%s %s" % (name, ver) if ver else name


def titles():
    """[{label, name, game, can_run, why, counts}] for every port report, runnable first."""
    out = []
    d = ports_dir()
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else ():
        if not fn.endswith(".json"):
            continue
        label = fn[:-5]
        try:
            p = load_port(label)
        except (OSError, ValueError):
            continue
        if not p:
            continue
        why = ""
        try:
            mk().runtime_files(p)
        except Exception as e:                              # noqa: BLE001 - its reason is the why
            why = str(e)
        out.append({"label": label, "name": display_name(label, p), "game": p.get("game", ""),
                    "can_run": not why, "why": why,
                    "counts": {k: len(p.get(k) or ()) for k in ("switches", "lamps", "sounds", "fonts", "game_modes")}})
    out.sort(key=lambda t: (not t["can_run"], t["name"].lower()))
    return out


def version_of(path):
    """An update's version from its name: v2025.12.01.09.scooby -> 2025.12.01.09; a P-ROC game
    code's date, rm-gamecode-20220902.pkg -> 2022.09.02."""
    base = os.path.basename(path or "")
    m = re.search(r"(\d{4}[._]\d{2}[._]\d{2}(?:[._]\d{2})?)", base)
    if m:
        return m.group(1).replace("_", ".")
    m = re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", base)
    return "%s.%s.%s" % m.groups() if m else ""


def game_of(path):
    """The plugin's game key for an update file, or ""."""
    try:
        from .formats import detect_game
        g = detect_game(path)
    except Exception:                                       # noqa: BLE001
        return ""
    return getattr(g, "game_key", "") or ""


def labels_of(game):
    """Every port report's label for *game*."""
    d = ports_dir()
    pre = (game or "") + "-"
    return sorted(fn[:-5] for fn in (os.listdir(d) if os.path.isdir(d) else ())
                  if fn.endswith(".json") and fn.startswith(pre))


def label_for_card(path):
    """The port report the selected update is (its game and version), or "".  Texas Chainsaw's,
    Halloween's and Ultraman's update names carry no date (tcm-1_00.pkg, code_H78.pkg): the port
    whose stock update is that name and size, else the game's only port."""
    path = (path or "").strip()
    if not path or not os.path.isfile(path):
        return ""
    game, ver = game_of(path), version_of(path)
    if not game:
        return ""
    label = "%s-%s" % (game, ver)
    if ver and load_port(label):
        return label
    if ver:
        return ""
    labels = labels_of(game)
    size = os.path.getsize(path)
    for lb in labels:
        p = load_port(lb) or {}
        if p.get("update_name") == os.path.basename(path) and int(p.get("update_size") or 0) == size:
            return lb
    return labels[0] if len(labels) == 1 else ""


# ============================================================================ a title's folder
def title_dir(label, seed=True):
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
                      "%s - defaults for every mode in this folder" % label)
    return d


def read_cfg(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return collections.OrderedDict()
    out = collections.OrderedDict()
    rep = getattr(mk(), "REPEATABLE", {})
    for _n, k, v in mk().MJ.parse_cfg(text):
        out[k] = out[k] + "\n" + v if k in rep and out.get(k) else v   # PAD-1508: every line of a repeated key
    return out


def write_cfg(path, values, header=""):
    """``key = value`` lines in the runtime's key order (unknown keys kept, after), empty ones
    left out, LF line ends (the machine is Linux)."""
    keys = list(mk().TITLE_KEYS) + list(mk().KEYS)
    order = [k for k in keys if k in values] + [k for k in values if k not in keys]
    lines = ["# " + header] if header else []
    for k in order:
        v = str(values.get(k) if values.get(k) is not None else "").strip()
        for one in v.splitlines():            # a repeated key (PAD-1508): a line each
            if one.strip():
                lines.append("%s = %s" % (k, one.strip()))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


def mode_files(label):
    d = title_dir(label)
    return sorted(f for f in os.listdir(d) if f.endswith(".mode"))


def list_modes(label):
    """[{file, name, start, starts, kind}] in the runtime's load order (file name)."""
    d = title_dir(label)
    out = []
    for fn in mode_files(label):
        v = read_cfg(os.path.join(d, fn))
        out.append({"file": fn, "name": v.get("name") or fn[:-5], "start": v.get("start", ""),
                    "starts": mk().start_text(v), "kind": "form", "code": ""})
    return out


def _safe(fn):
    fn = os.path.basename(fn or "")
    if not fn.endswith(".mode") or fn.startswith("."):
        raise ValueError("not a mode file: %r" % fn)
    return fn


def read_mode(label, fn):
    return read_cfg(os.path.join(title_dir(label), _safe(fn)))


def write_mode(label, fn, values):
    write_cfg(os.path.join(title_dir(label), _safe(fn)), values,
              "%s - made in the app's Modes tab" % (values.get("name") or fn))


def read_title(label):
    return read_cfg(os.path.join(title_dir(label), "title.cfg"))


def write_title(label, values):
    p = load_port(label) or {}
    values = collections.OrderedDict(values)
    if p.get("game"):
        values["game"] = p["game"]
    write_cfg(os.path.join(title_dir(label), "title.cfg"), values,
              "%s - defaults for every mode in this folder" % label)


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
    """A new mode with the title's starter picks (its port report's ``defaults``) -> its file."""
    if how != "form":
        raise ValueError("on a Spooky game a mode is made with the form")
    if len(mode_files(label)) >= MAX_MODES:
        raise ValueError("a title takes %d modes; delete one first" % MAX_MODES)
    d = (load_port(label) or {}).get("defaults") or {}
    v = collections.OrderedDict([("name", name), ("title", name.upper()), ("start", d.get("start", "")),
                                 ("shots", d.get("shots", "")), ("points", "1000000"), ("seconds", "20"),
                                 ("complete", "5"), ("complete_points", "5000000")])
    for k in ("sound_start", "sound_shot", "sound_complete", "sound_end"):
        if d.get(k):
            v[k] = d[k]
    fn = _next_file(label, name)
    write_mode(label, fn, v)
    return fn


def duplicate_mode(label, fn):
    if len(mode_files(label)) >= MAX_MODES:
        raise ValueError("a title takes %d modes; delete one first" % MAX_MODES)
    v = read_mode(label, fn)
    v["name"] = (v.get("name") or fn[:-5]) + " copy"
    new = _next_file(label, v["name"])
    write_mode(label, new, v)
    return new


def delete_mode(label, fn):
    os.unlink(os.path.join(title_dir(label), _safe(fn)))


def check(label):
    return mk().check_modes(title_dir(label), load_port(label))


def is_pinheck(label):
    return mk().engine(load_port(label) or {}) == "pinheck"


def key_kind(key):
    m = mk()
    return m.KEYS.get(key) or m.TITLE_KEYS.get(key)


def names_for(port, kind, folder=None):
    if kind == "switches":
        return list(port.get("switches") or ())
    if kind == "sound":
        return list(port.get("sounds") or ())
    if kind == "font":
        return list(port.get("fonts") or ())
    if kind == "lamps":                 # one word each (mkspkmodes.token): a mode line is a list
        return [mk().token(n) for n in port.get("lamps") or ()]
    if kind == "coil_pulse":
        return [mk().token(n) for n in port.get("coils") or ()]
    if kind == "coil_hold":
        return [mk().token(n) for n in port.get("coil_holds") or ()]
    if kind in ("sound_file", "picture_file", "video_file"):
        exts = mk().media_exts(port, kind)
        try:
            return sorted(f for f in os.listdir(folder or "") if f.rsplit(".", 1)[-1].lower() in exts)
        except OSError:
            return []
    if kind == "sound_or_file":
        return names_for(port, "sound_file", folder) + list(port.get("sounds") or ())
    if kind == "events":
        return [e for e in mk().MJ.START_EVENTS if e in (port.get("start_events") or mk().MJ.START_EVENTS)]
    if kind == "after":
        seen = ["any"]
        for n in list(port.get("game_modes") or ()) + list(port.get("mode_classes") or ()):
            if n not in seen:
                seen.append(n)
        return seen
    return []


# ============================================================================ sounds to hear
_SND = {}


def sound_index(folder):
    """{stem lower: path} of every .wav / .ogg under an extract folder (cached by the folder's
    mtime): a callout is the clip its Resources path names, extracted under its own name."""
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


def sound_file(index, name, port=None):
    """The extract's file for callout *name*: its clip's name is the last part of its path (a
    Unity Resources path has no extension, a Godot res:// path has: .wav, .ogg)."""
    if not name or not index:
        return ""
    path = ((port or {}).get("sound_paths") or {}).get(name) or name
    last = path.rsplit("/", 1)[-1]
    stem, ext = os.path.splitext(last)
    if ext.lower() not in (".wav", ".ogg"):
        stem = last
    return index.get(stem.lower(), "") or index.get(name.lower(), "")


# ============================================================================ the build
LIBRARY = r"D:\Pinball\images\Spooky"


def find_stock(label, folders):
    """The title's stock update in *folders* (the selected card's folder, the library): the file
    whose name is this game and version, without PAD's modes in it."""
    p = load_port(label) or {}
    ext = p.get("update_ext") or ""
    want = p.get("version") or ""
    name, size = p.get("update_name") or "", int(p.get("update_size") or 0)
    for d in folders:
        if not d or not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if ext and not fn.lower().endswith(ext):
                continue
            # a dateless name (code_H78.pkg) is the stock one only at the stock size
            if name and fn == name and (not size or os.path.getsize(os.path.join(d, fn)) == size):
                return os.path.join(d, fn)
            if version_of(fn) and version_of(fn) == want:
                return os.path.join(d, fn)
    return ""


def install_note(label):
    """What installing a modes update does on this title's machine (the Build card says it)."""
    p = load_port(label) or {}
    if mk().engine(p) == "pinheck":
        return ("Install it the way a stock update goes on: unzip it onto the game's SD card, then in "
                "the service menu choose UPDATE CODE and restart. The machine flashes the new program, "
                "with the modes in it, into the game. To take them out, put the stock update on the card "
                "and choose UPDATE CODE again.")
    note = "Install it the way a stock update installs: on a USB stick, under its own name. "
    if mk().engine(p) == "godot":
        note += ("The machine puts it in place when it next powers up, and the modes are in the game "
                 "from that start. To take them out, install the stock update again.")
    elif mk().engine(p) == "proc":
        note += ("The modes are in the game from its first start after the update. To take them out, "
                 "install the stock update again.")
    elif mk().load_of(p) == "dllmap":
        note += "The game runs the modes from its first start after the update."
    else:
        note += "The game restarts once by itself on its first start after the update, to take up the modes."
    if p.get("update_container") == "gpg_signed":
        note += " The machine asks before it installs it: the app signs it, not Spooky."
    return note


def default_out(stock, folder):
    """The new update: the stock one's own name (the machine reads an update by its name) in a
    folder of its own - never beside the stock one, never in the image library."""
    if not stock:
        return ""
    return os.path.join(folder, "PAD modes", os.path.basename(stock))


def stage_try(label, base, stock=None):
    """The Try it folder (the runtime + the modes as the update's pad/ holds them) -> its path;
    on a pinHeck title the modes PRG made from *stock* (the update zip) -> that file's path."""
    return mk().stage(title_dir(label), os.path.join(base, label, "pad"), load_port(label), stock)


# ============================================================================ Write (the Write tab)
def label_for_extract(folder, meta=None):
    """The port report an extract folder is (its .spooky_meta's game, its version.txt), or ""."""
    if meta is None:
        try:
            import json
            with open(os.path.join(folder, ".spooky_meta"), encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            return ""
    game = next((k for k, v in GAME_NAMES.items() if v == (meta or {}).get("game")), "")
    if not game:
        return ""
    # a pinHeck card (Jetsons): its program's name is the build (JET_V004.PRG)
    for lb in labels_of(game):
        prg = ((load_port(lb) or {}).get("prg") or "").upper()
        if prg and _find_prg(folder, prg + ".PRG"):
            return lb
    # what the extract says its version is: version.txt's first line (Scooby-Doo, Beetlejuice,
    # Evil Dead, Texas Chainsaw's "TCM V1.00"), or uptest/version_<n>.txt's name (Halloween, Ultraman)
    seen = []
    for vt in (os.path.join(folder, "version.txt"), os.path.join(folder, "uptest", "version.txt")):
        try:
            with open(vt, encoding="utf-8", errors="replace") as f:
                seen.append(f.readline().strip())
        except OSError:
            continue
    up = os.path.join(folder, "uptest")
    if os.path.isdir(up):
        seen += [fn for fn in sorted(os.listdir(up)) if fn.startswith("version_") and fn.endswith(".txt")]
    # a P-ROC game code has no version file: its date is in the update's name (the extract's source)
    seen.append((meta or {}).get("source") or "")
    for line in seen:
        ver = version_of(line + ".x")
        if ver and load_port("%s-%s" % (game, ver)):
            return "%s-%s" % (game, ver)
    for lb in labels_of(game):
        if set(seen) & set((load_port(lb) or {}).get("version_match") or ()):
            return lb
    return ""


def _find_prg(folder, name):
    """*name* (a PRG) in an extract folder or one level down (Jetsons/JET_V004.PRG), or ""."""
    for d in (folder, *(os.path.join(folder, x) for x in sorted(os.listdir(folder))
                        if os.path.isdir(os.path.join(folder, x)))) if os.path.isdir(folder) else ():
        for fn in os.listdir(d):
            if fn.upper() == name:
                return os.path.join(d, fn)
    return ""


def write_pad_modes(label, folder=None):
    """The person's modes for *label* as the Write tab packs them -> ``(files, rewrite, pad, top)``
    for formats.create_tar_gz / create_tar (*pad*: where pad/ goes, beside the extract's
    main.x86_64; ``top``: files beside main.x86_64, Godot's override.cfg), None when they have
    none; ValueError with the check's problems."""
    d = title_dir(label, seed=False)
    if not os.path.isdir(d) or not any(f.endswith(".mode") for f in os.listdir(d)):
        return None
    m = mk()
    port = load_port(label)
    if m.engine(port) == "pinheck":
        # the update is the card again with its PRG the modes PRG: no pad/ folder, one rewrite
        modes, problems = m.check_modes(d, port)
        if problems:
            raise ValueError("the modes have problems:\n  " + "\n  ".join(problems))
        want = port["prg"].upper() + ".PRG"

        def rewrite_prg(rel, data):
            if rel.replace("\\", "/").rsplit("/", 1)[-1].upper() != want:
                return data
            try:
                return m.build_prg_of(data, modes, port)
            except m.Refused as e:
                raise ValueError(str(e))
        rewrite_prg.names = {want}
        rewrite_prg.modes = len(modes)
        return [], rewrite_prg, None, []
    try:
        files = m.pad_files(d, port)
    except m.Refused as e:
        raise ValueError(str(e))

    def rewrite(rel, data):
        return m.patch_file(rel, data, port)[0]
    rewrite.names = m.patched_names(port)
    pad = m.PAD_DIR
    if folder and os.path.isfile(os.path.join(folder, "uptest", "main.x86_64")):
        pad = "uptest/" + m.PAD_DIR
    return files, rewrite, pad, m.top_files(port)


def loads_how(label):
    """How the update PAD writes loads the runtime, for the Write log."""
    port = load_port(label)
    if mk().engine(port) == "pinheck":
        return "the game's program (%s.PRG) carries it" % port.get("prg", "")
    if mk().engine(port) == "godot":
        return "an override.cfg beside the game loads it"
    if mk().engine(port) == "proc":
        return "a line in the game's config.yaml loads it"
    if mk().load_of(port) == "dllmap":
        return "the game's Mono config loads it"
    return "the game's launch line preloads it"
