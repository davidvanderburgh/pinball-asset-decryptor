"""Building a Spike 2 card for a bigger SD card (card_size.py).

The partition-table arithmetic is checked against the numbers read off
Stern's own images: an 8 GB card grown to the 16 GB class must come out with
jaws_le 16G's table, and to the 32 GB class with metallica's.  The byte move
is exercised on sparse synthetic cards; resize2fs and e2fsck are stubbed here
(the real ones run in the scratchpad end-to-end check on real images).
"""

import os
import struct

import pytest

from pinball_decryptor.plugins.stern import card_size as cs
from pinball_decryptor.plugins.stern import formats

# The MBR entries and EBRs of the stock images, byte for byte.
P1_ENT = bytes.fromhex("00000140 0c0320bf 00200000 00400000")
P2_ENT = bytes.fromhex("000001c0 8303e0ff 00600000 00800a00")
EBR1 = bytes.fromhex("0003e0ff 8303e0ff 00080000 fe3f0200"
                     "0003e0ff 0503e0ff fe470200 00a01000")
EBR2 = bytes.fromhex("0003e0ff 8303e0ff 02000000 fe9f1000")
TABLES = {    # class: (p3 count, p4 start) as Stern ships them
    "8G": (13402110, 14114816),
    "16G": (28311550, 29024256),
    "32G": (57343998, 58056704),
}
P4_COUNT = 1239038


def _sparse(f, size):
    # the module's own way of growing a file without writing gigabytes of
    # zeros (a Windows truncate writes them)
    cs._grow_file(f, 0, size)


def make_card(path, cls="8G", extra_logical=False, marks=True):
    """A sparse Stern-shaped card of class *cls*: the real MBR and EBR bytes,
    and a recognisable pattern at the start of p5 and p6 and in the tail."""
    p3c, p4s = TABLES[cls]
    size = cs.CARD_SIZES[cls]
    mbr = bytearray(512)
    mbr[440:444] = b"\x0c\x4d\xb0\x8f"
    mbr[446:462] = P1_ENT
    mbr[462:478] = P2_ENT
    mbr[478:494] = (bytes.fromhex("0003e0ff 8303e0ff 00e00a00")
                    + struct.pack("<I", p3c))
    mbr[494:510] = (bytes.fromhex("0003e0ff 0f03e0ff")
                    + struct.pack("<II", p4s, P4_COUNT))
    mbr[510:512] = b"\x55\xaa"
    with open(path, "wb") as f:
        _sparse(f, size)
        f.seek(0)
        f.write(bytes(mbr))
        e1 = bytearray(512)
        e1[446:478] = EBR1
        e1[510:512] = b"\x55\xaa"
        f.seek(p4s * 512)
        f.write(bytes(e1))
        e2 = bytearray(512)
        e2[446:462] = EBR2
        if extra_logical:
            e2[462:478] = bytes.fromhex("0003e0ff 0503e0ff 00001100 00100000")
        e2[510:512] = b"\x55\xaa"
        ebr2 = p4s + 149502
        f.seek(ebr2 * 512)
        f.write(bytes(e2))
        if extra_logical:
            e3 = bytearray(512)
            e3[446:462] = bytes.fromhex("0003e0ff 8303e0ff 02000000 00080000")
            e3[510:512] = b"\x55\xaa"
            f.seek((p4s + 0x110000) * 512)
            f.write(bytes(e3))
        if marks:
            f.seek((p4s + 2048) * 512)
            f.write(b"P5-DATA-" * 64)
            f.seek((ebr2 + 2) * 512)
            f.write(b"P6-DUMP-" * 64)
            f.seek(size - 1024)
            f.write(b"TAIL" * 256)
            f.seek(712704 * 512)
            f.write(b"P3-GAMES" * 64)
    return path


def test_the_stock_layouts_read_back(tmp_path):
    for cls, (p3c, p4s) in TABLES.items():
        with open(make_card(tmp_path / (cls + ".raw"), cls), "rb") as f:
            lay = cs.read_layout(f)
        assert lay.laid_out == cs.CARD_SIZES[cls]
        assert (lay.p3_count, lay.p4_start, lay.p4_count) == (p3c, p4s, P4_COUNT)
        assert lay.logicals == [(p4s, p4s + 2048, 147454),
                                (p4s + 149502, p4s + 149504, 1089534)]


@pytest.mark.parametrize("src,dst", [("8G", "16G"), ("8G", "32G"),
                                     ("16G", "32G")])
def test_growing_gives_sterns_own_table_for_that_class(tmp_path, src, dst):
    with open(make_card(tmp_path / "c.raw", src), "rb") as f:
        lay = cs.read_layout(f)
    delta, new = cs.plan(lay, dst)
    assert delta > 0
    assert (new.p3_count, new.p4_start) == TABLES[dst]
    assert new.laid_out == cs.CARD_SIZES[dst]
    # ...and the partitions the app's own reader finds on a card of that
    # class are the ones linux_parts predicts
    with open(make_card(tmp_path / "ref.raw", dst, marks=False), "rb") as f:
        ref = cs.read_layout(f)
    assert new == ref._replace(size=new.size)
    assert cs.linux_parts(new) == formats.linux_partitions(
        str(tmp_path / "ref.raw"))


def test_nothing_to_do_when_the_card_is_that_big_already(tmp_path):
    with open(make_card(tmp_path / "c.raw", "16G", marks=False), "rb") as f:
        lay = cs.read_layout(f)
    assert cs.plan(lay, "16G") == (0, lay)
    assert cs.plan(lay, "8G") == (0, lay)


@pytest.mark.parametrize("damage,words", [
    (lambda b: b.__setitem__(slice(478 + 8, 478 + 12),
                             struct.pack("<I", 712705)), "games partition"),
    (lambda b: b.__setitem__(slice(510, 512), b"\0\0"), "no partition table"),
    (lambda b: b.__setitem__(494 + 4, 0x83), "no extended partition"),
    (lambda b: b.__setitem__(slice(462 + 8, 462 + 12),
                             struct.pack("<I", 24577)), "boot and system"),
])
def test_a_card_not_laid_out_like_sterns_is_refused(tmp_path, damage, words):
    path = make_card(tmp_path / "c.raw", marks=False)
    with open(path, "r+b") as f:
        mbr = bytearray(f.read(512))
        damage(mbr)
        f.seek(0)
        f.write(bytes(mbr))
        with pytest.raises(cs.CardSizeError, match=words):
            cs.read_layout(f)


def test_a_third_logical_partition_is_a_multi_boot_card(tmp_path):
    path = make_card(tmp_path / "c.raw", extra_logical=True, marks=False)
    with open(path, "rb") as f:
        with pytest.raises(cs.CardSizeError, match="more than two logical"):
            cs.read_layout(f)


def test_a_truncated_image_is_refused(tmp_path):
    path = make_card(tmp_path / "c.raw", marks=False)
    with open(path, "r+b") as f:
        f.truncate(cs.CARD_SIZES["8G"] - 4096)
        with pytest.raises(cs.CardSizeError, match="shorter"):
            cs.read_layout(f)


def test_requested_reads_the_build_option(monkeypatch):
    monkeypatch.delenv(cs.ENV, raising=False)
    assert cs.requested() is None
    for v, want in (("16G", "16G"), ("32g", "32G"), (" 16G ", "16G"),
                    ("8G", None), ("64G", None), ("", None), ("yes", None)):
        monkeypatch.setenv(cs.ENV, v)
        assert cs.requested() == want


class _FakeE2fs:
    """Stands in for the loop-device runner: records the grow it was asked
    for and answers every step with *rcs* (default: all clean)."""
    calls = []
    rcs = {}

    def __init__(self):
        pass

    def grow(self, image_path, offset, size, epoch=None, timeout=0):
        _FakeE2fs.calls.append((image_path, offset, size))
        res = {}
        for step in ("loop", "fsck", "resize", "check"):
            rc = self.rcs.get(step, 0)
            res[step] = (rc, "%s said %d" % (step, rc))
            if rc not in ((0, 1) if step == "fsck" else (0,)):
                break
        return res


def _read(path, off, n):
    with open(path, "rb") as f:
        f.seek(off)
        return f.read(n)


def test_expand_moves_the_data_partitions_and_rewrites_two_fields(
        tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "_E2fs", _FakeE2fs)
    _FakeE2fs.calls = []
    path = make_card(tmp_path / "c.raw")
    with open(path, "rb") as f:
        old = cs.read_layout(f)
    before = {
        "boot": _read(path, 0, 440),
        "diskid": _read(path, 440, 6),
        "p1p2": _read(path, 446, 32),
        "p3": _read(path, 712704 * 512, 512),
    }
    region_head = _read(path, old.p4_start * 512, 2048 * 512 + 512)
    p6_head = _read(path, old.logicals[1][1] * 512, 512)
    tail = _read(path, old.laid_out - 1024, 1024)

    assert cs.expand_image(str(path), "16G") is True

    assert os.path.getsize(path) == cs.CARD_SIZES["16G"]
    with open(path, "rb") as f:
        new = cs.read_layout(f)
    assert (new.p3_count, new.p4_start) == TABLES["16G"]
    # sectors before p3's end are untouched: the boot code, the disk id,
    # p1/p2's entries and the games partition's first bytes
    assert _read(path, 0, 440) == before["boot"]
    assert _read(path, 440, 6) == before["diskid"]
    assert _read(path, 446, 32) == before["p1p2"]
    assert _read(path, 712704 * 512, 512) == before["p3"]
    # the EBRs, /data and /dump and the tail moved verbatim
    assert _read(path, new.p4_start * 512, len(region_head)) == region_head
    assert _read(path, new.logicals[1][1] * 512, 512) == p6_head
    assert _read(path, new.laid_out - 1024, 1024) == tail
    # one grow of p3, bounded to the new partition
    assert _FakeE2fs.calls == [(str(path), 712704 * 512, 28311550 * 512)]


def test_expand_is_a_no_op_at_the_same_size(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "_E2fs", _FakeE2fs)
    _FakeE2fs.calls = []
    path = make_card(tmp_path / "c.raw", "16G", marks=False)
    assert cs.expand_image(str(path), "16G") is False
    assert _FakeE2fs.calls == []
    assert os.path.getsize(path) == cs.CARD_SIZES["16G"]


def test_a_failed_resize_is_reported_not_swallowed(tmp_path, monkeypatch):
    class Failing(_FakeE2fs):
        rcs = {"resize": 1}
    monkeypatch.setattr(cs, "_E2fs", Failing)
    path = make_card(tmp_path / "c.raw", marks=False)
    with pytest.raises(cs.CardSizeError, match="could not be grown"):
        cs.expand_image(str(path), "16G")


def test_a_dirty_games_partition_stops_it_before_the_resize(tmp_path,
                                                            monkeypatch):
    class Dirty(_FakeE2fs):
        rcs = {"fsck": 4}
    monkeypatch.setattr(cs, "_E2fs", Dirty)
    path = make_card(tmp_path / "c.raw", marks=False)
    with pytest.raises(cs.CardSizeError, match="failed its check"):
        cs.expand_image(str(path), "16G")


def test_a_truncating_resize_is_caught(tmp_path, monkeypatch):
    """What resize2fs does to a REGULAR FILE (resize/main.c:683): it ends by
    truncating it to the filesystem's length, offset or not.  The runner never
    hands it a file, and if the image changes size anyway the grow fails."""
    class Truncating(_FakeE2fs):
        def grow(self, image_path, offset, size, epoch=None, timeout=0):
            with open(image_path, "r+b") as f:
                f.truncate(size // 4096 * 4096)
            return super().grow(image_path, offset, size)
    monkeypatch.setattr(cs, "_E2fs", Truncating)
    path = make_card(tmp_path / "c.raw", marks=False)
    with pytest.raises(cs.CardSizeError, match="changed size"):
        cs.expand_image(str(path), "16G")


def test_the_runner_script_uses_a_bounded_loop_device():
    """The script the runner ships: a loop device limited to the partition,
    and resize2fs/e2fsck pointed at it, never at the image file."""
    shipped = []

    class Ex:
        def to_exec_path(self, p):
            return p

        def run(self, cmd, timeout=0):
            import base64
            import shlex
            tmp = shlex.split(cmd.split("<", 1)[1].split("|", 1)[0])[0]
            with open(tmp, "rb") as fh:
                shipped.append(base64.b64decode(fh.read()).decode())
            return ("PAD_E2 loop 0\nPAD_E2 fsck 0\nPAD_E2 resize 0\n"
                    "PAD_E2 check 0\n")
    e2 = cs._E2fs.__new__(cs._E2fs)
    e2.ex = Ex()
    res = e2.grow("C:/x/card.raw", 364904448, 14495513600)
    assert res == {"loop": (0, ""), "fsck": (0, ""), "resize": (0, ""),
                   "check": (0, "")}
    script = shipped[0]
    assert ("losetup -f --show -o 364904448 --sizelimit 14495513600"
            in script)
    # in 512-byte SECTORS: a bare number would be read in the filesystem's
    # own block size, which nothing here may assume
    assert 'resize2fs "$L" 28311550s' in script
    assert 'e2fsck -fp "$L"' in script and 'e2fsck -fn "$L"' in script
    assert "?offset" not in script
    assert 'losetup -d "$L"' in script


def test_target_for_and_output_parts(tmp_path, monkeypatch):
    path = make_card(tmp_path / "c.raw", marks=False)
    monkeypatch.delenv(cs.ENV, raising=False)
    assert cs.target_for(str(path)) is None
    assert cs.target_for(str(path), "16G") == "16G"
    monkeypatch.setenv(cs.ENV, "32G")
    assert cs.target_for(str(path)) == "32G"
    parts = formats.linux_partitions(str(path))
    assert cs.output_parts(str(path), parts, None) == parts
    got = cs.output_parts(str(path), parts, "16G")
    assert got[0] == (712704 * 512, 28311550 * 512)
    # the MBR's Linux partitions only (what formats reads): p3 longer, p2 as
    # it was
    assert got == [(712704 * 512, 28311550 * 512), (24576 * 512, 688128 * 512)]


def test_target_for_refuses_a_card_it_cannot_read(tmp_path):
    bad = tmp_path / "x.raw"
    bad.write_bytes(b"\0" * 4096)
    with pytest.raises(cs.CardSizeError, match="can't be built for a 16 GB SD card"):
        cs.target_for(str(bad), "16G")


def _set_p3_superblock(path, incompat):
    """Give the synthetic card's games partition an ext4 superblock magic
    and *incompat* word (all the journal check reads)."""
    with open(path, "r+b") as f:
        f.seek(712704 * 512 + 1024 + 0x38)
        f.write(b"\x53\xef")
        f.seek(712704 * 512 + 1024 + 0x60)
        f.write(struct.pack("<I", incompat))


def test_an_unreplayed_journal_is_refused_before_the_build(tmp_path):
    """The check before the resize replays a pending journal, and the replay
    moves files the build already patched (a real library image has one):
    refused up front, in words, instead of discarded after the encode."""
    path = make_card(tmp_path / "c.raw", marks=False)
    _set_p3_superblock(path, 0x0242)                # stock: no recovery
    assert cs.target_for(str(path), "16G") == "16G"
    _set_p3_superblock(path, 0x0246)                # needs_recovery
    with pytest.raises(cs.CardSizeError, match="not cleanly unmounted"):
        cs.target_for(str(path), "16G")
    with pytest.raises(cs.CardSizeError, match="16 GB SD card"):
        cs.target_for(str(path), "16G")


def test_the_vacated_range_is_zeroed_and_the_clock_passed_on(tmp_path,
                                                            monkeypatch):
    seen = {}

    class Rec(_FakeE2fs):
        def grow(self, image_path, offset, size, epoch=None, timeout=0):
            seen["epoch"] = epoch
            return super().grow(image_path, offset, size)
    monkeypatch.setattr(cs, "_E2fs", Rec)
    path = make_card(tmp_path / "c.raw")
    with open(path, "rb") as f:
        old = cs.read_layout(f)
    cs.expand_image(str(path), "16G", epoch=1662343979)
    assert seen["epoch"] == 1662343979
    # the old EBR1 and the old /data start read as zeros now
    assert _read(path, old.p4_start * 512, 512) == bytes(512)
    assert _read(path, (old.p4_start + 2048) * 512, 512) == bytes(512)


def test_a_cancel_is_a_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "_E2fs", _FakeE2fs)
    path = make_card(tmp_path / "c.raw", marks=False)
    with pytest.raises(cs.Cancelled):
        cs.expand_image(str(path), "16G", cancel=lambda: True)
    # nothing points at a moved copy: the card is its old size and layout
    assert os.path.getsize(path) == cs.CARD_SIZES["8G"]
    with open(path, "rb") as f:
        assert cs.read_layout(f).p3_count == TABLES["8G"][0]


def test_the_runner_pins_the_clock_zeroes_tables_and_clears_stale_loops():
    shipped = []

    class Ex:
        def to_exec_path(self, p):
            return p

        def run(self, cmd, timeout=0):
            import base64
            import shlex
            tmp = shlex.split(cmd.split("<", 1)[1].split("|", 1)[0])[0]
            with open(tmp, "rb") as fh:
                shipped.append(base64.b64decode(fh.read()).decode())
            return "PAD_E2 loop 0\n"
    e2 = cs._E2fs.__new__(cs._E2fs)
    e2.ex = Ex()
    e2.grow("C:/x/card.raw", 364904448, 14495513600, epoch=1662343979)
    e2.grow("C:/x/card.raw", 364904448, 14495513600)
    pinned, free = shipped
    assert "export RESIZE2FS_FORCE_ITABLE_INIT=1" in pinned
    assert "E2FSCK_TIME=1662343979 E2FSPROGS_FAKE_TIME=1662343979" in pinned
    assert "E2FSCK_TIME" not in free and "RESIZE2FS_FORCE_ITABLE_INIT" in free
    assert 'losetup -j "$IMG"' in pinned
    assert pinned.index("losetup -j") < pinned.index("losetup -f")


def test_the_bigger_card_hint_only_where_it_helps(tmp_path):
    from pinball_decryptor.core import ext4_grow
    from pinball_decryptor.plugins.stern import engine
    nospace = ext4_grow.Ext4GrowNoSpace("full")
    p3 = 712704 * 512
    c8 = make_card(tmp_path / "8.raw", "8G", marks=False)
    c16 = make_card(tmp_path / "16.raw", "16G", marks=False)
    c32 = make_card(tmp_path / "32.raw", "32G", marks=False)
    h8 = engine._bigger_card_hint(nospace, str(c8), p3)
    assert "16 GB or 32 GB" in h8 or not cs.supported()
    assert "32 GB" in engine._bigger_card_hint(nospace, str(c16), p3) \
        or not cs.supported()
    assert "16 GB" not in engine._bigger_card_hint(nospace, str(c16), p3)
    assert engine._bigger_card_hint(nospace, str(c32), p3) == ""
    # the system partition never grows; a failure that isn't for space is
    # not answered with a size
    assert engine._bigger_card_hint(nospace, str(c8), 24576 * 512) == ""
    assert engine._bigger_card_hint(ext4_grow.Ext4GrowError("x"),
                                    str(c8), p3) == ""


def test_a_grown_partition_that_does_not_check_clean_is_refused(tmp_path,
                                                               monkeypatch):
    class Unclean(_FakeE2fs):
        rcs = {"check": 4}
    monkeypatch.setattr(cs, "_E2fs", Unclean)
    path = make_card(tmp_path / "c.raw", marks=False)
    with pytest.raises(cs.CardSizeError, match="did not check clean"):
        cs.expand_image(str(path), "16G")


def test_offered_is_what_the_original_can_be_built_for(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "supported", lambda: True)
    c8 = make_card(tmp_path / "8.raw", "8G", marks=False)
    c16 = make_card(tmp_path / "16.raw", "16G", marks=False)
    c32 = make_card(tmp_path / "32.raw", "32G", marks=False)
    assert cs.offered(str(c8)) == ["16G", "32G"]
    assert cs.offered(str(c16)) == ["32G"]
    assert cs.offered(str(c32)) == []
    _set_p3_superblock(c8, 0x0246)                  # a pending journal
    assert cs.offered(str(c8)) == []
    monkeypatch.setattr(cs, "supported", lambda: False)
    assert cs.offered(str(c16)) == []


def test_the_hint_names_only_sizes_the_original_can_take(tmp_path):
    from pinball_decryptor.core import ext4_grow
    from pinball_decryptor.plugins.stern import engine
    nospace = ext4_grow.Ext4GrowNoSpace("full")
    c8 = make_card(tmp_path / "8.raw", "8G", marks=False)
    p3 = 712704 * 512
    # an original the Write tab offers nothing for gets no pointer at it
    assert engine._bigger_card_hint(nospace, str(c8), p3, []) == ""
    if cs.supported():
        h = engine._bigger_card_hint(nospace, str(c8), p3, ["32G"])
        assert "(32 GB)" in h and "16 GB" not in h
