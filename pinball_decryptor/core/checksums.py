"""Baseline checksum generation and reading — shared across plugins.

Each plugin's Extract pipeline calls :func:`generate_checksums` to write
``.checksums.md5`` next to the extracted files.  Write pipelines and
mod-pack export use :func:`read_checksums` to diff against the baseline.
"""

import hashlib
import os

CHECKSUMS_FILE = ".checksums.md5"


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_checksums(folder, log_cb=None, progress_cb=None):
    """Walk *folder* and write ``.checksums.md5``.  Returns file count.

    Symlinks and unreadable files (broken targets, locked files, OneDrive
    placeholders) are skipped with a warning rather than aborting.
    """
    files = []
    for dirpath, _, filenames in os.walk(folder):
        for fn in filenames:
            if fn.startswith("."):
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
