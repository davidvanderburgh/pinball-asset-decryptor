#!/usr/bin/env python3
"""cardcopy.py <card.raw> <copy> - copy a card image, reading only what its filesystems use.

    cardcopy.py card.raw copy.raw        the copy, sparse; exit 0 when it is whole
    cardcopy.py --plan card.raw          what would be read, and nothing written

PAD-484. The card cache (cardmount.sh) copied every byte of an image with
`dd conv=sparse`: the zeros land as holes, but every one of them is still
READ - through 9p, off a spinning D: at 75-90 MB/s, 1m45s for an 8 GB card.
With the game sped up a sweep's job is about a minute, so the copies became the
floor of a library sweep. And a Spike 2 card is half empty: Deadpool LE 1.16's
7.9 GB image holds 3.4 GB of data, 3.2 of it in the 6.9 GB game partition.

So the partition table (sfdisk) says where each partition is, each ext
partition's own bitmaps (dumpe2fs - its metadata, a few hundred small reads)
say which blocks are in use, and only those are read: in long runs, a free gap
shorter than GAP read through rather than seeked over (a seek on the spinning
disk costs more than 4 MB of reading). Everything outside the ext partitions -
the partition table, the FAT boot partition, the extended partition's link
sectors, the gaps between - is copied whole. A free block reads back as zeros
rather than whatever it last held; nothing mounts a free block.

NOT e2image -ra, which reads one block per call: over 9p that is exactly the
latency the cache exists to avoid. A partition whose bitmaps do not add up to
its group descriptors' free counts is copied whole, and anything else that
goes wrong exits non-zero: cardmount.sh then copies the old way.
"""
import json
import os
import re
import subprocess
import sys

#: one read; and the size of an all-zero chunk left as a hole
CHUNK = 4 << 20
#: a free run shorter than this is read through, not seeked over
GAP = 4 << 20
#: the ext2/3/4 superblock magic, 1080 bytes into the filesystem
EXT_MAGIC = b"\x53\xef"


def partitions(img):
    """[(offset, size)] in bytes, every partition sfdisk lists (an extended one included)."""
    out = subprocess.run(["sfdisk", "-J", img], capture_output=True, text=True, check=True).stdout
    pt = json.loads(out)["partitiontable"]
    ss = int(pt.get("sectorsize", 512))
    return [(int(p["start"]) * ss, int(p["size"]) * ss) for p in pt["partitions"]]


def is_ext(f, off):
    f.seek(off + 1080)
    return f.read(2) == EXT_MAGIC


def used_runs(img, off, size):
    """[(start, end)] image byte ranges the ext filesystem at `off` uses, or None (copy it whole)."""
    r = subprocess.run(["dumpe2fs", "%s?offset=%d" % (img, off)], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    head = {}
    for key in ("Block size", "Block count", "First block"):
        m = re.search(r"^%s:\s+(\d+)$" % key, r.stdout, re.M)
        if not m:
            return None
        head[key] = int(m.group(1))
    bs, count = head["Block size"], head["Block count"]
    if count * bs > size:
        return None                            # bigger than its partition: not one to trim
    free, said = [], 0
    for m in re.finditer(r"^\s+(\d+) free blocks,", r.stdout, re.M):
        said += int(m.group(1))
    for m in re.finditer(r"^\s+Free blocks: (.*)$", r.stdout, re.M):
        for part in m.group(1).split(","):
            part = part.strip()
            if part:
                a, _, b = part.partition("-")
                free.append((int(a), int(b or a) + 1))
    if not free or sum(b - a for a, b in free) != said:
        return None                            # the bitmaps and the counts disagree
    used, at = [], 0
    for a, b in sorted(free):
        if a > at:
            used.append((at, a))
        at = max(at, b)
    if at < count:
        used.append((at, count))
    return [(off + a * bs, off + b * bs) for a, b in used]


def merge(runs, gap):
    out = []
    for a, b in sorted(runs):
        if out and a - out[-1][1] < gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def plan(img):
    """(runs, size, notes): the byte ranges to read, the image size, one line per partition."""
    size = os.path.getsize(img)
    runs, trimmed, notes = [], [], []
    with open(img, "rb") as f:
        for off, psize in partitions(img):
            if off >= size or not is_ext(f, off):
                continue
            u = used_runs(img, off, psize)
            if u is None:
                notes.append("ext at %d: copied whole (its bitmaps could not be read or do not add up)" % off)
                continue
            trimmed.append((off, off + psize))
            runs += u
            notes.append("ext at %d: %.2f of %.2f GB in use" % (off, sum(b - a for a, b in u) / 1e9, psize / 1e9))
    at = 0
    for a, b in sorted(trimmed):
        if a > at:
            runs.append((at, a))
        at = max(at, b)
    if at < size:
        runs.append((at, size))
    runs = [(a, min(b, size)) for a, b in merge(runs, GAP) if a < size]
    return runs, size, notes


def copy(img, out, runs, size):
    """Read `runs` of `img` into `out` at the same offsets, in order, so the copy's size tracks
    the position (cardmount.sh's progress line reads it); an all-zero chunk stays a hole."""
    zero = bytes(CHUNK)
    with open(img, "rb", buffering=0) as src, open(out, "wb") as dst:
        for a, b in runs:
            src.seek(a)
            pos = a
            while pos < b:
                n = min(CHUNK, b - pos)
                buf = src.read(n)
                if len(buf) != n:
                    raise OSError("short read at %d of %s" % (pos, img))
                if buf != zero[:n]:
                    dst.seek(pos)
                    dst.write(buf)
                pos += n
        dst.truncate(size)


def main(argv):
    if len(argv) == 2 and argv[0] == "--plan":
        runs, size, notes = plan(argv[1])
        for line in notes:
            print(line)
        print("read %.2f of %.2f GB in %d runs" % (sum(b - a for a, b in runs) / 1e9, size / 1e9, len(runs)))
        return 0
    if len(argv) != 2:
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    img, out = argv
    try:
        runs, size, notes = plan(img)
        copy(img, out, runs, size)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
        print("cardcopy: %s" % e, file=sys.stderr)
        return 1
    if os.path.getsize(out) != size:
        print("cardcopy: the copy is %d bytes, the image %d" % (os.path.getsize(out), size), file=sys.stderr)
        return 1
    for line in notes:
        print("[card] %s" % line)
    print("[card] read %.2f of %.2f GB" % (sum(b - a for a, b in runs) / 1e9, size / 1e9))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
