"""Multi-boot tab (item 90): the pure command builders, the validation that
keeps a bad form off WSL, the boot-menu preview's arithmetic, the status
row's sentences and the form's round trips - :mod:`pinball_decryptor.webui.
multiboot_core`, with no Tk anywhere.

The command builders are tested WITHOUT WSL: they return argv, and what is
asserted is the argv - which tool, which subcommand, which flags, how a title
with spaces is quoted.  The panel as the page drives it is tested in
tests/test_webui_multiboot.py.
"""

import json
import os
import shlex
import sys
from types import SimpleNamespace

import ast

import pytest

from pinball_decryptor.webui import emulate_core, multiboot_core
from pinball_decryptor.webui.multiboot_core import (
    ANIM_LABEL, DEFAULT_SELECTOR_DIR, FRAME_H, FRAME_W, INSPECT_JSON,
    PREVIEW_BUILD_DIR,
    ImageRow, MultibootForm, anim_period_ms, anim_spec, apply_commands,
    art_spec, build_commands, bypass_commands, card_path_state,
    APPLY_TICK, WRITE_BUTTON,
    card_size_view, cell_anim, split_music_source, split_sound_source,
    status_checks,
    cell_art, default_output_path, diff_forms, frame_pattern,
    menu_from_state, parse_snapshot_frames, path_root,
    probe_card_path, rows_from_state,
    edit_status_text, ensure_selector_args, fit_factors, form_from_inspect,
    install_selector_args, install_selector_line,
    host_path, inject_commands, inspect_commands, list_title,
    loaded_media_dir, media_fingerprint, media_specs_changed,
    eta_text, menu_summary, parse_anim_frames, parse_inspect, parse_plan,
    parse_progress, parse_refusal,
    parse_selector_path, plan_commands, prepare_commands, preview_box,
    selector_card,
    preview_fingerprint, preview_prepare_args, preview_snapshot_args,
    rebuild_blockers, snapshot_commands, split_anim_source,
    split_art_source, suggest_title, under_library, validate_form,
    write_preview_conf,
    sound_choices, used_sounds,
    build_args, inject_args)


@pytest.fixture(autouse=True)
def _no_wsl_home_probe(monkeypatch):
    """A root step resolves the desktop user's WSL home on the worker (two
    wsl.exe probes); no test may reach wsl.exe for it - including the
    account probe a missing home falls back to."""
    monkeypatch.setattr(multiboot_core, "wsl_home", lambda: "/home/x")
    monkeypatch.setattr(multiboot_core, "wsl_account", lambda: ("x", "/home/x"))


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
    """The shell line inside a wsl.exe / bash -lc argv.  A ROOT step's argv
    is a callable the worker resolves (item 93; root_command) - resolved
    here the same way, with wsl_home stubbed by the autouse fixture below."""
    if callable(argv):
        argv = argv({})
    return argv[-1]


def _tool_words(argv):
    """The tool's own argv (after ``cd … && python3``), shell-split."""
    words = shlex.split(_line(argv))
    assert words[0] == "cd" and words[2] == "&&" and words[3] == "python3", \
        words
    return words[4:]


def _win(monkeypatch):
    monkeypatch.setattr(multiboot_core.sys, "platform", "win32")


@pytest.fixture(autouse=True)
def _own_preview_knob(tmp_path, monkeypatch):
    """The preview's volume/mute file is the USER's (beside settings.json);
    a test must neither read the knob David left the app at nor move it."""
    monkeypatch.setattr(multiboot_core, "PREVIEW_AUDIO_CTL_FILE",
                        str(tmp_path / "preview_audio_ctl.json"))


# --------------------------------------------------------------------------
# the command builders
# --------------------------------------------------------------------------

def test_two_image_form_builds_plan_build_verify(monkeypatch, tmp_path):
    _win(monkeypatch)
    form = _form(tmp_path, 2)
    cmds = build_commands(form, cwd="/mnt/c/repo")
    # THE SELECTOR STEP FIRST (PAD-105): the menu program the card carries,
    # built and installed before a byte of the card is planned or copied.
    assert [label for label, _ in cmds] == ["selector", "plan", "build",
                                            "verify"]
    for label, argv in cmds:
        if label == "selector":
            # root too (PAD-140): it installs into a filesystem that is
            # usually root's
            assert callable(argv)
            assert argv({})[:3] == ["wsl.exe", "-u", "root"], argv({})
            continue
        if label == "build":
            # the build runs AS ROOT (item 93: it records the card the way
            # update needs, and update loop-mounts it), with the desktop
            # user's HOME so ~/spike2root is still theirs
            assert callable(argv)
            argv = argv({})
            assert argv[:8] == ["wsl.exe", "-u", "root", "-e", "env",
                                "HOME=/home/x", "bash", "-lc"], argv
        else:
            assert argv[:4] == ["wsl.exe", "-e", "bash", "-lc"], argv
        assert _line(argv).startswith("cd /mnt/c/repo && python3 "
                                      "tools/spike2_emu/mkmulticard.py ")
        assert "\\" not in _line(argv)          # Windows paths would not open
    prim = multiboot_core.wsl(form.images[0].path)
    extra = multiboot_core.wsl(form.images[1].path)
    out = multiboot_core.wsl(form.out)
    step = dict(cmds)
    plan = _tool_words(step["plan"])
    assert plan[:2] == ["tools/spike2_emu/mkmulticard.py", "plan"]
    assert plan[2:6] == ["--primary", prim, "--extra", extra]
    assert plan[plan.index("--layout") + 1] == "auto" and "--cache-dir" in plan
    build = _tool_words(step["build"])
    assert build[1] == "build"
    assert build[2:6] == ["--primary", prim, "--extra", extra]
    assert build[build.index("--out") + 1] == out
    assert build[build.index("--selector-dir") + 1] == DEFAULT_SELECTOR_DIR
    assert build[build.index("--layout") + 1] == "auto"
    assert build[build.index("--titles") + 1] == "IMG 0;IMG 1"
    assert build[build.index("--timeout") + 1] == "15"
    assert build[build.index("--default") + 1] == "0"
    assert build[build.index("--volume") + 1] == "50"
    assert "--bypass-validation" in build          # on by default (David; item 98 made it safe)
    assert "--media-dir" not in build              # nothing prepared
    assert "--force" not in build
    assert "--subtitles" not in build              # none given
    verify = _tool_words(step["verify"])
    assert verify[1:3] == ["verify", "--card"] and verify[3] == out
    assert verify[4:8] == ["--primary", prim, "--extra", extra]
    assert verify[-2:] == ["--selector-dir", DEFAULT_SELECTOR_DIR]


def test_three_image_form_carries_every_extra_and_the_media(monkeypatch,
                                                           tmp_path):
    _win(monkeypatch)
    media = tmp_path / "multi" / "media"
    form = _form(tmp_path, 3, media_dir=str(media), force=True,
                 timeout=0, default=2, volume=35, sound_move="synth",
                 sound_confirm="none")
    form.images[1].subtitle = "1987 cartoon"
    form.images[1].anim = "auto"
    cmds = dict(build_commands(form))
    build = _tool_words(cmds["build"])
    extras = [build[i + 1] for i, w in enumerate(build) if w == "--extra"]
    assert extras == [multiboot_core.wsl(r.path) for r in form.images[1:]]
    assert "--bypass-validation" in build            # always on
    assert build[build.index("--media-dir") + 1] == multiboot_core.wsl(
        str(media))
    assert "--force" in build
    assert build[build.index("--timeout") + 1] == "0"
    assert build[build.index("--default") + 1] == "2"
    assert build[build.index("--subtitles") + 1] == ";1987 cartoon;"
    assert build[build.index("--volume") + 1] == "35"
    verify = _tool_words(cmds["verify"])
    assert verify.count("--extra") == 2
    assert verify[verify.index("--media-dir") + 1] == multiboot_core.wsl(
        str(media))
    # ...and the media preparation: the images (auto art / clips come off
    # them), then --art/--anim/--music N=value for EVERY image, then the
    # globals.
    prep = _tool_words(prepare_commands(form, str(media))[0][1])
    assert prep[:2] == ["tools/spike2_emu/selectmedia.py", "prepare"]
    assert prep[2:4] == ["--primary", multiboot_core.wsl(form.images[0].path)]
    assert [prep[i + 1] for i, w in enumerate(prep) if w == "--extra"] == \
        [multiboot_core.wsl(r.path) for r in form.images[1:]]
    assert prep[prep.index("--out") + 1] == multiboot_core.wsl(str(media))
    arts = [prep[i + 1] for i, w in enumerate(prep) if w == "--art"]
    anims = [prep[i + 1] for i, w in enumerate(prep) if w == "--anim"]
    musics = [prep[i + 1] for i, w in enumerate(prep) if w == "--music"]
    assert arts == ["0=auto", "1=auto", "2=auto"]
    assert anims == ["0=none", "1=auto", "2=none"]
    assert musics == ["0=none", "1=none", "2=none"]
    assert prep[prep.index("--sound-move") + 1] == "synth"
    assert prep[prep.index("--volume") + 1] == "35"
    assert "--visual-only" not in prep
    # --sound-confirm appends: the bare menu-wide value first, then one
    # N=value per image.  A row with no confirm of its own is written
    # 'none' EXPLICITLY, so a row that used to have one really loses it.
    confirms = [prep[i + 1] for i, w in enumerate(prep)
                if w == "--sound-confirm"]
    assert confirms == ["none", "0=none", "1=none", "2=none"]
    form.images[1].confirm = "synth"
    prep2 = _tool_words(prepare_commands(form, str(media))[0][1])
    assert [prep2[i + 1] for i, w in enumerate(prep2)
            if w == "--sound-confirm"] == ["none", "0=none", "1=synth",
                                           "2=none"]


def test_media_files_cross_as_wsl_paths(monkeypatch, tmp_path):
    _win(monkeypatch)
    wav = tmp_path / "my click.wav"
    wav.write_bytes(bytes(4))
    form = _form(tmp_path, 2, sound_move=str(wav))
    form.images[1].art = str(tmp_path / "logo.png")
    prep = _tool_words(prepare_commands(form, str(tmp_path / "media"))[0][1])
    assert prep[prep.index("--sound-move") + 1] == multiboot_core.wsl(str(wav))
    assert "\\" not in _line(prepare_commands(form, str(tmp_path / "m"))[0][1])
    arts = [prep[i + 1] for i, w in enumerate(prep) if w == "--art"]
    assert arts[1] == "1=" + multiboot_core.wsl(str(tmp_path / "logo.png"))


def test_art_and_animation_specs_reach_both_prepares(monkeypatch, tmp_path):
    """A 2-image form with the new per-row fields: 'auto' art and an
    'auto@20' animation on the primary, a 'video frame' at 3 s on the
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
    form.images[1].art = "video frame"
    form.images[1].art_video = str(clip)
    form.images[1].art_time = "3"
    assert validate_form(form) == []
    wclip = multiboot_core.wsl(str(clip))
    assert art_spec(form.images[0]) == "auto"
    assert art_spec(form.images[1]) == wclip + "@3"
    assert anim_spec(form.images[0]) == "auto@20"
    assert anim_spec(form.images[1]) == "none"
    # a picture file is the path; a typed video is a frame at its time (0)
    assert art_spec(ImageRow("x", art=str(tmp_path / "logo.png"))) == \
        multiboot_core.wsl(str(tmp_path / "logo.png"))
    assert art_spec(ImageRow("x", art=str(clip))) == wclip + "@0"
    assert art_spec(ImageRow("x", art=str(clip), art_time="2.5")) == \
        wclip + "@2.5"
    # ONLY A START is ever spelled out: the loop's length and rate are the
    # tool's own contract (5 s at the source's frame rate), never a request
    # from the form - a form asking '13 s at 30 fps' was rendered at 2 fps
    assert anim_spec(ImageRow("x", anim="auto")) == "auto"
    assert anim_spec(ImageRow("x", anim="auto", anim_start="1.5")) == \
        "auto@1.5"
    assert anim_spec(ImageRow("x", anim="auto", anim_start="0")) == "auto"
    assert anim_spec(ImageRow("x", anim="none", anim_start="9")) == "none"
    media = str(tmp_path / "multi" / "media")
    full = _tool_words(prepare_commands(form, media)[0][1])
    vis = _tool_words(multiboot_core.preview_prepare_commands(form, media)[0][1])
    for prep in (full, vis):
        assert prep[:2] == ["tools/spike2_emu/selectmedia.py", "prepare"]
        assert prep[prep.index("--out") + 1] == multiboot_core.wsl(media)
        arts = [prep[i + 1] for i, w in enumerate(prep) if w == "--art"]
        anims = [prep[i + 1] for i, w in enumerate(prep) if w == "--anim"]
        assert arts == ["0=auto", "1=" + wclip + "@3"]
        assert anims == ["0=auto@20", "1=none"]
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
    form.images[0].anim_start = "soon"
    assert any("animation start" in e for e in validate_form(form))
    form.images[0].anim_start = "-2"
    assert any("animation start" in e for e in validate_form(form))
    form.images[0].anim_start = "20"
    assert validate_form(form) == []
    # a 'none' animation ignores a stale start
    form.images[0].anim = "none"
    form.images[0].anim_start = "x"
    assert validate_form(form) == []


def test_titles_with_spaces_are_quoted_for_the_shell(monkeypatch, tmp_path):
    _win(monkeypatch)
    form = _form(tmp_path, 2)
    form.images[0].title = "STERN 1.59"
    form.images[1].title = "TMNT 1987"
    form.images[1].subtitle = "1987 cartoon upscale (1.59.0)"
    line = _line(dict(build_commands(form))["build"])
    assert "--titles 'STERN 1.59;TMNT 1987'" in line
    assert "--subtitles ';1987 cartoon upscale (1.59.0)'" in line
    build = _tool_words(dict(build_commands(form))["build"])
    assert build[build.index("--titles") + 1] == "STERN 1.59;TMNT 1987"


def test_blank_titles_fall_back_to_the_image_name(tmp_path):
    form = _form(tmp_path, 2)
    form.images[0].title = ""
    build = _tool_words(dict(build_commands(form, cwd="/x"))["build"])
    assert build[build.index("--titles") + 1] == \
        "turtles_pro-1_59_0;IMG 1"


def test_selector_dir_tilde_stays_expandable(monkeypatch, tmp_path):
    """``~/`` must sit OUTSIDE the quotes: bash expands it there, and a
    ``$HOME`` would be eaten by wsl.exe's re-parse before bash saw it."""
    _win(monkeypatch)
    form = _form(tmp_path, 2)
    line = _line(dict(build_commands(form))["build"])
    assert " --selector-dir ~/spike2root/usr/local/codeselect " in line
    assert "$" not in line
    form.selector_dir = "~/my root/sel dir"
    line = _line(dict(build_commands(form))["build"])
    assert " --selector-dir ~/'my root/sel dir' " in line


def test_linux_runs_bash_directly(monkeypatch, tmp_path):
    monkeypatch.setattr(multiboot_core.sys, "platform", "linux")
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
    want = multiboot_core._q(multiboot_core.wsl(str(tmp_path / "checkout")))
    assert line.startswith("cd %s && " % want), line


def test_bypass_command_targets_an_existing_card(monkeypatch, tmp_path):
    _win(monkeypatch)
    card = str(tmp_path / "TMNT 1987" / "multi" / "card.raw")
    words = _tool_words(bypass_commands(card)[0][1])
    assert words == ["tools/spike2_emu/mkmulticard.py", "bypass", "--card",
                     multiboot_core.wsl(card)]
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
        "default=1", "timeout=20", "heading=SELECT GAME CODE",
        # PAD-183: the preview draws the text the size the card will
        "text_size=uniform",
        # ...and PAD-190: with the card's own two lines under the cards
        "counter=on", "countdown_word=starting", "volume=40",
        "font=/usr/local/codeselect/font.ttf", "theme=midnight"]
    assert text.endswith("\n") and "\r" not in text
    # PAD-135: an emptied heading reaches the preview as 'heading=', which is
    # what the selector reads as no line across the top
    form.heading = ""
    assert "heading=\n" in write_preview_conf(form)
    form.heading = "THE BEATLES JUKEBOX"
    assert "heading=THE BEATLES JUKEBOX\n" in write_preview_conf(form)


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
    # sounds and volume-less things are not in the picture
    quiet = _form(tmp_path, 2, sound_move="none")
    assert preview_fingerprint(quiet) == fp


def test_a_frame_file_is_named_after_the_form_that_drew_it(tmp_path):
    """THE FINGERPRINT IS IN THE FILE NAME.  Without it, change a title,
    let it render, change it back: the reverted form has no cache entry, so
    a render is queued - and it wrote to the very name the newer form had
    already written, so either form could be shown the other's picture."""
    pv = str(tmp_path / "preview")
    a = preview_fingerprint(_form(tmp_path, 2))
    other = _form(tmp_path, 2)
    other.images[1].title = "TMNT 1987"
    b = preview_fingerprint(other)
    assert a != b
    assert multiboot_core.frame_path(pv, a, 1, 0) != \
        multiboot_core.frame_path(pv, b, 1, 0)
    assert os.path.basename(multiboot_core.frame_path(pv, a, 1, 3)) == \
        "frame_%s_1_3.ppm" % a
    # ...and the ones no form can ask for again are found so they can go
    os.makedirs(pv)
    for name in ("frame_%s_0_0.ppm" % a, "frame_%s_1_2.ppm" % a,
                 "frame_%s_0_0.ppm" % b, "images.conf", "notes.txt"):
        open(os.path.join(pv, name), "w").close()
    assert sorted(os.path.basename(p) for p in
                  multiboot_core.stale_frames(pv, b)) == [
        "frame_%s_0_0.ppm" % a, "frame_%s_1_2.ppm" % a]
    assert multiboot_core.stale_frames(str(tmp_path / "nope"), b) == []


def test_scaled_size_keeps_the_aspect_ratio_in_both_directions():
    """The smooth path: whatever the column's width, the picture fits it
    with its shape intact (Tk's own PhotoImage only halves and thirds)."""
    from pinball_decryptor.webui.multiboot_core import scaled_size
    assert scaled_size(1360, 768, 680, 384) == (680, 384)
    assert scaled_size(1360, 768, 500, 384) == (500, 282)   # width-limited
    assert scaled_size(1360, 768, 900, 384) == (680, 384)   # height-limited
    assert scaled_size(1360, 768, 431, 384) == (431, 243)   # no whole step
    assert scaled_size(136, 77, 680, 384) == (678, 384)     # scaled UP
    assert scaled_size(0, 0, 100, 100) == (1, 1)


def test_the_card_run_installs_the_menu_program_first(monkeypatch,
                                                     tmp_path):
    """PAD-105.  The tab built a selector for its PREVIEW and installed
    nothing, so a machine that had never run buildselect.sh by hand met the
    builder's refusal seconds into a build - 'selector dir ... is not a
    directory' - with nothing to act on.  Every writing run now starts with
    ensureselect.sh, which is the RIG's own answer (ensurebuild.sh: unpack
    the guest filesystem from the card when there is none, build the menu
    program when it is missing, rebuild it when these sources are newer).

    It runs AS ROOT with the desktop HOME (PAD-140 - see the test below),
    carries the primary image (what a first-run rootfs is built from) and
    names the rootfs the selector directory sits in.  No ``$`` anywhere and
    ``~/`` outside the quotes, like every other line this tab hands to
    wsl.exe.
    """
    _win(monkeypatch)
    form = _form(tmp_path, 2)
    step = install_selector_args(form, cwd="/mnt/c/repo")
    assert callable(step)            # resolved on the worker, like build
    argv = step({})
    assert argv[:8] == ["wsl.exe", "-u", "root", "-e", "env",
                        "HOME=/home/x", "bash", "-lc"], argv
    line = _line(argv)
    assert line == ("cd /mnt/c/repo && PAD_ROOT=~/spike2root bash "
                    "tools/spike2_emu/ensureselect.sh %s"
                    % multiboot_core.wsl(form.images[0].path)), line
    assert "$" not in line
    # a selector build under another rootfs names THAT rootfs
    form.selector_dir = "~/my root/usr/local/codeselect"
    assert "PAD_ROOT=~/'my root' bash" in _line(install_selector_args(
        form, cwd="/mnt/c/repo"))


def test_the_menu_program_installs_as_root_into_roots_filesystem(
        monkeypatch, tmp_path):
    """★ PAD-140.  The Emulate tab's Start is ``wsl -u root`` and unpacks
    ~/spike2root as root, so on a machine that had run a game the selector
    step - then a USER step - could not create /usr/local/codeselect, and a
    first multi-boot build stopped on coreutils' words for that:

        install: cannot change permissions of
        '/home/home/spike2root/usr/local/codeselect': No such file or directory

    It installs as root now, with the desktop HOME so ``~`` is still the
    user's rootfs (buildselect.sh hands the tree back).  The shapes a root
    step has to get right, one each:"""
    _win(monkeypatch)
    form = _form(tmp_path, 2)
    user_line = _line(install_selector_args(form, cwd="/mnt/c/repo"))
    # WSL will not say who it logs in as: the user step it used to be, not a
    # refusal - the build step right after it says the sentence.
    monkeypatch.setattr(multiboot_core, "wsl_home", lambda: None)
    monkeypatch.setattr(multiboot_core, "wsl_account", lambda: ("", ""))
    argv = install_selector_args(form, cwd="/mnt/c/repo")({})
    assert argv[:4] == ["wsl.exe", "-e", "bash", "-lc"], argv
    assert argv[-1] == user_line
    # a root-default distro (PAD-114): root's own home, like the build
    monkeypatch.setattr(multiboot_core, "wsl_account", lambda: ("root", "/root"))
    argv = install_selector_args(form, cwd="/mnt/c/repo")({})
    assert argv[:6] == ["wsl.exe", "-u", "root", "-e", "env", "HOME=/root"]
    assert argv[-1] == user_line
    # Linux: nothing there unpacks the filesystem as root, and `sudo -n`
    # would refuse a machine that builds today
    monkeypatch.setattr(multiboot_core.sys, "platform", "linux")
    argv = install_selector_args(form, cwd="/mnt/c/repo")
    assert not callable(argv) and argv[:2] == ["bash", "-lc"], argv


def test_a_selector_dir_of_somebody_elses_is_checked_never_written():
    """PAD_MULTIBOOT_SELECTOR is the only way to move the directory, and a
    path that is not a rootfs's own ``/usr/local/codeselect`` is not one the
    app may install into: it is tested, and the refusal says whose variable
    put it there."""
    line = install_selector_line("~/somewhere/else", "/mnt/d/card.raw")
    assert line.startswith("if [ -x ~/somewhere/else/codeselect ] && "
                           "[ -f ~/somewhere/else/select.sh ]; then"), line
    assert "ensureselect.sh" not in line and "PAD_ROOT" not in line
    assert multiboot_core.SELECTOR_READY_LINE in line
    assert "PAD_MULTIBOOT_SELECTOR" in line
    # ...and it refuses in the words the tab reads back as a refusal
    assert parse_refusal(multiboot_core.SELECTOR_ERROR + " no menu program")
    assert line.endswith("; exit 1; fi")


def test_the_rig_script_and_the_tab_spell_the_selector_lines_the_same():
    """ensureselect.sh prints the ready line and the refusals; the tab reads
    both prefixes (:data:`_REFUSAL_PREFIXES` decides what a failed run says
    instead of an exit code).  Two files, one spelling."""
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(multiboot_core.__file__))), "..", "tools",
        "spike2_emu", "ensureselect.sh")
    with open(os.path.normpath(path), encoding="utf-8") as fh:
        text = fh.read()
    assert 'echo "[selector] menu program: $SEL_DIR"' in text
    assert multiboot_core.SELECTOR_READY_LINE == "[selector] menu program:"
    assert 'ERR="%s"' % multiboot_core.SELECTOR_ERROR in text
    assert "pad_ensure_rootfs" in text and "pad_ensure_select" in text
    # ONE LINE PER REFUSAL.  parse_refusal takes the LAST line carrying the
    # prefix, so a sentence split over three echoes reached the tab as its
    # last third - 'selector failed (exit 1) - above. Expected at ...',
    # measured on the way to this ticket's own after shot.
    echoes = [n for n, ln in enumerate(text.splitlines())
              if 'echo "$ERR' in ln]
    assert echoes and all(n + 1 not in echoes for n in echoes), echoes


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
                           "elif [ ! -d ~/spike2root/usr/lib ]; then echo "),\
        line
    assert line.endswith("; exit 1; fi")
    assert "$" not in line
    # THE PREVIEW INSTALLS NOTHING - the target is `all`, never `install`.
    # Asked of the build itself rather than of the whole line, because the
    # refusal at the end of it names `apt install make` (PAD-126).
    assert "install" not in line.split("elif ! command -v make", 1)[0]
    # ...and with no card to unpack one from, nothing runs before the make
    assert line.startswith("cd /mnt/c/repo && if make")
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


def test_selector_card_prefers_the_card_in_hand(tmp_path):
    """Which card a guest filesystem may be unpacked from.  The LOADED card
    first: a card somebody else built names its images' sources on THEIR
    machine, so row 0's path is a path that is not here, while the card file
    the tab was pointed at is."""
    here = tmp_path / "downloaded.multi.raw"
    here.write_bytes(b"x")
    form = _form(tmp_path, 2)
    row0 = form.images[0].path
    form.images[0].path = "G:/somebody elses/machine.raw"
    assert selector_card(form, str(here)) == str(here)
    # no loaded card: row 0, when row 0 is on this machine
    form.images[0].path = row0
    assert selector_card(form, "") == row0
    # neither is here, and a directory is not a card either
    form.images[0].path = "G:/somebody elses/machine.raw"
    assert selector_card(form, "G:/gone.raw") == ""
    assert selector_card(form, str(tmp_path)) == ""
    form.images = []
    assert selector_card(form, "") == ""


def test_ensure_selector_unpacks_a_guest_filesystem_when_there_is_none(
        monkeypatch, tmp_path):
    """A machine that has never unpacked one cannot compile the menu program
    at all - it is built against the CARD's own headers and libraries - so
    the step runs the rig's ensureselect.sh first, from a card that IS on
    this machine.  Guarded twice (no filesystem, and the card is there), so
    a healthy machine pays one `[ -d ]` per keystroke render, and never
    fatally: a preview would rather fall through to an installed selector
    than stop."""
    _win(monkeypatch)
    form = _form(tmp_path, 2)
    card = tmp_path / "downloaded.multi.raw"
    card.write_bytes(b"x")
    quoted = multiboot_core._q(multiboot_core.wsl(str(card)))
    line = _line(ensure_selector_args(form, cwd="/mnt/c/repo",
                                      card=str(card)))
    head, _make = line.split("; if make", 1)
    assert head == ("cd /mnt/c/repo && if [ ! -d ~/spike2root/usr/lib ] "
                    "&& [ -f %s ]; then PAD_ROOT=~/spike2root bash "
                    "tools/spike2_emu/ensureselect.sh %s; fi"
                    % (quoted, quoted)), head
    assert "$" not in line
    # the refusal names the missing filesystem, not a selector path nobody
    # has heard of, which is all the old one said
    assert ("elif [ ! -d ~/spike2root/usr/lib ]; then echo '[preview] error: "
            "no selector - the menu program is built against the machine") \
        in line
    assert "unpacked one yet (nothing at ~/spike2root)" in line


def test_the_preview_names_make_rather_than_calling_the_build_a_failure(
        monkeypatch, tmp_path):
    """★ PAD-126.  The preview line's first word IS `make`, so a PC without
    one fails it with `make: command not found` and then meets the fallback's
    sentence about a build that "failed" - which names a path and no package.
    Nothing about the emulator needs make, so a machine that runs every title
    can be exactly this machine, and a user's was."""
    _win(monkeypatch)
    line = _line(ensure_selector_args(_form(tmp_path, 2), cwd="/mnt/c/repo"))
    assert "elif ! command -v make >/dev/null 2>&1; then" in line
    assert "this Linux has no make (on Debian/Ubuntu: apt install make)" \
        in line
    # ...and it is asked AFTER the installed selector and the missing
    # filesystem: a preview would rather draw with what is installed than
    # explain a tool it did not need.
    assert line.index("elif [ -x ") < line.index("command -v make")
    assert line.index("[ ! -d ") < line.index("command -v make")


def test_snapshot_runs_the_selector_under_qemu(monkeypatch, tmp_path):
    _win(monkeypatch)
    conf = str(tmp_path / "multi" / "preview" / "images.conf")
    media = str(tmp_path / "multi" / "media")
    ppm = str(tmp_path / "multi" / "preview" / "frame_1_3.ppm")
    words = preview_snapshot_args("/home/d/emusrc/codeselect-preview/"
                                  "codeselect", conf, media, ppm, 1, 3)
    n = len(multiboot_core.QEMU_ARM)
    assert words[:n] == multiboot_core.QEMU_ARM
    assert words[n:n + 3] == ["-L", "~/spike2root",
                              "/home/d/emusrc/codeselect-preview/codeselect"]
    assert words[words.index("--snapshot") + 1] == multiboot_core.wsl(ppm)
    assert words[words.index("--conf") + 1] == multiboot_core.wsl(conf)
    assert words[words.index("--media") + 1] == multiboot_core.wsl(media)
    assert words[words.index("--highlight-card") + 1] == "1"
    assert "--highlight" not in words, "the preview names a CARD, not an image"
    assert "--loading-out" not in words, "asked for, never assumed"
    assert "--roll-state" not in words, "asked for, never assumed"
    rolled = preview_snapshot_args("/bin/cs", conf, media, ppm, 1, 3,
                                   roll_state="/x/roll.state")
    assert rolled[rolled.index("--roll-state") + 1] == \
        multiboot_core.wsl("/x/roll.state")
    with_loading = preview_snapshot_args("/bin/cs", conf, media, ppm, 1, 3,
                                         loading="/x/loading_ab_1.ppm")
    assert with_loading[with_loading.index("--loading-out") + 1] == \
        multiboot_core.wsl("/x/loading_ab_1.ppm")
    assert words[words.index("--anim-frame") + 1] == "3"
    assert words[words.index("--input") + 1] == "none"
    for flag in ("--out", "--last", "--timeout", "--headless"):
        assert flag not in words
    label, argv = snapshot_commands("~/emusrc/codeselect-preview/codeselect",
                                    conf, media, ppm, 1, 3, cwd="/mnt/c/repo")[0]
    assert label == "frame 3"
    line = _line(argv)
    assert line.startswith("cd /mnt/c/repo && sh -c ")
    assert (" qemu-arm -L ~/spike2root "
            "~/emusrc/codeselect-preview/codeselect --snapshot ") in line
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
    # ...and into a box that is not the default one
    assert fit_factors(1360, 768, 454, 256) == (3, 1)


def test_preview_box_is_a_whole_fraction_of_the_selectors_frame():
    """Tk PhotoImage scales by whole numbers only, so the box is always
    1360x768 over one - never 0.62 of it."""
    assert preview_box(1400, 800) == (1360, 768, 1)
    assert preview_box(700, 500) == (680, 384, 2)
    assert preview_box(680, 384) == (680, 384, 2)
    assert preview_box(679, 500) == (454, 256, 3)     # 1 px short of half
    assert preview_box(500, 300) == (454, 256, 3)
    assert preview_box(500, 255) == (340, 192, 4)     # too short for a third
    assert preview_box(10, 10) == (340, 192, 4)       # never smaller
    for avail_w, avail_h in ((1400, 800), (700, 500), (500, 300), (10, 10)):
        w, h, k = preview_box(avail_w, avail_h)
        assert (w, h) == (-(-FRAME_W // k), -(-FRAME_H // k))


def test_the_table_cells_and_the_menu_summary_say_it_in_a_phrase():
    """What the images table's own cells carry - the settings are COLUMNS
    now, not one phrase summarising all of them."""
    assert cell_art(ImageRow("x.raw")) == "auto"
    assert cell_art(ImageRow("x.raw", art="none")) == "none"
    assert cell_art(ImageRow("x.raw", art="video frame",
                             art_video="D:/a.mov", art_time="21")) == \
        "a.mov @21s"
    assert cell_art(ImageRow("x.raw", art="D:/logo.png")) == "logo.png"
    assert cell_anim(ImageRow("x.raw", anim="auto", anim_start="20")) == \
        "auto @20s"
    assert cell_anim(ImageRow("x.raw", anim="auto")) == "auto"
    on_card = ImageRow("", art="art0.png", art_on_card=True,
                       music="music0.wav", music_on_card=True, anim="none")
    assert cell_art(on_card) == "art0.png (on the card)"
    # the title cell carries what is wrong with the .raw, since the table
    # has no room for a column of paths
    assert list_title(ImageRow("", title="STERN"), 0) == \
        "STERN  [no source recorded]"
    assert list_title(ImageRow("D:/gone.raw", title="1987"), 1) == \
        "1987  [not on this machine]"
    assert list_title(ImageRow("", device="/dev/mmcblk0p3"), 2) == \
        "image 2  [no source recorded]"
    form = MultibootForm(images=[], volume=35, timeout=0, default=1,
                         sound_move="D:/a b/click.wav",
                         machine_volume=False)
    assert menu_summary(form) == (
        "sounds click.wav / auto  ·  volume 35  ·  wait for START  ·  "
        "default 1  ·  theme midnight  ·  \"SELECT GAME CODE\"")
    form.machine_volume = True
    assert "volume 35 (the machine's own on the card)" in menu_summary(form)
    # PAD-135: the heading, quoted and cut - and named in words when there is none
    form.heading = ""
    assert menu_summary(form).endswith("no heading")
    form.heading = "A HEADING FAR TOO LONG FOR ONE SUMMARY LINE"
    assert menu_summary(form).endswith('"A HEADING FAR TOO LONG FOR …"')
    assert "15 s countdown" in menu_summary(MultibootForm(images=[]))


def test_the_media_fingerprint_moves_only_for_media(tmp_path):
    """The split that makes the preview cheap: text is not in it, media is."""
    form = _form(tmp_path, 2)
    mfp = media_fingerprint(form)
    for change in (lambda f: setattr(f.images[1], "title", "TMNT"),
                   lambda f: setattr(f.images[1], "subtitle", "x"),
                   lambda f: setattr(f, "timeout", 0),
                   lambda f: setattr(f, "default", 1),
                   lambda f: setattr(f, "selector_dir", "~/other")):
        other = _form(tmp_path, 2)
        change(other)
        assert media_fingerprint(other) == mfp
        # ...but the PICTURE fingerprint does move, so the frame is redrawn
        assert preview_fingerprint(other) != preview_fingerprint(form)
    for change in (lambda f: setattr(f.images[0], "art", "none"),
                   lambda f: setattr(f.images[1], "anim", "auto"),
                   lambda f: setattr(f.images[1], "music", "D:/bed.wav"),
                   lambda f: setattr(f, "sound_move", "synth"),
                   lambda f: setattr(f, "volume", 35)):
        other = _form(tmp_path, 2)
        change(other)
        assert media_fingerprint(other) != mfp


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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path semantics (D:/)")
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
    rig = emulate_core.DEFAULT_RIG_DIR
    if not os.path.isfile(os.path.join(rig, "mkmulticard.py")):
        pytest.skip("mkmulticard.py not present")
    if rig not in sys.path:
        sys.path.insert(0, rig)
    import mkmulticard
    ours = {multiboot_core._norm(p) for p in multiboot_core.LIBRARY_PREFIXES}
    theirs = {multiboot_core._norm(p)
              for p in mkmulticard.FORBIDDEN_OUTPUT_PREFIXES}
    assert ours == theirs


PLAN_TEXT = (
    "p7   0x83 15353856     13402110     ...\n"
    "images: 0=/dev/mmcblk0p3, 1=/dev/mmcblk0p7\n"
    "image-size 0 /dev/mmcblk0p3 6861881344 turtles_pro-1_59_0.Release\n"
    "image-size 1 /dev/mmcblk0p7:img1 6000000000 turtles_pro-1_59_0.1987\n"
    "image-size overhead 1861174272 boot + rootfs + data + dump + slack\n"
    "image: 28755968 sectors = 14723055616 bytes (14.72 GB)\n"
    "  fits Stern 8G  image size 7861174272: NO (spare -6861881344)\n"
    "  fits Stern 16G image size 15494807552: YES (spare 771751936)\n"
    "  fits Stern 32G image size 30359420928: YES (spare 15636365312)\n")


def test_plan_output_carries_the_size_of_every_image():
    info = parse_plan(PLAN_TEXT)
    assert info["bytes"] == 14723055616
    assert info["fits"]["8G"] == (False, -6861881344)
    assert info["fits"]["16G"] == (True, 771751936)
    # the per-image block, which is what the strip's bands are drawn from
    assert info["sizes"] == [
        (0, "/dev/mmcblk0p3", 6861881344, "turtles_pro-1_59_0.Release"),
        (1, "/dev/mmcblk0p7:img1", 6000000000, "turtles_pro-1_59_0.1987")]
    assert info["overhead"] == 1861174272
    # ...and a size the tool could not measure is None, never a zero band
    unknown = parse_plan("image-size 2 /dev/mmcblk0p7:img2 ? whatever.raw\n")
    assert unknown["sizes"] == [(2, "/dev/mmcblk0p7:img2", None, "whatever.raw")]


def test_the_size_view_names_the_card_to_buy():
    view = card_size_view(parse_plan(PLAN_TEXT))
    assert view["known"] and view["need"] == "16 GB" and not view["over"]
    assert view["head"] == "16 GB"
    # the bar is drawn against THE CARD YOU BUY, not the image
    assert view["scale"] == 14723055616 + 771751936
    assert "14.72 GB of code" in view["detail"]
    assert "0.77 GB spare" in view["detail"]
    # a band per image, then the card's own overhead, and they add up
    assert [kind for _l, _b, kind in view["bands"]] == \
        ["image", "image", "overhead"]
    assert sum(b for _l, b, _k in view["bands"]) == view["total"]
    assert view["bands"][0][0].endswith("turtles_pro-1_59_0.Release")


def test_the_size_view_says_when_nothing_holds_it():
    text32 = PLAN_TEXT.replace(
        "16G image size 15494807552: YES (spare 771751936)",
        "16G image size 15494807552: NO (spare -1)")
    assert card_size_view(parse_plan(text32))["need"] == "32 GB"
    none = text32.replace("32G image size 30359420928: YES",
                          "32G image size 30359420928: NO")
    view = card_size_view(parse_plan(none))
    assert view["over"] and view["head"] == "too big" and view["need"] is None
    # the overflow is measured from the biggest card there is
    assert view["cap"] == 14723055616 + 15636365312
    assert view["scale"] == view["total"]      # the bar runs past the mark
    assert "Drop an image" in view["detail"]
    assert card_size_view(parse_plan(""))["known"] is False
    assert card_size_view(None)["bands"] == []


def test_suggest_title_splits_the_card_name():
    assert suggest_title("turtles_pro-1_59_0.Release.8G.sdcard.raw") == \
        ("turtles_pro-1_59_0", "Release")
    if sys.platform == "win32":                 # a backslash path is Windows' alone
        assert suggest_title(r"D:\x\turtles_pro-1_59_0.1987-upscaled.8G.sdcard.raw") \
            == ("turtles_pro-1_59_0", "1987-upscaled")
    assert suggest_title("card.img") == ("card", "")


def test_capability_is_spike2_and_jjp_only(manufacturers_by_key):
    """Multi-boot is Stern's Spike 2 era and Jersey Jack (item 118: the same
    tab with a JJP backend behind it) - and nobody else."""
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
    assert manufacturers_by_key["jjp"].capabilities.multiboot is True
    for key, mfr in manufacturers_by_key.items():
        if key not in ("stern", "jjp"):
            assert getattr(mfr.capabilities, "multiboot", False) is False, key


# --------------------------------------------------------------------------
# what an image shows, and the sounds it can offer
# --------------------------------------------------------------------------


def _prepared_media(tmp_path, sources, name="media"):
    """A prepared media directory: one ``art<N>.png`` per source spec, and
    the media.json that says which spec each was made from."""
    from PIL import Image
    media = tmp_path / name
    media.mkdir(exist_ok=True)
    rows = []
    for i, spec in enumerate(sources):
        art = "art%d.png" % i
        Image.new("RGB", (338, 190), (20, 40 + i, 80)).save(str(media / art))
        rows.append({"art": art, "anim": None, "music": None, "confirm": None,
                     "art_source": spec})
    (media / "media.json").write_text(json.dumps({"images": rows}),
                                      encoding="utf-8")
    return str(media)


def test_still_for_row_says_where_the_preview_can_draw_from(tmp_path):
    """BEN, PAD-187: "Add in a preview of what it will look like".  What it
    can draw RIGHT NOW is one of four things, and which one is a question
    about the row, the files on this machine and what the tools last made -
    never about the dialog, which is why it is a function."""
    mb = multiboot_core
    paths = _images(tmp_path, 2)
    picture = tmp_path / "poster.png"
    picture.write_bytes(bytes(4))
    clip = tmp_path / "intro.mp4"
    clip.write_bytes(bytes(4))
    media = _prepared_media(tmp_path, ["auto", "auto"])
    form = MultibootForm(images=[ImageRow(path=paths[0], title="A"),
                                 ImageRow(path=paths[1], title="B")],
                         out=str(tmp_path / "card.multi.raw"))
    manifest = mb.read_manifest(media)

    # the game's own logo, and the tools have made it from exactly that
    assert mb.still_for_row(form, 0, media, manifest) == \
        ("rendered", os.path.join(media, "art0.png"))
    # ...but not once the row asks for something else: the file beside it is
    # then a picture of the choice that was just left
    mb.set_media(form.images[0], "picture", str(picture))
    assert mb.still_for_row(form, 0, media, manifest) == ("file", str(picture))
    # a video is the frame it starts on, whether or not it has been rendered
    mb.set_media(form.images[1], "video", str(clip), start="20")
    assert mb.still_for_row(form, 1, media, manifest) == \
        ("video", (str(clip), "20"))
    # a file that is not on this machine is nothing to draw
    mb.set_media(form.images[1], "picture", str(tmp_path / "gone.png"))
    assert mb.still_for_row(form, 1, media, manifest) == ("none", "")
    # ...and neither is a media set that has not been prepared
    mb.set_media(form.images[1], "logo")
    assert mb.still_for_row(form, 1, "", {}) == ("none", "")
    assert mb.still_for_row(form, 9, media, manifest) == ("none", "")

    # A RANDOM CARD'S ART IS ITS OWN FILE, numbered by group and recorded in
    # the manifest's own `groups` row - not images[1], which is some other
    # game's (the same trap manifest_sounds had to be taught).
    mb.set_media(form.images[0], "logo")
    group = mb.set_group_media(
        ImageRow(path="", title="RANDOM",
                 members=[mb.MemberRow(path=p) for p in paths], keep=True),
        "stack")
    form.images.append(group)
    from PIL import Image
    gart = os.path.join(media, "gart0.png")
    Image.new("RGB", (338, 190), (90, 90, 90)).save(gart)
    doc = mb.read_manifest(media)
    doc["groups"] = [{"art": "gart0.png", "art_source": "stack"}]
    with open(os.path.join(media, "media.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f)
    manifest = mb.read_manifest(media)
    assert mb.still_for_row(form, 2, media, manifest) == ("rendered", gart)
    mb.set_group_media(group, "mosaic")
    assert mb.still_for_row(form, 2, media, manifest) == ("none", "")


def test_media_kind_and_cell_media_read_every_row_shape():
    """The dialog's one choice, derived from any row the builders can read -
    the pairs the flat list cannot make included."""
    Row = ImageRow
    kind, cell, file_ = (multiboot_core.media_kind, multiboot_core.cell_media,
                         multiboot_core.media_file)
    assert (kind(Row("x")), cell(Row("x")), file_(Row("x"))) == \
        ("logo", "logo", "")
    r = Row("x", art="none")
    assert (kind(r), cell(r)) == ("none", "none")
    r = Row("x", art="D:/a/logo.png")
    assert (kind(r), cell(r), file_(r)) == \
        ("picture", "logo.png", "D:/a/logo.png")
    r = Row("x", anim="auto", anim_start="20")
    assert (kind(r), cell(r), file_(r)) == \
        ("attract", "attract video @20s", "")
    r = Row("x", art="D:/c/intro.mp4", art_time="3", anim="D:/c/intro.mp4",
            anim_start="3")
    assert (kind(r), cell(r), file_(r)) == \
        ("video", "intro.mp4 @3s", "D:/c/intro.mp4")
    # the still at another second than the clip's start: both halves
    r.art_time = "5"
    assert cell(r) == "intro.mp4 @5s + intro.mp4 @3s"
    # a still off a video with no clip yet (an older form): 'video', and
    # the cell says what there is, not what an edit would make of it
    r = Row("x", art="video frame", art_video="D:/c/intro.mp4",
            art_time="3")
    assert (kind(r), cell(r), file_(r)) == \
        ("video", "intro.mp4 @3s", "D:/c/intro.mp4")
    r = Row("x", art="D:/c/intro.mp4")
    assert (kind(r), cell(r), file_(r)) == \
        ("video", "intro.mp4 @0s", "D:/c/intro.mp4")
    # a logo still with a file animation (the dropped pair): both halves
    r = Row("x", anim="D:/c/intro.mp4")
    assert (kind(r), cell(r), file_(r)) == \
        ("video", "logo + intro.mp4", "D:/c/intro.mp4")
    r = Row("x", art="D:/a/logo.png", anim="auto")
    assert (kind(r), cell(r)) == ("attract", "logo.png + attract video")
    # the card's own files
    r = Row("x", art="art0.png", art_on_card=True)
    assert (kind(r), cell(r), file_(r)) == \
        ("card", "art0.png (on the card)", "")
    r.anim, r.anim_on_card = "anim0.gif", True
    assert cell(r) == "art0.png (on the card) + anim0.gif (on the card)"
    r = Row("x", anim="anim0.gif", anim_on_card=True)
    assert (kind(r), cell(r)) == ("card", "logo + anim0.gif (on the card)")


def test_set_media_writes_the_pair_each_choice_means():
    set_media = multiboot_core.set_media
    r = set_media(ImageRow("x", art="D:/a.png", anim="auto", anim_start="8"),
                  "logo")
    assert (r.art, r.anim, r.anim_start) == ("auto", "none", "")
    r = set_media(ImageRow("x"), "none")
    assert (r.art, r.anim) == ("none", "none")
    r = set_media(ImageRow("x"), "picture", " D:/a.png ")
    assert (r.art, r.anim) == ("D:/a.png", "none")
    r = set_media(ImageRow("x"), "attract", "D:/ignored.mp4", "20")
    assert (r.art, r.anim, r.anim_start) == ("auto", "auto", "20")
    assert anim_spec(r) == "auto@20"
    r = set_media(ImageRow("x"), "video", "D:/c/intro.mp4", "3")
    assert (r.art, r.art_time, r.anim, r.anim_start) == \
        ("D:/c/intro.mp4", "3", "D:/c/intro.mp4", "3")
    assert art_spec(r).endswith("intro.mp4@3")
    assert anim_spec(r).endswith("intro.mp4@3")
    # the card's own files are left exactly alone...
    r = ImageRow("x", art="art0.png", art_on_card=True, anim="anim0.gif",
                 anim_on_card=True)
    assert set_media(r, "card", "D:/x.png") is r
    assert (r.art, r.art_on_card, r.anim, r.anim_on_card) == \
        ("art0.png", True, "anim0.gif", True)
    # ...and any other choice clears the flags
    set_media(r, "logo")
    assert (r.art_on_card, r.anim_on_card) == (False, False)
    with pytest.raises(ValueError):
        set_media(ImageRow("x"), "hologram")


def test_the_confirm_box_names_the_sound_it_will_play():
    """BEN, PAD-184: "the properties page does not show the correct sound
    but will play the correct sound with the play button".  The box holds
    the SETTING and the list column holds the ANSWER, so the box carries
    the answer too - in the column's own words."""
    note = multiboot_core.image_confirm_note
    # inheriting: the menu's sound, NAMED, however the row spells inherit
    for spell in ("", "menu", "MENU", "none"):
        assert note(spell, r"D:\wav\ComeTogether.wav") == \
            "Plays ComeTogether.wav, the menu's own."
        assert note(spell, "auto") == "Plays auto, the menu's own."
    # ...and when neither has one, nothing plays - which is worth saying
    assert note("", "none") == ("Plays nothing: neither this image nor the "
                                "menu has a confirm sound.")
    assert note("menu", "") == ("Plays nothing: neither this image nor the "
                                "menu has a confirm sound.")
    # its own: the file's NAME, which is what the box could not show (it
    # holds the whole path) and what the column has always shown
    assert note(r"C:\Users\ben\My Sounds\Godzilla Roar.wav", "auto") == \
        "Plays Godzilla Roar.wav, this image's own."
    assert note('"C:\\x\\Roar.wav"', "auto") == \
        "Plays Roar.wav, this image's own."
    assert note("synth", "auto") == "Plays synth, this image's own."
    # ...including a name a LOAD read off the card, with no source recorded
    assert note("confirm2.wav", "auto") == \
        "Plays confirm2.wav, this image's own."


def test_used_sounds_are_the_files_this_menu_already_has(tmp_path):
    """C FB: "the drop down list, populated with all current selections
    would be a nice addition".  One list for all four sound boxes - the
    menu's own two and every image's music and confirm - with the words,
    the duplicates, the files on somebody else's machine and the names a
    load read off the card all left out of it."""
    a = tmp_path / "ComeTogether.wav"
    b = tmp_path / "bed" / "Medley.wav"
    b.parent.mkdir()
    for p in (a, b):
        p.write_bytes(bytes(4))
    gone = str(tmp_path / "not-here.wav")
    rows = [ImageRow("x", music="none", confirm=str(a)),
            # the same file again, and spelled with quotes round it
            ImageRow("y", music=str(b), confirm='"%s"' % a),
            # a load's own values: a NAME on the card, not a path here
            ImageRow("z", music="music2.wav", music_on_card=True,
                     confirm="confirm2.wav", confirm_on_card=True),
            # ...and a card built on somebody else's PC
            ImageRow("w", music=gone, confirm="auto@7")]
    assert used_sounds(rows, "auto", "synth", "") == [str(a), str(b)]
    # the menu's own two are in it as well
    assert used_sounds([], str(b), "auto") == [str(b)]
    # and the labels are file NAMES, because the list is 26 characters wide
    assert sound_choices([str(a), str(b)]) == [("ComeTogether.wav", str(a)),
                                               ("Medley.wav", str(b))]
    # ...unless two of them share one, and then the folder comes too
    twin = tmp_path / "bed" / "ComeTogether.wav"
    twin.write_bytes(bytes(4))
    assert sound_choices([str(a), str(twin)]) == [
        ("ComeTogether.wav  (%s)" % tmp_path.name, str(a)),
        ("ComeTogether.wav  (bed)", str(twin))]


# --------------------------------------------------------------------------
# the animation: ONE run, then played from memory
# --------------------------------------------------------------------------

def test_a_run_of_frames_is_one_command_line():
    """``--frames K`` and a printf pattern for a run; K == 1 is left
    exactly as it was - no ``--frames`` at all - because that is the
    selector's own single-frame path, where the --snapshot value is a file
    NAME and a '%' in it is a '%'."""
    pat = frame_pattern("/x/preview", "abc123", 1)
    assert pat.replace("\\", "/") == "/x/preview/frame_abc123_1_%d.ppm"
    assert pat % 7 == multiboot_core.frame_path("/x/preview", "abc123", 1, 7)
    one = preview_snapshot_args("/bin/cs", "/x/c.conf", "/x/media",
                                "/x/f.ppm", 1, 3)
    assert "--frames" not in one
    run = preview_snapshot_args("/bin/cs", "/x/c.conf", "/x/media", pat, 1, 3,
                                frames=16)
    assert run[run.index("--frames") + 1] == "16"
    assert run[run.index("--anim-frame") + 1] == "3"       # where it starts
    assert run[run.index("--snapshot") + 1] == multiboot_core.wsl(pat)
    assert run[-2:] == ["--input", "none"]
    # ...and a run is ONE step, under its own name
    assert snapshot_commands("/bin/cs", "/x/c.conf", "/x/m", pat, 1, 3,
                             frames=16)[0][0] == ANIM_LABEL
    assert snapshot_commands("/bin/cs", "/x/c.conf", "/x/m", "/x/f.ppm", 1,
                             3)[0][0] == "frame 3"


def test_a_per_cent_in_the_card_path_does_not_kill_the_whole_run():
    """codeselect's check_frames_pattern counts EVERY '%' in the --snapshot
    value, not only the one the tab appended - so a card under
    'D:/Pinball/100% builds' made it refuse the command outright (exit 2,
    nothing written) and Play alone died in that folder.  '%%' is the
    printf spelling of a literal per-cent, which is what the selector asks
    for and what Python's own %-formatting reads back the same way."""
    pat = frame_pattern("D:/Pinball/100% builds/preview", "abc123", 1)
    assert pat.replace("\\", "/") == \
        "D:/Pinball/100%% builds/preview/frame_abc123_1_%d.ppm"
    # exactly one bare %d, which is the selector's whole rule
    assert pat.replace("%%", "").count("%") == 1
    # ...and it still names the file the cache and the sweep know
    assert pat % 7 == multiboot_core.frame_path(
        "D:/Pinball/100% builds/preview", "abc123", 1, 7)
    # a literal '%d' in the folder is escaped the same way and stops being
    # a second conversion
    odd = frame_pattern("/x/100%d builds/preview", "ab", 0)
    assert odd.replace("%%", "").count("%") == 1
    assert odd % 3 == multiboot_core.frame_path("/x/100%d builds/preview",
                                               "ab", 0, 3)


def test_which_frames_a_run_wrote_is_read_off_the_selectors_own_lines():
    """A run decides for itself which frames it writes - it starts at
    --anim-frame, wraps, and trims K to the animation's length - so the
    files are read back rather than predicted."""
    log = (
        "codeselect: anim: image 1 4 frames 512x288\n"
        "codeselect: snapshot: 8 frames asked for, image 1 has 4: 4 written\n"
        "[select] snapshot: /p/frame_ab_1_3.ppm 1360x768, highlight 1 (TMNT "
        "1987) from --highlight, frame 3 of 4, timeout 15 s, invert 0, font "
        "/f.ttf, media /m, footer \"LEFT / RIGHT FLIPPER: choose\"\n"
        "[select] snapshot: /p/frame_ab_1_0.ppm 1360x768, highlight 1 (TMNT "
        "1987) from --highlight, frame 0 of 4, timeout 15 s, invert 0, font "
        "/f.ttf, media /m, footer \"LEFT / RIGHT FLIPPER: choose\"\n")
    assert parse_snapshot_frames(log) == [("/p/frame_ab_1_3.ppm", 3, 4),
                                          ("/p/frame_ab_1_0.ppm", 0, 4)]
    # a path with spaces in it still comes back whole (the size after it is
    # what ends it), and a still says 'of 0'
    still = ("[select] snapshot: /my cards/f_0.ppm 1360x768, highlight 0 (A) "
             "from --highlight, frame 0 of 0, timeout 15 s, invert 0, font "
             "/f.ttf, media /m, footer \"x\"")
    assert parse_snapshot_frames(still) == [("/my cards/f_0.ppm", 0, 0)]
    assert parse_snapshot_frames("") == []
    assert parse_snapshot_frames("codeselect: anim: image 1 4 frames") == []


def test_the_loading_frame_is_swept_with_its_form(tmp_path):
    """One per card rather than per frame, and cleared by the same sweep - or
    preview/ grows a file per form for as long as the tab is open."""
    mb = multiboot_core
    pv = str(tmp_path)
    keep, gone = "abc123", "def456"
    for fp in (keep, gone):
        for name in (mb.loading_path(pv, fp, 0), mb.frame_path(pv, fp, 0, 0)):
            with open(name, "wb") as f:
                f.write(b"x")
    stale = [os.path.basename(x) for x in mb.stale_frames(pv, keep)]
    assert sorted(stale) == ["frame_def456_0_0.ppm", "loading_def456_0.ppm"]


def _gif(path, frames=4, delay_ms=100):
    """A GIF of *frames* solid frames at *delay_ms* each - what selectmedia
    leaves in the media directory and what codeselect ticks on."""
    Image = pytest.importorskip("PIL.Image")
    pics = []
    for n in range(frames):
        # every frame really different: the encoder collapses duplicates
        # into one, summing their delays, and then there is no animation
        pic = Image.new("RGB", (32, 8), (0, 0, 0))
        pic.putpixel((n % 32, 0), (255, 0, 0))
        pics.append(pic.convert("P"))
    pics[0].save(str(path), save_all=True, append_images=pics[1:],
                 duration=delay_ms, loop=0)
    return str(path)


def test_a_playing_clip_does_not_hold_its_file_open(tmp_path):
    """THE PREVIEW MUST NOT PIN THE MEDIA IT IS PLAYING.  Every card animates
    all the time, and the media directory is on a Windows drive - so a handle
    held here is a file the next `selectmedia prepare` cannot unlink, which is
    what stopped the preview redrawing after David deleted an image."""
    pytest.importorskip("PIL.Image")
    path = _gif(tmp_path / "anim2.gif", frames=3)
    clip = multiboot_core.ClipFrames(path, (8, 4))
    assert clip.frame(0) is not None
    os.remove(path)                 # EACCES on Windows if a handle is open
    assert not os.path.exists(path)
    # ...and it goes on playing from the bytes it read
    assert clip.n == 3
    assert clip.frame(2).size == (8, 4)
    assert clip.loop_ms() > 0
    clip.close()


def test_an_animation_plays_at_the_rate_it_was_rendered_at(tmp_path):
    """THE GIF'S OWN DELAY IS THE RATE - the machine ticks on
    ``a->delay_ms[frame]`` - and until the GIF is there, the contract's
    30 fps (the row has no rate field any more: the one it had was a
    request selectmedia clamped, and a stale one made a 2 fps clip).
    Clamped, because a file can say anything."""
    assert anim_period_ms(ImageRow("", anim="auto"), delay_ms=100) == 100
    assert anim_period_ms(delay_ms=33) == 33
    assert anim_period_ms(ImageRow("", anim="auto")) == 33         # 30 fps
    assert anim_period_ms() == 33
    assert anim_period_ms(delay_ms=0) == 33
    assert anim_period_ms(delay_ms=None) == 33
    assert anim_period_ms(delay_ms=1) == 16
    assert anim_period_ms(delay_ms=9000) == 2000


# --------------------------------------------------------------------------
# loading a card back into the form (Load card… / Apply to card)
# --------------------------------------------------------------------------

def _rich_report(tmp_path, clip=None, armed=True):
    """What ``inspect --json`` prints for a v2 card built by this tab: two
    images whose .raw sources are on this machine, art from a source spec
    (one 'auto', one a frame of a video), a clip with its own start / length
    / fps, no music.  *armed* leaves the second tree waiting for the bypass
    (the card the tool builds is fully patched; ``armed=False`` is that
    realistic state, which is what :func:`_loaded` uses so a plain load has
    no pending change - the bypass is always on now)."""
    a, b = _images(tmp_path, 2)
    clip = clip or str(tmp_path / "attract.mov")
    if not os.path.isfile(clip):
        open(clip, "wb").write(bytes(4))
    return {
        "card": str(tmp_path / "multi" / "card.multi.raw"),
        "size": 15494807552, "layout": "parts",
        "partitions": [{"index": 3, "device": "/dev/mmcblk0p3"},
                       {"index": 7, "device": "/dev/mmcblk0p7"}],
        "images": [
            {"index": 0, "device": "/dev/mmcblk0p3", "title": "STERN 1.59.0",
             "subtitle": "Original Stern code", "art": "art0.png",
             "anim": None, "music": None, "art_source": "auto",
             "anim_source": "none", "source": multiboot_core.wsl(a),
             "source_exists": True, "title_dir": "turtles",
             "bypass": "bypassed"},
            {"index": 1, "device": "/dev/mmcblk0p7", "title": "TMNT 1987",
             "subtitle": "1987 cartoon upscale", "art": "art1.png",
             "anim": "anim1.gif", "music": None,
             "art_source": multiboot_core.wsl(clip) + "@21",
             "anim_source": "auto@20:2:8", "source": multiboot_core.wsl(b),
             "source_exists": True, "title_dir": "turtles",
             "bypass": "armed" if armed else "bypassed"}],
        "timeout": 20, "default": 1, "volume": 35, "mixer_volume": None,
        "sound_move": "synth", "sound_confirm": "none",
        "font": "/usr/local/codeselect/font.ttf",
        "media": [{"name": "art0.png", "bytes": 4096},
                  {"name": "art1.png", "bytes": 4096},
                  {"name": "anim1.gif", "bytes": 90112}],
        "has_media_json": True, "has_build_json": True,
        "selector": {"bytes": 41272, "version": "codeselect 1.0"},
        "warnings": []}


def _degraded_report(tmp_path):
    """...and for a card an older mkmulticard wrote: no build.json (no
    sources, no timeout, no sounds), media the manifest cannot explain, and
    one image whose .raw is not on this machine."""
    gone = str(tmp_path / "gone" / "turtles_pro-1_59_0.1987.8G.sdcard.raw")
    return {
        "card": str(tmp_path / "v1.multi.raw"), "size": 15494807552,
        "layout": "parts",
        "partitions": [{"index": 3, "device": "/dev/mmcblk0p3"}],
        "images": [
            {"index": 0, "device": "/dev/mmcblk0p3", "title": "STERN",
             "subtitle": "", "art": "art0.png", "anim": None,
             "music": "music0.wav", "art_source": None, "anim_source": None,
             "source": None, "source_exists": False, "title_dir": "turtles",
             "bypass": "bypassed"},
            {"index": 1, "device": "/dev/mmcblk0p7", "title": "1987",
             "subtitle": "", "art": None, "anim": None, "music": None,
             "art_source": None, "anim_source": None,
             "source": multiboot_core.wsl(gone), "source_exists": False,
             "title_dir": "turtles", "bypass": "bypassed"}],
        "timeout": None, "default": None, "volume": None,
        "mixer_volume": None, "sound_move": None,
        "sound_confirm": "confirm.wav", "font": None,
        "media": [{"name": "art0.png", "bytes": 4096},
                  {"name": "music0.wav", "bytes": 176400}],
        "has_media_json": False, "has_build_json": False,
        "selector": {"bytes": 41272, "version": None},
        "warnings": ["no build.json: this card was written by an older "
                     "mkmulticard - the images it was built from are not "
                     "recorded"]}


def test_inspect_commands_read_the_card_and_extract_its_media(monkeypatch,
                                                              tmp_path):
    """The load's two steps: the tool's own table for the pane, then the
    same read as JSON with the card's media dropped where the tab can draw
    it.  Neither writes the card."""
    _win(monkeypatch)
    card = str(tmp_path / "multi" / "card.multi.raw")
    media = loaded_media_dir(card)
    cmds = inspect_commands(card, media, cwd="/mnt/c/repo")
    assert [label for label, _ in cmds] == ["inspect", INSPECT_JSON]
    table = _tool_words(cmds[0][1])
    assert table[:4] == ["tools/spike2_emu/mkmulticard.py", "inspect",
                         "--card", multiboot_core.wsl(card)]
    assert "--json" not in table and "--media-out" not in table
    js = _tool_words(cmds[1][1])
    assert js[1:4] == ["inspect", "--card", multiboot_core.wsl(card)]
    assert "--json" in js
    assert js[js.index("--media-out") + 1] == multiboot_core.wsl(media)
    assert "\\" not in _line(cmds[1][1])
    # the media dir is per card, beside it - two cards in one folder do not
    # write over each other
    other = str(tmp_path / "multi" / "other.multi.raw")
    assert loaded_media_dir(other) != media
    assert os.path.basename(media) == "media-card.multi"


def test_inject_argv_spells_out_every_menu_field(monkeypatch, tmp_path):
    """An inject keeps the card's own value for a flag left off, so the tab
    passes them all - subtitles included, or clearing one would not clear
    it.  No image is named: nothing is copied."""
    _win(monkeypatch)
    media = tmp_path / "media-card.multi"
    form = _form(tmp_path, 2, timeout=0, default=1, volume=35,
                 media_dir=str(media))
    form.images[1].subtitle = "1987 cartoon"
    card = str(tmp_path / "multi" / "card.multi.raw")
    cmds = inject_commands(form, card, cwd="/mnt/c/repo")
    assert [label for label, _ in cmds] == ["inject"]
    words = _tool_words(cmds[0][1])
    assert words[1:4] == ["inject", "--card", multiboot_core.wsl(card)]
    assert words[words.index("--selector-dir") + 1] == DEFAULT_SELECTOR_DIR
    assert words[words.index("--titles") + 1] == "IMG 0;IMG 1"
    assert words[words.index("--subtitles") + 1] == ";1987 cartoon"
    assert words[words.index("--timeout") + 1] == "0"
    assert words[words.index("--default") + 1] == "1"
    assert words[words.index("--volume") + 1] == "35"
    assert words[words.index("--media-dir") + 1] == multiboot_core.wsl(
        str(media))
    for flag in ("--primary", "--extra", "--out", "--bypass-validation",
                 "--layout", "--force"):
        assert flag not in words, flag
    # subtitles are passed even when every one is empty (that is the clear)
    form.images[1].subtitle = ""
    words = _tool_words(inject_commands(form, card)[0][1])
    assert words[words.index("--subtitles") + 1] == ";"


def test_apply_commands_add_the_prepare_and_the_bypass_only_when_asked(
        monkeypatch, tmp_path):
    _win(monkeypatch)
    media = str(tmp_path / "media-card.multi")
    form = _form(tmp_path, 2, media_dir=media)
    card = str(tmp_path / "multi" / "card.multi.raw")
    # the selector leads every writing run: an inject writes the menu
    # program itself onto the card, so it needs one (PAD-105)
    assert [n for n, _ in apply_commands(form, card, media)] == [
        "selector", "inject", "inspect", INSPECT_JSON]
    labels = [n for n, _ in apply_commands(form, card, media, prepare=True,
                                           bypass=True)]
    assert labels == ["selector", "prepare", "inject", "bypass", "inspect",
                      INSPECT_JSON]
    cmds = apply_commands(form, card, media, prepare=True, bypass=True,
                          refresh=False)
    prep = _tool_words(dict(cmds)["prepare"])
    assert prep[1] == "prepare"
    assert prep[prep.index("--out") + 1] == multiboot_core.wsl(media)
    assert "--visual-only" not in prep
    byp = _tool_words(dict(cmds)["bypass"])
    assert byp[1:4] == ["bypass", "--card", multiboot_core.wsl(card)]


def test_parse_inspect_finds_the_report_and_the_refusal():
    assert parse_inspect('{"layout": "parts"}') == {"layout": "parts"}
    # a profile line in front of it must not lose the report
    assert parse_inspect('hello\n{"a": [1, 2]}\n') == {"a": [1, 2]}
    assert parse_inspect("not json at all") is None
    assert parse_inspect("") is None
    # the spelling the tool REALLY uses, which is why a failed load used to
    # say "see the tool output" and never the reason
    assert parse_refusal(
        "reading\n[card] error: no /usr/local/codeselect on its p2\n") == \
        "no /usr/local/codeselect on its p2"
    assert parse_refusal("reading\nrefused: not a multi card\n") == \
        "not a multi card"
    assert parse_refusal("all fine") == ""


def test_media_specs_come_back_as_the_specs_that_made_them(monkeypatch,
                                                           tmp_path):
    """art_source / anim_source round-trip: what a load puts in the row
    builds the very spec the card recorded, so an apply writes it back
    unchanged."""
    _win(monkeypatch)
    assert host_path("/mnt/d/Pinball/x.mov") == "D:/Pinball/x.mov"
    assert host_path("/home/david/x.png") == "/home/david/x.png"
    assert split_art_source("auto") == ("auto", "", "")
    assert split_art_source(None) == ("auto", "", "")
    assert split_art_source("/mnt/d/a.png") == ("D:/a.png", "", "")
    assert split_art_source("/mnt/d/clip.mov@21") == ("D:/clip.mov", "", "21")
    assert split_anim_source("none") == ("none", "")
    assert split_anim_source("auto@20") == ("auto", "20")
    assert split_anim_source("/mnt/d/x.gif") == ("D:/x.gif", "")
    # a length and a rate a card recorded are DROPPED on the way in: the
    # loop is the tool's contract now, so the next apply re-renders that
    # clip like every other (5 s at the source's own frame rate)
    assert split_anim_source("auto@20:2:8") == ("auto", "20")
    assert split_anim_source("/mnt/d/x.mp4@3:3:10") == ("D:/x.mp4", "3")
    for spec in ("auto", "none", "/mnt/d/clip.mov@21"):
        art, video, at = split_art_source(spec)
        row = ImageRow(path="x.raw", art=art, art_video=video, art_time=at)
        assert art_spec(row) == spec
    for spec in ("none", "auto", "auto@20", "/mnt/d/x.gif"):
        anim, start = split_anim_source(spec)
        row = ImageRow(path="x.raw", anim=anim, anim_start=start)
        assert anim_spec(row) == spec


def test_a_rich_report_becomes_the_whole_form(monkeypatch, tmp_path):
    _win(monkeypatch)
    info = _rich_report(tmp_path)
    card = str(tmp_path / "multi" / "card.multi.raw")
    form, warnings = form_from_inspect(info, card, "")
    assert warnings == []
    assert form.out == card
    assert (form.timeout, form.default, form.volume) == (20, 1, 35)
    assert (form.sound_move, form.sound_confirm) == ("synth", "none")
    a, b = _images(tmp_path, 2)
    assert [multiboot_core._norm(r.path) for r in form.images] == \
        [multiboot_core._norm(a), multiboot_core._norm(b)]
    assert [r.title for r in form.images] == ["STERN 1.59.0", "TMNT 1987"]
    assert form.images[1].subtitle == "1987 cartoon upscale"
    assert form.images[0].art == "auto" and form.images[0].anim == "none"
    assert form.images[1].art_time == "21"
    assert art_spec(form.images[1]) == info["images"][1]["art_source"]
    # the card's 'auto@20:2:8' loads as the clip from 20 s: its length and
    # rate are the tool's contract now, not the card's
    assert anim_spec(form.images[1]) == "auto@20"
    assert not any(multiboot_core.on_card_fields(r) for r in form.images)
    assert rebuild_blockers(form) == []


def test_a_degraded_report_keeps_the_cards_own_files_and_says_so(monkeypatch,
                                                                 tmp_path):
    """A card with no build.json: nulls become the tab's defaults, the media
    the manifest cannot explain stays as the card's file names, and every
    gap is a warning rather than an error."""
    _win(monkeypatch)
    info = _degraded_report(tmp_path)
    form, warnings = form_from_inspect(info, str(tmp_path / "v1.multi.raw"),
                                       "")
    assert (form.timeout, form.default, form.volume) == (15, 0, 50)
    # no sound_move on the card at all -> none; a confirm.wav whose source
    # nothing records -> the tab's default, said out loud
    assert form.sound_move == "none" and form.sound_confirm == "auto"
    row0, row1 = form.images
    assert (row0.art, row0.art_on_card) == ("art0.png", True)
    assert (row0.music, row0.music_on_card) == ("music0.wav", True)
    assert row0.anim == "none" and row0.anim_on_card is False
    assert row0.path == "" and row0.device == "/dev/mmcblk0p3"
    assert row1.art == "none" and multiboot_core.on_card_fields(row1) == []
    assert row1.path.endswith("1987.8G.sdcard.raw")
    assert multiboot_core.on_card_fields(row0) == [
        ("art", "art0.png"), ("music", "music0.wav")]
    text = "\n".join(warnings)
    assert "older mkmulticard" in text            # the tool's own warning
    assert "does not record which .raw" in text   # image 0 has no source
    assert "not on this machine" in text          # image 1's is gone
    assert "confirm sound" in text and "confirm.wav" in text
    assert "no source recorded" in text and "(on the card)" in text
    # the card's own files are not paths on this machine, and are not
    # looked for - but they do stop a NEW card being built from this form
    assert not [e for e in validate_form(form, sources=False)
                if "not found" in e]
    blockers = "\n".join(rebuild_blockers(form))
    assert "art0.png" in blockers and "music0.wav" in blockers


def test_diff_forms_splits_menu_changes_from_image_list_changes(tmp_path):
    """The two buckets: everything an inject can write, and the image list,
    which only a rebuild can change."""
    before = _form(tmp_path, 3)
    after = _form(tmp_path, 3)
    assert diff_forms(before, after) == ([], [])
    assert media_specs_changed(before, after) is False

    def changed(**kw):
        f = _form(tmp_path, 3)
        for k, v in kw.items():
            setattr(f, k, v)
        return diff_forms(before, f)
    after.images[1].title = "TMNT 1987"
    after.images[2].subtitle = "orchestral"
    after.images[0].anim = "auto"
    assert diff_forms(before, after) == (
        ["title", "subtitle", "animation"], [])
    assert media_specs_changed(before, after) is True
    assert changed(volume=35) == (["volume"], [])
    assert changed(timeout=0) == (["countdown"], [])
    assert changed(default=2) == (["default"], [])
    assert changed(sound_move="synth") == (["move sound"], [])
    assert media_specs_changed(before, _form(tmp_path, 3, volume=35)) is False
    # ...and the image list, every way it can change
    fewer = _form(tmp_path, 2)
    assert diff_forms(before, fewer)[1] == ["3 images -> 2"]
    more = _form(tmp_path, 4)
    assert diff_forms(before, more)[1] == ["3 images -> 4"]
    swapped = _form(tmp_path, 3)
    swapped.images[0], swapped.images[1] = swapped.images[1], swapped.images[0]
    assert diff_forms(before, swapped)[1] == ["reordered"]
    replaced = _form(tmp_path, 3)
    replaced.images[2].path = _images(tmp_path, 4)[3]
    assert diff_forms(before, replaced)[1] == ["an image was replaced"]
    assert media_specs_changed(before, fewer) is True
    # a row with no source is still the same row: its device says so
    b2 = _form(tmp_path, 2)
    a2 = _form(tmp_path, 2)
    for f in (b2, a2):
        f.images[0].path, f.images[0].device = "", "/dev/mmcblk0p3"
    assert diff_forms(b2, a2) == ([], [])


def test_the_status_line_names_what_will_happen(tmp_path):
    card = "D:/Pinball/multi/card.multi.raw"
    assert "no changes yet" in edit_status_text(card, [], [])
    one = edit_status_text(card, ["title"], [])
    assert one.startswith("1 menu change (title)")
    assert APPLY_TICK in one, "it names the control that really writes it"
    assert "card.multi.raw" in one and "no rebuild" in one
    three = edit_status_text(card, ["title", "art", "volume"], [])
    assert "3 menu changes (title, art, volume)" in three
    listed = edit_status_text(card, ["title"], ["3 images -> 2"])
    assert listed.startswith("The image list changed (3 images -> 2)")
    assert WRITE_BUTTON in listed and "1 menu change would ride" in listed


# --------------------------------------------------------------------------
# what the card path is pointing at
#
# The row lost its two labelled buttons, so every word about the tab's two
# modes now comes out of card_path_state - and all of it is decided WITHOUT
# Tk and WITHOUT a disk, from the box's text, a facts dict and the form.
# That is where the bulk of this coverage is: the panel only has to prove it
# wires the answer to the right widgets.
# --------------------------------------------------------------------------

CARD = "D:/Pinball/multi/card.multi.raw"


def _state(field, kind="unknown", parent=True, root="D:\\", **kw):
    return card_path_state(field, {"kind": kind, "parent": parent,
                                   "root": root}, **kw)


def test_an_empty_path_says_where_a_card_would_come_from():
    kind, text, tone, on = _state("")
    assert (kind, tone, on) == ("empty", "gray", False)
    assert text == multiboot_core.EMPTY_PATH_TEXT


def test_a_file_that_is_there_is_the_one_a_load_reads():
    kind, text, tone, on = _state(CARD, kind="file")
    assert (kind, tone, on) == ("file", "fg", True)
    assert text.startswith("card.multi.raw is on disk")
    # ...and it does NOT claim to know what kind of card it is: only the
    # tool under WSL can read images.conf out of the card's ext4.
    for word in ("multi-boot card", "stock", "single-image"):
        assert word not in text


def test_a_path_with_nothing_at_it_is_where_a_build_would_write():
    kind, text, tone, on = _state(CARD, kind="missing", parent=True)
    assert (kind, tone, on) == ("missing", "gray", False)
    assert text == "%s will write a new card at card.multi.raw." \
        % WRITE_BUTTON
    _k, text, _t, _on = _state(CARD, kind="missing", parent=False)
    assert text.endswith("creating multi.")


def test_a_folder_a_dead_drive_and_a_slow_one_each_say_so():
    kind, text, tone, on = _state(CARD, kind="dir")
    assert (kind, tone, on) == ("dir", "error", False)
    assert text == "That path is a folder, not a card."
    kind, text, tone, on = _state(CARD, kind="unreachable", root="W:\\")
    assert (kind, tone, on) == ("unreachable", "error", False)
    assert text.startswith("W:\\ is not there right now")
    kind, text, tone, on = _state(CARD, kind="looking")
    assert (kind, tone, on) == ("looking", "gray", False)
    assert text == "Looking at card.multi.raw…"


def test_nothing_asked_yet_says_nothing_and_leaves_the_verb_live():
    """The probe is off (PAD_MULTIBOOT_PROBE=0) or has not answered.  A
    guess would have to be wrong half the time, so the row says nothing and
    the verb stays live - pressing it asks the TOOL, whose refusal is
    better than anything this app could invent."""
    kind, text, _tone, on = _state(CARD, kind="unknown")
    assert (kind, text, on) == ("unknown", "", True)


def test_the_library_and_an_input_image_outrank_any_probe_answer():
    """Both are refusals validate_form already makes, and both are decided
    from the text alone - so a facts dict claiming the file is right there
    cannot talk over them."""
    lib = multiboot_core.LIBRARY_PREFIXES[0] + "/Stern/spike2/x.raw"
    kind, text, tone, on = _state(lib, kind="file")
    assert (kind, tone, on) == ("library", "error", False)
    assert "card library" in text
    rows = [ImageRow(path="D:/cards/a.raw"), ImageRow(path=CARD)]
    kind, text, tone, on = _state(CARD, kind="file", rows=rows)
    assert (kind, tone, on) == ("is_image", "error", False)
    assert text.startswith("That file is image 1 in the list below")


def test_the_loaded_card_outranks_the_probe_and_says_what_apply_would_do():
    """A load is a fact; a stat is a guess about the same file.  ~20 tests
    load a 16-byte stand-in card, and a probe that contradicted them would
    turn every one of them red."""
    kind, text, tone, on = _state(
        CARD, kind="missing", loaded_card=CARD, menu=["title"])
    assert (kind, tone, on) == ("loaded", "fg", True)
    assert text == edit_status_text(CARD, ["title"], [])
    # ...and a changed image LIST paints it red, exactly as before
    kind, _t, tone, _on = _state(CARD, kind="file", loaded_card=CARD,
                                 rebuild=["3 images -> 2"])
    assert (kind, tone) == ("loaded", "error")


def test_typing_the_path_away_from_the_loaded_card_names_the_way_back():
    """Nothing is thrown away by it - only what the tab CLAIMS changes - so
    the sentence is about the way back, while the verb still describes the
    path now in the box.

    AND THE WAY BACK IS THE PATH, not a menu entry: the sentence used to end
    'More ▾ ▸ Back to the card being edited', and that menu is gone."""
    other = "D:/Pinball/multi/copy.multi.raw"
    kind, text, tone, on = _state(
        other, kind="file", loaded_card=CARD, menu=["title", "volume"])
    assert (kind, tone) == ("strayed", "fg")
    assert "no longer names card.multi.raw" in text
    assert "2 unsaved changes" in text
    assert "type that path back" in text
    assert "More" not in text
    # the verb is still about the path in the box, not about the loaded card
    assert on is True
    # with nothing unsaved it is past tense and counts nothing
    _k, text, _t, _on = _state(other, kind="missing", loaded_card=CARD)
    assert "the card you were editing" in text and "unsaved" not in text
    # ...and emptying the box is straying too: clearing a path must not read
    # as "no card yet" while a card is still in the form.
    kind, text, _t, on = _state("", loaded_card=CARD)
    assert kind == "strayed" and on is False
    assert "type that path back" in text


def test_no_sentence_names_a_title_a_build_or_a_version():
    """The tab's copy rule (multiboot_tab.py's own comment): nothing it says
    names an example card."""
    rows = [ImageRow(path="D:/cards/a.raw")]
    for kw in ({"kind": "file"}, {"kind": "dir"}, {"kind": "missing"},
               {"kind": "unreachable"}, {"kind": "looking"}):
        _k, text, _t, _on = _state(CARD, rows=rows, **kw)
        low = text.lower()
        for word in ("turtles", "godzilla", "1.59", "spike"):
            assert word not in low


# --------------------------------------------------------------------------
# the probe itself
# --------------------------------------------------------------------------

def test_the_probe_stats_and_stops(tmp_path):
    card = tmp_path / "card.raw"
    card.write_bytes(b"x")
    assert probe_card_path(str(card))["kind"] == "file"
    assert probe_card_path(str(tmp_path))["kind"] == "dir"
    gone = probe_card_path(str(tmp_path / "nope.raw"))
    assert gone["kind"] == "missing" and gone["parent"] is True
    deep = probe_card_path(str(tmp_path / "a" / "b" / "nope.raw"))
    assert deep["kind"] == "missing" and deep["parent"] is False
    assert probe_card_path("")["kind"] == "unknown"


def test_the_probe_creates_nothing(tmp_path):
    """It is on a debounce behind every keystroke of an arbitrary path.  A
    probe that made a directory would litter the disk with half-typed
    folders - which is the trap _auto_render already guards against."""
    before = sorted(os.listdir(tmp_path))
    probe_card_path(str(tmp_path / "one" / "two" / "card.raw"))
    probe_card_path(str(tmp_path / "card.raw"))
    assert sorted(os.listdir(tmp_path)) == before


def test_the_root_is_what_an_unplugged_drive_sentence_names():
    if sys.platform == "win32":
        assert path_root("D:/Pinball/x.raw") == "D:\\"
    assert path_root("") == ""


# --------------------------------------------------------------------------
# the tab's saved state (the pure half)
# --------------------------------------------------------------------------

def test_a_saved_row_comes_back_with_its_paths_resolved():
    rows = rows_from_state(
        [{"path": "W:/cards/a.raw", "title": "A", "art": "W:/art/a.png",
          "anim": "auto", "music": "none", "confirm": "auto@3",
          "art_video": "W:/clips/a.mov", "art_on_card": True,
          "not_a_field_this_app_knows": 7}],
        resolve=lambda p: p.replace("W:/", "//server/share/"))
    assert len(rows) == 1
    row = rows[0]
    assert row.path == "//server/share/cards/a.raw"
    assert row.art == "//server/share/art/a.png"
    assert row.art_video == "//server/share/clips/a.mov"
    # the WORDS are not paths, and auto@N reads as one but is not
    assert (row.anim, row.music, row.confirm) == ("auto", "none", "auto@3")
    assert row.art_on_card is True and row.title == "A"


def test_a_half_written_state_costs_the_tab_its_state_not_the_startup():
    assert rows_from_state(None) == []
    assert rows_from_state(["not a dict", 7, None]) == []
    assert len(rows_from_state([{"path": "a.raw"}] * 40)) == \
        multiboot_core.MAX_IMAGES
    menu = menu_from_state({"volume": "not a number", "timeout": None,
                            "default": 2, "bypass": False})
    assert menu.pop("compact") is False
    assert menu == {"move": "auto", "confirm": "auto", "volume": 50,
                    "timeout": 15, "default": 2,
                    "machine_volume": True,
                    # PAD-135: a state written before the field existed
                    # described a menu that said SELECT GAME CODE
                    "heading": "SELECT GAME CODE",
                    # ...and PAD-183: one that said nothing about the text
                    # size described a menu drawn at one size
                    "same_text_size": True,
                    # ...and PAD-190: one that said nothing about the two
                    # lines under the cards described a menu that counted
                    # them and said 'starting'
                    "show_counter": True, "countdown_word": "starting",
                    # ...and PAD-190 round 2: one that said nothing about the
                    # instructions line described a menu drawing the
                    # selector's own (the tick on, the box empty)
                    "show_footer": True, "footer": "",
                    "theme": "midnight", "colors": {}}
    assert "bypass" not in menu_from_state(None)     # always on: not a setting
    assert menu_from_state({"volume": 900})["volume"] == 100
    # ...and a state that saved an EMPTY heading gets it back, not the default
    assert menu_from_state({"heading": ""})["heading"] == ""


# --------------------------------------------------------------------------
# the tab in the app
# --------------------------------------------------------------------------


def test_the_countdowns_own_word_cannot_drift_from_the_selectors(tmp_path):
    """Three copies of one word - codeselect.c's DEF_COUNTDOWN_WORD (what the
    menu draws), mkmulticard.py's (what `inspect` says a card that never set
    the key does) and this tab's DEFAULT for the field - so they are pinned to
    each other by name here, exactly as the footer macros are (PAD-190)."""
    import re as _re
    import importlib.util
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "tools", "spike2_emu", "codeselect",
                            "codeselect.c"), encoding="utf-8").read()
    word = _re.search(r'^#define DEF_COUNTDOWN_WORD "(.*)"$', src,
                      _re.M).group(1)
    spec = importlib.util.spec_from_file_location(
        "mkmulticard_for_word",
        os.path.join(root, "tools", "spike2_emu", "mkmulticard.py"))
    mkc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mkc)
    assert word == mkc.DEF_COUNTDOWN_WORD == multiboot_core.DEF_COUNTDOWN_WORD
    # ...and the counter's two words are the tool's, not this tab's own pair
    assert (multiboot_core.COUNTER_ON, multiboot_core.COUNTER_OFF) == mkc.COUNTERS
    assert multiboot_core.COUNTDOWN_WORD_MAX == mkc.CONF_STR_MAX


def test_an_images_own_confirm_survives_a_card_round_trip(tmp_path):
    """What an inspect reports comes back as the row that wrote it, so a
    load followed by an apply writes the same card.  The manifest records
    the SPEC in confirm_source and the staged file in confirm; only the
    spec can be rendered again, and a bare file name with no spec is kept
    as the card's own file - the same rule art, animation and music follow."""
    rows, _warn = multiboot_core.rows_from_inspect({"images": [
        {"device": "/dev/mmcblk0p3", "title": "A"},
        {"device": "/dev/mmcblk0p7", "title": "B",
         "confirm": "confirm1.wav", "confirm_source": "synth"},
        {"device": "/dev/mmcblk0p7:img2", "title": "C",
         "confirm": "confirm2.wav"},
    ]})
    assert [r.confirm for r in rows] == ["", "synth", "confirm2.wav"]
    assert [r.confirm_on_card for r in rows] == [False, False, True]
    assert multiboot_core.on_card_fields(rows[2]) == [
        ("confirm sound", "confirm2.wav")]
    assert [multiboot_core.confirm_spec(r) for r in rows] == [
        "none", "synth", multiboot_core.wsl("confirm2.wav")]


def test_a_confirm_spec_keeps_a_catalogue_index_and_a_path(tmp_path):
    """'auto@54' picks a specific sound out of that image's own catalogue.
    The tab never writes one, but a card prepared by hand carries it, and a
    load must hand it back rather than mangle it into a path."""
    assert multiboot_core.split_confirm_source("auto@54") == "auto@54"
    assert multiboot_core.confirm_spec(ImageRow("", confirm="auto@54")) == \
        "auto@54"
    assert multiboot_core.split_confirm_source("none") == ""
    assert multiboot_core.split_confirm_source(None) == ""
    # a path still crosses as a path
    p = str(tmp_path / "my chime.wav")
    assert multiboot_core.confirm_spec(ImageRow("", confirm=p)) == \
        multiboot_core.wsl(p)


def test_a_per_image_confirm_is_a_media_change(tmp_path):
    """It is prepared media, so changing one has to make the tools run
    again - and it is a MENU field, so 'Apply to card' can write it without
    a rebuild."""
    before = _form(tmp_path, 2)
    after = _form(tmp_path, 2)
    after.images[1].confirm = "synth"
    menu, rebuild = multiboot_core.diff_forms(before, after)
    assert "confirm sound" in menu and not rebuild
    assert "confirm sound" in multiboot_core.MEDIA_FIELDS
    # ...and the prepared set depends on it, so the cache cannot hand back
    # the old media
    assert multiboot_core.media_fingerprint(before) != \
        multiboot_core.media_fingerprint(after)


def test_the_version_gate_findings_come_back_worst_first():
    """``inspect`` writes each finding as a finished sentence, so the tab
    shows what the tool decided rather than deciding it again.  A card whose
    images are not even the same GAME is worse than one that is a version
    apart, which is worse than one that only ships different node firmware."""
    assert multiboot_core.version_alarm({}) is None
    assert multiboot_core.version_alarm(
        {"version_mismatch": None, "node_fw_mismatch": None}) is None
    head, full = multiboot_core.version_alarm({
        "version_mismatch": "1.59.0 and 1.58.0 are not the same code.",
        "node_fw_mismatch": "Image 2 carries 1.19.0.",
    })
    assert head == "These images are not the same game code version."
    # every finding is kept, in the same order, for the Log and the tooltip
    assert full.splitlines()[0] == "1.59.0 and 1.58.0 are not the same code."
    assert "Image 2 carries 1.19.0." in full
    worst, _full = multiboot_core.version_alarm({
        "title_mismatch": "One is turtles_pro, the other is godzilla.",
        "version_mismatch": "1.59.0 and 1.13.0.",
    })
    assert worst == "These images are not the same game."


def test_a_menu_read_off_an_sd_card_is_not_an_unreadable_version():
    """PAD-197.  A menu read off an SD card (item 99) holds the menu
    partition only, so every games tree on it is unreadable by design - and
    the tab put up a red 'could not be read' strip about a card nobody had
    touched.  That one finding is dropped for such a card; the rest stay."""
    unread = {"unknown_version": "6 image(s) did not say what game code they run."}
    assert multiboot_core.is_menu_image(r"C:\Temp\cards\SanDisk-32G.menu.raw")
    assert multiboot_core.is_menu_image('"/tmp/cards/X.MENU.RAW"')
    assert not multiboot_core.is_menu_image(r"D:\cards\beatles.multi.raw")
    assert not multiboot_core.is_menu_image("")
    assert multiboot_core.version_alarm(unread)[0] ==         "The game code version of an image could not be read."
    assert multiboot_core.version_alarm(unread, menu_only=True) is None
    head, full = multiboot_core.version_alarm(
        dict(unread, version_mismatch="1.29.0 and 1.27.0."), menu_only=True)
    assert head == "These images are not the same game code version."
    assert "did not say" not in full


# --------------------------------------------------------------------------
# the tab comes back as it was left
# --------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file-name rules")
def test_a_name_the_file_system_refuses_is_not_an_unplugged_drive(tmp_path):
    """Windows raises the same class of OSError for a '?' in a file name as
    it does for a share that is down (errno 22 / winerror 123), so the row
    told David to plug in a drive that was plainly sitting there."""
    for bad in ("card?.raw", "card*.raw", "card|x.raw", "c" * 300 + ".raw"):
        facts = multiboot_core.probe_card_path(str(tmp_path / bad))
        assert facts["kind"] == "badname", bad
    # ...and it reads as what it is, in the error colour, with no verb
    kind, text, tone, on = _state(str(tmp_path / "x?.raw"),
                                  kind="badname")
    assert (kind, tone, on) == ("badname", "error", False)
    assert "not a name" in text and "plug" not in text
    # a path that really is missing is still missing
    assert multiboot_core.probe_card_path(
        str(tmp_path / "nope.raw"))["kind"] == "missing"


# --------------------------------------------------------------------------
# ...and the rail it comes back on: the project anchor, with the global
# settings as the fallback for having no project open.  Same shape, same
# rules and the same stub pattern as the Emulate tab's card path
# (tests/test_emulate_tab.py), because two places deciding one thing
# differently is the failure this tree keeps paying for.
# --------------------------------------------------------------------------

class _StatePanel:
    """A stand-in for the panel: it records what it was handed."""

    def __init__(self, doc=None):
        self.doc = doc if doc is not None else {}
        self.restored = "NOTHING WAS RESTORED"

    def state(self):
        return self.doc

    def restore_state(self, doc):
        self.restored = doc
        return True


def _multi_anchor(folder, **updates):
    from pinball_decryptor.core import project_file
    project_file.save(project_file.anchor_path(str(folder)),
                      manufacturer_key="stern",
                      paths={"extract_input": "C:/stock/game.raw",
                             "extract_output": str(folder)},
                      extract_options={}, app_version="test")
    if updates:
        project_file.update_anchor(str(folder), **updates)


def _multi_restore(folder, settings=None, panel=None):
    from pinball_decryptor.app import App
    panel = panel if panel is not None else _StatePanel()
    stub = SimpleNamespace(
        _settings=settings if settings is not None else {},
        window=SimpleNamespace(_multiboot_panel=panel))
    App.restore_multiboot_state(stub, str(folder) if folder else "")
    # A real panel records nothing - the tests that pass one read the tab.
    return getattr(panel, "restored", None)


def test_the_project_owns_the_tabs_form(tmp_path):
    proj = tmp_path / "godzilla"
    proj.mkdir()
    _multi_anchor(proj, multiboot={"v": 1, "card": "D:/cards/a.multi.raw"})
    assert _multi_restore(proj)["card"] == "D:/cards/a.multi.raw"
    other = tmp_path / "beatles"
    other.mkdir()
    _multi_anchor(other, multiboot={"v": 1, "card": "D:/cards/b.multi.raw"})
    assert _multi_restore(other)["card"] == "D:/cards/b.multi.raw"


def test_a_projects_empty_form_wins_over_the_global(tmp_path):
    """A PROJECT'S VALUE WINS ABSOLUTELY, INCLUDING WHEN IT IS EMPTY - the
    rule _restore_emulate_card already keeps, and the reason switching
    projects cannot leak the last one's state."""
    proj = tmp_path / "fresh"
    proj.mkdir()
    _multi_anchor(proj, multiboot={})
    assert _multi_restore(
        proj, {"multiboot_state": {"v": 1, "card": "D:/leaked.raw"}}) == {}


def test_an_anchor_written_before_this_shipped_uses_the_global(tmp_path):
    """No `multiboot` key at all means there is nothing to honour - the same
    exception the JJP ISO and the Spike 1 card make, and what makes an
    EXISTING project restore instead of coming back blank."""
    proj = tmp_path / "older"
    proj.mkdir()
    _multi_anchor(proj)
    doc = {"v": 1, "card": "D:/cards/last.multi.raw"}
    assert _multi_restore(proj, {"multiboot_state": doc}) == doc


def test_no_project_falls_back_to_the_global_form(tmp_path):
    doc = {"v": 1, "card": "D:/cards/last.multi.raw"}
    plain = tmp_path / "just-a-folder"
    plain.mkdir()
    assert _multi_restore(plain, {"multiboot_state": doc}) == doc
    assert _multi_restore("", {"multiboot_state": doc}) == doc
    assert _multi_restore("", {}) == {}


def test_an_unreadable_anchor_leaves_the_tab_empty_not_broken(tmp_path):
    """Anchors live in the project folder, which is often a NAS.  A
    truncated one must not take the startup down with it - and must not be
    mistaken for an anchor written before the key existed, which is the one
    case allowed to reach for the global.  With a global set (the normal
    state: every quit writes one) that confusion put the LAST project's card
    on this project's tab, silently, on an ordinary launch."""
    from pinball_decryptor.core import project_file
    proj = tmp_path / "corrupt"
    proj.mkdir()
    with open(project_file.anchor_path(str(proj)), "w", encoding="utf-8") as f:
        f.write("{not json")
    assert _multi_restore(proj) == {}
    assert _multi_restore(
        proj, {"multiboot_state": {"v": 1, "card": "D:/global.raw"}}) == {}


def test_opening_another_project_saves_the_one_being_left(tmp_path):
    """An evening's work on project A was only ever on screen: the anchor
    writes are the quit, an extract, Project - Save and New project, and
    OPENING project B is none of them.  So A kept the morning's version and
    the form still visible belonged to B."""
    from pinball_decryptor.app import App
    from pinball_decryptor.core import project_file
    a, b = tmp_path / "a", tmp_path / "b"
    for folder in (a, b):
        folder.mkdir()
        _multi_anchor(folder, multiboot={"v": 1, "card": "%s.raw" % folder})
    doc = {"v": 1, "card": "D:/an evenings work.multi.raw"}
    stub = SimpleNamespace(
        _settings={}, _project_path=str(a), _capture_run=lambda: False,
        window=SimpleNamespace(_multiboot_panel=_StatePanel(doc)))
    stub.multiboot_state = lambda: App.multiboot_state(stub)
    App.save_multiboot_state(stub, str(a))
    assert project_file.load_anchor(str(a))["multiboot"] == doc
    # ...and it is not what turns a plain folder into a project
    plain = tmp_path / "plain"
    plain.mkdir()
    App.save_multiboot_state(stub, str(plain))
    assert not project_file.has_anchor(str(plain))
    App.save_multiboot_state(stub, "")          # no project open: nothing


def test_the_project_switch_saves_before_it_restores(tmp_path):
    """The whole point is the ORDER: the outgoing project's anchor is
    written before one line of the incoming project has touched the tab."""
    from pinball_decryptor.app import App, get_manufacturer
    from pinball_decryptor.core import project_file
    a, b = tmp_path / "a", tmp_path / "b"
    for folder in (a, b):
        folder.mkdir()
    _multi_anchor(a, multiboot={"v": 1, "card": "this mornings.raw"})
    _multi_anchor(b, multiboot={"v": 1, "card": "b.multi.raw"})
    panel = _StatePanel({"v": 1, "card": "an evenings work.raw"})
    mfr = get_manufacturer("stern")     # the real one: _apply_project_
    var = SimpleNamespace(set=lambda v: None)   # folder looks it up itself
    window = SimpleNamespace(
        _multiboot_panel=panel, extract_input_var=var,
        extract_output_var=var, write_filename_var=var,
        emulate_card_var=var, emulate_savestates_var=var,
        set_extract_options=lambda o: None,
        invalidate_asset_scans=lambda: None,
        append_log=lambda *a, **kw: None)
    stub = SimpleNamespace(
        _settings={}, _project_path=str(a), _current_mfr=mfr, window=window,
        _registry_touch=lambda f: None, _set_loaded_project=lambda f: None,
        _save_settings=lambda: None, _capture_run=lambda: False)
    stub.multiboot_state = lambda: App.multiboot_state(stub)
    stub.save_multiboot_state = (
        lambda folder: App.save_multiboot_state(stub, folder))
    stub.restore_multiboot_state = (
        lambda folder: App.restore_multiboot_state(stub, folder))
    App._apply_project_folder(stub, str(b), project_file.load_anchor(str(b)))
    assert project_file.load_anchor(str(a))["multiboot"]["card"] == \
        "an evenings work.raw"
    assert panel.restored["card"] == "b.multi.raw"
    # ...and re-opening the project that is already open does not write its
    # own form back over itself from a tab that has not been restored yet
    before = project_file.load_anchor(str(b))["multiboot"]
    stub._project_path = str(b)
    panel.doc = {"v": 1, "card": "something else.raw"}
    App._apply_project_folder(stub, str(b), project_file.load_anchor(str(b)))
    assert project_file.load_anchor(str(b))["multiboot"] == before


def test_the_global_form_is_written_on_every_settings_save(tmp_path,
                                                           monkeypatch):
    """Without this the no-project fallback has nothing to read: the anchor
    save is skipped outright when the folder is not a project."""
    from pinball_decryptor import app as app_mod
    from pinball_decryptor.app import App
    monkeypatch.setattr(app_mod, "SETTINGS_FILE",
                        str(tmp_path / "settings.json"))
    settings = {}
    doc = {"v": 1, "card": "D:/cards/x.multi.raw"}
    stub = SimpleNamespace(
        _current_mfr=None, _settings=settings,
        root=SimpleNamespace(winfo_geometry=lambda: "1x1"),
        _window_is_maximized=lambda: False,
        _last_normal_geometry=None, _capture_run=lambda: False,
        window=SimpleNamespace(_current_theme="dark", _last_browse_dirs=None,
                               _multiboot_panel=_StatePanel(doc)))
    stub.multiboot_state = lambda: App.multiboot_state(stub)
    App._save_settings(stub)
    assert settings["multiboot_state"] == doc


def test_a_window_with_no_multiboot_tab_is_not_a_failure():
    """Every manufacturer but Spike 2 hides this tab, and the panel tests
    build one on its own - neither must make the app's save or restore
    raise."""
    from pinball_decryptor.app import App
    stub = SimpleNamespace(_settings={}, window=SimpleNamespace())
    assert App.multiboot_state(stub) == {}
    App.restore_multiboot_state(stub, "")           # no panel, no exception


# --------------------------------------------------------------------------
# the menu's colour themes
# --------------------------------------------------------------------------

def test_the_themes_are_read_off_the_selectors_own_file():
    """themes.json is the selector's; the tab reads it as is - the names,
    the titles the picker shows, the roles and their labels."""
    th = multiboot_core.boot_themes()
    assert th is not None and th["default"] == "midnight"
    assert multiboot_core.theme_names() == [
        "midnight", "arcade", "neon", "emerald", "slate", "daylight"]
    assert len(multiboot_core.theme_roles()) == 14
    assert multiboot_core.theme_title("slate") == "Slate"
    assert multiboot_core.theme_title("custom") == "Make your own…"
    assert multiboot_core.theme_title("") == "midnight"
    assert multiboot_core.theme_label("frame_hl") == "Card frame, highlighted"
    assert "amber" in multiboot_core.theme_about("midnight")
    assert multiboot_core.theme_colors("midnight")["frame_hl"] == "ffc42d"
    assert multiboot_core.theme_colors("custom") is None
    assert multiboot_core.clean_colors(
        {"frame_hl": "#ABCDEF", "countdown": "zzz", "nosuch": "ffffff",
         "background": " 102030 "}) == {"frame_hl": "abcdef",
                                        "background": "102030"}
    assert multiboot_core.clean_colors("not a dict") == {}


def test_theme_from_card_shows_what_the_machine_will_draw():
    f = multiboot_core.theme_from_card
    assert f("slate", {}) == ("slate", {})
    assert f(None, None) == ("midnight", {})
    assert f("nosuch", {}) == ("midnight", {})
    # overrides on top of anything are the custom theme with every role
    # spelled out - the base's colours under them
    theme, colors = f("slate", {"countdown": "00ff00"})
    assert theme == "custom" and colors["countdown"] == "00ff00"
    assert colors["background"] == multiboot_core.theme_colors("slate")[
        "background"] and len(colors) == 14
    theme, colors = f("custom", {"frame_hl": "#FFFFFF", "bad": "zzz"})
    assert theme == "custom" and colors["frame_hl"] == "ffffff"
    assert colors["background"] == "0b0e13" and "bad" not in colors
    theme, colors = f(None, {"heading": "ff0000"})
    assert theme == "custom" and colors["heading"] == "ff0000"


def test_the_theme_rides_every_command_line_and_the_preview_conf(tmp_path):
    """--theme on build and inject, --color per role for the custom theme
    (the selector's order), the same keys in the preview's conf - and a
    colour that is not one is left out there and refused by validate_form,
    never handed to a tool."""
    form = _form(tmp_path, 2, theme="slate")
    build, inject = build_args(form), inject_args(form, form.out)
    for argv in (build, inject):
        assert argv[argv.index("--theme") + 1] == "slate"
        assert "--color" not in argv
    assert multiboot_core.theme_args(form) == ["--theme", "slate"]
    assert write_preview_conf(form).splitlines()[-1] == "theme=slate"
    a = preview_fingerprint(form)
    form.theme = "neon"
    assert preview_fingerprint(form) != a
    colors = dict(multiboot_core.theme_colors("neon"))
    colors["countdown"] = "#00FF00"
    form = _form(tmp_path, 2, theme="custom", colors=colors)
    words = multiboot_core.theme_args(form)
    assert words[:2] == ["--theme", "custom"]
    pairs = [words[i + 1] for i in range(2, len(words), 2)
             if words[i] == "--color"]
    assert len(pairs) == 14 and pairs[0].startswith("background=")
    assert pairs[-1] == "countdown=00ff00"
    argv = build_args(form)
    i = argv.index("--theme")
    assert argv[i:i + len(words)] == words
    lines = write_preview_conf(form).splitlines()
    assert lines[-15] == "theme=custom"
    assert lines[-1] == "color_countdown=00ff00"
    assert validate_form(form, sources=False) == []
    form.colors["frame_hl"] = "not a colour"
    errs = validate_form(form, sources=False)
    assert any("card frame, highlighted colour must be six hex" in e
               for e in errs)
    assert "frame_hl=" not in " ".join(multiboot_core.theme_args(form))
    assert "color_frame_hl" not in write_preview_conf(form)
    form.colors = {"nosuch": "ffffff"}
    assert any("not a colour the menu has" in e
               for e in validate_form(form, sources=False))
    form = _form(tmp_path, 2, theme="nosuch")
    assert any("not one the selector has" in e
               for e in validate_form(form, sources=False))


def test_form_from_inspect_carries_the_theme(monkeypatch, tmp_path):
    _win(monkeypatch)
    info = _rich_report(tmp_path)
    card = str(tmp_path / "multi" / "card.multi.raw")
    form, _w = form_from_inspect(info, card, "")
    assert (form.theme, form.colors) == ("midnight", {})
    info["theme"], info["colors"] = "neon", {}
    assert form_from_inspect(info, card, "")[0].theme == "neon"
    info["theme"], info["colors"] = "custom", {"frame_hl": "00ff00"}
    form, _w = form_from_inspect(info, card, "")
    assert form.theme == "custom" and form.colors["frame_hl"] == "00ff00"
    assert len(form.colors) == 14


# ---- the menu's heading (C FB, PAD-135) --------------------------------------
def test_the_heading_rides_every_command_line_and_the_preview_conf(tmp_path):
    """PAD-135, about SELECT GAME CODE: "Can there be an option to change this
    text?"  The form starts as what the menu already says, --heading is always
    spelled out (so clearing it CLEARS it rather than leaving the card's), and
    the field is refused where it is typed rather than half-written."""
    form = _form(tmp_path, 2)
    assert form.heading == "SELECT GAME CODE" == multiboot_core.DEF_HEADING
    for argv in (build_args(form), inject_args(form, form.out),
                 multiboot_core.update_args(form, form.out)):
        assert argv[argv.index("--heading") + 1] == "SELECT GAME CODE"
    form.heading = "THE BEATLES JUKEBOX"
    assert multiboot_core.heading_args(form) == ["--heading",
                                                "THE BEATLES JUKEBOX"]
    assert "heading=THE BEATLES JUKEBOX" in write_preview_conf(form)
    # the frame depends on it: a new heading is a new picture
    before = preview_fingerprint(form)
    form.heading = ""
    assert preview_fingerprint(form) != before
    # AN EMPTY BOX IS AN ANSWER: the flag still goes, with nothing after it
    assert build_args(form)[build_args(form).index("--heading") + 1] == ""
    assert "heading=\n" in write_preview_conf(form)
    assert validate_form(form, sources=False) == []
    # ...and the two things the selector's own field cannot take
    form.heading = "two\nlines"
    assert any("one line" in e for e in validate_form(form, sources=False))
    form.heading = "x" * 200
    assert any("too long" in e for e in validate_form(form, sources=False))


def test_form_from_inspect_carries_the_heading(monkeypatch, tmp_path):
    """null in the report is a card that never set one, and what it draws IS
    the selector's line - so that is what the field shows.  An empty string is
    a card that asked for a bare top, and must not read as "never set"."""
    _win(monkeypatch)
    info = _rich_report(tmp_path)
    card = str(tmp_path / "multi" / "card.multi.raw")
    info["heading"] = None
    assert form_from_inspect(info, card, "")[0].heading == "SELECT GAME CODE"
    info["heading"] = "THE BEATLES JUKEBOX"
    assert form_from_inspect(info, card, "")[0].heading == "THE BEATLES JUKEBOX"
    info["heading"] = ""
    assert form_from_inspect(info, card, "")[0].heading == ""


# ---- the machine's own volume (David, 2026-09-03) -----------------------------
def test_the_menu_follows_the_machines_own_volume_by_default(tmp_path):
    """David: 'we need to be considerate of what volume level it will play at
    on the actual machine. it should follow the set volume of the actual
    machine.'  The form follows by default, build and inject pass the flag,
    and the number stays the preview's own."""
    from pinball_decryptor.webui.multiboot_core import inject_args, form_from_inspect
    form = _form(tmp_path, 2, volume=35)
    assert form.machine_volume is True
    build = _tool_words(dict(build_commands(form))["build"])
    assert "--machine-volume" in build
    assert build[build.index("--volume") + 1] == "35"
    assert "--machine-volume" in inject_args(form, "D:/card.raw")
    form.machine_volume = False
    assert "--machine-volume" not in _tool_words(
        dict(build_commands(form))["build"])
    assert "--machine-volume" not in inject_args(form, "D:/card.raw")
    # a card read back: volume=machine is the tick, a number is not
    f2, _w = form_from_inspect({"images": [], "volume": "machine"}, "D:/card.raw")
    assert f2.machine_volume is True and f2.volume == 50
    f3, _w = form_from_inspect({"images": [], "volume": 35}, "D:/card.raw")
    assert f3.machine_volume is False and f3.volume == 35


# ---- same text size on every card (BEN, Discord, PAD-183) ---------------------
def test_the_text_size_tick_reaches_every_command_and_the_preview_conf(tmp_path):
    """BEN: 'is there a way to make the font size consistent across all images
    in a multiboot?'  The tick is ON by default - which is what the selector
    does when no card says otherwise - and the word is written out either way,
    so the card says what it does rather than leaning on that default."""
    from pinball_decryptor.webui.multiboot_core import (
        inject_args, text_size_args, write_preview_conf, TEXT_SIZE_UNIFORM,
        TEXT_SIZE_PER_CARD)
    form = _form(tmp_path, 2)
    assert form.same_text_size is True
    assert text_size_args(form) == ["--text-size", TEXT_SIZE_UNIFORM]
    build = _tool_words(dict(build_commands(form))["build"])
    assert build[build.index("--text-size") + 1] == TEXT_SIZE_UNIFORM
    words = inject_args(form, "D:/card.raw")
    assert words[words.index("--text-size") + 1] == TEXT_SIZE_UNIFORM
    assert "text_size=uniform" in write_preview_conf(form).splitlines()
    form.same_text_size = False
    assert text_size_args(form) == ["--text-size", TEXT_SIZE_PER_CARD]
    assert _tool_words(dict(build_commands(form))["build"])[
        build.index("--text-size") + 1] == TEXT_SIZE_PER_CARD
    assert "text_size=per-card" in write_preview_conf(form).splitlines()
    # the preview is keyed on the conf, so the tick cannot show a stale frame
    assert preview_fingerprint(_form(tmp_path, 2)) != preview_fingerprint(form)


# ---- the two lines under the cards (BEN, Discord, PAD-190) -------------------
def test_the_counter_and_the_countdown_word_reach_every_command_and_the_preview(tmp_path):
    """BEN: 'have an option to hide the "< x / y >" line' and 'have the option
    to change this text in case you want something like "Launching"'.  Both are
    written out either way, on the heading's rule: the form is the record of
    what the menu says, so clearing one has to reach the card as the other
    answer rather than as "the flag was absent, keep what is there"."""
    from pinball_decryptor.webui.multiboot_core import (
        inject_args, menu_text_args, write_preview_conf, update_args,
        COUNTER_ON, COUNTER_OFF, DEF_COUNTDOWN_WORD)
    form = _form(tmp_path, 2)
    assert form.show_counter is True
    assert form.countdown_word == DEF_COUNTDOWN_WORD == "starting"
    # ...and the instructions line rides in the same bundle (round 2): an
    # empty box with the tick on is --footer-own, the selector's own line
    assert menu_text_args(form) == ["--counter", COUNTER_ON,
                                    "--countdown-word", "starting",
                                    "--footer-own"]
    build = _tool_words(dict(build_commands(form))["build"])
    assert build[build.index("--counter") + 1] == COUNTER_ON
    assert build[build.index("--countdown-word") + 1] == "starting"
    for words in (inject_args(form, "D:/card.raw"),
                  update_args(form, "D:/card.raw")):
        assert words[words.index("--counter") + 1] == COUNTER_ON
        assert words[words.index("--countdown-word") + 1] == "starting"
    lines = write_preview_conf(form).splitlines()
    assert "counter=on" in lines and "countdown_word=starting" in lines
    form.show_counter = False
    form.countdown_word = "Launching"
    assert menu_text_args(form) == ["--counter", COUNTER_OFF,
                                    "--countdown-word", "Launching",
                                    "--footer-own"]
    words = _tool_words(dict(build_commands(form))["build"])
    assert words[words.index("--counter") + 1] == COUNTER_OFF
    assert words[words.index("--countdown-word") + 1] == "Launching"
    lines = write_preview_conf(form).splitlines()
    assert "counter=off" in lines and "countdown_word=Launching" in lines
    # an empty word is a real answer - the countdown then names the game and
    # the seconds and nothing else - and it reaches the card as one
    form.countdown_word = ""
    assert menu_text_args(form)[3] == ""
    assert "countdown_word=" in write_preview_conf(form).splitlines()
    # the preview is keyed on the conf, so neither can show a stale frame
    assert preview_fingerprint(_form(tmp_path, 2)) != preview_fingerprint(form)


def test_the_instructions_line_reaches_every_command_and_the_preview(tmp_path):
    """BEN, round 2: "can you extend this to make the instructions also
    customizable and/or visible?"  THREE answers, and the empty box is the one
    the tools cannot spell as text: the menu's own line, which is the only form
    that follows the buttons the machine has."""
    from pinball_decryptor.webui.multiboot_core import (
        footer_args, inject_args, update_args, write_preview_conf)
    form = _form(tmp_path, 2)
    # as it comes: the tick on, the box empty - the menu's own line
    assert form.show_footer is True and form.footer == ""
    assert footer_args(form) == ["--footer-own"]
    build = _tool_words(dict(build_commands(form))["build"])
    assert "--footer-own" in build and "--footer" not in build
    assert "footer=" not in write_preview_conf(form)
    # somebody's own words
    form.footer = "FLIPPERS pick a game    START plays it"
    assert footer_args(form) == ["--footer", "FLIPPERS pick a game    START plays it"]
    for words in (_tool_words(dict(build_commands(form))["build"]),
                  inject_args(form, "D:/card.raw"),
                  update_args(form, "D:/card.raw")):
        assert words[words.index("--footer") + 1] == \
            "FLIPPERS pick a game    START plays it"
        assert "--footer-own" not in words
    assert "footer=FLIPPERS pick a game    START plays it" in \
        write_preview_conf(form).splitlines()
    # ...and the tick off: no line at all, whatever is in the box
    form.show_footer = False
    assert footer_args(form) == ["--footer", ""]
    assert "footer=" in write_preview_conf(form).splitlines()
    # the preview is keyed on the conf, so none of the three shows another's frame
    fps = set()
    for on, text in ((True, ""), (True, "OWN WORDS"), (False, "OWN WORDS")):
        form.show_footer, form.footer = on, text
        fps.add(preview_fingerprint(form))
    assert len(fps) == 3


def test_a_loaded_cards_instructions_line_is_read_back(tmp_path):
    """null on the card = the selector's own line (the tick on, the box empty);
    "" = the card asked for no line (the tick off); anything else is the card's
    own words."""
    from pinball_decryptor.webui.multiboot_core import form_from_inspect
    f1, _w = form_from_inspect({"images": []}, "D:/card.raw")
    assert f1.show_footer is True and f1.footer == ""
    f2, _w = form_from_inspect({"images": [], "footer": "FLIPPERS choose"},
                               "D:/card.raw")
    assert f2.show_footer is True and f2.footer == "FLIPPERS choose"
    f3, _w = form_from_inspect({"images": [], "footer": ""}, "D:/card.raw")
    assert f3.show_footer is False and f3.footer == ""
    # ...and changing it is a MENU field: an inject writes it, not a rebuild
    from pinball_decryptor.webui.multiboot_core import diff_forms
    menu, rebuild = diff_forms(f1, f2)
    assert menu == ["instructions"] and rebuild == []


def test_the_instructions_example_says_which_of_the_three_lines_is_drawn():
    """The words in the box, or - for the two answers an empty box can be - a
    sentence.  The menu's own wording is never quoted here: it names the
    buttons the MACHINE has, which this app cannot know."""
    from pinball_decryptor.webui.multiboot_core import footer_example
    assert footer_example(True, "FLIPPERS choose") == "FLIPPERS choose"
    assert footer_example(True, "  padded  ") == "padded"
    assert "the menu's own" in footer_example(True, "")
    assert "no line" in footer_example(False, "")
    assert "no line" in footer_example(False, "FLIPPERS choose")


def test_the_countdown_example_says_what_the_menu_will_say():
    """The label beside the box is the line itself, so the box needs no note -
    and a countdown of 0 is a menu that waits for START, where the word is
    never seen at all."""
    from pinball_decryptor.webui.multiboot_core import countdown_example
    assert countdown_example("starting", "The Beatles", 15) == \
        "starting The Beatles in 15 s"
    assert countdown_example("Launching", "The Beatles", 9) == \
        "Launching The Beatles in 9 s"
    # no word at all: the game and the seconds, which is what the menu draws
    assert countdown_example("", "The Beatles", 9) == "The Beatles in 9 s"
    assert countdown_example("  Booting  ", "The Beatles", 9) == \
        "Booting The Beatles in 9 s"
    assert "waits for START" in countdown_example("starting", "The Beatles", 0)
    assert "waits for START" in countdown_example("starting", "The Beatles", "x")
    # no image to name yet
    assert countdown_example("starting", "", 15) == "starting the game in 15 s"


def test_eta_text_is_coarse_or_silent():
    assert eta_text(None) == "" and eta_text(-1) == ""
    assert eta_text(10 ** 6) == ""              # not an estimate any more
    assert eta_text(30) == "less than a minute left"
    assert eta_text(90) == "about 2 minutes left"
    assert eta_text(60) == "about 1 minute left"
    assert eta_text(3600) == "about 1 hour left"
    assert eta_text(3600 + 25 * 60) == "about 1h 25m left"


def test_parse_progress_reads_the_meter_and_nothing_else():
    assert parse_progress("[card] progress 250/1000 25.0% copying p3") == \
        (250, 1000, 0.25, "copying p3")
    assert parse_progress("[card] progress 0/0 0.0% preparing") == \
        (0, 0, 0.0, "preparing")
    assert parse_progress("[card] copying p3: 6.53 GB from x") is None
    assert parse_progress("plan: exit 0") is None
    assert parse_progress("") is None


def test_a_refusal_drops_the_path_the_sentence_already_carries():
    about = "C:/x/gz multi/godzilla.multi.raw"
    assert parse_refusal(
        "[card] error: /mnt/c/x/gz multi/godzilla.multi.raw: no selector",
        about) == "no selector"
    # a path that is NOT the file in hand is part of the reason, not a prefix
    assert parse_refusal(
        "[card] error: /mnt/c/other.raw: no selector", about) == \
        "/mnt/c/other.raw: no selector"
    # ...and without a file in hand nothing is dropped
    assert parse_refusal("[card] error: /mnt/c/x.raw: no selector") == \
        "/mnt/c/x.raw: no selector"
    assert parse_refusal("[card] error: no selector", about) == "no selector"


# ---- the status row: four checks and a message, on one line --------------------------
def _state_of(checks, key):
    return dict((k, st) for k, _l, st, _d in checks)[key]


def _detail_of(checks, key):
    return dict((k, d) for k, _l, _st, d in checks)[key]


def test_the_checks_walk_the_work_in_order(tmp_path):
    """An empty tab, then one filled in, then built: the row is the four
    things that have to be true before an SD card can be written."""
    rows = [ImageRow(path=p) for p in _images(tmp_path, 2)]
    empty = ("empty", multiboot_core.EMPTY_PATH_TEXT, "gray", False)
    got = status_checks([], empty, "")
    assert [k for k, _l, _st, _d in got] == \
        [k for k, _l in multiboot_core.STATUS_CHECKS]
    assert [st for _k, _l, st, _d in got] == ["no", "no", "no", "no"]
    assert _detail_of(got, "images").startswith("Add the images below")
    # a path and two images: the first two tick, and nothing is built
    missing = ("missing", "Build & verify will write a new card at x.", "gray",
               False)
    got = status_checks(rows, missing, "")
    assert [st for _k, _l, st, _d in got] == ["ok", "ok", "no", "no"]
    assert [l for _k, l, _st, _d in got][1] == "2 images"
    assert _detail_of(got, "built").startswith("Nothing at that path yet")
    # A FILE AT THE PATH IS NOT A BUILT CARD.  There was a 17 GB leftover
    # at David's from a build whose inject never ran, and Built ticked for
    # it: "I don't even understand how I got into this error state. So I
    # just need to build the image? If so, then why is built checked off?"
    ondisk = ("file", "x is on disk - ...", "fg", True)
    got = status_checks(rows, ondisk, "", card="file")
    assert [st for _k, _l, st, _d in got] == ["ok", "ok", "no", "no"]
    assert "nothing has looked inside" in _detail_of(got, "built")
    assert _detail_of(got, "ready") == "Build the card first."
    # ...and a file this tab has READ and found is not one says which
    bad = ("unreadable", "x is on disk but is not a multi-boot card: no "
           "selector.", "fg", True)
    got = status_checks(rows, bad, "", card="file")
    assert _state_of(got, "built") == "no"
    assert _detail_of(got, "built").startswith(bad[1])
    assert "writes over it" in _detail_of(got, "built")
    # a card this tab has confirmed ticks both
    got = status_checks(rows, ("loaded", "Editing x.", "fg", True), "x.raw",
                        card="card")
    assert [st for _k, _l, st, _d in got] == ["ok", "ok", "ok", "ok"]


def test_a_check_that_cannot_work_is_marked_bad(tmp_path):
    rows = [ImageRow(path=p) for p in _images(tmp_path, 2)]
    # the path is somewhere no card may be written
    lib = ("library", "That path is in the card library...", "error", False)
    got = status_checks(rows, lib, "")
    assert _state_of(got, "card") == "bad"
    assert _detail_of(got, "card") == lib[1]
    # one image is a card, but it is not a menu
    ok = ("missing", "will write", "gray", False)
    got = status_checks(rows[:1], ok, "")
    assert _state_of(got, "images") == "bad"
    assert "at least two images" in _detail_of(got, "images")
    # ...and an image whose .raw is not on this machine
    gone = [ImageRow(path=rows[0].path),
            ImageRow(path=str(tmp_path / "gone.raw"))]
    got = status_checks(gone, ok, "")
    assert _state_of(got, "images") == "bad"
    assert "not on this machine" in _detail_of(got, "images")
    # ...but a LOADED card names sources that may live on another machine,
    # and neither drawing its menu nor injecting one opens them
    loaded = ("loaded", "Editing x: no changes yet.", "fg", True)
    got = status_checks(gone, loaded, "x.raw", card="card")
    assert _state_of(got, "images") == "ok"


def test_ready_to_flash_is_about_the_card_and_not_the_tab(tmp_path):
    rows = [ImageRow(path=p) for p in _images(tmp_path, 2)]
    loaded = ("loaded", "Editing card.raw: no changes yet.", "fg", True)
    # read back, and the form has not moved since
    got = status_checks(rows, loaded, "card.raw", card="card")
    assert _state_of(got, "ready") == "ok"
    assert "matches this form" in _detail_of(got, "ready")
    # ...and the moment it has
    got = status_checks(rows, loaded, "card.raw", menu=["countdown"],
                        card="card")
    assert _state_of(got, "ready") == "no"
    assert "1 change not on card.raw yet: countdown" in \
        _detail_of(got, "ready")
    # a card BUILT in this session counts, because a build leaves no
    # baseline to diff against
    ondisk = ("file", "x is on disk", "fg", True)
    got = status_checks(rows, ondisk, "", card="card",
                        built_changes=([], []))
    assert _state_of(got, "ready") == "ok"
    assert "Built and verified" in _detail_of(got, "ready")
    got = status_checks(rows, ondisk, "", card="card",
                        built_changes=(["volume"], ["image 2"]))
    assert _state_of(got, "ready") == "no"
    assert "2 changes since it was built" in _detail_of(got, "ready")
    # NOTHING TO FLASH IS ONE MARK, NOT TWO: Ready follows Built, and two
    # marks shouting about one missing card sends a person hunting for a
    # second problem that is not there.
    for state in ("none", "file"):
        got = status_checks(rows, ondisk, "", card=state)
        assert _state_of(got, "ready") == "no"
        assert _detail_of(got, "ready") == "Build the card first."


def test_a_run_in_flight_shows_on_the_built_check(tmp_path):
    rows = [ImageRow(path=p) for p in _images(tmp_path, 2)]
    ok = ("missing", "will write", "gray", False)
    for kind in ("build", "apply"):
        got = status_checks(rows, ok, "", running=kind)
        assert _state_of(got, "built") == "now"
    # a LOAD is a run too, and it builds nothing
    got = status_checks(rows, ok, "", running="load")
    assert _state_of(got, "built") == "no"


# ---- a loaded card's sounds are the sounds it has ------------------------------------
@pytest.mark.skipif(sys.platform != "win32", reason="a WSL path reads back as a Windows one")
def test_a_sound_reads_back_as_the_spec_that_made_it():
    """WHAT MADE IT, not what it made.  media.json has recorded the source of
    every sound since they learned to re-render; inspect hands it over now,
    and a field holding it can be compared with the manifest.  A field
    holding the FILE NAME instead can only ever look stale."""
    src = "/mnt/c/x/gz/audio/idx1369 - Look.wav"
    assert split_sound_source("move.wav", "move sound", src) == \
        ("C:/x/gz/audio/idx1369 - Look.wav", "")
    # the words come back as words
    assert split_sound_source("move.wav", "move sound", "auto") == ("auto", "")
    assert split_sound_source("x.wav", "move sound", "synth") == ("synth", "")
    assert split_sound_source("x.wav", "move sound", "auto@1717") == \
        ("auto@1717", "")
    # ...and a card built before media.json carried them still says so
    val, why = split_sound_source("move.wav", "move sound", None)
    assert val == "auto" and "not recorded" in why
    assert split_sound_source("", "move sound", None) == ("none", "")
    # music reads the same way
    assert split_music_source("/mnt/c/a/b.wav") == "C:/a/b.wav"
    assert split_music_source("auto") == "auto"
    assert split_music_source("") == "none"
    assert split_music_source("none") == "none"


#: Control names this tab USED to have.  Every one of them is now part of
#: one green button and its modal (see MultibootPanel._build_actions).
GONE_CONTROLS = ("Apply to card", "Build & verify", "Load card")


def test_no_sentence_names_a_control_that_is_not_there(tmp_path):
    """A SENTENCE THAT SENDS SOMEONE LOOKING FOR A BUTTON WHICH IS NOT THERE
    is worse than one that says only what is true - this tab's own rule,
    written when the 'More' menu went, and then broken by the consolidation
    that followed it.  Three buttons became one green button and a modal;
    the sentences went on naming the three for months, until David asked
    "there is no 'apply to card' option anywhere in the gui. how do i do
    that?"

    Docstrings and comments are exempt: 'the Apply to card run' is what the
    code calls that run and always will be.  This is about the strings a
    person READS."""
    with open(multiboot_core.__file__, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and \
                    isinstance(body[0].value, ast.Constant) and \
                    isinstance(body[0].value.value, str):
                docs.add(id(body[0].value))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docs:
            for gone in GONE_CONTROLS:
                if gone in node.value:
                    bad.append("line %d names %r: %s"
                               % (node.lineno, gone,
                                  node.value.strip()[:70]))
    assert bad == [], "\n".join(bad)
    # ...and the names it DOES use are the ones the controls wear
    assert WRITE_BUTTON == multiboot_core.MultibootPanel.BUILD_FLASH_TEXT
    assert WRITE_BUTTON in APPLY_TICK
    assert "Update the loaded card in place" in APPLY_TICK


# ---------------------------------------------------------------------------
# the compact (store) layout tick - item 95, OPT-IN, default off
# ---------------------------------------------------------------------------
def test_the_compact_tick_is_off_by_default_and_selects_the_store_layout(tmp_path):
    from pinball_decryptor.webui.multiboot_core import build_args, plan_args
    form = _form(tmp_path, 2)
    assert form.compact is False
    b, p = build_args(form), plan_args(form)
    assert b[b.index("--layout") + 1] == "auto" and p[p.index("--layout") + 1] == "auto"
    assert "store" not in b and "store" not in p
    form.compact = True
    b, p = build_args(form), plan_args(form)
    assert b[b.index("--layout") + 1] == "store" and p[p.index("--layout") + 1] == "store"
    assert "--cache-dir" in p                     # the plan hashes to size the store: one cache with build


def test_diff_forms_puts_a_compact_change_in_the_rebuild_bucket(tmp_path):
    from dataclasses import replace
    before = _form(tmp_path, 2)
    after = replace(before, compact=True)
    menu, rebuild = diff_forms(before, after)
    assert menu == [] and rebuild == ["compact layout on"]
    assert diff_forms(after, before)[1] == ["compact layout off"]
    assert diff_forms(before, replace(before))[1] == []


def test_parse_plan_reads_the_shared_row_and_the_strip_says_so():
    text = ("image-size 0 /dev/mmcblk0p3 3000000000 a.raw\n"
            "image-size 1 /dev/mmcblk0p3:img1 1000000000 b.raw\n"
            "image-size free 5000000000 room for updates in the games partitions\n"
            "image-size shared 2500000000 stored once, shared by content\n"
            "image-size overhead 1000000000 boot + rootfs + data + dump + metadata\n"
            "image: 19531250 sectors = 10000000000 bytes (10.00 GB)\n"
            "  fits Stern 16G image size 15494807552: YES (spare 5494807552)\n")
    info = parse_plan(text)
    assert info["shared"] == 2500000000 and info["free"] == 5000000000 and info["bytes"] == 10000000000
    view = card_size_view(info)
    assert view["detail"] == "4.00 GB of games, 2.50 GB saved, 5.00 GB free."
    assert view["saved"] == 2500000000
    assert sum(b for _l, b, _k in view["bands"]) == 10000000000     # the saving is not a band
    assert parse_plan("image-size free 1\n")["shared"] is None
    info["shared"] = None
    v2 = card_size_view(info)
    assert v2["detail"] == "4.00 GB of games, 5.00 GB free for updates." and v2["saved"] == 0


#: The report's own card (C FB, PAD-137): 10.83 GB of games and 6.21 GB of
#: room for updates, which together want a 32 GB card the games alone would
#: not.  Whole sectors, and the rows plus the room plus the overhead add up
#: to the total, the way the tool's own arithmetic does.
PLAN_ROOMY = (
    "image-size 0 /dev/mmcblk0p3 1600000000 Abbey.raw\n"
    "image-size 1 /dev/mmcblk0p7:img1 4600000000 Pepper.raw\n"
    "image-size 2 /dev/mmcblk0p7:img2 4630000128 Revolver.raw\n"
    "image-size free 6210000384 room for updates in the games partitions\n"
    "image-size overhead 609999872 boot + rootfs + data + dump + metadata\n"
    "image: 34472657 sectors = 17650000384 bytes (17.65 GB)\n"
    "  fits Stern 8G  image size 7861174272: NO (spare -9788826112)\n"
    "  fits Stern 16G image size 15494807552: NO (spare -2155192832)\n"
    "  fits Stern 32G image size 30359420928: YES (spare 12709420544)\n")


def test_the_strip_says_why_the_card_is_bigger_than_the_games():
    """C FB, PAD-137: "I was wondering why it suggested a 32gb card for my
    images when it looks like it does not break 16gb".  Both numbers were
    already on the strip; what was missing was the sum that joins them."""
    view = card_size_view(parse_plan(PLAN_ROOMY))
    assert view["head"] == "32 GB" and not view["over"]
    assert view["detail"] == (
        "10.83 GB of games + 6.21 GB free for updates = 17.65 GB, "
        "so 32 GB and not 16 GB.")
    # ...and the line still fits the strip, which gives the BAR up before
    # it gives up the words
    assert len(view["detail"]) <= multiboot_core.MultibootPanel.SIZE_DETAIL_MAX
    # the paragraph behind it names the smaller card's real size, the build's
    # own, and the one tick that does something about it
    assert "A 16 GB card holds 15.49 GB and this build is 17.65 GB." \
        in view["why"]
    assert "Compact build" in view["why"]
    # the card sizes are the PLAN's, never a table in the view: drop the
    # 16G row and there is no smaller card to name
    info = parse_plan(PLAN_ROOMY)
    del info["fits"]["16G"]
    assert multiboot_core.card_without_room(
        info, info["bytes"], info["free"], "32 GB") is None


def test_the_strip_explains_nothing_when_the_games_want_that_card_anyway():
    """The clause is only for a card the ROOM bought.  A list whose games
    need the card on their own gets the two numbers and no lecture."""
    text = PLAN_ROOMY.replace("image-size 1 /dev/mmcblk0p7:img1 4600000000",
                              "image-size 1 /dev/mmcblk0p7:img1 16000000000")
    text = text.replace("image: 34472657 sectors = 17650000384 bytes",
                        "image: 56736329 sectors = 29050000384 bytes")
    text = text.replace("32G image size 30359420928: YES (spare 12709420544)",
                        "32G image size 30359420928: YES (spare 1309420544)")
    text = text.replace("16G image size 15494807552: NO (spare -2155192832)",
                        "16G image size 15494807552: NO (spare -13555192832)")
    view = card_size_view(parse_plan(text))
    assert view["head"] == "32 GB"
    assert view["detail"] == "22.23 GB of games, 6.21 GB free for updates."
    assert view["why"] == ""
    # ...and neither does the compact layout's own sentence grow one
    assert card_size_view(parse_plan(PLAN_ROOMY.replace(
        "image-size free", "image-size shared 900000000 stored once\n"
        "image-size free")))["why"] == ""


def test_the_two_confirm_boxes_name_each_other():
    """C FB, PAD-137: "the confirm sound is both in the image properties and
    the overall properties which seems to not be in synch".  One setting
    falling back to the other - so each box says what the other is doing."""
    rows = [ImageRow("a.raw", title="Abbey Road"),
            ImageRow("b.raw", title="Sgt. Pepper", confirm="synth"),
            ImageRow("c.raw", title="Revolver")]
    assert multiboot_core.own_confirm_note(rows) == (
        "1 of the 3 images has a confirm sound of its own - Sgt. Pepper - "
        "and does not use this one.")
    rows[2].confirm = r"D:\wav\ComeTogether.wav"
    assert multiboot_core.own_confirm_note(rows) == (
        "2 of the 3 images have a confirm sound of their own - Sgt. Pepper "
        "and Revolver - and do not use this one.")
    # a row that inherits says so with '' or the word, and a name a LOAD read
    # off the card is the image's own
    assert multiboot_core.own_confirm_note(
        [ImageRow("a.raw", confirm=""), ImageRow("b.raw", confirm="menu")]) == ""
    assert multiboot_core.has_own_confirm(
        ImageRow("a.raw", confirm="confirm2.wav", confirm_on_card=True))
    # ...and a long list does not read out every name
    many = [ImageRow("%d.raw" % i, title="T%d" % i, confirm="synth")
            for i in range(5)]
    assert "T0, T1, T2 and 2 more" in multiboot_core.own_confirm_note(many)
    # an untitled row is named the way the list names it
    assert multiboot_core.plain_title(ImageRow(""), 2) == "image 2"
    assert multiboot_core.plain_title(
        ImageRow("D:/x/turtles_pro-1_59_0.Release.8G.sdcard.raw")) == \
        "turtles_pro-1_59_0"
    # and the other direction: what the image dialog's 'menu' resolves to
    assert multiboot_core.menu_confirm_now("auto") == "auto"
    assert multiboot_core.menu_confirm_now("") == "none"
    assert multiboot_core.menu_confirm_now(r"D:\wav\ComeTogether.wav") == \
        "ComeTogether.wav"


def test_form_from_inspect_reads_the_store_layout_as_the_compact_tick(monkeypatch, tmp_path):
    _win(monkeypatch)
    info = _rich_report(tmp_path)
    card = str(tmp_path / "multi" / "card.multi.raw")
    assert form_from_inspect(info, card, "")[0].compact is False
    info["layout"] = "store"
    assert form_from_inspect(info, card, "")[0].compact is True


# ---------------------------------------------------------------------------
# item 99: the menu straight off the SD card in the reader
# ---------------------------------------------------------------------------
def test_a_half_bypassed_tree_counts_as_armed_for_the_apply():
    """Item 98: a tree whose tick is off but whose grade restore is still live
    ('half') has a bypass left to finish, so it reads as armed."""
    from pinball_decryptor.webui.multiboot_core import bypass_state
    assert bypass_state({"images": [{"bypass": "bypassed"}, {"bypass": "half"}]}) == (False, True)
    assert bypass_state({"images": [{"bypass": "bypassed"}, {"bypass": "bypassed"}]}) == (True, False)


def test_menu_card_image_path_names_the_card_under_temp(monkeypatch, tmp_path):
    from pinball_decryptor.webui.multiboot_core import menu_card_image_path
    from pinball_decryptor.core.drives import PhysicalDrive
    monkeypatch.setattr("pinball_decryptor.webui.multiboot_core.tempfile.gettempdir",
                        lambda: str(tmp_path))
    d = PhysicalDrive(device_path="\\\\.\\PHYSICALDRIVE4", model="NORELSYS 1081CS1",
                      size_bytes=15931539456, bus_type="USB")
    p = menu_card_image_path(d)
    assert p == os.path.join(str(tmp_path), "pinball_spike2_multiboot", "cards",
                             "NORELSYS_1081CS1-16G.menu.raw")


# ---------------------------------------------------------------------------
# item 98: the validator bypass is ALWAYS ON - no tick, no restore from the app
# ---------------------------------------------------------------------------
def test_build_and_update_args_always_carry_the_bypass(tmp_path):
    """David, after the TMNT booted clean on both images: "we tested that
    this bypass works, we don't need to make it optional. it should always
    be on now." """
    from pinball_decryptor.webui.multiboot_core import build_args, update_args
    form = _form(tmp_path, 2)
    card = str(tmp_path / "multi" / "card.multi.raw")
    upd = update_args(form, card)
    assert "--bypass-validation" in upd and "--restore-validation" not in upd
    assert "--bypass-validation" in build_args(form)
    assert not hasattr(form, "bypass")


# --------------------------------------------------------------------------
# Recover images… - a card someone else built, made this machine's
# --------------------------------------------------------------------------


# ---- item 106: a GROUP row - several games behind one card -----------------

def _group_form(tmp_path, n_members=3):
    """A form of: the primary, one plain extra, and a group of `n_members`."""
    mb = multiboot_core
    paths = []
    for name in ["stock", "custom"] + ["set%d" % i for i in range(1, n_members + 1)]:
        f = tmp_path / (name + ".raw")
        f.write_bytes(b"x")
        paths.append(str(f))
    rows = [ImageRow(path=paths[0], title="STERN STOCK"),
            ImageRow(path=paths[1], title="CUSTOM A"),
            ImageRow(path="", title="JUKEBOX",
                     subtitle="a different set every power-up",
                     members=[mb.MemberRow(path=q, title="SET %d" % (k + 1))
                              for k, q in enumerate(paths[2:])])]
    return MultibootForm(images=rows, out=str(tmp_path / "card.raw")), paths


def test_rows_are_cards_and_trees_are_games(tmp_path):
    """The two index spaces meet in form_trees and nowhere else. images.conf,
    the choice file, --titles and --art N= count IMAGES; the table, the preview
    and --highlight count CARDS. They are the same number until a group row
    makes them differ, and every bug this feature can have is a place that used
    one where it meant the other."""
    mb = multiboot_core
    form, paths = _group_form(tmp_path)
    assert len(form.images) == 3, "three cards"
    trees = mb.form_trees(form)
    assert [t[0] for t in trees] == [0, 1, 2, 3, 4], "five games"
    assert [t[1] for t in trees] == paths
    assert [t[2] for t in trees] == [0, 1, 2, 2, 2], "the row each game sits in"
    assert [t[3] for t in trees] == [None, None, 0, 1, 2]
    assert [mb.row_first_image(form, i) for i in range(3)] == [0, 1, 2]
    assert mb.is_group(form.images[2]) and not mb.is_group(form.images[0])


def test_a_group_row_becomes_group_and_member_flags_in_row_order(tmp_path):
    mb = multiboot_core
    form, paths = _group_form(tmp_path)
    args = mb._image_args(form)
    assert args[:2] == ["--primary", mb.wsl(paths[0])]
    assert args[2:4] == ["--extra", mb.wsl(paths[1])]
    assert args[4:6] == ["--group", "JUKEBOX|a different set every power-up"]
    assert args[6:] == ["--member", mb.wsl(paths[2]),
                        "--member", mb.wsl(paths[3]),
                        "--member", mb.wsl(paths[4])]


def test_a_group_forces_the_compact_build(tmp_path):
    """David, 2026-09-09. mkmulticard refuses parts/multi with a group outright;
    the tab ticks the box so the reason is visible before the press."""
    mb = multiboot_core
    form, _paths = _group_form(tmp_path)
    assert form.compact is False, "the tick itself is still off by default"
    assert mb.form_compact(form) is True
    pa = mb.plan_args(form)
    assert pa[pa.index("--layout") + 1] == "store"
    ba = build_args(form)
    assert ba[ba.index("--layout") + 1] == "store"
    # ...and a form with no group is left exactly as it was
    plain = MultibootForm(images=form.images[:2], out=form.out)
    assert mb.form_compact(plain) is False
    pb = build_args(plain)
    assert pb[pb.index("--layout") + 1] == "auto"


def test_titles_and_the_default_are_per_game_not_per_row(tmp_path):
    """images.conf's image= lines are one per GAME, so --titles is too; a group
    card's own title rides on its --group flag. --default names an image as
    well, and a group row is named by its first member."""
    form, _paths = _group_form(tmp_path)
    # THE GROUP GOES FIRST among the extras, so a row index and an image index
    # can never agree by luck: the plain row is row 2 and image 4.
    form.images = [form.images[0], form.images[2], form.images[1]]
    args = build_args(form)
    titles = args[args.index("--titles") + 1].split(";")
    assert titles == ["STERN STOCK", "SET 1", "SET 2", "SET 3", "CUSTOM A"]
    assert "JUKEBOX" not in titles, "the card's title goes on --group"
    form.default = 1                                  # the group ROW
    da = build_args(form)
    assert da[da.index("--default") + 1] == "1", "a group row is named by its first member"
    form.default = 2                                  # the PLAIN row after it
    db = build_args(form)
    assert db[db.index("--default") + 1] == "4", "row 2 is image 4 under a 3-member group"


def test_the_media_indexes_are_games(tmp_path):
    """media.json carries one row per games tree, which is what plan_media
    expects, and a group card takes its first member's. Using the row number
    here would shift every media row after the first group."""
    args = multiboot_core.prepare_args(_group_form(tmp_path)[0],
                                      str(tmp_path / "media"))
    arts = [args[i + 1] for i, a in enumerate(args) if a == "--art"]
    assert [x.split("=")[0] for x in arts] == ["0", "1", "2", "3", "4"]


def test_the_preview_conf_draws_one_card_per_row(tmp_path):
    form, _paths = _group_form(tmp_path)
    form.default = 2
    text = write_preview_conf(form)
    kinds = [l.split("=")[0] for l in text.splitlines()
             if l[:6] in ("image=", "group=")]
    assert kinds == ["image", "image", "group", "image", "image", "image"]
    assert "group=2-4|JUKEBOX|a different set every power-up" in text
    assert "default=2" in text, "the group row's first member, not the row"


def test_a_member_change_is_a_rebuild_not_a_menu_edit(tmp_path):
    """Adding, removing or swapping a member changes which games are on the
    card, which only a build can do. If the key did not move with them, a
    member change would look like a menu edit and an inject would leave the
    card's games as they were."""
    before, _paths = _group_form(tmp_path)
    after, _ = _group_form(tmp_path)
    assert diff_forms(before, after)[1] == []
    after.images[2].members = after.images[2].members[:2]
    _menu, rebuild = diff_forms(before, after)
    assert rebuild, "dropping a member must ask for a build"
    # ...and a title change on the same row is still only a menu edit
    same, _ = _group_form(tmp_path)
    same.images[2].title = "JUKEBOX 2"
    menu, rebuild = diff_forms(before, same)
    assert rebuild == [] and menu


def test_the_form_refuses_a_group_that_cannot_be_built(tmp_path):
    form, _paths = _group_form(tmp_path)
    assert validate_form(form) == []
    one = _group_form(tmp_path)[0]
    one.images[2].members = one.images[2].members[:1]
    assert any("at least 2" in e for e in validate_form(one))
    # the machine boots image 0 when the menu is not honoured, so it cannot roll
    first = _group_form(tmp_path)[0]
    first.images = [first.images[2], first.images[0], first.images[1]]
    assert any("primary and cannot be a random group" in e
               for e in validate_form(first))
    # the same .raw twice, once plain and once as a member
    dup = _group_form(tmp_path)[0]
    dup.images[1].path = dup.images[2].members[0].path
    assert any("listed twice" in e for e in validate_form(dup))
    # a member file that is not there
    gone = _group_form(tmp_path)[0]
    gone.images[2].members[1].path = str(tmp_path / "nope.raw")
    assert any("no such file" in e for e in validate_form(gone))


def test_a_saved_state_brings_a_group_back_as_rows_not_as_a_string(tmp_path):
    """str([]) is "[]", a truthy STRING - so an ordinary row restored from a
    state file used to read as a group with one member called "[". Every
    non-bool row field went through str(); this one is a list of rows."""
    mb = multiboot_core
    form, paths = _group_form(tmp_path)
    doc = [mb.asdict(r) for r in form.images]
    back = rows_from_state(doc)
    assert len(back) == 3
    assert not mb.is_group(back[0]) and not mb.is_group(back[1])
    assert mb.is_group(back[2])
    assert [m.path for m in back[2].members] == paths[2:]
    assert [m.title for m in back[2].members] == ["SET 1", "SET 2", "SET 3"]
    assert mb._image_args(MultibootForm(images=back, out="x")) == mb._image_args(form)
def test_the_list_says_a_row_is_a_group_and_what_code_it_runs():
    """Nothing else in the table can tell a group from a plain image, and "why
    does this card have no file" is the first thing a person would otherwise
    ask."""
    mb = multiboot_core
    row = ImageRow(path="", title="JUKEBOX",
                   members=[mb.MemberRow(path="/nope/a.raw", version="1.29.0"),
                            mb.MemberRow(path="/nope/b.raw", version="1.29.0"),
                            mb.MemberRow(path="/nope/c.raw", version="1.29.0")])
    cell = list_title(row, 2)
    assert "JUKEBOX" in cell and "(random, 3 sets)" in cell
    assert "[3 not on this machine]" in cell
    assert mb.list_code(row) == "1.29.0"
    # a jukebox whose members run different code is worth seeing: swapping
    # between two versions reflashes the node boards at every boot
    row.members[1].version = "1.30.0"
    assert mb.list_code(row) == "mixed"
    # ...but a version that has simply not been READ yet is blank, and calling
    # that a disagreement would alarm somebody over nothing: only two different
    # KNOWN versions are mixed.
    row.members[1].version = ""
    assert mb.list_code(row) == "1.29.0"
    for m in row.members:
        m.version = ""
    assert mb.list_code(row) == "", "nothing read yet says nothing"
    plain = ImageRow(path="", title="CUSTOM", version="1.29.0")
    assert mb.list_code(plain) == "1.29.0"
    assert "(random" not in list_title(plain, 1)


def _grouped_inspect(tmp_path):
    """An inspect report for a card of: the primary, then a 3-member group -
    the shape mkmulticard writes (one entry per GAME plus a groups block)."""
    paths = []
    for n in ("stock", "s1", "s2", "s3"):
        f = tmp_path / (n + ".raw")
        f.write_bytes(bytes(16))
        paths.append(str(f))
    images = [{"index": i, "device": "/dev/mmcblk0p3" if i == 0
               else "/dev/mmcblk0p3:img%d" % i,
               "source": paths[i], "source_exists": True,
               "title": ["STERN STOCK", "SET 1", "SET 2", "SET 3"][i],
               "subtitle": "", "version": "1.29.0"} for i in range(4)]
    info = {"card": "c.raw", "images": images, "warnings": [],
            "groups": [{"index": 0, "title": "JUKEBOX",
                        "subtitle": "a different set every power-up",
                        "members": [1, 2, 3], "art": "art1.png",
                        "anim": None, "music": None, "confirm": None}],
            "default": 1, "timeout": 15, "volume": 50, "layout": "store"}
    return info, paths


def test_loading_a_card_folds_its_groups_back_into_rows(tmp_path):
    """inspect reports one entry per GAME plus a groups block; the tab's list is
    CARDS. Without the fold a loaded jukebox card would come up as three
    ordinary rows and an Apply would flatten it."""
    mb = multiboot_core
    info, paths = _grouped_inspect(tmp_path)
    rows, _warnings = mb.rows_from_inspect(info)
    assert len(rows) == 2, "one primary and one group card"
    assert not mb.is_group(rows[0]) and rows[0].path == host_path(paths[0])
    g = rows[1]
    assert mb.is_group(g)
    assert g.title == "JUKEBOX" and g.subtitle == "a different set every power-up"
    assert [m.path for m in g.members] == [host_path(q) for q in paths[1:]]
    assert [m.title for m in g.members] == ["SET 1", "SET 2", "SET 3"]
    assert [m.version for m in g.members] == ["1.29.0"] * 3
    # the CARD's media is the group's own, not its first member's row
    assert g.art == "art1.png" and g.art_on_card is True
    # ...and it comes straight back out as the same flags
    form = mb.MultibootForm(images=rows, out="x")
    args = mb._image_args(form)
    assert args[2:4] == ["--group", "JUKEBOX|a different set every power-up"]
    assert args[4:] == ["--member", mb.wsl(host_path(paths[1])),
                        "--member", mb.wsl(host_path(paths[2])),
                        "--member", mb.wsl(host_path(paths[3]))]


def test_a_groups_block_this_tool_cannot_make_sense_of_is_left_alone(tmp_path):
    """A report whose members do not all exist must not be half-folded: the
    card would then be silently changed by a load."""
    mb = multiboot_core
    info, _paths = _grouped_inspect(tmp_path)
    info["groups"][0]["members"] = [1, 2, 99]
    rows, _w = mb.rows_from_inspect(info)
    assert len(rows) == 4 and not any(mb.is_group(r) for r in rows)
    # ...and a one-member group is a plain card, not a group
    info["groups"][0]["members"] = [2]
    rows, _w = mb.rows_from_inspect(info)
    assert len(rows) == 4 and not any(mb.is_group(r) for r in rows)
    # a card with no groups at all is exactly what it always was
    info.pop("groups")
    rows, _w = mb.rows_from_inspect(info)
    assert len(rows) == 4 and not any(mb.is_group(r) for r in rows)
_OK_PATH = ("missing", "Build & verify will write a new card at x.", "gray", False)


def test_the_status_row_counts_a_groups_games_not_its_empty_path(tmp_path):
    """A GROUP row has no path of its own - its games are its members - so
    reading row.path here reported a perfectly good jukebox card as "Image 1
    has no file" and put a red cross on the status row. Caught on the first
    screenshot of the finished tab."""
    mb = multiboot_core
    form, paths = _group_form(tmp_path)
    checks = dict((k, (state, detail))
                  for k, _lbl, state, detail in
                  status_checks(form.images, _OK_PATH, "", card="none"))
    state, detail = checks["images"]
    assert state == "ok", detail
    assert "3 cards over 5 games" in detail
    # a group whose games are not on this machine still says which game
    gone = _group_form(tmp_path)[0]
    gone.images[2].members[1].path = str(tmp_path / "nope.raw")
    checks = dict((k, (state, detail))
                  for k, _lbl, state, detail in
                  status_checks(gone.images, _OK_PATH, "", card="none"))
    state, detail = checks["images"]
    assert state == "bad"
    assert "Image 2, game 2 is not on this machine" in detail, detail
    # and a plain list is worded exactly as it always was
    plain = mb.MultibootForm(images=form.images[:2], out="x")
    checks = dict((k, (state, detail))
                  for k, _lbl, state, detail in
                  status_checks(plain.images, _OK_PATH, "", card="none"))
    assert checks["images"][0] == "ok"
    assert checks["images"][1] == "2 images, in the order the menu offers them."
# ---- item 106 reopened: RANDOM beside the builds it rolls between ----------


def test_loading_a_card_keeps_a_keeping_groups_member_rows(tmp_path):
    """A consuming group takes its members' rows away; a keeping one adds a
    card in front of rows that stay exactly where they are."""
    mb = multiboot_core
    info, paths = _grouped_inspect(tmp_path)
    info["groups"][0].update(keep=True, members=[1, 2], pos=4)
    rows, _w = mb.rows_from_inspect(info)
    # 4 images, and the group card LAST because that is where its line sat
    assert len(rows) == 5
    assert [mb.is_group(r) for r in rows] == [False, False, False, False, True]
    assert rows[4].keep is True
    assert [m.path for m in rows[4].members] == [host_path(q) for q in paths[1:3]]
    # ...and with pos 0 its card is first
    info["groups"][0]["pos"] = 0
    rows, _w = mb.rows_from_inspect(info)
    assert mb.is_group(rows[0]) and len(rows) == 5
def test_the_status_row_does_not_call_a_keeping_groups_games_duplicates(tmp_path):
    """A keeping group's games ARE other rows' - being listed elsewhere is the
    point of it. Counting that as a duplicate is what put a red cross on
    David's perfectly good two-builds-plus-RANDOM card."""
    mb = multiboot_core
    paths = _images(tmp_path, 2)
    rows = [ImageRow(path=paths[0], title="A"), ImageRow(path=paths[1], title="B"),
            ImageRow(path="", title="RANDOM", keep=True,
                     members=[mb.MemberRow(path=paths[0]), mb.MemberRow(path=paths[1])])]
    checks = dict((k, (st, d)) for k, _l, st, d in
                  status_checks(rows, _OK_PATH, "", card="none"))
    state, detail = checks["images"]
    assert state == "ok", detail
    assert "3 cards over 2 games" in detail, detail
    # a CONSUMING group still counts its games, because they are its own
    rows[2].keep = False
    rows[2].members = [mb.MemberRow(path=str(tmp_path / "c.raw")),
                       mb.MemberRow(path=str(tmp_path / "d.raw"))]
    for n in ("c.raw", "d.raw"):
        (tmp_path / n).write_bytes(bytes(16))
    checks = dict((k, (st, d)) for k, _l, st, d in
                  status_checks(rows, _OK_PATH, "", card="none"))
    assert checks["images"][0] == "ok"
    assert "3 cards over 4 games" in checks["images"][1]


# ---- item 106: a RANDOM card's own picture ---------------------------------

def test_a_random_cards_pictures_round_trip_through_the_row(tmp_path):
    """Every style the dialog offers has to come back off the row as the style
    that was chosen. The row stores two fields and the dialog offers one
    choice, so the reading is where a pairing can be lost - and two of the nine
    (cycling and stack) deliberately share a still."""
    mb = multiboot_core
    row = ImageRow(path="", members=[object(), object()])
    for kind in mb.GROUP_MEDIA_NAMES:
        mb.set_group_media(row, kind, str(tmp_path / "own.png"))
        assert mb.group_media_kind(row) == kind, (kind, row.art, row.anim)
    # ...and a row from before this existed reads as the default rather than as
    # a file called 'auto'
    row.art, row.anim = "auto", "none"
    assert mb.group_media_kind(row) == mb.GROUP_MEDIA_DEFAULT == "cycling"
    # a file the LOAD read off the card is the card's own, as for an image
    row.art, row.art_on_card = "gart0.png", True
    assert mb.group_media_kind(row) == "card"


# ---- item 106: deleting a game, and picking games that are already here ----
