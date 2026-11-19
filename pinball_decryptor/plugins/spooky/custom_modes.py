"""Spooky custom modes in the app (PAD-1417): the Tk-free half of the Modes tab on a Spooky game.

The same mode files as on Jersey Jack (``key = value``, tools/jjp_emu/MODES.md), run inside a
retail Spooky Unity game by PAD's runtime (tools/spooky_emu/modes/unity: ``padunity.so``, which
the update's launch line preloads, and ``PadModes.dll``, which adds one Mode of ours to the
game's own mode list).  ``tools/spooky_emu/modes/mkspkmodes.py`` is the checker and the build;
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
              "halloween_78": "Halloween", "ultraman": "Ultraman"}
MAX_MODES = 24
#: the form's groups: every key of mkspkmodes.KEYS once
FORM_GROUPS = (
    ("Mode", ("name", "title", "start", "start_count", "shots", "points", "seconds", "complete",
              "complete_points")),
    ("Sounds", ("sound_start", "sound_shot", "sound_complete", "sound_end")),
    ("Screen", ("panel", "font_title", "font_value", "font_timer", "title_color", "value_color",
                "timer_color", "panel_color")),
)
TITLE_FORM = ("panel", "font_title", "font_value", "font_timer", "title_color", "value_color",
              "timer_color", "panel_color")
#: what an empty key means (PadModes.cs)
DEFAULTS = {
    "start_count": "1", "points": "1000000", "seconds": "20", "complete": "0", "complete_points": "0",
    "title_color": "ffffff", "value_color": "ffdc00", "timer_color": "ffffff", "panel_color": "000000b0",
    "panel": "middle",
}
LABELS = {
    "name": "Name", "title": "Title on the screen", "start": "Started by", "start_count": "Hits to start",
    "shots": "Scoring shots", "points": "Points a shot", "seconds": "Seconds (0: until the ball ends)",
    "complete": "Shots to complete", "complete_points": "Completion bonus",
    "sound_start": "Start sound", "sound_shot": "Shot sound", "sound_complete": "Completed sound",
    "sound_end": "End sound", "font_title": "Title font", "font_value": "Total font",
    "font_timer": "Timer font", "title_color": "Title color", "value_color": "Total color",
    "timer_color": "Timer color", "panel_color": "Panel color", "panel": "Panel place",
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
    """An update's version from its name: v2025.12.01.09.scooby -> 2025.12.01.09."""
    m = re.search(r"(\d{4}[._]\d{2}[._]\d{2}(?:[._]\d{2})?)", os.path.basename(path or ""))
    return m.group(1).replace("_", ".") if m else ""


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
    return collections.OrderedDict((k, v) for _n, k, v in mk().MJ.parse_cfg(text))


def write_cfg(path, values, header=""):
    """``key = value`` lines in the runtime's key order (unknown keys kept, after), empty ones
    left out, LF line ends (the machine is Linux)."""
    keys = list(mk().TITLE_KEYS) + list(mk().KEYS)
    order = [k for k in keys if k in values] + [k for k in values if k not in keys]
    lines = ["# " + header] if header else []
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
    if kind == "lamps":
        return list(port.get("lamps") or ())
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
    """The extract's file for callout *name*: its clip's name is the last part of its path."""
    if not name or not index:
        return ""
    path = ((port or {}).get("sound_paths") or {}).get(name) or name
    return index.get(path.rsplit("/", 1)[-1].lower(), "") or index.get(name.lower(), "")


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
    note = ("The game runs the modes from its first start after the update."
            if (p.get("load") or "preload") == "dllmap" else
            "The game restarts once by itself on its first start after the update, to take up the modes.")
    if p.get("update_container") == "gpg_signed":
        note += " The machine asks before it installs it: the app signs it, not Spooky."
    return note


def default_out(stock, folder):
    """The new update: the stock one's own name (the machine reads an update by its name) in a
    folder of its own - never beside the stock one, never in the image library."""
    if not stock:
        return ""
    return os.path.join(folder, "PAD modes", os.path.basename(stock))


def stage_try(label, base):
    """The Try it folder (the runtime + the modes as the update's pad/ holds them) -> its path."""
    return mk().stage(title_dir(label), os.path.join(base, label, "pad"), load_port(label))


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
    for line in seen:
        ver = version_of(line + ".x")
        if ver and load_port("%s-%s" % (game, ver)):
            return "%s-%s" % (game, ver)
    for lb in labels_of(game):
        if set(seen) & set((load_port(lb) or {}).get("version_match") or ()):
            return lb
    return ""


def write_pad_modes(label, folder=None):
    """The person's modes for *label* as the Write tab packs them -> ``(files, rewrite, pad)``
    for formats.create_tar_gz (*pad*: where pad/ goes, beside the extract's main.x86_64), None
    when they have none; ValueError with the check's problems."""
    d = title_dir(label, seed=False)
    if not os.path.isdir(d) or not any(f.endswith(".mode") for f in os.listdir(d)):
        return None
    m = mk()
    port = load_port(label)
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
    return files, rewrite, pad
