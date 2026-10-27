#!/usr/bin/env python3
"""runrec.py - every run is recorded so it can be replayed exactly (PAD-764).

    runrec.py start  <logdir> <root> <game> <log> [restart]   # watch.sh, as each boot starts
    runrec.py finish <logdir> [note]                          # watch.sh, as each boot ends
    runrec.py list   <logdir>                                 # the recordings, newest first
    runrec.py restore <recording> <root>                      # put its NVRAM back (replayrun.sh)
    runrec.py env <recording>                                 # its launch settings, as `export` lines

WHY. David asked to replay exactly what he saw in his last games (PAD-733). The
switch log alone was nearly enough: every switch the game was handed is in the
guest log as `[sw] <ms> ms +<id><who> ...` on the guest's own clock, and
swreplay.py fed one of his sessions back to a rig to the millisecond - until his
first pick, where the game read what the MACHINE remembered (the last place he
played, the audits) and the rig remembered something else. A replay needs the
machine's memory as it was when the run began. Nothing kept it: the NVRAM goes
on changing as the game plays, and gzwatch.log is truncated by the next boot.

So each boot gets a folder under <logdir>/runs/, made BEFORE the guest starts:

    nvram/      the title's NVRAM as the game found it - data/nv/<title>,
                data/nvram-<title>.bin, the boot selector's own memory
                (codeselect.last / .color) and an edition's own store
                (nv.own/*/<title>, PAD-226): everything of /data the boot reads
    run.json    what was booted and how: the title, the card, the edits and
                modes the launch brought, every PAD_ setting, the switch levels
                a Restart game began from
    switches.log  the run's own record, written when the boot ends: its [sw]
                edges, [swspin] rips and [pause] totals, as the shim logged them

`finish` runs at the end of each boot (teardown, and before Restart game boots
again) and, as a backstop, at the start of the next one - a run whose watch.sh
was killed outright still gets its switch log, from the log it left behind,
before the new boot truncates it. The newest KEEP recordings stay (PAD_RUN_KEEP,
20 by default; ~0.5 MB each, the NVRAM).
"""
import glob
import hashlib
import json
import os
import re
import shutil
import socket
import sys
import time

KEEP = 20
CURRENT = ".current"
SWITCHES = "switches.log"
#: What a replay reads back, as the shim wrote it (hwshim.c sw_shm_edges and the
#: rip code). Searched, not anchored: a PAD_LOG_TIME run prefixes every line.
RECORD_LINE = re.compile(r"\[sw\] \d+ ms(?: [-+]\d+\S)+|\[swspin\] \d+ ms id=\d+ .*?rip (?:START|END)"
                         r"|\[pause\] \d+ ms frozen \d+ ms in all")


def runs_dir(logdir):
    return os.path.join(logdir, "runs")


def _owner_of(path):
    try:
        st = os.stat(path)
        return st.st_uid, st.st_gid
    except OSError:
        return None


def _chown_tree(path, owner):
    """A root run (the app's checkpointable launch) records as root; the
    recording belongs to whoever owns the log folder, as every log there does."""
    if owner is None or getattr(os, "geteuid", lambda: -1)() != 0:
        return
    for dirpath, dirnames, filenames in os.walk(path):
        for n in [dirpath] + [os.path.join(dirpath, f) for f in dirnames + filenames]:
            try:
                os.lchown(n, *owner)
            except OSError:
                pass


def nvram_items(root, game):
    """(relative path under data/, absolute path) of everything of /data the
    boot of <game> reads, that exists."""
    data = os.path.join(root, "data")
    rels = ["nv/" + game, "nvram-%s.bin" % game, "codeselect.last", "codeselect.color"]
    rels += sorted(os.path.relpath(p, data).replace(os.sep, "/") for p in glob.glob(os.path.join(data, "nv.own", "*", game)))
    return [(r, os.path.join(data, r)) for r in rels if os.path.lexists(os.path.join(data, r))]


def _sha1_tree(path):
    h = hashlib.sha1()
    paths = [path] if os.path.isfile(path) else sorted(
        os.path.join(d, f) for d, _ds, fs in os.walk(path) for f in fs)
    for p in paths:
        h.update(os.path.relpath(p, path).encode() if p != path else b"")
        try:
            with open(p, "rb") as f:
                h.update(f.read())
        except OSError:
            h.update(b"?")
    return h.hexdigest()


def _card_facts(card):
    if not card:
        return None
    try:
        st = os.stat(card)
        return {"path": card, "size": st.st_size, "mtime": int(st.st_mtime)}
    except OSError:
        return {"path": card}


def _levels(root):
    """The switches closed in the block as this boot starts: what a Restart game
    boots into (watch.sh keeps the block - the balls are where they are). None
    when there is no block."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import padsw
        with open(os.path.join(root, "dump", "padsw"), "rb") as f:
            b = f.read(padsw.SIZE)
        if len(b) < padsw.SIZE or int.from_bytes(b[:4], "little") != padsw.MAGIC:
            return None
        return [i for i in range(padsw.MAX_ID) if b[padsw.OFF_MRG + i]]
    except (OSError, ImportError, AttributeError):
        return None


def launch_modes(root, env):
    """The files tryit.sh install put in the rootfs for this launch, when it
    brought a mode runtime of its own (PAD_MODE_SO)."""
    if not env.get("PAD_MODE_SO"):
        return []
    so = os.path.join(root, env["PAD_MODE_SO"].lstrip("/"))
    dump = os.path.join(root, "dump")
    out = [so] if os.path.isfile(so) else []
    for pat in ("game.port", "gamecheck.on", "mode*.cfg", "*.assets"):
        out += sorted(p for p in glob.glob(os.path.join(dump, pat)) if os.path.isfile(p))
    return out


def edits_facts(path):
    """Which edits a run was given: the override set's own manifest
    (overrides.json, rebuilt with the set whenever the project's edits change)
    by hash. The set itself is the project's and can be gigabytes, so it is
    not kept; a replay says when the folder now holds another one."""
    try:
        with open(os.path.join(path, "overrides.json"), "rb") as f:
            return {"path": path, "manifest_sha1": hashlib.sha1(f.read()).hexdigest()}
    except OSError:
        return {"path": path, "manifest_sha1": None}


def start(logdir, root, game, log, boot="start", now=None, env=None):
    """Make this boot's recording; returns its folder."""
    env = os.environ if env is None else env
    finish(logdir)                      # the last boot's, if nothing finished it
    now = time.time() if now is None else now
    runs = runs_dir(logdir)
    os.makedirs(runs, exist_ok=True)
    name = "%s-%s" % (time.strftime("%Y%m%d-%H%M%S", time.localtime(now)), game)
    rec, n = os.path.join(runs, name), 1
    while os.path.exists(rec):
        n += 1
        rec = os.path.join(runs, "%s-%d" % (name, n))
    nv = os.path.join(rec, "nvram")
    os.makedirs(nv)
    saved = {}
    for rel, src in nvram_items(root, game):
        dst = os.path.join(nv, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(src):
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst)
        saved[rel] = _sha1_tree(src)
    pivot = bool(env.get("PAD_PIVOT"))
    info = {
        "version": 1,
        "game": game,
        "boot": boot,
        "started": int(now),
        "started_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "host": env.get("WSL_DISTRO_NAME") or socket.gethostname(),
        "slot": env.get("PAD_SLOT", "0"),
        "label": env.get("PAD_LABEL", ""),
        "root": root,
        "card": _card_facts(env.get("PAD_CARD") or env.get("CARD_PATH")),
        "nvram": saved,
        # the guest's own log: game.out on a checkpointable (PAD_PIVOT) run,
        # which is what $LOG tails; read first because it is the guest's file
        "logs": ([os.path.join(root, "dump", "game.out")] if pivot else []) + [log],
        "env": {k: v for k, v in sorted(env.items()) if k.startswith("PAD_")},
    }
    if boot == "restart":
        info["levels"] = _levels(root)
    modes = launch_modes(root, env)
    if modes:
        # THE MODES THE LAUNCH BROUGHT (the Emulate tab's edits, the Modes tab's
        # Try it): installed in the rootfs before the run, and replaced by the
        # next one - so kept, as tryit.sh install takes them. A card's own modes
        # need nothing: run_game.sh installs them from the card every boot.
        os.makedirs(os.path.join(rec, "modes"))
        for p in modes:
            shutil.copy2(p, os.path.join(rec, "modes", os.path.basename(p)))
        info["modes"] = sorted(os.path.basename(p) for p in modes)
    edits = env.get("PAD_OVERRIDE_DIR")
    if edits:
        info["edits"] = edits_facts(edits)
    with open(os.path.join(rec, "run.json"), "w") as f:
        json.dump(info, f, indent=1)
    with open(os.path.join(runs, CURRENT), "w") as f:
        f.write(os.path.basename(rec) + "\n")
    prune(logdir, int(env.get("PAD_RUN_KEEP") or KEEP))
    _chown_tree(runs, _owner_of(logdir))
    return rec


def record_lines(path):
    out = []
    try:
        with open(path, "rb") as f:
            for raw in f:
                if b"[sw]" in raw or b"[swspin]" in raw or b"[pause]" in raw:
                    out.extend(m.group(0) for m in RECORD_LINE.finditer(raw.decode("utf-8", "replace")))
    except OSError:
        pass
    return out


def finish(logdir, note=""):
    """Write the current boot's switches.log; returns the recording, or None.
    `note` says why it ended early (loadgame.sh: a save state replaced the
    game, and what follows is not this boot's to replay)."""
    runs = runs_dir(logdir)
    try:
        with open(os.path.join(runs, CURRENT)) as f:
            rec = os.path.join(runs, f.read().strip())
    except OSError:
        return None
    try:
        os.remove(os.path.join(runs, CURRENT))
    except OSError:
        pass
    try:
        with open(os.path.join(rec, "run.json")) as f:
            info = json.load(f)
    except (OSError, ValueError):
        return None
    lines = []
    for log in info.get("logs", []):
        # this boot's log only: one written since the boot began (another run in
        # this slot since then would have truncated it first)
        try:
            if os.path.getmtime(log) + 2 < info.get("started", 0):
                continue
        except OSError:
            continue
        lines = record_lines(log)
        if lines:
            break
    with open(os.path.join(rec, SWITCHES), "w") as f:
        f.write("".join(l + "\n" for l in lines))
    info["ended"] = int(time.time())
    if note:
        info["note"] = note
    info["switch_lines"] = sum(1 for l in lines if l.startswith("[sw]"))
    with open(os.path.join(rec, "run.json"), "w") as f:
        json.dump(info, f, indent=1)
    _chown_tree(rec, _owner_of(logdir))
    return rec


def recordings(logdir):
    """Recording folders, newest first."""
    runs = runs_dir(logdir)
    try:
        names = [n for n in os.listdir(runs) if os.path.isfile(os.path.join(runs, n, "run.json"))]
    except OSError:
        return []
    return [os.path.join(runs, n) for n in sorted(names, reverse=True)]


def prune(logdir, keep=KEEP):
    runs = runs_dir(logdir)
    try:
        with open(os.path.join(runs, CURRENT)) as f:
            current = f.read().strip()
    except OSError:
        current = ""
    for rec in recordings(logdir)[max(keep, 1):]:
        if os.path.basename(rec) != current:
            shutil.rmtree(rec, ignore_errors=True)


def restore(rec, root):
    """Put the recording's NVRAM back into <root>/data, replacing what the rig
    has of that title, owned by whoever owns <root>/data (the game must own its
    NVRAM - watch.sh refuses a run that does not). Returns the paths written."""
    with open(os.path.join(rec, "run.json")) as f:
        info = json.load(f)
    game = info["game"]
    data = os.path.join(root, "data")
    os.makedirs(data, exist_ok=True)
    owner = _owner_of(data)
    for rel, path in nvram_items(root, game):     # what the rig has now goes,
        if os.path.isdir(path) and not os.path.islink(path):  # so nothing of it
            shutil.rmtree(path)                    # outlives the recording's
        else:
            os.remove(path)
    written = []
    for rel in info.get("nvram", {}):
        src, dst = os.path.join(rec, "nvram", rel), os.path.join(data, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(src):
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst)
        _chown_tree(dst, owner)
        written.append(dst)
    return written


#: What a replay must NOT take from the recording: where THIS rig's paths and
#: windows are (the replay is another slot), and the helpers the replay turns
#: off or drives itself (swreplay.py's docstring says why).
REPLAY_DROP = {
    "PAD_SLOT", "PAD_LABEL", "PAD_ROOT", "PAD_TABLES", "PAD_STAGE", "PAD_LOGDIR", "PAD_CARDS", "PAD_AUDIO_PORT",
    "PAD_PATHS_SLOT", "PAD_SLOTDIR", "PAD_SLOTS_MAX", "PAD_BASE_ROOT", "PAD_HOME", "PAD_ROOT_WSL", "PAD_WSL_DISTRO",
    "PAD_WINPYTHON", "PAD_HIDDEN", "PAD_AUDIO", "PAD_PLAYFIELD", "PAD_SPEED", "PAD_BALL_FEED", "PAD_AUTO_ATTRACT",
    "PAD_RECORD", "PAD_RUN_KEEP", "PAD_TICKET", "PAD_SHIM_GAME_PID", "PAD_PIVOT", "PAD_RESTORE_KILL",
}


def replay_env(rec, env=None):
    """(the recording's launch settings a replay boots with, [warnings])."""
    env = os.environ if env is None else env
    with open(os.path.join(rec, "run.json")) as f:
        info = json.load(f)
    keep = {k: v for k, v in info.get("env", {}).items() if k not in REPLAY_DROP}
    warn = []
    if info.get("modes"):
        keep["PAD_MODE_SO"] = info["env"].get("PAD_MODE_SO") or "/lib/pad_mode.so"
    here = env.get("WSL_DISTRO_NAME")
    if here and info.get("host") and here != info["host"]:
        warn.append("recorded in %s, replayed in %s: the card and edit paths are %s's" % (
            info["host"], here, info["host"]))
    card = info.get("card") or {}
    now = _card_facts(card.get("path"))
    if card.get("path") and (now or {}).get("size") is None:
        warn.append("the card %s is not there any more" % card["path"])
    elif card.get("size") is not None and now["size"] != card["size"]:
        # the size only: every boot mounts the card's partitions, which moves
        # the image's mtime (measured: the cache's copy, 4 s before the run)
        warn.append("the card %s has changed since the run" % card["path"])
    edits = info.get("edits")
    if edits and edits_facts(edits["path"])["manifest_sha1"] != edits.get("manifest_sha1"):
        warn.append("the edits folder %s holds another set now (the project's edits changed since)" % edits["path"])
    speed = info.get("env", {}).get("PAD_SPEED")
    if speed and speed != "1":
        warn.append("the run went at x%s; the replay goes at x1 and times by the raw clock" % speed)
    if info.get("boot") == "restart":
        warn.append("this boot was a Restart game: the replay starts from a fresh session's switches")
    if info.get("note"):
        warn.append(info["note"])
    return keep, warn


def _sh(v):
    return "'" + v.replace("'", "'\\''") + "'"


def main(argv):
    if len(argv) >= 5 and argv[0] == "start":
        rec = start(argv[1], argv[2], argv[3], argv[4], argv[5] if len(argv) > 5 else "start")
        with open(os.path.join(rec, "run.json")) as f:
            n = len(json.load(f)["nvram"])
        print("[watch] recording this run: %s (the title's NVRAM as the game starts%s; its switch log is"
              " added when the run ends)" % (rec, "" if n else " - it has none yet"))
        return 0
    if len(argv) in (2, 3) and argv[0] == "finish":
        rec = finish(argv[1], argv[2] if len(argv) > 2 else "")
        if rec:
            with open(os.path.join(rec, "run.json")) as f:
                n = json.load(f).get("switch_lines", 0)
            print("[watch] recorded %d switch changes beside the NVRAM in %s" % (n, rec))
        return 0
    if len(argv) == 2 and argv[0] == "list":
        for rec in recordings(argv[1]):
            with open(os.path.join(rec, "run.json")) as f:
                info = json.load(f)
            print("%s\t%s\t%s\t%s switch changes\t%s" % (
                rec, info.get("started_text", ""), info["game"],
                info.get("switch_lines", "?"), (info.get("card") or {}).get("path", "")))
        return 0
    if len(argv) == 2 and argv[0] == "env":
        keep, warn = replay_env(argv[1])
        for w in warn:
            print("[replay] NOTE: " + w, file=sys.stderr)
        for k, v in sorted(keep.items()):
            print("export %s=%s" % (k, _sh(v)))
        return 0
    if len(argv) == 3 and argv[0] == "restore":
        for p in restore(argv[1], argv[2]):
            print("[replay] NVRAM put back: %s" % p)
        return 0
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
