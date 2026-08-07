#!/usr/bin/env python3
"""parts.py <card.raw> - the card's partition table, and which partition is what.

    parts.py card.raw            # the table, with each partition identified
    parts.py --rootfs card.raw   # byte offset of the OS partition
    parts.py --games  card.raw   # byte offset of the games partition
    parts.py --fat    card.raw   # "<start_lba> <sectors>" of the boot partition

WHY THIS EXISTS. Every script here that reached into a card image carried the
offsets of ONE card as constants - `?offset=12582912` for the rootfs,
`?offset=364904448` for games, `skip=8192` for boot. Those are Godzilla Pro
1.15.0 on an 8 GB card and they say nothing about a 16 GB Jaws image. The MBR
has carried the real numbers all along.

**THE PARTITION NUMBER IS NOT THE ANSWER EITHER, which is the part worth being
careful about.** "p2 is the rootfs and p3 is games" held on the cards this rig
has seen, and a Spike 2 card can carry an A/B pair of system partitions - two
ext4 filesystems that both look like an OS. So the identification below is
STRUCTURAL: a rootfs has `/lib` and `/usr` and no `/spk`, a games partition has
`/spk` and title directories and no `/lib`. That is read out of each candidate
with `debugfs -R ls`, which needs no root and no mount.

Falls back to partition order only when debugfs is missing, and SAYS SO, because
a silently-guessed offset is how an extraction ends up half from the wrong
filesystem.
"""
import argparse
import os
import struct
import subprocess
import sys

SECTOR = 512

#: MBR partition types seen on Spike 2 cards. 0x0c is the boot partition (FAT,
#: despite holding FAT12 rather than the FAT32 the type nominally means).
FAT_TYPES = {0x01, 0x04, 0x06, 0x0B, 0x0C, 0x0E}
LINUX_TYPES = {0x83}


def table(path):
    """[(index, type, start_lba, sectors)] from the MBR, empty entries dropped."""
    with open(path, "rb") as f:
        mbr = f.read(512)
    if len(mbr) < 512 or mbr[510:512] != b"\x55\xaa":
        raise SystemExit("%s: no MBR signature - not a card image?" % path)
    out = []
    for i in range(4):
        e = mbr[0x1BE + i * 16: 0x1BE + i * 16 + 16]
        ptype = e[4]
        start, count = struct.unpack_from("<II", e, 8)
        if ptype and count:
            out.append((i + 1, ptype, start, count))
    return out


def _ls(path, offset):
    """Top-level names in the ext4 filesystem at `offset`, or None."""
    try:
        r = subprocess.run(["debugfs", "-R", "ls -p /",
                            "%s?offset=%d" % (path, offset)],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    names = set()
    for line in r.stdout.decode("latin-1").splitlines():
        bits = line.split("/")
        if len(bits) >= 6 and bits[5]:
            names.add(bits[5])
    return names or None


def identify(path):
    """{'rootfs': offset, 'games': offset, 'fat': (lba, sectors)}.

    Structural where it can be (see the header), positional where debugfs is
    not installed - and the caller is told which, because the two deserve
    different amounts of trust.
    """
    parts, out, guessed = table(path), {}, False
    for idx, ptype, start, count in parts:
        if ptype in FAT_TYPES and "fat" not in out:
            out["fat"] = (start, count)

    linux = [(idx, start) for idx, ptype, start, _c in parts
             if ptype in LINUX_TYPES]
    for idx, start in linux:
        names = _ls(path, start * SECTOR)
        if names is None:
            guessed = True
            continue
        # A rootfs is an OS: it has the directories a chroot needs. A games
        # partition has the package tree and the title directories instead.
        if {"lib", "usr"} <= names and "spk" not in names:
            out.setdefault("rootfs", start * SECTOR)
        elif "spk" in names or not ({"lib", "usr", "etc"} & names):
            out.setdefault("games", start * SECTOR)

    if guessed or ("rootfs" not in out and linux):
        # Order is the fallback and nothing more: p2 rootfs, p3 games is what
        # every card this rig has opened looks like.
        if "rootfs" not in out and len(linux) >= 1:
            out["rootfs"] = linux[0][1] * SECTOR
            out["rootfs_guessed"] = True
        if "games" not in out and len(linux) >= 2:
            out["games"] = linux[1][1] * SECTOR
            out["games_guessed"] = True
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image")
    for flag in ("rootfs", "games", "fat"):
        ap.add_argument("--" + flag, action="store_true")
    a = ap.parse_args()
    if not os.path.exists(a.image):
        raise SystemExit("no such image: %s" % a.image)
    found = identify(a.image)

    if a.rootfs or a.games:
        key = "rootfs" if a.rootfs else "games"
        if key not in found:
            return 1
        if found.get(key + "_guessed"):
            print("parts.py: %s identified by PARTITION ORDER, not contents "
                  "(debugfs unavailable)" % key, file=sys.stderr)
        print(found[key])
        return 0
    if a.fat:
        if "fat" not in found:
            return 1
        print("%d %d" % found["fat"])
        return 0

    print("%-4s %-6s %-12s %-12s %s" % ("part", "type", "start LBA", "sectors", "is"))
    for idx, ptype, start, count in table(a.image):
        what = ""
        if found.get("fat") and found["fat"][0] == start:
            what = "boot (FAT)"
        elif found.get("rootfs") == start * SECTOR:
            what = "rootfs" + (" (by order)" if found.get("rootfs_guessed") else "")
        elif found.get("games") == start * SECTOR:
            what = "games" + (" (by order)" if found.get("games_guessed") else "")
        print("%-4d 0x%02x   %-12d %-12d %s  offset=%d"
              % (idx, ptype, start, count, what, start * SECTOR))
    return 0


if __name__ == "__main__":
    sys.exit(main())
