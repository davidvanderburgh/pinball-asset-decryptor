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

# (prefix, manufacturer, detail-role).  Ordered most-specific first so e.g.
# ``cc_dcs_`` is matched before the broader ``cc_``.  Kept in sync with the
# ``tempfile.mkdtemp(prefix=...)`` calls across the plugins:
#   stern/engine.py        -> spike2_*            (host-only; no WSL)
#   williams/*.py          -> williams_*          (DMD/video render; CGC reuses)
#   cgc/cc_dcs.py,cc_video  -> cc_dcs_*, cc_anim_*
#   dp/aaiw.py             -> pad_aaiw_*
#   spooky/*.py            -> spooky_*
#   jjp/pipeline.py        -> jjp_*               (host-side temp files)
#   core/audio.py          -> pad-ffmpeg-*
#   core/clonezilla.py     -> pad_iso_*
_PREFIXES = (
    ("spike2_", "Stern Pinball", "audio extract / build staging"),
    ("williams_", "Williams DMD render", "DMD / video render"),
    ("cc_dcs_", "Chicago Gaming Company", "Cactus Canyon DCS scratch"),
    ("cc_anim_", "Chicago Gaming Company", "Cactus Canyon video render"),
    ("cc_", "Chicago Gaming Company", "Cactus Canyon scratch"),
    ("pad_aaiw_", "Dutch Pinball", "Alice in Wonderland staging"),
    ("spooky_", "Spooky Pinball", "build scratch"),
    ("jjp_", "Jersey Jack Pinball", "staging"),
    ("pad-ffmpeg-", "Shared tooling", "ffmpeg helper"),
    ("pad_iso_", "Shared tooling", "ISO mount"),
)
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


def _spike2_detail(name):
    """Stern work dirs are now named ``spike2_<title>_<hex8>`` (or
    ``spike2_revert_<title>_<hex8>`` for a revert) so crash-leftovers are
    attributable; older ones were a bare random ``spike2_<suffix>`` with no
    title.  Return the game title (suffixed " (revert)" for reverts) when
    present, else the generic role."""
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
    for prefix, mfr, detail in _PREFIXES:
        if name.startswith(prefix):
            if prefix == "spike2_":
                return mfr, _spike2_detail(name)
            return mfr, detail
    return "Other", name


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


def scan():
    """Return leftover host-temp entries, largest first.

    Each entry is ``{path, size, manufacturer, detail}``.  Only direct children
    of the temp dir whose name matches a known PAD prefix are considered.
    """
    td = temp_dir()
    entries = []
    try:
        names = os.listdir(td)
    except OSError:
        return entries
    for name in names:
        if not name.startswith(_PREFIX_STRINGS):
            continue
        path = os.path.join(td, name)
        size = _entry_size(path)
        if size == 0:
            continue  # empty leftover -- nothing to free, just noise
        mfr, detail = _classify(name)
        entries.append({"path": path, "size": size,
                        "manufacturer": mfr, "detail": detail})
    entries.sort(key=lambda e: e["size"], reverse=True)
    return entries


def _is_safe(path):
    """True only for a direct child of the temp dir with a known PAD prefix."""
    td = os.path.realpath(temp_dir())
    rp = os.path.realpath(path)
    if os.path.normcase(os.path.dirname(rp)) != os.path.normcase(td):
        return False
    return os.path.basename(rp).startswith(_PREFIX_STRINGS)


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
    return freed
