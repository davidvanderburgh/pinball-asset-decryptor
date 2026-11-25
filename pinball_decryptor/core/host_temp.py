"""Windows temp-dir cleanup for the host-side staging the app leaves behind.

Several code paths stage on the Windows drive via ``tempfile.gettempdir()``
(normally ``%TEMP%`` = ``C:\\Users\\<you>\\AppData\\Local\\Temp``), independently
of WSL.  Most use context managers and auto-delete, but bare ``mkdtemp()`` dirs
can linger after a crash -- most notably **Stern Spike 2**, which never uses
WSL at all and stages its audio extract/build work entirely host-side.

This mirrors :mod:`core.wsl_disk` for that host temp dir:

  * :func:`usage`  -- the temp drive's total / used / free.
  * :func:`scan`   -- PAD-prefixed leftover dirs/files under the temp dir,
                      attributed to a manufacturer, with sizes.
  * :func:`delete` -- remove selected entries (guarded to direct children of
                      the temp dir whose name matches a known PAD prefix).

Unlike WSL this is the *local* filesystem, so it works on any OS / without WSL
(the GUI shows it alongside the WSL section, or on its own for Stern users who
have no WSL installed).
"""

import os
import re
import shutil
import tempfile

from . import pad_temp

# PAD-1596: the names are core/pad_temp.py's NAMES, the one list of what the
# app makes in the temp folder; ``(prefix, manufacturer, detail)`` here for
# the callers that read it.
_PREFIXES = tuple((n.prefix, n.maker, n.detail) for n in pad_temp.NAMES)
_PREFIX_STRINGS = tuple(p for p, _m, _d in _PREFIXES)


class HostTempError(Exception):
    """A host temp-dir operation failed (with a user-facing message)."""


def temp_dir():
    """The directory the app's host-side staging lands in (``%TEMP%``)."""
    return tempfile.gettempdir()


def usage():
    """Return the temp drive usage as ``{total, used, free, pct, drive}``."""
    td = temp_dir()
    total, used, free = shutil.disk_usage(td)
    pct = int(round(used * 100 / total)) if total else 0
    drive = os.path.splitdrive(os.path.abspath(td))[0] or td
    return {"total": total, "used": used, "free": free, "pct": pct,
            "drive": drive}


_HEX8 = re.compile(r"^[0-9a-f]{8}$")
#: Folders kept on purpose between builds (safe to clean: a build makes
#: them again), named so the Clean temp view says what they are.
_SPIKE2_KEPT = {n.prefix: n.detail for n in pad_temp.NAMES if n.kept}


def _spike2_detail(name):
    """Stern work dirs are now named ``spike2_<title>_<hex8>`` (or
    ``spike2_revert_<title>_<hex8>`` for a revert) so crash-leftovers are
    attributable; older ones were a bare random ``spike2_<suffix>`` with no
    title.  Return the game title (suffixed " (revert)" for reverts) when
    present, else the generic role."""
    if name in _SPIKE2_KEPT:
        return _SPIKE2_KEPT[name]
    rest = name[len("spike2_"):]
    head, _, tail = rest.rpartition("_")
    if not (head and _HEX8.match(tail)):
        return "audio extract / build staging"
    is_revert = head == "revert" or head.startswith("revert_")
    if head.startswith("revert_"):
        head = head[len("revert_"):]
    elif head == "revert":
        head = ""
    title = head.replace("_", " ").strip()
    if title:
        return f"{title} (revert)" if is_revert else title
    return "revert staging" if is_revert else "audio extract / build staging"


def _classify(name):
    n = pad_temp.lookup(name)
    if n is None:
        return "Other", name
    if n.prefix == "spike2_":
        return n.maker, _spike2_detail(name)
    return n.maker, n.detail


def _entry_size(path):
    """Total bytes under *path* (a single-file entry returns its own size)."""
    if os.path.isfile(path) or os.path.islink(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def scan(include_empty=False):
    """Return leftover host-temp entries, largest first.

    Each entry is ``{path, size, manufacturer, detail, in_use}``.  Only
    direct children of the temp dir whose name is one of the app's
    (:data:`pad_temp.NAMES`) are considered; ``in_use`` when the process
    that made it still runs (its detail says so).  Empty ones are left out
    of the window's list (nothing to free) unless *include_empty* (the
    space keeper, which tidies them away too).
    """
    td = temp_dir()
    entries = []
    try:
        names = os.listdir(td)
    except OSError:
        return entries
    for name in names:
        if name == pad_temp.OWNERS or pad_temp.lookup(name) is None:
            continue
        path = os.path.join(td, name)
        size = _entry_size(path)
        if size == 0 and not include_empty:
            continue  # empty leftover -- nothing to free, just noise
        mfr, detail = _classify(name)
        in_use = pad_temp.owner_state(name) == "alive"
        if in_use:
            detail += " (in use)"
        entries.append({"path": path, "size": size, "in_use": in_use,
                        "manufacturer": mfr, "detail": detail})
    entries.sort(key=lambda e: e["size"], reverse=True)
    return entries


def _is_safe(path):
    """True only for a direct child of the temp dir with one of the app's
    names, or an entry directly inside one of its caches (``child_days``,
    which the space keeper ages out one by one)."""
    td = os.path.normcase(os.path.realpath(temp_dir()))
    rp = os.path.realpath(path)
    parent = os.path.dirname(rp)
    if os.path.normcase(parent) == td:
        name = os.path.basename(rp)
        return name != pad_temp.OWNERS and pad_temp.lookup(name) is not None
    if os.path.normcase(os.path.dirname(parent)) == td:
        n = pad_temp.lookup(os.path.basename(parent))
        return bool(n and n.kept and n.child_days)
    return False


def delete(paths):
    """Remove each host-temp entry in *paths*; return bytes freed.

    Any path that isn't a known PAD-prefixed direct child of the temp dir
    raises :class:`HostTempError` *before* anything is deleted.
    """
    paths = [p for p in paths if p]
    if not paths:
        return 0
    for p in paths:
        if not _is_safe(p):
            raise HostTempError(
                f"Refusing to delete a path outside the temp dir: {p!r}")
    freed = 0
    for p in paths:
        name = os.path.basename(os.path.realpath(p))
        top = os.path.normcase(os.path.dirname(os.path.realpath(p))) ==             os.path.normcase(os.path.realpath(temp_dir()))
        if top and pad_temp.owner_state(name) == "alive":
            continue    # PAD-1596: a running build's or an open tab's
        freed += _entry_size(p)
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
        except OSError:
            # A file held open by a still-running operation can't be removed;
            # skip it rather than abort the whole sweep.
            pass
        if top and not os.path.lexists(p):
            pad_temp.forget_owner(name)
    return freed
