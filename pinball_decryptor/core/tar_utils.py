"""Tar-related helpers used by .upd-style pipelines."""

import os


def safe_member(member, dest_dir):
    """Return *member* if it's safe to extract; None otherwise.

    Rejects absolute paths, drive letters, and ``..`` traversal.
    """
    name = member.name
    if not name:
        return None
    if name.startswith("/") or name.startswith("\\"):
        return None
    if len(name) > 1 and name[1] == ":":  # Windows-style C:\foo
        return None
    parts = name.replace("\\", "/").split("/")
    if any(p == ".." for p in parts):
        return None
    return member


def truncation_hint(archive_path, original_exc, support_url_hint=None):
    """Build a user-facing error message for a likely-truncated archive."""
    try:
        size = os.path.getsize(archive_path)
    except OSError:
        size = -1
    name = os.path.basename(archive_path)
    base = (
        f"The archive appears to be truncated or corrupt:\n"
        f"  {name}  ({size:,} bytes on disk)\n\n"
        f"This is usually a partial download.  Try re-downloading the file."
    )
    if support_url_hint:
        base += f"\n\n{support_url_hint}"
    base += f"\n\nOriginal error: {original_exc}"
    return base


def format_size(nbytes):
    if nbytes < 1024:
        return f"{nbytes} B"
    if nbytes < 1024 ** 2:
        return f"{nbytes / 1024:.1f} KiB"
    if nbytes < 1024 ** 3:
        return f"{nbytes / 1024**2:.1f} MiB"
    return f"{nbytes / 1024**3:.2f} GiB"
