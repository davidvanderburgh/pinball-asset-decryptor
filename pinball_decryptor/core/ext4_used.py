"""Which bytes of an ext2/3/4 filesystem are IN USE, from its block bitmaps
(PAD-1576).

A card write copied every byte of the image and a card backup read every
byte of the card, free space included: a 16 GB card holding 5 GB of game
took the time of 16.  The filesystem already says which blocks hold
nothing - one bitmap block per group - so the copy can leave them alone.

THE RULE IS "UNKNOWN MEANS COPY".  :func:`fs_used_ranges` answers ``None``
- copy the whole partition, as before - unless every one of these holds:

* there is a superblock, and its geometry is sane and fits the partition;
* the filesystem is CLEAN and its journal needs no replay.  A journal
  waiting to be replayed can hold a newer bitmap than the one on disk, and
  the blocks that newer bitmap claims would be ones this skipped;
* it uses no feature that changes what a bitmap bit means (bigalloc's
  clusters, meta_bg's moved descriptors) and none this code has not heard
  of;
* every group's bitmap agrees with the free count in its own descriptor.

What is skipped is only what the filesystem itself calls free, so a copy
made this way mounts and checks clean; the skipped blocks keep whatever
the destination held, which nothing reads.

Pure Python and brand-agnostic: it lives in ``core`` beside
:mod:`rawdevice`, which owns the partition table walk.
"""

import struct

# Feature bits that leave the meaning of a block bitmap bit alone.  Anything
# outside these masks is "unknown": copy everything.
_INCOMPAT_OK = (0x2        # filetype
                | 0x40     # extents
                | 0x80     # 64bit
                | 0x200    # flex_bg
                | 0x400    # ea_inode
                | 0x2000   # csum_seed
                | 0x4000   # largedir
                | 0x8000   # inline_data
                | 0x10000  # encrypt
                | 0x20000)  # casefold
_INCOMPAT_64BIT = 0x80
_RO_COMPAT_OK = (0x1 | 0x2 | 0x4 | 0x8      # sparse_super large_file btree huge_file
                 | 0x10 | 0x20 | 0x40       # gdt_csum dir_nlink extra_isize
                 | 0x100 | 0x400            # quota metadata_csum
                 | 0x1000 | 0x2000          # readonly project
                 | 0x8000)                  # verity
_RO_COMPAT_GROUP_CSUM = 0x10 | 0x400
_BG_BLOCK_UNINIT = 0x2
_STATE_VALID, _STATE_ERROR = 0x1, 0x2

# Sanity bound on the group count: 64 GiB of 1 KiB blocks is 8 M blocks in
# 8192-block groups.  A superblock claiming more is not one of ours.
_MAX_GROUPS = 1 << 16


def _bit_runs(bitmap, nbits):
    """``[(first, count)]`` runs of SET bits among the first *nbits* of
    *bitmap* (bit 0 is the low bit of byte 0, as ext4 numbers them)."""
    runs = []
    start = None
    nbytes = (nbits + 7) // 8
    for bi in range(nbytes):
        v = bitmap[bi]
        if v == 0xFF:
            if start is None:
                start = bi * 8
            continue
        if v == 0:
            if start is not None:
                runs.append((start, bi * 8 - start))
                start = None
            continue
        for k in range(8):
            if (v >> k) & 1:
                if start is None:
                    start = bi * 8 + k
            elif start is not None:
                runs.append((start, bi * 8 + k - start))
                start = None
    if start is not None:
        runs.append((start, nbytes * 8 - start))
    # The bits past the group's last block are padding (mkfs sets them).
    out = []
    for first, count in runs:
        if first >= nbits:
            break
        out.append((first, min(count, nbits - first)))
    return out


def merge_ranges(ranges, gap=0):
    """Sorted, non-overlapping ``[(offset, length)]`` from *ranges*, joining
    any two closer than *gap* bytes."""
    out = []
    for off, length in sorted(r for r in ranges if r[1] > 0):
        if out and off <= out[-1][0] + out[-1][1] + gap:
            end = max(out[-1][0] + out[-1][1], off + length)
            out[-1] = (out[-1][0], end - out[-1][0])
        else:
            out.append((off, length))
    return out


def complement(ranges, total):
    """The parts of ``[0, total)`` that the sorted, merged *ranges* leave."""
    out = []
    at = 0
    for off, length in ranges:
        if off > at:
            out.append((at, off - at))
        at = max(at, off + length)
    if at < total:
        out.append((at, total - at))
    return out


def fs_used_ranges(read, part_len):
    """``[(offset, length)]`` - the bytes of one partition that its ext
    filesystem has in use, sorted and merged, offsets from the partition's
    start - or ``None`` when that cannot be said for certain and the whole
    partition must be copied (the module docstring has the conditions).

    *read(offset, length)* returns bytes of the partition.  Whatever of the
    partition lies past the filesystem's end counts as in use.
    """
    try:
        return _fs_used_ranges(read, part_len)
    except (struct.error, IndexError, ValueError, OverflowError):
        return None


def _fs_used_ranges(read, part_len):
    sb = read(1024, 1024)
    if len(sb) < 1024 or sb[0x38:0x3A] != b"\x53\xef":
        return None
    u32 = lambda off: struct.unpack_from("<I", sb, off)[0]
    u16 = lambda off: struct.unpack_from("<H", sb, off)[0]
    rev = u32(0x4C)
    incompat = u32(0x60) if rev else 0
    ro_compat = u32(0x64) if rev else 0
    if incompat & ~_INCOMPAT_OK or ro_compat & ~_RO_COMPAT_OK:
        return None
    state = u16(0x3A)
    if not state & _STATE_VALID or state & _STATE_ERROR:
        return None
    log_bs = u32(0x18)
    if log_bs > 6:
        return None
    bs = 1024 << log_bs
    first = u32(0x14)
    bpg = u32(0x20)
    ipg = u32(0x28)
    blocks = u32(0x04)
    desc = 32
    if incompat & _INCOMPAT_64BIT:
        blocks |= u32(0x150) << 32
        desc = u16(0xFE)
        if desc < 64 or desc > bs or desc & (desc - 1):
            return None
    inode_size = u16(0x58) if rev else 128
    if (not 0 < bpg <= bs * 8 or not ipg or first != (1 if bs == 1024 else 0)
            or blocks <= first or blocks * bs > part_len
            or not 128 <= inode_size <= bs):
        return None
    ngroups = -(-(blocks - first) // bpg)
    if ngroups > _MAX_GROUPS:
        return None
    gdt_blocks = -(-(ngroups * desc) // bs)
    gdt = read((first + 1) * bs, gdt_blocks * bs)
    if len(gdt) < ngroups * desc:
        return None
    reserved_gdt = u16(0xCE)
    itable_blocks = -(-(ipg * inode_size) // bs)
    uninit_ok = bool(ro_compat & _RO_COMPAT_GROUP_CSUM)
    wide = desc >= 64

    used = [(0, first + 1 + gdt_blocks)]        # boot block, superblock, GDT
    for g in range(ngroups):
        d = g * desc
        bbm, ibm, itb = struct.unpack_from("<III", gdt, d)
        free = struct.unpack_from("<H", gdt, d + 0x0C)[0]
        flags = struct.unpack_from("<H", gdt, d + 0x12)[0]
        if wide:
            hb, hi, ht = struct.unpack_from("<III", gdt, d + 0x20)
            bbm |= hb << 32
            ibm |= hi << 32
            itb |= ht << 32
            free |= struct.unpack_from("<H", gdt, d + 0x2C)[0] << 16
        for blk, count in ((bbm, 1), (ibm, 1), (itb, itable_blocks)):
            if not first <= blk or blk + count > blocks:
                return None
            used.append((blk, count))
        start = first + g * bpg
        n = min(bpg, blocks - start)
        if uninit_ok and flags & _BG_BLOCK_UNINIT:
            # No bitmap on disk yet: the group holds at most a superblock
            # and descriptor backup (taken as present - a few blocks) and
            # whatever group metadata the loop above places in it.
            used.append((start, min(n, 1 + gdt_blocks + reserved_gdt)))
            continue
        bitmap = read(bbm * bs, bs)
        if len(bitmap) < bs:
            return None
        runs = _bit_runs(bitmap, n)
        if n - sum(c for _f, c in runs) != free:
            return None                     # bitmap and descriptor disagree
        used.extend((start + f, c) for f, c in runs)

    out = merge_ranges([(b * bs, c * bs) for b, c in used])
    if blocks * bs < part_len:
        out = merge_ranges(out + [(blocks * bs, part_len - blocks * bs)])
    return out
