"""File-format detection + ZIP helpers for American Pinball game files."""

import os
import zipfile

from ...core.checksums import CHECKSUMS_FILE
from .crypto import looks_like_ap_pkg
from .games import GAME_DB, PKG_FILENAME_PATTERNS


class GameFile:
    """Detected game file metadata."""

    def __init__(self, path, game_key, game_name, format_type, ext, notes=""):
        self.path = path
        self.game_key = game_key
        self.game_name = game_name
        self.format_type = format_type
        self.ext = ext
        self.notes = notes


def detect_game(path):
    """Detect an American Pinball game file.

    Returns a :class:`GameFile` or ``None``.  Only ``.pkg`` game-code updates
    are recognised; the Clonezilla ``.iso`` images use a partclone ext4 layout
    that isn't wired up yet.
    """
    _, ext = os.path.splitext(path)
    if ext.lower() != ".pkg":
        return None
    return _detect_pkg(path, os.path.basename(path))


def _detect_pkg(path, basename):
    basename_lower = basename.lower()

    # 1. Filename hints encode the title directly (e.g. houdini-gamecode...).
    for pattern, game_key in PKG_FILENAME_PATTERNS:
        if pattern in basename_lower:
            display = GAME_DB[game_key]["display"]
            return GameFile(path, game_key, display, "aes_pkg", ".pkg")

    # 2. Unknown name — confirm it's ours with a key-validated probe so we
    #    don't false-claim another maker's AES .pkg.
    if looks_like_ap_pkg(path):
        return GameFile(path, None, "American Pinball (.pkg)", "aes_pkg",
                        ".pkg", notes="detected via universal key")

    return None


# ---------------------------------------------------------------------------
# ZIP helpers (extract / create)
# ---------------------------------------------------------------------------

def extract_zip(zip_path, output_dir, progress_cb=None):
    """Extract a ZIP archive into *output_dir*; return the member list.

    ``ZipFile.extract`` sanitises member paths (strips leading slashes and
    rejects ``..`` traversal), so this is safe against malicious archives.
    """
    extracted = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.namelist()
        total = len(members)
        for i, member in enumerate(members):
            zf.extract(member, output_dir)
            extracted.append(member)
            if progress_cb and (i % 50 == 0 or i == total - 1):
                progress_cb(i + 1, total, member)
    return extracted


def create_zip(source_dir, out_path, progress_cb=None):
    """Create a deflate ZIP from *source_dir*, preserving relative paths.

    Skips the ``.checksums.md5`` baseline so it doesn't end up inside the
    rebuilt package.
    """
    files = []
    for root, _dirs, names in os.walk(source_dir):
        for name in names:
            if name == CHECKSUMS_FILE:
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, source_dir).replace("\\", "/")
            files.append((full, rel))
    files.sort(key=lambda x: x[1])

    total = len(files)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, (full, rel) in enumerate(files):
            zf.write(full, rel)
            if progress_cb and (i % 50 == 0 or i == total - 1):
                progress_cb(i + 1, total, rel)
