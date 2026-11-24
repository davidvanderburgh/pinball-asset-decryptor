"""Administrator-privilege detection.

Direct-SSD mode needs Administrator privileges on Windows because
both ``Set-Disk -IsOffline`` and ``wsl --mount <physical drive>``
fail with elevation errors otherwise.  The GUI uses
:func:`is_admin` to gate the Direct-SSD UI (warning banner +
disabled Extract / Apply Modifications buttons when not elevated).

The app starts WITHOUT Administrator on Windows (PAD-1563, GitHub issue
#46); the jobs that need it ask for it as they start.  A Direct-SSD run
cannot (its wsl --mount calls run all through the pipeline), so its panel's
Restart as administrator uses :func:`relaunch_as_admin` with
:func:`restart_args`.  An earlier one-click restart was dropped because it
visibly "did nothing" in some setups: a ``-m`` run re-started as a plain
script, and an elevated start lands in System32, not the app's folder.
:func:`restart_args` and the working folder passed on cover both.

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

import os
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
    elevation even though ``\\\\server\\share`` is reachable (a tester,
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


def restart_args(argv, tab):
    """The arguments a Restart as administrator from a Direct-SSD *tab*
    starts the elevated copy with (PAD-1563): the script this run was
    started as, then ``--direct-ssd <tab>``.  Nothing else of this run's
    command line comes along - a card image double-clicked in Explorer was
    handed in already, and an earlier ``--direct-ssd`` is replaced.  A run
    started as ``-m pinball_decryptor`` (its argv[0] the package's
    ``__main__.py``) restarts the same way, since that file cannot run as a
    plain script; a frozen build's argv[0] is its own exe, so it gets only
    the flag."""
    script = (argv or [""])[0]
    if getattr(sys, "frozen", False):
        head = []
    elif os.path.basename(script) == "__main__.py":
        head = ["-m", os.path.basename(os.path.dirname(os.path.abspath(script)))]
    else:
        head = [os.path.abspath(script)]
    return head + ["--direct-ssd", tab]


def relaunch_as_admin(args=None):
    """Re-launch the current Python process with elevation (Windows).

    *args* are the interpreter's arguments (``sys.argv`` when None - this
    run's own command line); :func:`restart_args` builds them for a Restart
    as administrator.

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
        argv = " ".join(f'"{a}"' for a in (sys.argv if args is None
                                            else args))
        # the working folder too: an elevated start otherwise lands in
        # System32, where a "-m pinball_decryptor" run finds no package
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, argv, os.getcwd(), 1)
        return int(rc) > 32
    except Exception:
        return False
