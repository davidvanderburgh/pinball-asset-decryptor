"""Start the Windows prerequisite installer elevated, and notice when it
never actually starts.

Install Missing used to run a plain PowerShell whose only job was to run
``Start-Process powershell -Verb RunAs`` - two PowerShell start-ups before
the installer printed a line, and nothing the app could see afterwards.  On
hotel Wi-Fi a user got an elevated window that stayed blank for many minutes
and the app said nothing (PAD-327): PowerShell stalled before running line 1
of the script, which shows its menu before it touches the network.

So the elevated PowerShell is started straight from here (one start-up, not
two), the script is handed a marker path it writes as its very first act,
and :func:`watch_started` reports a window that is still running but has not
started the script after a grace period.  A window the user closes, or a
script that started, is never reported.
"""

import os
import tempfile
import time

#: Seconds an elevated PowerShell may take to start the script before the
#: app says so.  A cold PowerShell 5.1 on a slow PC takes 5-15 s; the clock
#: only starts once UAC was answered (ShellExecuteEx returns after that).
STARTED_GRACE_S = 45


def installer_args(script, marker, wsl_only=False):
    """The powershell.exe arguments that run ``script`` and hand it the
    started-marker path (empty = the script writes none).  ``wsl_only``
    runs its -WslOnly mode: WSL2 switched on, no distro, no menu."""
    args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script]
    if marker:
        args += ["-StartedMarker", marker]
    if wsl_only:
        args += ["-WslOnly"]
    return args


# ---------------------------------------------------------------------------
# WHICH INSTALL, on Windows (PAD-1103)
# ---------------------------------------------------------------------------
# Install Missing used to have one answer: the full prerequisite installer, a
# console that asks which manufacturers, installs WSL2 AND an Ubuntu of one
# exact release, then apt-installs the tools into it.  Every step of that is a
# place a newcomer gets stuck - a Pinside helper set PAD up on several PCs and
# installed WSL2 and Ubuntu-24.04 by hand from a command line on every one -
# and none of it is needed any more where the app can bring its own Linux
# (core/runtime.py), which is built with every one of those tools in it.
#
# So the button now does the ONE step this PC is missing:
#
#   ROUTE_WSL      WSL itself is off.  Switch it on and nothing else (the
#                  script's -WslOnly), then one restart.
#   ROUTE_RUNTIME  WSL is on and the app's own Linux is not here (or is out of
#                  date).  Install it, in the app, with a progress bar.
#   ROUTE_SCRIPT   Everything else, exactly as before: only Windows-side tools
#                  missing, the app's Linux already installed, WSL not
#                  answering, a restart still due, or a build with no image.

ROUTE_WSL = "wsl"
ROUTE_RUNTIME = "runtime"
ROUTE_SCRIPT = "script"


def pick_route(wsl_rows_missing, wsl_ok, runtime_state, restart_pending=False):
    """Which install Install Missing starts on Windows.

    *wsl_rows_missing*: did any missing prerequisite probe inside WSL.
    *wsl_ok*: ``wsl --status`` - True on, False off, None did not answer.
    *runtime_state*: :func:`core.runtime.status`'s state.
    *restart_pending*: WSL was installed in this boot and waits on a restart.

    Only ``absent`` and ``stale`` runtimes are installable: ``ready`` has its
    tools already (a red row there is the app's fault, said elsewhere),
    ``foreign`` is somebody else's distro, ``unknown`` is a WSL that did not
    answer, and the rest mean this build has no image to install.
    """
    if not wsl_rows_missing or runtime_state not in ("absent", "stale"):
        return ROUTE_SCRIPT
    if wsl_ok is True:
        return ROUTE_RUNTIME
    if wsl_ok is False and not restart_pending:
        return ROUTE_WSL
    return ROUTE_SCRIPT


def wsl_setup_text(rows):
    """The question before ROUTE_WSL; *rows* names what is waiting on it."""
    return ("WSL2 is not set up on this PC, and %s %s on it.\n\n"
            "Set it up now? Windows asks for administrator permission, "
            "installs WSL2 in a window of its own (a few minutes) and then "
            "usually needs one restart.\n\n"
            "After the restart, click Install Missing again: it installs "
            "the app's own Linux, with every tool already in it. You do not "
            "need to install Ubuntu or anything else yourself."
            % (_names(rows), "runs" if len(rows) == 1 else "run"))


def runtime_text(rows, size_mb, stale=False):
    """The question before ROUTE_RUNTIME (Yes / No / Cancel)."""
    what = ("The app's own Linux on this PC is from an older version, so "
            if stale else
            "WSL2 is set up, but ")
    return ("%s%s %s missing.\n\n"
            "Install the app's own Linux now? It is a one-time download of "
            "about %d MB, built with every tool the app uses, so nothing has "
            "to be installed into Ubuntu or any other distro. Your own WSL "
            "distros are not changed.\n\n"
            "Yes: install it (recommended).\n"
            "No: install the missing tools into this PC's own WSL distro "
            "with the full prerequisite installer instead."
            % (what, _names(rows), "is" if len(rows) == 1 else "are",
               size_mb))


def _names(rows):
    rows = [str(r) for r in rows] or ["the Linux-side tools"]
    if len(rows) <= 3:
        return ", ".join(rows)
    return "%s and %d more" % (", ".join(rows[:3]), len(rows) - 3)


def new_marker_path():
    """A fresh, not-yet-existing marker path in the user's temp folder."""
    fd, path = tempfile.mkstemp(prefix="pad_prereqs_started_", suffix=".txt")
    os.close(fd)
    os.remove(path)
    return path


class ElevatedConsole:
    """A visible elevated ``powershell.exe`` started with ShellExecuteEx
    ``runas``, keeping the process handle so :meth:`running` can tell a
    window the user closed from one that is still sitting there.

    ``declined`` is True when the UAC prompt was answered No; ``error``
    holds the WinError of any other failure (0 = started)."""

    def __init__(self, args, cwd=None, verb="runas"):
        import ctypes
        from ctypes import wintypes
        from .elevated_flash import _winq

        class SHELLEXECUTEINFOW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("fMask", wintypes.ULONG),
                ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR),
                ("lpFile", wintypes.LPCWSTR),
                ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR),
                ("nShow", ctypes.c_int),
                ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", wintypes.LPVOID),
                ("lpClass", wintypes.LPCWSTR),
                ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD),
                ("hIconOrMonitor", wintypes.HANDLE),
                ("hProcess", wintypes.HANDLE),
            ]

        _SEE_MASK_NOCLOSEPROCESS = 0x00000040
        _SW_SHOWNORMAL = 1
        _ERROR_CANCELLED = 1223

        self._ctypes = ctypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        info = SHELLEXECUTEINFOW()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = _SEE_MASK_NOCLOSEPROCESS
        info.lpVerb = verb
        info.lpFile = "powershell.exe"
        info.lpParameters = " ".join(_winq(a) for a in args)
        info.lpDirectory = cwd
        info.nShow = _SW_SHOWNORMAL
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
        shell32.ShellExecuteExW.restype = wintypes.BOOL
        if shell32.ShellExecuteExW(ctypes.byref(info)):
            self._handle = info.hProcess
            self.error = 0
        else:
            self._handle = None
            self.error = ctypes.get_last_error() or -1
        self.declined = self.error == _ERROR_CANCELLED

    def running(self):
        if not self._handle:
            return False
        code = self._ctypes.c_ulong(0)
        self._kernel32.GetExitCodeProcess(self._handle,
                                          self._ctypes.byref(code))
        return code.value == 259    # STILL_ACTIVE

    def close(self):
        if self._handle:
            try:
                self._kernel32.CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None


def watch_started(marker, running, grace_s=STARTED_GRACE_S, poll_s=1.0,
                  clock=time.monotonic, sleep=time.sleep):
    """Wait up to ``grace_s`` for the installer to write ``marker``.

    Returns True when the window is still open after the grace period and
    the script never started - the one case worth telling the user about.
    False when the marker appeared or the window went away (closed, or the
    script ran and exited)."""
    deadline = clock() + grace_s
    while True:
        if os.path.exists(marker):
            return False
        if not running():
            return False
        if clock() >= deadline:
            return True
        sleep(poll_s)


def remove_marker(marker):
    try:
        os.remove(marker)
    except OSError:
        pass


NOT_STARTED_TEXT = (
    "The prerequisite installer has not started yet.\n\n"
    "If its PowerShell window is still blank, PowerShell itself is stuck "
    "before the installer's first line. That happens on some hotel and "
    "public Wi-Fi networks. Close the window and try again on another "
    "connection.\n\n"
    "If the window shows the installer's menu, ignore this.")
