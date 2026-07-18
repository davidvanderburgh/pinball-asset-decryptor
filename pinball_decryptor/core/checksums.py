"""Baseline checksum generation and reading — shared across plugins.

Each plugin's Extract pipeline calls :func:`generate_checksums` to write
``.checksums.md5`` next to the extracted files.  Write pipelines and
mod-pack export use :func:`read_checksums` to diff against the baseline.
"""

import hashlib
import os
import re

CHECKSUMS_FILE = ".checksums.md5"

# A ``.checksums.md5`` line in md5sum form: "<md5>  <path>" (optionally "*path").
_MD5SUM_LINE = re.compile(r'^([a-f0-9]{32})\s+\*?(.+)$')

# Auto-name output sidecars (callouts.csv / music_titles.csv).  These are
# derived tracking metadata — they have no destination inside the card/ISO
# binary and must never be diffed as a "modified asset".  Excluded both from
# the baseline written here and from the Write "Modified Files Preview".
TRACKING_SIDECARS = frozenset({"callouts.csv", "music_titles.csv"})


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_checksums(folder, log_cb=None, progress_cb=None,
                       exclude_dirs=None, cancel=None):
    """Walk *folder* and write ``.checksums.md5``.  Returns file count.

    Symlinks and unreadable files (broken targets, locked files, OneDrive
    placeholders) are skipped with a warning rather than aborting.

    *exclude_dirs* is an optional iterable of directory names (relative
    to *folder*, with ``/`` separators) to skip entirely.  Used by the
    CGC plugin to keep the derived ``dmd/`` extraction folder out of
    the modding baseline -- those files don't correspond to anything
    inside the eMMC's ext4 partition.

    *cancel* is an optional zero-arg predicate; when it returns True the hashing
    loop stops promptly and returns the partial count, so a cancelled extract
    doesn't grind through hashing a large output before the pipeline notices
    (the caller re-checks cancel afterwards to report the cancellation).
    """
    cancel = cancel or (lambda: False)
    # Always exclude the .orig snapshot mirror (core.staged_originals) — it is a
    # backup of edited assets, not part of the card, and must never enter the
    # baseline (else a re-extract would record the snapshots as real files).
    from .staged_originals import ORIG_DIR
    excluded = {d.replace("\\", "/").strip("/")
                for d in (exclude_dirs or ())}
    excluded.add(ORIG_DIR)
    files = []
    for dirpath, dirnames, filenames in os.walk(folder):
        rel_dir = os.path.relpath(dirpath, folder).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        # Prune excluded subtrees in-place so os.walk doesn't descend.
        dirnames[:] = [
            d for d in dirnames
            if (f"{rel_dir}/{d}" if rel_dir else d) not in excluded
        ]
        for fn in filenames:
            if fn.startswith("."):
                continue
            if fn in TRACKING_SIDECARS:
                continue
            abs_path = os.path.join(dirpath, fn)
            if os.path.islink(abs_path):
                continue
            rel_path = os.path.relpath(abs_path, folder).replace("\\", "/")
            files.append((rel_path, abs_path))

    out_path = os.path.join(folder, CHECKSUMS_FILE)
    skipped = 0
    written = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for i, (rel_path, abs_path) in enumerate(files):
            if cancel():
                break
            try:
                md5 = md5_file(abs_path)
            except OSError as e:
                skipped += 1
                if log_cb and skipped <= 5:
                    log_cb(f"  Skipping (cannot read): {rel_path} — {e}", "info")
                elif log_cb and skipped == 6:
                    log_cb("  ... further unreadable files will be skipped silently.",
                           "info")
                continue
            out.write(f"{rel_path}\t{md5}\n")
            written += 1
            if progress_cb:
                progress_cb(i + 1, len(files), rel_path)

    if log_cb:
        if skipped:
            log_cb(f"Checksums written for {written} file(s); skipped {skipped} "
                   f"unreadable.", "success")
        else:
            log_cb(f"Checksums written for {written} file(s).", "success")
    return written


def read_checksums(folder):
    """Read ``.checksums.md5`` from *folder*.  Returns {rel_path: md5}."""
    path = os.path.join(folder, CHECKSUMS_FILE)
    baseline = {}
    if not os.path.isfile(path):
        return baseline
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if "\t" in line:
                rel, md5 = line.rsplit("\t", 1)
                baseline[rel] = md5
    return baseline


def read_baseline_any(folder):
    """Read ``.checksums.md5`` in *either* on-disk flavour → ``{rel: md5}``.

    Two plugins write the baseline differently:
      * JJP / md5sum style — ``"<md5>  <path>"`` (md5 first);
      * BOF / Stern style  — ``"<path>\\t<md5>"``  (path first).
    :func:`read_checksums` only parses the tab form; this robust superset
    detects per-line, so a single helper can diff any plugin's folder.  Paths
    are normalised to forward slashes with any leading ``./`` stripped.
    """
    path = os.path.join(folder, CHECKSUMS_FILE)
    baseline = {}
    if not os.path.isfile(path):
        return baseline
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = _MD5SUM_LINE.match(line)
            if m:
                md5_val, rel = m.group(1), m.group(2)
            elif "\t" in line:
                rel, md5_val = line.rsplit("\t", 1)
                md5_val = md5_val.strip()
                if not re.fullmatch(r'[a-f0-9]{32}', md5_val):
                    continue
            else:
                continue
            if rel.startswith("./"):
                rel = rel[2:]
            baseline[rel.replace("\\", "/")] = md5_val
    return baseline


def rename_in_baseline(folder, renames):
    """Re-point baseline entries for files that were *moved* (not edited).

    *renames* maps ``old_rel -> new_rel`` (``/``-separated).  A rename preserves
    the bytes, so the md5 carries over unchanged — we just move the key.  Used by
    the Auto-name step (transcribe / music-ID), which renames
    ``audio/idxNNNN.wav`` to ``audio/idxNNNN - Title.wav`` *after* the Extract
    baseline was written (the rename pipeline is chained after the Extract that
    emits ``.checksums.md5``).  Without this re-point the renamed file's new path
    is absent from the baseline, so the Replace-tab change-scan flags every
    auto-named track as "changed on disk" even though nothing was edited.

    Returns the number of entries moved.  No-op (returns 0) when there's no
    baseline file or none of the *old_rel* keys are present.
    """
    if not renames:
        return 0
    path = os.path.join(folder, CHECKSUMS_FILE)
    if not os.path.isfile(path):
        return 0
    baseline = read_baseline_any(folder)
    moved = 0
    for old_rel, new_rel in renames.items():
        old_rel = old_rel.replace("\\", "/")
        new_rel = new_rel.replace("\\", "/")
        if old_rel == new_rel or old_rel not in baseline:
            continue
        baseline[new_rel] = baseline.pop(old_rel)
        moved += 1
    if not moved:
        return 0
    with open(path, "w", encoding="utf-8") as out:
        for rel, md5 in baseline.items():
            out.write(f"{rel}\t{md5}\n")
    return moved


def changed_rels(folder, rels, baseline=None):
    """Return the subset of *rels* whose current bytes differ from the baseline.

    *rels* is an iterable of ``/``-separated paths relative to *folder* (e.g. the
    Replace tab's slot paths).  A rel that's missing from the baseline is treated
    as changed (a brand-new / un-baselined file).  Unreadable files are reported
    as changed rather than silently clean.  *baseline* defaults to
    :func:`read_baseline_any`.
    """
    if baseline is None:
        baseline = read_baseline_any(folder)
    # Shared size+mtime MD5 cache (see core.hashcache): unchanged files skip
    # the re-hash, which is most of a Replace tab's changed-marks pass.
    from . import hashcache
    hcache = hashcache.load(folder)
    out = set()
    for rel in rels:
        abs_path = os.path.join(folder, *rel.split("/"))
        base = baseline.get(rel)
        cur = hashcache.md5_for(abs_path, rel, hcache)
        if cur is None or base is None or cur != base:
            out.add(rel)
    hashcache.save(folder, hcache)
    return out


def all_changed(folder, baseline=None, progress=None, cancel=None, quick=False):
    """Every *baselined* rel under *folder* whose bytes now differ — the set the
    Write build repacks, and so the set "Revert all changes" restores.

    Only files present in the baseline are checked (a brand-new file has no
    original to revert to), and the ``.orig`` snapshot mirror is excluded.
    *progress(current, total)* and *cancel()* (stop early) are optional — the
    walk hashes potentially many files, so callers run it off the UI thread.

    *quick* enables an mtime fast-path for the revert "anything left to restore?"
    scan: :func:`generate_checksums` writes ``.checksums.md5`` LAST, so a pristine
    extracted asset always has ``mtime <= checksums-file mtime``.  Any file at or
    below that mtime is taken as unchanged and skipped without hashing — turning a
    multi-GB re-hash (slow over a network share) into cheap ``stat`` calls.  A
    real post-extract edit always bumps the file's mtime past the baseline, so the
    fast-path can't miss one; only files modified after extract get hashed.  Off by
    default (the Write build keeps the exact byte-for-byte scan).
    """
    if baseline is None:
        baseline = read_baseline_any(folder)
    cancel = cancel or (lambda: False)
    skip_mtime = None
    if quick:
        try:
            skip_mtime = int(os.path.getmtime(os.path.join(folder, CHECKSUMS_FILE)))
        except OSError:
            skip_mtime = None        # no baseline file → fall back to full hash
    # ".orig/" is the snapshot mirror (core.staged_originals); never in a fresh
    # baseline, but filter defensively so a stale entry can't sneak in.
    rels = [r for r in baseline if not r.startswith(".orig/")]
    out = set()
    total = len(rels)
    for i, rel in enumerate(rels):
        if cancel():
            break
        if progress:
            progress(i, total)
        abs_path = os.path.join(folder, *rel.split("/"))
        try:
            if skip_mtime is not None and int(os.path.getmtime(abs_path)) <= skip_mtime:
                continue             # untouched since extract — pristine, skip hash
            if md5_file(abs_path) != baseline[rel]:
                out.add(rel)
        except OSError:
            # Missing/unreadable now but present at extract — treat as changed so
            # the caller can try to restore it.
            out.add(rel)
    if progress:
        progress(total, total)
    return out
