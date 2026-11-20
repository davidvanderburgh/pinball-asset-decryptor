#!/usr/bin/env python3
"""mkspkmodes.py - custom modes on Spooky's Unity and Godot titles (PAD-1417, PAD-1418, PAD-1419;
docs/plans/spooky_modes.md).

A mode is the same ``key = value`` file as on JJP (tools/jjp_emu/MODES.md); a title's modes are
one folder of them (``title.cfg`` + ``*.mode``).  The runtime is the port report's ``engine``:

  unity  ``padunity.so`` (preloaded by the update's launch line) + ``PadModes.dll`` (built against
         the title's own Managed/, runs the modes through the game's own Mode, scoring and
         callouts): tools/spooky_emu/modes/unity.
  godot  ``pad_modes.gd`` (Looney Tunes): one more autoload, named by an ``override.cfg`` beside
         main.x86_64, running the modes through the game's own Game.score and Audio:
         tools/spooky_emu/modes/godot.
  pinheck  ``padheck_<PRG>.bin`` (Jetsons, PAD-1422): compiled MIPS linked into the free flash of
         the game's own ``<GAME>_Vnnn.PRG``, the modes packed after it as data, one call in the
         game re-pointed at it: tools/spooky_emu/modes/pinheck.  The update is the stock zip with
         its PRG replaced; Try it is that PRG in the pinHeck emulator on the stock card.

How the runtime gets into the game is the port report's ``load``:

  preload  (Scooby-Doo) the update's launch lines (sway_config, i3_config) start main.x86_64 with
           LD_PRELOAD=pad/padunity.so; the game copies them into the system at its next start
  dllmap   (Beetlejuice, Texas Chainsaw, Evil Dead, Halloween, Ultraman: their updates carry no
           launch line) the update's own Mono config (main_Data/MonoBleedingEdge/etc/mono/config)
           maps MonoPosixHelper, the library the game's serial port loads, to pad/padunity.so (the
           dllmap build of the loader, which needs the real one beside it); Mono loads it when the
           game opens its board, and its loader starts the runtime as the preload does

and its ``update_container`` what the update file is around its tar.gz: ``tar.gz`` (Scooby-Doo,
Texas Chainsaw, Evil Dead), ``gpg_signed`` (Beetlejuice: signed again with PAD's own key, as Write
does, so the machine asks before it takes it) or ``gpg_symmetric`` (Halloween, Ultraman: encrypted
again with the game's own passphrase, ``gpg_format``).

  check <mode dir> --port <port.json>            the folder as the runtime will read it
  stage <mode dir> <pad dir> --port <port.json>  the update's pad/ folder (the rig's Try it)
  build <stock update> <mode dir> <new update> --port <port.json>
                                                 the stock update again, with pad/ in it and
                                                 its launch lines preloading the runtime (or
                                                 its override.cfg loading it)
  port <raw port.json> --label <label> --title <name> --ext <.ext> [--defaults <mode>] --out <json>
                                                 the runtime's own report (PADMODES_PORT) made
                                                 into the shipped port report

Only the keys in KEYS run on Spooky today; any other JJP key is refused by name ("not on
Spooky games yet"), never silently ignored.  The game multiplies every award by its points
scale and rounds it (Scooby-Doo: x10, to 100): the port report says so, the build writes the
scale into title.cfg for the runtime, and points the game would round are refused here.
"""
import argparse
import collections
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
UNITY = os.path.join(HERE, "unity")
GODOT = os.path.join(HERE, "godot")
PINHECK = os.path.join(HERE, "pinheck")
PREBUILT = os.path.join(UNITY, "prebuilt")
PORTS = os.path.join(HERE, "ports")
#: where the runtime sits in the update (and so in /game/code/uptest on the machine)
PAD_DIR = "pad"
RUNTIME_SO = "/game/code/uptest/pad/padunity.so"
#: Godot: the autoload override.cfg (beside main.x86_64, read by the engine at start) adds
RUNTIME_GD = "/game/code/uptest/pad/pad_modes.gd"
OVERRIDE_CFG = "override.cfg"
OVERRIDE_TEXT = '[autoload]\n\nPadModes="*%s"\n' % RUNTIME_GD
#: the files whose ``exec ... main.x86_64`` line starts the game (sway on 6.1 kernels, i3 on 5.10)
LAUNCH_FILES = ("sway_config", "i3_config")
#: the update's Mono config (under its uptest/ on the titles laid out that way); dllmap titles
MONO_CONFIG = "main_Data/MonoBleedingEdge/etc/mono/config"
_DLLMAP = re.compile(r'(<dllmap\s+dll="MonoPosixHelper"\s+target=")([^"]*)(")')
_LAUNCH = re.compile(r"^(\s*exec\s+(?:--no-startup-id\s+)?)((?:env\s+(?:\S+=\S*\s+)*)?)(\S*main\.x86_64)(.*)$")
MAX_MODES = 24


class Refused(Exception):
    pass


def _jjp():
    """tools/jjp_emu/mkjjpmodes.py: the mode file's grammar and value checks are shared."""
    path = os.path.join(os.path.dirname(os.path.dirname(HERE)), "jjp_emu", "mkjjpmodes.py")
    spec = importlib.util.spec_from_file_location("pad_mkjjpmodes_for_spooky", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MJ = _jjp()

#: the keys PadModes.cs takes, and their kinds (MJ.check_value's)
KEYS = collections.OrderedDict([
    ("name", "text"), ("title", "text"), ("start", "switches"), ("start_count", "int"),
    ("shots", "switches"), ("points", "int"), ("seconds", "int"), ("complete", "int"),
    ("complete_points", "int"),
    ("sound_start", "sound"), ("sound_shot", "sound"), ("sound_complete", "sound"), ("sound_end", "sound"),
    ("font_title", "font"), ("font_value", "font"), ("font_timer", "font"),
    ("title_color", "rgba"), ("value_color", "rgba"), ("timer_color", "rgba"), ("panel_color", "rgba"),
    ("panel", ("middle", "bottom", "top", "none")),
])
#: title.cfg: every mode's defaults (the panel), and the title it is for
TITLE_KEYS = collections.OrderedDict([("game", "text")])
#: what the build writes into the staged title.cfg (never the person's)
BUILD_TITLE_KEYS = ("points_scale",)
#: JJP keys the Spooky runtime does not run yet (docs/plans/spooky_modes.md ticket 8)
NOT_YET = tuple(k for k in MJ.KEYS if k not in KEYS)


# ============================================================================ ports
def ports():
    """{label: port} for every port report shipped."""
    out = {}
    for fn in sorted(os.listdir(PORTS)) if os.path.isdir(PORTS) else ():
        if fn.endswith(".json"):
            with open(os.path.join(PORTS, fn), encoding="utf-8") as f:
                out[fn[:-5]] = json.load(f)
    return out


def load_port(path_or_label):
    p = path_or_label if os.path.isfile(path_or_label) else os.path.join(PORTS, path_or_label + ".json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def engine(port):
    return (port or {}).get("engine") or "unity"


_PH = []


def ph():
    """tools/spooky_emu/modes/pinheck/pinheck.py (the pinHeck PRG build), loaded once."""
    if not _PH:
        spec = importlib.util.spec_from_file_location("pad_pinheck_build", os.path.join(PINHECK, "pinheck.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _PH.append(mod)
    return _PH[0]


def load_of(port):
    """How the runtime gets into a Unity title's game: "preload" or "dllmap" (module doc)."""
    return (port or {}).get("load") or "preload"


def runtime_files(port):
    """The runtime's files the title runs - (padunity.so, PadModes.dll) on Unity (a dllmap title's
    padunity.so is the dllmap build of the loader, unity/build.sh), (pad_modes.gd,) on Godot - or
    Refused."""
    if engine(port) == "pinheck":
        b = ph().runtime_path(port.get("prg") or "?")
        if not os.path.isfile(b):
            raise Refused("no mode runtime built for %s (%s)" % (port.get("title", "this title"), b))
        return (b,)
    if engine(port) == "godot":
        gd = os.path.join(GODOT, "pad_modes.gd")
        if not os.path.isfile(gd):
            raise Refused("no mode runtime for %s (%s)" % (port.get("title", "this title"), gd))
        return (gd,)
    if engine(port) != "unity":
        raise Refused("no mode runtime for %s's engine (%s) yet" % (port.get("title", "this title"), engine(port)))
    so = os.path.join(PREBUILT, "padunity_dllmap.so" if load_of(port) == "dllmap" else "padunity.so")
    dll = os.path.join(PREBUILT, port.get("runtime_dll") or "")
    for p in (so, dll):
        if not port.get("runtime_dll") or not os.path.isfile(p):
            raise Refused("no mode runtime built for %s (%s)" % (port.get("title", "this title"), p))
    return so, dll


# ============================================================================ check
def _int(v):
    return int(v.replace(",", "").replace("_", "")) if MJ._INT.match(v or "") else None


def _not_here(k, port):
    """A key the title's runtime cannot do (a pinHeck DMD: no fonts, no colours), or None."""
    if k in ((port or {}).get("keys_not_here") or ()):
        return ("%s is not on %s: its panel is the game's own text on the DMD, in the game's font "
                "and colour" % (k, port.get("title", "this game")))
    return None


def check_value(kind, v, port):
    if kind == "sound":
        known = set(port.get("sounds") or ()) if port else set()
        if known and v not in known:
            return "not one of %s's sounds (its callouts): %s" % (port.get("title", "this game"), v)
        return None
    return MJ.check_value(kind, v, port)


def check_modes(mode_dir, port=None):
    """-> (modes, problems), as the runtime will read the folder."""
    problems, modes = [], []
    if not os.path.isdir(mode_dir):
        raise Refused("%s is not a folder" % mode_dir)
    title_name = (port or {}).get("title", "this game")
    title = {}
    tpath = os.path.join(mode_dir, "title.cfg")
    if os.path.isfile(tpath):
        with open(tpath, encoding="utf-8", errors="replace") as f:
            for n, k, v in MJ.parse_cfg(f.read()):
                kind = TITLE_KEYS.get(k) or KEYS.get(k)
                if _not_here(k, port):
                    problems.append("title.cfg:%d: %s" % (n, _not_here(k, port)))
                    continue
                if k in BUILD_TITLE_KEYS:
                    problems.append("title.cfg:%d: %s is the game's own (its port report says it); take "
                                    "the line out" % (n, k))
                    continue
                if kind is None:
                    problems.append("title.cfg:%d: %s" % (n, _unknown(k)))
                    continue
                p = check_value(kind, v, port)
                if p:
                    problems.append("title.cfg:%d: %s %s" % (n, k, p))
                title[k] = v
    files = sorted(f for f in os.listdir(mode_dir) if f.endswith(".mode"))
    if not files:
        problems.append("no .mode files in %s" % mode_dir)
    if len(files) > MAX_MODES:
        problems.append("%d modes: the runtime takes %d" % (len(files), MAX_MODES))
    rnd = int((port or {}).get("points_round") or 0)
    for fn in files:
        with open(os.path.join(mode_dir, fn), encoding="utf-8", errors="replace") as f:
            rows = MJ.parse_cfg(f.read())
        m = dict(title)
        for n, k, v in rows:
            if k in TITLE_KEYS:
                problems.append("%s:%d: %s belongs in title.cfg" % (fn, n, k))
                continue
            kind = KEYS.get(k)
            if kind is None:
                problems.append("%s:%d: %s" % (fn, n, _unknown(k)))
                continue
            if _not_here(k, port):
                problems.append("%s:%d: %s" % (fn, n, _not_here(k, port)))
                continue
            p = check_value(kind, v, port)
            if p:
                problems.append("%s:%d: %s %s" % (fn, n, k, p))
            m[k] = v
        m["file"] = fn
        m.setdefault("name", fn[:-5])
        if not m.get("start"):
            problems.append("%s: no start = (the switches that start it): the mode would never start" % fn)
        if engine(port) == "pinheck":
            tp = ph().title_problem(m.get("title") or m.get("name"))
            if tp:
                problems.append("%s: title %s" % (fn, tp))
        complete = _int(m.get("complete") or "0") or 0
        if complete > 0 and not m.get("shots"):
            problems.append("%s: complete = %s but no shots = (nothing can score it)" % (fn, m["complete"]))
        for k in ("points", "complete_points"):
            v = _int(m.get(k) or "")
            if rnd and v and v % rnd:
                problems.append("%s: %s = %s: %s rounds every award to %d, so it would score %s" % (
                    fn, k, m[k], title_name, rnd, format(int(round(v / float(rnd))) * rnd, ",")))
        for k in ("seconds", "start_count", "complete"):
            v = _int(m.get(k) or "")
            if v is not None and v < 0:
                problems.append("%s: %s must not be below 0" % (fn, k))
        modes.append(m)
    return modes, problems


def _unknown(k):
    if k in NOT_YET:
        return "%s is not on Spooky games yet (the runtime would ignore it)" % k
    return "unknown key %s" % k


def start_text(m):
    return MJ.start_text(m)


# ============================================================================ stage and build
def title_cfg_text(mode_dir, port):
    """The staged title.cfg: the person's, plus what the runtime needs from the port report."""
    text = ""
    p = os.path.join(mode_dir, "title.cfg")
    if os.path.isfile(p):
        with open(p, encoding="utf-8", errors="replace") as f:
            text = "".join(l for l in f.read().splitlines(True)
                           if not re.match(r"\s*(%s)\s*=" % "|".join(BUILD_TITLE_KEYS), l))
        if text and not text.endswith("\n"):
            text += "\n"
    return text + "# written by mkspkmodes.py from the port report\npoints_scale = %d\n" % int(port.get("points_scale") or 1)


def pad_files(mode_dir, port):
    """[(path in pad/, bytes or a file path, mode)] - the update's pad/ folder."""
    modes, problems = check_modes(mode_dir, port)
    if problems:
        raise Refused("the modes have problems:\n  " + "\n  ".join(problems))
    rt = runtime_files(port)
    if engine(port) == "godot":
        out = [("pad_modes.gd", rt[0], 0o644)]
    else:
        out = [("padunity.so", rt[0], 0o755), ("PadModes.dll", rt[1], 0o644)]
    out.append(("modes/title.cfg", title_cfg_text(mode_dir, port).encode("utf-8"), 0o644))
    for m in modes:
        out.append(("modes/" + m["file"], os.path.join(mode_dir, m["file"]), 0o644))
    stamp = "PAD custom modes (mkspkmodes.py, runtime %s) for %s: %s\n" % (
        port.get("runtime", "?"), port.get("title", "?"), ", ".join(m["name"] for m in modes))
    out.append(("README.txt", stamp.encode("utf-8"), 0o644))
    return out


def top_files(port):
    """[(path at the update's top, bytes, mode)] the runtime needs beside main.x86_64: Godot's
    override.cfg (the autoload that loads pad_modes.gd); nothing on Unity (its launch line)."""
    if engine(port) == "godot":
        return [(OVERRIDE_CFG, OVERRIDE_TEXT.encode("utf-8"), 0o644)]
    return []


def launch_files(port):
    """The launch files whose game line a modes build rewrites: a preload Unity title's; none on
    a dllmap one (patched_names: its Mono config) or on Godot."""
    return LAUNCH_FILES if engine(port) == "unity" and load_of(port) == "preload" else ()


def _base_name(name):
    return name.replace("\\", "/").rsplit("/", 1)[-1]


def stock_prg(stock, port):
    """A pinHeck title's stock PRG bytes from its update zip (or a PRG file); a PRG PAD built
    comes back as the stock one it was made from."""
    want = (port.get("prg") or "").upper() + ".PRG"
    if stock.lower().endswith(".zip"):
        import zipfile
        with zipfile.ZipFile(stock) as z:
            names = [n for n in z.namelist() if _base_name(n).upper() == want]
            if not names:
                raise Refused("%s has no %s: not the update this runtime knows" % (os.path.basename(stock), want))
            data = z.read(names[0])
    else:
        with open(stock, "rb") as f:
            data = f.read()
    return ph().stock_of(data)


def build_prg(stock, mode_dir, port):
    """The modes PRG (bytes): the stock one with the runtime and these modes in its free flash."""
    modes, problems = check_modes(mode_dir, port)
    if problems:
        raise Refused("the modes have problems:\n  " + "\n  ".join(problems))
    return build_prg_of(stock_prg(stock, port), modes, port)


def build_prg_of(prg, modes, port):
    try:
        return ph().build_prg(ph().stock_of(prg), modes, port)
    except ph().Refused as e:
        raise Refused(str(e))


def stage(mode_dir, pad_dir, port, stock=None):
    """The pad/ folder on disk (the rig's Try it overlay); on a pinHeck title the modes PRG,
    written to ``pad_dir/<PRG>`` from *stock* (the update zip) -> its path."""
    if engine(port) == "pinheck":
        if not stock:
            raise Refused("Try it on %s needs its stock update (its PRG)" % port.get("title", "this game"))
        data = build_prg(stock, mode_dir, port)
        os.makedirs(pad_dir, exist_ok=True)
        out = os.path.join(pad_dir, port["prg"] + ".PRG")
        with open(out, "wb") as f:
            f.write(data)
        return out
    if os.path.isdir(pad_dir):
        shutil.rmtree(pad_dir)
    for rel, src, mode in pad_files(mode_dir, port):
        dst = os.path.join(pad_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if isinstance(src, bytes):
            with open(dst, "wb") as f:
                f.write(src)
        else:
            shutil.copyfile(src, dst)
        os.chmod(dst, mode)
    return pad_dir


def patch_launch(text):
    """A launch file with its game line preloading the runtime -> (text, changed lines).
    A line that already preloads it is left alone (a modes update built again)."""
    out, n = [], 0
    for line in text.splitlines(True):
        body = line.rstrip("\r\n")
        m = _LAUNCH.match(body)
        if m:
            n += 1
            if RUNTIME_SO not in m.group(2):
                env = m.group(2) or "env "
                pre = re.search(r"(?:^|\s)LD_PRELOAD=(\S*)", env)
                if pre:                             # the line preloads something else too
                    env = env.replace("LD_PRELOAD=" + pre.group(1),
                                      "LD_PRELOAD=%s%s" % (RUNTIME_SO, ":" + pre.group(1) if pre.group(1) else ""), 1)
                else:
                    env = env + "LD_PRELOAD=%s " % RUNTIME_SO
                body = m.group(1) + env + m.group(3) + m.group(4)
                line = body + line[len(line.rstrip("\r\n")):]
        out.append(line)
    return "".join(out), n


def patch_mono_config(text):
    """The update's Mono config with MonoPosixHelper mapped to the runtime -> (text, changed
    entries).  Already mapped (a modes update built again): left alone, and counted."""
    n = [0]

    def sub(m):
        n[0] += 1
        return m.group(1) + RUNTIME_SO + m.group(3)
    return _DLLMAP.sub(sub, text), n[0]


def _base(rel):
    name = _norm(rel.replace("\\", "/"))
    return name.split("/", 1)[1] if name.startswith("uptest/") else name


def patch_file(rel, data, port):
    """A file of the update as a modes build carries it -> (data, patched).  *rel* is its path in
    the update; only the title's own way in (load_of) is touched."""
    base = _base(rel)
    load = load_of(port)
    if load == "preload" and base in LAUNCH_FILES:
        text, n = patch_launch(data.decode("utf-8", "surrogateescape"))
        return text.encode("utf-8", "surrogateescape"), n
    if load == "dllmap" and base == MONO_CONFIG:
        text, n = patch_mono_config(data.decode("utf-8", "surrogateescape"))
        return text.encode("utf-8", "surrogateescape"), n
    return data, 0


def patched_names(port):
    """The base names of the files patch_file may change (for a scan by name)."""
    if engine(port) != "unity":
        return ()                                   # Godot: override.cfg, nothing patched
    return LAUNCH_FILES if load_of(port) == "preload" else (os.path.basename(MONO_CONFIG),)


def pad_dir_for(names):
    """Where pad/ goes in an update laid out as *names*: beside main.x86_64 ("pad" or
    "uptest/pad")."""
    for n in names:
        n = _norm(n.replace("\\", "/"))
        base = _base(n)
        if base == "main.x86_64":
            return n[:-len(base)] + PAD_DIR
    return PAD_DIR


def _norm(name):
    return name[2:] if name.startswith("./") else name


# ============================================================================ containers
def _spooky_gpg():
    """The Spooky plugin's GPG helpers (the app's own, so Build and Write agree)."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
    if root not in sys.path:
        sys.path.insert(0, root)
    from pinball_decryptor.plugins.spooky import gpg, games
    return gpg, games


def container_of(port):
    return (port or {}).get("update_container") or "tar.gz"


def unwrap(stock, tmp, port, log=print):
    """The stock update's tar.gz -> its path (the stock file itself when it is one)."""
    kind = container_of(port)
    if kind == "tar.gz":
        return stock
    gpg, games = _spooky_gpg()
    if kind == "gpg_signed":
        log("taking the signature off %s..." % os.path.basename(stock))
        gpg.strip_gpg_signature(stock, tmp)
    elif kind == "gpg_symmetric":
        log("decrypting %s..." % os.path.basename(stock))
        gpg.decrypt_gpg_symmetric(stock, tmp, games.GPG_PASSPHRASES[port["gpg_format"]])
    else:
        raise Refused("%s: update container %s is not one this build knows" % (os.path.basename(stock), kind))
    return tmp


def wrap(tar_gz, out, port, log=print):
    """The new tar.gz -> the update file the machine takes (*out*)."""
    kind = container_of(port)
    if kind == "tar.gz":
        os.replace(tar_gz, out)
        return
    gpg, games = _spooky_gpg()
    if kind == "gpg_signed":
        log("signing it (PAD's own key: the machine asks before it takes it, as for any update Write makes)...")
        gpg.sign_beetlejuice(tar_gz, out)
    else:
        log("encrypting it with the game's own passphrase...")
        gpg.encrypt_gpg_symmetric(tar_gz, out, games.GPG_PASSPHRASES[port["gpg_format"]])


def _gzipped(path):
    with open(path, "rb") as f:
        return f.read(2) == b"\x1f\x8b"


def build_zip(stock, mode_dir, out, port, log=print, progress=None, cancelled=lambda: False):
    """A pinHeck title's update: the stock zip again, every file as it was, its PRG the modes
    PRG (the machine flashes the card's PRG into the game CPU from Service -> UPDATE CODE)."""
    import zipfile
    if os.path.abspath(stock) == os.path.abspath(out):
        raise Refused("the new update must not replace the stock one")
    data = build_prg(stock, mode_dir, port)
    n_modes = len(check_modes(mode_dir, port)[0])
    want = port["prg"].upper() + ".PRG"
    tmp, t0, done, replaced = out + ".partial", time.time(), 0, False
    try:
        with zipfile.ZipFile(stock) as src, zipfile.ZipFile(tmp, "w") as dst:
            infos = src.infolist()
            total = sum(i.file_size for i in infos) or 1
            for info in infos:
                if cancelled():
                    raise Refused("cancelled")
                zi = zipfile.ZipInfo(info.filename, info.date_time)
                zi.compress_type, zi.external_attr = info.compress_type, info.external_attr
                if _base_name(info.filename).upper() == want and not replaced:
                    dst.writestr(zi, data)
                    replaced = True
                    log("%s: the stock program with the mode runtime and %d mode(s) in its free flash "
                        "(%d bytes, was %d)" % (info.filename, n_modes, len(data), info.file_size))
                elif info.is_dir():
                    dst.writestr(zi, b"")
                else:
                    with src.open(info) as fi, dst.open(zi, "w") as fo:
                        shutil.copyfileobj(fi, fo, 1 << 20)
                done += info.file_size
                if progress:
                    progress(done, total)
        os.replace(tmp, out)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    log("built %s (%.2f GB) in %.0f s" % (out, os.path.getsize(out) / 1e9, time.time() - t0))
    return out


def build(stock, mode_dir, out, port, log=print, progress=None, cancelled=lambda: False):
    """The stock update again, written the same way (a tar.gz, or Looney Tunes' plain tar), with
    pad/ beside its main.x86_64 and the runtime loaded: on Unity the title's way in (load_of)
    patched, on Godot an override.cfg beside main.x86_64 naming it; unwrapped from and wrapped
    again in the title's container (container_of).  A pinHeck title's: build_zip."""
    if engine(port) == "pinheck":
        return build_zip(stock, mode_dir, out, port, log, progress, cancelled)
    files = pad_files(mode_dir, port)
    tops = top_files(port)
    if os.path.abspath(stock) == os.path.abspath(out):
        raise Refused("the new update must not replace the stock one")
    load = load_of(port)
    tmp_in, tmp_tar, tmp_out = out + ".stock.partial", out + ".tar.partial", out + ".partial"
    patched, prefix, total = 0, None, 0
    names = patched_names(port)
    t0 = time.time()
    try:
        src_path = unwrap(stock, tmp_in, port, log)
        total = os.path.getsize(src_path)
        gz = _gzipped(src_path)
        with open(src_path, "rb") as raw, tarfile.open(fileobj=raw, mode="r|gz" if gz else "r|") as src, \
                (tarfile.open(tmp_tar, mode="w:gz", compresslevel=1, format=tarfile.GNU_FORMAT) if gz
                 else tarfile.open(tmp_tar, mode="w", format=tarfile.GNU_FORMAT)) as dst:
            last = 0
            for ti in src:
                if cancelled():
                    raise Refused("cancelled")
                name = _norm(ti.name)
                base = _base(name)
                if prefix is None and base == "main.x86_64":
                    prefix = name[:-len(base)]
                if base == PAD_DIR or base.startswith(PAD_DIR + "/"):
                    continue                        # an old modes build's pad/: replaced below
                if base in (t[0] for t in tops):
                    continue                        # an old modes build's override.cfg: the same
                if ti.isfile() and os.path.basename(base) in names:
                    data = src.extractfile(ti).read()
                    new, n = patch_file(name, data, port)
                    if n:
                        patched += n
                        log("%s: %s" % (name, "the game's launch line now preloads " + RUNTIME_SO
                                        if load == "preload" else "Mono's MonoPosixHelper is now " + RUNTIME_SO))
                    ti.size = len(new)
                    dst.addfile(ti, io.BytesIO(new))
                    continue
                dst.addfile(ti, src.extractfile(ti) if ti.isfile() else None)
                if progress and raw.tell() - last > (16 << 20):
                    last = raw.tell()
                    progress(last, total)
            if names and not patched:
                what = (", ".join(LAUNCH_FILES) + ": no launch line starting main.x86_64") if load == "preload" \
                    else (MONO_CONFIG + ": no MonoPosixHelper dllmap")
                raise Refused("%s has no way in for the runtime (%s): not an update this runtime knows"
                              % (os.path.basename(stock), what))
            if not names and prefix is None:
                raise Refused("%s has no main.x86_64: not an update this runtime knows"
                              % os.path.basename(stock))
            now = int(time.time())
            pre = prefix or ""
            d = tarfile.TarInfo(pre + PAD_DIR)
            d.type, d.mode, d.mtime = tarfile.DIRTYPE, 0o755, now
            dst.addfile(d)
            m = tarfile.TarInfo(pre + PAD_DIR + "/modes")
            m.type, m.mode, m.mtime = tarfile.DIRTYPE, 0o755, now
            dst.addfile(m)
            for rel, srcf, mode in files:
                data = srcf if isinstance(srcf, bytes) else open(srcf, "rb").read()
                ti = tarfile.TarInfo(pre + PAD_DIR + "/" + rel)
                ti.size, ti.mode, ti.mtime = len(data), mode, now
                dst.addfile(ti, io.BytesIO(data))
            for rel, data, mode in tops:
                ti = tarfile.TarInfo(pre + rel)
                ti.size, ti.mode, ti.mtime = len(data), mode, now
                dst.addfile(ti, io.BytesIO(data))
                log("added %s%s: it loads the runtime (%s) when the game starts" % (pre, rel, RUNTIME_GD))
            log("added %s%s/: the runtime and %d mode file(s)" % (
                pre, PAD_DIR, sum(1 for f in files if f[0].endswith(".mode"))))
        if cancelled():
            raise Refused("cancelled")
        wrap(tmp_tar, tmp_out, port, log)
        os.replace(tmp_out, out)
    finally:
        for p in (tmp_in, tmp_tar, tmp_out):
            try:
                os.remove(p)
            except OSError:
                pass
    if progress:
        progress(total, total)
    log("built %s (%.2f GB) in %.0f s" % (out, os.path.getsize(out) / 1e9, time.time() - t0))
    return out


# ============================================================================ the port report
#: what each engine's scoring does to an award, for the port report (read from the game's code)
POINTS = {
    "godot": (10, "Game.score multiplies by the playfield multiplier (Game.multiplier) and a shot's "
                  "special multiplier, and rounds to 10 (snapped(int(points * multiplier), 10)); the "
                  "runtime calls it as the game's own awards do"),
}


def make_port(raw, label, title, ext, defaults=None):
    """The runtime's own report (PADMODES_PORT) -> the port report the app ships."""
    game, _, ver = label.partition("-")
    eng = raw.get("engine") or "unity"
    if raw.get("game_version") and ver and raw["game_version"].replace("_", ".") != ver:
        raise Refused("the report is from %s %s, not %s" % (raw.get("game_title"), raw["game_version"], ver))
    m = raw.get("points_scale_measured") or {}
    if not m.get("scored"):
        raise Refused("the report has no points measurement: run a game with PADMODES_PORT to its first ball")
    if int(m.get("multiplier") or 1) != 1:
        raise Refused("the points were measured under a x%s playfield multiplier" % m["multiplier"])
    scale = int(round(float(m["scored"]) / float(m["asked"])))
    rnd, note = POINTS.get(eng, (0, ""))
    out = collections.OrderedDict([
        ("title", title), ("game", game), ("version", ver), ("update_ext", ext), ("engine", eng),
        ("made_by", "the runtime itself in the running game on the Spooky rig (PADMODES_PORT, "
                    "unity/rigrun.sh --port), PAD-1419"),
    ])
    if eng == "godot":
        out["runtime_script"] = "pad_modes.gd"
    out["points_round"] = rnd
    out["points_note"] = note
    if defaults:
        out["defaults"] = defaults
    for k, v in raw.items():
        if k not in out and k != "points_scale_measured":
            out[k] = v
    out["points_scale"] = scale
    return out


def _defaults_from(mode_file):
    with open(mode_file, encoding="utf-8", errors="replace") as f:
        rows = MJ.parse_cfg(f.read())
    keep = ("start", "shots", "sound_start", "sound_shot", "sound_complete")
    return collections.OrderedDict((k, v) for _n, k, v in rows if k in keep)


# ============================================================================ cli
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("dir")
    c.add_argument("--port", required=True)
    s = sub.add_parser("stage")
    s.add_argument("dir")
    s.add_argument("out")
    s.add_argument("--port", required=True)
    s.add_argument("--stock", help="a pinHeck title's stock update (its PRG is the one patched)")
    b = sub.add_parser("build")
    b.add_argument("stock")
    b.add_argument("dir")
    b.add_argument("out")
    b.add_argument("--port", required=True)
    r = sub.add_parser("port")
    r.add_argument("raw")
    r.add_argument("--label", required=True)
    r.add_argument("--title", required=True)
    r.add_argument("--ext", required=True)
    r.add_argument("--defaults", help="a starter .mode file: the new mode form's picks")
    r.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "port":
            with open(a.raw, encoding="utf-8") as f:
                raw = json.load(f)
            p = make_port(raw, a.label, a.title, a.ext, _defaults_from(a.defaults) if a.defaults else None)
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                json.dump(p, f, indent=1)
                f.write("\n")
            print("%s: %d switches, %d lamps, %d sounds, %d game modes, %d fonts, points x%d round %d" % (
                a.out, len(p.get("switches") or ()), len(p.get("lamps") or ()), len(p.get("sounds") or ()),
                len(p.get("game_modes") or ()), len(p.get("fonts") or ()), p["points_scale"], p["points_round"]))
            return 0
        port = load_port(a.port)
        if a.cmd == "check":
            modes, problems = check_modes(a.dir, port)
            for p in problems:
                print("problem: " + p)
            print("%d mode(s), %d problem(s)" % (len(modes), len(problems)))
            return 1 if problems else 0
        if a.cmd == "stage":
            print(stage(a.dir, a.out, port, a.stock))
            return 0
        build(a.stock, a.dir, a.out, port,
              progress=lambda d, t: print("progress %d" % (d * 100 // max(1, t)), flush=True))
        return 0
    except Refused as e:
        print("mkspkmodes: %s" % e, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
