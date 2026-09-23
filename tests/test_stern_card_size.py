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
    calls = []

    def __init__(self):
        pass

    def dev(self, image_path, offset):
        return "%s?offset=%d" % (image_path, offset)

    def run(self, tool, args, timeout):
        _FakeE2fs.calls.append((tool, list(args)))
        return 0, ""


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
    # e2fsck -fp, resize2fs to the class's block count, e2fsck -fn - on p3
    tools = [c[0] for c in _FakeE2fs.calls]
    assert tools == ["e2fsck", "resize2fs", "e2fsck"]
    assert _FakeE2fs.calls[0][1][0] == "-fp"
    assert _FakeE2fs.calls[1][1][1] == str(28311550 * 512 // 4096)
    assert _FakeE2fs.calls[2][1][0] == "-fn"
    assert all(c[1][-2 if c[0] == "resize2fs" else -1].endswith(
        "?offset=%d" % (712704 * 512)) for c in _FakeE2fs.calls)


def test_expand_is_a_no_op_at_the_same_size(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "_E2fs", _FakeE2fs)
    _FakeE2fs.calls = []
    path = make_card(tmp_path / "c.raw", "16G", marks=False)
    assert cs.expand_image(str(path), "16G") is False
    assert _FakeE2fs.calls == []
    assert os.path.getsize(path) == cs.CARD_SIZES["16G"]


def test_a_failed_resize_is_reported_not_swallowed(tmp_path, monkeypatch):
    class Failing(_FakeE2fs):
        def run(self, tool, args, timeout):
            return (1, "resize2fs: No space left on device") \
                if tool == "resize2fs" else (0, "")
    monkeypatch.setattr(cs, "_E2fs", Failing)
    path = make_card(tmp_path / "c.raw", marks=False)
    with pytest.raises(cs.CardSizeError, match="resize2fs could not grow"):
        cs.expand_image(str(path), "16G")


def test_a_dirty_games_partition_stops_it_before_the_resize(tmp_path,
                                                            monkeypatch):
    seen = []

    class Dirty(_FakeE2fs):
        def run(self, tool, args, timeout):
            seen.append(tool)
            return (4, "UNEXPECTED INCONSISTENCY") if tool == "e2fsck" \
                else (0, "")
    monkeypatch.setattr(cs, "_E2fs", Dirty)
    path = make_card(tmp_path / "c.raw", marks=False)
    with pytest.raises(cs.CardSizeError, match="failed its check"):
        cs.expand_image(str(path), "16G")
    assert seen == ["e2fsck"]


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
    with pytest.raises(cs.CardSizeError, match="can't be built for a 16G"):
        cs.target_for(str(bad), "16G")
