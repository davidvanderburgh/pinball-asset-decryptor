"""The Multi-boot tab's in-place UPDATE (item 93) - the pure layer and the decision.

The tool's contract is pinned in tools/spike2_emu/mkmulticard.py (`update --dry-run` rows,
`plan`'s `image-size free` row, inspect's `trees` block); these tests hold the tab to it: the
argv it builds (a root step is a callable resolved on the worker), what it parses and what
the size strip draws.  Everything runs without WSL; the helpers are test_multiboot_tab.py's.
"""
import pytest

from pinball_decryptor.webui import multiboot_core
from pinball_decryptor.webui.multiboot_core import (
    DRY_RUN, INSPECT_JSON, build_commands, card_size_view, measure_commands, parse_plan,
    parse_update, root_command, trees_from_inspect, update_args, update_commands,
    wsl_shell_root)

from tests.test_multiboot_tab import (  # noqa: E402
    _form, _line, _tool_words, _win)


@pytest.fixture(autouse=True)
def _no_wsl_home_probe(monkeypatch):
    monkeypatch.setattr(multiboot_core, "wsl_home", lambda: "/home/x")
    monkeypatch.setattr(multiboot_core, "wsl_account", lambda: ("x", "/home/x"))


# ------------------------------------------------------------------ argv
def test_update_argv_is_the_menu_flags_on_the_loaded_card(monkeypatch, tmp_path):
    _win(monkeypatch)
    form = _form(tmp_path, 2)
    card = str(tmp_path / "card.raw")
    words = _tool_words(root_command(update_args(form, card), cwd="/mnt/c/repo"))
    assert words[:4] == ["tools/spike2_emu/mkmulticard.py", "update", "--card", multiboot_core.wsl(card)]
    assert "--primary" in words and "--extra" in words
    for flag in ("--selector-dir", "--titles", "--subtitles", "--timeout", "--default", "--volume",
                 "--cache-dir", "--bypass-validation"):
        assert flag in words, flag
    assert "--dry-run" not in words and "--expect-bytes" not in words
    assert "--out" not in words and "--layout" not in words and "--force" not in words
    words = _tool_words(multiboot_core.wsl_command(update_args(form, card, dry_run=True, expect_bytes=123),
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
    monkeypatch.setattr(multiboot_core.sys, "platform", "linux")
    assert wsl_shell_root("echo hi", "/home/x") == ["sudo", "-n", "bash", "-lc", "echo hi"]


def test_a_root_step_without_a_home_fails_with_a_sentence(monkeypatch, tmp_path):
    """Only when WSL would not say WHO it logs in as - see the test below for
    the machine that has no desktop home and does not need one."""
    _win(monkeypatch)
    monkeypatch.setattr(multiboot_core, "wsl_home", lambda: None)
    monkeypatch.setattr(multiboot_core, "wsl_account", lambda: ("", ""))
    step = root_command(["x.py", "build"], cwd="/mnt/c/repo")
    with pytest.raises(RuntimeError) as e:
        step({})
    assert "WSL home" in str(e.value)


def test_a_root_default_distro_builds_with_roots_own_home(monkeypatch, tmp_path):
    """PAD-114.  A distro whose default account IS root has no desktop home
    to carry, and needs none: every other step of the run has already been
    root, so ~/spike2root means /root/spike2root here too and the build goes
    ahead.  It used to be refused with "check that WSL starts" - on a WSL
    that had just built the menu program and planned the card."""
    _win(monkeypatch)
    monkeypatch.setattr(multiboot_core, "wsl_home", lambda: None)
    monkeypatch.setattr(multiboot_core, "wsl_account", lambda: ("root", "/root"))
    argv = root_command(["x.py", "build"], cwd="/mnt/c/repo")({})
    assert argv[:8] == ["wsl.exe", "-u", "root", "-e", "env", "HOME=/root",
                        "bash", "-lc"]
    assert _line(argv) == "cd /mnt/c/repo && python3 x.py build"
    # ...and with no readable passwd row for root, no override at all:
    # `wsl -u root` sets HOME itself, to the same account's home.
    monkeypatch.setattr(multiboot_core, "wsl_account", lambda: ("root", ""))
    argv = root_command(["x.py", "build"], cwd="/mnt/c/repo")({})
    assert argv[:6] == ["wsl.exe", "-u", "root", "-e", "bash", "-lc"]


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


def test_the_footer_walks_copy_for_an_update():
    assert multiboot_core.MultibootPanel.PHASE_OF["update"] == 1
    assert multiboot_core.MultibootPanel.PHASE_OF[DRY_RUN] == 0
    assert "changed" in multiboot_core.MultibootPanel.PHASE_STATUS["update"]



def test_update_and_inject_titles_are_one_per_game_not_per_row(monkeypatch, tmp_path):
    """PAD-202: a random card over games already on the card is a ROW that
    adds no GAME.  Update and inject sent one title per row, so six games and
    one such card said 7 titles for 6 images and the tool refused the update
    ("images.conf: 7 titles / 7 subtitles / 6 media rows for 6 images") -
    'Build a fresh card' was then the only way to change anything."""
    from pinball_decryptor.webui.multiboot_core import (
        MemberRow, build_args, inject_args)
    from pinball_decryptor.webui.multiboot_core import ImageRow
    _win(monkeypatch)
    form = _form(tmp_path, 4)              # four games, five rows
    paths = [r.path for r in form.images]
    # the random card sits FIRST, so a per-row --default would name the
    # wrong image too
    form.images.insert(0, ImageRow(path="", title="RANDOM", subtitle="surprise me", keep=True,
                                   members=[MemberRow(path=p) for p in paths[1:4]]))
    card = str(tmp_path / "card.raw")

    def flag(words, name):
        return words[words.index(name) + 1]

    want = ";".join("IMG %d" % i for i in range(4))
    for argv in (update_args(form, card), inject_args(form, card), build_args(form)):
        words = _tool_words(root_command(argv, cwd="/mnt/c/repo"))
        assert flag(words, "--titles") == want, words[1]
        if "--subtitles" in words:
            assert flag(words, "--subtitles").split(";") == [""] * 4, words[1]
    # row 1 (IMG 0) highlighted: that is IMAGE 0, not 1
    form.default = 1
    for argv in (update_args(form, card), inject_args(form, card), build_args(form)):
        words = _tool_words(root_command(argv, cwd="/mnt/c/repo"))
        assert flag(words, "--default") == "0", words[1]
        assert "--default-card" not in words, words[1]
    # the random card highlighted: its CARD index goes, as build's always did
    form.default = 0
    for argv in (update_args(form, card), inject_args(form, card), build_args(form)):
        words = _tool_words(root_command(argv, cwd="/mnt/c/repo"))
        assert flag(words, "--default-card") == "0", words[1]
