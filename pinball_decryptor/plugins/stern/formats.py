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

# Returned by detect_game for any Spike 2 card whose filename doesn't hint at a
# specific title.  The audio engine is fully title-agnostic (every sound's
# params are derived from the card's own firmware), so every Spike 2 card is
# supported — recognition must not depend on the title being in GAME_DB.
SPIKE2_GENERIC_KEY = "spike2"


def _filename_hint(path, key):
    name = os.path.basename(path).lower()
    return any(h in name for h in GAME_DB[key]["filename_hints"])


def display_for_key(key, path):
    """Human title for a detected key: the named-title display when ``key`` is
    in GAME_DB, otherwise a title derived from the card's filename (the generic
    Spike 2 case)."""
    info = GAME_DB.get(key)
    return info["display"] if info else _title_from_filename(path)


def _title_from_filename(path):
    """Readable title from a Stern card filename, e.g.
    ``munsters_le-1_27_0.Release.8G.sdcard.raw`` -> ``Munsters LE (Spike 2)``.
    Stern names cards ``<title>_<edition>-<version>.Release.<size>.sdcard.raw``,
    so drop everything from the first ``.`` (the .Release… tail) and the ``-``
    version, then prettify the remaining title_edition words."""
    stem = os.path.basename(path).split(".", 1)[0].split("-", 1)[0]
    words = [w for w in stem.replace("_", " ").split() if w]
    if not words:
        return "Stern Spike 2 card"
    pretty = " ".join(w.upper() if w.lower() in ("le", "pro", "se")
                      else w.capitalize() for w in words)
    return f"{pretty} (Spike 2)"


def parse_mbr_partitions_bytes(mbr):
    """Parse the four primary MBR entries from the first 512 bytes of a disk.

    Returns ``[(index, type, lba_start, sectors), ...]``.  Pure (no I/O), so it
    serves both a file path and a raw device (which is read sector-aligned via
    :class:`.rawdevice.RawDeviceFile` before being handed here)."""
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


def parse_mbr_partitions(path):
    """Return ``[(index, type, lba_start, sectors), ...]`` from the MBR.

    Reads only the first 512 bytes; never touches the filesystem.
    """
    try:
        with open(path, "rb") as f:
            mbr = f.read(512)
    except OSError:
        return []
    return parse_mbr_partitions_bytes(mbr)


def linux_partitions_from_parts(parts, sector_size=512):
    """``[(byte_offset, byte_size), ...]`` for every ext partition in *parts*
    (the output of :func:`parse_mbr_partitions*`), largest first."""
    linux = [p for p in parts if p[1] == _MBR_LINUX]
    linux.sort(key=lambda p: p[3], reverse=True)
    return [(lba * sector_size, sectors * sector_size)
            for (_i, _t, lba, sectors) in linux]


def linux_partitions(path, sector_size=512):
    """Return ``[(byte_offset, byte_size), ...]`` for every ext partition,
    largest first.  Used to locate the rootfs (game_real) and data (image.bin)
    partitions on a Spike card."""
    return linux_partitions_from_parts(parse_mbr_partitions(path), sector_size)


def is_spike_card_parts(parts):
    """True if *parts* carry the Stern Spike 2 firmware partition signature:
    an 8 MB FAT boot partition (type 0x0c) at LBA 8192, immediately followed by
    a Linux (ext) partition at LBA 24576.  This boot/first-ext layout is fixed
    by the firmware across every title, edition and card size (only the data and
    extended partitions grow), so it identifies a Spike 2 card without needing a
    per-title filename hint, while staying specific enough not to grab generic
    Linux SBC images (which don't place a fixed 8 MB FAT boot at exactly LBA
    8192 followed by an ext partition at 24576)."""
    if len(parts) < 2:
        return False
    p0, p1 = parts[0], parts[1]
    return (p0[1] in _MBR_FAT and p0[2] == 8192 and p0[3] == 16384
            and p1[1] == _MBR_LINUX and p1[2] == 24576)


def _is_spike_card(path):
    """:func:`is_spike_card_parts` over a file path's MBR."""
    return is_spike_card_parts(parse_mbr_partitions(path))


def detect_game(path):
    """Return a Spike game key for *path*, or None.

    Any raw ``.img``/``.bin``/``.raw`` with the Spike 2 partition signature
    (:func:`_is_spike_card`) is claimed: a known title's key when the filename
    hints at one, otherwise :data:`SPIKE2_GENERIC_KEY` (the engine decodes every
    Spike 2 title generically, so the card needn't be in GAME_DB).  Non-Spike
    images are declined so other manufacturers' cards aren't grabbed.
    """
    low = path.lower()
    if not (low.endswith(".img") or low.endswith(".bin") or low.endswith(".raw")):
        return None
    if not _is_spike_card(path):
        return None
    for key in GAME_DB:
        if _filename_hint(path, key):
            return key
    return SPIKE2_GENERIC_KEY
