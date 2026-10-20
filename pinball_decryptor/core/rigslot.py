"""Which Spike 2 emulator rig this app drives, and who holds the others.

The rig side is ``tools/spike2_emu/padpath.sh`` ("RIG SLOTS") and
``riglock.sh``; the design is ``docs/plans/rig_slots.md``. In one paragraph:
a PC can run several emulator rigs at once, one per session. Rig 0 is the
ordinary one and what every installed copy of the app uses; rig N >= 1 is a
complete rig of its own, selected by ``PAD_SLOT=N`` in the environment of every
rig command. Who holds which rig is written to a BOARD on the Windows side
(``%USERPROFILE%\\.pad-rig``), one JSON line per file:

    slot-N.lock   {"slot","who","what","distro","user","taken"}
    slot-N.run    {"slot","game","label","distro","root","pid","started"},
                  touched every ~10 s while the run lives

This module is the app's half: the environment its rig commands carry, the
board as the Emulate tab shows it, and the rig an app launched from a triage
ticket claims for itself so that two ticket apps never share one.

NOTHING HERE CHANGES AN ORDINARY INSTALL. With no PAD_SLOT, PAD_LABEL or
PAD_TICKET in the environment, rig_env() is empty and the app drives rig 0
exactly as before; the board is only read, and an absent board reads as five
free rigs.
"""
import atexit
import json
import os
import sys
import time

#: Rigs a PC offers (padpath.sh's PAD_SLOTS_MAX).
SLOTS_MAX = 5
#: A run record whose heartbeat is older than this is a run that died hard
#: (riglock.sh's RUN_FRESH).
RUN_FRESH_S = 120

#: The six rig colours, the same ones the playfield window's band and chip
#: use (pfpage/pf.css --rig-N) and the triage dashboard draws.
COLOURS = ("#8b9196", "#4fb3d9", "#c08cf0", "#f0845d", "#6fcf8a", "#e8c04a")

_claimed = []           # [slot] this process took and must give back
_home = []              # the rigs this app has run on, last one last
_atexit = []
#: A held rig nobody has used for this long has LAPSED (riglock.sh's
#: PAD_LOCK_IDLE): anyone may take it.
IDLE_S = 300


def board_dir():
    """Where the board lives, as THIS side can open it."""
    v = os.environ.get("PAD_BOARD_WIN")         # tests, and a moved board
    if v:
        return v
    if sys.platform == "win32":
        return os.path.join(os.environ.get("USERPROFILE")
                            or os.path.expanduser("~"), ".pad-rig")
    return os.path.join(os.path.expanduser("~"), ".pad-rig")


def slot():
    """The rig this app drives: PAD_SLOT, or 0."""
    try:
        return max(0, min(SLOTS_MAX, int(os.environ.get("PAD_SLOT") or 0)))
    except ValueError:
        return 0


def label():
    """Who this app's runs are for: PAD_LABEL, else the triage ticket."""
    return (os.environ.get("PAD_LABEL") or os.environ.get("PAD_TICKET") or "").strip()


def rig_env():
    """``NAME=value`` entries every rig command carries. Empty on an ordinary
    install - rig 0, no label - so nothing about those commands changes."""
    out = []
    if slot():
        out.append("PAD_SLOT=%d" % slot())
    if label():
        out.append("PAD_LABEL=%s" % label())
    return out


def board_env():
    """``NAME=value`` entries for the OTHER emulators' launches (AP, BoF, DP,
    JJP, Spike 1 - tools/rigboard.sh, PAD-296), so their runs post to the
    board too: where the board is, as WSL opens it (an install under Program
    Files is nowhere near the profile the tools would guess it from), and the
    triage ticket the run is for. Windows only - elsewhere there is no board
    the dashboard reads."""
    if sys.platform != "win32":
        return []
    from ..webui.rig import wsl_path
    out = ["PAD_BOARD=%s" % wsl_path(board_dir())]
    if label():
        out.append("PAD_TICKET=%s" % label())
    return out


def agent_driven():
    """This app was started from a Claude Code session: Claude Code sets
    ``CLAUDECODE=1`` in every command it runs, and an app started by one of
    them inherits it. David's own starts - the shortcut, the installer, the
    triage dashboard's launch (which drops it, PAD-309) - never carry it."""
    return bool((os.environ.get("CLAUDECODE") or "").strip())


def hidden():
    """Whether this app's emulator runs stay off the desktop (PAD-309).

    David, 2026-10-01: "shouldn't the rigs always be headless (no window)
    when running?" - for a session's runs, yes: an agent driving this app
    put a visible, sounding game and its playfield on his desktop for a
    ticket already released. So an app a session started runs every
    emulator hidden; ``PAD_HIDDEN=0`` in its environment shows them (when
    David asks to watch), ``PAD_HIDDEN=1`` hides them for anyone."""
    v = (os.environ.get("PAD_HIDDEN") or "").strip()
    if v:
        return v != "0"
    return agent_driven()


def muted():
    """Whether this app's emulator runs are silent: every hidden run (a sound
    nobody can find the source of is the worst case, PAD-266), and a
    session's run unless its environment says ``PAD_AUDIO=1``."""
    v = (os.environ.get("PAD_AUDIO") or "").strip()
    if hidden() or v == "0":
        return True
    return agent_driven() and v != "1"


def quiet_env():
    """``NAME=value`` entries every emulator Start puts LAST in its list -
    env(1) applies them in order, so these win over the tab's own
    ``PAD_VISIBLE=1`` / ``PAD_AUDIO=1`` (PAD-309).

    Hidden: ``PAD_HIDDEN=1`` (Spike 2's watch.sh) and ``PAD_VISIBLE=0`` (every
    other emulator's). Muted: ``PAD_AUDIO=0``. Otherwise ``PAD_HIDDEN=0``,
    said out loud because a run labelled for a ticket hides by default on the
    rig side - and a ticket's app, which David opens to see the change, labels
    its runs."""
    if hidden():
        out = ["PAD_HIDDEN=1", "PAD_VISIBLE=0"]
    else:
        out = ["PAD_HIDDEN=0"]
    if muted():
        out.append("PAD_AUDIO=0")
    return out


def title_tag():
    """The app window's own tag, in the words the rig's windows use."""
    n, l = slot(), label()
    if n:
        return "rig %d%s" % (n, (": " + l) if l else "")
    return l        # a ticket's app before its first run: no rig yet


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            rec = json.loads(fh.readline() or "null")
        return rec if isinstance(rec, dict) else None, os.path.getmtime(path)
    except (OSError, ValueError):
        return None, 0


def board(now=None):
    """Every rig, as the Emulate tab and the triage dashboard show it:
    [{"slot", "colour", "holder", "doing", "held_s", "run": {...} | None}]."""
    now = now or time.time()
    d = board_dir()
    # A LAPSED lock is cleared, not only shown (riglock.sh sweep()): the
    # Emulate tab reads this every few seconds, so an unused lock goes away
    # whether or not any session runs riglock.sh.
    for n in range(0, SLOTS_MAX + 1):
        if state(n, now) == "lapsed":
            _seize(n)
    out = []
    cps = copies(now)
    for n in range(0, SLOTS_MAX + 1):
        lock, lm = _read(os.path.join(d, "slot-%d.lock" % n))
        run, rm = _read(os.path.join(d, "slot-%d.run" % n))
        row = {"slot": n, "colour": COLOURS[n], "holder": "", "doing": "",
               "held_s": None, "distro": "", "run": None, "mine": n == slot(),
               "state": state(n, now), "idle_s": None, "copy": None}
        if row["state"] in ("active", "lapsed"):
            row["idle_s"] = int(now - max(lm, rm))
        if lock:
            row.update(holder=str(lock.get("who") or ""),
                       doing=str(lock.get("what") or ""),
                       held_s=int(now - (lock.get("taken") or lm)),
                       distro=str(lock.get("distro") or ""))
        if run:
            row["run"] = {"game": str(run.get("game") or ""),
                          "label": str(run.get("label") or ""),
                          "up_s": int(now - (run.get("started") or rm)),
                          "stale": (now - rm) > RUN_FRESH_S,
                          "distro": str(run.get("distro") or ""),
                          # the game's clock against the wall's (watch.sh, PAD-649): 4 while a
                          # sweep runs sped up; an older record has none, so 1
                          "speed": _speed(run.get("speed"))}
        row["copy"] = copy_for(row, cps)        # the card copy this rig waits on (PAD-649)
        out.append(row)
    return out


#: A copy record nobody has touched for this long is a copier that died.
COPY_FRESH_S = 90


def card_title(card):
    """``dungeons_and_dragons_le-1_10_0_spike2.Release.16G.sdcard.raw`` ->
    ``Dungeons And Dragons LE 1.10``: the card's name as a person reads it."""
    name = os.path.basename(str(card or ""))
    name = name.split(".Release")[0]
    if name.endswith(".raw"):
        name = name[:-4]
    key, _, ver = name.partition("-")
    words = [w for w in key.replace("_", " ").split() if w]
    eds = {"le": "LE", "pro": "Pro", "prem": "Premium", "premium": "Premium", "se": "SE"}
    title = " ".join(eds.get(w.lower(), w.capitalize()) for w in words)
    parts = [p for p in ver.split("_") if p.isdigit()]
    if len(parts) >= 2:
        title += " " + parts[0] + "." + parts[1]
    return title


def copies(now=None):
    """The card copies on the board (cardmount.sh copy_board_write, PAD-649):
    [{"label","card","title","who","state","pct","done_mb","total_mb"}],
    fresh ones only."""
    now = now or time.time()
    d = board_dir()
    out = []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for n in names:
        if not (n.startswith("copy-") and n.endswith(".json")):
            continue
        rec, m = _read(os.path.join(d, n))
        if not rec or (now - m) > COPY_FRESH_S:
            continue
        try:
            pct = max(0, min(100, int(rec.get("pct") or 0)))
        except (TypeError, ValueError):
            pct = 0
        out.append({"label": str(rec.get("label") or n[5:-5]),
                    "card": str(rec.get("card") or ""),
                    "title": card_title(rec.get("card") or rec.get("label")),
                    "who": str(rec.get("who") or ""),
                    "state": "queued" if rec.get("state") == "queued" else "copying",
                    "pct": pct, "done_mb": int(rec.get("done_mb") or 0),
                    "total_mb": int(rec.get("total_mb") or 0)})
    return out


def copy_for(row, copies_):
    """The copy a rig waits on: its lock says "waiting for its card: <label>"
    (rigbatch.sh); failing a record for that label, the same holder's copy
    that is running, else its first queued one."""
    doing = row.get("doing") or ""
    if "waiting for its card" not in doing:
        return None
    label = doing.split("waiting for its card:", 1)[1].strip(" )") \
        if "waiting for its card:" in doing else ""
    mine = [c for c in copies_ if c["who"] and c["who"] == row.get("holder")]
    for c in mine:
        if label and c["label"] == label:
            return c
    for c in mine:
        if c["state"] == "copying":
            return c
    return mine[0] if mine else None


def _speed(v):
    try:
        k = float(v)
    except (TypeError, ValueError):
        return 1.0
    return k if k > 0 else 1.0


def speed_text(k):
    """4.0 -> "4x", 0.5 -> "0.5x", 1 -> "" (real time says nothing)."""
    k = _speed(k)
    if abs(k - 1.0) < 1e-6:
        return ""
    return ("%g" % k) + "x"


def _lock_path(n):
    return os.path.join(board_dir(), "slot-%d.lock" % n)


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _running(n, now=None):
    """A run record with a heartbeat: a run is up in rig n."""
    rm = _mtime(os.path.join(board_dir(), "slot-%d.run" % n))
    return rm is not None and (now or time.time()) - rm < RUN_FRESH_S


def state(n, now=None):
    """riglock.sh's lease, read from the board: "free", "running" (a run
    record with a heartbeat), "active" (its holder used it in the last
    IDLE_S) or "lapsed" (held, unused since - anyone may take it)."""
    now = now or time.time()
    lm = _mtime(_lock_path(n))
    if lm is None:
        return "free"
    if _running(n, now):
        return "running"
    rm = _mtime(os.path.join(board_dir(), "slot-%d.run" % n)) or 0
    return "active" if now - max(lm, rm) < IDLE_S else "lapsed"


def _take(n, who, what):
    d = board_dir()
    os.makedirs(d, exist_ok=True)
    rec = {"slot": n, "who": who, "what": what, "distro": "windows",
           "user": os.environ.get("USERNAME") or os.environ.get("USER") or "",
           "taken": int(time.time())}
    try:
        with open(_lock_path(n), "x", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
        return True
    except OSError:
        return False


def _seize(n):
    """Take a LAPSED lock off its old holder - riglock.sh's seize(): the rename
    is the atomic step, and the moved file is judged again in case its holder
    used the rig between our look and our move (then it goes back)."""
    path = _lock_path(n)
    tmp = "%s.seize.%d" % (path, os.getpid())
    try:
        os.rename(path, tmp)
    except OSError:
        return False
    try:
        if time.time() - os.path.getmtime(tmp) < IDLE_S or _running(n):
            try:
                with open(tmp, encoding="utf-8", errors="replace") as old:
                    back = old.read()
                with open(path, "x", encoding="utf-8") as fh:
                    fh.write(back)
            except OSError:
                pass
            return False
        return True
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _mine(n):
    lock, _ = _read(_lock_path(n))
    return bool(lock) and lock.get("who") == label()


def release_claimed():
    """Give back the rig claim_for_run() took - only ours, only while no run
    of ours is up in it. Stop calls this; so does the app's exit."""
    while _claimed:
        n = _claimed.pop()
        if _mine(n) and not _running(n):
            try:
                os.remove(_lock_path(n))
            except OSError:
                pass


def claim_for_run():
    """The rig an app launched for a triage ticket runs on - taken at START,
    given back at Stop (riglock.sh, "A LOCK IS A LEASE").

    Until 2026-09-27 the app took its rig when its window opened and held it
    until the window closed: three ticket windows held three idle rigs, a
    killed window held one forever, and a merged ticket's window still held
    one. Now the rig is taken only for a run. The one this app ran on last is
    asked for first (its NVRAM and save states are in that rig), then a free
    one, then a lapsed one. Returns the rig; 0 with no ticket or when the app
    was launched on a chosen rig (PAD_SLOT, which is then simply used); None
    when every rig is in use by someone else - the caller refuses the Start.
    """
    if not os.environ.get("PAD_TICKET"):
        return slot()
    if os.environ.get("PAD_SLOT") and not _home:
        return slot()                   # launched on a chosen rig
    order = list(_home[-1:]) + [n for n in range(1, SLOTS_MAX + 1)
                                if n not in _home[-1:]]

    def got(n):
        os.environ["PAD_SLOT"] = str(n)
        if n not in _claimed:
            _claimed.append(n)
        if not _home or _home[-1] != n:
            _home.append(n)
        if not _atexit:
            atexit.register(release_claimed)
            _atexit.append(True)
        return n

    for n in order:
        if _mine(n):
            os.utime(_lock_path(n), None)
            return got(n)
    for n in order:
        if state(n) == "free" and _take(n, label(), "app run"):
            return got(n)
    for n in order:
        if state(n) == "lapsed" and _seize(n) and _take(n, label(), "app run"):
            return got(n)
    return None
