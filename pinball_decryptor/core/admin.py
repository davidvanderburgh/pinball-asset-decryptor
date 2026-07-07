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

:func:`resolve_mapped_drive` also lives here because it exists purely
as an elevation side effect: mapped network drives are per logon
session, so paths saved as ``W:\\…`` break the moment the app runs
elevated.
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


def _drive_visible(letter):
    """True if drive *letter* exists in THIS logon session (Windows).

    Uses the GetLogicalDrives bitmask — a pure in-memory lookup, so an
    unreachable NAS behind a mapped letter can't stall the GUI thread the
    way an ``os.path.exists`` probe of the drive root would."""
    try:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        return bool(mask >> (ord(letter.upper()) - ord("A")) & 1)
    except Exception:
        return True     # can't tell — leave the path alone


def _persistent_mapping(letter):
    """The UNC target of the user's persistent drive mapping for *letter*
    (``HKCU\\Network\\<letter>\\RemotePath``), or None."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            "Network\\" + letter.upper()) as k:
            remote, _ = winreg.QueryValueEx(k, "RemotePath")
        return remote or None
    except OSError:
        return None


def resolve_mapped_drive(path):
    """Translate a mapped-network-drive path to its UNC target when the
    drive letter isn't visible in this session (Windows).

    Mapped drive letters are per-logon-session: an elevated ("Run as
    administrator") process runs under a separate token whose session has
    no drive mappings, so a saved ``W:\\mods`` stops resolving under
    elevation even though ``\\\\server\\share`` is reachable (monkeybug,
    running PAD elevated for flash-image).  The persistent mapping lives
    per-USER in the registry (``HKCU\\Network\\<letter>\\RemotePath``),
    which both sessions share — translate through it.  Anything that
    doesn't fit (non-Windows, no drive letter, letter visible in this
    session, no persistent mapping) returns *path* unchanged."""
    if sys.platform != "win32" or not path:
        return path
    p = path.strip()
    if (len(p) < 2 or p[1] != ":" or not p[0].isalpha()
            or (len(p) > 2 and p[2] not in "\\/")):
        return path
    if _drive_visible(p[0]):
        return path
    remote = _persistent_mapping(p[0])
    if not remote:
        return path
    return remote.rstrip("\\/") + p[2:]


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
