"""Multi-boot tab (item 90): the pure command builders, the validation that
keeps a bad form off WSL, and the handoffs to the flash flow and the Emulate
tab.

The command builders are tested WITHOUT WSL: they return argv, and what is
asserted is the argv - which tool, which subcommand, which flags, how a title
with spaces is quoted.  The widget tests build panels on an invisible, parked
root exactly as tests/test_emulate_tab.py does (transparent AND off-screen: a
transparent window is still mapped and takes the foreground), and skip when
Tk is unusable.  The one test that needs the whole app borrows
test_gui_smoke's ``app`` fixture, which is also what conftest's Tk sniff keys
on to keep this file in the Tk group.
"""

import os
import shlex
import sys
import time

import pytest

from tests.conftest import HAS_DISPLAY
from tests.test_gui_smoke import app  # noqa: F401  (fixture)

from pinball_decryptor.gui import emulate_tab, multiboot_tab
from pinball_decryptor.gui.multiboot_tab import (
    DEFAULT_SELECTOR_DIR, ImageRow, MultibootForm, build_commands,
    bypass_commands, default_output_path, parse_plan, plan_commands,
    prepare_commands, size_plan_text, suggest_title, under_library,
    validate_form)


@pytest.fixture(autouse=True)
def _no_real_setup_probe(monkeypatch):
    """Same rule as test_emulate_tab: building an Emulate panel must not
    shell out to WSL for the setup probe."""
    monkeypatch.setattr(emulate_tab, "setup_state", lambda: None)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _images(tmp_path, n):
    names = ["turtles_pro-1_59_0.Release.8G.sdcard.raw",
             "turtles_pro-1_59_0.1987-upscaled.8G.sdcard.raw",
             "godzilla_pro-1_15_0.Heisei-orchestra.8G.sdcard.raw",
             "godzilla_pro-1_15_0.Heisei.8G.sdcard.raw"]
    paths = []
    for name in names[:n]:
        p = tmp_path / name
        p.write_bytes(bytes(16))
        paths.append(str(p))
    return paths


def _form(tmp_path, n, **kw):
    paths = _images(tmp_path, n)
    rows = [ImageRow(path=p, title="IMG %d" % i) for i, p in enumerate(paths)]
    out = str(tmp_path / "multi" / "card.multi.raw")
    form = MultibootForm(images=rows, out=out)
    for k, v in kw.items():
        setattr(form, k, v)
    return form


def _line(argv):
    """The shell line inside a wsl.exe / bash -lc argv."""
    return argv[-1]


def _tool_words(argv):
    """The tool's own argv (after ``cd … && python3``), shell-split."""
    words = shlex.split(_line(argv))
    assert words[0] == "cd" and words[2] == "&&" and words[3] == "python3", \
        words
    return words[4:]


def _win(monkeypatch):
    monkeypatch.setattr(multiboot_tab.sys, "platform", "win32")


# --------------------------------------------------------------------------
# the command builders
# --------------------------------------------------------------------------

def test_two_image_form_builds_plan_build_verify(monkeypatch, tmp_path):
    _win(monkeypatch)
    form = _form(tmp_path, 2)
    cmds = build_commands(form, cwd="/mnt/c/repo")
    assert [label for label, _ in cmds] == ["plan", "build", "verify"]
    for _label, argv in cmds:
        assert argv[:4] == ["wsl.exe", "-e", "bash", "-lc"], argv
        assert _line(argv).startswith("cd /mnt/c/repo && python3 "
                                      "tools/spike2_emu/mkmulticard.py ")
        assert "\\" not in _line(argv)          # Windows paths would not open
    prim = multiboot_tab.wsl(form.images[0].path)
    extra = multiboot_tab.wsl(form.images[1].path)
    out = multiboot_tab.wsl(form.out)
    plan = _tool_words(cmds[0][1])
    assert plan[:2] == ["tools/spike2_emu/mkmulticard.py", "plan"]
    assert plan[2:6] == ["--primary", prim, "--extra", extra]
    assert plan[-2:] == ["--layout", "auto"]
    build = _tool_words(cmds[1][1])
    assert build[1] == "build"
    assert build[2:6] == ["--primary", prim, "--extra", extra]
    assert build[build.index("--out") + 1] == out
    assert build[build.index("--selector-dir") + 1] == DEFAULT_SELECTOR_DIR
    assert build[build.index("--layout") + 1] == "auto"
    assert build[build.index("--titles") + 1] == "IMG 0;IMG 1"
    assert build[build.index("--timeout") + 1] == "15"
    assert build[build.index("--default") + 1] == "0"
    assert build[build.index("--volume") + 1] == "50"
    assert "--bypass-validation" in build          # the default is ON
    assert "--media-dir" not in build              # nothing prepared
    assert "--force" not in build
    assert "--subtitles" not in build              # none given
    verify = _tool_words(cmds[2][1])
    assert verify[1:3] == ["verify", "--card"] and verify[3] == out
    assert verify[4:8] == ["--primary", prim, "--extra", extra]
    assert verify[-2:] == ["--selector-dir", DEFAULT_SELECTOR_DIR]


def test_three_image_form_carries_every_extra_and_the_media(monkeypatch,
                                                           tmp_path):
    _win(monkeypatch)
    media = tmp_path / "multi" / "media"
    form = _form(tmp_path, 3, bypass=False, media_dir=str(media), force=True,
                 timeout=0, default=2, volume=35, sound_move="synth",
                 sound_confirm="none")
    form.images[1].subtitle = "1987 cartoon"
    form.images[1].anim = "auto"
    cmds = build_commands(form)
    build = _tool_words(cmds[1][1])
    extras = [build[i + 1] for i, w in enumerate(build) if w == "--extra"]
    assert extras == [multiboot_tab.wsl(r.path) for r in form.images[1:]]
    assert "--bypass-validation" not in build
    assert build[build.index("--media-dir") + 1] == multiboot_tab.wsl(
        str(media))
    assert "--force" in build
    assert build[build.index("--timeout") + 1] == "0"
    assert build[build.index("--default") + 1] == "2"
    assert build[build.index("--subtitles") + 1] == ";1987 cartoon;"
    assert build[build.index("--volume") + 1] == "35"
    verify = _tool_words(cmds[2][1])
    assert verify.count("--extra") == 2
    assert verify[verify.index("--media-dir") + 1] == multiboot_tab.wsl(
        str(media))
    # ...and the media preparation: the images (auto art / clips come off
    # them), then --art/--anim/--music N=value for EVERY image, then the
    # globals.
    prep = _tool_words(prepare_commands(form, str(media))[0][1])
    assert prep[:2] == ["tools/spike2_emu/selectmedia.py", "prepare"]
    assert prep[2:4] == ["--primary", multiboot_tab.wsl(form.images[0].path)]
    assert [prep[i + 1] for i, w in enumerate(prep) if w == "--extra"] == \
        [multiboot_tab.wsl(r.path) for r in form.images[1:]]
    assert prep[prep.index("--out") + 1] == multiboot_tab.wsl(str(media))
    arts = [prep[i + 1] for i, w in enumerate(prep) if w == "--art"]
    anims = [prep[i + 1] for i, w in enumerate(prep) if w == "--anim"]
    musics = [prep[i + 1] for i, w in enumerate(prep) if w == "--music"]
    assert arts == ["0=auto", "1=auto", "2=auto"]
    assert anims == ["0=none", "1=auto", "2=none"]
    assert musics == ["0=none", "1=none", "2=none"]
    assert prep[prep.index("--sound-move") + 1] == "synth"
    assert prep[prep.index("--sound-confirm") + 1] == "none"
    assert prep[prep.index("--volume") + 1] == "35"


def test_media_files_cross_as_wsl_paths(monkeypatch, tmp_path):
    _win(monkeypatch)
    wav = tmp_path / "my click.wav"
    wav.write_bytes(bytes(4))
    form = _form(tmp_path, 2, sound_move=str(wav))
    form.images[1].art = str(tmp_path / "logo.png")
    prep = _tool_words(prepare_commands(form, str(tmp_path / "media"))[0][1])
    assert prep[prep.index("--sound-move") + 1] == multiboot_tab.wsl(str(wav))
    assert "\\" not in _line(prepare_commands(form, str(tmp_path / "m"))[0][1])
    arts = [prep[i + 1] for i, w in enumerate(prep) if w == "--art"]
    assert arts[1] == "1=" + multiboot_tab.wsl(str(tmp_path / "logo.png"))


def test_titles_with_spaces_are_quoted_for_the_shell(monkeypatch, tmp_path):
    _win(monkeypatch)
    form = _form(tmp_path, 2)
    form.images[0].title = "STERN 1.59"
    form.images[1].title = "TMNT 1987"
    form.images[1].subtitle = "1987 cartoon upscale (1.59.0)"
    line = _line(build_commands(form)[1][1])
    assert "--titles 'STERN 1.59;TMNT 1987'" in line
    assert "--subtitles ';1987 cartoon upscale (1.59.0)'" in line
    build = _tool_words(build_commands(form)[1][1])
    assert build[build.index("--titles") + 1] == "STERN 1.59;TMNT 1987"


def test_blank_titles_fall_back_to_the_image_name(tmp_path):
    form = _form(tmp_path, 2)
    form.images[0].title = ""
    build = _tool_words(build_commands(form, cwd="/x")[1][1])
    assert build[build.index("--titles") + 1] == \
        "turtles_pro-1_59_0;IMG 1"


def test_selector_dir_tilde_stays_expandable(monkeypatch, tmp_path):
    """``~/`` must sit OUTSIDE the quotes: bash expands it there, and a
    ``$HOME`` would be eaten by wsl.exe's re-parse before bash saw it."""
    _win(monkeypatch)
    form = _form(tmp_path, 2)
    line = _line(build_commands(form)[1][1])
    assert " --selector-dir ~/spike2root/usr/local/codeselect " in line
    assert "$" not in line
    form.selector_dir = "~/my root/sel dir"
    line = _line(build_commands(form)[1][1])
    assert " --selector-dir ~/'my root/sel dir' " in line


def test_linux_runs_bash_directly(monkeypatch, tmp_path):
    monkeypatch.setattr(multiboot_tab.sys, "platform", "linux")
    argv = plan_commands(_form(tmp_path, 2), cwd="/home/x/repo")[0][1]
    assert argv[:2] == ["bash", "-lc"]
    assert "wsl.exe" not in argv


def test_default_cwd_is_the_checkout_root(monkeypatch, tmp_path):
    """The tools import pinball_decryptor (the bypass uses valpatch/sidx), so
    they run from the checkout the rig sits in: <rig>/../.."""
    _win(monkeypatch)
    rig = tmp_path / "checkout" / "tools" / "spike2_emu"
    rig.mkdir(parents=True)
    monkeypatch.setenv("PAD_EMU_DIR", str(rig))
    line = _line(plan_commands(_form(tmp_path, 2))[0][1])
    want = multiboot_tab._q(multiboot_tab.wsl(str(tmp_path / "checkout")))
    assert line.startswith("cd %s && " % want), line


def test_bypass_command_targets_an_existing_card(monkeypatch, tmp_path):
    _win(monkeypatch)
    card = str(tmp_path / "TMNT 1987" / "multi" / "card.raw")
    words = _tool_words(bypass_commands(card)[0][1])
    assert words == ["tools/spike2_emu/mkmulticard.py", "bypass", "--card",
                     multiboot_tab.wsl(card)]
    assert "'" in _line(bypass_commands(card)[0][1])   # the space was quoted


# --------------------------------------------------------------------------
# validation and defaults
# --------------------------------------------------------------------------

def test_validation_refuses_what_the_tool_would(tmp_path):
    good = _form(tmp_path, 2)
    assert validate_form(good) == []
    one = _form(tmp_path, 1)
    assert any("at least two" in e for e in validate_form(one))
    bar = _form(tmp_path, 2)
    bar.images[1].title = "TMNT|1987"
    assert any("must not contain" in e for e in validate_form(bar))
    semi = _form(tmp_path, 2)
    semi.images[0].subtitle = "a;b"
    assert any("must not contain" in e for e in validate_form(semi))
    dollar = _form(tmp_path, 2)
    dollar.images[0].title = "$HOME"
    assert any("must not contain" in e for e in validate_form(dollar))
    lib = _form(tmp_path, 2, out="D:/Pinball/images/Stern/spike2/x.multi.raw")
    assert any("card library" in e for e in validate_form(lib))
    same = _form(tmp_path, 2)
    same.out = same.images[0].path
    assert any("one of the input images" in e for e in validate_form(same))
    missing = _form(tmp_path, 2)
    missing.images[1].path = str(tmp_path / "nope.raw")
    assert any("no such file" in e.lower() for e in validate_form(missing))
    nomedia = _form(tmp_path, 2, sound_confirm=str(tmp_path / "none.wav"))
    assert any("confirm sound" in e for e in validate_form(nomedia))
    bad_default = _form(tmp_path, 2, default=2)
    assert any("default image" in e for e in validate_form(bad_default))


def test_default_output_leaves_the_library(tmp_path):
    """A default the tool would refuse is no default: a primary IN the
    library gets its output beside the library, not inside it."""
    got = default_output_path("D:/Pinball/images/Stern/spike2/"
                              "turtles_pro-1_59_0.Release.8G.sdcard.raw")
    assert os.path.normpath(got) == os.path.normpath(
        "D:/Pinball/multi/turtles_pro-1_59_0.Release.8G.sdcard.multi.raw")
    assert not under_library(got)
    primary = _images(tmp_path, 1)[0]
    got = default_output_path(primary)
    assert os.path.normpath(got) == os.path.normpath(
        str(tmp_path / "multi" /
            "turtles_pro-1_59_0.Release.8G.sdcard.multi.raw"))


def test_library_prefixes_are_the_tools_own(tmp_path):
    """One fact, two files: the tab refuses exactly what mkmulticard.py
    refuses.  Compared after both are normalised the tool's way."""
    rig = emulate_tab.DEFAULT_RIG_DIR
    if not os.path.isfile(os.path.join(rig, "mkmulticard.py")):
        pytest.skip("mkmulticard.py not present")
    if rig not in sys.path:
        sys.path.insert(0, rig)
    import mkmulticard
    ours = {multiboot_tab._norm(p) for p in multiboot_tab.LIBRARY_PREFIXES}
    theirs = {multiboot_tab._norm(p)
              for p in mkmulticard.FORBIDDEN_OUTPUT_PREFIXES}
    assert ours == theirs


def test_plan_output_becomes_a_card_size_sentence():
    text = ("p7   0x83 15353856     13402110     ...\n"
            "images: 0=/dev/mmcblk0p3, 1=/dev/mmcblk0p7\n"
            "image: 28755968 sectors = 14723055616 bytes (14.72 GB)\n"
            "  fits Stern 8G  image size 7861174272: NO (spare -6861881344)\n"
            "  fits Stern 16G image size 15494807552: YES (spare 771751936)\n"
            "  fits Stern 32G image size 30359420928: YES (spare 15636365312)\n")
    info = parse_plan(text)
    assert info["bytes"] == 14723055616
    assert info["fits"]["8G"] == (False, -6861881344)
    assert info["fits"]["16G"] == (True, 771751936)
    s = size_plan_text(info)
    assert "14.72 GB" in s and "Fits a 16 GB card" in s and "0.77 GB" in s
    text32 = text.replace("16G image size 15494807552: YES (spare 771751936)",
                          "16G image size 15494807552: NO (spare -1)")
    assert "Needs a 32 GB card" in size_plan_text(parse_plan(text32))
    none = text32.replace("32G image size 30359420928: YES",
                          "32G image size 30359420928: NO")
    assert "Does not fit" in size_plan_text(parse_plan(none))
    assert size_plan_text(parse_plan("")) == ""


def test_suggest_title_splits_the_card_name():
    assert suggest_title("turtles_pro-1_59_0.Release.8G.sdcard.raw") == \
        ("turtles_pro-1_59_0", "Release")
    assert suggest_title(r"D:\x\turtles_pro-1_59_0.1987-upscaled.8G.sdcard.raw") \
        == ("turtles_pro-1_59_0", "1987-upscaled")
    assert suggest_title("card.img") == ("card", "")


def test_capability_is_spike2_only(manufacturers_by_key):
    from pinball_decryptor.core.registry import Capabilities
    assert Capabilities().multiboot is False
    stern = manufacturers_by_key["stern"]
    try:
        stern.set_era("spike2")
        assert stern.capabilities.multiboot is True
        stern.set_era("spike1")
        assert stern.capabilities.multiboot is False
        stern.set_era("whitestar")
        assert stern.capabilities.multiboot is False
    finally:
        stern.set_era("spike2")
    for key, mfr in manufacturers_by_key.items():
        if key != "stern":
            assert getattr(mfr.capabilities, "multiboot", False) is False, key


# --------------------------------------------------------------------------
# the panel (invisible root)
# --------------------------------------------------------------------------

def _root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError as exc:                          # no display / no Tcl
        pytest.skip("Tk unavailable: %s" % exc)
    root.attributes("-alpha", 0)
    root.geometry("+10000+10000")
    return root


def _panel(**kw):
    """A built Multi-boot panel on an invisible root, or a skip."""
    import tkinter as tk
    root = _root()
    frame = tk.Frame(root)
    frame.pack()
    panel = multiboot_tab.MultibootPanel(frame, **kw)
    panel.build(frame)
    root.update()
    return root, panel


def _recorder(panel):
    """Replace the worker with a recorder: (cmds, on_step, on_done)."""
    calls = []

    def fake(cmds, on_step=None, on_done=None):
        calls.append(cmds)
        return True
    panel._run_commands = fake
    return calls


def test_add_images_fills_title_and_output(tmp_path):
    root, panel = _panel()
    try:
        a, b = _images(tmp_path, 2)
        panel.add_image(a)
        panel.add_image(b)
        form = panel.form()
        assert [r.path for r in form.images] == [a, b]
        assert form.images[0].title == "turtles_pro-1_59_0"
        assert form.images[1].subtitle == "1987-upscaled"
        assert os.path.normpath(form.out) == os.path.normpath(
            default_output_path(a))
        assert form.bypass is True and form.volume == 50
        assert form.timeout == 15 and form.default == 0
        assert form.media_dir == ""                    # nothing prepared
        assert form.selector_dir == DEFAULT_SELECTOR_DIR
        assert len(panel._tree.get_children()) == 2
    finally:
        root.destroy()


def test_editor_writes_back_to_the_selected_row(tmp_path):
    root, panel = _panel()
    try:
        a, b = _images(tmp_path, 2)
        panel.add_image(a)
        panel.add_image(b)
        panel._tree.selection_set("1")
        root.update()
        panel._ed_title.set("TMNT 1987")
        panel._ed_anim.set("auto")
        form = panel.form()
        assert form.images[1].title == "TMNT 1987"
        assert form.images[1].anim == "auto"
        assert form.images[0].title == "turtles_pro-1_59_0"   # untouched
    finally:
        root.destroy()


def test_invalid_form_surfaces_error_and_builds_nothing(tmp_path,
                                                        monkeypatch):
    root, panel = _panel()
    calls = _recorder(panel)
    monkeypatch.setattr(multiboot_tab.subprocess, "Popen",
                        lambda *a, **kw: pytest.fail("a tool was started"))
    try:
        a, b = _images(tmp_path, 2)
        panel.add_image(a)
        panel._build_card()
        assert "at least two" in panel._hint.cget("text")
        assert calls == []
        panel.add_image(b)
        panel._rows[1].title = "TMNT|1987"
        panel._build_card()
        assert "must not contain" in panel._hint.cget("text")
        assert calls == []
        panel._rows[1].title = "TMNT 1987"
        panel._out_var.set("D:/Pinball/images/Stern/spike2/x.multi.raw")
        panel._build_card()
        assert "card library" in panel._hint.cget("text")
        assert calls == []
        panel._check_size()
        assert calls == []
        panel._prepare_media()
        assert calls == []
    finally:
        root.destroy()


def test_valid_form_runs_plan_build_verify(tmp_path):
    root, panel = _panel()
    calls = _recorder(panel)
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        panel._build_card()
        assert len(calls) == 1
        assert [label for label, _ in calls[0]] == ["plan", "build", "verify"]
        assert "--bypass-validation" in _line(calls[0][1][1])
        panel._check_size()
        assert [label for label, _ in calls[1]] == ["plan"]
        panel._bypass_var.set(False)
        panel._build_card()
        assert "--bypass-validation" not in _line(calls[2][1][1])
    finally:
        root.destroy()


def test_prepared_media_rides_into_the_build(tmp_path):
    root, panel = _panel()
    calls = _recorder(panel)
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        panel._prepare_media()
        media = multiboot_tab.media_dir_for(panel._out_var.get())
        assert os.path.isdir(media)
        assert [label for label, _ in calls[0]] == ["prepare"]
        assert multiboot_tab.wsl(media) in _line(calls[0][0][1])
        # Not prepared yet (no media.json) -> the build does not name it.
        panel._build_card()
        assert "--media-dir" not in _line(calls[1][1][1])
        with open(os.path.join(media, "media.json"), "w") as f:
            f.write("{}")
        panel._build_card()
        assert "--media-dir " + multiboot_tab._q(multiboot_tab.wsl(media)) \
            in _line(calls[2][1][1])
    finally:
        root.destroy()


def test_busy_guard_refuses_a_second_run(tmp_path, monkeypatch):
    root, panel = _panel()
    monkeypatch.setattr(multiboot_tab.subprocess, "Popen",
                        lambda *a, **kw: pytest.fail("a tool was started"))
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        panel._set_busy(True)
        assert panel._run_commands([("plan", ["true"])]) is False
        panel._build_card()
        assert "already in progress" in panel._hint.cget("text")
        assert str(panel._build_btn.cget("state")) == "disabled"
        panel._set_busy(False)
        assert str(panel._build_btn.cget("state")) == "normal"
    finally:
        root.destroy()


def test_flash_button_passes_the_output_path(tmp_path):
    flashed = []
    root, panel = _panel(flash_fn=flashed.append)
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        out = panel._out_var.get()
        panel._flash()
        assert flashed == []
        assert "Build the card first" in panel._hint.cget("text")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(bytes(16))
        panel._flash()
        assert flashed == [out]
    finally:
        root.destroy()


def test_run_in_emulator_hands_the_card_to_the_emulate_panel(tmp_path):
    ran = []
    root, panel = _panel(emulate_fn=ran.append)
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        out = panel._out_var.get()
        panel._run_emulator()
        assert ran == []
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(bytes(16))
        panel._run_emulator()
        assert ran == [out]
    finally:
        root.destroy()


def test_handoff_buttons_are_greyed_without_the_app():
    root, panel = _panel()
    try:
        assert str(panel._flash_btn.cget("state")) == "disabled"
        assert str(panel._emu_btn.cget("state")) == "disabled"
    finally:
        root.destroy()


def test_emulate_launch_carries_pad_card_and_pad_select(tmp_path):
    """The Emulate panel's half of 'Run in emulator': the card lands in
    PAD_CARD and Boot selector in PAD_SELECT=1 - in the Start env, NOT in
    _source_env (a test pins that to the one PAD_CARD entry)."""
    import tkinter as tk
    img = _images(tmp_path, 1)[0]
    root = _root()
    frame = tk.Frame(root)
    frame.pack()
    panel = emulate_tab.EmulatePanel(frame)
    panel.build(frame)
    root.update()
    try:
        assert panel._select_var.get() is False          # off by default
        panel.launch_card(img, select=True)              # no rig: start() is a no-op
        assert panel._src_path.get() == img
        assert panel._select_var.get() is True
        src = panel._source_env()
        assert len(src) == 1 and src[0].startswith("PAD_CARD=")
        env = panel._launch_env(src)
        assert "PAD_SELECT=1" in env
        assert src[0] in env
        assert "PAD_AUDIO_CTL=" + emulate_tab.AUDIO_CTL_FILE in env
        panel._select_var.set(False)
        assert "PAD_SELECT=1" not in panel._launch_env(src)
        # The checkbox sits beside Mute, on the button row.
        assert panel._select_chk.master is panel._mute_chk.master
    finally:
        root.destroy()


def test_run_commands_streams_the_tool_into_the_pane(tmp_path):
    """The worker, without WSL: a Python child stands in for the tool.  Its
    lines reach the pane, the plan line becomes the size sentence, the busy
    flag clears, and on_done sees the exit code."""
    root, panel = _panel()
    done = []
    argv = [sys.executable, "-c",
            "print('[card] hello from the tool'); "
            "print('image: 28755968 sectors = 14723055616 bytes (14.72 GB)'); "
            "print('  fits Stern 16G image size 15494807552: YES "
            "(spare 771751936)')"]
    try:
        assert panel._run_commands(
            [("plan", argv)], on_step=panel._plan_step,
            on_done=lambda rc, failed, texts: done.append((rc, failed))) is True
        assert panel._busy is True
        deadline = time.time() + 20
        while not done and time.time() < deadline:
            root.update()
            time.sleep(0.02)
        root.update()
        assert done == [(0, None)]
        assert panel._busy is False
        pane = panel._log_text.get("1.0", "end")
        assert "[card] hello from the tool" in pane
        assert "plan: exit 0" in pane
        assert "Fits a 16 GB card" in panel._plan_lbl.cget("text")
    finally:
        root.destroy()


def test_run_commands_stops_at_the_first_failure(tmp_path):
    root, panel = _panel()
    done = []
    fail = [sys.executable, "-c", "print('[card] error: nope'); raise SystemExit(2)"]
    never = [sys.executable, "-c", "print('SHOULD NOT RUN')"]
    try:
        panel._run_commands([("build", fail), ("verify", never)],
                            on_done=lambda rc, failed, texts:
                            done.append((rc, failed, sorted(texts))))
        deadline = time.time() + 20
        while not done and time.time() < deadline:
            root.update()
            time.sleep(0.02)
        root.update()
        assert done == [(2, "build", ["build"])]
        assert "SHOULD NOT RUN" not in panel._log_text.get("1.0", "end")
    finally:
        root.destroy()


# --------------------------------------------------------------------------
# the tab in the app
# --------------------------------------------------------------------------

@pytest.mark.gui
@pytest.mark.skipif(not HAS_DISPLAY, reason="no Tk display available")
def test_multiboot_tab_built_for_spike2_and_absent_otherwise(
        app, manufacturers_by_key):                      # noqa: F811
    w = app.window
    assert isinstance(w._multiboot_panel, multiboot_tab.MultibootPanel)
    assert "Multi-boot" in w._tab_keys.values()
    stern = manufacturers_by_key["stern"]
    app._on_manufacturer_change(stern)
    w.extract_input_var.set("")
    try:
        stern.set_era("spike2")
        w.apply_manufacturer(stern, reset_era=False)
        app.root.update()
        assert w._tab_visible("Multi-boot")
        assert w._tab_visible("Emulate")
        stern.set_era("spike1")
        w.apply_manufacturer(stern, reset_era=False)
        app.root.update()
        assert not w._tab_visible("Multi-boot")
        stern.set_era("whitestar")
        w.apply_manufacturer(stern, reset_era=False)
        app.root.update()
        assert not w._tab_visible("Multi-boot")
    finally:
        stern.set_era("spike2")
    app._on_back_to_picker()
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    assert not w._tab_visible("Multi-boot")
    # Every tab has help content, this one included (the smoke test walks
    # them all; this pins the key the tab is registered under).
    from pinball_decryptor.gui.help_dialog import HELP_CONTENT
    assert "Multi-boot" in HELP_CONTENT
