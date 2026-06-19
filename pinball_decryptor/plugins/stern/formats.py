"""Detection for Stern Spike disk images.

A Spike 2 card is a raw disk image with an MBR partition table: a small
boot/data partition plus one or more Linux (ext) partitions.  The game data
partition contains ``image.bin`` (the packed asset container) and the rootfs
partition contains the ``game_real`` firmware.

Detection is deliberately cheap — it reads only the 512-byte MBR and (when a
filename hint is absent) confirms the Spike partition *shape*.  Confirming the
exact title requires reading inside an ext partition, which the extract
pipeline does; ``detect`` stays lightweight so the picker is responsive.
"""

import os
import struct

from .games import GAME_DB

_MBR_SIG = b"\x55\xaa"
_MBR_LINUX = 0x83          # Linux native (ext2/3/4)
_MBR_FAT = (0x0b, 0x0c, 0x0e, 0x06, 0x04)   # FAT boot partition variants


def _filename_hint(path, key):
    name = os.path.basename(path).lower()
    return any(h in name for h in GAME_DB[key]["filename_hints"])


def parse_mbr_partitions(path):
    """Return ``[(index, type, lba_start, sectors), ...]`` from the MBR.

    Reads only the first 512 bytes; never touches the filesystem.
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


def linux_partitions(path, sector_size=512):
    """Return ``[(byte_offset, byte_size), ...]`` for every ext partition,
    largest first.  Used to locate the rootfs (game_real) and data (image.bin)
    partitions on a Spike card."""
    parts = parse_mbr_partitions(path)
    linux = [p for p in parts if p[1] == _MBR_LINUX]
    linux.sort(key=lambda p: p[3], reverse=True)
    return [(lba * sector_size, sectors * sector_size)
            for (_i, _t, lba, sectors) in linux]


def _looks_like_spike(path):
    """True if *path* has the Spike card partition shape: a FAT/boot partition
    plus at least two Linux (ext) partitions (rootfs + data)."""
    parts = parse_mbr_partitions(path)
    if not parts:
        return False
    n_linux = sum(1 for p in parts if p[1] == _MBR_LINUX)
    has_fat = any(p[1] in _MBR_FAT for p in parts)
    return n_linux >= 2 and has_fat


def detect_game(path):
    """Return a Spike game key (e.g. ``"tmnt"``) or None for *path*.

    A raw ``.img``/``.bin`` whose filename hints at a known title and whose MBR
    matches the Spike shape is claimed.  Without a filename hint we stay
    conservative and decline (so generic Linux images aren't grabbed) — the
    user can still pick Stern manually in the GUI.
    """
    low = path.lower()
    if not (low.endswith(".img") or low.endswith(".bin") or low.endswith(".raw")):
        return None
    if not _looks_like_spike(path):
        return None
    for key in GAME_DB:
        if _filename_hint(path, key):
            return key
    return None
