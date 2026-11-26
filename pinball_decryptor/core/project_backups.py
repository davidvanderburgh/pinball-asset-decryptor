"""PAD-1602: the project's Backups folder (PAD-402) keeps the last few and no twins.

A Modes or Scenes load that replaces the user's own edits first saves them to ``<project>/Backups`` as
``Before loading <name> <date time>.zip``.  Two rules, the ones machine backups follow (PAD-1588):

* a new backup whose content is the newest one's is not kept: the newest one already holds it, and its path is
  what the load names;
* only the newest :func:`keep_of` of these backups stay; older ones are removed.

Only files named the way the app names them are counted or removed: a backup the user renamed, or a file they put
in the folder themselves, is never touched.  Content is compared by each zip entry's name, size and CRC (stored in
the zip's directory, so nothing is unpacked); neither zip kind carries a date of its own, so two saves of the same
edits are entry-for-entry the same.
"""

import os
import re
import zipfile

#: settings key: how many automatic backups a project keeps
KEEP_KEY = "project_backup_keep"
KEEP_DEFAULT = 10
KEEP_MAX = 50
#: the counts the load dialog offers
KEEP_CHOICES = (3, 5, 10, 20, 50)

#: a name :func:`pinball_decryptor.plugins.stern.mode_project.backup_path` gives
_AUTO = re.compile(r"^Before loading .+ (\d{4}-\d{2}-\d{2} \d{2}\.\d{2}\.\d{2})(?: \((\d+)\))?\.zip$")


def keep_of(settings):
    try:
        n = int((settings or {}).get(KEEP_KEY, KEEP_DEFAULT))
    except (TypeError, ValueError):
        n = KEEP_DEFAULT
    return max(1, min(KEEP_MAX, n))


def is_automatic(name):
    """Whether *name* is one the app gave a backup (a renamed or hand-made file is not)."""
    return bool(_AUTO.match(name))


def automatic(folder):
    """The app's own backups in *folder*, newest first (by the date in the name, then its ``(n)``)."""
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    out = []
    for n in names:
        m = _AUTO.match(n)
        p = os.path.join(folder, n)
        if m and os.path.isfile(p):
            out.append((m.group(1), int(m.group(2) or 1), p))
    out.sort(reverse=True)
    return [p for _s, _n, p in out]


def fingerprint(path):
    """Each entry's (name, size, CRC) of the zip at *path*, or None when it cannot be read."""
    try:
        with zipfile.ZipFile(path) as z:
            return sorted((i.filename, i.file_size, i.CRC) for i in z.infolist())
    except (OSError, zipfile.BadZipFile, ValueError):
        return None


def prune(folder, keep):
    """Remove all but the newest *keep* of the app's backups in *folder*; the names removed."""
    gone = []
    for p in automatic(folder)[max(1, int(keep)):]:
        try:
            os.remove(p)
            gone.append(os.path.basename(p))
        except OSError:
            pass
    return gone


def settle(path, keep=KEEP_DEFAULT):
    """After a backup was written to *path*: drop it when the newest earlier backup holds the same, then prune.

    Returns ``{"path": the backup that holds the edits, "same": True when that is the earlier one,
    "pruned": [names removed]}``."""
    folder = os.path.dirname(path)
    same = False
    earlier = [p for p in automatic(folder) if os.path.normcase(p) != os.path.normcase(path)]
    if earlier:
        mine = fingerprint(path)
        if mine is not None and mine == fingerprint(earlier[0]):
            try:
                os.remove(path)
                path, same = earlier[0], True
            except OSError:
                pass
    return {"path": path, "same": same, "pruned": prune(folder, keep)}
