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


# ------------------------------------------------------------------ update: the pure parts
def test_update_rows_are_the_pinned_contract(mk, capsys):
    u = {"card": "/mnt/d/x.raw", "layout": "multi", "dirty": [7], "unrecorded": False,
         "sources": [(0, "/dev/mmcblk0p3", "unchanged", "a.raw"), (1, "/dev/mmcblk0p7:img1", "rehashed", "b.raw"),
                     (2, "/dev/mmcblk0p7:img2", "removed", None)],
         "files": [(0, "/dev/mmcblk0p3", 0, 0, "keep", "a.raw"),
                   (1, "/dev/mmcblk0p7:img1", 1, 65011712, "sync", "b.raw"),
                   (2, "/dev/mmcblk0p7:img2", 1385, 0, "remove", None)],
         "inject": True, "size": 65011712, "peak": 65011712 + (64 << 20), "free_after": 4100000000,
         "grow": (7, 1 << 30), "fits": True, "notes": ["image 2 removed"]}
    mk._print_update_rows(u)
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "update-card /mnt/d/x.raw layout multi dirty",
        "update-source 0 /dev/mmcblk0p3 unchanged a.raw",
        "update-source 1 /dev/mmcblk0p7:img1 rehashed b.raw",
        "update-source 2 /dev/mmcblk0p7:img2 removed -",
        "update-files 0 /dev/mmcblk0p3 0 0 keep a.raw",
        "update-files 1 /dev/mmcblk0p7:img1 1 65011712 sync b.raw",
        "update-files 2 /dev/mmcblk0p7:img2 1385 0 remove -",
        "update-inject yes",
        "update-size 65011712",
        "update-peak %d" % (65011712 + (64 << 20)),
        "update-free 4100000000",
        "update-grow p7 1073741824",
        "update-fits YES",
        "update-note image 2 removed",
    ]
    u["grow"] = None
    u["dirty"] = []
    u["unrecorded"] = True
    mk._print_update_rows(u)
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "update-card /mnt/d/x.raw layout multi unrecorded" and "update-grow none" in out


def test_bypass_tree_bytes_leaves_a_game_without_a_validator_alone(mk):
    elf = b"\x7fELF" + bytes(64)
    state, new_elf, new_sidx, notes = mk.bypass_tree_bytes(elf, b"not a manifest\n", "t/game", "t")
    assert state in ("absent", "unlocated") and new_elf is None and new_sidx is None
    assert notes and "t/game" in notes[0]


def test_update_refuses_a_directory_a_missing_card_and_a_host_without_loop(mk, tmp_path, capsys):
    rc = mk.main(["update", "--card", str(tmp_path)])
    assert rc == 2 and "not a regular file" in capsys.readouterr().err
    rc = mk.main(["update", "--card", str(tmp_path / "nope.raw")])
    assert rc == 2 and "does not exist" in capsys.readouterr().err
    card = mk.make_synthetic_card(str(tmp_path / "A.img"), "A", 0x0A0A0A0A)
    if os.name != "posix":
        rc = mk.main(["update", "--card", card])
        assert rc == 2 and "loop mount" in capsys.readouterr().err


def test_update_dry_run_needs_no_root_but_a_readable_card(mk, tmp_path, capsys, monkeypatch):
    """A dry-run never asks for root or the lock; on a host without debugfs it stops at the
    first read with the tool's own sentence, never a traceback."""
    card = mk.make_synthetic_card(str(tmp_path / "A.img"), "A", 0x0A0A0A0A)
    monkeypatch.setattr(mk, "loop_available", lambda: (False, "not root"))
    rc = mk.main(["update", "--card", card, "--dry-run"])
    err = capsys.readouterr().err
    assert rc == 2 and "[card] error:" in err and "loop mount" not in err


def test_p2_skip_and_slack_constants(mk):
    assert mk.P2_SKIP == ("usr/local/codeselect", "etc/init.d/game")
    assert mk.UPDATE_SLACK == 0.10 and mk.UPDATE_SLACK_BYTES == 64 << 20


def test_selector_manifests_carry_trees_json_through(mk, ts, tmp_path):
    from tests.test_mkmulticard import _two_image_plan, _menu_conf
    plan = _two_image_plan(mk)
    conf = _menu_conf(mk, plan)
    man, _ = ts.mem_source_from({"t/game": b"g"})
    rec = ts.CardTrees([ts.ImageTrees(0, "/dev/mmcblk0p3", "", man)], layout="parts", version="1.2")
    out = mk.selector_manifests(plan, conf, None, None, None, None, trees=rec)
    assert out[mk.TREES_MANIFEST] == rec.to_json()
    out = mk.selector_manifests(plan, conf, None, None, None, None, existing_trees=b"{carried}")
    assert out[mk.TREES_MANIFEST] == b"{carried}"
    out = mk.selector_manifests(plan, conf, None, None, None, None)
    assert mk.TREES_MANIFEST not in out


# ---- item 98: putting the stock game back where the tool patched it -------------------
def test_restore_changes_names_the_patched_game_and_sidx_only(mk):
    ts = mk._treesync()
    tree = ts.TreeManifest({"t/game": ts.FileRec("a" * 64, 100, 0o755, 0, 0, 1),
                            "spk/index/t.sidx": ts.FileRec("b" * 64, 20, 0o644, 0, 0, 1),
                            "t/other": ts.FileRec("c" * 64, 5, 0o644, 0, 0, 1)})
    patched = ts.ImageTrees(0, "/dev/mmcblk0p3", "", tree, None, None,
                            {"game_path": "t/game", "sidx_path": "spk/index/t.sidx", "game": "d" * 64, "sidx": "e" * 64})
    assert [(c.op, c.rel, c.size) for c in mk.restore_changes(patched, tree, [])] == [
        ("write", "t/game", 100), ("write", "spk/index/t.sidx", 20)]
    # already written by the diff -> not twice; already bypassed in the SOURCE (no digest
    # recorded) -> nothing to put back; no record -> nothing
    assert [c.rel for c in mk.restore_changes(patched, tree, [ts.Change("write", "t/game", 100)])] == ["spk/index/t.sidx"]
    carried = ts.ImageTrees(0, "/dev/mmcblk0p3", "", tree, None, None, {"game_path": "t/game", "sidx_path": None})
    assert mk.restore_changes(carried, tree, []) == []
    assert mk.restore_changes(None, tree, []) == []
    # a build's raw bypass is not in the record: the card's own tree says 'bypassed', and
    # then the game and every spk/index .sidx come back from the source
    live = ("bypassed", "t", "t/game")
    assert [c.rel for c in mk.restore_changes(None, tree, [], live)] == ["t/game", "spk/index/t.sidx"]
    assert mk.restore_changes(None, tree, [], ("armed", "t", "t/game")) == []
    assert mk.restore_changes(None, tree, [], ("absent", "t", "t/game")) == []


def test_update_refuses_bypass_and_restore_together(mk, tmp_path):
    card = tmp_path / "x.raw"
    card.write_bytes(bytes(1024))
    assert mk.main(["update", "--card", str(card), "--bypass-validation", "--restore-validation", "--dry-run"]) == 2


def test_a_machine_volume_conf_renders_back_like_for_like(mk):
    """update compares the card's own images.conf with a fresh render: a card that follows the
    machine's volume reads back volume='machine', which the render must take as the
    machine_volume line and not as a number (it refused every update of such a card)."""
    text = mk.render_images_conf(["/dev/mmcblk0p3", "/dev/mmcblk0p7"], ["A", "B"], ["", ""], 0, 15, None,
                                 [], "move.wav", "confirm.wav", None, None,
                                 machine_volume={"store": "/data/nv/t/NVM", "key": "a" * 40, "default": 18})
    conf = mk.parse_images_conf(text)
    assert conf["volume"] == "machine" and conf["machine_volume"]["default"] == 18
    again = mk.render_images_conf_text(conf)
    assert "volume=machine" in again and mk.parse_images_conf(again) == conf
