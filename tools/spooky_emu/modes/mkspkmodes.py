#!/usr/bin/env python3
"""mkspkmodes.py - custom modes on Spooky's Unity titles (PAD-1417; docs/plans/spooky_modes.md).

A mode is the same ``key = value`` file as on JJP (tools/jjp_emu/MODES.md); a title's modes are
one folder of them (``title.cfg`` + ``*.mode``).  The runtime is ``padunity.so`` (preloaded by
the update's launch line) + ``PadModes.dll`` (built against the title's own Managed/, runs the
modes through the game's own Mode, scoring and callouts): tools/spooky_emu/modes/unity.

  check <mode dir> --port <port.json>            the folder as the runtime will read it
  stage <mode dir> <pad dir> --port <port.json>  the update's pad/ folder (the rig's Try it)
  build <stock update> <mode dir> <new update> --port <port.json>
                                                 the stock .scooby again, with pad/ in it and
                                                 its launch lines preloading the runtime

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
PREBUILT = os.path.join(UNITY, "prebuilt")
PORTS = os.path.join(HERE, "ports")
#: where the runtime sits in the update (and so in /game/code/uptest on the machine)
PAD_DIR = "pad"
RUNTIME_SO = "/game/code/uptest/pad/padunity.so"
#: the files whose ``exec ... main.x86_64`` line starts the game (sway on 6.1 kernels, i3 on 5.10)
LAUNCH_FILES = ("sway_config", "i3_config")
_LAUNCH = re.compile(r"^(\s*exec\s+(?:--no-startup-id\s+)?)(\S*main\.x86_64)(.*)$")
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


def runtime_files(port):
    """(padunity.so, PadModes.dll) the title runs, or Refused."""
    so = os.path.join(PREBUILT, "padunity.so")
    dll = os.path.join(PREBUILT, port.get("runtime_dll") or "")
    for p in (so, dll):
        if not port.get("runtime_dll") or not os.path.isfile(p):
            raise Refused("no mode runtime built for %s (%s)" % (port.get("title", "this title"), p))
    return so, dll


# ============================================================================ check
def _int(v):
    return int(v.replace(",", "").replace("_", "")) if MJ._INT.match(v or "") else None


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
            p = check_value(kind, v, port)
            if p:
                problems.append("%s:%d: %s %s" % (fn, n, k, p))
            m[k] = v
        m["file"] = fn
        m.setdefault("name", fn[:-5])
        if not m.get("start"):
            problems.append("%s: no start = (the switches that start it): the mode would never start" % fn)
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
    so, dll = runtime_files(port)
    out = [("padunity.so", so, 0o755), ("PadModes.dll", dll, 0o644),
           ("modes/title.cfg", title_cfg_text(mode_dir, port).encode("utf-8"), 0o644)]
    for m in modes:
        out.append(("modes/" + m["file"], os.path.join(mode_dir, m["file"]), 0o644))
    stamp = "PAD custom modes (mkspkmodes.py, runtime %s) for %s: %s\n" % (
        port.get("runtime", "?"), port.get("title", "?"), ", ".join(m["name"] for m in modes))
    out.append(("README.txt", stamp.encode("utf-8"), 0o644))
    return out


def stage(mode_dir, pad_dir, port):
    """The pad/ folder on disk (the rig's Try it overlay)."""
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
        if m and RUNTIME_SO not in body:
            body = "%senv LD_PRELOAD=%s %s%s" % (m.group(1), RUNTIME_SO, m.group(2), m.group(3))
            line = body + line[len(line.rstrip("\r\n")):]
            n += 1
        elif m:
            n += 1
        out.append(line)
    return "".join(out), n


def _norm(name):
    return name[2:] if name.startswith("./") else name


def build(stock, mode_dir, out, port, log=print, progress=None, cancelled=lambda: False):
    """The stock update (a tar.gz) again, with pad/ and its launch lines preloading the runtime."""
    files = pad_files(mode_dir, port)
    if os.path.abspath(stock) == os.path.abspath(out):
        raise Refused("the new update must not replace the stock one")
    tmp = out + ".partial"
    total = os.path.getsize(stock)
    launched, prefix = 0, None
    t0 = time.time()
    try:
        with open(stock, "rb") as raw, tarfile.open(fileobj=raw, mode="r|gz") as src, \
                tarfile.open(tmp, mode="w:gz", compresslevel=1, format=tarfile.GNU_FORMAT) as dst:
            last = 0
            for ti in src:
                if cancelled():
                    raise Refused("cancelled")
                name = _norm(ti.name)
                base = name.split("/", 1)[1] if name.startswith("uptest/") else name
                if prefix is None and base.endswith("main.x86_64") and "/" not in base:
                    prefix = name[:-len(base)]
                if base == PAD_DIR or base.startswith(PAD_DIR + "/"):
                    continue                        # an old modes build's pad/: replaced below
                if ti.isfile() and base in LAUNCH_FILES:
                    text = src.extractfile(ti).read().decode("utf-8", "surrogateescape")
                    text, n = patch_launch(text)
                    data = text.encode("utf-8", "surrogateescape")
                    launched += n
                    ti.size = len(data)
                    dst.addfile(ti, io.BytesIO(data))
                    log("%s: the game's launch line now preloads %s" % (name, RUNTIME_SO))
                    continue
                dst.addfile(ti, src.extractfile(ti) if ti.isfile() else None)
                if progress and raw.tell() - last > (16 << 20):
                    last = raw.tell()
                    progress(last, total)
            if not launched:
                raise Refused("%s has no launch line starting main.x86_64 (%s): not an update this "
                              "runtime knows" % (os.path.basename(stock), ", ".join(LAUNCH_FILES)))
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
            log("added %s%s/: the runtime and %d mode file(s)" % (pre, PAD_DIR, len(files) - 4))
        os.replace(tmp, out)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    if progress:
        progress(total, total)
    log("built %s (%.2f GB) in %.0f s" % (out, os.path.getsize(out) / 1e9, time.time() - t0))
    return out


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
    b = sub.add_parser("build")
    b.add_argument("stock")
    b.add_argument("dir")
    b.add_argument("out")
    b.add_argument("--port", required=True)
    a = ap.parse_args(argv)
    try:
        port = load_port(a.port)
        if a.cmd == "check":
            modes, problems = check_modes(a.dir, port)
            for p in problems:
                print("problem: " + p)
            print("%d mode(s), %d problem(s)" % (len(modes), len(problems)))
            return 1 if problems else 0
        if a.cmd == "stage":
            print(stage(a.dir, a.out, port))
            return 0
        build(a.stock, a.dir, a.out, port,
              progress=lambda d, t: print("progress %d" % (d * 100 // max(1, t)), flush=True))
        return 0
    except Refused as e:
        print("mkspkmodes: %s" % e, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
