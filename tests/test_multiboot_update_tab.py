"""The Multi-boot tab's in-place UPDATE (item 93) - the pure layer and the decision.

The tool's contract is pinned in tools/spike2_emu/mkmulticard.py (`update --dry-run` rows,
`plan`'s `image-size free` row, inspect's `trees` block); these tests hold the tab to it: the
argv it builds (a root step is a callable resolved on the worker), what it parses, what the
size strip draws, and what the Build / flash modal offers for a loaded card whose sources
moved on disk.  Everything runs without WSL; the helpers are test_multiboot_tab.py's.
"""
import copy
import os

import pytest

from pinball_decryptor.gui import multiboot_tab
from pinball_decryptor.gui.multiboot_tab import (
    DRY_RUN, INSPECT_JSON, build_commands, card_size_view, measure_commands, parse_plan,
    parse_update, root_command, trees_from_inspect, update_args, update_commands,
    wsl_shell_root)

from tests.test_multiboot_tab import (  # noqa: E402
    _form, _line, _loaded, _rich_report, _tool_words, _win, _write_action)


@pytest.fixture(autouse=True)
def _no_wsl_home_probe(monkeypatch):
    monkeypatch.setattr(multiboot_tab, "wsl_home", lambda: "/home/x")


# ------------------------------------------------------------------ argv
def test_update_argv_is_the_menu_flags_on_the_loaded_card(monkeypatch, tmp_path):
    _win(monkeypatch)
    form = _form(tmp_path, 2)
    card = str(tmp_path / "card.raw")
    words = _tool_words(root_command(update_args(form, card), cwd="/mnt/c/repo"))
    assert words[:4] == ["tools/spike2_emu/mkmulticard.py", "update", "--card", multiboot_tab.wsl(card)]
    assert "--primary" in words and "--extra" in words
    for flag in ("--selector-dir", "--titles", "--subtitles", "--timeout", "--default", "--volume",
                 "--cache-dir", "--bypass-validation"):
        assert flag in words, flag
    assert "--dry-run" not in words and "--expect-bytes" not in words
    assert "--out" not in words and "--layout" not in words and "--force" not in words
    words = _tool_words(multiboot_tab.wsl_command(update_args(form, card, dry_run=True, expect_bytes=123),
                                                  cwd="/mnt/c/repo"))
    assert "--dry-run" in words and words[words.index("--expect-bytes") + 1] == "123"
    cache = words[words.index("--cache-dir") + 1]
    assert cache.endswith("/pinball_spike2_multiboot") and not cache.startswith("~")


def test_build_and_update_run_as_root_with_the_desktop_home(monkeypatch, tmp_path):
    _win(monkeypatch)
    form = _form(tmp_path, 2)
    step = dict(build_commands(form, cwd="/mnt/c/repo"))["build"]
    assert callable(step)
    argv = step({})
    assert argv[:8] == ["wsl.exe", "-u", "root", "-e", "env", "HOME=/home/x", "bash", "-lc"]
    assert _line(argv).startswith("cd /mnt/c/repo && python3 tools/spike2_emu/mkmulticard.py build")
    cmds = update_commands(form, str(tmp_path / "c.raw"), cwd="/mnt/c/repo")
    # the selector first: update re-injects the menu program (PAD-105)
    assert [label for label, _ in cmds] == ["selector", "update", "inspect", INSPECT_JSON]
    assert callable(dict(cmds)["update"]) and not callable(dict(cmds)["inspect"])
    cmds = update_commands(form, str(tmp_path / "c.raw"), media_dir=str(tmp_path), prepare=True, cwd="/mnt/c/repo")
    assert [label for label, _ in cmds] == ["selector", "prepare", "update", "inspect", INSPECT_JSON]
    assert wsl_shell_root("echo hi") == ["wsl.exe", "-u", "root", "-e", "bash", "-lc", "echo hi"]
    monkeypatch.setattr(multiboot_tab.sys, "platform", "linux")
    assert wsl_shell_root("echo hi", "/home/x") == ["sudo", "-n", "bash", "-lc", "echo hi"]


def test_a_root_step_without_a_home_fails_with_a_sentence(monkeypatch, tmp_path):
    _win(monkeypatch)
    monkeypatch.setattr(multiboot_tab, "wsl_home", lambda: None)
    step = root_command(["x.py", "build"], cwd="/mnt/c/repo")
    with pytest.raises(RuntimeError) as e:
        step({})
    assert "WSL home" in str(e.value)


def test_measure_commands_add_the_dry_run_only_for_a_loaded_card(monkeypatch, tmp_path):
    _win(monkeypatch)
    form = _form(tmp_path, 2)
    assert [label for label, _ in measure_commands(form, None, cwd="/mnt/c/repo")] == ["plan"]
    cmds = measure_commands(form, str(tmp_path / "c.raw"), cwd="/mnt/c/repo")
    assert [label for label, _ in cmds] == ["plan", DRY_RUN]
    assert not callable(cmds[1][1]) and "--dry-run" in _tool_words(cmds[1][1])


# ------------------------------------------------------------------ parsing
PLAN_TEXT = (
    "image-size 0 /dev/mmcblk0p3 3490000000 turtles_pro-1_59_0.Release\n"
    "image-size 1 /dev/mmcblk0p7 4250000000 turtles_pro-1_59_0.1987\n"
    "image-size free 5500000000 room for updates in the games partitions\n"
    "image-size overhead 2254807552 boot + rootfs + data + dump + metadata\n"
    "image: 30263296 sectors = 15494807552 bytes (15.49 GB)\n"
    "  fits Stern 8G  image size 7861174272: NO (spare -7633633280)\n"
    "  fits Stern 16G image size 15494807552: YES (spare 0)\n"
    "  fits Stern 32G image size 30359420928: YES (spare 14864613376)\n")


def test_plan_output_carries_the_free_row_and_the_bands_sum_to_the_image():
    info = parse_plan(PLAN_TEXT)
    assert info["free"] == 5500000000 and len(info["sizes"]) == 2
    assert sum(s[2] for s in info["sizes"]) + info["free"] + info["overhead"] == info["bytes"]
    view = card_size_view(info)
    assert [k for _l, _b, k in view["bands"]] == ["image", "image", "free", "overhead"]
    assert sum(b for _l, b, _k in view["bands"]) == view["total"]
    assert view["head"] == "16 GB"
    assert view["detail"] == "7.74 GB of games, 5.50 GB free for updates."
    assert len(view["detail"]) <= 50
    old = parse_plan(PLAN_TEXT.replace("image-size free 5500000000 room for updates in the games partitions\n", ""))
    assert old["free"] is None
    assert card_size_view(old)["detail"].endswith("on a 16 GB card.")


def test_parse_update_reads_the_dry_run_rows():
    text = ("update-card /mnt/d/x.raw layout multi\n"
            "update-source 0 /dev/mmcblk0p3 unchanged a.raw\n"
            "update-source 1 /dev/mmcblk0p7:img1 hashed b.raw\n"
            "update-source 2 /dev/mmcblk0p7:img2 missing c.raw\n"
            "update-files 0 /dev/mmcblk0p3 0 0 keep a.raw\n"
            "update-files 1 /dev/mmcblk0p7:img1 1 65011712 sync b.raw\n"
            "update-inject yes\nupdate-size 65011712\nupdate-peak 132000000\n"
            "update-free 4100000000\nupdate-grow p7 1073741824\nupdate-fits YES\n")
    u = parse_update(text)
    assert u["bytes"] == 65011712 and u["peak"] == 132000000 and u["fits"] and u["inject"]
    assert u["files"] == {0: (0, 0, "keep"), 1: (1, 65011712, "sync")}
    assert u["grow"] == ("p7", 1073741824) and u["missing"] == [2]
    assert parse_update("")["bytes"] is None
    assert parse_update("update-grow none\nupdate-fits NO\n")["grow"] is None
    assert parse_update("update-fits NO\n")["fits"] is False


def test_trees_from_inspect_needs_a_record():
    assert trees_from_inspect({}) is None
    assert trees_from_inspect({"trees": None}) is None
    info = {"trees": {"recorded": True, "free_bytes": 5, "dirty": [], "synced": [7],
                      "images": [{"index": 0, "source_changed": False}, {"index": 1, "source_changed": True}]}}
    t = trees_from_inspect(info)
    assert t == {"free": 5, "dirty": [], "synced": [7], "changed": {0: False, 1: True}}


# ------------------------------------------------------------------ the decision
def _messages(panel, monkeypatch):
    """Every status message the panel puts up, in order (the app's status line
    is a callback; this reads the words, not the widget)."""
    msgs = []
    monkeypatch.setattr(panel, "_ok", lambda msg, extra=True: msgs.append(msg))
    monkeypatch.setattr(panel, "_error", lambda msg: msgs.append(msg))
    return msgs


def _recorded_report(tmp_path):
    rep = copy.deepcopy(_rich_report(tmp_path, armed=False))
    rep["trees"] = {"recorded": True, "free_bytes": 3400000000, "dirty": [], "synced": [],
                    "images": [{"index": i, "source_changed": False} for i in range(len(rep["images"]))]}
    return rep


def _dry(nfiles, nbytes, action="sync", index=1):
    rows = ["update-card x layout parts", "update-files 0 /dev/mmcblk0p3 0 0 keep a.raw",
            "update-files %d /dev/mmcblk0p7 %d %d %s b.raw" % (index, nfiles, nbytes, action),
            "update-inject no", "update-size %d" % nbytes, "update-peak %d" % nbytes,
            "update-free 100", "update-grow none", "update-fits YES"]
    return "\n".join(rows) + "\n"


def test_a_loaded_card_with_a_record_offers_update_once_the_dry_run_names_a_change(tmp_path):
    root, panel, card, media = _loaded(tmp_path, report=_recorded_report(tmp_path))
    try:
        assert panel._loaded_trees is not None
        assert _write_action(panel) == "apply"                     # nothing measured, nothing changed
        panel._update_step(0, _dry(0, 0, "keep"))
        assert _write_action(panel) == "apply"                     # measured: nothing to write
        panel._update_step(0, _dry(1, 65011712))
        plan = panel._write_plan()
        assert plan["action"] == "update" and plan["can_write"] and plan["default_write"]
        assert plan["write_label"] == "Update the loaded card in place"
        assert "1 file, 65.0 MB to write" in plan["write_detail"] or "1 file, 0.07 GB" in plan["write_detail"]
        assert "image 1 changed on disk" in plan["write_detail"]
        assert "nothing else is copied" in plan["write_detail"]
    finally:
        root.destroy()


def test_a_refused_dry_run_falls_back_to_a_fresh_card_that_cannot_be_the_loaded_one(tmp_path):
    root, panel, card, media = _loaded(tmp_path, report=_recorded_report(tmp_path))
    try:
        panel._update_step(2, "[card] error: p7 needs 2.00 GB and has 0.50 GB free: build a fresh card\n")
        plan = panel._write_plan()
        assert plan["action"] == "build" and not plan["can_write"] and not plan["default_write"]
        assert "cannot be updated in place" in plan["write_detail"]
        assert "build a fresh card" in plan["write_detail"]
    finally:
        root.destroy()


def test_a_card_without_a_record_says_the_list_change_needs_a_fresh_card(tmp_path):
    root, panel, card, media = _loaded(tmp_path)                    # _rich_report: no trees block
    try:
        assert panel._loaded_trees is None
        panel._rows.append(multiboot_tab.ImageRow(path=str(tmp_path / "third.raw")))
        panel._refresh_tree()
        plan = panel._write_plan()
        assert plan["action"] == "build" and not plan["can_write"]
        assert "written before cards could be updated in place" in plan["write_detail"]
    finally:
        root.destroy()


def test_a_list_change_on_a_recorded_card_is_an_update(tmp_path):
    root, panel, card, media = _loaded(tmp_path, report=_recorded_report(tmp_path))
    try:
        panel._rows.append(multiboot_tab.ImageRow(path=str(tmp_path / "third.raw")))
        panel._refresh_tree()
        plan = panel._write_plan()
        assert plan["action"] == "update" and plan["can_write"]
        assert "working out what has to be written" in plan["write_detail"]
        panel._update_step(0, _dry(1385, 4250000000, "new", index=2))
        plan = panel._write_plan()
        assert plan["action"] == "update" and "1385 files" in plan["write_detail"]
    finally:
        root.destroy()


def test_update_card_runs_update_then_reads_the_card_back(tmp_path, monkeypatch):
    # the root step is a CALLABLE on Windows (the WSL home is resolved on the
    # worker) and a `sudo -n` argv elsewhere; this test is about the former
    monkeypatch.setattr(multiboot_tab.sys, "platform", "win32")
    root, panel, card, media = _loaded(tmp_path, report=_recorded_report(tmp_path))
    try:
        panel._update_step(0, _dry(1, 65011712))
        seen = {}

        def fake(cmds, on_step=None, on_done=None, quiet=(), preview=False, on_tick=None):
            seen["labels"] = [label for label, _ in cmds]
            seen["argv"] = [argv for _l, argv in cmds]
            seen["quiet"] = quiet
            on_done(0, None, {})
            return True
        monkeypatch.setattr(panel, "_run_commands", fake)
        msgs = _messages(panel, monkeypatch)
        assert panel.update_card() is True
        assert seen["labels"] == ["selector", "update", "inspect", INSPECT_JSON]
        assert callable(seen["argv"][1]) and INSPECT_JSON in seen["quiet"]
        words = _tool_words(seen["argv"][1]({}))
        assert words[1] == "update" and words[words.index("--expect-bytes") + 1] == "65011712"
        assert panel._run_kind == "update"
        assert panel._update_info is None
        assert any("Card updated" in m for m in msgs)
    finally:
        root.destroy()


def test_a_refused_update_run_says_why_and_offers_a_fresh_card(tmp_path, monkeypatch):
    root, panel, card, media = _loaded(tmp_path, report=_recorded_report(tmp_path))
    try:
        panel._update_step(0, _dry(1, 65011712))

        def fake(cmds, on_step=None, on_done=None, quiet=(), preview=False, on_tick=None):
            on_done(2, "update", {"update": "[card] error: other.raw is not the primary this card was built from"})
            return True
        monkeypatch.setattr(panel, "_run_commands", fake)
        msgs = _messages(panel, monkeypatch)
        panel.update_card()
        assert any("Cannot update" in m and "not the primary" in m for m in msgs)
        assert panel._update_info.get("refused")
        assert _write_action(panel) == "build"
    finally:
        root.destroy()


def test_a_cancelled_update_says_it_carries_on(tmp_path, monkeypatch):
    root, panel, card, media = _loaded(tmp_path, report=_recorded_report(tmp_path))
    try:
        panel._update_step(0, _dry(1, 65011712))

        def fake(cmds, on_step=None, on_done=None, quiet=(), preview=False, on_tick=None):
            panel._cancelled = True
            on_done(137, "update", {"update": ""})
            return True
        monkeypatch.setattr(panel, "_run_commands", fake)
        msgs = _messages(panel, monkeypatch)
        panel.update_card()
        assert any("carries on from what was already written" in m for m in msgs)
    finally:
        root.destroy()


def test_the_footer_walks_copy_for_an_update():
    assert multiboot_tab.MultibootPanel.PHASE_OF["update"] == 1
    assert multiboot_tab.MultibootPanel.PHASE_OF[DRY_RUN] == 0
    assert "changed" in multiboot_tab.MultibootPanel.PHASE_STATUS["update"]


def test_the_size_check_asks_for_the_dry_run_only_on_the_loaded_card(tmp_path, monkeypatch):
    root, panel, card, media = _loaded(tmp_path, report=_recorded_report(tmp_path))
    try:
        seen = []

        def fake(cmds, on_step=None, on_done=None, quiet=(), preview=False, on_tick=None):
            seen.append([label for label, _ in cmds])
            return True
        monkeypatch.setattr(panel, "_run_commands", fake)
        panel._auto_plan = True
        for r in panel._rows:
            if not os.path.isfile(r.path):
                with open(r.path, "wb") as f:
                    f.write(b"x")
        assert panel._plan_now() is True
        assert seen[-1] == ["plan", DRY_RUN]
        assert panel._plan_key()[1] == panel._loaded_card
    finally:
        root.destroy()
