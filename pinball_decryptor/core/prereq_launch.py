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


def installer_args(script, marker):
    """The powershell.exe arguments that run ``script`` and hand it the
    started-marker path (empty = the script writes none)."""
    args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script]
    if marker:
        args += ["-StartedMarker", marker]
    return args


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
