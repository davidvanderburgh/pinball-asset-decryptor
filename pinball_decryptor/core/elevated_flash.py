"""Elevate only the card flash, not the whole app.

A whole-card flash writes raw sectors, which needs Administrator (Windows) or
root (macOS/Linux).  The old contract was "re-launch the entire app elevated
first" — awkward everywhere and genuinely broken on macOS, where the intuitive
``sudo open -a PAD.app`` hands the launch to ``launchd`` and starts the app as
*you*, not root, so the in-app admin check still fails (flippermeister's
report).

Instead we keep the GUI unprivileged and elevate *only the write*, the way
balenaEtcher does: at flash time we spawn a short-lived elevated child that runs
the real :func:`core.rawdevice.flash_image_to_device` and streams progress /
log / result back through a small temp-dir file protocol.  The parent relays
those to the normal status area and can cancel by dropping a sentinel file.

Elevation prompt per platform:
  * macOS   — ``osascript … with administrator privileges`` (the native secure
    password dialog; we never see the password).
  * Windows — ``ShellExecuteEx`` with the ``runas`` verb (the standard UAC
    prompt).  Note the shipped Windows build already launches the whole app
    elevated via ``launcher.vbs``, so :func:`core.admin.is_admin` is normally
    already True there and this path is the fallback for an unelevated launch.
  * Linux   — ``pkexec`` (graphical) when present.

When the process is *already* elevated we skip all of this and flash in-process,
so nothing changes for an already-root run.

The child re-invokes THIS application in "flash-helper" mode
(:func:`run_helper_main`, dispatched from the app's entry points on the
``--flash-helper`` argument).  Frozen bundles (macOS/Linux) re-exec their own
binary; the Windows embeddable build and source runs re-exec
``-m pinball_decryptor`` (the ``._pth`` makes the package importable from the
bundled interpreter regardless of cwd).
"""

import json
import os
import subprocess
import sys
import tempfile
import time

from .admin import is_admin
from .rawdevice import (FlashCancelled, FlashError, flash_image_to_device,
                        is_device_path)

# IPC file names inside the per-flash temp directory.  The parent creates the
# directory and ``job.json``; the elevated child writes the rest.
_JOB = "job.json"
_PROGRESS = "progress.json"
_RESULT = "result.json"
_LOG = "log.jsonl"
_CANCEL = "cancel"

# How often the parent samples the IPC files while the child runs.
_POLL_SECS = 0.15
# The child rewrites progress.json at most this often (the raw copy fires its
# progress callback far more frequently than the UI needs).
_PROGRESS_MIN_INTERVAL = 0.1


# ---------------------------------------------------------------------------
# Parent side — orchestrate an elevated flash
# ---------------------------------------------------------------------------

def can_self_elevate():
    """True if a flash can raise its own privileges here without the whole app
    being re-launched elevated.

    Windows (UAC) and macOS (osascript) always can; Linux only when ``pkexec``
    is installed.  Drives the flash dialog's wording (forewarn vs. "re-launch
    as admin")."""
    if sys.platform in ("win32", "darwin"):
        return True
    return _which("pkexec") is not None


def flash_image_with_privileges(image_path, device_path, *, log=None,
                                progress=None, cancel=None, verify=True,
                                on_verify_start=None):
    """Flash *image_path* onto *device_path*, elevating only the write.

    Drop-in for :func:`core.rawdevice.flash_image_to_device` with the same
    return value (bytes written) and exceptions (:class:`FlashError`,
    :class:`FlashCancelled`).  When the app is already Administrator/root the
    flash runs in-process; otherwise it runs in an elevated child and this
    relays its progress/log/result.
    """
    # Elevation is only needed to write a *raw physical device*.  If we're
    # already Administrator/root, or the target is a plain file (backing-file
    # tests, or any non-device path), write in-process — spawning an elevated
    # child there would be pointless (and would pop a UAC/password prompt).
    if is_admin() or not is_device_path(device_path):
        return flash_image_to_device(
            image_path, device_path, log=log, progress=progress,
            cancel=cancel, verify=verify, on_verify_start=on_verify_start)

    if log is not None:
        log("This flash needs administrator access — approve the prompt to "
            "continue (the app itself keeps running normally).", "info")

    ipc = tempfile.mkdtemp(prefix="pad_flash_")
    try:
        with open(os.path.join(ipc, _JOB), "w", encoding="utf-8") as f:
            json.dump({"image": image_path, "device": device_path,
                       "verify": bool(verify)}, f)

        run = _spawn_elevated_helper(ipc)
        if run is None:
            raise FlashError(
                "Could not request administrator access on this system. "
                "Re-launch the app as administrator and flash again.")

        written = _relay_until_done(
            run, ipc, log=log, progress=progress, cancel=cancel,
            on_verify_start=on_verify_start)
        return written
    finally:
        _rmtree_quiet(ipc)


def _relay_until_done(run, ipc, *, log, progress, cancel, on_verify_start):
    """Pump the IPC files to the UI callbacks until the child exits, then
    translate its result into a return value / exception."""
    prog_path = os.path.join(ipc, _PROGRESS)
    log_path = os.path.join(ipc, _LOG)
    cancel_path = os.path.join(ipc, _CANCEL)
    state = {"log_seen": 0, "verify_started": False}

    def _drain():
        state["log_seen"] = _relay_log(log_path, state["log_seen"], log)
        snap = _read_json(prog_path)
        if snap is None:
            return
        if (not state["verify_started"] and snap.get("phase") == "verify"
                and on_verify_start is not None):
            on_verify_start()
            state["verify_started"] = True
        if progress is not None:
            progress(snap.get("done", 0), snap.get("total", 0),
                     snap.get("msg", ""))

    cancel_sent = False
    while run.poll() is None:
        _drain()
        if not cancel_sent and cancel is not None and cancel():
            _touch(cancel_path)
            cancel_sent = True
        time.sleep(_POLL_SECS)

    # Final drain: a fast child can finish between polls (or before the first
    # one), so relay the last log lines + progress snapshot — including the
    # verify-phase transition — that the loop may not have observed.
    _drain()

    result = _read_json(os.path.join(ipc, _RESULT))
    if result is None:
        # The child died before writing a result: user declined the prompt,
        # or it crashed on startup.
        if run.declined:
            raise FlashError(
                "Administrator access was declined, so the card was not "
                "written. Nothing was changed on the card.")
        detail = (run.stderr or "").strip()
        raise FlashError(
            "The elevated flash helper exited (code %s) without reporting a "
            "result, so the card may not have been written.%s"
            % (run.exit_code, ("\n\n" + detail) if detail else ""))

    if result.get("cancelled"):
        raise FlashCancelled(result.get("error")
                             or "Flash cancelled before completion.")
    if not result.get("ok"):
        raise FlashError(result.get("error") or "The elevated flash failed.")

    # The child's flash_image_to_device already logged its own "Wrote … to …
    # (verified)." success line, which we relayed from log.jsonl — don't repeat
    # it here.  Just settle the progress bar at 100%.
    written = int(result.get("written", 0))
    if progress is not None:
        progress(written, written, "Flash complete")
    return written


def _relay_log(log_path, seen, log):
    """Relay newly-appended ``log.jsonl`` lines; return the new line count."""
    lines = _read_lines(log_path)
    if log is not None:
        for entry in lines[seen:]:
            try:
                rec = json.loads(entry)
            except ValueError:
                continue
            log(rec.get("text", ""), rec.get("level", "info"))
    return len(lines)


# ---------------------------------------------------------------------------
# Parent side — launch the elevated child
# ---------------------------------------------------------------------------

def _helper_argv(ipc_dir):
    """Command re-invoking this app in flash-helper mode.

    Frozen bundles re-exec their own binary (which dispatches ``--flash-helper``
    in the PyInstaller entry).  Everything else re-execs ``-m pinball_decryptor``
    — the Windows embeddable interpreter's ``._pth`` lists ``..`` so the package
    imports regardless of the elevated child's working directory.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--flash-helper", ipc_dir]
    return [sys.executable, "-m", "pinball_decryptor", "--flash-helper", ipc_dir]


def _spawn_elevated_helper(ipc_dir):
    """Start the elevated helper for *ipc_dir*; return an ``_ElevatedRun`` or
    ``None`` if this platform has no elevation mechanism we can drive (or the
    launch itself fails before the prompt)."""
    argv = _helper_argv(ipc_dir)
    try:
        if sys.platform == "win32":
            return _WindowsRunasRun(argv)
        if sys.platform == "darwin":
            return _OsascriptRun(argv)
        return _PkexecRun(argv)
    except _NoMechanism:
        return None
    except Exception:
        return None


class _ElevatedRun:
    """Poll-able handle to an elevated child process.

    Subclasses expose :meth:`poll` (exit code or ``None`` while running),
    ``exit_code``, ``declined`` (user refused the elevation prompt), and
    ``stderr`` (captured diagnostic text, when available)."""

    exit_code = None
    declined = False
    stderr = ""

    def poll(self):
        raise NotImplementedError


class _OsascriptRun(_ElevatedRun):
    """macOS: ``osascript … with administrator privileges`` running the helper.

    ``do shell script`` blocks osascript until the helper finishes, so we run
    osascript itself under :class:`subprocess.Popen` and poll it.  A declined
    auth dialog surfaces as AppleScript error ``-128`` / ``User canceled``."""

    def __init__(self, argv):
        shell = " ".join(_shq(a) for a in argv)
        applescript = ('do shell script "%s" with administrator privileges'
                       % shell.replace("\\", "\\\\").replace('"', '\\"'))
        self._proc = subprocess.Popen(
            ["osascript", "-e", applescript],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace")
        self._captured = None

    def poll(self):
        rc = self._proc.poll()
        if rc is None:
            return None
        if self._captured is None:
            out, err = self._proc.communicate()
            self._captured = (out or "") + (err or "")
            self.exit_code = rc
            low = self._captured.lower()
            self.declined = ("-128" in self._captured
                             or "user canceled" in low
                             or "user cancelled" in low)
            self.stderr = "" if self.declined else self._captured
        return rc


class _PkexecRun(_ElevatedRun):
    """Linux: run the helper via ``pkexec`` (graphical elevation) when present.

    Falls back to reporting "no mechanism" (``None`` spawn) if pkexec is
    missing; the caller then tells the user to re-launch as root."""

    def __init__(self, argv):
        self._proc = None
        pkexec = _which("pkexec")
        if not pkexec:
            raise _NoMechanism()
        # pkexec needs an absolute program path and a sane environment.
        self._proc = subprocess.Popen(
            [pkexec, "--disable-internal-agent"] + argv,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace")
        self._captured = None

    def poll(self):
        rc = self._proc.poll()
        if rc is None:
            return None
        if self._captured is None:
            out, err = self._proc.communicate()
            self._captured = (out or "") + (err or "")
            self.exit_code = rc
            # pkexec exits 126 (auth dialog dismissed) / 127 (not authorized).
            self.declined = rc in (126, 127)
            self.stderr = "" if self.declined else self._captured
        return rc


class _NoMechanism(Exception):
    """Raised by a launcher ctor when the platform has no elevation tool."""


class _WindowsRunasRun(_ElevatedRun):
    """Windows: ``ShellExecuteEx`` with the ``runas`` verb (UAC prompt).

    ``runas`` can't go through :class:`subprocess.Popen` (that uses
    ``CreateProcess``, which won't elevate), so we call ``ShellExecuteExW`` and
    keep the process handle to poll its exit code.  A declined UAC prompt comes
    back as ``ERROR_CANCELLED`` (1223)."""

    def __init__(self, argv):
        import ctypes
        from ctypes import wintypes

        exe = argv[0]
        params = " ".join(_winq(a) for a in argv[1:])

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
        _SEE_MASK_NO_CONSOLE = 0x00008000
        _SW_HIDE = 0
        _ERROR_CANCELLED = 1223

        self._ctypes = ctypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        info = SHELLEXECUTEINFOW()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = _SEE_MASK_NOCLOSEPROCESS | _SEE_MASK_NO_CONSOLE
        info.lpVerb = "runas"
        info.lpFile = exe
        info.lpParameters = params
        info.lpDirectory = None
        info.nShow = _SW_HIDE

        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
        shell32.ShellExecuteExW.restype = wintypes.BOOL

        ok = shell32.ShellExecuteExW(ctypes.byref(info))
        if not ok:
            err = ctypes.get_last_error()
            self.exit_code = err
            self.declined = (err == _ERROR_CANCELLED)
            self.stderr = "" if self.declined else ("ShellExecuteEx failed "
                                                    "(WinError %d)." % err)
            self._handle = None
            self._done = True
            return
        self._handle = info.hProcess
        self._done = False

    def poll(self):
        if self._done:
            return self.exit_code
        if not self._handle:
            self._done = True
            return self.exit_code
        ctypes = self._ctypes
        code = ctypes.c_ulong(0)
        # STILL_ACTIVE (259) means the process hasn't exited yet.
        self._kernel32.GetExitCodeProcess(self._handle, ctypes.byref(code))
        if code.value == 259:
            return None
        self.exit_code = code.value
        self._done = True
        try:
            self._kernel32.CloseHandle(self._handle)
        except Exception:
            pass
        return self.exit_code


# ---------------------------------------------------------------------------
# Child side — the elevated helper that actually writes the card
# ---------------------------------------------------------------------------

def run_helper_main(argv):
    """Flash-helper entry point (dispatched on ``--flash-helper <ipc_dir>``).

    Runs the real flash against the job described in ``ipc_dir/job.json``,
    streaming progress / log to the sibling IPC files and honouring the
    ``cancel`` sentinel.  Always returns 0 (even on a flash failure): the parent
    reads ``result.json`` as the source of truth, and a nonzero exit would make
    osascript/UAC treat a flash error as a *launch* error.
    """
    try:
        ipc = argv[argv.index("--flash-helper") + 1]
    except (ValueError, IndexError):
        return 2
    job = _read_json(os.path.join(ipc, _JOB)) or {}
    image = job.get("image")
    device = job.get("device")
    verify = bool(job.get("verify", True))
    cancel_path = os.path.join(ipc, _CANCEL)
    log_path = os.path.join(ipc, _LOG)
    prog_path = os.path.join(ipc, _PROGRESS)
    result_path = os.path.join(ipc, _RESULT)

    state = {"phase": "write", "last_write": 0.0}

    def _log(text, level="info"):
        _append_line(log_path, json.dumps({"text": text, "level": level}))

    def _progress(done, total, msg=""):
        now = time.monotonic()
        # Always emit the terminal 100% tick; throttle the rest.
        if (done < total
                and now - state["last_write"] < _PROGRESS_MIN_INTERVAL):
            return
        state["last_write"] = now
        _write_json_atomic(prog_path, {"done": done, "total": total,
                                       "msg": msg, "phase": state["phase"]})

    def _cancel():
        return os.path.exists(cancel_path)

    def _on_verify_start():
        state["phase"] = "verify"
        state["last_write"] = 0.0        # force the next progress write through

    try:
        written = flash_image_to_device(
            image, device, log=_log, progress=_progress, cancel=_cancel,
            verify=verify, on_verify_start=_on_verify_start)
        _write_json_atomic(result_path, {"ok": True, "written": written})
    except FlashCancelled as e:
        _write_json_atomic(result_path,
                           {"ok": False, "cancelled": True, "error": str(e)})
    except FlashError as e:
        _write_json_atomic(result_path, {"ok": False, "error": str(e)})
    except BaseException as e:                      # noqa: BLE001 - report all
        import traceback
        _write_json_atomic(result_path, {
            "ok": False,
            "error": "The flash helper hit an unexpected error:\n%s"
                     % traceback.format_exc(),
            "exc": repr(e)})
    return 0


# ---------------------------------------------------------------------------
# Small IPC / quoting helpers
# ---------------------------------------------------------------------------

def _read_json(path):
    """Parse *path* as JSON, or ``None`` if absent / mid-write / unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except OSError:
        return []


def _append_line(path, line):
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def _write_json_atomic(path, obj):
    """Write JSON so a concurrent reader never sees a half-written file."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    os.replace(tmp, path)


def _touch(path):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("cancel")
    except OSError:
        pass


def _rmtree_quiet(path):
    import shutil
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def _which(name):
    from shutil import which
    return which(name)


def _shq(arg):
    """POSIX shell-quote a single argument (for the osascript command)."""
    import shlex
    return shlex.quote(arg)


def _winq(arg):
    r"""Quote an argument for a Windows command line (``ShellExecuteEx``
    ``lpParameters``).  Wraps in double quotes and escapes embedded quotes /
    trailing backslashes per the CommandLineToArgvW rules."""
    if arg and not any(c in arg for c in ' \t"'):
        return arg
    out = ['"']
    backslashes = 0
    for ch in arg:
        if ch == "\\":
            backslashes += 1
            out.append(ch)
        elif ch == '"':
            out.append("\\" * backslashes + '\\"')
            backslashes = 0
        else:
            backslashes = 0
            out.append(ch)
    out.append("\\" * backslashes + '"')
    return "".join(out)
