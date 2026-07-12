"""Mod-pack export/import — zip the files that differ from the baseline.

Manufacturer-agnostic: only relies on ``.checksums.md5`` written by the
shared :mod:`core.checksums` module.
"""

import os
import zipfile

from .checksums import CHECKSUMS_FILE, md5_file, read_baseline_any


def export_mod_pack(assets_folder, zip_path, log_cb=None, progress_cb=None):
    """Zip only files that differ from the baseline checksums.

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
    for i, (rel, orig_md5) in enumerate(baseline.items()):
        if progress_cb:
            progress_cb(i, len(baseline), rel)
        abs_path = os.path.join(assets_folder, rel)
        if not os.path.isfile(abs_path):
            continue
        if md5_file(abs_path) != orig_md5:
            changed.append(rel)

    if not changed:
        raise ValueError("No modified files found. Modify some files first.")

    if log_cb:
        log_cb(f"Packing {len(changed)} modified file(s)...", "info")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, rel in enumerate(changed):
            zf.write(os.path.join(assets_folder, rel), rel)
            if progress_cb:
                progress_cb(i + 1, len(changed), rel)

    return len(changed), zip_path


def import_mod_pack(zip_path, assets_folder, log_cb=None, progress_cb=None):
    """Extract a mod-pack zip into *assets_folder*.  Returns file count."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        if log_cb:
            log_cb(f"Importing {len(names)} file(s)...", "info")
        for i, name in enumerate(names):
            zf.extract(name, assets_folder)
            if progress_cb:
                progress_cb(i + 1, len(names), name)
    return len(names)
