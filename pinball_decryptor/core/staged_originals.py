"""Pristine-original snapshot cache, so a staged edit can be reverted without
re-extracting the whole card.

The Replace tabs apply edits by writing the converted replacement *over* the
extracted file in the assets folder (see ``core.audio_slots.stage_replacements``
and its video/image twins) — the Write pipeline then diffs the folder against
the Extract baseline (``.checksums.md5``) and repacks whatever changed.  That
makes every build self-contained, but it also means there's no copy of the
original bytes left to go back to: once a slot is staged, the only way to "undo"
it was a full re-extract (slow, and it re-reads gigabytes off the card).

This module keeps a tiny per-file backup: the *first* time a file is about to be
overwritten, its pristine (baseline-matching) bytes are copied into an
``.orig/`` mirror at the root of the assets folder.  Reverting is then an instant
local copy back — and costs disk only for the handful of files actually edited,
not a second full extract.

Files with no snapshot (edited before this feature shipped, or hand-edited
outside the Replace tabs so they never matched the baseline) can't be restored
from here; the caller falls back to re-decoding just those from the source image.

``.orig`` is a dotfolder so the slot scanners and the Write/mod-pack diff (which
all skip dot-entries / unknown paths) ignore it; :data:`ORIG_DIR`.
"""

import os
import shutil

from .checksums import md5_file

# Backup mirror at the assets-folder root.  Dotfolder so the audio/video/image
# slot scanners (which skip dot-entries) and the baseline diff never treat its
# contents as editable assets.
ORIG_DIR = ".orig"


def _orig_abs(assets_dir, rel):
    """Absolute path of the snapshot for *rel* (a ``/``-separated rel path)."""
    return os.path.join(assets_dir, ORIG_DIR, *rel.split("/"))


def snapshot(assets_dir, rel, baseline_md5):
    """Back up the pristine bytes of ``assets_dir/rel`` into ``.orig/`` before it
    is first modified.  Returns ``True`` if a snapshot was taken.

    No-op (returns ``False``) when:
      * a snapshot already exists — the existing one is the *true* original and
        must not be clobbered by an already-modified file on a later build;
      * the file is missing;
      * *baseline_md5* is given and the file no longer matches it — the file has
        already diverged with no snapshot, so its current bytes are NOT the
        original and capturing them would "revert" to the wrong content.  Pass
        ``None`` to snapshot unconditionally (caller vouches it's pristine).
    """
    if not assets_dir or not rel:
        return False
    src = os.path.join(assets_dir, *rel.split("/"))
    if not os.path.isfile(src):
        return False
    dst = _orig_abs(assets_dir, rel)
    if os.path.exists(dst):
        return False
    if baseline_md5 is not None:
        try:
            if md5_file(src) != baseline_md5:
                return False
        except OSError:
            return False
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except OSError:
        return False


def has_snapshot(assets_dir, rel):
    """True if a pristine snapshot of *rel* is on hand."""
    return bool(assets_dir) and os.path.isfile(_orig_abs(assets_dir, rel))


def snapshot_rels(assets_dir):
    """Set of ``/``-separated rel paths that have a snapshot under ``.orig/``."""
    out = set()
    if not assets_dir:
        return out
    root = os.path.join(assets_dir, ORIG_DIR)
    if not os.path.isdir(root):
        return out
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            rel = os.path.relpath(os.path.join(dirpath, fn), root)
            out.add(rel.replace(os.sep, "/"))
    return out


def revert(assets_dir, rel):
    """Restore ``assets_dir/rel`` from its snapshot and drop the snapshot.

    Returns ``True`` if a snapshot existed and the file was restored, ``False``
    when there's nothing to restore (the caller then falls back to the source
    image).  Empty ``.orig`` subfolders left behind are pruned.
    """
    if not assets_dir or not rel:
        return False
    src = _orig_abs(assets_dir, rel)
    if not os.path.isfile(src):
        return False
    dst = os.path.join(assets_dir, *rel.split("/"))
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        os.remove(src)
    except OSError:
        return False
    _prune_empty_dirs(os.path.join(assets_dir, ORIG_DIR), os.path.dirname(src))
    return True


def revert_all(assets_dir):
    """Restore every snapshotted file and remove the ``.orig`` tree.

    Returns the list of rel paths restored.  Files that fail to restore are left
    in ``.orig`` (so the tree is only removed when it's actually empty).
    """
    reverted = []
    for rel in sorted(snapshot_rels(assets_dir)):
        if revert(assets_dir, rel):
            reverted.append(rel)
    root = os.path.join(assets_dir, ORIG_DIR)
    if os.path.isdir(root) and not os.listdir(root):
        try:
            os.rmdir(root)
        except OSError:
            pass
    return reverted


def discard(assets_dir):
    """Delete the whole ``.orig`` snapshot tree without restoring anything.

    Used by Extract: a fresh decode rewrites every file pristine and lays down a
    new baseline, so any snapshots from a previous session now describe stale
    content and must go.
    """
    if not assets_dir:
        return
    root = os.path.join(assets_dir, ORIG_DIR)
    if os.path.isdir(root):
        shutil.rmtree(root, ignore_errors=True)


def _prune_empty_dirs(stop_at, start):
    """Remove *start* and its empty parents up to (not including) *stop_at*."""
    cur = start
    stop = os.path.normpath(stop_at)
    while cur and os.path.normpath(cur) != stop and os.path.isdir(cur):
        try:
            os.rmdir(cur)        # only succeeds when empty
        except OSError:
            break
        cur = os.path.dirname(cur)
