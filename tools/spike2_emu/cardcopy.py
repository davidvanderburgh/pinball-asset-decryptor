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
partition's own bitmaps (its metadata, read straight off the image in a few
hundred small reads) say which blocks are in use, and only those are read: in long runs, a free gap
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
import struct
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


#: a bitmap byte as 8 bytes of b"0" (free) / b"1" (used), lowest block first
_BITS = [bytes(b"01"[(x >> i) & 1] for i in range(8)) for x in range(256)]


def _super_groups(sb, ngroups):
    """The groups that carry a superblock backup and its group descriptors."""
    compat, ro_compat = struct.unpack_from("<I", sb, 0x5C)[0], struct.unpack_from("<I", sb, 0x64)[0]
    if compat & 0x200:                          # sparse_super2: group 0 and the two it names
        return {0} | set(g for g in struct.unpack_from("<2I", sb, 0x24C) if g)
    if not ro_compat & 0x1:                     # no sparse_super: every group
        return set(range(ngroups))
    out = {0, 1}
    for p in (3, 5, 7):
        x = p
        while x < ngroups:
            out.add(x)
            x *= p
    return out


def used_runs(img, off, size):
    """[(start, end)] image byte ranges the ext filesystem at `off` uses, or None (copy it whole).

    Read straight off the image - superblock, group descriptors, block bitmaps - NOT through
    dumpe2fs: since e2fsprogs 1.47.1 dumpe2fs hands its device argument to blkid first, which
    reads `card.raw?offset=N` as a NAME=value tag and gives up ("Unable to resolve"), so on
    Ubuntu 26.04 every card was copied whole (PAD-817)."""
    u16 = lambda b, o: struct.unpack_from("<H", b, o)[0]
    u32 = lambda b, o: struct.unpack_from("<I", b, o)[0]
    with open(img, "rb") as f:
        f.seek(off + 1024)
        sb = f.read(1024)
        if len(sb) != 1024 or sb[56:58] != EXT_MAGIC:
            return None
        incompat, ro_compat = u32(sb, 0x60), u32(sb, 0x64)
        if incompat & 0x10:
            return None                         # meta_bg: descriptors scattered, not read here
        wide = bool(incompat & 0x80)            # 64bit
        bs = 1024 << u32(sb, 0x18)
        count = u32(sb, 0x04) | (u32(sb, 0x150) << 32 if wide else 0)
        first, bpg, ipg = u32(sb, 0x14), u32(sb, 0x20), u32(sb, 0x28)
        isize = u16(sb, 0x58) if u32(sb, 0x4C) else 128
        dsize = max(u16(sb, 0xFE), 64) if wide else 32
        if not bpg or count <= first or count * bs > size:
            return None                         # bigger than its partition: not one to trim
        ngroups = (count - first + bpg - 1) // bpg
        gdt = (ngroups * dsize + bs - 1) // bs
        itable = (ipg * isize + bs - 1) // bs
        csum = bool(ro_compat & 0x410)          # gdt_csum / metadata_csum: BLOCK_UNINIT is meaningful
        f.seek(off + (first + 1) * bs)
        desc = f.read(ngroups * dsize)
        if len(desc) != ngroups * dsize:
            return None
        supers = _super_groups(sb, ngroups)
        groups, said, meta, want = [], [], [], []
        for g in range(ngroups):
            d = desc[g * dsize:(g + 1) * dsize]
            hi = lambda o: u32(d, o) << 32 if dsize >= 64 else 0
            bb, ib, it = u32(d, 0) | hi(0x20), u32(d, 4) | hi(0x24), u32(d, 8) | hi(0x28)
            said.append(u16(d, 0x0C) | (u16(d, 0x2C) << 16 if dsize >= 64 else 0))
            meta += [(bb, bb + 1), (ib, ib + 1), (it, it + itable)]
            n = min(bpg, count - first - g * bpg)
            if csum and u16(d, 0x12) & 0x2:     # BLOCK_UNINIT: free but for its own backup
                m = bytearray(b"0" * n)
                if g in supers:
                    k = min(n, 1 + gdt + u16(sb, 0xCE))
                    m[:k] = b"1" * k
                groups.append(m)
            else:
                if not first <= bb < count:
                    return None
                groups.append(None)
                want.append((bb, g, n))
        # the bitmaps of a flex group sit side by side: one read for each run of them
        want.sort()
        i = 0
        while i < len(want):
            j = i + 1
            while j < len(want) and want[j][0] == want[j - 1][0] + 1:
                j += 1
            f.seek(off + want[i][0] * bs)
            buf = f.read((j - i) * bs)
            if len(buf) != (j - i) * bs:
                return None
            for k in range(i, j):
                _, g, n = want[k]
                bm = buf[(k - i) * bs:(k - i) * bs + (n + 7) // 8]
                groups[g] = bytearray(b"".join(_BITS[x] for x in bm)[:n])
            i = j
    for a, b in meta:                           # every group's bitmaps and inode table are in use
        if not first <= a < b <= count:
            return None
        while a < b:
            g, at = divmod(a - first, bpg)
            k = min(b - a, bpg - at)
            groups[g][at:at + k] = b"1" * k
            a += k
    free = []
    for g, m in enumerate(groups):
        if m.count(b"0") != said[g]:
            return None                         # the bitmaps and the counts disagree
        start = first + g * bpg
        free += [(start + r.start(), start + r.end()) for r in re.finditer(b"0+", m)]
    used, at = [], 0
    for a, b in free:
        if a > at:
            used.append((at, a))
        at = b
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
