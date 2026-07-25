"""Folder-level project operations: sizes, Save-As fork copy, archive,
hydrate.

Everything here is deliberately plain — real file copies and deletes, no
symlinks/hardlinks/shortcuts anywhere (David: forks and archives must be
straightforward to process mentally; also links are unreliable on the
NAS/SMB shares these projects live on, and the Replace tabs edit extracted
files in place, so shared bytes would corrupt a sibling project).

Disk model (batch 19): a project folder's bulk is DERIVED — the extraction
comes from the stock image, ``build/`` is a rebuildable product.  The unique
bytes are the edited assets, ``.orig/`` snapshots, the sidecars and the
anchor.  So:

* ``fork_copy``    — Save As: copy the working state (everything but the
                     build dir), the fork carries the mods it was showing;
* ``archive``      — delete only files whose bytes EXACTLY match the
                     extract baseline (full hash, no mtime shortcuts — this
                     deletes, so it out-cautions even the revert scan) plus
                     the build dir, then flag the anchor archived;
* ``pre_hydrate`` / ``post_hydrate`` — bracket a normal re-extract when an
                     archived project is opened: edited files step aside
                     into ``.hydrate/``, the extract refills pristine
                     content, the edits move back over it.  First-move-wins
                     inside ``.hydrate`` so a crashed/repeated hydrate can
                     never replace true edited bytes with fresh pristine
                     ones.
"""

import os
import shutil

from .checksums import CHECKSUMS_FILE, md5_file, read_baseline_any
from . import project_file

# Default build-output subfolder name (overridable per project via the
# anchor's build_dir).  NOT a dot-name, so scanners need explicit excludes —
# see the slot scanners / Write diff / mod-pack export.
BUILD_DIR_NAME = "build"

# Edited files wait here, mirrored by relative path, while a hydrate's
# re-extract refills the folder.  Dotfolder: invisible to slot scanners.
HYDRATE_DIR = ".hydrate"


def _build_abs(folder, build_dir=None):
    return os.path.normpath(build_dir or os.path.join(folder, BUILD_DIR_NAME))


def _is_under(path, root):
    path = os.path.normcase(os.path.normpath(path))
    root = os.path.normcase(os.path.normpath(root))
    return path == root or path.startswith(root + os.sep)


def dir_size(path):
    """Total bytes under *path* (0 if missing).  Best-effort: unreadable
    entries are skipped, never raised."""
    total = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(path):
            for fn in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, fn))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def project_sizes(folder, build_dir=None):
    """Size breakdown for the Properties / manager UI:
    ``{"assets": n, "build": n, "mods": n}`` (bytes).

    assets = the visible extraction tree (non-dot roots, minus the build
    dir); build = the build dir; mods = the ``.orig/`` snapshot mirror (the
    dot sidecars are noise-level and aren't worth a stat pass)."""
    build_abs = _build_abs(folder, build_dir)
    sizes = {"assets": 0, "build": dir_size(build_abs), "mods": 0}
    try:
        entries = os.listdir(folder)
    except OSError:
        return sizes
    from .staged_originals import ORIG_DIR
    for name in entries:
        abs_path = os.path.join(folder, name)
        if _is_under(abs_path, build_abs):
            continue
        if name == ORIG_DIR:
            sizes["mods"] += dir_size(abs_path)
            continue
        if name.startswith("."):
            continue
        if os.path.isdir(abs_path):
            sizes["assets"] += dir_size(abs_path)
        else:
            try:
                sizes["assets"] += os.path.getsize(abs_path)
            except OSError:
                pass
    return sizes


def iter_fork_files(folder, build_dir=None):
    """Yield ``(abs, rel)`` for everything Save As copies: the whole tree —
    dotfiles and ``.orig/`` included (the fork must revert like the
    original) — EXCEPT the build dir and any ``.hydrate/`` leftovers."""
    build_abs = _build_abs(folder, build_dir)
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames
                       if not _is_under(os.path.join(dirpath, d), build_abs)
                       and d != HYDRATE_DIR]
        for fn in filenames:
            abs_path = os.path.join(dirpath, fn)
            yield abs_path, os.path.relpath(abs_path, folder)


def fork_size(folder, build_dir=None):
    """Bytes Save As would copy — shown up front so the disk cost is a
    visible choice."""
    total = 0
    for abs_path, _rel in iter_fork_files(folder, build_dir):
        try:
            total += os.path.getsize(abs_path)
        except OSError:
            pass
    return total


def fork_copy(folder, dest, *, build_dir=None, progress=None, cancel=None):
    """Copy the project's working state into *dest* (created if missing).

    Plain ``copy2`` per file.  Returns ``(files_copied, bytes_copied,
    cancelled)`` — on cancel the caller decides what to do with the partial
    destination (the app deletes it).  Raises OSError on a hard copy
    failure."""
    cancel = cancel or (lambda: False)
    files = list(iter_fork_files(folder, build_dir))
    os.makedirs(dest, exist_ok=True)
    copied = 0
    nbytes = 0
    for i, (abs_path, rel) in enumerate(files):
        if cancel():
            return copied, nbytes, True
        target = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(abs_path, target)
        copied += 1
        try:
            nbytes += os.path.getsize(target)
        except OSError:
            pass
        if progress:
            progress(i + 1, len(files), rel)
    return copied, nbytes, False


def archive(folder, *, build_dir=None, progress=None, cancel=None):
    """Shrink a dormant project to its unique bytes.

    Flags the anchor ``archived`` FIRST — any partial state (cancel, crash)
    must already read as archived so the app demands a hydrate before the
    tabs can scan (the staged-changes validator prunes entries whose slot
    file is missing).  Then per baseline entry: full-hash the file and
    delete it only on an exact match — hash-then-delete one file at a time,
    so a cancel can never delete a file it didn't just verify.  Finally the
    build dir goes and emptied directories are pruned.

    Returns ``(deleted, freed_bytes, cancelled)``."""
    cancel = cancel or (lambda: False)
    project_file.update_anchor(folder, archived=True)
    baseline = read_baseline_any(folder)
    rels = sorted(baseline)
    deleted = 0
    freed = 0
    cancelled = False
    for i, rel in enumerate(rels):
        if cancel():
            cancelled = True
            break
        if progress:
            progress(i, len(rels), rel)
        abs_path = os.path.join(folder, *rel.split("/"))
        try:
            if not os.path.isfile(abs_path):
                continue
            size = os.path.getsize(abs_path)
            if md5_file(abs_path) != baseline[rel]:
                continue          # edited — unique bytes, keep
            os.remove(abs_path)
            deleted += 1
            freed += size
        except OSError:
            continue
    if not cancelled:
        build_abs = _build_abs(folder, build_dir)
        freed += dir_size(build_abs)
        shutil.rmtree(build_abs, ignore_errors=True)
        _prune_empty_dirs(folder)
    if progress:
        progress(len(rels), len(rels), "")
    return deleted, freed, cancelled


def pre_hydrate(folder, build_dir=None):
    """Move every visible (non-dot, non-build) file into ``.hydrate/`` so a
    normal re-extract can refill the folder without touching edited bytes.

    First move WINS: a rel already present in ``.hydrate/`` is left alone
    (it is the true edited copy from an earlier, interrupted hydrate — the
    file now in the folder would be freshly-extracted pristine content).
    Returns the number of files set aside."""
    build_abs = _build_abs(folder, build_dir)
    hydrate_root = os.path.join(folder, HYDRATE_DIR)
    moved = 0
    for dirpath, dirnames, filenames in os.walk(folder):
        if dirpath == folder:
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".")
                           and not _is_under(os.path.join(dirpath, d),
                                             build_abs)]
            filenames = [f for f in filenames if not f.startswith(".")]
        for fn in filenames:
            abs_path = os.path.join(dirpath, fn)
            rel = os.path.relpath(abs_path, folder)
            target = os.path.join(hydrate_root, rel)
            if os.path.exists(target):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.replace(abs_path, target)
            moved += 1
    _prune_empty_dirs(folder)
    return moved


def post_hydrate(folder):
    """Move the set-aside files back OVER the freshly-extracted content and
    clear the archived flag.  Returns the number restored."""
    hydrate_root = os.path.join(folder, HYDRATE_DIR)
    restored = 0
    if os.path.isdir(hydrate_root):
        for dirpath, _dirnames, filenames in os.walk(hydrate_root):
            for fn in filenames:
                abs_path = os.path.join(dirpath, fn)
                rel = os.path.relpath(abs_path, hydrate_root)
                target = os.path.join(folder, rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(abs_path, target)
                restored += 1
        shutil.rmtree(hydrate_root, ignore_errors=True)
    project_file.update_anchor(folder, archived=False)
    return restored


def _prune_empty_dirs(folder):
    """Remove directories emptied by archive/pre_hydrate (bottom-up; the
    project root itself always stays).  ``rmdir`` is attempted on every
    directory — it refuses non-empty ones, which is exactly the test we
    want (the walk's own dirnames listing predates the children's removal,
    so checking it would leave freshly-emptied parents behind)."""
    for dirpath, _dirnames, _filenames in os.walk(folder, topdown=False):
        if dirpath == folder:
            continue
        try:
            os.rmdir(dirpath)
        except OSError:
            pass
