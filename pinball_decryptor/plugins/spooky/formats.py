"""File-format detection + archive helpers for Spooky game files."""

import os
import struct
import tarfile
import zipfile

from .games import (GAME_DB, KNOWN_GAMES, PKG_FILENAME_PATTERNS,
                    ZIP_GAME_PATTERNS)


class GameFile:
    """Detected game file metadata."""

    def __init__(self, path, game_key, game_name, format_type, ext):
        self.path = path
        self.game_key = game_key
        self.game_name = game_name
        self.format_type = format_type
        self.ext = ext


def detect_game(path):
    """Detect game type from file extension, filename, and magic bytes.

    Returns ``GameFile`` or ``None`` if unrecognized.
    """
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    basename = os.path.basename(path)

    # 1. Unique extensions (.ed, .scooby, .beetlejuice, .looney)
    if ext in KNOWN_GAMES:
        game_key, fmt = KNOWN_GAMES[ext]
        display = GAME_DB[game_key]["display"]
        return GameFile(path, game_key, display, fmt, ext)

    # 2. .pkg files — filename + magic byte detection
    if ext == ".pkg":
        return _detect_pkg(path, basename)

    # 3. .zip files — could be game update (P3) or Clonezilla image
    if ext == ".zip":
        return _detect_zip(path, basename)

    # 4. .iso files — always Clonezilla
    if ext == ".iso":
        return GameFile(path, None, "Restore Image", "clonezilla", ext)

    return None


def _detect_pkg(path, basename):
    basename_lower = basename.lower()

    # Filename patterns first (they encode the right key for decryption)
    for pattern, game_key, fmt in PKG_FILENAME_PATTERNS:
        if pattern.lower() in basename_lower:
            display = GAME_DB[game_key]["display"]
            return GameFile(path, game_key, display, fmt, ".pkg")

    # Fall back to magic bytes
    try:
        with open(path, "rb") as f:
            magic = f.read(16)
    except OSError:
        return None

    fmt = detect_pkg_format_from_magic(magic)
    if fmt == "tar_gz":
        return GameFile(path, None, "Unknown Game (.pkg tar.gz)", "tar_gz",
                        ".pkg")
    if fmt == "gpg_symmetric":
        return GameFile(path, None, "Unknown Game (.pkg GPG encrypted)",
                        "gpg_symmetric", ".pkg")
    if fmt == "aes_pkg":
        return GameFile(path, None, "Unknown Game (.pkg AES encrypted)",
                        "aes_pkg", ".pkg")

    return None


def detect_pkg_format_from_magic(magic_bytes):
    """Determine .pkg format from the first 16 bytes."""
    if len(magic_bytes) < 2:
        return None

    # gzip magic
    if magic_bytes[:2] == b"\x1f\x8b":
        return "tar_gz"

    # GPG symmetric: tag 3 (Symmetric-Key Encrypted Session Key)
    if magic_bytes[0] in (0x8c, 0x8d, 0xc3):
        return "gpg_symmetric"

    # AES-CBC .pkg: [8-byte LE uint64 orig_size][16-byte IV]
    if len(magic_bytes) >= 8:
        upper = struct.unpack("<I", magic_bytes[4:8])[0]
        if upper == 0:
            return "aes_pkg"

    return None


def _detect_zip(path, basename):
    basename_lower = basename.lower()

    # Known P3 game update ZIPs
    for pattern, game_key, fmt in ZIP_GAME_PATTERNS:
        if pattern.lower() in basename_lower:
            display = GAME_DB[game_key]["display"]
            return GameFile(path, game_key, display, fmt, ".zip")

    if _is_clonezilla_zip(path):
        return GameFile(path, None, "Restore Image", "clonezilla", ".zip")

    return GameFile(path, None, "Unknown Game (ZIP)", "plain_zip", ".zip")


def _is_clonezilla_zip(path):
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                if "partimag" in name or "ptcl-img" in name:
                    return True
    except (zipfile.BadZipFile, OSError):
        pass
    return False


# ---------------------------------------------------------------------------
# Archive helpers (extract / create)
# ---------------------------------------------------------------------------

def extract_zip(zip_path, output_dir, progress_cb=None):
    """Extract a ZIP archive to *output_dir*."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.namelist()
        total = len(members)
        extracted = []
        for i, member in enumerate(members):
            zf.extract(member, output_dir)
            extracted.append(member)
            if progress_cb:
                progress_cb(i + 1, total, member)
    return extracted


def extract_tar_gz(tar_path, output_dir, progress_cb=None):
    """Extract a tar.gz (or plain tar) archive with path-traversal protection."""
    abs_output = os.path.abspath(output_dir)
    with tarfile.open(tar_path, "r:*") as tf:
        members = tf.getmembers()
        total = len(members)
        extracted = []
        for i, member in enumerate(members):
            member_path = os.path.normpath(
                os.path.join(abs_output, member.name))
            if not member_path.startswith(abs_output):
                continue  # skip suspicious paths
            tf.extract(member, output_dir)
            extracted.append(member.name)
            if progress_cb:
                progress_cb(i + 1, total, member.name)
    return extracted


def create_zip(source_dir, out_path, progress_cb=None):
    """Create a ZIP archive from *source_dir*."""
    all_files = []
    for root, _dirs, files in os.walk(source_dir):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, source_dir)
            all_files.append((full, rel))

    total = len(all_files)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, (full, rel) in enumerate(all_files):
            zf.write(full, rel)
            if progress_cb:
                progress_cb(i + 1, total, rel)


def create_tar_gz(source_dir, out_path, progress_cb=None):
    """Create a tar.gz archive from *source_dir*."""
    all_files, all_dirs = _scan_for_tar(source_dir)
    total = len(all_files) + len(all_dirs)
    _create_tar_impl(out_path, "w:gz", all_files, all_dirs, total, progress_cb)


def create_tar(source_dir, out_path, progress_cb=None):
    """Create a plain (uncompressed) tar archive from *source_dir*."""
    all_files, all_dirs = _scan_for_tar(source_dir)
    total = len(all_files) + len(all_dirs)
    _create_tar_impl(out_path, "w:", all_files, all_dirs, total, progress_cb)


def _scan_for_tar(source_dir):
    all_files = []
    all_dirs = []
    for root, dirs, files in os.walk(source_dir):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, source_dir)
            all_files.append((full, rel))
        for d in dirs:
            full = os.path.join(root, d)
            rel = os.path.relpath(full, source_dir)
            all_dirs.append((full, rel))
    return all_files, all_dirs


def _create_tar_impl(out_path, mode, all_files, all_dirs, total, progress_cb):
    count = 0
    with tarfile.open(out_path, mode) as tf:
        for full, rel in all_dirs:
            tf.add(full, arcname=rel)
            count += 1
            if progress_cb:
                progress_cb(count, total, rel + "/")
        for full, rel in all_files:
            tf.add(full, arcname=rel)
            count += 1
            if progress_cb:
                progress_cb(count, total, rel)
