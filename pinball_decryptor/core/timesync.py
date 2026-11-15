"""Turn off systemd-timesyncd in the WSL distros a rig run shares a clock with.

WHY (PAD-1307, PAD-932).  WSL 2 runs every distro on ONE kernel with ONE clock,
and WSL itself keeps that clock on Windows time.  An Ubuntu with systemd also
runs systemd-timesyncd, which sets the same clock from NTP, and the two fight:
the guest clock has been measured running up to 2.5 % fast.  PulseAudio (WSLg's
sound server) paces sound on that clock, so the emulator's sound drifts and
breaks up - on a rig in PAD-Runtime too, which has no time service of its own,
because the Ubuntu next to it moves the clock under it.  It looks like an audio
bug and takes a long time to trace (David heard it on Deadpool and Jurassic
Park, 2026-11-01, and it went away when he disabled timesyncd).

WHAT.  At the start of a rig run, once per app session and off the interface
thread, every RUNNING distro is asked (as root, which ``wsl -u root`` is for any
Windows user) to ``systemctl disable --now systemd-timesyncd`` - only where
systemd is running and the service is active or enabled, so a distro without it
is not touched and one already off answers nothing.  A distro that is not
running is not started for this: it is not moving the clock.  The installer
does the same when it sets Ubuntu up (install_prerequisites.ps1), and watch.sh
does it in its own distro for a run started from a shell.

Nothing is lost: WSL's own time sync keeps the clock right without it.
``PAD_KEEP_TIMESYNC=1`` keeps it running.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading

#: Run with ``sh -c`` as root in each running distro.  Prints MARK only when it
#: turned the service off.  No quotes in it: it crosses wsl.exe's command line.
MARK = "PAD_TIMESYNC_OFF"
SCRIPT = ("[ -d /run/systemd/system ] || exit 0; "
          "command -v systemctl >/dev/null || exit 0; "
          "systemctl is-active --quiet systemd-timesyncd "
          "|| systemctl is-enabled --quiet systemd-timesyncd 2>/dev/null "
          "|| exit 0; "
          "systemctl disable --now systemd-timesyncd >/dev/null 2>&1 "
          "&& echo " + MARK)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_lock = threading.Lock()
_done = False


def _decode(raw: bytes) -> str:
    """wsl.exe's own output is UTF-16 LE; a Linux command's is UTF-8."""
    if raw[:2] == b"\xff\xfe" or (len(raw) > 1 and raw[1:2] == b"\x00"):
        return raw.decode("utf-16-le", "replace")
    return raw.decode("utf-8", "replace")


def running_distros(runner=subprocess.run) -> list:
    """Names of the WSL distros running now (Docker Desktop's own skipped)."""
    try:
        r = runner(["wsl.exe", "-l", "--running", "-q"], capture_output=True,
                   timeout=15, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return []
    if getattr(r, "returncode", 1) != 0:
        return []
    names = []
    for line in _decode(r.stdout or b"").replace("\x00", "").splitlines():
        name = line.strip().lstrip("﻿")
        if name and not name.lower().startswith("docker-desktop"):
            names.append(name)
    return names


def quiet_clocks(log=None, runner=subprocess.run, force=False) -> list:
    """Turn timesyncd off in every running distro that runs it; return the
    names of the distros where it was turned off.  Once per session unless
    *force*; never off Windows; never with ``PAD_KEEP_TIMESYNC=1``."""
    global _done
    if sys.platform != "win32" and runner is subprocess.run:
        return []
    if os.environ.get("PAD_KEEP_TIMESYNC") == "1":
        return []
    with _lock:
        if _done and not force:
            return []
        _done = True
    changed = []
    for name in running_distros(runner):
        try:
            r = runner(["wsl.exe", "-d", name, "-u", "root", "-e",
                        "sh", "-c", SCRIPT],
                       capture_output=True, timeout=30,
                       creationflags=_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            continue
        if MARK in _decode(getattr(r, "stdout", b"") or b""):
            changed.append(name)
            if log:
                log("[clock] turned off systemd-timesyncd in %s: it fights "
                    "WSL's own clock, and the sound drifts and breaks up "
                    "(PAD_KEEP_TIMESYNC=1 keeps it)" % name)
    return changed


def quiet_clocks_async(log=None) -> None:
    """:func:`quiet_clocks` on a daemon thread - a run never waits for it."""
    threading.Thread(target=quiet_clocks, kwargs={"log": log},
                     name="pad-timesync", daemon=True).start()
