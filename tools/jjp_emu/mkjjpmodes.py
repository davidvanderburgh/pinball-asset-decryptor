#!/usr/bin/env python3
"""mkjjpmodes.py - a JJP install ISO in, the same ISO with custom modes out (PAD-1337).

The JJP mode SDK runs custom modes inside a retail JJP game from outside its
binary (jjpmodes.c, MODES.md).  On the rig run_game.sh preloads it.  On a real
machine nothing preloads anything, so this writes an install ISO whose root
carries the SDK and one guarded line in scripts/rungame.sh that loads it:

  /jjpe/gen1/padmodes/jjpmodes.so      the runtime (built by buildmods.sh)
  /jjpe/gen1/padmodes/modes/           title.cfg + *.mode, as given
  /jjpe/gen1/padmodes/build.json       what was written, with sha256s
  /jjpe/gen1/scripts/padmodes.sh       exports LD_PRELOAD + JJP_MODS_DIR
  /jjpe/gen1/scripts/rungame.sh        + MODES_HOOK_LINES after runonce.sh

and nothing else changes.  JJP's own installer restores sda3 into BOTH root
slots, so only the sda3 pieces are replaced: no installer or boot-config edit
(unlike mkjjpmulti.py, whose building blocks this reuses).  The installer only
gunzip-tests the pieces, so the ISO installs as a stock one does.  A multi-boot
ISO in gives a multi-boot ISO out with modes in root A; title.cfg's `game` key
keeps them out of image 1's game.

Turning the modes off on a machine without reinstalling: create
/jjpe/perm/padmodes.off (padmodes.sh checks for it).

    mkjjpmodes.py check --modes DIR [--port PORT.json]
    mkjjpmodes.py build --iso IN.iso --modes DIR --out OUT.iso [--port P.json] [--so jjpmodes.so]   (root, WSL)
        (no --so: the runtime is built from jjpmodes.c against the ISO's own glibc)
    mkjjpmodes.py inspect --iso OUT.iso
"""
import argparse
import collections
import hashlib
import json
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TOOL = "mkjjpmodes"
VERSION = "1"
JJPEDIR = "/jjpe/gen1"
PADMODES_DIR = JJPEDIR + "/padmodes"
MODES_HOOK = JJPEDIR + "/scripts/padmodes.sh"
RUNGAME = JJPEDIR + "/scripts/rungame.sh"
RUNONCE_LINE = "$JJPEDIR/scripts/runonce.sh"
ISO_MODES_DIR = "/jjp/padmodes"
OFF_SWITCH = "/jjpe/perm/padmodes.off"
SO_DEFAULT = "/var/tmp/jjpmodes.so"
#: the image's glibc, where the runtime is linked against it (buildmods.sh JJP_MODS_LIBDIR)
ROOT_LIBDIR = "/lib/x86_64-linux-gnu"
MODES_HOOK_MARK = "# PAD custom modes:"
MODES_HOOK_LINES = [
    "",
    MODES_HOOK_MARK + " the JJP mode SDK and its modes (padmodes.sh)",
    "[ -r $JJPEDIR/scripts/padmodes.sh ] && . $JJPEDIR/scripts/padmodes.sh",
]

PADMODES_SH = """#!/bin/sh
# PAD custom modes (PAD-1337).  Sourced by rungame.sh after runonce.sh, so the
# exports below reach ./game.  Loads the JJP mode SDK runtime with the modes in
# $JJPEDIR/padmodes/modes.  To turn the modes off without reinstalling, create
# %(off)s.
if [ -r $JJPEDIR/padmodes/jjpmodes.so ] && [ ! -e %(off)s ]; then
    export LD_PRELOAD="${LD_PRELOAD:+$LD_PRELOAD }$JJPEDIR/padmodes/jjpmodes.so"
    export JJP_MODS_DIR=$JJPEDIR/padmodes/modes
    echo "PAD custom modes: $(ls $JJPEDIR/padmodes/modes | grep -c '\\.mode$') mode(s) loaded"
fi
""" % {"off": OFF_SWITCH}


class Refused(Exception):
    pass


# ============================================================================= mode files
#: every key jjpmodes.c reads (apply_kv), and what its value is
KEYS = collections.OrderedDict([
    ("name", "text"), ("title", "text"), ("start", "switches"), ("start_count", "int"),
    ("shots", "switches"), ("points", "int"), ("seconds", "int"), ("complete", "int"),
    ("complete_points", "int"), ("sound_start", "sound"), ("sound_shot", "sound"),
    ("sound_end", "sound"), ("sound_complete", "sound"), ("lamps", "lamps"), ("lamp_color", "rgb"),
    ("lamp_blink", "int"), ("font_title", "font"), ("font_value", "font"), ("font_timer", "font"),
    ("title_color", "rgba"), ("value_color", "rgba"), ("timer_color", "rgba"), ("panel_color", "rgba"),
    ("game_modes", ("pause", "end", "ignore")),
    ("panel", ("middle", "bottom", "top")),
])
#: keys only title.cfg takes
TITLE_KEYS = collections.OrderedDict([
    ("game", "text"), ("ingame_state", "int"), ("background_modes", "modes"),
])
MAX_MODES, MAX_LIST, MAX_SHOT_SWITCHES = 24, 24, 96
_INT = re.compile(r"^-?[0-9][0-9,_]*$")
_HEX = re.compile(r"^#?[0-9A-Fa-f]+$")


def parse_cfg(text):
    """`key = value` lines -> [(lineno, key, value)] as jjpmodes.c reads them (# and ; comment
    lines, a trailing ' #' comment)."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s[0] in "#;" or "=" not in s:
            continue
        k, v = s.split("=", 1)
        v = v.strip()
        if " #" in v:
            v = v.split(" #", 1)[0].strip()
        out.append((n, k.strip(), v))
    return out


def _names(v):
    return [t for t in re.split(r"[ ,\t]+", v) if t]


def check_value(kind, v, port=None):
    """-> a problem string, or None."""
    if isinstance(kind, tuple):
        return None if v in kind else "must be one of %s" % ", ".join(kind)
    if kind == "int":
        return None if _INT.match(v) else "must be a whole number"
    if kind in ("rgb", "rgba"):
        h = v.lstrip("#")
        ok = _HEX.match(v) and len(h) in ((6,) if kind == "rgb" else (6, 8))
        return None if ok else "must be %s hex" % ("rrggbb" if kind == "rgb" else "rrggbb or rrggbbaa")
    if port is None:
        return None
    table = {"switches": "switches", "lamps": "lamps", "sound": "sounds", "font": "fonts",
             "modes": "game_modes"}.get(kind)
    if table is None:
        return None
    known = set(port.get(table, []))
    if table == "lamps":
        # a mode lights lamps (lp_*) or whole lamp groups (ls_*): MODES.md, jjpmodes.c find_lamps
        known |= set(port.get("lamp_groups", []))
    if table == "switches":
        known = set(s["symbol"] if isinstance(s, dict) else s for s in port.get("switches", []))
    if not known:
        return None
    missing = [t for t in (_names(v) if kind in ("switches", "lamps", "modes") else [v]) if t not in known]
    return None if not missing else "not in %s: %s" % (port.get("title", "this game"), " ".join(missing))


def check_modes(mode_dir, port=None):
    """A mode folder checked the way jjpmodes.c will read it -> (modes, problems):
    modes = [{file, name, start, ...}], problems = ["file:line: ..."]."""
    problems, modes = [], []
    if not os.path.isdir(mode_dir):
        raise Refused("%s is not a folder" % mode_dir)
    title = {}
    tpath = os.path.join(mode_dir, "title.cfg")
    if os.path.isfile(tpath):
        with open(tpath, encoding="utf-8", errors="replace") as f:
            for n, k, v in parse_cfg(f.read()):
                kind = TITLE_KEYS.get(k) or KEYS.get(k)
                if kind is None:
                    problems.append("title.cfg:%d: unknown key %s" % (n, k))
                    continue
                p = check_value(kind, v, port)
                if p:
                    problems.append("title.cfg:%d: %s %s" % (n, k, p))
                title[k] = v
    files = sorted(f for f in os.listdir(mode_dir) if f.endswith(".mode"))
    if not files:
        problems.append("no .mode files in %s" % mode_dir)
    if len(files) > MAX_MODES:
        problems.append("%d modes: the runtime takes %d, the rest are ignored" % (len(files), MAX_MODES))
    shot_switches = set()
    for fn in files:
        with open(os.path.join(mode_dir, fn), encoding="utf-8", errors="replace") as f:
            rows = parse_cfg(f.read())
        m = dict(title)
        for n, k, v in rows:
            if k in TITLE_KEYS:
                problems.append("%s:%d: %s belongs in title.cfg" % (fn, n, k))
                continue
            kind = KEYS.get(k)
            if kind is None:
                problems.append("%s:%d: unknown key %s" % (fn, n, k))
                continue
            p = check_value(kind, v, port)
            if p:
                problems.append("%s:%d: %s %s" % (fn, n, k, p))
            if kind in ("switches", "lamps") and len(_names(v)) > MAX_LIST:
                problems.append("%s:%d: %s lists %d; the runtime takes %d" % (fn, n, k, len(_names(v)), MAX_LIST))
            m[k] = v
        if not m.get("start"):
            problems.append("%s: no start = <switch> (the mode would never start)" % fn)
        m["file"] = fn
        m.setdefault("name", fn[:-5])
        for k in ("start", "shots"):
            shot_switches.update(_names(m.get(k, "")))
        modes.append(m)
    if len(shot_switches) > MAX_SHOT_SWITCHES:
        problems.append("%d different shot switches; the runtime wraps %d" % (len(shot_switches), MAX_SHOT_SWITCHES))
    return modes, problems


# ============================================================================= rungame.sh
def has_modes_hook(text):
    return any(ln.startswith(MODES_HOOK_MARK) for ln in text.split("\n"))


def hook_rungame_modes(text):
    """rungame.sh with MODES_HOOK_LINES after the runonce.sh line (idempotent; refused when the
    anchor is not exactly one line - a rungame.sh this tool does not know is not edited blind)."""
    if has_modes_hook(text):
        return text
    lines = text.split("\n")
    at = [i for i, ln in enumerate(lines) if ln.strip() == RUNONCE_LINE]
    if len(at) != 1:
        raise Refused("rungame.sh: expected exactly one '%s' line to hook after, found %d" % (RUNONCE_LINE, len(at)))
    i = at[0] + 1
    return "\n".join(lines[:i] + MODES_HOOK_LINES + lines[i:])


def strip_modes_hook(text):
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        if lines[i].startswith(MODES_HOOK_MARK):
            if out and out[-1] == "":
                out.pop()
            i += 2
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


# ============================================================================= build
def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def build_runtime(libdir, out):
    """jjpmodes.c built by buildmods.sh against the glibc in *libdir* (an image's own) -> out.
    Raises Refused with the build's last lines when it fails (no gcc, a glibc too new...)."""
    import subprocess
    env = dict(os.environ, JJP_MODS_LIBDIR=libdir, JJP_MODS_SO=out)
    r = subprocess.run(["bash", os.path.join(HERE, "buildmods.sh")], env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True, errors="replace")
    if r.returncode != 0 or not os.path.isfile(out):
        tail = " | ".join([ln for ln in (r.stdout or "").splitlines() if ln.strip()][-4:])
        raise Refused("building the mode runtime failed (rc %d): %s" % (r.returncode, tail))
    print("runtime: built against the image's glibc (%d bytes)" % os.path.getsize(out), flush=True)
    return out


def stage_modes(mj, raw, so_path, mode_dir, manifest):
    """The SDK + modes into a root image (loop-mounted rw), rungame.sh hooked; e2fsck after.
    *so_path* None builds the runtime against this root's own glibc first (PAD-1350: the app
    builds with no runtime of its own lying about).  -> {path in the root: sha256}."""
    staged = collections.OrderedDict()

    def put(src, rel, mode):
        dest = mnt + rel
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if isinstance(src, bytes):
            with open(dest, "wb") as f:
                f.write(src)
        else:
            shutil.copyfile(src, dest)
        os.chmod(dest, mode)
        try:
            os.chown(dest, 0, 0)
        except (OSError, AttributeError):
            pass
        staged[rel] = sha256_file(dest)

    with mj.LoopRW(raw) as mnt:
        rg = mnt + RUNGAME
        if not os.path.isfile(rg):
            raise Refused("%s: no %s in this root - not a JJP game image" % (raw, RUNGAME))
        d = mnt + PADMODES_DIR
        if os.path.isdir(d):
            shutil.rmtree(d)
        if so_path is None:
            so_path = build_runtime(mnt + ROOT_LIBDIR, os.path.join(os.path.dirname(raw), "jjpmodes.so"))
        manifest["so_sha256"] = sha256_file(so_path)
        put(so_path, PADMODES_DIR + "/jjpmodes.so", 0o755)
        for fn in sorted(os.listdir(mode_dir)):
            p = os.path.join(mode_dir, fn)
            if os.path.isfile(p) and (fn.endswith(".mode") or fn == "title.cfg"):
                put(p, PADMODES_DIR + "/modes/" + fn, 0o644)
        put(PADMODES_SH.encode(), MODES_HOOK, 0o755)
        with open(rg, "r", encoding="utf-8", errors="surrogateescape") as f:
            text = f.read()
        hooked = hook_rungame_modes(text)
        if hooked != text:
            mode = os.stat(rg).st_mode & 0o7777
            with open(rg, "w", encoding="utf-8", errors="surrogateescape") as f:
                f.write(hooked)
            os.chmod(rg, mode)
        staged[RUNGAME] = sha256_file(rg)
        manifest["staged"] = dict(staged)
        put((json.dumps(manifest, indent=1) + "\n").encode(), PADMODES_DIR + "/build.json", 0o644)
        mj.syncfs(mnt)
    rc = mj.e2fsck(raw)
    mj.say("staged %d file(s) into %s (e2fsck rc %d)" % (len(staged), os.path.basename(raw), rc))
    return staged


def _stop_on_sigterm():
    """A SIGTERM (the app's Cancel) raises Refused, so the with-blocks unmount and the
    finally deletes the scratch, instead of dying with the ISO and the root still mounted."""
    import signal

    def stop(*_a):
        raise Refused("cancelled")
    try:
        signal.signal(signal.SIGTERM, stop)
    except (ValueError, OSError):                       # not the main thread
        pass


def build(a):
    import mkjjpmulti as mj
    mj.require_root("build")
    _stop_on_sigterm()
    mj.need_tools("partclone.ext4", "partclone.restore", "gunzip", "split", "e2fsck", "losetup", "mount",
                  "umount", "debugfs", "xorriso", "cp")
    iso = os.path.abspath(a.iso)
    if not os.path.isfile(iso):
        raise Refused("%s does not exist" % iso)
    so = None
    if a.so:
        so = os.path.abspath(a.so)
        if not os.path.isfile(so):
            raise Refused("%s does not exist - build it with buildmods.sh (or leave out --so)" % so)
        with open(so, "rb") as f:
            if f.read(4) != b"\x7fELF":
                raise Refused("%s is not an ELF library" % so)
    else:
        mj.need_tools("gcc", "objdump", "nm")
    port = json.load(open(a.port)) if a.port else None
    modes, problems = check_modes(a.modes, port)
    for p in problems:
        print("problem: " + p)
    if problems and not a.force:
        raise Refused("%d problem(s) in %s (--force writes it anyway)" % (len(problems), a.modes))
    out = os.path.abspath(mj.check_output_path(a.out, [iso], force=a.force or a.overwrite))
    work = os.path.abspath(a.workdir) if a.workdir else os.path.join(os.path.dirname(out), ".mkjjpmodes_" + os.path.basename(out))
    os.makedirs(work, exist_ok=True)
    t0 = time.time()
    try:
        with mj.IsoMount(iso, os.path.join(work, "iso")) as m:
            info = mj.iso_info(iso, m)
            info.check_stock_shape("the ISO")
            cache = mj.cached_root_raw(iso, a.cache_dir, m, info, None)
            work_raw = os.path.join(work, "sda3.raw")
            mj.say("copying the cached root %s -> %s" % (cache, work_raw))
            mj.sparse_copy(cache, work_raw)
            manifest = collections.OrderedDict([
                ("tool", TOOL), ("version", VERSION), ("written", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
                ("source_iso", os.path.basename(iso)), ("title", info.title or info.name),
                ("game_version", info.game_version),
                ("modes", [collections.OrderedDict((k, m_.get(k, "")) for k in ("file", "name", "start", "seconds", "points"))
                           for m_ in modes]),
            ])
            staged = stage_modes(mj, work_raw, so, a.modes, manifest)
            chunks = mj.partclone_root(work_raw, os.path.join(work, "chunks"), info.split_size(), None, None)
            mj.say("root: %d piece(s), %s compressed" % (len(chunks), mj._gb(sum(os.path.getsize(c) for c in chunks))))
            iso_dir = os.path.join(work, "isofiles", "padmodes")
            if os.path.isdir(iso_dir):
                shutil.rmtree(iso_dir)
            os.makedirs(os.path.join(iso_dir, "modes"))
            for fn in os.listdir(a.modes):
                p = os.path.join(a.modes, fn)
                if os.path.isfile(p) and (fn.endswith(".mode") or fn == "title.cfg"):
                    shutil.copyfile(p, os.path.join(iso_dir, "modes", fn))
            manifest["staged"] = dict(staged)
            with open(os.path.join(iso_dir, "build.json"), "w") as f:
                f.write(json.dumps(manifest, indent=1) + "\n")
            maps = [(c, mj.PARTIMAG + "/" + os.path.basename(c)) for c in chunks]
            maps.append((iso_dir, ISO_MODES_DIR))
            removes = [ISO_MODES_DIR] if os.path.isdir(os.path.join(m, ISO_MODES_DIR.lstrip("/"))) else []
            if os.path.exists(out):
                os.unlink(out)
            mj.xorriso_build(iso, out, removes, [(mj.PARTIMAG, mj.ROOT_PIECE + ".gz.*")], maps, [], None, None)
        size = os.path.getsize(out)
        mj.say("wrote %s: %s in %d s, %d mode(s)" % (out, mj._gb(size), int(time.time() - t0), len(modes)))
        print("iso-size %d written" % size)
        return 0
    finally:
        if not a.keep_work and os.path.isdir(work):
            shutil.rmtree(work, ignore_errors=True)


def inspect(a):
    """What a mode ISO carries (its /jjp/padmodes/build.json), read with xorriso: no root needed."""
    import subprocess
    import tempfile
    d = tempfile.mkdtemp(prefix="mkjjpmodes_")
    try:
        r = subprocess.run(["xorriso", "-osirrox", "on", "-indev", a.iso, "-extract", ISO_MODES_DIR + "/build.json",
                            os.path.join(d, "build.json")], capture_output=True, text=True)
        p = os.path.join(d, "build.json")
        if r.returncode != 0 or not os.path.isfile(p):
            print("no custom modes on %s" % a.iso)
            return 1
        man = json.load(open(p))
        print("%s %s: %d custom mode(s), written %s by %s %s" % (man.get("title"), man.get("game_version"),
              len(man.get("modes", [])), man.get("written"), man.get("tool"), man.get("version")))
        for m in man.get("modes", []):
            print("  %-24s start %-28s %s s, %s a shot" % (m.get("name"), m.get("start"), m.get("seconds") or "20",
                                                           m.get("points") or "1000000"))
        return 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("check", help="check a mode folder (and, with --port, its names against a title)")
    s.add_argument("--modes", required=True)
    s.add_argument("--port", help="the title's port JSON (jjpport.py) to check every name against")
    s = sub.add_parser("build", help="write the install ISO with the modes (root, WSL)")
    s.add_argument("--iso", required=True)
    s.add_argument("--modes", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--so", help="a runtime built already (buildmods.sh's %s); left out, it is built "
                              "against the ISO's own glibc" % SO_DEFAULT)
    s.add_argument("--port")
    s.add_argument("--cache-dir")
    s.add_argument("--workdir")
    s.add_argument("--keep-work", action="store_true")
    s.add_argument("--force", action="store_true", help="write it despite problems in the modes")
    s.add_argument("--overwrite", action="store_true", help="replace an earlier output")
    s = sub.add_parser("inspect", help="list the modes a mode ISO carries")
    s.add_argument("--iso", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "check":
            port = json.load(open(a.port)) if a.port else None
            modes, problems = check_modes(a.modes, port)
            for m in modes:
                print("mode %-28s start %s" % (m["name"], m.get("start", "")))
            for p in problems:
                print("problem: " + p)
            print("%d mode(s), %d problem(s)" % (len(modes), len(problems)))
            return 1 if problems else 0
        if a.cmd == "build":
            return build(a)
        return inspect(a)
    except Refused as e:
        print("refused: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
