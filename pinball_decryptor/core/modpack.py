"""Mod-pack export/import — zip the files that differ from the baseline.

Manufacturer-agnostic: only relies on ``.checksums.md5`` written by the
shared :mod:`core.checksums` module.
"""

import json
import os
import zipfile

from . import hashcache
from . import staged_originals
from .checksums import CHECKSUMS_FILE, TRACKING_SIDECARS, read_baseline_any
from .extract_source import read_extract_source, version_hint_from_name

# Manifest written into every pack, naming the extract it was built from so
# Import can say what it's applying (and warn on an obvious mismatch).  The
# help text has always promised this; nothing wrote it until batch 16.
MANIFEST_NAME = ".modpack.json"


def _is_packable(rel):
    """False for baseline entries that are pipeline scratch, not card assets.

    ``fl_decrypted.dat`` (JJP's decrypted blob) and any ``.img`` are written
    at extract time — so they ARE in the baseline — and get rewritten by later
    steps, which made them read as "modified" and land in the pack.  They are
    hundreds of MB and useless to the recipient, and they are exactly why an
    audio-only mod pack could weigh 350 MB (monkeybug batch 16).  The Write
    tab's Modified-Files preview already hides them for the same reason.
    """
    name = os.path.basename(rel)
    return not (name.startswith(".")
                or name == "fl_decrypted.dat"
                or name.lower().endswith(".img")
                or name in TRACKING_SIDECARS)


def _human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.0f %s" % (n, unit) if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0


def export_mod_pack(assets_folder, zip_path, log_cb=None, progress_cb=None):
    """Zip only files that differ from the baseline checksums.

    The diff is against ``.checksums.md5`` from the LAST extract of this
    folder, so a pack carries every change made since that extract — not just
    this session's.  Re-extracting into a folder re-baselines it, which resets
    what counts as "modified" (see the log line this emits).

    Returns ``(count, zip_path)``.
    """
    # read_baseline_any, not read_checksums: the baseline ships in two
    # flavours (md5sum-style for JJP, path\tmd5 for BOF/Stern) and the
    # tab-only parser silently returns {} for the md5sum form — which
    # here read as "no baseline, extract first" on a valid JJP extract.
    baseline = read_baseline_any(assets_folder)
    if not baseline:
        raise FileNotFoundError(
            f"No {CHECKSUMS_FILE} found in {assets_folder}. Extract first.")

    if log_cb:
        log_cb(f"Comparing {len(baseline)} file(s) against the extract "
               f"baseline...", "info")
    changed = []
    skipped_scratch = 0
    n_base = len(baseline)
    # Size+mtime MD5 cache (shared with the Write change scan): unchanged
    # files skip the re-hash, so an export right after a scan is near-instant.
    hcache = hashcache.load(assets_folder)
    for i, (rel, orig_md5) in enumerate(baseline.items()):
        if progress_cb:
            # The compare pass walks EVERY baseline file (that's how changed
            # ones are found, whatever their type) — say so, or an audio-only
            # modder watching video paths scroll by reads it as wasted work.
            progress_cb(i, n_base,
                        "Comparing %d of %d: %s" % (i + 1, n_base, rel))
        abs_path = os.path.join(assets_folder, rel)
        if not os.path.isfile(abs_path):
            continue
        digest = hashcache.md5_for(abs_path, rel, hcache)
        if digest is not None and digest != orig_md5:
            if _is_packable(rel):
                changed.append(rel)
            else:
                skipped_scratch += 1
    hashcache.save(assets_folder, hcache)

    if not changed:
        raise ValueError("No modified files found. Modify some files first.")

    total_bytes = 0
    for rel in changed:
        try:
            total_bytes += os.path.getsize(os.path.join(assets_folder, rel))
        except OSError:
            pass

    if log_cb:
        log_cb("Packing %d modified file(s), %s of assets..."
               % (len(changed), _human_size(total_bytes)), "info")
        if skipped_scratch:
            log_cb("Skipped %d rebuilt working file(s) (decrypted blobs / raw "
                   "images) — they aren't card assets and would bloat the pack."
                   % skipped_scratch, "info")
        # The pack is a diff against the LAST extract of this folder, so say
        # what that baseline is: re-extracting resets it, which is what makes
        # a pack look like it only holds "this session's" changes.
        log_cb("These are all the changes in this folder since its last "
               "extract (%d baselined file(s) compared), not just this "
               "session's." % n_base, "info")

    src = read_extract_source(assets_folder) or {}
    manifest = {
        "format": 1,
        "source_name": src.get("input_name") or "",
        "version_hint": version_hint_from_name(src.get("input_name")) or "",
        "file_count": len(changed),
        "total_bytes": total_bytes,
        "files": sorted(changed),
    }

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
        for i, rel in enumerate(changed):
            zf.write(os.path.join(assets_folder, rel), rel)
            if progress_cb:
                progress_cb(i + 1, len(changed),
                            "Archiving %d of %d: %s" % (i + 1, len(changed),
                                                        rel))

    return len(changed), zip_path


def import_mod_pack(zip_path, assets_folder, log_cb=None, progress_cb=None):
    """Extract a mod-pack zip into *assets_folder*.  Returns file count.

    Packs written since batch 16 carry :data:`MANIFEST_NAME`, so we can say
    which extract they were built from and flag an obvious version mismatch.
    Older packs have no manifest and import exactly as before.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = [n for n in zf.namelist() if n != MANIFEST_NAME]
        manifest = None
        try:
            manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
        except (KeyError, ValueError, UnicodeDecodeError):
            pass
        if log_cb:
            if isinstance(manifest, dict):
                made_from = (manifest.get("version_hint")
                             or manifest.get("source_name") or "")
                if made_from:
                    log_cb("This pack was made from %s." % made_from, "info")
                    here = version_hint_from_name(
                        (read_extract_source(assets_folder) or {})
                        .get("input_name"))
                    hint = manifest.get("version_hint")
                    if here and hint and here != hint:
                        log_cb("This extract is %s — the pack was built "
                               "against %s. Importing across versions can "
                               "produce a card that won't boot; use "
                               "\"Transfer Mods to New Version\" instead."
                               % (here, hint), "warning")
            log_cb(f"Importing {len(names)} file(s)...", "info")
        # Snapshot each pristine original into .orig/ before it's overwritten
        # (same backup staging takes), so an imported change previews its true
        # original and "Revert" can undo it without a re-extract.  snapshot()
        # verifies against the baseline md5, so a file that already diverged
        # (or a pack entry not in the baseline) is left un-snapshotted rather
        # than captured wrong.
        baseline = read_baseline_any(assets_folder)
        for i, name in enumerate(names):
            rel = name.replace("\\", "/")
            md5 = baseline.get(rel)
            if md5 is not None:
                staged_originals.snapshot(assets_folder, rel, md5)
            zf.extract(name, assets_folder)
            if progress_cb:
                progress_cb(i + 1, len(names), name)
    return len(names)
