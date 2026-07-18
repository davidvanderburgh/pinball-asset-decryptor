"""Partition Explorer in-place Replace (CardImage.replace_file) + dir_stats.

Uses the shared fake ext4 layer with synthetic disk offsets
(_ext4_fake.materialize_files) so the extent-mapped writes land on real,
checkable bytes in a real card file — including the Spike 2 .sidx record
refresh.
"""
import struct

import pytest

from pinball_decryptor.plugins.stern import sidx
from pinball_decryptor.plugins.stern.explorer import CardImage

from tests._ext4_fake import (SAMPLE_TREE, install_fake_reader,
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
