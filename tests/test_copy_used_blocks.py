"""PAD-1576: a card write and a card backup leave the free blocks alone.

The filesystems here are built by hand (a superblock, one descriptor table,
one bitmap a group), so the tests need no mkfs and say exactly which blocks
are in use.
"""
import os
import struct

import pytest

from pinball_decryptor.core import ext4_used
from pinball_decryptor.core import rawdevice as rd

BS = 1024
BPG = 256            # blocks a group: small, so a few groups fit in 1 MiB
IPG = 16
GROUPS = 4
BLOCKS = 1 + GROUPS * BPG
META = (3, 4, 5, 6)  # bitmap, inode bitmap, two inode-table blocks


def make_fs(data=None, *, state=1, incompat=0x2, ro_compat=0x1, wide=False,
            uninit=(), free_lie=0, tail_blocks=0):
    """A ``BLOCKS``-block ext filesystem whose group *g* has the data blocks
    ``data[g]`` (offsets inside the group) in use.  Every used block is
    filled with a byte naming it; free ones are zero."""
    data = data or {}
    desc = 64 if wide else 32
    if wide:
        incompat |= 0x80
    fs = bytearray((BLOCKS + tail_blocks) * BS)
    sb = bytearray(1024)
    struct.pack_into("<I", sb, 0x00, IPG * GROUPS)
    struct.pack_into("<I", sb, 0x04, BLOCKS)
    struct.pack_into("<I", sb, 0x14, 1)             # first data block
    struct.pack_into("<I", sb, 0x18, 0)             # 1 KiB blocks
    struct.pack_into("<I", sb, 0x20, BPG)
    struct.pack_into("<I", sb, 0x28, IPG)
    sb[0x38:0x3A] = b"\x53\xef"
    struct.pack_into("<H", sb, 0x3A, state)
    struct.pack_into("<I", sb, 0x4C, 1)             # rev 1
    struct.pack_into("<H", sb, 0x58, 128)           # inode size
    struct.pack_into("<I", sb, 0x60, incompat)
    struct.pack_into("<I", sb, 0x64, ro_compat)
    struct.pack_into("<H", sb, 0xFE, desc if wide else 0)
    fs[1024:2048] = sb
    used = {0, 1, 2}                                # boot, superblock, GDT
    for g in range(GROUPS):
        start = 1 + g * BPG
        bits = set(META) | set(data.get(g, ()))
        if g == 0:
            bits |= {0, 1}                          # superblock, GDT
        d = 2 * BS + g * desc
        struct.pack_into("<III", fs, d, start + 3, start + 4, start + 5)
        flags = 0x2 if g in uninit else 0
        if g in uninit:
            bits = set(META) | ({0, 1} if g == 0 else set())
        struct.pack_into("<H", fs, d + 0x0C,
                         BPG - len(bits) + (free_lie if g == 1 else 0))
        struct.pack_into("<H", fs, d + 0x12, flags)
        if g not in uninit:
            bm = bytearray(BS)
            for b in bits:
                bm[b // 8] |= 1 << (b % 8)
            for b in range(BPG, BS * 8):            # padding bits, as mkfs
                bm[b // 8] |= 1 << (b % 8)
            fs[(start + 3) * BS:(start + 4) * BS] = bm
        used |= {start + b for b in bits}
    for blk in used:
        if not any(fs[blk * BS:(blk + 1) * BS]):
            fs[blk * BS:(blk + 1) * BS] = bytes([blk % 251 + 1]) * BS
    return bytes(fs), used


def reader(buf):
    return lambda off, n: buf[off:off + n]


def blocks_of(ranges):
    out = set()
    for off, length in ranges:
        assert off % BS == 0 and length % BS == 0
        out |= set(range(off // BS, (off + length) // BS))
    return out


DATA = {0: range(10, 40), 1: (7, 8, 200), 3: range(100, 256)}


def test_used_ranges_are_exactly_the_bitmaps():
    fs, used = make_fs(DATA)
    got = ext4_used.fs_used_ranges(reader(fs), len(fs))
    assert blocks_of(got) == used
    assert got == ext4_used.merge_ranges(got)        # sorted, merged


def test_wide_descriptors():
    fs, used = make_fs(DATA, wide=True)
    assert blocks_of(ext4_used.fs_used_ranges(reader(fs), len(fs))) == used


def test_what_lies_past_the_filesystem_is_kept():
    fs, used = make_fs(DATA, tail_blocks=5)
    got = blocks_of(ext4_used.fs_used_ranges(reader(fs), len(fs)))
    assert got == used | set(range(BLOCKS, BLOCKS + 5))


def test_a_group_with_no_bitmap_yet_keeps_its_metadata():
    fs, used = make_fs(DATA, ro_compat=0x1 | 0x10, uninit=(2,))
    got = blocks_of(ext4_used.fs_used_ranges(reader(fs), len(fs)))
    assert used <= got
    start = 1 + 2 * BPG
    assert got - used <= {start, start + 1}          # the backup it may hold


@pytest.mark.parametrize("kw", [
    dict(state=0),                      # not cleanly unmounted
    dict(state=3),                      # errors recorded
    dict(incompat=0x2 | 0x4),           # journal needs replay
    dict(incompat=0x2 | 0x10),          # meta_bg
    dict(incompat=0x2 | 0x80000),       # a feature nobody has heard of
    dict(ro_compat=0x1 | 0x200),        # bigalloc
    dict(free_lie=1),                   # bitmap and descriptor disagree
])
def test_anything_uncertain_means_copy_everything(kw):
    fs, _used = make_fs(DATA, **kw)
    assert ext4_used.fs_used_ranges(reader(fs), len(fs)) is None


def test_not_a_filesystem_or_a_broken_one():
    assert ext4_used.fs_used_ranges(reader(bytes(8192)), 8192) is None
    fs, _ = make_fs(DATA)
    assert ext4_used.fs_used_ranges(reader(fs), len(fs) - BS) is None
    junk = bytearray(fs)
    struct.pack_into("<I", junk, 1024 + 0x20, 0)     # no blocks per group
    assert ext4_used.fs_used_ranges(reader(bytes(junk)), len(junk)) is None
    assert ext4_used.fs_used_ranges(reader(fs[:3000]), len(fs)) is None


# ---- a whole card image ------------------------------------------------

SEC = 512
FS_SECTORS = BLOCKS * BS // SEC


def make_image(fs_a, fs_b):
    """MBR: p1 FAT (64 sectors at 8), p2 Linux *fs_a*, p4 extended holding
    one logical Linux *fs_b*.  Returns ``(image, offset of a, offset of b)``."""
    p1, p2 = 8, 80
    ext = p2 + FS_SECTORS + 16
    log = ext + 8
    total = log + FS_SECTORS + 2
    img = bytearray(os.urandom(total * SEC))         # nothing here is zero

    def entry(buf, at, ptype, lba, count):
        buf[at:at + 16] = struct.pack("<BBBBBBBBII", 0, 0, 0, 0, ptype,
                                      0, 0, 0, lba, count)
    mbr = bytearray(512)
    entry(mbr, 446, 0x0C, p1, 64)
    entry(mbr, 462, 0x83, p2, FS_SECTORS)
    entry(mbr, 494, 0x0F, ext, total - ext)
    mbr[510:512] = b"\x55\xaa"
    img[0:512] = mbr
    ebr = bytearray(512)
    entry(ebr, 446, 0x83, log - ext, FS_SECTORS)
    ebr[510:512] = b"\x55\xaa"
    img[ext * SEC:ext * SEC + 512] = ebr
    img[p2 * SEC:p2 * SEC + len(fs_a)] = fs_a
    img[log * SEC:log * SEC + len(fs_b)] = fs_b
    return bytes(img), p2 * SEC, log * SEC


@pytest.fixture
def image(monkeypatch):
    monkeypatch.setattr(rd, "_COPY_MERGE_GAP", 0)
    monkeypatch.delenv("PAD_COPY_ALL_BLOCKS", raising=False)
    fs_a, used_a = make_fs(DATA)
    fs_b, used_b = make_fs({2: range(50, 60)})
    img, off_a, off_b = make_image(fs_a, fs_b)
    free = set()
    for off, used in ((off_a, used_a), (off_b, used_b)):
        free |= {off + b * BS + i for b in set(range(BLOCKS)) - used
                 for i in range(BS)}
    return img, free


def covered(ranges):
    out = set()
    for off, length in ranges:
        out |= set(range(off, off + length))
    return out


def test_copy_ranges_leave_out_only_the_free_blocks(image):
    img, free = image
    ranges = rd.copy_ranges(reader(img), len(img))
    assert covered(ranges) == set(range(len(img))) - free
    assert all(off % 512 == 0 for off, _n in ranges)


def test_copy_ranges_keep_what_they_are_told_to(image):
    img, free = image
    keep = (min(free), 3000)
    got = covered(rd.copy_ranges(reader(img), len(img), keep=[keep]))
    assert set(range(keep[0], keep[0] + keep[1])) <= got


def test_copy_ranges_on_4k_sectors_start_aligned(image):
    img, free = image
    ranges = rd.copy_ranges(reader(img), len(img), sector=4096)
    assert all(off % 4096 == 0 for off, _n in ranges)
    assert set(range(len(img))) - free <= covered(ranges)


def test_no_partition_table_is_one_range():
    blob = bytes(4096)
    assert rd.copy_ranges(reader(blob), len(blob)) == [(0, len(blob))]


def test_an_unclean_filesystem_is_copied_whole(monkeypatch):
    monkeypatch.setattr(rd, "_COPY_MERGE_GAP", 0)
    fs_a, _ = make_fs(DATA, incompat=0x2 | 0x4)
    fs_b, _ = make_fs(DATA, state=0)
    img, _a, _b = make_image(fs_a, fs_b)
    assert rd.copy_ranges(reader(img), len(img)) == [(0, len(img))]


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_flash_writes_and_verifies_only_the_blocks_in_use(image, tmp_path):
    img, free = image
    src = _write(tmp_path, "image.raw", img)
    card = _write(tmp_path, "card.bin", b"\xA5" * len(img))
    said = []
    written = rd.flash_image_to_device(
        src, card, eject=False, log=lambda m, _l="info": said.append(m))
    got = open(card, "rb").read()
    assert written == len(img) - len(free)
    for i in range(0, len(img), BS):
        if i in free:
            assert got[i:i + BS] == b"\xA5" * BS, i   # left as it was
        else:
            assert got[i:i + BS] == img[i:i + BS], i
    assert any("free space" in m for m in said)
    assert any("every block in use matches" in m for m in said)


def test_flash_all_blocks_on_request(image, tmp_path, monkeypatch):
    img, _free = image
    src = _write(tmp_path, "image.raw", img)
    card = _write(tmp_path, "card.bin", b"\xA5" * len(img))
    monkeypatch.setenv("PAD_COPY_ALL_BLOCKS", "1")
    assert rd.flash_image_to_device(src, card, eject=False) == len(img)
    assert open(card, "rb").read() == img
    card2 = _write(tmp_path, "card2.bin", b"\xA5" * len(img))
    monkeypatch.delenv("PAD_COPY_ALL_BLOCKS")
    assert rd.flash_image_to_device(src, card2, eject=False,
                                    skip_free=False) == len(img)
    assert open(card2, "rb").read() == img


def test_verify_still_catches_a_bad_block_in_use(image, tmp_path, monkeypatch):
    img, free = image
    src = _write(tmp_path, "image.raw", img)
    card = _write(tmp_path, "card.bin", b"\xA5" * len(img))
    used_at = next(i for i in range(len(img) - 1, 0, -1) if i not in free)
    real = rd.RawDeviceFile.copy_image_onto

    def flaky(self, *a, **kw):
        n = real(self, *a, **kw)
        self.seek(used_at)
        self.write(bytes([img[used_at] ^ 0xFF]))
        return n
    monkeypatch.setattr(rd.RawDeviceFile, "copy_image_onto", flaky)
    with pytest.raises(rd.FlashError, match="does not match the image"):
        rd.flash_image_to_device(src, card, eject=False)


def test_backup_reads_only_the_blocks_in_use(image, tmp_path):
    img, free = image
    card = _write(tmp_path, "card.bin", img)
    out = str(tmp_path / "backup.raw")
    seen = []
    n = rd.read_device_to_image(card, out,
                                progress=lambda d, t, _m="": seen.append((d, t)))
    got = open(out, "rb").read()
    assert n == len(img) - len(free)
    assert len(got) == len(img)
    for i in range(0, len(img), BS):
        want = bytes(BS) if i in free else img[i:i + BS]
        assert got[i:i + BS] == want, i
    assert seen[-1] == (n, n)
    assert not os.path.exists(out + ".part")
    # and the backup is itself a card image the planner reads the same way
    assert covered(rd.copy_ranges(reader(got), len(got))) == \
        set(range(len(img))) - free


def test_backup_all_blocks_on_request(image, tmp_path, monkeypatch):
    img, _free = image
    card = _write(tmp_path, "card.bin", img)
    out = str(tmp_path / "backup.raw")
    monkeypatch.setenv("PAD_COPY_ALL_BLOCKS", "1")
    assert rd.read_device_to_image(card, out) == len(img)
    assert open(out, "rb").read() == img
    monkeypatch.delenv("PAD_COPY_ALL_BLOCKS")
    assert rd.read_device_to_image(card, out, skip_free=False) == len(img)
    assert open(out, "rb").read() == img
