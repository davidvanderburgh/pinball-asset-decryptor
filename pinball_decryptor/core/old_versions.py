"""Old copies of the app that updates leave behind, and clearing them away.

Two kinds pile up, one per release, and PAD ships often:

* **Linux AppImages** (Settings, the gear, Updates > Old versions).  An
  AppImage update downloads the new AppImage beside the running one and leaves
  the old one alone on purpose (``App._finish_appimage_update``: a bad update
  costs a delete, not a working copy).  So every update kept one more, and
  deleting them was the user's job (Brombomb, PAD-937: "I really don't want to
  manage version cleanup").  How many to keep is the user's pick; keeping all
  of them stays the default, the behaviour before.
* **Windows setup exes and macOS disk images** in the temp folder.  Those are
  throwaway (``App._update_download_dir``): the install copies what it needs
  and the file is never run again, but nothing deleted it, so each update left
  ~110 MB behind in %TEMP%.  They go without asking.

Only files named like a release asset (``Pinball_Asset_Decryptor_v<ver>_...``)
whose version is OLDER than the running app are touched, and never the file the
app is running from: a newer download the user has not started yet survives
whatever the setting says.
"""

import os
import re
import tempfile

#: (how many old AppImages to keep, label).  ``-1`` keeps every one (the
#: default, as before); ``0`` keeps none.  ``OLD_VERSIONS_DEFAULT`` must be
#: one of these values.
OLD_VERSIONS_CHOICES = (
    (-1, "Keep them all"),
    (3, "Keep the last 3"),
    (1, "Keep the last one"),
    (0, "Delete them"),
)
OLD_VERSIONS_DEFAULT = -1

#: the Updates submenu rows' tooltip
OLD_VERSIONS_TIP = (
    "Each update saves the new AppImage beside the old one. This picks how "
    "many older ones PAD keeps and deletes the rest, now and each time PAD "
    "starts. The one you are running and any newer download are never "
    "touched.")

_ASSET_RE = re.compile(r"^Pinball_Asset_Decryptor_v(\d+(?:\.\d+)*)_(.+)$",
                       re.IGNORECASE)


def normalize_old_versions(value):
    """The stored keep count as one of :data:`OLD_VERSIONS_CHOICES`.

    Missing, unparseable or off-menu falls back to
    :data:`OLD_VERSIONS_DEFAULT`; ``0`` (keep none) survives.
    """
    try:
        keep = int(value)
    except (TypeError, ValueError):
        return OLD_VERSIONS_DEFAULT
    return keep if keep in {k for k, _ in OLD_VERSIONS_CHOICES} \
        else OLD_VERSIONS_DEFAULT


def running_appimage(environ=None):
    """The AppImage the app runs from, or ``""`` when it isn't one.

    ``$APPIMAGE`` is set by the AppImage runtime, so it is the whole test:
    a source checkout or a Windows/macOS install has none, and the Old
    versions setting has nothing to do there.
    """
    env = os.environ if environ is None else environ
    return env.get("APPIMAGE") or ""


def _version(text):
    try:
        return tuple(int(x) for x in text.split("."))
    except ValueError:
        return ()


def _older_assets(folder, current_version, suffixes, skip=()):
    """``[(version, path)]`` of release assets in ``folder`` older than the
    running version, newest first."""
    cur = _version(str(current_version).lstrip("v"))
    if not cur:
        return []
    skip = {os.path.normcase(os.path.realpath(p)) for p in skip if p}
    found = []
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    for name in names:
        m = _ASSET_RE.match(name)
        if not m or not name.lower().endswith(suffixes):
            continue
        ver = _version(m.group(1))
        if not ver or ver >= cur:
            continue
        path = os.path.join(folder, name)
        if not os.path.isfile(path) or os.path.islink(path):
            continue
        if os.path.normcase(os.path.realpath(path)) in skip:
            continue
        found.append((ver, path))
    found.sort(reverse=True)
    return found


def _delete(paths):
    """``(deleted, failed)``: the paths removed, and ``(path, error)`` for
    those that would not go (in use, no permission)."""
    deleted, failed = [], []
    for path in paths:
        try:
            os.remove(path)
            deleted.append(path)
        except OSError as e:
            failed.append((path, str(e)))
    return deleted, failed


def appimage_folders(current, home=None):
    """Where updates put AppImages (``App._update_download_dir``): beside the
    running one, then ~/Downloads and ~.  Each folder once."""
    home = home if home is not None else os.path.expanduser("~")
    out, seen = [], set()
    for d in (os.path.dirname(os.path.abspath(current)) if current else "",
              os.path.join(home, "Downloads"), home):
        key = os.path.normcase(os.path.realpath(d)) if d else ""
        if d and key not in seen and os.path.isdir(d):
            seen.add(key)
            out.append(d)
    return out


def prune_old_appimages(current, current_version, keep, folders=None):
    """Delete all but the ``keep`` newest AppImages older than the running
    version.  ``keep < 0`` keeps them all.  Returns ``(deleted, failed)``."""
    keep = normalize_old_versions(keep)
    if keep < 0 or not current:
        return [], []
    older = []
    for folder in (folders if folders is not None
                   else appimage_folders(current)):
        older += _older_assets(folder, current_version, (".appimage",),
                               skip=(current,))
    older.sort(reverse=True)
    return _delete([p for _v, p in older[keep:]])


def prune_old_installers(current_version, folder=None):
    """Delete the setup exes and disk images earlier updates left in the temp
    folder.  Returns ``(deleted, failed)``."""
    folder = folder if folder is not None else tempfile.gettempdir()
    older = _older_assets(folder, current_version, ("_windows.exe", ".dmg"))
    return _delete([p for _v, p in older])
