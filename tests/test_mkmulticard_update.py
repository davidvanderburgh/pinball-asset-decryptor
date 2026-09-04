"""mkmulticard.py's in-place layer (item 93) - the parts that run on Windows without WSL.

The loop mount, the lock, the p2 primitive and the grow need root under WSL and are proven
by `mkmulticard.py selftest` (parts 5+); what is here is their pure logic: the losetup
listing parser, the stale-loop rules, the debugfs script for a p2 write, the Plan a grow
rewrites the tables from, DirOps' file operations on a plain directory, and trees.json
read/write through the fake p2.
"""
import json
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "spike2_emu")
pytestmark = pytest.mark.skipif(not os.path.isfile(os.path.join(RIG, "mkmulticard.py")), reason="no rig")


@pytest.fixture
def mk():
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    import mkmulticard
    return mkmulticard


@pytest.fixture
def ts():
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    import treesync
    return treesync


def test_parse_losetup_j_reads_device_and_offset(mk):
    text = ("/dev/loop0: [2049]:1234 (/mnt/d/Pinball/x.raw), offset 364904448\n"
            "/dev/loop12: [2049]:1234 (/mnt/d/Pinball/x.raw)\n"
            "garbage line\n")
    assert mk.parse_losetup_j(text) == [("/dev/loop0", 364904448), ("/dev/loop12", 0)]
    assert mk.parse_losetup_j("") == []


def test_select_write_commands_rm_write_then_attrs(mk):
    cmds = mk.select_write_commands([("/tmp/stage/trees.json", "trees.json")], remove=["updating.json"])
    assert cmds[0] == 'rm "/usr/local/codeselect/trees.json"'
    assert cmds[1] == 'rm "/usr/local/codeselect/updating.json"'
    assert cmds[2] == 'write "/tmp/stage/trees.json" "/usr/local/codeselect/trees.json"'
    assert cmds[3:] == ['set_inode_field "/usr/local/codeselect/trees.json" mode 0100644',
                        'set_inode_field "/usr/local/codeselect/trees.json" uid 0',
                        'set_inode_field "/usr/local/codeselect/trees.json" gid 0']


def test_loop_available_is_honest_on_this_host(mk):
    ok, why = mk.loop_available()
    if os.name != "posix":
        assert not ok and "Linux" in why
    else:
        assert isinstance(ok, bool) and why


def test_lock_held_is_false_without_a_lock_file(mk, tmp_path):
    card = tmp_path / "card.raw"
    card.write_bytes(b"x")
    assert mk.lock_held(str(card)) is False


def test_dirops_writes_renames_and_walks_a_plain_directory(mk, tmp_path):
    ops = mk.DirOps(str(tmp_path))
    ops.mkdir("img1", 0o755, 0, 0)
    ops.write_stream("img1/a.tmp", [b"ab", b"cd"], 0o644, 0, 0, 1_700_000_000)
    ops.rename("img1/a.tmp", "img1/a")
    st = ops.lstat("img1/a")
    assert st["kind"] == "file" and st["size"] == 4 and st["mtime"] == 1_700_000_000
    assert ops.lstat("img1")["kind"] == "dir" and ops.lstat("nope") is None
    assert [r for r, _s in ops.walk_files("img1")] == ["img1/a"]
    assert ops.free_bytes() > 0
    ops.rmtree("img1")
    assert not ops.exists("img1")


def test_plan_with_p7_sectors_rewrites_only_the_last_partition(mk, monkeypatch, tmp_path):
    """Two synthetic 8G-shaped cards -> a multi plan; the grown plan keeps p1..p6 and moves
    only p7's count and the image end."""
    srcs = [mk.make_synthetic_card(str(tmp_path / ("S%d.img" % i)), "S%d" % i, 0x0A0B0C00 + i) for i in range(3)]
    plan = mk.make_plan(srcs[0], srcs[1:], "multi", multi_sectors=4096, multi_subdirs=["img1", "img2"],
                        multi_src=srcs[1])
    card = str(tmp_path / "multi.img")
    mk.build_image(plan, card)
    monkeypatch.setattr(mk, "multi_subdirs_on", lambda c, part_num=7: ["img1", "img2"])
    plan0 = mk.plan_from_card(card)
    grown = mk.plan_with_p7_sectors(card, plan0.multi_part.count + 4096)
    assert grown.multi_part.count == plan0.multi_part.count + 4096
    assert grown.multi_part.start == plan0.multi_part.start
    assert [p.start for p in grown.prims + grown.logs[:2]] == [p.start for p in plan0.prims + plan0.logs[:2]]
    assert grown.total == plan0.total + 4096
    assert grown.multi_subdirs == ["img1", "img2"]


def test_read_trees_reads_the_record_off_p2(mk, ts, monkeypatch):
    man, _ = ts.mem_source_from({"turtles_pro/game": b"elf"})
    trees = ts.CardTrees([ts.ImageTrees(0, "/dev/mmcblk0p3", "", man, {"path": "a", "size": 1, "mtime_ns": 2})],
                         layout="parts", version="1.2")
    monkeypatch.setattr(mk, "select_ref", lambda card: "ref")
    monkeypatch.setattr(mk, "read_select_file",
                        lambda ref, name: trees.to_json() if name == mk.TREES_MANIFEST else None)
    back = mk.read_trees("card.raw")
    assert back is not None and back.image(0).tree == man and back.layout == "parts"
    monkeypatch.setattr(mk, "read_select_file", lambda ref, name: None)
    assert mk.read_trees("card.raw") is None
    monkeypatch.setattr(mk, "read_select_file", lambda ref, name: b"{}")
    with pytest.raises(mk.Refused):
        mk.read_trees("card.raw")


def test_trees_manifest_is_a_known_sidecar(mk):
    assert mk.TREES_MANIFEST in mk.SIDECAR_MANIFESTS
    assert json.loads(json.dumps({"x": mk.TREES_MANIFEST}))["x"] == "trees.json"
