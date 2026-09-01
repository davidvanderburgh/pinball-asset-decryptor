#!/usr/bin/env python3
"""parts.py <card.raw> - the card's partition table, and which partition is what.

    parts.py card.raw                 # the table, with each partition identified
    parts.py --rootfs card.raw        # byte offset of the OS partition
    parts.py --games  card.raw        # byte offset of the (first) games partition
    parts.py --fat    card.raw        # "<start_lba> <sectors>" of the boot partition
    parts.py --list-games card.raw    # every games partition: "idx lba offset title"
    parts.py --part N card.raw        # byte offset of partition N (primary or logical)
    parts.py --rootfs-file /etc/x card.raw   # a file out of the rootfs, via debugfs

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

THE EXTENDED PARTITION IS WALKED TOO (item 90). A stock card's p4 is an
extended container holding p5 (/data) and p6 (/dump) as logicals, and a
multi-image card (mkmulticard.py) appends each extra image's games partition
after them as p7, p8... - the only place a fixed 4-primary MBR has room. The
kernel numbers logicals 5, 6, 7... in chain order, so that is the numbering
used here: `--part 7` is what `/dev/mmcblk0p7` is on the machine.

THE STRICT GAMES RULE FOR THAT LIST, and why the identify() rule cannot be
reused for it: identify() calls a Linux partition "games" when it has /spk OR
when it has none of /lib /usr /etc - and p5 and p6 on a stock card are EMPTY
ext4 (only lost+found), so once logicals are walked that negative branch
would offer /data and /dump as boot choices. `--list-games` requires /spk AND
a title directory holding a `game` file, which is what a games partition
actually is.
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
#: An extended container (the stock p4 is 0x0f) and the EBR chain's link type.
EXT_TYPES = {0x05, 0x0F}
#: The most logicals a chain is followed for. A corrupt link that loops would
#: otherwise walk forever; a real card has two (stock) or a handful (multi).
MAX_LOGICALS = 32


def _entry(sector, i):
    """(type, start, count) of table entry `i` (0..3) in a 512-byte sector."""
    e = sector[0x1BE + i * 16: 0x1BE + i * 16 + 16]
    ptype = e[4]
    start, count = struct.unpack_from("<II", e, 8)
    return ptype, start, count


def table(path):
    """[(index, type, start_lba, sectors)] from the MBR, empty entries dropped."""
    with open(path, "rb") as f:
        mbr = f.read(512)
    if len(mbr) < 512 or mbr[510:512] != b"\x55\xaa":
        raise SystemExit("%s: no MBR signature - not a card image?" % path)
    out = []
    for i in range(4):
        ptype, start, count = _entry(mbr, i)
        if ptype and count:
            out.append((i + 1, ptype, start, count))
    return out


def logical(path):
    """[(index, type, start_lba, sectors, ebr_lba)] - the EBR chain of the
    first extended primary, numbered 5, 6, 7... the way the kernel numbers them.
    Empty when the card has no extended partition.

    THE TWO KINDS OF LBA IN AN EBR, verified against the stock card: entry 0
    (this logical) is relative to the EBR's OWN sector - the stock EBR at
    14114816 says +2048 and p5 is at 14116864; entry 1 (the link) is relative
    to the EXTENDED PARTITION'S start - the same EBR links +149502 and the
    next EBR is at 14264318. Getting either one wrong lands on zeros and
    silently ends the chain one partition early.
    """
    ext = [(start, count) for _i, ptype, start, count in table(path)
           if ptype in EXT_TYPES]
    if not ext:
        return []
    ext_base = ext[0][0]
    out, seen, cur = [], set(), ext_base
    with open(path, "rb") as f:
        while cur not in seen and len(out) < MAX_LOGICALS:
            seen.add(cur)
            f.seek(cur * SECTOR)
            ebr = f.read(512)
            if len(ebr) < 512 or ebr[510:512] != b"\x55\xaa":
                break
            ptype, start, count = _entry(ebr, 0)
            if not ptype or not count:
                break
            out.append((5 + len(out), ptype, cur + start, count, cur))
            ltype, lstart, lcount = _entry(ebr, 1)
            if ltype not in EXT_TYPES or not lcount:
                break
            cur = ext_base + lstart
    return out


def _entries(path, offset, sub="/"):
    """[(name, mode)] at directory `sub` of the ext4 filesystem at `offset`,
    or None when debugfs is missing or cannot read it.

    ONE place shells out to debugfs for a listing, so a test can stand in for
    the whole filesystem by replacing this function alone.
    """
    try:
        r = subprocess.run(["debugfs", "-R", "ls -p %s" % sub,
                            "%s?offset=%d" % (path, offset)],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    out = []
    for line in r.stdout.decode("latin-1").splitlines():
        # /inode/mode(octal)/uid/gid/name/size/
        bits = line.split("/")
        if len(bits) >= 6 and bits[5]:
            try:
                mode = int(bits[2], 8)
            except ValueError:
                mode = 0
            out.append((bits[5], mode))
    return out or None


def _ls(path, offset, sub="/"):
    """Names in directory `sub` of the ext4 filesystem at `offset`, or None."""
    ents = _entries(path, offset, sub)
    if ents is None:
        return None
    return {n for n, _m in ents if n not in (".", "..")} or None


def _dirs(path, offset, sub="/"):
    """Names of the real DIRECTORIES (not symlinks - the games root carries
    game/conagent/data links into the title directory) in `sub`, or None."""
    ents = _entries(path, offset, sub)
    if ents is None:
        return None
    return [n for n, m in ents
            if n not in (".", "..") and (m & 0o170000) == 0o040000]


def _title_dirs(path, offset):
    """Title directories - subdirectories holding a `game` file - of the
    filesystem at `offset`, in name order. Empty for anything else."""
    names = _ls(path, offset)
    if not names or "spk" not in names:
        return []
    out = []
    for d in sorted(_dirs(path, offset) or []):
        if d in ("lost+found", "spk"):
            continue
        inside = _ls(path, offset, "/" + d)
        if inside and "game" in inside:
            out.append(d)
    return out


def games_all(path):
    """[(index, start_lba, offset, [title, ...])] for EVERY games partition,
    primaries and logicals, in partition order - the strict rule from the
    header: /spk AND a title directory holding `game`."""
    parts = [(idx, ptype, start) for idx, ptype, start, _c in table(path)]
    parts += [(idx, ptype, start) for idx, ptype, start, _c, _e in logical(path)]
    out = []
    for idx, ptype, start in parts:
        if ptype not in LINUX_TYPES:
            continue
        titles = _title_dirs(path, start * SECTOR)
        if titles:
            out.append((idx, start, start * SECTOR, titles))
    return out


def part_offset(path, n):
    """Byte offset of partition `n` (kernel numbering, primary or logical),
    or None when the card has no such partition."""
    for idx, _t, start, _c in table(path):
        if idx == n:
            return start * SECTOR
    for idx, _t, start, _c, _e in logical(path):
        if idx == n:
            return start * SECTOR
    return None


def rootfs_file(path, name):
    """The content of file `name` in the rootfs partition, or None.

    `debugfs -R cat` exits 0 for a missing file too (the complaint goes to
    stderr), so an EMPTY answer is the only reliable "not there" - and a
    genuinely empty file reads as absent, which is the right answer for every
    caller here (an empty images.conf names no image)."""
    found = identify(path)
    if "rootfs" not in found:
        return None
    try:
        r = subprocess.run(["debugfs", "-R", "cat %s" % name,
                            "%s?offset=%d" % (path, found["rootfs"])],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or not r.stdout:
        return None
    return r.stdout.decode("utf-8", "replace")


def identify(path):
    """{'rootfs': offset, 'games': offset, 'fat': (lba, sectors)}.

    Structural where it can be (see the header), positional where debugfs is
    not installed - and the caller is told which, because the two deserve
    different amounts of trust. Primaries only, deliberately: this is the
    rootfs/first-games answer every existing card script relies on, and the
    logical chain is games_all()'s business.
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


def _ordinal(n):
    if 10 <= n % 100 <= 20:
        return "%dth" % n
    return "%d%s" % (n, {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image")
    for flag in ("rootfs", "games", "fat", "list-games"):
        ap.add_argument("--" + flag, action="store_true")
    ap.add_argument("--part", type=int, metavar="N",
                    help="byte offset of partition N (kernel numbering)")
    ap.add_argument("--rootfs-file", metavar="PATH",
                    help="print a file out of the rootfs partition")
    a = ap.parse_args()
    if not os.path.exists(a.image):
        raise SystemExit("no such image: %s" % a.image)

    # The two answers that need no identification at all come first: they are
    # pure table reads, and a card with no debugfs must still answer them.
    if a.part is not None:
        off = part_offset(a.image, a.part)
        if off is None:
            print("parts.py: no partition %d in %s" % (a.part, a.image),
                  file=sys.stderr)
            return 1
        print(off)
        return 0
    if a.list_games:
        games = games_all(a.image)
        if not games:
            return 1
        for idx, lba, off, titles in games:
            print("%d %d %d %s" % (idx, lba, off, ",".join(titles)))
        return 0
    if a.rootfs_file:
        text = rootfs_file(a.image, a.rootfs_file)
        if text is None:
            return 1
        sys.stdout.write(text)
        return 0

    found = identify(a.image)
    if a.rootfs or a.games:
        key = "rootfs" if a.rootfs else "games"
        if key not in found:
            return 1
        if found.get(key + "_guessed"):
            print("parts.py: %s identified by PARTITION ORDER, not contents "
                  "(debugfs unavailable)" % key, file=sys.stderr)
        if key == "games":
            # A multi-image card: say so, once, on the channel nobody parses.
            # --games stays "the first games partition" so every card script
            # that mounts p3 keeps mounting p3.
            games = games_all(a.image)
            if len(games) > 1:
                print("parts.py: %d games partitions; --games is the first (p%d); "
                      "see --list-games" % (len(games), games[0][0]),
                      file=sys.stderr)
        print(found[key])
        return 0
    if a.fat:
        if "fat" not in found:
            return 1
        print("%d %d" % found["fat"])
        return 0

    games = {idx: n for n, (idx, _l, _o, _t) in enumerate(games_all(a.image), 1)}
    rows = [(idx, ptype, start, count, None)
            for idx, ptype, start, count in table(a.image)]
    rows += [(idx, ptype, start, count, ebr)
             for idx, ptype, start, count, ebr in logical(a.image)]
    print("%-4s %-6s %-12s %-12s %s" % ("part", "type", "start LBA", "sectors", "is"))
    for idx, ptype, start, count, ebr in rows:
        what = ""
        if ptype in EXT_TYPES:
            what = "extended (holds the logicals below)"
        elif found.get("fat") and found["fat"][0] == start:
            what = "boot (FAT)"
        elif found.get("rootfs") == start * SECTOR:
            what = "rootfs" + (" (by order)" if found.get("rootfs_guessed") else "")
        elif found.get("games") == start * SECTOR:
            what = "games" + (" (by order)" if found.get("games_guessed") else "")
        elif idx in games:
            what = "games (%s)" % _ordinal(games[idx])
        if ebr is not None:
            what = ("%s  [logical, EBR at %d]" % (what, ebr)).strip()
        print("%-4d 0x%02x   %-12d %-12d %s  offset=%d"
              % (idx, ptype, start, count, what, start * SECTOR))
    return 0


if __name__ == "__main__":
    sys.exit(main())
