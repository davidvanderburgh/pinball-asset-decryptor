"""Multi-boot tab (item 90): the pure command builders, the validation that
keeps a bad form off WSL, the boot-menu preview, and the handoffs to the
flash flow and the Emulate tab.

The command builders are tested WITHOUT WSL: they return argv, and what is
asserted is the argv - which tool, which subcommand, which flags, how a title
with spaces is quoted.  The preview's pipeline is driven with Python children
standing in for the selector (they write a small P6 PPM and print the log
line the real one prints).  The widget tests build panels on an invisible,
parked root exactly as tests/test_emulate_tab.py does (transparent AND
off-screen: a transparent window is still mapped and takes the foreground),
and skip when Tk is unusable.  The one test that needs the whole app borrows
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
    DEFAULT_SELECTOR_DIR, PREVIEW_BUILD_DIR, ImageRow, MultibootForm,
    anim_spec, art_spec, build_commands, bypass_commands,
    default_output_path, ensure_selector_args, fit_factors, parse_anim_frames,
    parse_plan, parse_selector_path, plan_commands, prepare_commands,
    preview_fingerprint, preview_prepare_args, preview_snapshot_args,
    size_plan_text, snapshot_commands, suggest_title, under_library,
    validate_form, write_preview_conf)


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


def _ppm(path, w=136, h=77, rgb=(40, 60, 90)):
    """A binary P6 PPM of one colour - what the selector's --snapshot writes,
    at a size a test can afford."""
    with open(path, "wb") as f:
        f.write(b"P6\n%d %d\n255\n" % (w, h))
        f.write(bytes(rgb) * (w * h))
    return str(path)


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
    assert "--visual-only" not in prep


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


def test_art_and_animation_specs_reach_both_prepares(monkeypatch, tmp_path):
    """A 2-image form with the new per-row fields: 'auto' art and an
    'auto@20:2:8' animation on the primary, a 'video frame' at 3 s on the
    other; a picture file stays a plain path.  The real Prepare media and
    the preview's --visual-only prepare carry the SAME specs into the SAME
    --out, so the selectmedia cache is shared and the card matches the
    picture; only the sound flags differ."""
    _win(monkeypatch)
    clip = tmp_path / "intro clip.mp4"
    clip.write_bytes(bytes(4))
    form = _form(tmp_path, 2)
    form.images[0].anim = "auto"
    form.images[0].anim_start = "20"
    form.images[0].anim_seconds = "2"
    form.images[0].anim_fps = "8"
    form.images[1].art = "video frame"
    form.images[1].art_video = str(clip)
    form.images[1].art_time = "3"
    assert validate_form(form) == []
    wclip = multiboot_tab.wsl(str(clip))
    assert art_spec(form.images[0]) == "auto"
    assert art_spec(form.images[1]) == wclip + "@3"
    assert anim_spec(form.images[0]) == "auto@20:2:8"
    assert anim_spec(form.images[1]) == "none"
    # a picture file is the path; a typed video is a frame at its time (0)
    assert art_spec(ImageRow("x", art=str(tmp_path / "logo.png"))) == \
        multiboot_tab.wsl(str(tmp_path / "logo.png"))
    assert art_spec(ImageRow("x", art=str(clip))) == wclip + "@0"
    assert art_spec(ImageRow("x", art=str(clip), art_time="2.5")) == \
        wclip + "@2.5"
    # a clip with only some fields set spells out the tool's defaults for
    # the rest (explicit rather than defaulted, like every --art N=)
    assert anim_spec(ImageRow("x", anim="auto", anim_fps="8")) == "auto@0:3:8"
    assert anim_spec(ImageRow("x", anim="auto", anim_start="1.5")) == \
        "auto@1.5:3:10"
    assert anim_spec(ImageRow("x", anim="none", anim_start="9")) == "none"
    media = str(tmp_path / "multi" / "media")
    full = _tool_words(prepare_commands(form, media)[0][1])
    vis = _tool_words(multiboot_tab.preview_prepare_commands(form, media)[0][1])
    for prep in (full, vis):
        assert prep[:2] == ["tools/spike2_emu/selectmedia.py", "prepare"]
        assert prep[prep.index("--out") + 1] == multiboot_tab.wsl(media)
        arts = [prep[i + 1] for i, w in enumerate(prep) if w == "--art"]
        anims = [prep[i + 1] for i, w in enumerate(prep) if w == "--anim"]
        assert arts == ["0=auto", "1=" + wclip + "@3"]
        assert anims == ["0=auto@20:2:8", "1=none"]
        assert prep[prep.index("--volume") + 1] == "50"
    assert "--visual-only" not in full
    assert full[full.index("--sound-move") + 1] == "auto"
    assert "--visual-only" in vis
    assert "--sound-move" not in vis and "--sound-confirm" not in vis
    assert preview_prepare_args(form, media) == vis
    # the shell line quotes the space in the clip's name
    assert "'" in _line(prepare_commands(form, media)[0][1])


def test_clip_and_video_frame_fields_are_validated(tmp_path):
    form = _form(tmp_path, 2)
    form.images[1].art = "video frame"
    assert any("pick the video" in e for e in validate_form(form))
    form.images[1].art_video = str(tmp_path / "gone.mp4")
    assert any("video not found" in e for e in validate_form(form))
    (tmp_path / "gone.mp4").write_bytes(bytes(4))
    assert validate_form(form) == []
    form.images[1].art_time = "soon"
    assert any("video frame time" in e for e in validate_form(form))
    form.images[1].art_time = "-1"
    assert any("negative" in e for e in validate_form(form))
    form.images[1].art_time = ""
    form.images[0].anim = "auto"
    form.images[0].anim_seconds = "0"
    assert any("animation length" in e for e in validate_form(form))
    form.images[0].anim_seconds = "2"
    form.images[0].anim_fps = "7.5"
    assert any("whole number" in e for e in validate_form(form))
    form.images[0].anim_fps = "8"
    assert validate_form(form) == []
    # a 'none' animation ignores stale clip fields
    form.images[0].anim = "none"
    form.images[0].anim_fps = "x"
    assert validate_form(form) == []


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
# the preview builders
# --------------------------------------------------------------------------

def test_preview_conf_is_the_form_with_placeholder_devices(tmp_path):
    form = _form(tmp_path, 3, default=1, timeout=20, volume=40)
    form.images[0].title = "STERN 1.59.0"
    form.images[0].subtitle = "Original Stern code"
    form.images[1].title = ""                    # falls back to the name
    form.images[1].subtitle = "1987 cartoon upscale"
    form.images[1].anim = "auto"
    form.images[2].art = "none"
    form.images[2].anim = str(tmp_path / "clip.gif")
    text = write_preview_conf(form)
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    assert lines == [
        "image=p3|STERN 1.59.0|Original Stern code|art0.png||",
        "image=p7|turtles_pro-1_59_0|1987 cartoon upscale|art1.png|anim1.gif|",
        "image=p7:img2|IMG 2|||anim2.gif|",
        "default=1", "timeout=20", "volume=40",
        "font=/usr/local/codeselect/font.ttf"]
    assert text.endswith("\n") and "\r" not in text


def test_fingerprint_changes_with_what_the_frame_shows(tmp_path):
    form = _form(tmp_path, 2)
    fp = preview_fingerprint(form)
    assert fp == preview_fingerprint(_form(tmp_path, 2))     # stable
    for change in (lambda f: setattr(f.images[1], "title", "TMNT"),
                   lambda f: setattr(f.images[1], "subtitle", "x"),
                   lambda f: setattr(f.images[1], "anim", "auto"),
                   lambda f: setattr(f.images[0], "art", "none"),
                   lambda f: setattr(f, "default", 1),
                   lambda f: setattr(f, "timeout", 0),
                   lambda f: setattr(f, "selector_dir", "~/other")):
        other = _form(tmp_path, 2)
        change(other)
        assert preview_fingerprint(other) != fp
    # the clip fields are in the spec, so in the fingerprint
    other = _form(tmp_path, 2)
    other.images[1].anim = "auto"
    a = preview_fingerprint(other)
    other.images[1].anim_start = "20"
    assert preview_fingerprint(other) != a
    # sounds, volume-less things and the bypass flag are not in the picture
    quiet = _form(tmp_path, 2, sound_move="none", bypass=False)
    assert preview_fingerprint(quiet) == fp


def test_ensure_selector_builds_from_the_checkout_then_falls_back(
        monkeypatch, tmp_path):
    """The 'selector' step: ``make`` into the scratch build dir (incremental,
    so it costs nothing once built and always draws with THIS checkout's
    selector), else the tab's installed build; the chosen path is echoed
    after '[preview] selector:' for the snapshot step.  No ``$`` anywhere,
    and ``~/`` outside the quotes (bash expands it in ``BUILD=`` too)."""
    _win(monkeypatch)
    form = _form(tmp_path, 2)
    argv = ensure_selector_args(form, cwd="/mnt/c/repo")
    assert argv[:4] == ["wsl.exe", "-e", "bash", "-lc"]
    line = _line(argv)
    assert line.startswith("cd /mnt/c/repo && if make -C "
                           "/mnt/c/repo/tools/spike2_emu/codeselect "
                           "BUILD=~/emusrc/codeselect-preview "
                           "ROOT=~/spike2root all; then echo "
                           "'[preview] selector:' "
                           "~/emusrc/codeselect-preview/codeselect; "
                           "elif [ -x ~/spike2root/usr/local/codeselect/"
                           "codeselect ]; then echo '[preview] selector:' "
                           "~/spike2root/usr/local/codeselect/codeselect; "
                           "else echo "), line
    assert line.endswith("; exit 1; fi")
    assert "$" not in line and "install" not in line
    assert PREVIEW_BUILD_DIR == "~/emusrc/codeselect-preview"
    # a selector build elsewhere names its own rootfs
    form.selector_dir = "~/my root/usr/local/codeselect"
    line = _line(ensure_selector_args(form, cwd="/mnt/c/repo"))
    assert "ROOT=~/'my root' all" in line
    assert "[ -x ~/'my root/usr/local/codeselect/codeselect' ]" in line
    assert parse_selector_path("make: Nothing to be done for 'all'.\n"
                               "[preview] selector: /home/d/emusrc/"
                               "codeselect-preview/codeselect\n") == \
        "/home/d/emusrc/codeselect-preview/codeselect"
    assert parse_selector_path("[preview] error: no selector") == ""


def test_snapshot_runs_the_selector_under_qemu(monkeypatch, tmp_path):
    _win(monkeypatch)
    conf = str(tmp_path / "multi" / "preview" / "images.conf")
    media = str(tmp_path / "multi" / "media")
    ppm = str(tmp_path / "multi" / "preview" / "frame_1_3.ppm")
    words = preview_snapshot_args("/home/d/emusrc/codeselect-preview/"
                                  "codeselect", conf, media, ppm, 1, 3)
    assert words[:4] == ["qemu-arm-static", "-L", "~/spike2root",
                         "/home/d/emusrc/codeselect-preview/codeselect"]
    assert words[words.index("--snapshot") + 1] == multiboot_tab.wsl(ppm)
    assert words[words.index("--conf") + 1] == multiboot_tab.wsl(conf)
    assert words[words.index("--media") + 1] == multiboot_tab.wsl(media)
    assert words[words.index("--highlight") + 1] == "1"
    assert words[words.index("--anim-frame") + 1] == "3"
    assert words[words.index("--input") + 1] == "none"
    for flag in ("--out", "--last", "--timeout", "--headless"):
        assert flag not in words
    label, argv = snapshot_commands("~/emusrc/codeselect-preview/codeselect",
                                    conf, media, ppm, 1, 3, cwd="/mnt/c/repo")[0]
    assert label == "frame 3"
    line = _line(argv)
    assert line.startswith("cd /mnt/c/repo && qemu-arm-static -L ~/spike2root "
                           "~/emusrc/codeselect-preview/codeselect --snapshot ")
    assert "python3" not in line and "\\" not in line
    # the frame count comes from the selector's own log line
    log = ("codeselect: art: image 0 art0.png -> 546x168\n"
           "codeselect: anim: image 1 24 frames 512x288\n"
           "codeselect: media: 2 art, 1 anim (24 frames), 0 music\n")
    assert parse_anim_frames(log, 1) == 24
    assert parse_anim_frames(log, 0) is None
    assert parse_anim_frames("anim: image 2 stopped after 7 frame(s): x", 2) \
        == 7
    assert parse_anim_frames("anim: image 1 decoded before the first frame "
                             "(4 ms)", 1) is None


def test_fit_factors_are_integers_that_fit_the_box():
    assert fit_factors(1360, 768) == (2, 1)          # the machine's frame
    assert fit_factors(136, 77) == (1, 4)            # a small test frame
    assert fit_factors(680, 384) == (1, 1)
    assert fit_factors(2720, 1536) == (4, 1)
    assert fit_factors(0, 0) == (1, 1)


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


def _wait(root, until, seconds=20):
    deadline = time.time() + seconds
    while not until() and time.time() < deadline:
        root.update()
        time.sleep(0.02)
    root.update()


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


def test_editor_video_frame_and_clip_fields_write_back(tmp_path):
    """The new per-row fields: the clip's start / length / fps live only
    while an animation is set, the video-frame file and time only for the
    'video frame' art; every one lands in the row, the tree cell says so,
    and a re-selected row loads them back."""
    root, panel = _panel()
    try:
        a, b = _images(tmp_path, 2)
        clip = tmp_path / "intro.mp4"
        clip.write_bytes(bytes(4))
        panel.add_image(a)
        panel.add_image(b)
        panel._tree.selection_set("1")
        root.update()
        assert str(panel._video_entry.cget("state")) == "disabled"
        assert all(str(w.cget("state")) == "disabled"
                   for w in panel._clip_widgets)
        panel._ed_anim.set("auto")
        assert all(str(w.cget("state")) == "normal"
                   for w in panel._clip_widgets)
        panel._ed_anim_start.set("20")
        panel._ed_anim_seconds.set("2")
        panel._ed_anim_fps.set("8")
        panel._ed_art.set("video frame")
        assert str(panel._video_entry.cget("state")) == "normal"
        assert str(panel._video_time.cget("state")) == "normal"
        panel._ed_art_video.set(str(clip))
        panel._ed_art_time.set("3")
        row = panel.form().images[1]
        assert (row.anim, row.anim_start, row.anim_seconds, row.anim_fps) == \
            ("auto", "20", "2", "8")
        assert (row.art, row.art_video, row.art_time) == \
            ("video frame", str(clip), "3")
        assert anim_spec(row) == "auto@20:2:8"
        assert art_spec(row) == multiboot_tab.wsl(str(clip)) + "@3"
        vals = panel._tree.item("1")["values"]
        assert vals[4] == "intro.mp4 @3s" and vals[5] == "auto @20s 2s 8fps"
        assert panel.form().images[0].anim_start == ""        # untouched
        # a typed video path in Art enables the time alone
        panel._ed_art.set(str(clip))
        assert str(panel._video_entry.cget("state")) == "disabled"
        assert str(panel._video_time.cget("state")) == "normal"
        panel._ed_art.set("video frame")
        # re-select: row 0 shows blanks, row 1 comes back whole
        panel._tree.selection_set("0")
        root.update()
        assert panel._ed_anim_start.get() == "" and panel._ed_art_video.get() == ""
        panel._tree.selection_set("1")
        root.update()
        assert panel._ed_anim_fps.get() == "8"
        assert panel._ed_art_video.get() == str(clip)
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
        assert panel.render_preview() is False
        assert calls == []
        assert "Fix the form" in panel._pv_status.cget("text")
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


def test_prepared_media_rides_into_the_build_after_a_fresh_prepare(tmp_path):
    """With a media set in <out dir>/media the build names it - and prepares
    it in full FIRST, with the form's specs: a preview leaves a sound-less
    media.json in that dir, and art changed since the last Prepare would
    otherwise not be on the card.  Without one, no prepare (text-only)."""
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
        assert "--visual-only" not in _line(calls[0][0][1])
        # Not prepared yet (no media.json) -> the build does not name it.
        panel._build_card()
        assert [label for label, _ in calls[1]] == ["plan", "build", "verify"]
        assert "--media-dir" not in _line(calls[1][1][1])
        with open(os.path.join(media, "media.json"), "w") as f:
            f.write("{}")
        panel._rows[1].anim = "auto"
        panel._build_card()
        labels = [label for label, _ in calls[2]]
        assert labels == ["prepare", "plan", "build", "verify"]
        prep = _tool_words(calls[2][0][1])
        assert prep[prep.index("--out") + 1] == multiboot_tab.wsl(media)
        assert "--visual-only" not in prep
        assert "--sound-move" in prep
        assert "1=auto" in prep
        assert "--media-dir " + multiboot_tab._q(multiboot_tab.wsl(media)) \
            in _line(calls[2][2][1])
        assert "Preparing the media, then building" in panel._hint.cget("text")
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
        assert str(panel._render_btn.cget("state")) == "disabled"
        # ...and the preview: refused, said on its own status line, and
        # nothing queued for the worker.
        assert panel.render_preview() is False
        assert "already in progress" in panel._pv_status.cget("text")
        assert panel._pv_cache == {}
        panel._set_busy(False)
        assert str(panel._build_btn.cget("state")) == "normal"
        assert str(panel._render_btn.cget("state")) == "normal"
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
        # The checkbox sits with the CARD PATH, never on the button row:
        # that row unmaps "Set up emulator…" first when it overflows, and
        # ~100 px of tickbox there cost exactly that (caught twice by the
        # full parallel suite on 2026-09-02, and David's desktop is 1024x768
        # - narrow enough to lose the button for real).
        assert panel._select_chk.master is not panel._mute_chk.master
        assert panel._select_chk.master is panel._src_entry.master
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
        _wait(root, lambda: done)
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
        _wait(root, lambda: done)
        assert done == [(2, "build", ["build"])]
        assert "SHOULD NOT RUN" not in panel._log_text.get("1.0", "end")
    finally:
        root.destroy()


def test_run_commands_evaluates_a_lazy_argv_from_earlier_output(tmp_path):
    """A step's argv may be a callable of the texts so far - the snapshot
    step needs the binary the selector step printed.  One that raises is a
    failure of that step, not a dead worker."""
    root, panel = _panel()
    done = []
    first = [sys.executable, "-c", "print('[preview] selector: /the/bin')"]

    def second(texts):
        return [sys.executable, "-c", "print('bin=%s')"
                % parse_selector_path(texts["selector"])]

    def third(texts):
        raise RuntimeError("nothing to run")
    try:
        panel._run_commands([("selector", first), ("frame 0", second),
                             ("frame 1", third), ("frame 2", first)],
                            on_done=lambda rc, failed, texts:
                            done.append((rc, failed, sorted(texts))))
        _wait(root, lambda: done)
        assert done == [(1, "frame 1", ["frame 0", "selector"])]
        pane = panel._log_text.get("1.0", "end")
        assert "bin=/the/bin" in pane
        assert "frame 1: nothing to run" in pane
        assert panel._busy is False
    finally:
        root.destroy()


# --------------------------------------------------------------------------
# the preview
# --------------------------------------------------------------------------

def test_load_frame_shows_a_ppm_scaled_into_the_box(tmp_path):
    """Tk reads the selector's binary P6 PPM natively; a 1360x768 frame is
    subsampled by 2 into the 680x384 box, the status names the frame, and
    the spinboxes follow what is shown."""
    root, panel = _panel()
    try:
        big = _ppm(tmp_path / "frame_1_3.ppm", 1360, 768)
        assert panel.load_frame(big, highlight=1, frame=3, total=24) is True
        assert (panel._pv_photo.width(), panel._pv_photo.height()) == (680, 384)
        assert panel._pv_canvas.find_all()                  # one image item
        assert panel._pv_canvas.type(panel._pv_canvas.find_all()[0]) == "image"
        assert panel._pv_status.cget("text") == "Highlight 1: frame 3 of 24"
        assert panel._hl_var.get() == "1" and panel._frame_var.get() == "3"
        assert panel._hl_touched is False       # programmatic, not typed
        assert int(panel._frame_spin.cget("to")) == 23
        small = _ppm(tmp_path / "small.ppm", 136, 77)
        assert panel.load_frame(small, highlight=0, frame=0, total=1)
        assert (panel._pv_photo.width(), panel._pv_photo.height()) == (544, 308)
        assert "a still" in panel._pv_status.cget("text")
        assert panel.load_frame(str(tmp_path / "missing.ppm")) is False
        assert "Cannot load" in panel._pv_status.cget("text")
        assert "Cannot load" in panel._log_text.get("1.0", "end")
    finally:
        root.destroy()


def test_highlight_follows_default_until_typed(tmp_path):
    root, panel = _panel()
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        assert int(panel._hl_spin.cget("to")) == 1
        panel._default_var.set("1")
        assert panel._hl_var.get() == "1"
        panel._hl_var.set("0")                    # typed by hand
        panel._default_var.set("1")
        assert panel._hl_var.get() == "0"
    finally:
        root.destroy()


def _tick(root, panel):
    """One Play step by hand, the timer cancelled so the test is the clock."""
    if panel._play_job is not None:
        root.after_cancel(panel._play_job)
        panel._play_job = None
    panel._play_tick()
    if panel._play_job is not None:
        root.after_cancel(panel._play_job)
        panel._play_job = None


def test_play_advances_through_the_cache_and_stops_when_the_form_changes(
        tmp_path):
    """Play with a fake renderer: frames it asks for land in the cache
    (keyed by form fingerprint, highlight, frame) with the count the
    selector would have logged; the ticks walk 0, 1, 2, 0...; a form
    change stops it with the reason on the status line."""
    root, panel = _panel()
    ppm = _ppm(tmp_path / "f.ppm")
    asked = []

    def fake_render(form, hl, frames):
        fp = preview_fingerprint(form)
        asked.append((hl, list(frames)))
        panel._pv_totals[(fp, hl)] = 3
        for n in frames:
            panel._pv_cache[(fp, hl, n)] = ppm
        return True
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        panel._rows[1].anim = "auto"
        panel._default_var.set("1")
        panel._render_frames = fake_render
        panel._play_var.set(True)
        panel._play_toggled()
        _tick(root, panel)                      # count unknown: frame 0 first
        assert asked == [(1, [0])]
        _tick(root, panel)                      # count known: the rest, in order
        assert asked[-1] == (1, [1, 2])
        for want in ("1", "2", "0", "1"):
            _tick(root, panel)
            assert panel._frame_var.get() == want
        assert "frame 1 of 3 - playing" in panel._pv_status.cget("text")
        assert panel._play_var.get() is True
        panel._rows[1].title = "TMNT 1987 (renamed)"
        _tick(root, panel)
        assert panel._play_var.get() is False
        assert "form changed" in panel._pv_status.cget("text")
        assert panel._play_job is None
        # a still cannot play: refused at the tick, said why
        panel._rows[1].title = "back"
        fp = preview_fingerprint(panel.form())
        panel._pv_totals[(fp, 1)] = 1
        panel._play_var.set(True)
        panel._play_toggled()
        assert panel._play_var.get() is False
        assert "no animation" in panel._pv_status.cget("text")
    finally:
        root.destroy()


def _stand_ins(monkeypatch, tmp_path, fail=None, frames=3):
    """Python children for the three preview steps.  The snapshot one
    writes a small PPM where the real selector would and prints its
    'anim: image N F frames' line; *fail* names the step that exits 2."""
    py = sys.executable
    seen = {"snapshot": []}

    def ensure(form, cwd=None):
        code = ("print('[preview] selector: /fake/codeselect')"
                if fail != "selector" else
                "print('[preview] error: no selector'); raise SystemExit(2)")
        return [("selector", [py, "-c", code])]

    def prepare(form, media_dir, cwd=None):
        seen["media"] = media_dir
        code = ("print('prepare: cached art1.png')" if fail != "prepare" else
                "print('[media] error: ffmpeg missing'); raise SystemExit(2)")
        return [("prepare", [py, "-c", code])]

    def snapshot(binary, conf, media_dir, ppm, hl, n, rootfs="~/r", cwd=None):
        seen["snapshot"].append((binary, conf, media_dir, ppm, hl, n))
        if fail == "frame":
            code = "print('[select] error: bad conf'); raise SystemExit(2)"
        else:
            code = ("import sys; p = sys.argv[1]; "
                    "open(p, 'wb').write(b'P6\\n136 77\\n255\\n' + "
                    "bytes([40, 60, 90]) * (136 * 77)); "
                    "print('anim: image %d %d frames 200x112')" % (hl, frames))
        return [("frame %d" % n, [py, "-c", code, ppm])]
    monkeypatch.setattr(multiboot_tab, "ensure_selector_commands", ensure)
    monkeypatch.setattr(multiboot_tab, "preview_prepare_commands", prepare)
    monkeypatch.setattr(multiboot_tab, "snapshot_commands", snapshot)
    return seen


def test_render_preview_runs_the_pipeline_and_shows_the_frame(tmp_path,
                                                              monkeypatch):
    """Render preview end to end with stand-ins: the conf is written under
    <out dir>/preview, the media goes to the build's <out dir>/media, the
    snapshot gets the binary the selector step named and the frame path,
    the frame count comes off the selector's log line, the frame is shown
    and cached, and a second render of the same form skips the selector
    and prepare steps."""
    root, panel = _panel()
    seen = _stand_ins(monkeypatch, tmp_path, frames=3)
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        panel._rows[1].anim = "auto"
        panel._rows[1].title = "TMNT 1987"
        panel._default_var.set("1")
        assert panel.render_preview() is True
        assert "rendering" in panel._pv_status.cget("text")
        _wait(root, lambda: not panel._busy)
        out = panel._out_var.get()
        pv = multiboot_tab.preview_dir_for(out)
        media = multiboot_tab.media_dir_for(out)
        assert os.path.normpath(seen["media"]) == os.path.normpath(media)
        with open(os.path.join(pv, "images.conf"), "rb") as f:
            conf = f.read()
        assert b"image=p7|TMNT 1987|1987-upscaled|art1.png|anim1.gif|" in conf
        assert b"\r" not in conf
        assert seen["snapshot"] == [(
            "/fake/codeselect", os.path.join(pv, "images.conf"), media,
            os.path.join(pv, "frame_1_0.ppm"), 1, 0)]
        assert os.path.isfile(os.path.join(pv, "frame_1_0.ppm"))
        assert panel._pv_status.cget("text") == "Highlight 1: frame 0 of 3"
        assert panel._pv_photo is not None
        fp = preview_fingerprint(panel.form())
        assert panel._pv_cache == {(fp, 1, 0): os.path.join(pv, "frame_1_0.ppm")}
        assert panel._pv_totals == {(fp, 1): 3}
        assert panel._pv_bin == "/fake/codeselect" and panel._pv_ready == fp
        pane = panel._log_text.get("1.0", "end")
        assert "selector: exit 0" in pane and "frame 0: exit 0" in pane
        # the same form again, another frame: straight to the snapshot
        panel._frame_var.set("2")
        calls = []
        real = panel._run_commands
        panel._run_commands = lambda cmds, **kw: calls.append(
            [label for label, _ in cmds]) or real(cmds, **kw)
        assert panel.render_preview() is True
        _wait(root, lambda: not panel._busy)
        assert calls == [["frame 2"]]
        assert (fp, 1, 2) in panel._pv_cache
        assert panel._pv_status.cget("text") == "Highlight 1: frame 2 of 3"
        # a spinbox move to a cached frame shows it without a render
        panel._frame_var.set("0")
        assert panel._pv_shown == (1, 0)
        # a changed form renders the whole pipeline again
        panel._rows[1].subtitle = "1987 cartoon upscale"
        panel._frame_var.set("0")
        assert panel.render_preview() is True
        _wait(root, lambda: not panel._busy)
        assert calls[-1] == ["selector", "prepare", "frame 0"]
    finally:
        root.destroy()


@pytest.mark.parametrize("fail", ["selector", "prepare", "frame"])
def test_a_failing_preview_step_surfaces_the_error(tmp_path, monkeypatch,
                                                   fail):
    root, panel = _panel()
    _stand_ins(monkeypatch, tmp_path, fail=fail)
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        panel._play_var.set(True)
        panel._play_fp = preview_fingerprint(panel.form())
        assert panel.render_preview() is True
        _wait(root, lambda: not panel._busy)
        status = panel._pv_status.cget("text")
        label = "frame 0" if fail == "frame" else fail
        assert "Preview failed at %s (exit 2)" % label in status
        pane = panel._log_text.get("1.0", "end")
        assert "error:" in pane and "%s: exit 2" % label in pane
        assert "[preview] Preview failed" in pane
        assert panel._pv_cache == {}
        assert panel._play_var.get() is False          # Play stops on error
        assert panel._pv_ready is None
        assert str(panel._render_btn.cget("state")) == "normal"
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
