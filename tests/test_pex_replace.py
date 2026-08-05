"""Partition Explorer Replace (CardImage.replace_file) + dir_stats.

Uses the shared fake ext4 layer with synthetic disk offsets
(_ext4_fake.materialize_files) so the extent-mapped writes land on real,
checkable bytes in a real card file — including the Spike 2 .sidx record
refresh.

Both halves of Replace are covered: the exact-size in-place write, and the
different-size one that hands the copy to the platform's ext4 driver.  The
driver itself (core.ext4_grow) is stubbed — it needs WSL2/loop devices, and
the real mount path is exercised by the video-growth tests — but the stub
mutates the fake filesystem exactly like ``cp`` would, so the .sidx refresh
that follows it is checked for real, size fields and all.
"""
import copy
import struct

import pytest

from pinball_decryptor.core import ext4_grow
from pinball_decryptor.plugins.stern import sidx
from pinball_decryptor.plugins.stern.explorer import CardImage

from tests._ext4_fake import (GOOD_OFF, SAMPLE_TREE, install_fake_reader,
                              materialize_files, write_fake_card)


def _sidx_blob(paths):
    """A minimal FI64 .sidx: 0x38-byte header, STRS path block, one 80-byte
    record per path (digest fields zeroed)."""
    strs = b"\x00".join(p.encode() for p in paths) + b"\x00"
    out = bytearray(0x38)
    out += b"STRS" + struct.pack("<I", len(strs)) + strs
    for _ in paths:
        out += b"FI64" + struct.pack("<I", 80) + bytes(80)
    return bytes(out)


SIDX_PATHS = ["etc/init.d/game", "zeta/a.bin"]
TREE = dict(SAMPLE_TREE)
TREE["spk"] = {"index": {"turtles.sidx": _sidx_blob(SIDX_PATHS)}}


@pytest.fixture
def card(tmp_path, monkeypatch):
    install_fake_reader(monkeypatch, TREE)
    path = write_fake_card(tmp_path / "card.raw")
    placed = materialize_files(path, TREE)
    return path, placed


def test_replace_exact_size_writes_and_refreshes_sidx(card):
    path, placed = card
    new = b"#!/bin/sh\necho HI\n"                      # same 18 bytes
    src_off, old = placed["/etc/init.d/game"]
    assert len(new) == len(old)
    srcfile = path + ".new"
    with open(srcfile, "wb") as f:
        f.write(new)
    with CardImage(path) as c:
        n, refreshed = c.replace_file(1, "/etc/init.d/game", srcfile)
    assert (n, refreshed) == (len(new), True)
    data = open(path, "rb").read()
    assert data[src_off:src_off + len(new)] == new
    # The record for the replaced path carries the new digests on disk.
    sidx_off, sblob = placed["/spk/index/turtles.sidx"]
    recs, _crc, fmt = sidx.parse_records(sblob)
    po = recs["etc/init.d/game"]
    hm, md = sidx.digests(new)
    for foff, expect in sidx.record_field_writes(po, hm, md, fmt):
        assert data[sidx_off + foff:sidx_off + foff + len(expect)] == expect
    # The OTHER record stayed zeroed.
    po2 = recs["zeta/a.bin"]
    assert data[sidx_off + po2 + 37:sidx_off + po2 + 37 + 20] == bytes(20)


def test_replace_unindexed_file_reports_no_refresh(card):
    path, placed = card
    src_off, old = placed["/readme.txt"]
    srcfile = path + ".new"
    with open(srcfile, "wb") as f:
        f.write(b"HELLO WORLD")                        # same 11 bytes
    with CardImage(path) as c:
        n, refreshed = c.replace_file(1, "/readme.txt", srcfile)
    assert (n, refreshed) == (11, False)
    assert open(path, "rb").read()[src_off:src_off + 11] == b"HELLO WORLD"


def test_replace_rejects_size_mismatch_without_writing(card):
    path, placed = card
    src_off, old = placed["/readme.txt"]
    srcfile = path + ".new"
    with open(srcfile, "wb") as f:
        f.write(b"too long for the slot")
    before = open(path, "rb").read()
    with CardImage(path) as c:
        with pytest.raises(ValueError, match="size mismatch"):
            c.replace_file(1, "/readme.txt", srcfile)
    assert open(path, "rb").read() == before


def test_replace_rejects_directories_and_missing(card):
    path, _placed = card
    srcfile = path + ".new"
    with open(srcfile, "wb") as f:
        f.write(b"x")
    with CardImage(path) as c:
        with pytest.raises(IsADirectoryError):
            c.replace_file(1, "/etc", srcfile)
        with pytest.raises(FileNotFoundError):
            c.replace_file(1, "/nope.bin", srcfile)


def test_dir_stats_recursive(card):
    path, _placed = card
    with CardImage(path) as c:
        n, b = c.dir_stats(1, "/zeta")
        assert (n, b) == (2, 6)                        # AA + BBBB
        n_all, b_all = c.dir_stats(1, "/")
        assert n_all >= 4 and b_all > b


def test_file_size_is_the_real_byte_count(card):
    path, _placed = card
    with CardImage(path) as c:
        assert c.file_size(1, "/etc/init.d/game") == 18
        assert c.file_size(1, "/readme.txt") == 11
        with pytest.raises(IsADirectoryError):
            c.file_size(1, "/etc")
        with pytest.raises(FileNotFoundError):
            c.file_size(1, "/nope.bin")


# --------------------------------------------------------------------------
# Different-size replace: the ext4 driver does the allocation, we refresh the
# record afterwards.
# --------------------------------------------------------------------------

# Both the stock 18-byte script and its replacement stay under the fake's
# 1 KB per-file stride, so growing one doesn't shift where any OTHER file
# (notably the .sidx) sits on the synthetic card.
GROWN = b"#!/bin/sh\n" + b"# a much longer boot script\n" * 10


@pytest.fixture
def resizable(tmp_path, monkeypatch):
    """A card whose filesystem the stubbed ext4 driver can really mutate."""
    tree = copy.deepcopy(TREE)
    install_fake_reader(monkeypatch, tree)
    path = write_fake_card(tmp_path / "card.raw")
    placed = materialize_files(path, tree)
    calls = []

    def fake_grow(image_path, part_offset, jobs, log=None, cancel=None,
                  timeout=1800):
        calls.append((image_path, part_offset, list(jobs)))
        for rel, src in jobs:
            with open(src, "rb") as f:
                data = f.read()
            node = tree
            names = rel.split("/")
            for n in names[:-1]:
                node = node[n]
            node[names[-1]] = data                     # what `cp` did
            off, _old = placed["/" + rel]
            with open(image_path, "r+b") as f:
                f.seek(off)
                f.write(data)
            if log:
                log("  grew %s" % rel, "info")
        return len(jobs)

    monkeypatch.setattr(ext4_grow, "available", lambda: (True, "stub"))
    monkeypatch.setattr(ext4_grow, "grow_files", fake_grow)
    return path, placed, calls


def _src(tmp_path, data, name="new.bin"):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_resize_replace_grows_file_and_refreshes_size_and_digests(
        resizable, tmp_path):
    path, placed, calls = resizable
    srcfile = _src(tmp_path, GROWN)
    with CardImage(path) as c:
        n, refreshed = c.replace_file(1, "/etc/init.d/game", srcfile,
                                      allow_resize=True)
    assert (n, refreshed) == (len(GROWN), True)
    # The driver was handed the partition's byte offset and a leading-slash-free
    # card-relative path — grow_files' contract.
    assert len(calls) == 1
    assert calls[0][1] == GOOD_OFF
    assert calls[0][2] == [("etc/init.d/game", srcfile)]

    data = open(path, "rb").read()
    src_off, _old = placed["/etc/init.d/game"]
    assert data[src_off:src_off + len(GROWN)] == GROWN

    sidx_off, sblob = placed["/spk/index/turtles.sidx"]
    recs, _crc, fmt = sidx.parse_records(sblob)
    po = recs["etc/init.d/game"]
    hm, md = sidx.digests(GROWN)
    # Digests AND both stored copies of the size move together.
    for foff, expect in sidx.record_field_writes(po, hm, md, fmt,
                                                 size=len(GROWN)):
        assert data[sidx_off + foff:sidx_off + foff + len(expect)] == expect
    size_fmt, *size_offs = sidx._SIZE_FIELDS[fmt]
    for o in size_offs:
        got = struct.unpack_from(size_fmt, data, sidx_off + po + o)[0]
        assert got == len(GROWN)


def test_resize_replace_shrinks_too(resizable, tmp_path):
    path, placed, calls = resizable
    srcfile = _src(tmp_path, b"tiny")
    with CardImage(path) as c:
        n, refreshed = c.replace_file(1, "/etc/init.d/game", srcfile,
                                      allow_resize=True)
    assert (n, refreshed) == (4, True)
    assert len(calls) == 1
    sidx_off, sblob = placed["/spk/index/turtles.sidx"]
    recs, _crc, fmt = sidx.parse_records(sblob)
    data = open(path, "rb").read()
    size_fmt, size_off = sidx._SIZE_FIELDS[fmt][0], sidx._SIZE_FIELDS[fmt][1]
    assert struct.unpack_from(size_fmt, data,
                              sidx_off + recs["etc/init.d/game"] + size_off)[0] == 4


def test_same_size_never_reaches_the_driver_even_when_resize_allowed(
        resizable, tmp_path):
    """The cheap, dependency-free path stays the default for an exact fit."""
    path, placed, calls = resizable
    srcfile = _src(tmp_path, b"#!/bin/sh\necho HI\n")     # the stock 18 bytes
    with CardImage(path) as c:
        n, refreshed = c.replace_file(1, "/etc/init.d/game", srcfile,
                                      allow_resize=True)
    assert (n, refreshed) == (18, True)
    assert calls == []
    off, _old = placed["/etc/init.d/game"]
    assert open(path, "rb").read()[off:off + 18] == b"#!/bin/sh\necho HI\n"


def test_resize_is_opt_in(resizable, tmp_path):
    """Without allow_resize a mismatch is still refused, and nothing runs."""
    path, _placed, calls = resizable
    srcfile = _src(tmp_path, GROWN)
    before = open(path, "rb").read()
    with CardImage(path) as c:
        with pytest.raises(ValueError, match="size mismatch"):
            c.replace_file(1, "/etc/init.d/game", srcfile)
    assert calls == []
    assert open(path, "rb").read() == before


def test_resize_reports_an_unavailable_platform_before_touching_the_card(
        resizable, tmp_path, monkeypatch):
    path, _placed, calls = resizable
    monkeypatch.setattr(ext4_grow, "available",
                        lambda: (False, "WSL 1 can't mount card images"))
    srcfile = _src(tmp_path, GROWN)
    before = open(path, "rb").read()
    with CardImage(path) as c:
        with pytest.raises(ValueError) as ei:
            c.replace_file(1, "/etc/init.d/game", srcfile, allow_resize=True)
    msg = str(ei.value)
    assert "WSL 1 can't mount card images" in msg
    assert "exactly 18 bytes" in msg          # the way out, in the message
    assert calls == []
    assert open(path, "rb").read() == before


def test_resize_out_of_space_names_the_partition_and_the_sizes(
        resizable, tmp_path, monkeypatch):
    path, _placed, _calls = resizable

    def boom(*a, **k):
        raise ext4_grow.Ext4GrowNoSpace("no room")
    monkeypatch.setattr(ext4_grow, "grow_files", boom)
    srcfile = _src(tmp_path, GROWN)
    with CardImage(path) as c:
        with pytest.raises(ValueError) as ei:
            c.replace_file(1, "/etc/init.d/game", srcfile, allow_resize=True)
    msg = str(ei.value)
    assert "sda2" in msg and str(len(GROWN)) in msg and "18 bytes" in msg


def test_resize_of_an_unindexed_file_reports_no_refresh(resizable, tmp_path):
    path, placed, calls = resizable
    srcfile = _src(tmp_path, b"a much longer readme than before")
    with CardImage(path) as c:
        n, refreshed = c.replace_file(1, "/readme.txt", srcfile,
                                      allow_resize=True)
    assert (n, refreshed) == (32, False)
    assert len(calls) == 1
    off, _old = placed["/readme.txt"]
    assert open(path, "rb").read()[off:off + 32] == \
        b"a much longer readme than before"
