"""The pure-Python ext4 reader against a real (tiny) ext4 image - item 93's additions.

tests/fixtures/treesync_tiny.ext4.gz is a 4 MiB ext4 made by make_treesync_tiny.sh (root,
under WSL/Linux) from the tree tests/fixtures/treesync_tiny.py describes; that module also
recomputes what a reader MUST see (sizes, sha256 of the bytes a mounted filesystem would
serve, symlink targets), so nothing here is a hand-typed expectation.  What the fixture
carries that a synthetic card cannot: an extent tree with a depth-1 index block, an
UNWRITTEN extent (fallocate), a hole, a fast and a slow symlink, a uid-1000 file, a
directory mode, and a file name that is not UTF-8.
"""
import gzip
import hashlib
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fixtures"))
import treesync_tiny as tiny  # noqa: E402

from pinball_decryptor.plugins.stern import ext4  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "treesync_tiny.ext4.gz")


@pytest.fixture(scope="module")
def image(tmp_path_factory):
    p = tmp_path_factory.mktemp("ext4") / "tiny.img"
    with gzip.open(FIXTURE, "rb") as g, open(p, "wb") as f:
        f.write(g.read())
    return p


@pytest.fixture
def reader(image):
    with open(image, "rb") as f:
        yield ext4.Ext4Reader(f, 0, os.path.getsize(image))


def _tree(reader):
    return {rel: (kind, ino, node) for rel, kind, ino, node in reader.iter_tree(2)}


def test_iter_tree_lists_every_entry_sorted_with_its_kind(reader):
    got = _tree(reader)
    want = tiny.expected()
    assert set(got) == set(want), (set(got) ^ set(want))
    for rel, (kind, _size, _sha, _target) in want.items():
        assert got[rel][0] == kind, rel
    assert "lost+found" not in got                      # skipped at the root by default
    rels = [rel for rel, _k, _i, _n in reader.iter_tree(2)]
    assert rels.index("d") < rels.index("d/a.bin") < rels.index("d/sub") < rels.index("d/sub/one.txt")
    top = [r for r in rels if r.startswith("d/") and r.count("/") == 1]
    assert top == sorted(top)


def test_iter_tree_can_keep_lost_and_found(reader):
    rels = {rel for rel, _k, _i, _n in reader.iter_tree(2, skip=())}
    assert "lost+found" in rels


def test_read_inode_carries_ownership_links_and_times(reader):
    got = _tree(reader)
    node = got["d/uid1000.txt"][2]
    assert (node["uid"], node["gid"]) == (1000, 1000)
    assert got["d/a.bin"][2]["uid"] == 0 and got["d/a.bin"][2]["gid"] == 0
    for rel in ("d/a.bin", "d/link_fast", "d/sub/one.txt"):
        assert got[rel][2]["links"] == 1, rel
        assert got[rel][2]["mtime"] > 1_600_000_000, rel
    assert got["d/sub"][2]["mode"] & 0o777 == 0o750
    assert got["d/a_mode.bin"][2]["mode"] & 0o777 == 0o755
    assert got["d/a.bin"][2]["mode"] & 0o777 == 0o644
    assert got["d"][2]["links"] == 3                    # . , .. from sub, and the root's entry


@pytest.mark.parametrize("chunk", [1 << 20, 64 << 10, 4096 + 1])
def test_read_file_chunks_serves_what_a_mount_would(reader, chunk):
    got = _tree(reader)
    for rel, (kind, size, sha, _t) in tiny.expected().items():
        if kind != "file":
            continue
        node = got[rel][2]
        h = hashlib.sha256()
        pos = 0
        for off, data in reader.read_file_chunks(node, chunk=chunk):
            assert off == pos, (rel, off, pos)
            assert 0 < len(data) <= chunk
            h.update(data)
            pos += len(data)
        assert pos == size == node["size"], rel
        assert h.hexdigest() == sha, rel


def test_holes_and_unwritten_extents_read_as_zeros(reader):
    got = _tree(reader)
    hole = b"".join(d for _o, d in reader.read_file_chunks(got["d/hole.bin"][2]))
    assert hole[:4096] == tiny.HOLE_HEAD and hole[tiny.HOLE_TAIL_AT:] == tiny.HOLE_TAIL
    assert hole[4096:tiny.HOLE_TAIL_AT] == bytes(tiny.HOLE_TAIL_AT - 4096)
    un = b"".join(d for _o, d in reader.read_file_chunks(got["d/uninit.bin"][2]))
    assert un[:4096] == tiny.UNINIT_HEAD and un[4096:] == bytes(tiny.UNINIT_LEN - 4096)
    flagged = reader._runs_flagged(got["d/uninit.bin"][2])
    assert any(u for (_l, _p, _c, u) in flagged), flagged
    assert not any(u for (_l, _p, _c, u) in reader._runs_flagged(got["d/a.bin"][2]))
    # the legacy 3-tuple view is unchanged in shape and still covers the unwritten blocks
    legacy = reader._runs(got["d/uninit.bin"][2])
    assert [r[:3] for r in flagged] == legacy


def test_the_multi_extent_file_walks_an_index_block(reader):
    got = _tree(reader)
    runs = reader._runs(got["d/multi.bin"][2])
    assert len(runs) >= 3, runs
    assert sum(c for (_l, _p, c) in runs) * reader.block_size >= tiny.MULTI_LEN


def test_read_symlink_fast_and_slow(reader):
    got = _tree(reader)
    fast = got["d/link_fast"][2]
    slow = got["d/link_slow"][2]
    assert reader.read_symlink(fast) == tiny.FAST_TARGET
    assert reader.read_symlink(slow) == tiny.SLOW_TARGET
    assert fast["blocks_lo"] == 0 and slow["blocks_lo"] > 0
    with pytest.raises(ext4.Ext4Error):
        reader.read_symlink(got["d/a.bin"][2])


def test_a_name_that_is_not_utf8_survives_the_walk(reader):
    got = _tree(reader)
    rel = "d/" + tiny.LATIN1_NAME.decode("utf-8", "surrogateescape")
    assert rel in got
    assert rel.split("/", 1)[1].encode("utf-8", "surrogateescape") == tiny.LATIN1_NAME
    d = got["d"][2]
    legacy = [n.encode("utf-8", "surrogateescape") for n, _c, _t in reader._iter_dir(d)]
    assert tiny.LATIN1_NAME not in legacy, "the legacy walk still skips it"
    assert any(n == tiny.LATIN1_NAME for n, _c, _t in reader._iter_dir_raw(d))


def test_uuid_and_feature_words(reader):
    u = reader.uuid()
    assert len(u) == 32 and int(u, 16) != 0
    words = reader.feature_words()
    assert len(words) == 6 and all(isinstance(w, int) for w in words)
    assert words[1] & 0x40, "INCOMPAT_EXTENTS is on for every ext4"
    assert words[3:] == (0, 0, 0), "the fixture has no journal"


def test_legacy_readers_are_unchanged(reader):
    """iter_regular_files / read_file_bytes / disk_ranges keep their contract."""
    files = {p: (i, n) for p, i, n in reader.iter_regular_files(2)}
    assert "/d/a.bin" in files
    ino, node = files["/d/a.bin"]
    assert reader.read_file_bytes(node) == tiny.a_bytes()
    rng = reader.disk_ranges(node, 0, 16)
    assert rng and rng[0][1] == 16
