"""PAD-1648: staged Defaults failed on a build with "file offset 0x60b000 not
allocated".

The Build grows the game program onto the card through debugfs, which leaves a
block of zeros out of the file (a hole).  The Defaults step then patched the
program in place through ``disk_ranges``, which refuses any hole, so the staged
settings never reached the card.  Zeros over a hole need no write; only other
bytes there need the file written whole by the filesystem driver.

``d/hole.bin`` in the tiny fixture has a hole between a 4 KiB head and a 4 KiB
tail (see tests/fixtures/treesync_tiny.py).
"""
import gzip
import os
import struct
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fixtures"))
import treesync_tiny as tiny  # noqa: E402

from pinball_decryptor.plugins.stern import explorer  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "treesync_tiny.ext4.gz")
LBA = 2048


@pytest.fixture
def card_path(tmp_path):
    """The tiny ext4 as partition 1 of an MBR card image."""
    with gzip.open(FIXTURE, "rb") as g:
        fs = g.read()
    mbr = bytearray(512)
    struct.pack_into("<BBBBBBBBII", mbr, 446, 0, 0, 0, 0, 0x83, 0, 0, 0,
                     LBA, len(fs) // 512)
    mbr[510:512] = b"\x55\xaa"
    p = tmp_path / "card.img"
    with open(p, "wb") as f:
        f.write(bytes(mbr) + bytes(LBA * 512 - 512) + fs)
    return str(p)


def _part(card):
    return next(p.index for p in card.partitions() if p.browsable)


def test_an_edit_off_the_hole_goes_in_place(card_path, monkeypatch):
    """His case: the defaults change a few bytes in the program's blocks and
    leave its hole the zeros it reads as."""
    def no_driver(*a, **k):
        raise AssertionError("an in-place edit must not need the driver")
    monkeypatch.setattr(explorer.CardImage, "_resize_file", no_driver)
    want = bytearray(tiny.hole_bytes())
    want[10:14] = b"PADX"            # in the head, which has a block
    with explorer.CardImage(card_path) as c:
        pi = _part(c)
        n, _ref = c.replace_file_bytes(pi, "/d/hole.bin", bytes(want))
    assert n == len(want)
    with explorer.CardImage(card_path) as c:
        r = c.reader(_part(c))
        node = c._resolve(r, "/d/hole.bin")[1]
        assert r.read_file_bytes(node) == bytes(want)
        # the hole is still a hole: the edit didn't need its blocks
        assert len(r.mapped_ranges(node)) == 2


def test_data_in_the_hole_goes_through_the_driver(card_path, monkeypatch):
    """Bytes other than zeros where the file has no block can't be written in
    place: the file is handed to the driver whole, and nothing is written
    before that."""
    seen = {}

    def driver(self, part_index, path, src_path, new_size, log=None):
        with open(src_path, "rb") as f:
            seen["bytes"] = f.read()
        seen["path"] = path
        return new_size, True
    monkeypatch.setattr(explorer.CardImage, "_resize_file", driver)
    before = open(card_path, "rb").read()
    want = bytearray(tiny.hole_bytes())
    hole_at = 4096 + 10              # just past the 4 KiB head
    assert want[hole_at] == 0
    want[hole_at] = 0x5a
    with explorer.CardImage(card_path) as c:
        n, ref = c.replace_file_bytes(_part(c), "/d/hole.bin", bytes(want))
    assert (n, ref) == (len(want), True)
    assert seen == {"bytes": bytes(want), "path": "/d/hole.bin"}
    assert open(card_path, "rb").read() == before


def test_extent_writes_names_the_offset_it_cannot_place(card_path):
    with explorer.CardImage(card_path) as c:
        r = c.reader(_part(c))
        node = c._resolve(r, "/d/hole.bin")[1]
        assert explorer._extent_writes(r, node, 4096, bytes(16)) == []
        with pytest.raises(explorer.HoleWriteError) as e:
            explorer._extent_writes(r, node, 4096, b"\x01" * 16)
    assert e.value.file_off == 4096
    assert "0x1000 not allocated" in str(e.value)
