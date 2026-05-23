"""Administrator-privilege detection.

Direct-SSD mode needs Administrator privileges on Windows because
both ``Set-Disk -IsOffline`` and ``wsl --mount <physical drive>``
fail with elevation errors otherwise.  The GUI uses
:func:`is_admin` to gate the Direct-SSD UI (warning banner +
disabled Extract / Apply Modifications buttons when not elevated).

``relaunch_as_admin`` is kept as a helper but isn't currently wired
to any button — an earlier attempt at one-click "Restart as
Administrator" had cross-environment failure modes (frozen vs
source, embeddable Python vs venv) that made the button visibly
"do nothing" in some setups.  Going through the standard Windows
"right-click → Run as administrator" flow is more reliable.

On macOS / Linux the equivalent operation (``diskutil mount`` /
direct device access for ``debugfs``) usually goes through ``sudo``
when needed (the Docker path) or works at user-level (native
debugfs reading the user's own drive) — so we report "elevated"
when the effective UID is 0 and otherwise let the runtime ``sudo``
prompts handle it.
"""

import sys


def is_admin():
    """True if the current process has Administrator / root privileges.

    Wraps the Windows ``IsUserAnAdmin`` and POSIX ``geteuid``.  Errors
    in the Windows path (e.g. missing shell32, sandbox blocking
    ctypes) degrade to ``False`` so the warning banner shows
    conservatively rather than letting a doomed run start.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    try:
        import os
        return os.geteuid() == 0
    except (AttributeError, OSError):
        return False


def relaunch_as_admin():
    """Re-launch the current Python process with elevation (Windows).

    Uses ``ShellExecuteW`` with the ``runas`` verb, which is what
    triggers the standard UAC prompt.  On approval the new process
    starts elevated and our settings file restores the user's
    selections (drive, output folder, etc.) on launch.

    Returns True if a new (elevated) process was started — the
    caller should then exit immediately so we don't leave two
    instances running.  Returns False on any failure (UAC declined,
    not on Windows, ShellExecute unavailable, …) so the caller can
    fall back to "please re-launch manually" messaging.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
    except ImportError:
        return False
    try:
        # Re-invoke this Python with the same argv.  ShellExecuteW
        # returns a value > 32 on success; <= 32 means failure
        # (32 = SE_ERR_DLLNOTFOUND, 5 = SE_ERR_ACCESSDENIED — the
        # "user clicked No on UAC" case).
        argv = " ".join(f'"{a}"' for a in sys.argv)
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, argv, None, 1)
        return int(rc) > 32
    except Exception:
        return False
