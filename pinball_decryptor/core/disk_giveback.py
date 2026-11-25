"""Give the space freed inside the app's WSL disks back to Windows when the
app closes (PAD-1458).

WHY. A WSL disk file only ever grows: the space keeper (core/space_keeper.py,
PAD-613) deletes unused emulator games, card copies and leftovers inside
PAD-Runtime, but the ``ext4.vhdx`` keeps its size (``--set-sparse`` is
disabled by WSL), so the user's C: never got that space back.  The only way
was Manage disk space > Reclaim: a button, Administrator, WSL shut down.  On
David's PC one ticket's compactions gave back PAD-Runtime 88.9 -> 65.5 GB.

WHEN. The app's close (its own WSL polling stops then), at most weekly, when
one of its disks holds :data:`space_keeper.GIVEBACK_SLACK_BYTES` more than it
uses, and only when NOTHING RUNS - the rules proven in
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
import time

from . import space_keeper, wsl_disk

log = logging.getLogger(__name__)

_FLAGS = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
          | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))

#: rig leases touched this recently mean a rig is in use (padcompact.ps1)
LEASE_FRESH_S = 600
#: how long the helper waits for the app to finish closing
APP_EXIT_WAIT_S = 300

#: a disk file's size after its compact (a hook for tests)
_file_size = os.path.getsize


def _slack_bytes():
    # support / proof override, in GB
    v = os.environ.get("PAD_GIVEBACK_SLACK_GB")
    try:
        return int(float(v) * 1024 ** 3) if v else \
            space_keeper.GIVEBACK_SLACK_BYTES
    except ValueError:
        return space_keeper.GIVEBACK_SLACK_BYTES


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
    """Worth starting the helper at all: Windows, not turned off, a week since
    the last look, and a disk file big enough to hold the slack.  Reads files
    only - never runs wsl.exe (the close must stay quick)."""
    if not wsl_disk.is_supported() or disabled():
        return False
    now = time.time() if now is None else now
    st = space_keeper.load_state() if st is None else st
    dl = disks() if disk_list is None else disk_list
    if any(d.get("old") for d in dl):
        return True                     # owed since a press (PAD-1599)
    if now - float(st.get("giveback_checked") or 0) \
            < space_keeper.GIVEBACK_EVERY_SECS:
        return False
    return any(d["size"] >= _slack_bytes() for d in dl)


# ---------------------------------------------------------------------------
# Is anything running?  Every check fails closed.
# ---------------------------------------------------------------------------

def _win_processes():
    """``[(pid, exe_name_lower, full_path_lower_or_'')]`` of every process."""
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
            out.append((e.th32ProcessID, e.szExeFile.lower(), path))
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


def windows_busy(procs=None, me=None, board=None, now=None, windows=None):
    """Reasons on the Windows side not to shut WSL down now ([] = none)."""
    why = []
    me = os.getpid() if me is None else me
    try:
        procs = _win_processes() if procs is None else procs
        windows = _app_windows() if windows is None else windows
    except Exception as e:                              # noqa: BLE001
        return ["could not list the running programs (%s)" % e]
    clients = sorted({n for p, n, _ in procs
                      if n in ("wsl.exe", "wslg.exe") and p != me})
    if clients:
        why.append("a Linux program is still open (%s)" % ", ".join(clients))
    # the app's window, from a Python (the app), not a browser tab or an
    # Explorer window that happens to show the name
    pyw = {p for p, n, _ in procs if n.startswith("python")}
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
        trim=None):
    """One give-back.  Returns its record: ``{"at", "freed", "disks"}`` when it
    compacted, else ``{"skipped": why}`` / ``{"busy": [why...]}`` /
    ``{"would": [names]}`` (dry run).  The keyword hooks are for tests."""
    now = time.time() if now is None else now
    release = release or wsl_disk._shutdown_until_free
    compact = compact or wsl_disk.virtdisk_compact
    busy_host = busy_host or windows_busy
    distros = distros or running_distros
    wsl_script = wsl_script or (
        lambda s: wsl_disk._wsl_script(s, timeout=600))
    trim = trim or (lambda: wsl_disk._wsl_bash(
        "/usr/sbin/fstrim -av 2>&1 || fstrim -av 2>&1 || true", timeout=1800))

    dl = disks() if disk_list is None else disk_list
    if not force and not due(now, disk_list=dl):
        return {"skipped": "not due"}
    slack = _slack_bytes()
    owed = [d for d in dl if d.get("old")]
    big = [d for d in dl if not d.get("old") and d["size"] >= slack]
    if not big and not owed:
        space_keeper.record_giveback(checked=now)
        return {"skipped": "no disk is big enough to hold %s spare" % _gb(slack)}

    why = list(busy_host())
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
        if d["size"] - u >= slack:
            todo.append(d)
    for d in owed:
        _say("%s: %s file, its leftovers removed - giving it back"
             % (d["name"], _gb(d["size"])))
        todo.append(d)
    if not todo:
        space_keeper.record_giveback(checked=now)
        _say("nothing holds %s more than it uses" % _gb(slack))
        return {"skipped": "nothing to give back"}
    if dry_run:
        return {"would": [d["name"] for d in todo]}

    try:
        trim()
    except Exception as e:                              # noqa: BLE001
        _say("fstrim failed (%s) - compacting what it can" % e)
    # the last look before WSL goes down: the app reopened, a terminal...
    why = list(busy_host())
    if why:
        _say("not now - " + " | ".join(why))
        return {"busy": why}

    done = []
    with wsl_disk.wsl_paused():
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


def runtime_distro():
    """The distro the app runs in (its own PAD-Runtime, or the default)."""
    name, _ = wsl_disk._default_distro_vhdx()
    return name


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
        run()
    except Exception as e:                              # noqa: BLE001
        _say("failed: %s" % e)
    return 0


__all__ = ["run", "due", "disks", "start_after_close", "helper_main",
           "windows_busy", "parse_scan", "scan_script", "disabled"]
