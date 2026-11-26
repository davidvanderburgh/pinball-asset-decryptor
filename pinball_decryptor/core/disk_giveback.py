"""Give the space freed inside the app's WSL disks back to Windows when the
app closes (PAD-1458), or while it stays open at a quiet moment (PAD-1600).

WHY. A WSL disk file only ever grows: the space keeper (core/space_keeper.py,
PAD-613) deletes unused emulator games, card copies and leftovers inside
PAD-Runtime, but the ``ext4.vhdx`` keeps its size (``--set-sparse`` is
disabled by WSL), so the user's C: never got that space back.  The only way
was Manage disk space > Reclaim: a button, Administrator, WSL shut down.  On
David's PC one ticket's compactions gave back PAD-Runtime 88.9 -> 65.5 GB.

WHEN. A look at most daily - at once after a clean-up that freed more than
the slack (``space_keeper.owe_giveback``) - and a disk is given back when it
holds its slack (:func:`space_keeper.giveback_slack`: 5 GB or 10% of the
file, whichever is larger) more than it uses.  Two places look:

* the app's close (a hidden helper, below), and
* the open app itself (:func:`run_when_quiet`, PAD-1600): a user who leaves
  the app open used to get nothing back.  Only once nobody has touched the
  PC for :data:`QUIET_IDLE_S` and the app has no job of its own on (an
  extract, a build, a card write, the disk window at work), so nobody is at
  a button that would need WSL while it is down; inside the pause the app's
  own short wsl.exe calls are let finish, and one still open after
  :data:`OWN_WSL_WAIT_S` (an emulator) is a reason to wait.

Either way only when NOTHING RUNS - the rules proven in
``tools/spike2_emu/padcompact.ps1`` (PAD-1453):

* a rig lease touched in the last 10 minutes,
* any ``wsl.exe`` still open on Windows (every emulator the app starts, a
  Linux terminal, VS Code), the app opened again,
* a distro running besides the app's own (Docker Desktop, the user's Ubuntu:
  ``wsl --shutdown`` would stop them),
* inside Linux: a ticket-tagged or rig process, an emulator with a game
  running, a card mount, anything open under ``/mnt/wsl`` or the emulators'
  folders;

and every check FAILS CLOSED: one that cannot answer is a reason to wait.

HOW. No Administrator and no scheduled task: Windows' own virtual-disk API
compacts an unattached VHDX as an ordinary user
(:func:`wsl_disk.virtdisk_compact`).  fstrim first (so the deleted blocks are
unmapped), then WSL is shut down right before each disk and the compact
retried, since anything calling wsl.exe restarts it within seconds.

The close starts this as a hidden helper (``--disk-giveback <pid>``), which
waits for the app to be gone.  What it did goes in the space keeper's record:
"Gave back 23.4 GiB to Windows".  ``PAD_DISK_GIVEBACK=0`` turns it off; the
keeper's "Clean up automatically" box does too.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import threading
import time

from . import space_keeper, wsl_disk

log = logging.getLogger(__name__)

_FLAGS = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
          | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))

#: rig leases touched this recently mean a rig is in use (padcompact.ps1)
LEASE_FRESH_S = 600
#: how long the helper waits for the app to finish closing
APP_EXIT_WAIT_S = 300
#: PAD-1600: the open app gives back only once the PC has had no keyboard or
#: mouse input this long...
QUIET_IDLE_S = 10 * 60
#: ...and, WSL paused, waits this long for its own wsl.exe calls to end
OWN_WSL_WAIT_S = 60

#: a disk file's size after its compact (a hook for tests)
_file_size = os.path.getsize


def _slack_bytes(size=0):
    """What a disk file of *size* may hold spare before it is given back."""
    # support / proof override, in GB
    v = os.environ.get("PAD_GIVEBACK_SLACK_GB")
    try:
        if v:
            return int(float(v) * 1024 ** 3)
    except ValueError:
        pass
    return space_keeper.giveback_slack(size)


def disabled():
    return bool(os.environ.get("PAD_DISK_GIVEBACK") == "0"
                or space_keeper.disabled()
                or not space_keeper.auto_enabled())


# ---------------------------------------------------------------------------
# The disks
# ---------------------------------------------------------------------------

def disks():
    """``[{name, vhdx, mount}]``: the app's Linux and the disks it mounts into
    WSL, those that exist.  ``mount`` is where the filesystem is seen from
    the app's distro (its own root for the distro)."""
    out = []
    name, vhdx = wsl_disk._default_distro_vhdx()
    if vhdx:
        out.append({"name": name or "the app's Linux", "vhdx": vhdx,
                    "mount": "/", "distro": True})
    try:
        from . import rigdata
        out += [
            {"name": "rigs' data disk", "vhdx": rigdata.disk_path(),
             "mount": rigdata.MOUNT},
            {"name": "card store", "vhdx": rigdata.cards_disk_path(),
             "mount": rigdata.CARDS_MOUNT},
            {"name": "card cache", "vhdx": rigdata.cache_disk_path(),
             "mount": "/mnt/wsl/" + rigdata.CACHE_DISK_MOUNT_NAME},
        ]
    except Exception:                                   # noqa: BLE001
        pass
    # PAD-1599: the previous Linux, once the app's leftovers in it are gone
    # and its disk file still owes the space (old_distro: the press found
    # WSL busy).  ``old`` names it: no slack rule, it was trimmed already.
    try:
        from . import old_distro
        out += [{"name": "%s (what the app left there)" % o["name"],
                 "vhdx": o["vhdx"], "mount": None, "old": o["name"]}
                for o in old_distro.owed()]
    except Exception:                                   # noqa: BLE001
        pass
    seen, keep = set(), []
    for d in out:
        try:
            d["size"] = os.path.getsize(d["vhdx"])
        except OSError:
            continue
        k = os.path.normcase(os.path.abspath(d["vhdx"]))
        if k not in seen:
            seen.add(k)
            keep.append(d)
    return keep


def due(now=None, st=None, disk_list=None):
    """Worth a look at all: Windows, not turned off, a day since the last
    look or a clean-up that owes one since, and a disk file big enough to
    hold the slack.  Reads files only - never runs wsl.exe (the close must
    stay quick)."""
    if not wsl_disk.is_supported() or disabled():
        return False
    now = time.time() if now is None else now
    st = space_keeper.load_state() if st is None else st
    dl = disks() if disk_list is None else disk_list
    if any(d.get("old") for d in dl):
        return True                     # owed since a press (PAD-1599)
    checked = float(st.get("giveback_checked") or 0)
    owed = float(st.get("giveback_owed") or 0) > checked
    if not owed and now - checked < space_keeper.GIVEBACK_EVERY_SECS:
        return False
    return any(d["size"] >= _slack_bytes(d["size"]) for d in dl)


# ---------------------------------------------------------------------------
# Is anything running?  Every check fails closed.
# ---------------------------------------------------------------------------

def _win_processes():
    """``[(pid, exe_name_lower, full_path_lower_or_'', parent_pid)]`` of
    every process."""
    import ctypes
    from ctypes import wintypes

    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(2, 0)       # TH32CS_SNAPPROCESS
    if snap in (None, wintypes.HANDLE(-1).value):
        raise OSError("could not list processes")
    out = []
    try:
        e = PE()
        e.dwSize = ctypes.sizeof(PE)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            path = ""
            h = k32.OpenProcess(0x1000, False, e.th32ProcessID)
            if h:
                buf = ctypes.create_unicode_buffer(1024)
                n = wintypes.DWORD(1024)
                if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                    path = buf.value.lower()
                k32.CloseHandle(h)
            out.append((e.th32ProcessID, e.szExeFile.lower(), path,
                        e.th32ParentProcessID))
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return out


#: the app's window title (webui/host.py APP_TITLE, and the title it sets)
APP_WINDOW = "Pinball Asset Decryptor"


def _app_windows():
    """Process ids owning a visible window titled like the app's."""
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.WinDLL("user32")
    found = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _one(hwnd, _):
        if u32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(512)
            u32.GetWindowTextW(hwnd, buf, 512)
            if APP_WINDOW in buf.value:
                pid = wintypes.DWORD()
                u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                found.append(pid.value)
        return True
    u32.EnumWindows(proto(_one), 0)
    return found


_WSL_CLIENTS = ("wsl.exe", "wslg.exe")


def _descendants(procs, me):
    """Process ids started by *me*, and by those, all the way down: a
    ``wsl.exe`` starts a second ``wsl.exe`` of its own (measured on WSL
    2.6, 2026-11-25), so a direct-children test misses half of them."""
    kids = {}
    for p in procs:
        if len(p) > 3:
            kids.setdefault(p[3], []).append(p[0])
    out, todo = set(), [me]
    while todo:
        for c in kids.get(todo.pop(), ()):
            if c not in out and c != me:
                out.add(c)
                todo.append(c)
    return out


def own_wsl_calls(procs=None, me=None):
    """Process ids of the wsl.exe this process started (the open app's status
    polls, its emulators).  Raises when the processes cannot be listed."""
    me = os.getpid() if me is None else me
    procs = _win_processes() if procs is None else procs
    mine = _descendants(procs, me)
    return [p[0] for p in procs if p[1] in _WSL_CLIENTS and p[0] in mine]


def windows_busy(procs=None, me=None, board=None, now=None, windows=None,
                 own_ok=False):
    """Reasons on the Windows side not to shut WSL down now ([] = none).
    *own_ok*: the open app asks (PAD-1600) - the wsl.exe it started itself
    are left to its own checks (they end, or show as a game in Linux)."""
    why = []
    me = os.getpid() if me is None else me
    try:
        procs = _win_processes() if procs is None else procs
        windows = _app_windows() if windows is None else windows
    except Exception as e:                              # noqa: BLE001
        return ["could not list the running programs (%s)" % e]
    mine = _descendants(procs, me) if own_ok else ()
    clients = sorted({p[1] for p in procs
                      if p[1] in _WSL_CLIENTS and p[0] != me
                      and p[0] not in mine})
    if clients:
        why.append("a Linux program is still open (%s)" % ", ".join(clients))
    # the app's window, from a Python (the app), not a browser tab or an
    # Explorer window that happens to show the name
    pyw = {p[0] for p in procs if p[1].startswith("python")}
    if any(w != me and w in pyw for w in windows):
        why.append("the app is open again")
    board = board or os.path.join(os.path.expanduser("~"), ".pad-rig")
    now = time.time() if now is None else now
    try:
        fresh = [f for f in os.listdir(board)
                 if f.endswith((".run", ".lock"))
                 and now - os.path.getmtime(os.path.join(board, f))
                 < LEASE_FRESH_S]
    except OSError:
        fresh = []
    if fresh:
        why.append("rig leases in use (%s)" % ", ".join(sorted(fresh)[:4]))
    return why


def running_distros():
    """``wsl -l --running -q`` (never starts the VM).  Raises when wsl.exe
    does not answer: the caller treats that as busy."""
    proc = subprocess.run(["wsl.exe", "-l", "--running", "-q"],
                          capture_output=True, timeout=30,
                          creationflags=wsl_disk._CREATE_FLAGS)
    names = [ln.strip().lstrip("﻿") for ln in
             wsl_disk._decode_wsl(proc.stdout or b"").splitlines()]
    known = wsl_disk._lxss_names()
    if known is None:
        if proc.returncode != 0:
            raise OSError("wsl.exe -l --running failed")
        return [n for n in names if n]
    return [n for n in names if n and n.casefold() in known]


#: One pass as root in the app's distro: what each disk's filesystem uses,
#: then anything running.  Lines: ``DF <mount> <used KiB>``, ``BUSY <what>``,
#: and ``SCAN_DONE`` last - a scan that did not finish is busy.
_SCAN = r"""
for m in @MOUNTS@; do
  mountpoint -q "$m" && printf 'DF %s %s\n' "$m" "$(df -k --output=used "$m" | tail -1 | tr -d ' ')"
done
sid() { sed 's/.*) //' /proc/$1/stat 2>/dev/null | cut -d' ' -f4; }
mine=$(sid $$)
for p in /proc/[0-9]*; do
  n=${p#/proc/}
  [ "$n" = 1 ] && continue
  # this scan's own processes (its session), and WSL's own plumbing
  s=$(sid $n); [ -z "$s" ] || [ "$s" = "$mine" ] && continue
  c=$(cat $p/comm 2>/dev/null)
  case $c in init|plan9|Relay*|SessionLeader*) continue ;; esac
  e=$(tr '\0' '\n' < $p/environ 2>/dev/null | grep -m1 -E '^PAD_(TICKET|SLOT|LABEL)=')
  [ -n "$e" ] && { echo "BUSY $c ($e)"; continue; }
  case $c in *qemu*|fuse2fs|*pinmame*|*mame*|unicorn*) echo "BUSY emulator $c"; continue ;; esac
  tr '\0' ' ' < $p/cmdline 2>/dev/null | grep -qE '/var/tmp/(pad_|jjp_)' && { echo "BUSY $c runs a game"; continue; }
  readlink $p/cwd $p/fd/* 2>/dev/null | grep -qE '^/mnt/wsl/|^/var/tmp/(pad_|jjp_)' && echo "BUSY $c has a game disk open"
done | sort -u | head -8
for b in /sys/block/loop*/loop/backing_file; do
  [ -f "$b" ] || continue
  f=$(cat "$b"); case $f in /var/lib/snapd/*) continue ;; esac
  echo "BUSY a card image is mounted ($f)"
done | head -3
echo SCAN_DONE
"""


def scan_script(mounts):
    q = " ".join("'%s'" % m.replace("'", "") for m in mounts)
    return _SCAN.replace("@MOUNTS@", q or "/")


def parse_scan(text):
    used, busy, done = {}, [], False
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if ln == "SCAN_DONE":
            done = True
        elif ln.startswith("DF "):
            parts = ln.split()
            if len(parts) == 3 and parts[2].isdigit():
                used[parts[1]] = int(parts[2]) * 1024
        elif ln.startswith("BUSY "):
            busy.append(ln[5:])
    if not done:
        busy.append("Linux could not be checked")
    return used, busy


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

def _say(msg):
    """One line in compact.log beside the keeper's state (padcompact.ps1's
    log too), and the module log."""
    log.info("disk give-back: %s", msg)
    try:
        p = os.path.join(os.path.dirname(space_keeper.state_path()),
                         "compact.log")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError:
        pass


def _gb(n):
    return "%.1f GB" % (n / 1024 ** 3)


def run(force=False, dry_run=False, now=None, disk_list=None, release=None,
        compact=None, busy_host=None, distros=None, wsl_script=None,
        trim=None, app_busy=None, own_calls=None, sleep=time.sleep):
    """One give-back.  Returns its record: ``{"at", "freed", "disks"}`` when it
    compacted, else ``{"skipped": why}`` / ``{"busy": [why...]}`` /
    ``{"would": [names]}`` (dry run).

    *app_busy* (``callable() -> [why...]``) means the OPEN APP runs it
    (PAD-1600): its own wsl.exe calls do not count as busy at first, and
    with WSL paused they get :data:`OWN_WSL_WAIT_S` to end before the last
    look.  The other keyword hooks are for tests."""
    now = time.time() if now is None else now
    in_app = app_busy is not None
    release = release or wsl_disk._shutdown_until_free
    compact = compact or wsl_disk.virtdisk_compact
    if busy_host is None:
        def busy_host(strict=False):
            return windows_busy(own_ok=in_app and not strict)
    own_calls = own_calls or own_wsl_calls
    distros = distros or running_distros
    wsl_script = wsl_script or (
        lambda s: wsl_disk._wsl_script(s, timeout=600))
    trim = trim or (lambda: wsl_disk._wsl_bash(
        "/usr/sbin/fstrim -av 2>&1 || fstrim -av 2>&1 || true", timeout=1800))

    dl = disks() if disk_list is None else disk_list
    if not force and not due(now, disk_list=dl):
        return {"skipped": "not due"}
    owed = [d for d in dl if d.get("old")]
    big = [d for d in dl if not d.get("old")
           and d["size"] >= _slack_bytes(d["size"])]
    if not big and not owed:
        space_keeper.record_giveback(checked=now)
        return {"skipped": "no disk is big enough to hold %s spare"
                % _gb(_slack_bytes())}

    why = list(app_busy()) if in_app else []
    why += list(busy_host())
    try:
        app = runtime_distro()
        others = [n for n in distros() if n.casefold() != (app or "").casefold()]
        if others:
            why.append("%s %s running" % (", ".join(others),
                                          "is" if len(others) == 1 else "are"))
    except Exception as e:                              # noqa: BLE001
        why.append("WSL did not say what is running (%s)" % e)
    if why:
        _say("not now - " + " | ".join(why))
        return {"busy": why}

    try:
        used, busy = parse_scan(wsl_script(scan_script(
            [d["mount"] for d in big])))
    except Exception as e:                              # noqa: BLE001
        used, busy = {}, ["Linux could not be checked (%s)" % e]
    if busy:
        _say("not now - " + " | ".join(busy))
        return {"busy": busy}

    todo = []
    for d in big:
        u = used.get(d["mount"])
        if u is None:
            _say("%s: %s file, not mounted - skipped" % (d["name"],
                                                         _gb(d["size"])))
            continue
        _say("%s: %s file, %s used, %s to give back"
             % (d["name"], _gb(d["size"]), _gb(u), _gb(d["size"] - u)))
        if d["size"] - u >= _slack_bytes(d["size"]):
            todo.append(d)
    for d in owed:
        _say("%s: %s file, its leftovers removed - giving it back"
             % (d["name"], _gb(d["size"])))
        todo.append(d)
    if not todo:
        space_keeper.record_giveback(checked=now)
        _say("nothing holds its slack (%s, or 10%% of the file) more "
             "than it uses" % _gb(_slack_bytes()))
        return {"skipped": "nothing to give back"}
    if dry_run:
        return {"would": [d["name"] for d in todo]}

    try:
        trim()
    except Exception as e:                              # noqa: BLE001
        _say("fstrim failed (%s) - compacting what it can" % e)

    done = []
    with wsl_disk.wsl_paused():
        # the last look before WSL goes down, with nothing new from this
        # process able to start: the app reopened, a terminal, a job...
        why = _last_look(in_app, app_busy, busy_host, own_calls, sleep)
        if why:
            _say("not now - " + " | ".join(why))
            return {"busy": why}
        for d in todo:
            before = d["size"]
            err = None
            for attempt in (1, 2, 3, 4):
                try:
                    release(d["vhdx"])
                    compact(d["vhdx"])
                    err = None
                    break
                except Exception as e:                  # noqa: BLE001
                    err = e
                    if getattr(e, "errno", None) != 32:
                        break
                    _say("%s: WSL took the disk back (try %d) - again"
                         % (d["name"], attempt))
            try:
                after = _file_size(d["vhdx"])
            except OSError:
                after = before
            if err is not None:
                _say("%s: not compacted (%s)" % (d["name"], err))
            elif d.get("old"):
                from . import old_distro
                old_distro.done(d["old"], before, after)
            _say("%s: %s -> %s" % (d["name"], _gb(before), _gb(after)))
            done.append({"name": d["name"], "before": before, "after": after})
    freed = sum(max(0, x["before"] - x["after"]) for x in done)
    rec = {"at": now, "freed": freed, "disks": done}
    space_keeper.record_giveback(rec)
    _say("gave back %s to Windows" % _gb(freed))
    return rec


def _last_look(in_app, app_busy, busy_host, own_calls, sleep):
    """Reasons not to shut WSL down, looked at with WSL paused.  In the open
    app its own short wsl.exe calls (status polls) get OWN_WSL_WAIT_S to end
    first; one still open is a job of its own (an emulator)."""
    if in_app:
        try:
            left = own_calls()
            waited = 0
            while left and waited < OWN_WSL_WAIT_S:
                sleep(1)
                waited += 1
                left = own_calls()
        except Exception as e:                          # noqa: BLE001
            return ["could not list the running programs (%s)" % e]
        if left:
            return ["the app's own Linux program is still open"]
        why = list(app_busy())
        return why + list(busy_host(strict=True))
    return list(busy_host())


def runtime_distro():
    """The distro the app runs in (its own PAD-Runtime, or the default)."""
    name, _ = wsl_disk._default_distro_vhdx()
    return name


# ---------------------------------------------------------------------------
# The open app, at a quiet moment (PAD-1600)
# ---------------------------------------------------------------------------

def idle_seconds():
    """Seconds since the last keyboard or mouse input on this PC (Windows'
    GetLastInputInfo), 0 when it cannot be told."""
    if sys.platform != "win32":
        return 0
    import ctypes
    from ctypes import wintypes

    class LII(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]
    lii = LII()
    lii.cbSize = ctypes.sizeof(LII)
    try:
        if not ctypes.WinDLL("user32").GetLastInputInfo(ctypes.byref(lii)):
            return 0
        tick = ctypes.WinDLL("kernel32").GetTickCount() & 0xFFFFFFFF
    except Exception:                                   # noqa: BLE001
        return 0
    return ((tick - lii.dwTime) & 0xFFFFFFFF) / 1000.0


_in_app_lock = threading.Lock()


def run_when_quiet(app_busy, idle=None, **kw):
    """The open app's give-back: when one is due, the PC has been left alone
    for QUIET_IDLE_S and *app_busy()* names nothing of the app's own at
    work.  Never asks for Administrator, never says anything; returns the
    run's record (``{"skipped"}`` / ``{"busy"}`` when it did nothing)."""
    if not due(disk_list=kw.get("disk_list")):
        return {"skipped": "not due"}
    quiet = (idle or idle_seconds)()
    if quiet < QUIET_IDLE_S:
        return {"busy": ["the PC is in use (input %d s ago)" % quiet]}
    if not _in_app_lock.acquire(blocking=False):
        return {"busy": ["a give-back is already running"]}
    try:
        return run(app_busy=app_busy, **kw)
    finally:
        _in_app_lock.release()


# ---------------------------------------------------------------------------
# The close
# ---------------------------------------------------------------------------

def helper_cmd(pid):
    if getattr(sys, "frozen", False):
        return [sys.executable, "--disk-giveback", str(pid)]
    return [sys.executable, "-m", "pinball_decryptor", "--disk-giveback",
            str(pid)]


def start_after_close(pid=None, popen=None):
    """Called by the app's close: start the hidden helper when a give-back may
    be due.  Never raises, never runs wsl.exe itself.  True when started."""
    try:
        # a test that closes an App never starts a real helper on the PC
        if (os.environ.get("PYTEST_CURRENT_TEST") and popen is None) \
                or not due():
            return False
        pid = os.getpid() if pid is None else pid
        env = dict(os.environ)
        # the helper runs from the app's package, wherever this one was
        pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        env["PYTHONPATH"] = pkg_root + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        (popen or subprocess.Popen)(
            helper_cmd(pid), cwd=tempfile.gettempdir(), env=env,
            creationflags=_FLAGS, close_fds=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:                                   # noqa: BLE001
        log.exception("disk give-back: could not start the helper")
        return False


def _wait_pid(pid, timeout):
    if sys.platform != "win32" or not pid:
        return
    import ctypes
    k32 = ctypes.WinDLL("kernel32")
    k32.OpenProcess.restype = ctypes.c_void_p
    h = k32.OpenProcess(0x00100000, False, int(pid))    # SYNCHRONIZE
    if not h:
        return                                          # already gone
    try:
        k32.WaitForSingleObject(ctypes.c_void_p(h), int(timeout * 1000))
    finally:
        k32.CloseHandle(ctypes.c_void_p(h))


def helper_main(argv):
    """``--disk-giveback <pid>``: wait for the app to close, then run."""
    pid = None
    try:
        pid = int(argv[argv.index("--disk-giveback") + 1])
    except (ValueError, IndexError):
        pass
    try:
        _wait_pid(pid, APP_EXIT_WAIT_S)
        # the app's last wsl.exe calls (the emulators' stop) settle first
        time.sleep(5)
        _off_main_thread(run)
    except Exception as e:                              # noqa: BLE001
        _say("failed: %s" % e)
    return 0


def _off_main_thread(fn):
    """Run *fn* on a thread of its own and wait for it.

    PAD-1599: on the MAIN thread ``runtime.status()`` never asks wsl.exe (the
    guard that keeps a UI from freezing), so ``runtime.wsl_distro()`` answered
    None and every lookup fell back to the machine's DEFAULT distro: the
    helper listed the user's own Ubuntu as "the app's Linux", ran its busy
    scan and fstrim there, and compacted it (David's record: "Ubuntu
    217 -> 206 GB") while PAD-Runtime counted as another distro running.
    The helper has no UI to freeze, so it asks from a worker thread."""
    import threading
    box = {}

    def _go():
        try:
            box["out"] = fn()
        except BaseException as e:                      # noqa: BLE001
            box["err"] = e
    t = threading.Thread(target=_go, name="pad-disk-giveback")
    t.start()
    t.join()
    if "err" in box:
        raise box["err"]
    return box.get("out")


__all__ = ["run", "due", "disks", "start_after_close", "helper_main",
           "windows_busy", "parse_scan", "scan_script", "disabled",
           "run_when_quiet", "idle_seconds", "own_wsl_calls",
           "QUIET_IDLE_S", "OWN_WSL_WAIT_S"]
