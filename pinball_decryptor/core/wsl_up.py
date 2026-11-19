"""Is WSL (or one distro in it) running?  Asked WITHOUT starting it (PAD-1457).

Every ``wsl.exe -d X ...`` boots the WSL VM and distro X if they are down, so
a status question asked that way keeps WSL up for as long as the app polls:
the installed app was launching wsl.exe once a second on the Home tab, and
``wsl --shutdown`` was undone within two seconds, every time.

The answer here costs no boot:

* the VM: its worker process (``vmmemWSL``; ``vmmem`` on older Windows, where
  it may also be another Hyper-V VM, so it only means "maybe") is looked for
  in the Windows process list - no wsl.exe at all.  No VM, no distro.
* a distro, only when the VM is up: ``wsl.exe -l --running -q``, which lists
  and never starts anything, cached for :data:`RUNNING_TTL` and shared by every
  caller.

A status poll asks :func:`distro_running` first and, on False, does not run
its rig's status script at all: a distro that is not running has no game
running in it.  Off Windows (Docker on macOS) everything is "running", as
before.
"""

import os
import subprocess
import sys
import threading
import time

#: how long one ``wsl -l --running`` answer is reused
RUNNING_TTL = 5.0
#: how long one process-list answer is reused
VM_TTL = 1.0

_VM_NAMES = ("vmmemwsl", "vmmem")

_lock = threading.Lock()
_vm_cache = [0.0, None]          # [when, bool]
_run_cache = [0.0, None]         # [when, frozenset of lower-case names | None]


def _process_names():
    """Lower-case image names of every Windows process, without starting one
    (Toolhelp snapshot).  None when they cannot be read."""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = [wintypes.HANDLE,
                                    ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [wintypes.HANDLE,
                                   ctypes.POINTER(PROCESSENTRY32W)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)       # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return None
    names = set()
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            names.add(e.szExeFile.lower())
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return names


def _forced():
    """``PAD_WSL_UP=1`` / ``0`` answers every question here (tests, and a
    machine where the process check misreads)."""
    v = os.environ.get("PAD_WSL_UP", "").strip()
    return None if v == "" else v not in ("0", "false", "no")


def vm_running():
    """True when the WSL VM may be up: False ONLY when it is certainly down.
    Never starts anything."""
    forced = _forced()
    if forced is not None:
        return forced
    if sys.platform != "win32":
        return True
    now = time.monotonic()
    with _lock:
        if _vm_cache[1] is not None and now - _vm_cache[0] < VM_TTL:
            return _vm_cache[1]
    try:
        names = _process_names()
    except Exception:                                   # noqa: BLE001
        names = None
    if names is None:
        up = True                       # cannot tell: behave as before
    else:
        up = any(n in names or n + ".exe" in names for n in _VM_NAMES)
    with _lock:
        _vm_cache[0], _vm_cache[1] = now, up
    return up


def _list_running():
    out = subprocess.run(
        ["wsl.exe", "-l", "--running", "-q"], stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    raw = out.stdout or b""
    # wsl.exe writes UTF-16-LE; an exit code of non-zero with no output is
    # "no running distributions" (the message itself goes to stdout in
    # some versions, so the names are filtered against it below)
    text = raw.decode("utf-16-le", "replace") if b"\x00" in raw \
        else raw.decode("utf-8", "replace")
    names = set()
    for line in text.replace("\x00", "").splitlines():
        n = line.strip()
        if n and " " not in n:
            names.add(n.lower())
    return frozenset(names)


def running_distros():
    """Lower-case names of the distros running now; an empty set when the
    VM is down (asked of nothing), None when WSL could not say."""
    forced = _forced()
    if forced is not None:
        return None if forced else frozenset()
    if sys.platform != "win32":
        return None
    if not vm_running():
        return frozenset()
    now = time.monotonic()
    with _lock:
        if _run_cache[1] is not None and now - _run_cache[0] < RUNNING_TTL:
            return _run_cache[1]
    try:
        names = _list_running()
    except Exception:                                   # noqa: BLE001
        return None
    with _lock:
        _run_cache[0], _run_cache[1] = time.monotonic(), names
    return names


def default_distro():
    """The default distro's name from the registry (no wsl.exe), or None."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        base = r"Software\Microsoft\Windows\CurrentVersion\Lxss"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as k:
            guid = winreg.QueryValueEx(k, "DefaultDistribution")[0]
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            base + "\\" + guid) as k:
            return winreg.QueryValueEx(k, "DistributionName")[0]
    except Exception:                                   # noqa: BLE001
        return None


def distro_running(name=None):
    """True unless distro ``name`` (None = the default one) is certainly not
    running.  Never starts WSL."""
    names = running_distros()
    if names is None:
        return True
    if not names:
        return False
    if not name:
        name = default_distro()
        if not name:
            return True
    return name.lower() in names


def distro_of(cmd):
    """The distro a ``wsl.exe ...`` argv runs in: its ``-d`` /
    ``--distribution`` value, None for the default, or False when ``cmd`` is
    not a wsl.exe command at all (a Docker or remote rig)."""
    if not isinstance(cmd, (list, tuple)) or not cmd:
        return False
    if os.path.basename(str(cmd[0])).lower() not in ("wsl", "wsl.exe"):
        return False
    for i, a in enumerate(cmd[1:], 1):
        if a in ("-d", "--distribution") and i + 1 < len(cmd):
            return cmd[i + 1]
        if a in ("-e", "--exec", "--"):
            break
    return None


def cmd_would_boot(cmd, known_up=False):
    """True when running ``cmd`` would start WSL or its distro (it is a
    wsl.exe command and its distro is certainly not running).

    ``known_up``: the caller's last reading saw its game running there, so
    the distro is up as long as the VM is: only the free VM check is made
    (a running game is polled every couple of seconds)."""
    d = distro_of(cmd)
    if d is False:
        return False
    if known_up:
        return not vm_running()
    return not distro_running(d)


def forget():
    """Drop the cached answers (after the app itself started or stopped WSL)."""
    with _lock:
        _vm_cache[1] = None
        _run_cache[1] = None


#: The status reading a poll stands in for its rig's status script when the
#: rig's distro is not running: every Emulate tab's ``state_text`` reads it as
#: its own idle word ("Stopped", or "Not running" on the Stern tabs) with
#: :data:`ASLEEP_HINT`, and nothing in it says a game, a key or a board is
#: there (none can be, with WSL down).
ASLEEP_KEY = "_wsl_asleep"
ASLEEP_HINT = ("WSL is not running, so no game is. Start wakes it up; the "
               "app does not keep WSL awake just to watch it.")
ASLEEP_STATE = ("Stopped", ASLEEP_HINT)


def asleep_info():
    return {ASLEEP_KEY: "1"}


class Asleep(Exception):
    """Raised instead of running a status command that would boot WSL."""


def registered_distros():
    """``{casefolded name: Lxss GUID}`` of every registered distro, read from
    the registry WSL itself keeps (``wsl -l`` reads the same keys), so no
    wsl.exe; None when the registry cannot be read (then ask wsl.exe)."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        base = r"Software\Microsoft\Windows\CurrentVersion\Lxss"
        out = {}
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as k:
            i = 0
            while True:
                try:
                    guid = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, guid) as sub:
                        name = winreg.QueryValueEx(sub, "DistributionName")[0]
                except OSError:
                    continue
                if name:
                    out[str(name).casefold()] = guid
        return out
    except FileNotFoundError:
        return {}                      # WSL never had a distro on this PC
    except Exception:                                   # noqa: BLE001
        return None
