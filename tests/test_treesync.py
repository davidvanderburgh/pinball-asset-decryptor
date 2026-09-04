"""treesync.py, the pure half of `mkmulticard.py update` - runs on Windows without WSL.

What this file CAN prove: the record's JSON round trip and its determinism, the diff between
two manifests, the room an update needs (including the peak while a replacement's temporary
file coexists with the old one), the executor's ordering and idempotence on an in-memory
filesystem (MemOps) including a simulated crash followed by a re-run that converges, tree
matching by path and by stamp, and the host cache's hit/miss/mismatch rules.

What only `mkmulticard.py selftest` under WSL as root can prove: the loop mount, the real
ext4 through the kernel, e2fsck after every umount, the journal, flock, and the crash drill
that SIGKILLs a writer mid-file.  The reader half (hashing a real ext4 image) is
tests/test_ext4_reader.py.
"""
import hashlib
import json
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "spike2_emu")
sys.path.insert(0, RIG)
import treesync as ts  # noqa: E402


def _tree(files):
    return ts.mem_source_from(files)


SHA = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731


# ------------------------------------------------------------------ the model
def test_manifest_json_round_trips_and_is_deterministic():
    man, _src = _tree({"t/a.bin": (b"aaaa", 0o755, 0, 0, 1_700_000_001), "t/b.txt": b"b",
                       "game": ("symlink", "t/game")})
    d1 = json.dumps(man.to_dict(), sort_keys=True)
    back = ts.TreeManifest.from_dict(json.loads(d1))
    assert back == man
    assert back.files["t/a.bin"].mode == 0o755
    assert json.dumps(back.to_dict(), sort_keys=True) == d1
    assert man.bytes() == 5 and man.count() == 4      # 2 files + 1 symlink + the dir t


def test_card_trees_round_trip_with_format_check():
    man, _ = _tree({"x": b"1"})
    card = ts.CardTrees([ts.ImageTrees(0, "/dev/mmcblk0p3", "", man, {"path": "a", "size": 1, "mtime_ns": 2},
                                       "u" * 32),
                         ts.ImageTrees(1, "/dev/mmcblk0p7:img1", "img1", man, None, None, {"game": "g", "sidx": "s"})],
                        primary={"p1_md5": "m", "p2_tree": "t"}, synced=[7], dirty=[3, 7], layout="multi",
                        version="1.2")
    raw = card.to_json()
    back = ts.CardTrees.from_json(raw)
    assert [i.index for i in back.images] == [0, 1]
    assert back.image(1).bypass == {"game": "g", "sidx": "s"} and back.image(1).sub == "img1"
    assert back.image(0).stamp["mtime_ns"] == 2 and back.image(0).tree == man
    assert back.synced == [7] and back.dirty == [3, 7] and back.primary["p2_tree"] == "t"
    assert back.to_json() == raw
    with pytest.raises(ts.TreesError):
        ts.CardTrees.from_json(b'{"format": 99}')
    with pytest.raises(ts.TreesError):
        ts.CardTrees.from_json(b"not json")


# ------------------------------------------------------------------ the diff
def _ops(changes):
    return [(c.op, c.rel) for c in changes]


def test_identical_trees_diff_to_nothing():
    a, _ = _tree({"t/a": b"x", "t/s": ("symlink", "a")})
    b, _ = _tree({"t/a": b"x", "t/s": ("symlink", "a")})
    assert ts.diff_tree(a, b) == []


def test_content_change_is_a_write_and_mtime_alone_is_nothing():
    a, _ = _tree({"t/a": (b"x", 0o644, 0, 0, 1)})
    b, _ = _tree({"t/a": (b"y", 0o644, 0, 0, 1)})
    assert _ops(ts.diff_tree(a, b)) == [("write", "t/a")]
    c, _ = _tree({"t/a": (b"x", 0o644, 0, 0, 999)})
    assert ts.diff_tree(a, c) == []


def test_mode_or_owner_change_rewrites_the_file():
    a, _ = _tree({"t/a": (b"x", 0o644, 0, 0, 1)})
    b, _ = _tree({"t/a": (b"x", 0o755, 0, 0, 1)})
    c, _ = _tree({"t/a": (b"x", 0o644, 1000, 0, 1)})
    assert _ops(ts.diff_tree(a, b)) == [("write", "t/a")]
    assert _ops(ts.diff_tree(a, c)) == [("write", "t/a")]


def test_symlink_retarget_dir_attr_and_kind_change():
    a, _ = _tree({"t/s": ("symlink", "old"), "t/d": ("dir", 0o755), "t/f": b"file", "t/x": ("symlink", "x")})
    b, _ = _tree({"t/s": ("symlink", "new"), "t/d": ("dir", 0o750), "t/f": ("symlink", "now-a-link"),
                  "t/x": b"now-a-file"})
    ops = _ops(ts.diff_tree(a, b))
    assert ("symlink", "t/s") in ops and ("attr_dir", "t/d") in ops
    assert ops.index(("unlink", "t/f")) < ops.index(("symlink", "t/f"))
    assert ops.index(("unsymlink", "t/x")) < ops.index(("write", "t/x"))


def test_removals_come_last_deep_first_and_creations_shallow_first():
    a, _ = _tree({"t/old/deep/f": b"1", "t/keep": b"k"})
    b, _ = _tree({"t/keep": b"k", "t/new/deeper/g": b"2"})
    ops = _ops(ts.diff_tree(a, b))
    assert ops[:3] == [("mkdir", "t/new"), ("mkdir", "t/new/deeper"), ("write", "t/new/deeper/g")]
    assert ops[3:] == [("unlink", "t/old/deep/f"), ("rmdir", "t/old/deep"), ("rmdir", "t/old")]


def test_a_latin1_name_is_an_ordinary_path():
    name = "t/" + b"caf\xe9".decode("utf-8", "surrogateescape")
    a, _ = _tree({name: b"1"})
    d = json.dumps(a.to_dict(), ensure_ascii=True)
    assert ts.TreeManifest.from_dict(json.loads(d)) == a
    assert _ops(ts.diff_tree(None, a)) == [("mkdir", "t"), ("write", name)]


def test_diff_against_nothing_writes_everything():
    a, _ = _tree({"t/a": b"1", "t/sub/b": b"22", "game": ("symlink", "t/a")})
    ops = _ops(ts.diff_tree(None, a))
    assert ops == [("mkdir", "t"), ("mkdir", "t/sub"), ("write", "t/a"), ("write", "t/sub/b"), ("symlink", "game")]


# ------------------------------------------------------------------ room
def test_room_counts_the_peak_of_a_replacement_and_frees_only_after():
    old, _ = _tree({"t/v.mp4": b"o" * 700})
    new, _ = _tree({"t/v.mp4": b"n" * 720})
    ch = ts.diff_tree(old, new)
    need, peak = ts.room_needed(ch, old, new, margin=64)
    assert need == 720 - 700 + 64
    assert peak == 720 + 64            # the old 700 still exist while the new 720 are written
    # a partition with 600 free must be refused by the PLAN, never fail mid-write
    assert peak > 600
    old2, _ = _tree({"t/big": b"b" * 4000, "t/keep": b"k"})
    new2, _ = _tree({"t/keep": b"k", "t/added": b"a" * 200})
    need2, peak2 = ts.room_needed(ts.diff_tree(old2, new2), old2, new2, margin=0)
    assert need2 == 200 - 4000 and peak2 == 200


# ------------------------------------------------------------------ the executor
def _apply(ops, prefix, old, new, src, **kw):
    return ts.apply_changes(ops, prefix, ts.diff_tree(old, new), new, src, **kw)


def test_apply_writes_a_tree_from_nothing_and_a_rerun_is_a_no_op():
    new, src = _tree({"t/a.bin": (b"A" * 10, 0o755, 0, 0, 5), "t/sub/b": b"bb", "game": ("symlink", "t/a.bin"),
                      "t/e": b""})
    ops = ts.MemOps()
    ops.mkdir("img1", 0o755, 0, 0)
    stats = _apply(ops, "img1", None, new, src)
    assert stats == {"written": 3, "bytes": 12, "removed": 0}
    assert ops.manifest("img1") == new
    assert ops.read("img1/t/a.bin") == b"A" * 10 and ops.lstat("img1/t/a.bin")["mode"] == 0o755
    assert ops.lstat("img1/game")["target"] == "t/a.bin"
    assert not any(ts.is_tmp(r) for r, _ in ops.walk_files("img1"))
    before = ops.ops
    assert _apply(ops, "img1", new, new, src) == {"written": 0, "bytes": 0, "removed": 0}
    assert ops.ops == before


def test_apply_replaces_removes_and_never_writes_in_place():
    old, src0 = _tree({"t/v.mp4": b"old" * 100, "t/gone": b"g", "t/d/x": b"x"})
    ops = ts.MemOps()
    ops.mkdir("img1", 0o755, 0, 0)
    _apply(ops, "img1", None, old, src0)
    ino_before = ops.lstat("img1/t/v.mp4")["ino"]
    new, src = _tree({"t/v.mp4": b"new" * 120, "t/added": b"a"})
    stats = _apply(ops, "img1", old, new, src)
    assert stats["written"] == 2 and stats["removed"] == 3
    assert ops.manifest("img1") == new
    assert ops.lstat("img1/t/v.mp4")["ino"] != ino_before, "a replacement is a new inode, never an overwrite"
    writes = [line for line in ops.log if line.startswith("write ")]
    assert all(ts.is_tmp(line.split(" ", 1)[1]) for line in writes), writes
    # adds land before the first removal
    first_removal = next(i for i, line in enumerate(ops.log) if line.startswith("unlink img1/t/gone"))
    last_write = max(i for i, line in enumerate(ops.log) if line.startswith("rename "))
    assert last_write < first_removal


def test_a_crash_mid_update_leaves_the_old_files_and_a_rerun_converges():
    old, src0 = _tree({"t/a": b"a" * 50, "t/b": b"b" * 50, "t/gone": b"g"})
    new, src = _tree({"t/a": b"A" * 60, "t/b": b"B" * 60, "t/c": b"c" * 10})
    ops = ts.MemOps()
    ops.mkdir("img1", 0o755, 0, 0)
    _apply(ops, "img1", None, old, src0)
    # crash after the first tmp write (before its rename)
    ops.abort_after = ops.ops + 1
    with pytest.raises(RuntimeError):
        _apply(ops, "img1", old, new, src)
    assert ops.read("img1/t/a") == b"a" * 50 and ops.read("img1/t/gone") == b"g", "nothing old was lost"
    assert any(ts.is_tmp(r) for r, _ in ops.walk_files("img1")), "a temporary file was left"
    ops.abort_after = None
    assert ts.sweep_tmp(ops, "img1") == 1
    _apply(ops, "img1", old, new, src)
    assert ops.manifest("img1") == new
    # and once more, from the recorded state, changes nothing
    n = ops.ops
    _apply(ops, "img1", new, new, src)
    assert ops.ops == n


def test_enospc_surfaces_from_the_write_and_leaves_the_old_file():
    old, src0 = _tree({"t/v": b"o" * 100})
    new, src = _tree({"t/v": b"n" * 300})
    ops = ts.MemOps(free=350)
    ops.mkdir("img1", 0o755, 0, 0)
    _apply(ops, "img1", None, old, src0)
    with pytest.raises(OSError):
        _apply(ops, "img1", old, new, src)
    assert ops.read("img1/t/v") == b"o" * 100


def test_tree_actions_remove_first_then_rename_in_two_phases_then_create():
    ops = ts.MemOps()
    for sub, payload in (("img1", b"one"), ("img2", b"two"), ("img3", b"three")):
        ops.mkdir(sub, 0o755, 0, 0)
        ops.write_stream(sub + "/f", [payload], 0o644, 0, 0, 1)
    actions = [ts.TreeAction(1, "p7:img1", "img2", "img1", "rename"),
               ts.TreeAction(2, "p7:img2", "img1", "img2", "rename"),
               ts.TreeAction(3, "p7:img3", None, "img3", "new"),
               ts.TreeAction(9, "p7:img3", "img3", None, "remove")]
    done = ts.apply_tree_actions(ops, actions, tmp_tag="t")
    assert done[0] == ("remove", "img3", None)
    assert ops.read("img1/f") == b"two" and ops.read("img2/f") == b"one"
    assert ops.exists("img3") and ops.listdir("img3") == []
    assert not any(n.startswith(".rename.") for n in ops.listdir(""))
    assert ops.log.index("unlink img3/f") < ops.log.index("rename img2 -> .rename.t.img2")


def test_match_trees_by_path_then_stamp_else_new_and_unclaimed_removed():
    man, _ = _tree({"x": b"1"})
    card = ts.CardTrees([
        ts.ImageTrees(0, "/dev/mmcblk0p3", "", man, {"path": "/p/primary.raw", "size": 10, "mtime_ns": 1}),
        ts.ImageTrees(1, "/dev/mmcblk0p7:img1", "img1", man, {"path": "/p/a.raw", "size": 20, "mtime_ns": 2}),
        ts.ImageTrees(2, "/dev/mmcblk0p7:img2", "img2", man, {"path": "/p/b.raw", "size": 30, "mtime_ns": 3}),
    ])
    sub = lambda i: "" if i == 0 else "img%d" % i  # noqa: E731
    # the same list, b's card copied to another path with the same stamp, a moved to position 2
    new = [(0, "/dev/mmcblk0p3", {"path": "/p/primary.raw", "size": 10, "mtime_ns": 1}),
           (1, "/dev/mmcblk0p7:img1", {"path": "/q/b-copy.raw", "size": 30, "mtime_ns": 3}),
           (2, "/dev/mmcblk0p7:img2", {"path": "/p/a.raw", "size": 21, "mtime_ns": 9}),
           (3, "/dev/mmcblk0p7:img3", {"path": "/p/c.raw", "size": 40, "mtime_ns": 4})]
    acts = ts.match_trees(card, new, sub)
    assert [(a.index, a.old_sub, a.new_sub, a.action) for a in acts] == [
        (0, "", "", "keep"), (1, "img2", "img1", "rename"), (2, "img1", "img2", "rename"), (3, None, "img3", "new")]
    fewer = [(0, "/dev/mmcblk0p3", new[0][2]),
             (1, "/dev/mmcblk0p7:img1", {"path": "/p/b.raw", "size": 30, "mtime_ns": 3})]
    acts = ts.match_trees(card, fewer, sub)
    assert [(a.index, a.old_sub, a.new_sub, a.action) for a in acts] == [
        (0, "", "", "keep"), (1, "img2", "img1", "rename"), (1, "img1", None, "remove")]


# ------------------------------------------------------------------ the cache
def test_cache_hit_miss_and_mismatch(tmp_path, monkeypatch):
    monkeypatch.setenv(ts.CACHE_ENV, str(tmp_path / "cache"))
    man, _ = _tree({"t/a": b"1"})
    stamp = {"path": "/x/card.raw", "size": 100, "mtime_ns": 5}
    src = ts.SourceManifest(man, stamp, "u" * 32, "")
    p = ts.store_cached(src)
    assert os.path.isfile(p) and p.startswith(str(tmp_path / "cache"))
    hit = ts.load_cached(stamp, "u" * 32)
    assert hit is not None and hit.tree == man
    assert ts.load_cached(stamp, "v" * 32) is None, "another partition"
    assert ts.load_cached({"path": "/y", "size": 100, "mtime_ns": 6}, "u" * 32) is None, "a moved stamp"
    copy = {"path": "/elsewhere/copy.raw", "size": 100, "mtime_ns": 5}
    assert ts.load_cached(copy, "u" * 32) is not None, "the path is not the key"
    assert ts.load_cached(stamp, "u" * 32, sub="img1") is None, "a subtree has its own entry"
    with open(p, "wb") as f:
        f.write(b"{corrupt")
    assert ts.load_cached(stamp, "u" * 32) is None


def test_stamp_key_and_candidates(tmp_path, monkeypatch):
    k = ts.stamp_key({"size": 7861174272, "mtime_ns": 1725000000000000000}, "abcdef0123456789abcdef", "img2")
    assert k == "7861174272-1725000000000000000-abcdef0123456789-img2"
    monkeypatch.setenv(ts.CACHE_ENV, str(tmp_path / "c"))
    cands = ts.cache_dir_candidates(str(tmp_path / "flag"))
    assert cands[0] == str(tmp_path / "flag") and cands[1] == str(tmp_path / "c")
    assert cands[-1].endswith(ts.CACHE_DIRNAME)
    assert len(cands) == len(set(cands))


def test_source_manifest_reads_the_fixture_and_caches_it(tmp_path, monkeypatch):
    """The real reader over the tiny ext4 fixture: hashed once, cached, a moved stamp re-hashed."""
    import gzip
    fx = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "treesync_tiny.ext4.gz")
    img = tmp_path / "tiny.img"
    with gzip.open(fx, "rb") as g, open(img, "wb") as f:
        f.write(g.read())
    monkeypatch.setenv(ts.CACHE_ENV, str(tmp_path / "cache"))
    size = os.path.getsize(img)
    man, how = ts.source_manifest(str(img), 0, size)
    assert how == "hashed" and "d/a.bin" in man.tree.files and man.tree.inodes["d/a.bin"] > 2
    assert man.tree.files["d/a.bin"].sha256 == man.tree.files["d/a_mode.bin"].sha256
    assert man.tree.files["d/a.bin"].mode == 0o644 and man.tree.files["d/a_mode.bin"].mode == 0o755
    assert man.tree.symlinks["d/link_slow"].target == "x" * 70
    assert man.tree.dirs["d/sub"].mode == 0o750 and man.tree.files["d/uid1000.txt"].uid == 1000
    assert "lost+found" not in man.tree.dirs
    man2, how2 = ts.source_manifest(str(img), 0, size)
    assert how2 == "cached" and man2.tree == man.tree and man2.tree.inodes == {}
    os.utime(img, ns=(1, 2))
    _m3, how3 = ts.source_manifest(str(img), 0, size)
    assert how3 == "hashed"
    src = ts.ReaderSource
    assert src is not None
