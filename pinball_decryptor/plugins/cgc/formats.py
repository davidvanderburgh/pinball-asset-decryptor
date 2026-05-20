"""CGC installer `.img` detection.

Detection is filename-based: reading P3 to peek at the package.dat
version string takes ~20 s per probe (3 GB dd) and the picker pings
every plugin on every browse.  CGC's installer images have always
shipped with the convention ``<Game><version>Installer.img`` (e.g.
``MedievalMadness300Installer.img``), so the hints in :mod:`.games`
are reliable.
"""

import os
import struct

from .games import GAME_DB

MBR_MAGIC = b"\x55\xaa"


def is_img_file(path):
    """Loose probe: regular file ending in .img with a valid MBR signature."""
    if not os.path.isfile(path):
        return False
    if not path.lower().endswith(".img"):
        return False
    try:
        with open(path, "rb") as f:
            f.seek(510)
            return f.read(2) == MBR_MAGIC
    except OSError:
        return False


def detect_game(img_path):
    """Return the game key for a CGC installer `.img`, or None."""
    if not is_img_file(img_path):
        return None
    name = os.path.basename(img_path).lower()
    for key, info in GAME_DB.items():
        for hint in info["filename_hints"]:
            if hint in name:
                return key
    return None


# ---------------------------------------------------------------------------
# MBR partition table parsing -- used by the pipeline to locate emmc.img's
# offset inside the installer .img without shelling out to fdisk.
# ---------------------------------------------------------------------------

def read_mbr_partitions(path):
    """Return a list of ``{index, boot, type, start_lba, sectors}`` dicts.

    Walks the 4 primary entries at offset 0x1BE.  Empty entries
    (``type == 0``) are omitted.  No support for extended/logical
    partitions -- CGC images don't use them.
    """
    parts = []
    with open(path, "rb") as f:
        f.seek(0x1BE)
        table = f.read(64)
        f.seek(510)
        if f.read(2) != MBR_MAGIC:
            raise ValueError(f"{path}: not an MBR-partitioned image")
    for i in range(4):
        entry = table[i * 16:(i + 1) * 16]
        boot, _, _, _, ptype, _, _, _, start_lba, sectors = struct.unpack(
            "<BBBBBBBBII", entry)
        if ptype == 0 or sectors == 0:
            continue
        parts.append({
            "index": i + 1,
            "boot": boot == 0x80,
            "type": ptype,
            "start_lba": start_lba,
            "sectors": sectors,
            "start_bytes": start_lba * 512,
            "size_bytes": sectors * 512,
        })
    return parts


def find_data_partition(img_path):
    """Return the data partition (the one containing emmc.img + package.dat).

    CGC's installer convention is: P1=FAT16 boot, P2=installer rootfs,
    P3=data (emmc.img lives here).  Both P2 and P3 are type 0x83 ext4,
    so we can't pick by type alone -- and on MM/AFM/MB the installer
    rootfs is actually *larger* than the data partition, so "largest
    ext4" picks the wrong one.

    The data partition is consistently the highest-LBA Linux partition.
    Use that.
    """
    parts = [p for p in read_mbr_partitions(img_path) if p["type"] == 0x83]
    if not parts:
        raise ValueError(f"{img_path}: no Linux (0x83) partitions")
    return max(parts, key=lambda p: p["start_lba"])


def find_game_partition(emmc_img_path):
    """Return the (only) Linux partition inside an extracted emmc.img.

    emmc.img has 2 partitions: FAT16 boot + ext4 rootfs.  We want the
    ext4 one.
    """
    parts = [p for p in read_mbr_partitions(emmc_img_path) if p["type"] == 0x83]
    if not parts:
        raise ValueError(f"{emmc_img_path}: no Linux (0x83) partition")
    return parts[0]
