"""Detection for Dutch Pinball inputs (TBL ``.zip`` and AAIW ``.img``)."""

import os
import struct
import zipfile

from .games import GAME_DB

# MBR partition type for Linux (the ext4 game/installer partition).
_MBR_LINUX = 0x83
_MBR_SIG = b"\x55\xaa"


def _filename_hint(path, key):
    name = os.path.basename(path).lower()
    return any(h in name for h in GAME_DB[key]["filename_hints"])


# ---------------------------------------------------------------------------
# The Big Lebowski — plain .zip update
# ---------------------------------------------------------------------------

def is_tbl_zip(path):
    """True if *path* looks like a TBL software-update zip.

    Identified by its internal layout: a single ``<version>/`` top folder
    containing ``assets/`` with ``.cdmd`` files (and/or a ``delta`` marker).
    """
    if not zipfile.is_zipfile(path):
        return False
    try:
        with zipfile.ZipFile(path) as zf:
            has_cdmd = False
            has_assets = False
            for i, name in enumerate(zf.namelist()):
                if i > 4000:
                    break
                low = name.lower()
                if low.endswith(".cdmd"):
                    has_cdmd = True
                if "/assets/" in low or low.startswith("assets/"):
                    has_assets = True
                if low.rstrip("/").endswith("/delta"):
                    return True
                if has_cdmd and has_assets:
                    return True
            return has_cdmd
    except (zipfile.BadZipFile, OSError):
        return False


def top_version(names):
    """Return the leading ``<version>/`` folder shared by zip entries.

    TBL updates wrap everything under a single version folder (e.g.
    ``1.01/...``).  Returns that folder name (``"1.01"``) or None.
    """
    top = None
    for name in names:
        norm = name.replace("\\", "/").lstrip("/")
        head = norm.split("/", 1)[0]
        if not head:
            continue
        if top is None:
            top = head
        elif head != top:
            return None  # not a single-version layout
    return top


def version_key(version):
    """Sort key for a dotted version string (``"1.10"`` -> ``(1, 10)``)."""
    parts = []
    for chunk in str(version).split("."):
        parts.append(int(chunk) if chunk.isdigit() else 0)
    return tuple(parts)


def bump_version(version):
    """Increment the last numeric segment, preserving its width.

    ``"1.15"`` -> ``"1.16"``; ``"1.09"`` -> ``"1.10"``.  Used to label a
    built update one step newer than the merged version so the machine's
    USB-update gate accepts it (it only applies a *newer* version).
    """
    parts = str(version).split(".")
    if not parts or not parts[-1].isdigit():
        return f"{version}.1"
    last = parts[-1]
    parts[-1] = str(int(last) + 1).zfill(len(last))
    return ".".join(parts)


def delta_info(zip_path):
    """Inspect a TBL update zip.

    Returns ``(version, compatible_bases)`` where *version* is the update's
    own version folder and *compatible_bases* is the list of base versions a
    **delta** can be applied to (from its ``<version>/delta`` marker), or
    None for a **full** image (no delta marker).
    """
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        version = top_version(names)
        compat = None
        if version is not None:
            marker = f"{version}/delta"
            if marker in names:
                raw = zf.read(marker).decode("utf-8", "replace")
                compat = [c.strip() for c in raw.replace("\n", ",").split(",")
                          if c.strip()]
        return version, compat


# ---------------------------------------------------------------------------
# Alice's Adventures in Wonderland — Clonezilla auto-installer .img
# ---------------------------------------------------------------------------

def parse_mbr_partitions(path):
    """Return a list of ``(index, type, lba_start, sectors)`` from the MBR.

    Reads only the 512-byte MBR; does not touch the filesystem.
    """
    try:
        with open(path, "rb") as f:
            mbr = f.read(512)
    except OSError:
        return []
    if len(mbr) < 512 or mbr[510:512] != _MBR_SIG:
        return []
    parts = []
    for i in range(4):
        entry = mbr[446 + i * 16: 446 + i * 16 + 16]
        ptype = entry[4]
        lba_start, sectors = struct.unpack_from("<II", entry, 8)
        if ptype != 0 and sectors > 0:
            parts.append((i, ptype, lba_start, sectors))
    return parts


def find_ext_partition(path, sector_size=512):
    """Return ``(byte_offset, byte_size)`` of the Linux/ext partition, or None.

    Picks the largest Linux (0x83) partition; falls back to the largest
    partition of any type when no 0x83 entry is present.
    """
    parts = parse_mbr_partitions(path)
    if not parts:
        return None
    linux = [p for p in parts if p[1] == _MBR_LINUX]
    pool = linux or parts
    pool.sort(key=lambda p: p[3], reverse=True)
    _idx, _type, lba, sectors = pool[0]
    return lba * sector_size, sectors * sector_size


def is_aaiw_img(path):
    """True if *path* looks like an AAIW Clonezilla installer image.

    Cheap heuristic that avoids mounting: it must be an ``.img`` with a
    valid MBR carrying a Linux partition, and either the filename hints at
    AAIW or the partition layout matches the installer (a small boot
    partition plus a large Linux partition).
    """
    if not path.lower().endswith(".img"):
        return False
    parts = parse_mbr_partitions(path)
    if not parts:
        return False
    has_linux = any(p[1] == _MBR_LINUX for p in parts)
    if not has_linux:
        return False
    if _filename_hint(path, "aaiw"):
        return True
    # Installer shape: exactly two partitions, a smallish first and a large
    # Linux second (the /home/partimag carrier).
    if len(parts) == 2 and parts[1][1] == _MBR_LINUX:
        return True
    return False


# ---------------------------------------------------------------------------
# Unified detection
# ---------------------------------------------------------------------------

def detect_game(path):
    """Return ``"tbl"``, ``"aaiw"``, or None for *path*."""
    low = path.lower()
    if low.endswith(".zip") and is_tbl_zip(path):
        return "tbl"
    if low.endswith(".img") and is_aaiw_img(path):
        return "aaiw"
    return None
