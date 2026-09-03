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

import json
import os
import shlex
import sys
import time
from types import SimpleNamespace

import pytest

from tests.conftest import HAS_DISPLAY
from tests.test_gui_smoke import app  # noqa: F401  (fixture)

from pinball_decryptor.gui import emulate_tab, multiboot_tab
from pinball_decryptor.gui.multiboot_tab import (
    ANIM_LABEL, DEFAULT_SELECTOR_DIR, FRAME_H, FRAME_W, INSPECT_JSON,
    PREVIEW_BUILD_DIR, PREVIEW_MAX_FRAMES,
    ImageRow, MultibootForm, anim_period_ms, anim_spec, apply_commands,
    art_spec, build_commands, bypass_commands, card_path_state, cell_anim,
    cell_art, default_output_path, diff_forms, frame_pattern,
    manifest_sounds, menu_from_state, parse_snapshot_frames, path_root,
    probe_card_path, rows_from_state,
    edit_status_text, ensure_selector_args, fit_factors, form_from_inspect,
    host_path, inject_commands, inspect_commands, list_title,
    loaded_media_dir, media_fingerprint, media_specs_changed,
    menu_summary, parse_anim_frames, parse_inspect, parse_plan, parse_refusal,
    parse_selector_path, plan_commands, prepare_commands, preview_box,
    preview_fingerprint, preview_prepare_args, preview_snapshot_args,
    rebuild_blockers, size_plan_text, snapshot_commands, split_anim_source,
    split_art_source, suggest_title, under_library, validate_form,
    write_preview_conf)


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


class _FakeAudio:
    """A :class:`PreviewAudio` that writes down what it was asked to play.

    The real one is tested in tests/test_preview_audio.py, device and all;
    what matters HERE is which WAV the tab asks for and when, so this
    records and answers the four read-only properties the tab reads."""

    def __init__(self, volume=50, backend_factory=None, threaded=True,
                 on_status=None):
        self.volume = volume
        self.calls = []
        self.looping = None
        self.available = True
        self.backend_name = "sounddevice"
        self.why_silent = ""
        self.status = "Sound plays through sounddevice."

    def loop(self, path):
        self.calls.append(("loop", path))
        self.looping = path

    def play(self, path):
        self.calls.append(("play", path))

    def set_volume(self, volume):
        self.volume = volume
        self.calls.append(("volume", volume))

    def stop(self):
        self.calls.append(("stop", None))
        self.looping = None

    def played(self, kind):
        return [p for k, p in self.calls if k == kind]


def _fake_audio(monkeypatch):
    """Every player the tab makes from now on is a :class:`_FakeAudio`."""
    made = []

    def factory(**kw):
        made.append(_FakeAudio(**kw))
        return made[-1]
    monkeypatch.setattr(multiboot_tab, "PreviewAudio", factory)
    return made


def _media_set(panel, images=2, music=True, sounds=True, own_confirm=None):
    """A prepared media directory for the panel's output: media.json the
    way selectmedia writes it, and a file for every name in it.  A
    ``--visual-only`` prepare (the one the preview runs for itself) is
    ``sounds=False``: the music is there, the two menu sounds are not."""
    media = panel.media_dir()
    os.makedirs(media, exist_ok=True)
    rows = []
    for i in range(images):
        rows.append({"art": "art%d.png" % i, "anim": None,
                     "music": ("music%d.wav" % i) if music else None,
                     "confirm": own_confirm if (own_confirm and i == 1)
                     else None})
    manifest = {"images": rows,
                "sound_move": "move.wav" if sounds else None,
                "sound_confirm": "confirm.wav" if sounds else None,
                "volume": 50}
    for row in rows:
        for name in row.values():
            if name:
                open(os.path.join(media, name), "wb").close()
    for name in (manifest["sound_move"], manifest["sound_confirm"]):
        if name:
            open(os.path.join(media, name), "wb").close()
    with open(os.path.join(media, "media.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    # ...and the FORM agrees with it, the way it does after a prepare or a
    # load: a row whose Music says 'none' has none, whatever is still
    # sitting in the directory from the last one.
    for i, row in enumerate(panel._rows[:images]):
        row.music = ("music%d.wav" % i) if music else "none"
        # ...and the same for the confirm, which the form decides too: a
        # row with a sound of its own says so ('auto' is one way), and ""
        # is the row that falls back to the menu's.
        row.confirm = "auto" if (own_confirm and i == 1) else ""
    return media


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
    assert multiboot_tab.frame_path(pv, a, 1, 0) != \
        multiboot_tab.frame_path(pv, b, 1, 0)
    assert os.path.basename(multiboot_tab.frame_path(pv, a, 1, 3)) == \
        "frame_%s_1_3.ppm" % a
    # ...and the ones no form can ask for again are found so they can go
    os.makedirs(pv)
    for name in ("frame_%s_0_0.ppm" % a, "frame_%s_1_2.ppm" % a,
                 "frame_%s_0_0.ppm" % b, "images.conf", "notes.txt"):
        open(os.path.join(pv, name), "w").close()
    assert sorted(os.path.basename(p) for p in
                  multiboot_tab.stale_frames(pv, b)) == [
        "frame_%s_0_0.ppm" % a, "frame_%s_1_2.ppm" % a]
    assert multiboot_tab.stale_frames(str(tmp_path / "nope"), b) == []


def test_scaled_size_keeps_the_aspect_ratio_in_both_directions():
    """The smooth path: whatever the column's width, the picture fits it
    with its shape intact (Tk's own PhotoImage only halves and thirds)."""
    from pinball_decryptor.gui.multiboot_tab import scaled_size
    assert scaled_size(1360, 768, 680, 384) == (680, 384)
    assert scaled_size(1360, 768, 500, 384) == (500, 282)   # width-limited
    assert scaled_size(1360, 768, 900, 384) == (680, 384)   # height-limited
    assert scaled_size(1360, 768, 431, 384) == (431, 243)   # no whole step
    assert scaled_size(136, 77, 680, 384) == (678, 384)     # scaled UP
    assert scaled_size(0, 0, 100, 100) == (1, 1)


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
    assert cell_anim(ImageRow("x.raw", anim="auto", anim_start="20",
                              anim_seconds="2", anim_fps="8")) == \
        "auto @20s 2s 8fps"
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
                         bypass=False, sound_move="D:/a b/click.wav")
    assert menu_summary(form) == (
        "sounds click.wav / auto  ·  volume 35  ·  wait for START  ·  "
        "default 1  ·  bypass off")
    assert "15 s countdown" in menu_summary(MultibootForm(images=[]))
    assert "bypass on" in menu_summary(MultibootForm(images=[]))


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


def _panel(auto=False, plan=False, **kw):
    """A built Multi-boot panel on an invisible root, or a skip.

    THE AUTO PREVIEW IS OFF unless a test asks for it: it would otherwise
    fire ~350 ms into any test that pumps the loop and start the real
    selector under WSL.  The tests that are about it turn it on and stub
    the render.

    THE AUTOMATIC SIZE CHECK IS OFF for the same reason and by the same
    lever (*plan*): it is the other thing on this tab that runs a tool
    without being pressed, ~900 ms after the image list moves, and every
    test here moves the image list.

    The panel has no output pane of its own any more - its lines go to the
    app's shared Log at the foot of the window - so the sink is captured
    here and :func:`_pane` reads it back."""
    import tkinter as tk
    root = _root()
    frame = tk.Frame(root)
    frame.pack()
    sunk = []
    kw.setdefault("log", sunk.append)
    panel = multiboot_tab.MultibootPanel(frame, **kw)
    panel.build(frame)
    panel._auto_preview.set(bool(auto))
    panel._auto_plan = bool(plan)
    panel.sunk = sunk
    root.update()
    return root, panel


def _pane(panel):
    """Everything the panel has said, as one string - what used to be read
    out of its own Tool output pane, and is now in the app's Log."""
    return "\n".join(panel.log_lines())


def _fire_debounce(root, panel):
    """Run the pending preview debounce now, instead of in 350 ms."""
    job = panel._pv_debounce_job
    if job is not None:
        root.after_cancel(job)
        panel._pv_debounce_job = None
        panel._auto_render()
    root.update()


def _recorder(panel):
    """Replace the worker with a recorder: (cmds, on_step, on_done)."""
    calls = []

    def fake(cmds, on_step=None, on_done=None, quiet=(), preview=False):
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
        # two images and the template row that adds a third
        assert panel._tree.get_children() == ("0", "1", panel.ADD_ROW)
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
    """The per-row fields, now inside the Edit image… modal: the clip's
    start / length / fps live only while an animation is set, the
    video-frame file and time only for the 'video frame' art; every one
    lands in the row, the list cell says so, and a re-selected row loads
    them back."""
    root, panel = _panel()
    try:
        a, b = _images(tmp_path, 2)
        clip = tmp_path / "intro.mp4"
        clip.write_bytes(bytes(4))
        panel.add_image(a)
        panel.add_image(b)
        panel._tree.selection_set("1")
        root.update()
        dlg = panel.edit_image()
        root.update()
        assert dlg is panel._image_dialog
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
        # a typed video path in Art enables the time alone
        panel._ed_art.set(str(clip))
        assert str(panel._video_entry.cget("state")) == "disabled"
        assert str(panel._video_time.cget("state")) == "normal"
        panel._ed_art.set("video frame")
        dlg.ok()
        root.update()
        assert panel._image_dialog is None
        assert panel._video_entry is None          # the widgets went with it
        # the full detail is still what the row says, and the list carries
        # the short version of it
        assert multiboot_tab.cell_art(row) == "intro.mp4 @3s"
        assert multiboot_tab.cell_anim(row) == "auto @20s 2s 8fps"
        assert panel._tree.item("1")["values"][3] == "intro.mp4 @3s"
        assert panel._tree.item("1")["values"][4] == "auto @20s 2s 8fps"
        assert panel.form().images[0].anim_start == ""        # untouched
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


def test_the_modals_write_on_ok_and_change_nothing_on_cancel(tmp_path):
    """Both dialogs edit the tab's own variables, so a keystroke is live -
    and Cancel puts back exactly what was there."""
    root, panel = _panel()
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        panel._tree.selection_set("1")
        root.update()
        before = multiboot_tab.replace(panel.form().images[1])
        dlg = panel.edit_image()
        root.update()
        panel._ed_title.set("TMNT 1987")
        panel._ed_anim.set("auto")
        dlg.cancel()
        root.update()
        after = panel.form().images[1]
        assert (after.title, after.anim) == (before.title, before.anim)
        assert panel._ed_title.get() == before.title      # and the editor
        dlg = panel.edit_image(1)
        root.update()
        panel._ed_title.set("TMNT 1987")
        dlg.ok()
        root.update()
        assert panel.form().images[1].title == "TMNT 1987"
        assert panel._tree.item("1")["values"][1] == "TMNT 1987"
        # ...and the same for the menu settings
        menu = panel.open_menu_settings()
        root.update()
        assert panel._default_spin is not None
        panel._volume_var.set("35")
        panel._timeout_var.set("0")
        menu.cancel()
        root.update()
        assert panel._volume_var.get() == "50"
        assert panel._timeout_var.get() == "15"
        assert panel._default_spin is None
        menu = panel.open_menu_settings()
        root.update()
        panel._volume_var.set("35")
        menu.ok()
        root.update()
        assert panel.form().volume == 35
        assert "volume 35" in panel._menu_lbl.cget("text")
        # Escape is Cancel
        menu = panel.open_menu_settings()
        root.update()
        panel._volume_var.set("70")
        menu.top.event_generate("<Escape>")
        root.update()
        assert panel._volume_var.get() == "35"
    finally:
        root.destroy()


def test_an_image_can_have_a_confirm_sound_of_its_own(tmp_path):
    """David: the confirm sound should be customizable for each entry.  A
    row without one INHERITS the menu's - and the column says which, because
    a bracket is the only mark a Treeview cell can carry."""
    root, panel = _panel()
    try:
        a, b = _images(tmp_path, 2)
        panel.add_image(a)
        panel.add_image(b)
        panel._confirm_var.set("auto")
        # both inherit to start with
        assert [panel._tree.item(str(i))["values"][6] for i in (0, 1)] == \
            ["(auto)", "(auto)"]
        # give row 1 its own through the editor, the way the dialog does
        panel._tree.selection_set("1")
        panel._load_editor()
        assert panel._ed_confirm.get() == "menu"
        panel._ed_confirm.set("synth")
        assert panel._rows[1].confirm == "synth"
        assert panel._tree.item("1")["values"][6] == "synth"
        # the menu's sound changing moves the inheriting row and not the other
        panel._confirm_var.set("none")
        assert [panel._tree.item(str(i))["values"][6] for i in (0, 1)] == \
            ["(none)", "synth"]
        # ...and "menu" in the box is "" on the row, so it inherits again
        panel._ed_confirm.set("menu")
        assert panel._rows[1].confirm == ""
        assert panel._tree.item("1")["values"][6] == "(none)"
    finally:
        root.destroy()


def test_the_table_carries_each_images_settings_in_columns(tmp_path):
    """The table is the full width of the tab, so what an image is SET TO
    is columns rather than one phrase - and the four icons at the right
    edge act on the row they are in."""
    root, panel = _panel()
    try:
        a, b = _images(tmp_path, 2)
        panel.add_image(a)
        panel.add_image(b)
        assert panel._tree.item("0")["values"][:8] == [
            0, "turtles_pro-1_59_0", "Release", "auto", "none", "none",
            "(auto)", ""]
        panel._rows[1].anim = "auto"
        panel._rows[1].music = str(tmp_path / "bed.wav")
        panel._rows[1].version = "1.59.0"
        panel._refresh_tree(select=1)
        assert panel._tree.item("1")["values"][3:8] == [
            "auto", "auto", "bed.wav", "(auto)", "1.59.0"]
        # a row with no confirm of its own shows the MENU's, in brackets,
        # and follows it
        panel._confirm_var.set("synth")
        assert panel._tree.item("1")["values"][6] == "(synth)"
        # the icons: the first row cannot go up, the last cannot go down,
        # and the arrow says so instead of silently doing nothing
        assert panel._tree.item("0")["values"][8:] == ["✎", "−",
                                                       "△", "▼"]
        assert panel._tree.item("1")["values"][8:] == ["✎", "−",
                                                       "▲", "▽"]
        # ...and the template row is the last one, dim, with the '+'
        assert panel._tree.get_children()[-1] == panel.ADD_ROW
        add = panel._tree.item(panel.ADD_ROW)
        assert add["values"][:2] == ["+", panel.ADD_ROW_TEXT]
        assert add["tags"] == ["add"]
        # ...and the selected row's own .raw is on the line under the table
        assert panel._rows[1].path in panel._row_tip.text
    finally:
        root.destroy()


def _click_cell(root, panel, item, column):
    """Click the middle of one cell of the table, the way a mouse would -
    through the same <Button-1> binding, so identify_row / identify_column
    are what decide which row and which icon was hit."""
    import tkinter as tk
    root.update()
    root.update_idletasks()
    box = panel._tree.bbox(item, column)
    assert box, "cell %s/%s is not on screen" % (item, column)
    x, y, w, h = box

    class _E:
        pass
    ev = _E()
    ev.x, ev.y = x + w // 2, y + h // 2
    ev.x_root = panel._tree.winfo_rootx() + ev.x
    ev.y_root = panel._tree.winfo_rooty() + ev.y
    return panel._table_click(ev), tk


def test_the_row_icons_act_on_the_row_they_are_in(tmp_path):
    """The row IS where the row is worked on: a pencil, a minus and two
    arrows at its right edge, and a click on one of them acts on THAT row
    - which is why they are columns and not five buttons under the table."""
    root, panel = _panel()
    opened = []
    panel.edit_image = lambda index=None: opened.append(index)
    try:
        a, b, c = _images(tmp_path, 3)
        for p in (a, b, c):
            panel.add_image(p)
        root.update()
        # ▼ on row 0 moves it down...
        _click_cell(root, panel, "0", "down")
        assert [r.path for r in panel._rows] == [b, a, c]
        # ...and ▲ on row 1 puts it back
        _click_cell(root, panel, "1", "up")
        assert [r.path for r in panel._rows] == [a, b, c]
        # ▲ on the FIRST row is the outlined arrow and does nothing
        _click_cell(root, panel, "0", "up")
        assert [r.path for r in panel._rows] == [a, b, c]
        # ✎ opens that row's editor
        _click_cell(root, panel, "1", "edit")
        assert opened == [1]
        # − takes it off the card
        _click_cell(root, panel, "1", "del")
        assert [r.path for r in panel._rows] == [a, c]
        # ...and a click in a text column is an ordinary selection
        assert _click_cell(root, panel, "0", "title")[0] is None
    finally:
        root.destroy()


def test_the_template_row_adds_an_image(tmp_path):
    """The last row of the table is the '+': an empty card shows only that
    row, which is both the way in and the lesson."""
    root, panel = _panel()
    asked = []
    panel._add_image = lambda: asked.append(len(panel._rows))
    try:
        root.update()
        assert panel._tree.get_children() == (panel.ADD_ROW,)
        _click_cell(root, panel, panel.ADD_ROW, "title")
        assert asked == [0]
        # ...and a double-click on it does NOT open the editor for a row
        # that is not there
        assert panel._table_double_click(_Ev(panel, panel.ADD_ROW)) == "break"
    finally:
        root.destroy()


class _Ev:
    """A click event over one row of the table, for the double-click seam."""
    def __init__(self, panel, item):
        box = panel._tree.bbox(item) or (0, 0, 10, 10)
        self.x, self.y = box[0] + 2, box[1] + box[3] // 2
        self.x_root = panel._tree.winfo_rootx() + self.x
        self.y_root = panel._tree.winfo_rooty() + self.y


def test_the_footer_stages_are_this_tabs_own(tmp_path):
    """The progress row belongs to THIS tab's buttons: the Extract ladder
    says nothing about assembling a card.  Build & verify walks all four
    stages, Apply to card only the ones an inject touches."""
    seen = []
    root, panel = _panel(
        phase_fn=lambda index, total=None, status=None:
        seen.append((index, status)))
    try:
        for label, index in (("prepare", 0), ("build", 1), ("inject", 2),
                             ("verify", 3), ("bypass", 2), ("inspect", 3)):
            seen[:] = []
            panel._phase_step(label)
            assert seen and seen[0][0] == index, label
            assert seen[0][1], label            # ...and it says what it is
        # a step that is not a stage moves nothing
        seen[:] = []
        panel._phase_step("frame 0")
        assert seen == []
        # done, and failed
        seen[:] = []
        panel._phase_done(0, None)
        assert seen == [(-1, "Ready")]
        seen[:] = []
        panel._phase_done(2, "verify")
        assert seen == [(None, "verify failed")]
    finally:
        root.destroy()


def test_a_background_render_never_touches_the_footer(tmp_path, monkeypatch):
    """...and the preview is not one of this tab's buttons: a redraw must
    not walk the stage row or move the bar."""
    seen = []
    root, panel = _panel(
        phase_fn=lambda index, total=None, status=None: seen.append(index))

    class _Proc:
        stdout = iter(())

        def wait(self):
            return 0

    monkeypatch.setattr(multiboot_tab.subprocess, "Popen",
                        lambda *a, **kw: _Proc())
    try:
        assert panel._run_commands([("prepare", ["true"])],
                                   preview=True) is True
        _wait(root, lambda: not panel._pv_busy, seconds=10)
        assert seen == []
        # ...but a real run does
        assert panel._run_commands([("prepare", ["true"])]) is True
        _wait(root, lambda: not panel._busy, seconds=10)
        assert seen == [0, -1]
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
        # The two runs the tab now starts by ITSELF refuse this form too:
        # the size check has only one image to plan, and the sound prepare
        # would be preparing for the output the library rule just refused.
        panel._auto_plan = True
        del panel._rows[1:]
        assert panel._plan_now() is False
        assert calls == []
        panel.add_image(b)
        panel._rows[1].title = "TMNT 1987"
        panel._sound_var.set(True)
        assert panel._prepare_sounds() is False
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
        panel._auto_plan = True
        assert panel._plan_now() is True
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
        panel._sound_var.set(True)
        assert panel._prepare_sounds() is True
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
        # ...and the preview: refused, said on its own status line, and
        # nothing queued for the worker.
        assert panel.render_preview() is False
        assert "already in progress" in panel._pv_status.cget("text")
        assert panel._pv_cache == {}
        panel._set_busy(False)
        assert str(panel._build_btn.cget("state")) == "normal"
    finally:
        root.destroy()


def test_a_background_render_leaves_every_action_live(tmp_path, monkeypatch):
    """THE PREVIEW MUST NOT GREY THE TAB.  It renders itself once per
    typing pause; when that went through the destructive-action guard the
    whole tab - Apply, Build, Flash, Run, Load, Browse, New - went dead and
    swallowed clicks about once a second while someone typed a title."""
    import threading
    root, panel = _panel()
    running = threading.Event()

    class _Proc:
        """A tool that does not finish until the test says so, so the
        assertions below are made while the render really is in flight."""
        stdout = iter(())

        def wait(self):
            running.wait(10)
            return 0

    monkeypatch.setattr(multiboot_tab.subprocess, "Popen",
                        lambda *a, **kw: _Proc())
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        assert panel._run_commands([("frame 0", ["true"])],
                                   preview=True) is True
        # the guard the actions share is untouched...
        assert panel._busy is False
        # (Apply, Flash and Run in emulator have their own reasons to be
        # grey on a standalone panel with no card loaded; these are the
        # ones the busy guard ALONE would have taken away.)
        for btn in (panel._build_btn, panel._new_btn, panel._menu_btn,
                    panel._browse_btn):
            assert str(btn.cget("state")) != "disabled", str(btn)
        # The row's verb has its own reason too - there is nothing at the
        # path yet - so it is asked with the probe told there is, which is
        # what leaves the busy guard as the only thing that could grey it.
        panel._probe_done(panel._out_var.get().strip(), {"kind": "file"})
        assert panel._can_read
        # ...but a SECOND render is still refused while this one is up
        assert panel._pv_busy is True
        assert panel._run_commands([("frame 1", ["true"])],
                                   preview=True) is False
        running.set()
        _wait(root, lambda: panel._pv_busy is False, seconds=10)
        assert panel._pv_busy is False
    finally:
        running.set()
        root.destroy()


def test_an_action_waits_for_the_render_instead_of_being_refused(tmp_path):
    """A real action asked for while a background render is in flight is
    not refused: the render is told to stop after the step it is on, and
    the action starts the moment it lets go - with the action's own guard
    taken at once, so a second action is still refused."""
    root, panel = _panel()
    try:
        started = []
        panel._start_worker = lambda *a: started.append(a)
        panel._pv_busy = True                   # a render is on the worker
        assert panel._run_commands([("build", ["true"])]) is True
        assert started == []                    # queued, not started
        assert panel._busy is True              # ...and the guard is taken
        assert panel._pv_cancel is True
        assert panel._run_commands([("verify", ["true"])]) is False
        cmds = panel._pending_run[0]
        assert cmds == [("build", ["true"])]
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
        pane = _pane(panel)
        assert "[card] hello from the tool" in pane
        assert "plan: exit 0" in pane
        assert "Fits a 16 GB card" in panel._edit_lbl.cget("text")
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
        assert "SHOULD NOT RUN" not in _pane(panel)
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
        pane = _pane(panel)
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
        box = (panel._pv_w, panel._pv_h)
        assert panel.load_frame(big, highlight=1, frame=3, total=24) is True
        # the picture IS the box: the canvas is sized to the frame's own
        # 16:9, so a 1360x768 snapshot fills it exactly
        assert (panel._pv_photo.width(), panel._pv_photo.height()) == box
        assert panel._pv_canvas.find_all()                  # one image item
        assert panel._pv_canvas.type(panel._pv_canvas.find_all()[0]) == "image"
        assert panel._pv_status.cget("text") == "Image 2: frame 3 of 24"
        assert panel._hl_var.get() == "1" and panel._frame_var.get() == "3"
        assert panel._hl_touched is False       # programmatic, not typed
        assert int(panel._frame_spin.cget("to")) == 23
        small = _ppm(tmp_path / "small.ppm", 136, 77)
        assert panel.load_frame(small, highlight=0, frame=0, total=1)
        # SMOOTHLY, not in whole-number steps: a 136x77 frame is scaled to
        # the box it is given, where PhotoImage's zoom could only quadruple
        # it and leave a quarter of the box empty.
        assert (panel._pv_photo.width(), panel._pv_photo.height()) == \
            multiboot_tab.scaled_size(136, 77, *box)
        assert "a still" in panel._pv_status.cget("text")
        assert panel.load_frame(str(tmp_path / "missing.ppm")) is False
        assert "Cannot load" in panel._pv_status.cget("text")
        assert "Cannot load" in _pane(panel)
    finally:
        root.destroy()


def test_highlight_follows_default_until_typed(tmp_path):
    """...and the flippers follow the number of images: the control's range
    IS 'is there another card to move to', which is what the Image spinbox's
    ``to`` used to say."""
    root, panel = _panel()
    try:
        assert str(panel._flip_l.cget("state")) == "disabled"
        assert str(panel._flip_r.cget("state")) == "disabled"
        images = _images(tmp_path, 2)
        panel.add_image(images[0])
        assert str(panel._flip_l.cget("state")) == "disabled"  # one card
        panel.add_image(images[1])
        assert str(panel._flip_l.cget("state")) == "normal"
        assert str(panel._flip_r.cget("state")) == "normal"
        panel._default_var.set("1")
        assert panel._hl_var.get() == "1"
        panel._hl_var.set("0")                    # typed by hand
        panel._default_var.set("1")
        assert panel._hl_var.get() == "0"
    finally:
        root.destroy()


def test_the_flippers_move_the_highlight_and_wrap_both_ways(tmp_path):
    """codeselect.c's EV_LEFT / EV_RIGHT, and nothing else: hl = (hl + n -
    1) % n and hl = (hl + 1) % n.  A press is a hand-typed highlight, so
    the preview stops following the Default index from then on."""
    root, panel = _panel()
    try:
        for p in _images(tmp_path, 3):
            panel.add_image(p)
        panel._tree.selection_set("0")
        root.update()
        assert panel._hl_var.get() == "0" and panel._hl_touched is False
        assert panel.flip_right() is True
        assert panel._hl_var.get() == "1"
        assert panel._hl_touched is True         # steered by hand now
        panel.flip_right()
        assert panel._hl_var.get() == "2"
        panel.flip_right()
        assert panel._hl_var.get() == "0"        # wraps at the end
        panel.flip_left()
        assert panel._hl_var.get() == "2"        # ...and at the start
        # the Default index no longer moves it
        panel._default_var.set("1")
        assert panel._hl_var.get() == "2"
        # ...and the arrow keys are the same two buttons
        panel._key_flip_right()
        assert panel._hl_var.get() == "0"
        panel._key_flip_left()
        assert panel._hl_var.get() == "2"
        # a new card restarts its animation, and Play follows the highlight
        # - both of them the C's own 'if (hl != old_hl)'
        panel._set_var(panel._frame_var, "7")
        panel._play_var.set(True)
        panel._play_hl = 2
        panel.flip_right()
        assert panel._frame_var.get() == "0"
        assert panel._play_hl == int(panel._hl_var.get())
        panel._play_var.set(False)
        # one image is a menu with nothing to choose between
        panel._rows[:] = panel._rows[:1]
        panel._refresh_tree()
        assert panel.flip_right() is False
        assert str(panel._flip_r.cget("state")) == "disabled"
    finally:
        root.destroy()


def test_a_flipper_press_moves_the_table_and_the_editor_with_it(tmp_path):
    """The blue row in the table, the fields in the editor and the amber
    card in the picture are three views of ONE choice.  The flippers are
    the headline way of making it now, and a press that left the table
    naming the image the picture had just walked away from put the tab's
    two answers to 'which image' side by side on screen disagreeing."""
    root, panel = _panel()
    try:
        for p in _images(tmp_path, 3):
            panel.add_image(p)
        for i, title in enumerate(("ONE", "TWO", "THREE")):
            panel._rows[i].title = title
        panel._refresh_tree()
        panel._tree.selection_set("0")
        root.update()
        assert panel._ed_title.get() == "ONE"
        panel.flip_right()
        panel.flip_right()
        root.update()                   # <<TreeviewSelect>> is a queued event
        assert panel._hl_var.get() == "2"
        assert panel._tree.selection() == ("2",)
        assert panel._ed_title.get() == "THREE"
        # ...and back the other way, wrapping
        panel.flip_left()
        panel.flip_left()
        panel.flip_left()
        root.update()
        assert panel._hl_var.get() == "2"       # 2 -> 1 -> 0 -> 2
        assert panel._tree.selection() == ("2",)
        # a press is still a hand-typed highlight, whatever moved the table
        assert panel._hl_touched is True
    finally:
        root.destroy()


def test_the_caption_numbers_images_the_way_the_picture_does(tmp_path):
    """codeselect.c:545 draws every card's label 'IMAGE %d' with i + 1, so
    the words 20 px under that picture count from one too - the flippers
    walk IMAGE 1, IMAGE 2, IMAGE 3 and a caption walking Image 0, Image 1,
    Image 2 under them is the tab's own readout contradicting its frame.
    The index stays 0-based everywhere a tool reads it."""
    root, panel = _panel()
    try:
        for p in _images(tmp_path, 3):
            panel.add_image(p)
        ppm = _ppm(tmp_path / "f.ppm")
        assert panel.load_frame(ppm, 0, 0, 4) is True
        assert panel._pv_status.cget("text") == "Image 1: frame 0 of 4"
        assert panel._hl_var.get() == "0"       # ...and the index is not
        assert panel.load_frame(ppm, 2, 1, 4) is True
        assert panel._pv_status.cget("text") == "Image 3: frame 1 of 4"
        # the cache miss a flipper press finds, and the two sound lines,
        # count the same way
        panel.flip_right()                      # to image 0, undrawn
        assert panel._pv_status.cget("text").startswith("Image 1 frame 0")
        assert panel.play_confirm() is False
        assert panel._pv_status.cget("text").startswith("Image 1 has no")
        # ...and a still that cannot be played
        fp = preview_fingerprint(panel.form())
        panel._pv_totals[(fp, 0)] = 1
        panel._play_var.set(True)
        panel._play_toggled()
        assert panel._pv_status.cget("text") == \
            "Image 1 has no animation to play."
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
    """Play with a fake renderer: ONE run draws the whole animation (the
    length is not known yet, so the most one can have is asked for and the
    selector trims it), the ticks then walk 0, 1, 2, 0... out of the cache
    without rendering again, and a form change stops it with the reason on
    the status line."""
    root, panel = _panel()
    ppm = _ppm(tmp_path / "f.ppm")
    asked = []

    def fake_render(form, hl, frames):
        fp = preview_fingerprint(form)
        asked.append((hl, list(frames)))
        panel._pv_totals[(fp, hl)] = 3
        for n in frames:
            if n < 3:              # the selector trims K to the real length
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
        # ONE run, at once - pressing Play is all pressing Play takes
        assert asked == [(1, list(range(multiboot_tab.PREVIEW_MAX_FRAMES)))]
        for want in ("1", "2", "0", "1"):
            _tick(root, panel)
            assert panel._frame_var.get() == want
        assert asked == [(1, list(range(multiboot_tab.PREVIEW_MAX_FRAMES)))]
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


def test_an_edit_during_a_slow_animation_is_not_thrown_away(tmp_path):
    """Play re-arms at the CLIP's rate now, which the clamp lets reach 2 s,
    while the debounce fires at 350 ms and used to refuse - and clear - a
    render whenever Play was on.  So an edit made during a slow animation
    was dropped by the debounce and only noticed a whole frame later by the
    tick, with nothing left queued: the preview stopped following the form
    and never redrew."""
    root, panel = _panel(auto=True)
    ppm = _ppm(tmp_path / "f.ppm")
    asked = []

    def fake_render(form, hl, frames):
        fp = preview_fingerprint(form)
        asked.append((fp, hl, list(frames)))
        panel._pv_totals[(fp, hl)] = 3
        for n in frames:
            if n < 3:
                panel._pv_cache[(fp, hl, n)] = ppm
        return True
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        panel._rows[1].anim = "auto"
        panel._rows[1].anim_fps = "1"           # one frame a second
        panel._default_var.set("1")
        panel._render_frames = fake_render
        panel._play_var.set(True)
        panel._play_toggled()
        assert panel._play_var.get() is True
        before = preview_fingerprint(panel.form())
        assert asked and asked[-1][0] == before
        # ...now type a title, and let the DEBOUNCE fire (350 ms), which is
        # long before the next tick of a 1 fps clip
        panel._rows[1].title = "TMNT 1987 (renamed)"
        panel.schedule_preview()
        job, panel._pv_debounce_job = panel._pv_debounce_job, None
        root.after_cancel(job)
        panel._auto_render()
        after = preview_fingerprint(panel.form())
        assert after != before
        # Play is off, the strip says why AND that it is being redrawn -
        # in the ordinary colour, because editing while an animation runs
        # is an ordinary thing to do
        assert panel._play_var.get() is False
        assert "form changed" in panel._pv_status.cget("text")
        assert panel._pv_error is False
        # ...and the render for the NEW form really happened, in the same
        # pass: nothing was thrown away and nothing is left queued
        assert asked[-1][0] == after
        assert panel._pv_debounce_job is None and panel._pv_pending == 0
        # ...so the picture is following the form again by itself
        root.update()
        assert panel._pv_status.cget("text").startswith("Image 2: frame 0")
        assert panel._pv_cache.get((after, 1, 0)) == ppm
    finally:
        root.destroy()


def _tool_path(path):
    """*path* as the selector is really handed it - and therefore as it
    echoes it back.

    ``snapshot_commands`` puts every path through ``wsl()``, so what the
    tool prints on Windows is ``/mnt/c/…`` and NOT the ``C:\\…`` the tab
    must open.  These stand-ins replace ``snapshot_commands`` itself, one
    level ABOVE that call, so without this they would hand the fake
    selector a Windows path, have it echo a Windows path, and be blind to
    a whole class of Windows-only path bug (the animation run cached the
    echoed path, and Play could not load a single frame of a run it had
    just drawn correctly).  The mapping is applied whatever the platform,
    because on a Linux desktop ``wsl()`` is the identity and a test that
    can only fail on one machine is not a test."""
    p = multiboot_tab.wsl(path)
    return p if p != path else "/mnt/wsl" + p.replace("\\", "/")


def _stand_ins(monkeypatch, tmp_path, fail=None, frames=3):
    """Python children for the three preview steps.  The snapshot one
    writes a small PPM where the real selector would and prints its
    'anim: image N F frames' line; *fail* names the step that exits 2.

    IT SPEAKS THE REAL CLI, ``--frames K`` included: one run fills the
    frame number into the pattern it is given, wraps at the animation's
    length (*frames*), trims K to it, and prints the selector's own
    'snapshot: <path> WxH … frame F of N' line per file - which is how the
    tab learns which frames a run actually wrote.  It writes to the HOST
    path and prints the TOOL's (see :func:`_tool_path`), which is what the
    real thing does and the only way the tab's own path handling is
    exercised at all."""
    py = sys.executable
    seen = {"snapshot": []}
    length = frames

    def ensure(form, cwd=None):
        code = ("print('[preview] selector: /fake/codeselect')"
                if fail != "selector" else
                "print('[preview] error: no selector'); raise SystemExit(2)")
        return [("selector", [py, "-c", code])]

    def prepare(form, media_dir, cwd=None):
        seen["media"] = media_dir
        seen.setdefault("media_dirs", []).append(media_dir)
        # ...and it leaves a mark in the directory it rendered into, so a
        # test can tell WHERE the media landed and not only that it ran.
        code = ("import os, sys; "
                "open(os.path.join(sys.argv[1], 'prepared'), 'w').close(); "
                "print('prepare: cached art1.png')"
                if fail != "prepare" else
                "print('[media] error: ffmpeg missing'); raise SystemExit(2)")
        return [("prepare", [py, "-c", code, media_dir])]

    def snapshot(binary, conf, media_dir, ppm, hl, n, rootfs="~/r", cwd=None,
                 frames=1):
        seen["snapshot"].append((binary, conf, media_dir, ppm, hl, n, frames))
        label = (multiboot_tab.ANIM_LABEL if frames > 1 else "frame %d" % n)
        if fail == "frame":
            code = "print('[select] error: bad conf'); raise SystemExit(2)"
            return [(label, [py, "-c", code])]
        code = (
            "import sys\n"
            "pat, wpat, hl, first, want, total = (sys.argv[1], sys.argv[2], "
            "int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), "
            "int(sys.argv[6]))\n"
            "print('anim: image %d %d frames 200x112' % (hl, total))\n"
            "for k in range(min(want, total or 1)):\n"
            "    f = (first + k) % total if total else 0\n"
            "    p = pat % f if '%d' in pat else pat\n"
            "    w = wpat % f if '%d' in wpat else wpat\n"
            "    open(p, 'wb').write(b'P6\\n136 77\\n255\\n' + "
            "bytes([40, 60, 90]) * (136 * 77))\n"
            "    print('[select] snapshot: %s 136x77, highlight %d (T) from "
            "--highlight, frame %d of %d, timeout 15 s, invert 0, font f, "
            "media m, footer \"x\"' % (w, hl, f, total))\n")
        return [(label, [py, "-c", code, ppm, _tool_path(ppm), str(hl),
                         str(n), str(frames), str(length)])]
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
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        out = panel._out_var.get()
        pv = multiboot_tab.preview_dir_for(out)
        media = multiboot_tab.media_dir_for(out)
        assert os.path.normpath(seen["media"]) == os.path.normpath(media)
        with open(os.path.join(pv, "images.conf"), "rb") as f:
            conf = f.read()
        assert b"image=p7|TMNT 1987|1987-upscaled|art1.png|anim1.gif|" in conf
        assert b"\r" not in conf
        fp = preview_fingerprint(panel.form())
        frame0 = multiboot_tab.frame_path(pv, fp, 1, 0)
        # ONE frame is asked for as one frame: the --snapshot value is a
        # file NAME and no --frames rides along (K == 1 is the selector's
        # own byte-for-byte single-frame path).
        assert seen["snapshot"] == [(
            "/fake/codeselect", os.path.join(pv, "images.conf"), media,
            frame0, 1, 0, 1)]
        assert os.path.isfile(frame0)
        assert panel._pv_status.cget("text") == "Image 2: frame 0 of 3"
        assert panel._pv_photo is not None
        assert panel._pv_cache == {(fp, 1, 0): frame0}
        assert panel._pv_totals == {(fp, 1): 3}
        assert panel._pv_bin == "/fake/codeselect"
        # ...and the third field is WHICH HALF was prepared: the preview
        # renders --visual-only while Sound is off, and a set with no
        # move or confirm sound in it is not a prepared set for a ticked
        # Sound box.
        assert panel._pv_ready == (media_fingerprint(panel.form()),
                                   media, False)
        pane = _pane(panel)
        assert "selector: exit 0" in pane and "frame 0: exit 0" in pane
        # the same form again, another frame: straight to the snapshot
        panel._frame_var.set("2")
        calls = []
        real = panel._run_commands
        panel._run_commands = lambda cmds, **kw: calls.append(
            [label for label, _ in cmds]) or real(cmds, **kw)
        assert panel.render_preview() is True
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        assert calls == [["frame 2"]]
        assert (fp, 1, 2) in panel._pv_cache
        assert panel._pv_status.cget("text") == "Image 2: frame 2 of 3"
        # a spinbox move to a cached frame shows it without a render
        panel._frame_var.set("0")
        assert panel._pv_shown == (1, 0)
    finally:
        root.destroy()


def test_a_text_change_costs_one_snapshot_and_a_media_change_a_prepare(
        tmp_path, monkeypatch):
    """The whole point of the preview following the form: retyping a title
    rewrites the conf and takes ONE snapshot, and only art / animation /
    music / the sounds make selectmedia run again."""
    root, panel = _panel()
    _stand_ins(monkeypatch, tmp_path, frames=3)
    calls = []
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        real = panel._run_commands
        panel._run_commands = lambda cmds, **kw: calls.append(
            [label for label, _ in cmds]) or real(cmds, **kw)
        assert panel.render_preview() is True
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        assert calls == [["selector", "prepare", "frame 0"]]
        # TEXT: no selector (built), no prepare (the media did not move)
        panel._rows[1].subtitle = "1987 cartoon upscale"
        panel._rows[0].title = "STERN 1.59.0"
        assert panel.render_preview() is True
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        assert calls[-1] == ["frame 0"]
        panel._timeout_var.set("8")
        assert panel.render_preview() is True
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        assert calls[-1] == ["frame 0"]
        # MEDIA: the prepare comes back, and once only
        panel._rows[1].anim = "auto"
        assert panel.render_preview() is True
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        assert calls[-1] == ["prepare", "frame 0"]
        panel._frame_var.set("1")
        assert panel.render_preview() is True
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        assert calls[-1] == ["frame 1"]
        # ...and a failed step forgets the prepared media, so the next
        # render prepares again
        panel._pv_ready = None
        panel._frame_var.set("2")
        assert panel.render_preview() is True
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        assert calls[-1] == ["prepare", "frame 2"]
    finally:
        root.destroy()


def test_a_reverted_form_gets_its_own_picture_back(tmp_path, monkeypatch):
    """CHANGE A TITLE, RENDER, CHANGE IT BACK.  The cache is keyed by the
    form, so the reverted form has no entry and a render is queued - and
    while every snapshot wrote to ``frame_<hl>_<n>.ppm`` that render wrote
    over (or was shown) the newer form's picture.  Two forms, two files."""
    root, panel = _panel()
    seen = _stand_ins(monkeypatch, tmp_path, frames=1)
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        panel._tree.selection_set("0")
        root.update()                       # let the selection settle first
        panel._rows[1].title = "one"
        assert panel.render_preview() is True
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        fp_a = preview_fingerprint(panel.form())
        ppm_a = seen["snapshot"][-1][3]
        assert panel._pv_cache[(fp_a, 0, 0)] == ppm_a
        assert os.path.isfile(ppm_a)

        panel._rows[1].title = "two"
        assert panel.render_preview() is True
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        fp_b = preview_fingerprint(panel.form())
        ppm_b = seen["snapshot"][-1][3]
        assert fp_b != fp_a and ppm_b != ppm_a       # the whole point
        # the first form's frame is still there: it is the one on screen
        assert os.path.isfile(ppm_a)

        panel._rows[1].title = "one"
        assert panel.render_preview() is True
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        assert seen["snapshot"][-1][3] == ppm_a
        assert panel._pv_src[0] == ppm_a

        # ...and preview/ does not grow without bound: a frame no form can
        # ask for again, and that is not on screen, goes
        panel._pv_src = None
        panel._rows[1].title = "two"
        panel._frame_var.set("0")
        assert panel.render_preview() is True
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        assert not os.path.isfile(ppm_a)
        assert (fp_a, 0, 0) not in panel._pv_cache
    finally:
        root.destroy()


def test_a_retired_forms_animation_leaves_the_cache_with_its_files(
        tmp_path, monkeypatch):
    """The eviction sweep matches a cache VALUE against the file it just
    deleted, so a run that cached the path the selector echoed - the WSL
    form of it, on Windows - could never match, and up to thirty dead
    entries per (retired form, image) piled up for the life of the tab
    while their files went.  One fault, two symptoms: the cache holds the
    names this process uses, so the sweep finds them."""
    root, panel = _panel()
    _stand_ins(monkeypatch, tmp_path, frames=4)
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        panel._rows[1].anim = "auto"
        panel._rows[1].title = "one"
        panel._default_var.set("1")
        panel._play_var.set(True)
        panel._play_toggled()
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        panel._play_var.set(False)
        panel._play_toggled()
        fp_a = preview_fingerprint(panel.form())
        pv = multiboot_tab.preview_dir_for(panel._out_var.get())
        gone = [multiboot_tab.frame_path(pv, fp_a, 1, n) for n in range(4)]
        assert sorted(panel._pv_cache) == [(fp_a, 1, n) for n in range(4)]
        assert all(os.path.isfile(p) for p in gone)
        # ...another form, and nothing of this one is on screen to spare
        panel._pv_src = None
        panel._rows[1].title = "two"
        assert panel.render_preview() is True
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        assert not any(os.path.isfile(p) for p in gone)
        assert not any(key[0] == fp_a for key in panel._pv_cache)
    finally:
        root.destroy()


def test_a_reverted_title_is_redrawn_and_not_left_on_the_other_form(
        tmp_path, monkeypatch):
    """THE SAME REVERT, TYPED, DOWN THE AUTO PATH - where the cache is
    allowed to answer.

    The cache key carries the fingerprint but ``_pv_shown`` carried only
    (highlight, frame), so the reverted form's own frame - still cached,
    because the prune spares the file that is on screen - was a hit that
    redrew nothing, and the canvas went on showing the OTHER title's
    picture under the reverted row.  A cache hit has to be checked against
    the FILE the canvas was drawn from."""
    root, panel = _panel(auto=True)
    _stand_ins(monkeypatch, tmp_path, frames=1)
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        panel._tree.selection_set("0")
        root.update()
        _wait(root, lambda: not (panel._busy or panel._pv_busy))

        def typed(title):
            """Type a title into the editor and let the debounce render."""
            panel._ed_title.set(title)
            root.update()
            _fire_debounce(root, panel)
            _wait(root, lambda: not (panel._busy or panel._pv_busy))
            return panel._pv_src[0]

        ppm_a = typed("AAA")
        photo_a = panel._pv_photo
        ppm_b = typed("BBB")
        assert ppm_b != ppm_a and panel._pv_photo is not photo_a
        assert os.path.isfile(ppm_a)        # spared: it was the one shown
        assert typed("AAA") == ppm_a        # ...and it comes back
        assert panel._pv_photo is not None
    finally:
        root.destroy()


def test_a_changed_output_path_prepares_the_media_again(tmp_path,
                                                        monkeypatch):
    """THE MEDIA DIRECTORY COMES OFF THE OUTPUT PATH, and the 'is it
    prepared' answer has to know that.  media_fingerprint leaves the output
    out on purpose (retyping it does not change what the media IS) - so
    keying on it alone left the prepared media in the OLD directory, the
    new one empty, and Build & verify wrote a text-only card."""
    root, panel = _panel()
    seen = _stand_ins(monkeypatch, tmp_path, frames=1)
    prepares = []
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        real = panel._run_commands
        panel._run_commands = lambda cmds, **kw: prepares.append(
            [label for label, _ in cmds]) or real(cmds, **kw)
        panel._out_var.set(str(tmp_path / "one" / "card.multi.raw"))
        assert panel.render_preview() is True
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        first = seen["media"]
        assert "prepare" in prepares[-1]
        assert panel._pv_ready == (media_fingerprint(panel.form()),
                                   first, False)
        # the same form, a different output: the media has not changed, but
        # the DIRECTORY it has to be in has
        panel._out_var.set(str(tmp_path / "two" / "card.multi.raw"))
        assert panel.render_preview() is True
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        assert os.path.normpath(seen["media"]) != os.path.normpath(first)
        assert "prepare" in prepares[-1], prepares[-1]
        assert os.path.isfile(os.path.join(seen["media"], "prepared"))
    finally:
        root.destroy()


def test_a_half_typed_output_path_leaves_nothing_behind(tmp_path):
    """Typing D:/x/mul on the way to D:/x/multi used to leave a preview/
    and a media/ under every prefix that happened to render.  Only the
    directories the preview MADE come back, only its own files go, and a
    directory with anything else in it is left alone."""
    root, panel = _panel()
    try:
        one, two = tmp_path / "mul", tmp_path / "multi"
        pv1, media1 = str(one / "preview"), str(one / "media")
        panel._makedirs(pv1)
        panel._makedirs(media1)
        open(os.path.join(pv1, "images.conf"), "w").close()
        open(os.path.join(pv1, "frame_abc123_0_0.ppm"), "w").close()
        assert os.path.isdir(pv1) and os.path.isdir(media1)
        # the output moved: the old pair goes, and so does the folder we
        # made to hold them
        pv2, media2 = str(two / "preview"), str(two / "media")
        panel._makedirs(pv2)
        panel._makedirs(media2)
        panel._forget_old_dirs(pv2, media2)
        assert not os.path.exists(pv1) and not os.path.exists(media1)
        assert os.path.isdir(pv2) and os.path.isdir(media2)
        # ...but a directory with something of the user's in it stays
        pv3 = str(tmp_path / "keep" / "preview")
        panel._makedirs(pv3)
        open(os.path.join(pv3, "notes.txt"), "w").close()
        panel._forget_old_dirs(pv2, media2)
        assert os.path.isfile(os.path.join(pv3, "notes.txt"))
        # ...and a directory that was already there is never ours to remove
        theirs = tmp_path / "theirs"
        theirs.mkdir()
        panel._makedirs(str(theirs))
        panel._forget_old_dirs(pv2, media2)
        assert os.path.isdir(str(theirs))
    finally:
        root.destroy()


def test_a_stepper_on_a_frame_that_is_not_drawn_yet_says_so(tmp_path):
    """The Image / Frame steppers used to do NOTHING on a cache miss, and
    the caption went on describing the frame still on screen."""
    root, panel = _panel()
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        panel._out_var.set(str(tmp_path / "out" / "card.multi.raw"))
        panel._auto_preview.set(False)
        panel._frame_var.set("4")
        assert "not been drawn yet" in panel._pv_status.cget("text")
        assert "right-click" in panel._pv_status.cget("text")
        panel._auto_preview.set(True)
        panel._frame_var.set("5")
        assert "drawing it" in panel._pv_status.cget("text")
        assert panel._pv_debounce_job is not None
    finally:
        root.destroy()


def test_a_settled_invalid_form_says_the_preview_is_out_of_date(tmp_path):
    """Right while a field is half typed, wrong once it settles: the
    debounce has already waited for the typing to stop, so a preview that
    quietly stops following the form from then on is the worst of both."""
    root, panel = _panel(auto=True)
    started = []
    panel._render_frames = lambda *a: started.append(a) or True
    try:
        a, b = _images(tmp_path, 2)
        panel.add_image(a)
        root.update()                   # the row selection, before the debounce
        _fire_debounce(root, panel)
        assert started == []
        # ONE image is not a card, and the tab now says which line to read
        assert "Preview not updated" in panel._pv_status.cget("text")
        assert "at least two images" in panel._pv_status.cget("text")
        panel.add_image(b)
        _fire_debounce(root, panel)
        assert started                       # ...and it draws once it can
    finally:
        root.destroy()


def test_the_preview_debounce_coalesces_a_burst_into_one_render(tmp_path):
    """Typing a title fires the trace per keystroke; ~350 ms after the last
    one, ONE render happens."""
    root, panel = _panel()
    asked = []
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        panel._render_frames = lambda form, hl, frames: asked.append(
            (hl, list(frames))) or True
        panel._auto_preview.set(True)
        panel._tree.selection_set("1")
        root.update()
        for text in ("T", "TM", "TMN", "TMNT", "TMNT 1987"):
            panel._ed_title.set(text)
        # one job, however many keystrokes
        assert panel._pv_debounce_job is not None
        assert panel._pv_pending >= 5
        assert asked == []
        _fire_debounce(root, panel)
        assert asked == [(1, [0])]
        assert panel._pv_debounce_job is None
        assert panel._pv_pending == 0
        # ...and a cached frame is shown without a render at all
        asked[:] = []
        panel._ed_sub.set("1987 cartoon upscale")
        fp = preview_fingerprint(panel.form())
        panel._pv_cache[(fp, 1, 0)] = _ppm(tmp_path / "cached.ppm")
        panel._pv_totals[(fp, 1)] = 1
        panel._pv_shown = None
        _fire_debounce(root, panel)
        assert asked == []
        assert panel._pv_shown == (1, 0)
        # every field asks: the menu ones too
        panel._timeout_var.set("8")
        assert panel._pv_debounce_job is not None
        _fire_debounce(root, panel)
        assert asked == [(1, [0])]
        # switched off, nothing is scheduled at all
        asked[:] = []
        panel._auto_preview.set(False)
        panel._ed_title.set("TMNT")
        assert panel._pv_debounce_job is None
        assert asked == []
        # ...and a half-typed output path draws nothing: a render writes
        # <out dir>/preview, and typing must not leave folders behind it
        panel._auto_preview.set(True)
        panel._out_var.set(str(tmp_path / "a" / "b" / "c" / "card"))
        _fire_debounce(root, panel)
        assert asked == []
        assert not os.path.isdir(str(tmp_path / "a"))
        panel._out_var.set(str(tmp_path / "out" / "card.multi.raw"))
        _fire_debounce(root, panel)
        assert asked == [(1, [0])]
    finally:
        root.destroy()


def test_selecting_a_row_moves_the_preview_highlight(tmp_path):
    root, panel = _panel()
    try:
        for p in _images(tmp_path, 3):
            panel.add_image(p)
        panel._tree.selection_set("2")
        root.update()
        assert panel._hl_var.get() == "2"
        assert panel._hl_touched is False     # programmatic, not typed
        panel._tree.selection_set("0")
        root.update()
        assert panel._hl_var.get() == "0"
        # ...and the line under the list follows it
        assert panel._rows[0].path in panel._row_tip.text
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
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        status = panel._pv_status.cget("text")
        label = "frame 0" if fail == "frame" else fail
        assert "Preview failed at %s (exit 2)" % label in status
        pane = _pane(panel)
        assert "error:" in pane and "%s: exit 2" % label in pane
        assert "[preview] Preview failed" in pane
        assert panel._pv_cache == {}
        assert panel._play_var.get() is False          # Play stops on error
        assert panel._pv_ready is None
        # ...and the tab was never greyed for it: a preview is a background
        # redraw, not a run that writes something.
        assert panel._busy is False and panel._pv_busy is False
        assert str(panel._build_btn.cget("state")) == "normal"
    finally:
        root.destroy()


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
    assert pat % 7 == multiboot_tab.frame_path("/x/preview", "abc123", 1, 7)
    one = preview_snapshot_args("/bin/cs", "/x/c.conf", "/x/media",
                                "/x/f.ppm", 1, 3)
    assert "--frames" not in one
    run = preview_snapshot_args("/bin/cs", "/x/c.conf", "/x/media", pat, 1, 3,
                                frames=16)
    assert run[run.index("--frames") + 1] == "16"
    assert run[run.index("--anim-frame") + 1] == "3"       # where it starts
    assert run[run.index("--snapshot") + 1] == multiboot_tab.wsl(pat)
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
    assert pat % 7 == multiboot_tab.frame_path(
        "D:/Pinball/100% builds/preview", "abc123", 1, 7)
    # a literal '%d' in the folder is escaped the same way and stops being
    # a second conversion
    odd = frame_pattern("/x/100%d builds/preview", "ab", 0)
    assert odd.replace("%%", "").count("%") == 1
    assert odd % 3 == multiboot_tab.frame_path("/x/100%d builds/preview",
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


def test_play_draws_the_whole_animation_in_one_run(tmp_path, monkeypatch):
    """THE POINT OF THE WHOLE THING: pressing Play used to start one qemu
    run per frame, each reloading every PNG, GIF and font.  Now it is ONE
    run - the most frames an animation can have, trimmed by the selector to
    what this image really has - and the ticks after it render nothing."""
    root, panel = _panel()
    seen = _stand_ins(monkeypatch, tmp_path, frames=4)
    calls = []
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        panel._rows[1].anim = "auto"
        panel._default_var.set("1")
        real = panel._run_commands
        panel._run_commands = lambda cmds, **kw: calls.append(
            [label for label, _ in cmds]) or real(cmds, **kw)
        panel._play_var.set(True)
        panel._play_toggled()
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        assert calls == [["selector", "prepare", ANIM_LABEL]]
        # one snapshot call, a PATTERN, and the whole ceiling asked for
        assert len(seen["snapshot"]) == 1
        assert seen["snapshot"][0][6] == PREVIEW_MAX_FRAMES
        assert seen["snapshot"][0][3].endswith("_%d.ppm")
        fp = preview_fingerprint(panel.form())
        pv = multiboot_tab.preview_dir_for(panel._out_var.get())
        assert panel._pv_totals == {(fp, 1): 4}
        assert sorted(panel._pv_cache) == [(fp, 1, n) for n in range(4)]
        # EVERY CACHED PATH IS ONE THIS PROCESS CAN OPEN.  The selector is
        # handed - and so echoes back - the WSL form of the pattern (see
        # _tool_path), and caching what it echoed left every frame of Play
        # pointing at a /mnt/c/… name Image.open cannot read: the picture
        # froze on frame 0 and the strip repainted 'Cannot load …' at the
        # clip's rate for as long as Play stayed ticked.
        for n in range(4):
            path = multiboot_tab.frame_path(pv, fp, 1, n)
            assert panel._pv_cache[(fp, 1, n)] == path
            assert os.path.isfile(path)
        # ...and the ticks walk it, wrapping, without asking for any more
        first = int(panel._frame_var.get())
        for k in range(1, 6):
            _tick(root, panel)
            assert panel._frame_var.get() == str((first + k) % 4)
        assert calls == [["selector", "prepare", ANIM_LABEL]]
        # stopping leaves the picture on a real frame, and the caption says
        # which one rather than going on claiming to be playing
        stopped = int(panel._frame_var.get())
        panel._play_var.set(False)
        panel._play_toggled()
        assert panel._pv_shown == (1, stopped)
        assert panel._pv_status.cget("text") == \
            "Image 2: frame %d of 4" % stopped
        # ...and the SAME names reach the photo cache, so a frame the
        # selector has just written again is decoded again rather than
        # drawn from the pixels it had before the run
        shown = multiboot_tab.frame_path(pv, fp, 1, stopped)
        assert os.path.abspath(shown) in panel._pv_photos
        assert panel._render_frames(panel.form(), 1, list(range(4))) is True
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        assert os.path.abspath(shown) not in panel._pv_photos
    finally:
        root.destroy()


def test_playback_decodes_each_frame_once_and_a_resize_drops_them(
        tmp_path, monkeypatch):
    """Playback must not touch the disk: a frame is read and scaled ONCE
    and kept, so the second pass of an animation is pure memory.  A box
    that changed size drops them all - they are scaled to the old one."""
    root, panel = _panel()
    reads = []
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        frames = [_ppm(tmp_path / ("f%d.ppm" % n)) for n in range(3)]
        real_decode = panel._decode_photo

        def counted(path):
            reads.append(path)
            return real_decode(path)
        panel._decode_photo = counted
        for _pass in range(2):
            for n, path in enumerate(frames):
                assert panel.load_frame(path, 1, n, 3) is True
        assert sorted(reads) == sorted(frames)          # once each, not twice
        # the window changed size: what is in memory is the wrong size now
        panel._pv_w, panel._pv_h = panel._pv_w // 2, panel._pv_h // 2
        panel._drop_photos()
        assert panel.load_frame(frames[0], 1, 0, 3) is True
        assert reads.count(frames[0]) == 2
        # ...and the cache is bounded: an animation's worth, not a card's
        for n in range(multiboot_tab.PHOTO_CACHE_MAX + 5):
            panel._keep_photo(str(tmp_path / ("x%d.ppm" % n)), object())
        assert len(panel._pv_photos) == multiboot_tab.PHOTO_CACHE_MAX
        assert len(panel._pv_photo_order) == multiboot_tab.PHOTO_CACHE_MAX
    finally:
        root.destroy()


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


def test_an_animation_plays_at_the_rate_it_was_rendered_at(tmp_path):
    """THE ROW'S FPS FIELD IS A REQUEST, not the rate.  selectmedia clamps
    it (gif_first_plan drops the frame rate to fit 30 frames) and shrinks
    it again down gif_ladder to fit the byte budget, so a row asking 25 fps
    is normally a 10 fps clip - and playing that at 40 ms ran the preview
    two and a half times too fast against a machine that ticks on the GIF's
    own delay.  The GIF settles it; the run's frame count over the clip's
    length is the fallback; the field itself is only a first guess."""
    # the rendered clip's own delay wins outright
    assert anim_period_ms(ImageRow("", anim="auto", anim_fps="25"),
                          frames=30, delay_ms=100) == 100
    # ...and without one, the frames the selector really wrote over the
    # length that was asked for: 25 fps for 3 s is 30 frames at 10 fps
    assert anim_period_ms(ImageRow("", anim="auto", anim_fps="25"),
                          frames=30) == 100
    # the ordinary case - only the Length box touched, FPS left blank
    assert anim_period_ms(ImageRow("", anim="auto", anim_seconds="5"),
                          frames=30) == 167
    assert anim_period_ms(ImageRow("", anim="auto", anim_seconds="6"),
                          frames=30) == 200
    # ...and the ladder's first rung, 8 fps over the default 3 s
    assert anim_period_ms(ImageRow("", anim="auto"), frames=24) == 125
    # nothing rendered yet: the field, clamped, because it is typed
    assert anim_period_ms(ImageRow("", anim="auto")) == 100        # 10 fps
    assert anim_period_ms(ImageRow("", anim="auto", anim_fps="25")) == 40
    assert anim_period_ms(ImageRow("", anim="auto", anim_fps="nonsense")) \
        == 100
    assert anim_period_ms(ImageRow("", anim="auto", anim_fps="0")) == 100
    assert anim_period_ms(ImageRow("", anim="auto", anim_fps="9000")) == 16
    assert anim_period_ms(ImageRow("", anim="auto", anim_fps="0.1")) == 2000
    # a one-frame 'run' says nothing about the rate, and neither does a
    # length of zero
    assert anim_period_ms(ImageRow("", anim="auto", anim_fps="25"),
                          frames=1) == 40
    assert anim_period_ms(ImageRow("", anim="auto", anim_fps="25",
                                   anim_seconds="0"), frames=30) == 40


def test_the_rendered_gif_is_what_the_preview_reads_its_rate_from(tmp_path):
    """codeselect.c ticks on ``a->delay_ms[frame]``, so the file carrying
    those delays is the only honest source for how fast Play should run -
    and it is on disk in the media directory the preview prepared."""
    assert multiboot_tab.gif_period_ms(str(tmp_path / "nothing.gif")) is None
    assert multiboot_tab.gif_period_ms(_ppm(tmp_path / "not.gif")) is None
    assert multiboot_tab.gif_period_ms(_gif(tmp_path / "a.gif",
                                            delay_ms=100)) == 100
    assert multiboot_tab.gif_period_ms(_gif(tmp_path / "b.gif", frames=30,
                                            delay_ms=170)) == 170
    root, panel = _panel()
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        panel._rows[1].anim = "auto"
        panel._rows[1].anim_fps = "25"          # the request, not the rate
        media = panel.media_dir()
        os.makedirs(media, exist_ok=True)
        # image 1's clip really was rendered at 10 fps, and the preview
        # reads that off the file the selector loads (anim<N>.gif, the name
        # write_preview_conf puts in the conf)
        _gif(os.path.join(media, "anim1.gif"), frames=30, delay_ms=100)
        assert panel._play_ms(1) == 100
        # nothing rendered for image 0, so its own field is all there is
        assert panel._play_ms(0) == 100
        assert panel._play_ms(9) == panel.PLAY_MS       # no such row
        # ...and a re-rendered clip at a new rate is picked up, because the
        # answer is kept against the file's own stat and not for the session
        _gif(os.path.join(media, "anim1.gif"), frames=12, delay_ms=250)
        assert panel._play_ms(1) == 250
    finally:
        root.destroy()


# --------------------------------------------------------------------------
# the preview's sound
# --------------------------------------------------------------------------

def test_the_menus_sounds_come_off_the_manifest(tmp_path):
    """WHICH WAV the menu plays is media.json's answer, not the form's: the
    form holds specs ('auto', 'synth', a path here), and what the selector
    opens is what the tools rendered from them.  An image plays its OWN
    confirm sound when it has one and the menu's otherwise, which is
    codeselect.c's own fallback."""
    manifest = {"images": [{"art": "art0.png", "music": None,
                            "confirm": None},
                           {"art": "art1.png", "music": "music1.wav",
                            "confirm": "confirm1.wav"}],
                "sound_move": "move.wav", "sound_confirm": "confirm.wav"}
    d = str(tmp_path / "media")
    assert manifest_sounds(manifest, d, 0) == {
        "music": "", "move": os.path.join(d, "move.wav"),
        "confirm": os.path.join(d, "confirm.wav")}
    assert manifest_sounds(manifest, d, 1) == {
        "music": os.path.join(d, "music1.wav"),
        "move": os.path.join(d, "move.wav"),
        "confirm": os.path.join(d, "confirm1.wav")}
    # a highlight past the end, and a media set with nothing prepared
    assert manifest_sounds(manifest, d, 7)["music"] == ""
    assert manifest_sounds({}, d, 0) == {"music": "", "move": "",
                                         "confirm": ""}
    # THE FORM SAYS WHETHER AN IMAGE HAS MUSIC, the manifest which file: a
    # row set to 'none' since the last prepare must not play the bed still
    # sitting in the directory.
    root, panel = _panel()
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        media = _media_set(panel)
        assert panel.menu_sounds(1)["music"] == os.path.join(media,
                                                             "music1.wav")
        panel._rows[1].music = "none"
        assert panel.menu_sounds(1)["music"] == ""
        assert panel.menu_sounds(1)["move"] == os.path.join(media,
                                                            "move.wav")
    finally:
        root.destroy()
    # ...and a directory with no manifest in it is not an error
    assert multiboot_tab.read_manifest(str(tmp_path / "nope")) == {}
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "media.json"), "w").write("{not json")
    assert multiboot_tab.read_manifest(d) == {}


def test_the_preview_starts_silent_and_says_what_is_going_unheard(
        tmp_path, monkeypatch):
    """DEFAULT OFF, and said once.  This app is used beside a machine that
    is running, so nothing here opens a sound device until the box is
    ticked - and a feature nobody can find is not a feature, so the caption
    says once that the highlighted image has music."""
    made = _fake_audio(monkeypatch)
    root, panel = _panel()
    try:
        assert panel._sound_var.get() is False
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        media = _media_set(panel)
        assert made == [] and panel._audio is None      # nothing opened
        ppm = _ppm(tmp_path / "f.ppm")
        panel._set_var(panel._hl_var, 1)
        assert panel.load_frame(ppm, 1, 0, 1) is True
        text = panel._pv_status.cget("text")
        assert text.startswith("Image 2: a still")
        assert "tick Sound" in text
        assert "[preview] This image has music" in _pane(panel)
        # ...once: the second frame says the frame and nothing else
        assert panel.load_frame(ppm, 1, 0, 1) is True
        assert panel._pv_status.cget("text") == "Image 2: a still (no " \
            "animation on this image)"
        # ONE CLICK, and it plays what the menu plays
        panel._sound_var.set(True)
        panel._sound_toggled()
        assert len(made) == 1
        assert made[0].looping == os.path.join(media, "music1.wav")
        assert made[0].volume == 50
        # ...and unticking it gives the device back
        panel._sound_var.set(False)
        panel._sound_toggled()
        assert made[0].calls[-1] == ("stop", None)
    finally:
        root.destroy()


def test_a_flipper_press_plays_the_move_sound_over_the_music(tmp_path,
                                                             monkeypatch):
    """What the machine does on every EV_LEFT / EV_RIGHT: the move sound
    fires, and the newly highlighted card's music takes over."""
    made = _fake_audio(monkeypatch)
    root, panel = _panel()
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        media = _media_set(panel)
        panel._sound_var.set(True)
        panel._sound_toggled()
        audio = made[0]
        assert audio.looping == os.path.join(media, "music0.wav")
        audio.calls[:] = []
        assert panel.flip_right() is True
        assert audio.played("play") == [os.path.join(media, "move.wav")]
        assert audio.looping == os.path.join(media, "music1.wav")
        # the volume knob is the menu's own
        panel._volume_var.set("20")
        assert audio.volume == 20
        # ...and a media set the PREVIEW prepared has no move sound in it,
        # which is said rather than swallowed
        _media_set(panel, sounds=False)
        panel.load_frame(_ppm(tmp_path / "f.ppm"), 1, 0, 1)
        audio.calls[:] = []
        assert panel.flip_left() is True         # the highlight still moves
        assert audio.played("play") == []
        # It NAMES NO CONTROL: the entry it used to send people to is gone,
        # and what replaced it is the Sound tick that has already been
        # pressed by anyone who can read this line.
        assert "No move sound in this" in panel._pv_status.cget("text")
        # ...and wherever the strip had to cut it, the whole of it is still
        # reachable: the label's tooltip carries it, and so does the Log.
        assert "no move sound" in (panel._pv_status_tip.text
                                   or panel._pv_status.cget("text")).lower()
        assert "No move sound in this media set." in _pane(panel)
    finally:
        root.destroy()


def test_the_confirm_sound_can_be_heard_before_a_card_is_written(
        tmp_path, monkeypatch):
    """The one sound with no other way of being heard: it plays when THAT
    image is chosen, and nothing else in the tab ever chooses one.  It
    plays whether or not Sound is ticked - picking it IS the asking - and
    it starts no music."""
    made = _fake_audio(monkeypatch)
    root, panel = _panel()
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        media = _media_set(panel, own_confirm="confirm1.wav")
        panel._set_var(panel._hl_var, 1)
        # it is on the picture's own menu, at the index the popup greys
        assert panel._pv_menu.entrycget(panel.PV_MENU_CONFIRM, "label") == \
            "Play this image's confirm sound"
        assert panel.play_confirm() is True
        assert made[0].played("play") == [os.path.join(media,
                                                       "confirm1.wav")]
        assert made[0].played("loop") == []             # no music started
        assert "confirm1.wav" in panel._pv_status.cget("text")
        # image 0 has none of its own, so it is the menu's
        panel._set_var(panel._hl_var, 0)
        assert panel.play_confirm() is True
        assert made[0].played("play")[-1] == os.path.join(media,
                                                          "confirm.wav")
        # ...and with nothing prepared it says so instead of playing
        _media_set(panel, sounds=False)
        assert panel.play_confirm() is False
        assert "no confirm sound" in panel._pv_status.cget("text")
    finally:
        root.destroy()


def test_the_confirm_sound_is_judged_without_the_music_under_it(
        tmp_path, monkeypatch):
    """codeselect.c stops music_voice and THEN plays the confirm, alone,
    under the LOADING frame - so a confirm auditioned over the bed is
    auditioned at a loudness the machine will never produce."""
    made = _fake_audio(monkeypatch)
    root, panel = _panel()
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        media = _media_set(panel, own_confirm="confirm1.wav")
        panel._set_var(panel._hl_var, 1)
        panel._sound_var.set(True)
        panel._sound_toggled()
        audio = made[0]
        assert audio.looping == os.path.join(media, "music1.wav")
        audio.calls[:] = []
        assert panel.play_confirm() is True
        # the machine's order, and nothing left playing under it
        assert [k for k, _ in audio.calls] == ["volume", "loop", "play"]
        assert audio.looping is None
        assert audio.played("play") == [os.path.join(media, "confirm1.wav")]
        # ...said, so the silence that follows is not a mystery
        assert "music stops for it" in panel._pv_status.cget("text")
        # and the next flipper press brings the bed back
        assert panel.flip_left() is True
        assert audio.looping == os.path.join(media, "music0.wav")
    finally:
        root.destroy()


def test_a_machine_with_no_sound_says_so_once_and_goes_on_drawing(
        tmp_path, monkeypatch):
    """The hard rule of the whole feature: a preview that cannot make a
    sound still draws its picture, and says why in words."""
    made = _fake_audio(monkeypatch)
    root, panel = _panel()
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        _media_set(panel)
        panel._sound_var.set(True)
        panel._sound_toggled()
        audio = made[0]
        audio.available = False
        audio.why_silent = ("No sound: sounddevice is not installed, and "
                            "winsound is a Windows module and this is "
                            "darwin.")
        audio.status = audio.why_silent
        panel._sound_poll()
        assert "sounddevice is not installed" in panel._pv_status.cget("text")
        assert "[preview] No sound:" in _pane(panel)
        # the picture still draws, and says it once
        assert panel.load_frame(_ppm(tmp_path / "f.ppm"), 1, 0, 1) is True
        assert panel._pv_status.cget("text") == "Image 2: a still (no " \
            "animation on this image)"
    finally:
        root.destroy()


def test_a_confirm_the_form_has_turned_off_is_not_offered_or_played(
        tmp_path, monkeypatch):
    """THE FORM SAYS WHETHER AN IMAGE HAS A SOUND; the manifest only says
    which file.  An image whose Confirm is 'the menu's sound' plays the
    MENU's confirm - so with that set to 'none' the machine plays nothing
    at all on confirm, whatever confirm<N>.wav an earlier prepare left in
    the directory.  Offering it, and playing it, described a card nobody
    was going to build."""
    made = _fake_audio(monkeypatch)
    root, panel = _panel()
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        media = _media_set(panel, own_confirm="confirm1.wav")
        # a full prepare, and image 1 with a confirm of its own: offered
        assert panel.menu_sounds(1)["confirm"] == os.path.join(
            media, "confirm1.wav")
        # the row goes back to the menu's sound, and the menu keeps one
        panel._rows[1].confirm = "menu"
        assert panel.menu_sounds(1)["confirm"] == os.path.join(
            media, "confirm.wav")
        # ...and now the menu has none either: there is nothing to play
        panel._confirm_var.set("none")
        assert panel.menu_sounds(1)["confirm"] == ""
        panel._set_var(panel._hl_var, 1)
        assert panel.play_confirm() is False
        assert made == []                       # no device opened for it
        assert "no confirm sound" in panel._pv_status.cget("text")
        # the right-click entry greys with it, the way it does for a media
        # set with nothing prepared (asked through the popup's own seam:
        # tk_popup itself takes a grab and never returns in a test)
        assert panel.sync_preview_menu() is True
        assert str(panel._pv_menu.entrycget(panel.PV_MENU_CONFIRM,
                                            "state")) == "disabled"
        # an image with a confirm of its OWN still has one, whatever the
        # menu says - that is the selector's fallback, not a veto
        panel._rows[1].confirm = os.path.join(media, "confirm1.wav")
        assert panel.menu_sounds(1)["confirm"] == os.path.join(
            media, "confirm1.wav")
    finally:
        root.destroy()


# --------------------------------------------------------------------------
# the control strip: one line, 30 px, and nothing cut in half
# --------------------------------------------------------------------------

#: Every window width scripts/shot_multiboot_tab.py measures the tab at.
#: The strip has to hold at all of them, and the narrowest is where the
#: caption has least room (the flippers, Frame and the two ticks take a
#: fixed 424 px out of it).
SWEEP_WIDTHS = (840, 889, 950, 1024, 1200, 1360)


def _sized_panel(width, height=768, **kw):
    """A panel in a window of a REAL size, so the strip has a measurable
    width and the caption a real wraplength.  _panel()'s root is sized to
    the panel's own natural width and never sees a narrow window, which is
    exactly where a caption runs out of room."""
    root, panel = _panel(**kw)
    root.geometry("%dx%d+10000+10000" % (width, height))
    root.update()
    panel._on_configure()
    root.update()
    return root, panel


@pytest.mark.parametrize("width", SWEEP_WIDTHS)
def test_nothing_the_strip_says_is_cut_in_half_by_its_own_bottom_edge(
        tmp_path, monkeypatch, width):
    """The strip is a fixed 30 px with pack_propagate(False), which is ONE
    line - so a message that wraps is drawn with its second line sliced
    horizontally by the bottom edge, and the half that goes is always the
    half that said what to do about it.  Every line the tab can put there
    fits on one line at every width the layout is measured at, and the one
    that cannot is cut with an ellipsis and kept whole in the tooltip and
    the app's Log."""
    _fake_audio(monkeypatch)
    root, panel = _sized_panel(width)
    try:
        strip_h = panel._pv_strip.winfo_height()
        assert strip_h == 30            # the room, as _build_preview pins it

        def fits(what):
            """Nothing on the strip is ever taller than the strip."""
            root.update_idletasks()
            assert panel._pv_status.winfo_reqheight() <= strip_h, \
                "%s needs %d px of a %d px strip at %d wide: %r" % (
                    what, panel._pv_status.winfo_reqheight(), strip_h, width,
                    panel._pv_status.cget("text"))

        def whole():
            """...and the whole of it is still reachable: on the strip when
            it fits, in the tooltip when it had to be cut."""
            return panel._pv_status_tip.text or panel._pv_status.cget("text")

        for p in _images(tmp_path, 2):
            panel.add_image(p)
        _media_set(panel, sounds=False)
        # Ticking Sound below now asks for the two menu sounds to be
        # rendered (see MultibootPanel._prepare_sounds); this test is about
        # the STRIP, so the run is recorded rather than started.
        _recorder(panel)
        # 1. the ONE line that says the Sound tick exists (it rides the
        #    first caption after a frame is drawn, and is said once)
        panel._set_var(panel._hl_var, 1)
        assert panel.load_frame(_ppm(tmp_path / "f.ppm"), 1, 0, 1) is True
        assert "tick Sound to hear it." in whole()
        fits("the Sound note")
        # 2. the move-sound aside a flipper press finds out about
        panel._sound_var.set(True)
        panel._sound_toggled()
        panel.flip_left()
        assert "No move sound in this media set." in whole()
        fits("the move-sound aside")
        # 3. the confirm sound that has not been rendered
        assert panel.play_confirm() is False
        assert "no confirm sound in this media set" in whole()
        fits("the confirm-sound line")
        # ...and each of those said on its own - which is how it is said
        # once the note that rides the first one has been said - fits the
        # strip whole, at every width, with nothing cut:
        for line in ("This image has music - tick Sound to hear it.",
                     "No move sound in this media set.",
                     "Rendering the menu's sounds…",
                     "Image 2 frame 7 has not been drawn yet - right-click "
                     "the preview to redraw.",
                     "Image 2: frame 12 of 24 - playing",
                     "The form changed - redrawing…"):
            panel._pv_say(line)
            fits(repr(line))
            assert panel._pv_status.cget("text") == line
        # ...and anything else at all is cut, with the whole of it kept
        long = ("A preview failure with a very long explanation indeed, of "
                "the kind a tool prints when a path is wrong: " + "x" * 200)
        panel._pv_say(long, error=True)
        fits("an arbitrarily long failure")
        assert panel._pv_status.cget("text").endswith("…")
        assert panel._pv_status_tip.text == long
        assert "[preview] " + long in _pane(panel)
    finally:
        root.destroy()


def test_the_strip_says_it_once_however_many_times_it_is_asked(tmp_path):
    """A failure that repeats at the animation's rate used to put a line
    into the app's Log per tick - sixty a second at the floor - and a
    flooded Log pane is one of this app's known ways of freezing its own
    UI thread."""
    root, panel = _panel()
    try:
        for _ in range(20):
            panel._pv_say("Cannot load x.ppm: no such file", error=True)
        assert len([ln for ln in panel.log_lines()
                    if "Cannot load" in ln]) == 1
        # ...and a different failure is still said
        panel._pv_say("Cannot load y.ppm: no such file", error=True)
        assert len([ln for ln in panel.log_lines()
                    if "Cannot load" in ln]) == 2
    finally:
        root.destroy()


def test_a_sound_poll_does_not_wipe_what_the_strip_was_saying(tmp_path,
                                                              monkeypatch):
    """_recaption is called on every Sound tick and ~400 ms after the first
    sound (the player picks its backend on a worker, and the poll sees the
    status change) - so re-issuing the caption of the frame drawn BEFORE
    whatever is up now threw away cache misses and red failures alike,
    without the picture having moved."""
    made = _fake_audio(monkeypatch)
    root, panel = _panel()
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        _media_set(panel)
        # a frame is drawn for image 1...
        assert panel.load_frame(_ppm(tmp_path / "f.ppm"), 1, 0, 1) is True
        # ...and the flipper walks to image 0, which has not been drawn
        assert panel.flip_right() is True
        assert panel._hl_var.get() == "0"
        assert "has not been drawn yet" in panel._pv_status.cget("text")
        # now the sound is turned on: the strip must still be describing
        # the card the flipper left it on
        panel._sound_var.set(True)
        panel._sound_toggled()
        assert "has not been drawn yet" in panel._pv_status.cget("text")
        # ...and the same for the poll that follows the backend being
        # chosen, and for a red failure
        panel._pv_say("Preview failed at animation (exit 2).", error=True)
        made[0].status = "Sound plays through winsound."
        panel._sound_poll()
        assert panel._pv_status.cget("text").startswith("Preview failed")
    finally:
        root.destroy()


# --------------------------------------------------------------------------
# loading a card back into the form (Load card… / Apply to card)
# --------------------------------------------------------------------------

def _rich_report(tmp_path, clip=None):
    """What ``inspect --json`` prints for a v2 card built by this tab: two
    images whose .raw sources are on this machine, art from a source spec
    (one 'auto', one a frame of a video), a clip with its own start / length
    / fps, no music, and a second tree still waiting for the bypass."""
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
             "anim_source": "none", "source": multiboot_tab.wsl(a),
             "source_exists": True, "title_dir": "turtles",
             "bypass": "bypassed"},
            {"index": 1, "device": "/dev/mmcblk0p7", "title": "TMNT 1987",
             "subtitle": "1987 cartoon upscale", "art": "art1.png",
             "anim": "anim1.gif", "music": None,
             "art_source": multiboot_tab.wsl(clip) + "@21",
             "anim_source": "auto@20:2:8", "source": multiboot_tab.wsl(b),
             "source_exists": True, "title_dir": "turtles",
             "bypass": "armed"}],
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
             "source": multiboot_tab.wsl(gone), "source_exists": False,
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


def _card_file(tmp_path, name="card.multi.raw"):
    """An existing (empty) card file to load, outside the library."""
    d = tmp_path / "multi"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_bytes(bytes(16))
    return str(p)


def _loaded(tmp_path, report=None, media_json=True):
    """A panel in editing mode: the report loaded, its media dir made (with
    a media.json when the card carries media)."""
    card = _card_file(tmp_path)
    media = loaded_media_dir(card)
    os.makedirs(media, exist_ok=True)
    if media_json:
        with open(os.path.join(media, "media.json"), "w") as f:
            f.write("{}")
    root, panel = _panel()
    panel.load_inspect(report if report is not None
                       else _rich_report(tmp_path), card, media)
    return root, panel, card, media


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
                         "--card", multiboot_tab.wsl(card)]
    assert "--json" not in table and "--media-out" not in table
    js = _tool_words(cmds[1][1])
    assert js[1:4] == ["inspect", "--card", multiboot_tab.wsl(card)]
    assert "--json" in js
    assert js[js.index("--media-out") + 1] == multiboot_tab.wsl(media)
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
    assert words[1:4] == ["inject", "--card", multiboot_tab.wsl(card)]
    assert words[words.index("--selector-dir") + 1] == DEFAULT_SELECTOR_DIR
    assert words[words.index("--titles") + 1] == "IMG 0;IMG 1"
    assert words[words.index("--subtitles") + 1] == ";1987 cartoon"
    assert words[words.index("--timeout") + 1] == "0"
    assert words[words.index("--default") + 1] == "1"
    assert words[words.index("--volume") + 1] == "35"
    assert words[words.index("--media-dir") + 1] == multiboot_tab.wsl(
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
    assert [n for n, _ in apply_commands(form, card, media)] == [
        "inject", "inspect", INSPECT_JSON]
    labels = [n for n, _ in apply_commands(form, card, media, prepare=True,
                                           bypass=True)]
    assert labels == ["prepare", "inject", "bypass", "inspect", INSPECT_JSON]
    cmds = apply_commands(form, card, media, prepare=True, bypass=True,
                          refresh=False)
    prep = _tool_words(cmds[0][1])
    assert prep[1] == "prepare"
    assert prep[prep.index("--out") + 1] == multiboot_tab.wsl(media)
    assert "--visual-only" not in prep
    byp = _tool_words(cmds[2][1])
    assert byp[1:4] == ["bypass", "--card", multiboot_tab.wsl(card)]


def test_parse_inspect_finds_the_report_and_the_refusal():
    assert parse_inspect('{"layout": "parts"}') == {"layout": "parts"}
    # a profile line in front of it must not lose the report
    assert parse_inspect('hello\n{"a": [1, 2]}\n') == {"a": [1, 2]}
    assert parse_inspect("not json at all") is None
    assert parse_inspect("") is None
    assert parse_refusal("reading\nrefused: not a multi card\n") == \
        "refused: not a multi card"
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
    assert split_anim_source("none") == ("none", "", "", "")
    assert split_anim_source("auto@20:2:8") == ("auto", "20", "2", "8")
    assert split_anim_source("/mnt/d/x.gif") == ("D:/x.gif", "", "", "")
    for spec in ("auto", "none", "/mnt/d/clip.mov@21"):
        art, video, at = split_art_source(spec)
        row = ImageRow(path="x.raw", art=art, art_video=video, art_time=at)
        assert art_spec(row) == spec
    for spec in ("none", "auto", "auto@20:2:8", "/mnt/d/x.gif"):
        anim, start, secs, fps = split_anim_source(spec)
        row = ImageRow(path="x.raw", anim=anim, anim_start=start,
                       anim_seconds=secs, anim_fps=fps)
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
    assert form.bypass is False              # image 1 is still armed
    a, b = _images(tmp_path, 2)
    assert [multiboot_tab._norm(r.path) for r in form.images] == \
        [multiboot_tab._norm(a), multiboot_tab._norm(b)]
    assert [r.title for r in form.images] == ["STERN 1.59.0", "TMNT 1987"]
    assert form.images[1].subtitle == "1987 cartoon upscale"
    assert form.images[0].art == "auto" and form.images[0].anim == "none"
    assert form.images[1].art_time == "21"
    assert art_spec(form.images[1]) == info["images"][1]["art_source"]
    assert anim_spec(form.images[1]) == "auto@20:2:8"
    assert not any(multiboot_tab.on_card_fields(r) for r in form.images)
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
    assert form.bypass is True               # every tree is bypassed
    row0, row1 = form.images
    assert (row0.art, row0.art_on_card) == ("art0.png", True)
    assert (row0.music, row0.music_on_card) == ("music0.wav", True)
    assert row0.anim == "none" and row0.anim_on_card is False
    assert row0.path == "" and row0.device == "/dev/mmcblk0p3"
    assert row1.art == "none" and multiboot_tab.on_card_fields(row1) == []
    assert row1.path.endswith("1987.8G.sdcard.raw")
    assert multiboot_tab.on_card_fields(row0) == [
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
    assert changed(bypass=False) == (["bypass"], [])
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
    assert one.startswith("Apply to card: 1 menu change (title)")
    assert "card.multi.raw" in one and "no rebuild" in one
    three = edit_status_text(card, ["title", "art", "volume"], [])
    assert "3 menu changes (title, art, volume)" in three
    listed = edit_status_text(card, ["title"], ["3 images -> 2"])
    assert listed.startswith("The image list changed (3 images -> 2)")
    assert "Build & verify" in listed and "1 menu change would ride" in listed


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
    assert text == multiboot_tab.EMPTY_PATH_TEXT


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
    assert text == "Build & verify will write a new card at card.multi.raw."
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
    lib = multiboot_tab.LIBRARY_PREFIXES[0] + "/Stern/spike2/x.raw"
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
        multiboot_tab.MAX_IMAGES
    menu = menu_from_state({"volume": "not a number", "timeout": None,
                            "default": 2, "bypass": False})
    assert menu == {"move": "auto", "confirm": "auto", "volume": 50,
                    "timeout": 15, "default": 2, "bypass": False}
    assert menu_from_state(None)["bypass"] is True
    assert menu_from_state({"volume": 900})["volume"] == 100


def test_the_status_block_says_the_state_and_the_consequence(tmp_path):
    """Two lines under the bar: what just happened, and what the two
    writing buttons would do about it - with the card's size on the same
    line, because that is the same question."""
    root, panel, card, _media = _loaded(tmp_path)
    try:
        # 1. the size sentence (Check size / the build's plan step)
        panel._plan_step("plan", 0,
                         "image: 28755968 sectors = 14723055616 bytes\n"
                         "  fits Stern 16G image size 15494807552: YES "
                         "(spare 771751936)\n")
        assert "Fits a 16 GB card" in panel._edit_lbl.cget("text")
        # 2. what Apply to card would write, beside it
        assert "no changes yet" in panel._edit_lbl.cget("text")
        panel._timeout_var.set("8")
        assert panel._edit_lbl.cget("text").startswith(
            "Apply to card: 1 menu change (countdown)")
        # 3. ...and why only a rebuild can, once the image LIST moved
        panel._tree.selection_set("1")
        root.update()
        panel._remove_image()
        assert panel._edit_lbl.cget("text").startswith(
            "The image list changed")
        # ...and the size sentence beside it goes with the list it was
        # about: that number is now a claim about a card nobody has, and
        # the tab asks for a new one by itself (_maybe_plan).
        assert "Fits a 16 GB card" not in panel._edit_lbl.cget("text")
        # 4. and the live line, which an error paints red and the app's Log
        # keeps in full
        panel._ok("Reading the card…")
        assert panel._hint.cget("text") == "Reading the card…"
        panel._error("first reason\nsecond reason")
        # ONE LINE EACH.  A two-line message used to unmap the label under
        # it - the consequence line - exactly when there was most to say;
        # so the block says the first reason and how many more, and the
        # Log at the foot of the window keeps every word.
        assert panel._hint.cget("text") == \
            "first reason  (+1 more - see the Log below)"
        pane = _pane(panel)
        assert "first reason" in pane and "second reason" in pane
        # ...and the line under it is still there, still saying what it said
        assert panel._edit_lbl.cget("text").startswith("The image list")
        for lbl in (panel._hint, panel._edit_lbl):
            assert lbl.winfo_ismapped(), str(lbl)
            assert "\n" not in lbl.cget("text")
        # the block is as tall as its lines really are - 56 px over three
        # ~19 px labels was a pixel short in EVERY state
        h = panel._status_wrap.winfo_reqheight()
        assert h >= sum(lbl.winfo_reqheight() for lbl in
                        (panel._hint, panel._edit_lbl))
        # ...and it never moves, however long the message
        panel._error("\n".join("reason %d" % i for i in range(20)))
        root.update()
        assert panel._status_wrap.winfo_reqheight() == h
        assert "(+19 more" in panel._hint.cget("text")
    finally:
        root.destroy()


def test_the_tools_output_goes_to_the_apps_own_log(tmp_path):
    """THE TAB HAS NO OUTPUT PANE.  Its lines go to the Log at the foot of
    the window - the one log the whole app writes to - tagged so they read
    beside the other tabs’, and the panel keeps the same lines so a message
    the one-line status block had to clip can still be read back."""
    root, panel = _panel()
    try:
        assert not hasattr(panel, "_log_text")
        assert not hasattr(panel, "_log_btn")
        panel._write("[card] something happened")
        assert panel.sunk == ["[multi-boot] [card] something happened"]
        assert "something happened" in _pane(panel)
        # ...and a message too long for the status block reaches it whole
        panel._error("first reason\nsecond reason\nthird reason")
        assert panel._hint.cget("text") == \
            "first reason  (+2 more - see the Log below)"
        for reason in ("first reason", "second reason", "third reason"):
            assert "[multi-boot] " + reason in panel.sunk
        # the panel keeps its own copy, capped
        panel._lines = ["x"] * (panel.LOG_KEEP + 5)
        panel._write("last")
        assert len(panel.log_lines()) == panel.LOG_KEEP
        assert panel.log_lines()[-1] == "last"
    finally:
        root.destroy()


def test_the_more_menu_is_gone_and_so_is_every_entry_in_it(tmp_path):
    """David, in dark mode: "the 'more' button looks awful ... it has two
    arrows and turns white and illegible. and i don't even understand most
    of these options. do we actually need any of these options?"  We went
    through the six with him and all six went, the button with them - which
    also disposes of the rendering fault, because it was the app's ONLY
    ttk.Menubutton and the dark theme styles no TMenubutton.

    The action row is Menu settings... and the four real actions, and every
    one of the six has somewhere honest to be instead."""
    root, panel = _panel()
    try:
        assert not hasattr(panel, "_more_btn")
        assert not hasattr(panel, "_more_menu")
        assert not hasattr(panel, "_back_entry")
        # ...and nothing that was behind it is still a method of the panel
        for gone in ("_more_entry", "_back_to_card", "_bypass_existing",
                     "bypass_card", "_check_size", "_prepare_media"):
            assert not hasattr(panel, gone), gone
        # THE ROW: one button on the left, four on the right, and the label
        # that expands between them.  Nothing else, and no Menubutton.
        kids = [w.cget("text") for w in panel._action_row.winfo_children()
                if w.winfo_class() == "TButton"]
        assert sorted(kids) == sorted([
            "Menu settings\u2026", "Apply to card", "Build & verify",
            "Flash to SD card\u2026", "Run in emulator"])
        assert all(w.winfo_class() != "TMenubutton"
                   for w in panel._action_row.winfo_children())
        # 1+2. Check size and Prepare media: the tab decides, not the user.
        assert callable(panel._maybe_plan) and callable(panel._prepare_sounds)
        # 3. Start a new card is beside the field it clears.
        assert panel._new_btn.master is panel._src_row
        # 4. 'Back to the card being edited' is the path box itself.
        # 5. 'Bypass an existing card...' is Apply to card with Bypass
        #    ticked - but the tool's own subcommand stays where it is.
        assert multiboot_tab.bypass_commands("D:/x.raw")[0][0] == "bypass"
        # 6. ...and the preview's automatic redraw is on the preview's menu.
        labels = [panel._pv_menu.entrycget(i, "label")
                  for i in range(panel._pv_menu.index("end") + 1)
                  if panel._pv_menu.type(i) != "separator"]
        assert "Update the preview automatically" in labels
    finally:
        root.destroy()


def test_the_size_sentence_keeps_itself_true(tmp_path):
    """'Check size' was a thing you had to know to ask for, so the sentence
    beside the status line was whatever the last press had found.  Now the
    image list moving is what asks - and the stale sentence goes at once,
    not when the new answer comes back."""
    root, panel = _panel(plan=True)
    calls = _recorder(panel)
    try:
        a, b, c = _images(tmp_path, 3)
        panel.add_image(a)
        panel.add_image(b)
        # DEBOUNCED, not one run per keystroke: a job is armed, nothing ran.
        assert panel._plan_job is not None
        assert calls == []
        # a title is not an input to the plan, so it arms nothing new
        panel._tree.selection_set("1")
        root.update()
        armed = panel._plan_job
        panel._ed_title.set("Second")
        assert panel._plan_job is armed
        # the debounce fires: one plan, and the sentence follows it
        assert panel._plan_now() is True
        assert [label for label, _ in calls[0]] == ["plan"]
        panel._plan_step("plan", 0, "image: 1 sectors = 2 bytes\n"
                                    "  fits Stern 16G image size 3: YES "
                                    "(spare 4)\n")
        assert "Fits a 16 GB card" in panel._plan_text
        assert panel._plan_text in panel._edit_lbl.cget("text")
        # A THIRD IMAGE IS A DIFFERENT CARD.  The sentence goes NOW - a
        # wrong number is worse than none - and another run is armed.
        panel.add_image(c)
        assert panel._plan_text == ""
        assert "Fits a 16 GB card" not in panel._edit_lbl.cget("text")
        assert panel._plan_job is not None
        assert len(calls) == 1
    finally:
        root.destroy()


def test_the_size_check_never_gets_in_front_of_a_real_run(tmp_path):
    """It writes nothing and nobody asked for it, so it takes the preview's
    light guard: a write run refuses it outright, and it re-arms rather than
    queueing behind one."""
    root, panel = _panel(plan=True)
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        started = []

        def fake(cmds, **kw):
            started.append(kw)
            return not panel._busy
        panel._run_commands = fake
        panel._set_busy(True)
        assert panel._plan_now() is False
        assert started[-1]["preview"] is True    # the LIGHT guard, always
        assert panel._plan_job is not None       # ...and it will ask again
        panel._set_busy(False)
        assert panel._plan_now() is True
    finally:
        root.destroy()


def test_the_size_check_will_not_run_on_a_list_it_cannot_plan(tmp_path):
    root, panel = _panel(plan=True)
    calls = _recorder(panel)
    try:
        a, b = _images(tmp_path, 2)
        panel.add_image(a)
        assert panel._plan_now() is False        # one image is not a card
        panel.add_image(b)
        panel._rows[1].path = str(tmp_path / "gone.raw")
        assert panel._plan_now() is False        # ...nor is a missing file
        assert calls == []
        panel._rows[1].path = b
        assert panel._plan_now() is True
        # ...and the off switch the screenshot rig and the tests use
        panel._auto_plan = False
        assert panel._plan_now() is False
        assert len(calls) == 1
    finally:
        root.destroy()


def test_ticking_sound_renders_the_menus_sounds(tmp_path, monkeypatch):
    """Ticking Sound used to tell you to go and find 'Prepare media' in a
    menu and press it, because the preview prepares pictures and music only.
    Ticking Sound IS the asking."""
    _fake_audio(monkeypatch)
    root, panel = _panel()
    calls = _recorder(panel)
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        # music=False so every media field is a WORD rather than a bare
        # file name off a card: this panel has loaded nothing, so a name
        # that is not a path on this machine is a form the tool would
        # refuse - which is a different refusal from the one being tested.
        _media_set(panel, sounds=False, music=False)   # --visual-only's half
        panel._sound_var.set(True)
        panel._sound_toggled()
        assert [label for label, _ in calls[0]] == ["prepare"]
        prep = _tool_words(calls[0][0][1])
        assert "--visual-only" not in prep and "--sound-move" in prep
        assert "Rendering the menu's sounds" in panel._pv_status.cget("text")
        # ...and a set that HAS them is not prepared again
        calls[:] = []
        _media_set(panel, sounds=True, music=False)
        panel._sound_var.set(False)
        panel._sound_toggled()
        panel._sound_var.set(True)
        panel._sound_toggled()
        assert calls == []
        # ...nor is a menu whose move sound is 'none': there is nothing to
        # render, whatever the media set has in it
        _media_set(panel, sounds=False, music=False)
        panel._move_var.set("none")
        assert panel._sounds_ready() is True
        panel._sound_var.set(False)
        panel._sound_toggled()
        panel._sound_var.set(True)
        panel._sound_toggled()
        assert calls == []
    finally:
        root.destroy()


def test_a_render_with_sound_on_prepares_the_whole_media_set(tmp_path):
    """The other half of the same rule: while Sound is ticked the preview's
    own prepare is the FULL one, so the sounds cannot go missing under a
    tick that is already on."""
    root, panel = _panel()
    calls = _recorder(panel)
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        assert panel.render_preview() is True
        assert "--visual-only" in _line(calls[0][1][1])
        panel._pv_ready = None
        panel._sound_var.set(True)
        assert panel.render_preview() is True
        prep = _tool_words(calls[1][1][1])
        assert "--visual-only" not in prep and "--sound-move" in prep
    finally:
        root.destroy()


def test_new_card_clears_the_form_and_leaves_editing_mode(tmp_path):
    root, panel, card, _media = _loaded(tmp_path)
    try:
        assert panel._loaded_card == card
        panel._plan_step("plan", 0, "  fits Stern 16G image size 1: YES "
                                    "(spare 2)\n")
        panel.new_card()
        assert panel._rows == []
        assert panel._loaded_card == "" and panel._loaded_form is None
        assert panel._out_var.get() == ""
        assert panel._volume_var.get() == "50"
        assert panel._timeout_var.get() == "15"
        assert panel._bypass_var.get() is True
        assert panel._plan_text == ""
        # The line under the buttons never goes blank any more: it is where
        # the mode is said now that the row has one control instead of two.
        assert panel._edit_lbl.cget("text") == multiboot_tab.EMPTY_PATH_TEXT
        assert str(panel._apply_btn.cget("state")) == "disabled"
        assert not panel._can_read
        assert panel._pv_cache == {} and panel._pv_photo is None
        assert panel._tree.get_children() == (panel.ADD_ROW,)
        # ...and the output box follows the next primary again
        panel.add_image(_images(tmp_path, 1)[0])
        assert panel._out_var.get() == default_output_path(
            _images(tmp_path, 1)[0])
    finally:
        root.destroy()


@pytest.mark.skipif(not HAS_DISPLAY, reason="no Tk display available")
def test_the_whole_tab_fits_a_1024x768_desktop(tmp_path):
    """DAVID'S DESKTOP IS 1024x768 and the app window is already larger than
    it.  The tab must fit the notebook's ~640 px of content height with
    nothing scrolled off - which is what the two modals and a preview
    sized to what the table leaves it buy.  Measured on a populated tab,
    because an empty one proves nothing."""
    import tkinter as tk
    root = _root()
    root.geometry("1024x768")
    frame = tk.Frame(root)
    frame.pack(fill=tk.BOTH, expand=True)
    panel = multiboot_tab.MultibootPanel(frame)
    panel.build(frame)
    panel._auto_preview.set(False)
    root.update()
    try:
        for p in _images(tmp_path, 3):
            panel.add_image(p)
        panel._tree.selection_set("1")
        root.update()
        panel._ed_title.set("TMNT 1987")
        panel._ed_sub.set("1987 cartoon upscale")
        panel._ed_anim.set("auto")
        panel._plan_step("plan", 0,
                         "image: 28755968 sectors = 14723055616 bytes\n"
                         "  fits Stern 16G image size 15494807552: YES "
                         "(spare 771751936)\n")
        panel._ok("Card built and verified: D:/Pinball/multi/card.multi.raw")
        root.update()
        root.update_idletasks()
        height = frame.winfo_reqheight()
        assert height <= multiboot_tab.TAB_BUDGET_H, \
            "the tab needs %d px of height" % height
        # the canvas IS the picture: exactly the 16:9 of the selector's own
        # frame, so there are no black bars around it
        assert panel._pv_h <= multiboot_tab.PREVIEW_H
        assert abs(panel._pv_w - panel._pv_h * multiboot_tab.FRAME_W
                   / multiboot_tab.FRAME_H) <= 1
        assert panel._pv_w <= 1024
        # every button is on screen - this app unmaps the last widget of a
        # row that overflows, without a word.  The path entry is in here
        # too: it is the widget the source row is packed to let shrink.
        for btn in (panel._out_entry, panel._browse_btn,
                    panel._new_btn, panel._about_badge,
                    panel._apply_btn, panel._build_btn, panel._flash_btn,
                    panel._emu_btn, panel._menu_btn,
                    panel._play_chk):
            assert btn.winfo_ismapped(), str(btn)
        # ...and the list has NONE: its actions are icons on its rows
        for gone in ("_add_btn", "_edit_btn", "_remove_btn", "_up_btn",
                     "_down_btn", "_render_btn", "_log_btn"):
            assert not hasattr(panel, gone), gone
        # THE ARRANGEMENT NEVER CHANGES.  Whatever the width, the preview
        # is above the table, the tab is the same height, and the picture
        # never grows past the width it is given.
        for width in (840, 889, 950, 1024, 1200, 1360):
            root.geometry("%dx768" % width)
            root.update()
            root.update_idletasks()
            assert panel._pv_canvas.winfo_y() < panel._tree.winfo_rooty()
            assert frame.winfo_reqheight() == height, width
            assert panel._pv_w <= width, width
            assert abs(panel._pv_w - panel._pv_h * multiboot_tab.FRAME_W
                       / multiboot_tab.FRAME_H) <= 1, width
    finally:
        root.destroy()


def _inspect_stand_in(monkeypatch, tmp_path, report,
                      table="== card\nimages: 2", refusal=None,
                      refuse_at="inspect"):
    """A python child for each inspect step: the table, then the JSON.

    Both read their output out of a FILE, so nothing a step prints is also
    in the command line the pane echoes - that is what makes 'the JSON is
    not in the pane' a real assertion."""
    py = sys.executable
    blob = tmp_path / "report.json"
    blob.write_text(json.dumps(report), encoding="utf-8")
    msg = tmp_path / "refusal.txt"
    msg.write_text(refusal or "", encoding="utf-8")
    cat = "import sys; sys.stdout.write(open(sys.argv[1]).read())"
    seen = {}

    def fake(card, media_out=None, cwd=None):
        seen["card"], seen["media_out"] = card, media_out
        seen.setdefault("runs", []).append(card)

        def step(label, path):
            if refusal is not None and label == refuse_at:
                return [py, "-c", cat + "; raise SystemExit(2)", str(msg)]
            if label == "inspect":
                return [py, "-c", "print(%r)" % table]
            return [py, "-c", cat, str(path)]
        return [("inspect", step("inspect", None)),
                (INSPECT_JSON, step(INSPECT_JSON, blob))]
    monkeypatch.setattr(multiboot_tab, "inspect_commands", fake)
    return seen


def test_load_card_runs_inspect_and_fills_every_field(tmp_path, monkeypatch):
    """The whole load through the worker: the tool's table lands in the
    pane, its JSON does NOT (it is for the form), and every widget comes
    back holding what the card carries."""
    card = _card_file(tmp_path)
    info = _rich_report(tmp_path)
    seen = _inspect_stand_in(monkeypatch, tmp_path, info)
    root, panel = _panel()
    try:
        assert panel.load_card(card) is True
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        assert seen["card"] == card
        assert os.path.normpath(seen["media_out"]) == os.path.normpath(
            loaded_media_dir(card))
        assert os.path.isdir(loaded_media_dir(card))
        pane = _pane(panel)
        assert "images: 2" in pane                       # the table
        assert '"art_source"' not in pane                # not the JSON
        assert "%s: exit 0" % INSPECT_JSON in pane
        form = panel.form()
        assert [r.title for r in form.images] == ["STERN 1.59.0", "TMNT 1987"]
        assert panel._out_var.get() == card
        assert panel._timeout_var.get() == "20"
        assert panel._default_var.get() == "1"
        assert panel._volume_var.get() == "35"
        assert panel._move_var.get() == "synth"
        assert panel._bypass_var.get() is False          # image 1 is armed
        assert panel._armed is True
        assert panel._loaded_card == card
        # the card's own default is the row the load lands on, so the
        # preview highlights the image the machine would boot
        assert panel._hl_var.get() == "1"
        assert panel._tree.selection() == ("1",)
        assert panel._tree.get_children() == ("0", "1", panel.ADD_ROW)
        assert panel._tree.item("1")["values"][:5] == [
            1, "TMNT 1987", "1987 cartoon upscale", "attract.mov @21s",
            "auto @20s 2s 8fps"]
        assert multiboot_tab.cell_anim(panel.form().images[1]) == \
            "auto @20s 2s 8fps"
        assert str(panel._apply_btn.cget("state")) == "normal"
        assert "no changes yet" in panel._edit_lbl.cget("text")
    finally:
        root.destroy()


@pytest.mark.parametrize("refuse_at", ["inspect", INSPECT_JSON])
def test_a_refused_inspect_says_why_and_leaves_the_form_alone(tmp_path,
                                                              monkeypatch,
                                                              refuse_at):
    card = _card_file(tmp_path)
    _inspect_stand_in(monkeypatch, tmp_path, _rich_report(tmp_path),
                      refusal="refused: p2 holds no /usr/local/codeselect",
                      refuse_at=refuse_at)
    root, panel = _panel()
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        before = panel.form()
        assert panel.load_card(card) is True
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        hint = panel._hint.cget("text")
        assert "refused: p2 holds no /usr/local/codeselect" in hint
        assert os.path.basename(card) in hint
        assert panel._loaded_card == ""
        assert panel._loaded_form is None
        assert [r.path for r in panel.form().images] == \
            [r.path for r in before.images]
        assert panel._out_var.get() == before.out
        assert str(panel._apply_btn.cget("state")) == "disabled"
        # ...and the row is not claiming to be editing anything either: the
        # verb only becomes 'Reload card' once a card really is in the form.
        # ...and what the tool said is in the pane either way: a quiet step
        # that FAILS prints everything it printed.
        assert "refused: p2 holds no" in _pane(panel)
    finally:
        root.destroy()


def test_the_busy_guard_covers_a_load_and_an_apply(tmp_path, monkeypatch):
    monkeypatch.setattr(multiboot_tab.subprocess, "Popen",
                        lambda *a, **kw: pytest.fail("a tool was started"))
    root, panel, card, _media = _loaded(tmp_path)
    try:
        panel._set_busy(True)
        # _can_read is about the PATH, not about whether a run is in
        # flight; the guard that used to grey a button now lives in the
        # methods themselves, which is what this test is really about.
        assert str(panel._apply_btn.cget("state")) == "disabled"
        assert panel._load_or_reload() is False
        assert panel.load_card(card) is False
        assert "already in progress" in panel._hint.cget("text")
        assert panel.apply_to_card() is False
        assert "already in progress" in panel._hint.cget("text")
        panel._set_busy(False)
        assert str(panel._apply_btn.cget("state")) == "normal"
    finally:
        root.destroy()


def test_a_menu_change_is_injected_into_the_loaded_card(tmp_path):
    """The common case: retype a title, press Apply, and the card is
    rewritten in place - an inject and a read-back, no prepare (no media
    field moved) and no copy."""
    root, panel, card, media = _loaded(tmp_path)
    calls = _recorder(panel)
    try:
        panel._tree.selection_set("1")
        root.update()
        panel._ed_sub.set("1987 cartoon, upscaled")
        panel._timeout_var.set("8")
        text = panel._edit_lbl.cget("text")
        assert "Apply to card: 2 menu changes (subtitle, countdown)" in text
        assert str(panel._apply_btn.cget("state")) == "normal"
        assert panel.apply_to_card() is True
        labels = [label for label, _ in calls[0]]
        assert labels == ["inject", "inspect", INSPECT_JSON]
        words = _tool_words(calls[0][0][1])
        assert words[1:4] == ["inject", "--card", multiboot_tab.wsl(card)]
        assert words[words.index("--subtitles") + 1] == \
            "Original Stern code;1987 cartoon, upscaled"
        assert words[words.index("--timeout") + 1] == "8"
        assert words[words.index("--media-dir") + 1] == multiboot_tab.wsl(
            media)
        assert "Writing the menu into" in panel._hint.cget("text")
    finally:
        root.destroy()


def test_a_media_change_prepares_into_the_loaded_cards_media_dir(tmp_path):
    root, panel, card, media = _loaded(tmp_path)
    calls = _recorder(panel)
    try:
        panel._tree.selection_set("0")
        root.update()
        panel._ed_anim.set("auto")
        assert "1 menu change (animation)" in panel._edit_lbl.cget("text")
        assert panel.apply_to_card() is True
        assert [label for label, _ in calls[0]] == [
            "prepare", "inject", "inspect", INSPECT_JSON]
        prep = _tool_words(calls[0][0][1])
        assert prep[prep.index("--out") + 1] == multiboot_tab.wsl(media)
        assert "0=auto" in prep and "1=auto@20:2:8" in prep
        assert "--visual-only" not in prep
        assert "(media first)" in panel._hint.cget("text")
    finally:
        root.destroy()


def test_the_bypass_rides_along_while_a_tree_is_still_armed(tmp_path):
    root, panel, card, _media = _loaded(tmp_path)
    calls = _recorder(panel)
    try:
        assert panel._armed is True and panel._bypass_var.get() is False
        panel._bypass_var.set(True)
        assert "1 menu change (bypass)" in panel._edit_lbl.cget("text")
        assert panel.apply_to_card() is True
        assert [label for label, _ in calls[0]] == [
            "inject", "bypass", "inspect", INSPECT_JSON]
        byp = _tool_words(calls[0][1][1])
        assert byp[1:4] == ["bypass", "--card", multiboot_tab.wsl(card)]
        # untick it again and the tab says what unticking cannot do
        panel._bypass_var.set(False)
        panel._loaded_form = multiboot_tab.replace(panel._loaded_form,
                                                   bypass=True)
        panel._update_edit_status()
        assert "cannot un-patch" in panel._edit_lbl.cget("text")
    finally:
        root.destroy()


@pytest.mark.parametrize("how", ["add", "remove", "reorder", "replace"])
def test_an_image_list_change_refuses_the_apply(tmp_path, how):
    """Adding, removing, reordering or replacing an image is a rebuild:
    Apply goes grey, says why, and starts nothing."""
    root, panel, card, _media = _loaded(tmp_path)
    calls = _recorder(panel)
    try:
        if how == "add":
            panel.add_image(_images(tmp_path, 3)[2])
        elif how == "remove":
            panel._tree.selection_set("1")
            root.update()
            panel._remove_image()
        elif how == "reorder":
            panel._tree.selection_set("1")
            root.update()
            panel._move_image(-1)
        else:
            panel._rows[1].path = _images(tmp_path, 3)[2]
            panel._refresh_tree(select=1)
        text = panel._edit_lbl.cget("text")
        assert text.startswith("The image list changed")
        assert "Build & verify writes a new card" in text
        assert str(panel._apply_btn.cget("state")) == "disabled"
        assert panel.apply_to_card() is False
        assert calls == []
        assert "image list changed" in panel._hint.cget("text")
        assert "Build & verify" in panel._hint.cget("text")
    finally:
        root.destroy()


def test_build_and_verify_will_not_write_over_the_loaded_card(tmp_path,
                                                              monkeypatch):
    """A load points the output at the card it read.  Build & verify must
    not copy ~7 GB per image over it on the strength of that: it refuses
    until a different output path is set, and says which two things it
    could do instead."""
    monkeypatch.setattr(multiboot_tab.subprocess, "Popen",
                        lambda *a, **kw: pytest.fail("a tool was started"))
    root, panel, card, _media = _loaded(tmp_path)
    calls = _recorder(panel)
    try:
        assert panel._out_var.get() == card
        panel._build_card()
        assert calls == []
        hint = panel._hint.cget("text")
        assert "writes a NEW card" in hint and card in hint
        assert "Apply to card" in hint
        # a different path builds as usual (the loaded card is untouched)
        out = str(tmp_path / "multi" / "copy.multi.raw")
        panel._out_var.set(out)
        panel._build_card()
        # the media set the load extracted is prepared again first, from the
        # source specs the card recorded - the same rule as any other build
        assert [label for label, _ in calls[0]] == [
            "prepare", "plan", "build", "verify"]
        assert multiboot_tab.wsl(out) in _line(calls[0][2][1])
        assert panel._loaded_card == card       # still editing that one
    finally:
        root.destroy()


def test_a_rebuild_is_blocked_by_media_only_the_card_has(
        tmp_path, monkeypatch):
    monkeypatch.setattr(multiboot_tab.subprocess, "Popen",
                        lambda *a, **kw: pytest.fail("a tool was started"))
    root, panel, card, _media = _loaded(
        tmp_path, _degraded_report(tmp_path), media_json=False)
    calls = _recorder(panel)
    try:
        panel._out_var.set(str(tmp_path / "multi" / "copy.multi.raw"))
        panel._build_card()
        assert calls == []
        # every reason at once - one on the tab, all of them in the tool
        # output pane (the status block holds one line per label)
        assert "(+3 more" in panel._hint.cget("text")
        pane = _pane(panel)
        assert "no such file" in pane.lower()
        assert "art0.png" in pane and "on the loaded card" in pane
        # the table says which fields those are, and which image is missing
        assert panel._tree.item("0")["values"][3] == "art0.png (on the card)"
        assert panel._tree.item("0")["values"][5] == "music0.wav"
        assert "no source recorded" in panel._tree.item("0")["values"][1]
        assert "not on this machine" in panel._tree.item("1")["values"][1]
        # ...and an apply that would have to re-render them says so too -
        # once the path box names the loaded card again, because Apply only
        # ever writes into the card the box is pointing at.
        panel._out_var.set(panel._loaded_card)
        assert panel._out_var.get() == card
        panel._tree.selection_set("0")
        root.update()
        panel._ed_anim.set("auto")
        assert panel.apply_to_card() is False
        pane = _pane(panel)
        assert "music0.wav" in pane and "no source recorded" in pane
        # ...and the confirm sound, which 'auto' would decode off a primary
        # image that is not here either
        assert "confirm sound is 'auto'" in pane
        assert calls == []
    finally:
        root.destroy()


def test_a_menu_only_apply_is_fine_on_a_card_with_no_sources(tmp_path):
    """The point of the whole feature: a card whose .raw sources are not on
    this machine can still have its menu rewritten."""
    root, panel, card, _media = _loaded(
        tmp_path, _degraded_report(tmp_path), media_json=False)
    calls = _recorder(panel)
    try:
        panel._tree.selection_set("0")
        root.update()
        panel._ed_title.set("STERN 1.59.0")
        assert panel.apply_to_card() is True
        assert [label for label, _ in calls[0]] == [
            "inject", "inspect", INSPECT_JSON]
        words = _tool_words(calls[0][0][1])
        assert words[words.index("--titles") + 1] == "STERN 1.59.0;1987"
        assert "--media-dir" not in words          # the card carries no
        # media.json, so the inject leaves the media it has alone
    finally:
        root.destroy()


def test_the_preview_after_a_load_draws_the_cards_own_media(tmp_path,
                                                            monkeypatch):
    """Requirement 4: the media is already in the extracted dir, so the
    preview renders straight from it - no prepare, and no need for the .raw
    files the card was built from.  Touch a media field and the prepare
    comes back."""
    seen = _stand_ins(monkeypatch, tmp_path, frames=3)
    root, panel, card, media = _loaded(
        tmp_path, _degraded_report(tmp_path), media_json=False)
    calls = []
    try:
        real = panel._run_commands
        panel._run_commands = lambda cmds, **kw: calls.append(
            [label for label, _ in cmds]) or real(cmds, **kw)
        assert panel.needs_prepare() is False
        assert panel.render_preview() is True
        _wait(root, lambda: not (panel._busy or panel._pv_busy))
        assert calls == [["selector", "frame 0"]]
        assert "media" not in seen                   # no prepare ran at all
        assert seen["snapshot"][0][2] == media       # drawn from the card's
        assert panel._pv_photo is not None
        conf = os.path.join(multiboot_tab.preview_dir_for(card), "images.conf")
        with open(conf, "rb") as f:
            assert b"art0.png" in f.read()
        # change the art and the media must be rendered again
        panel._tree.selection_set("0")
        root.update()
        panel._ed_art.set("auto")
        assert panel.needs_prepare() is True
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
    # THE FOOTER IS THIS TAB'S OWN while it shows: its stages, not the
    # Extract pipeline's, and the panel drives them through one seam.
    assert w.MULTIBOOT_PHASES == ("Media", "Copy", "Inject", "Verify")
    assert len(w._multiboot_phase_labels) == len(w.MULTIBOOT_PHASES)
    assert w._multiboot_panel._phase_fn == w.set_multiboot_phase
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


def test_the_screenshot_footer_cannot_drift_from_the_selectors_own():
    """The stand-in boot frame in scripts/shot_multiboot_tab.py is drawn in
    Python (the script must never need WSL or an ARM binary), so the footer
    it paints could drift from the one the selector really draws - and it
    nearly did: the selector grew a second footer for the Action button.
    The script reads codeselect.c's macros instead of carrying a copy."""
    import re as _re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    shot = open(os.path.join(root, "scripts", "shot_multiboot_tab.py"),
                encoding="utf-8").read()
    src = open(os.path.join(root, "tools", "spike2_emu", "codeselect",
                            "codeselect.c"), encoding="utf-8").read()
    feet = dict(_re.findall(r'^#define FOOT_(START|ACTION)\s+"(.*)"$', src,
                            _re.M))
    assert set(feet) == {"START", "ACTION"}, feet
    assert "LEFT / RIGHT FLIPPER" not in shot, \
        "the shot script carries its own copy of the selector's footer again"
    assert "def selector_footer(" in shot and "FOOT_(START|ACTION)" in shot


def test_an_images_own_confirm_survives_a_card_round_trip(tmp_path):
    """What an inspect reports comes back as the row that wrote it, so a
    load followed by an apply writes the same card.  The manifest records
    the SPEC in confirm_source and the staged file in confirm; only the
    spec can be rendered again, and a bare file name with no spec is kept
    as the card's own file - the same rule art, animation and music follow."""
    rows, _warn = multiboot_tab.rows_from_inspect({"images": [
        {"device": "/dev/mmcblk0p3", "title": "A"},
        {"device": "/dev/mmcblk0p7", "title": "B",
         "confirm": "confirm1.wav", "confirm_source": "synth"},
        {"device": "/dev/mmcblk0p7:img2", "title": "C",
         "confirm": "confirm2.wav"},
    ]})
    assert [r.confirm for r in rows] == ["", "synth", "confirm2.wav"]
    assert [r.confirm_on_card for r in rows] == [False, False, True]
    assert multiboot_tab.on_card_fields(rows[2]) == [
        ("confirm sound", "confirm2.wav")]
    assert [multiboot_tab.confirm_spec(r) for r in rows] == [
        "none", "synth", multiboot_tab.wsl("confirm2.wav")]


def test_a_confirm_spec_keeps_a_catalogue_index_and_a_path(tmp_path):
    """'auto@54' picks a specific sound out of that image's own catalogue.
    The tab never writes one, but a card prepared by hand carries it, and a
    load must hand it back rather than mangle it into a path."""
    assert multiboot_tab.split_confirm_source("auto@54") == "auto@54"
    assert multiboot_tab.confirm_spec(ImageRow("", confirm="auto@54")) == \
        "auto@54"
    assert multiboot_tab.split_confirm_source("none") == ""
    assert multiboot_tab.split_confirm_source(None) == ""
    # a path still crosses as a path
    p = str(tmp_path / "my chime.wav")
    assert multiboot_tab.confirm_spec(ImageRow("", confirm=p)) == \
        multiboot_tab.wsl(p)


def test_a_per_image_confirm_is_a_media_change(tmp_path):
    """It is prepared media, so changing one has to make the tools run
    again - and it is a MENU field, so 'Apply to card' can write it without
    a rebuild."""
    before = _form(tmp_path, 2)
    after = _form(tmp_path, 2)
    after.images[1].confirm = "synth"
    menu, rebuild = multiboot_tab.diff_forms(before, after)
    assert "confirm sound" in menu and not rebuild
    assert "confirm sound" in multiboot_tab.MEDIA_FIELDS
    # ...and the prepared set depends on it, so the cache cannot hand back
    # the old media
    assert multiboot_tab.media_fingerprint(before) != \
        multiboot_tab.media_fingerprint(after)


def test_the_version_gate_findings_come_back_worst_first():
    """``inspect`` writes each finding as a finished sentence, so the tab
    shows what the tool decided rather than deciding it again.  A card whose
    images are not even the same GAME is worse than one that is a version
    apart, which is worse than one that only ships different node firmware."""
    assert multiboot_tab.version_alarm({}) is None
    assert multiboot_tab.version_alarm(
        {"version_mismatch": None, "node_fw_mismatch": None}) is None
    head, full = multiboot_tab.version_alarm({
        "version_mismatch": "1.59.0 and 1.58.0 are not the same code.",
        "node_fw_mismatch": "Image 2 carries 1.19.0.",
    })
    assert head == "These images are not the same game code version."
    # every finding is kept, in the same order, for the Log and the tooltip
    assert full.splitlines()[0] == "1.59.0 and 1.58.0 are not the same code."
    assert "Image 2 carries 1.19.0." in full
    worst, _full = multiboot_tab.version_alarm({
        "title_mismatch": "One is turtles_pro, the other is godzilla.",
        "version_mismatch": "1.59.0 and 1.13.0.",
    })
    assert worst == "These images are not the same game."


def test_a_mismatched_card_raises_a_strip_above_the_picture(tmp_path):
    """David: warn very loudly when the versions do not match.  It is a
    line of its own in the error colour, not one note among many on the
    status line - and it costs no vertical space on a card that is fine."""
    root, panel = _panel()
    try:
        report = {
            "images": [
                {"device": "/dev/mmcblk0p3", "title": "A", "version": "1.59.0"},
                {"device": "/dev/mmcblk0p7", "title": "B", "version": "1.58.0"},
            ],
            "version_mismatch": "Image 0 is 1.59.0 and image 1 is 1.58.0.",
        }
        panel.load_inspect(report, str(tmp_path / "card.raw"),
                           media_dir=str(tmp_path / "media"))
        assert panel._alarm_box.winfo_manager() == "pack"
        assert panel._alarm.cget("text").startswith(panel.ALARM_PREFIX)
        assert "not the same game code version" in panel._alarm.cget("text")
        # the whole finding is readable, not just the headline
        assert report["version_mismatch"] in panel._alarm_tip.text
        assert any("Image 0 is 1.59.0" in ln for ln in panel.log_lines())
        # ...and the version the tool read is in the table, never typed
        assert [panel._tree.item(str(i))["values"][7] for i in (0, 1)] == \
            ["1.59.0", "1.58.0"]
        # a card whose images agree takes the strip away again
        clean = dict(report, version_mismatch=None)
        panel.load_inspect(clean, str(tmp_path / "ok.raw"),
                           media_dir=str(tmp_path / "media2"))
        assert panel._alarm_box.winfo_manager() == ""
        # ...and so does starting a new card
        panel.load_inspect(report, str(tmp_path / "card.raw"),
                           media_dir=str(tmp_path / "media"))
        assert panel._alarm_box.winfo_manager() == "pack"
        panel.new_card()
        assert panel._alarm_box.winfo_manager() == ""
    finally:
        root.destroy()


# --------------------------------------------------------------------------
# the source row: one path, one verb, one Browse
#
# David, looking at the row it replaced: "this section is confusing. why do i
# have a browse and input section when i have a 'new card' and 'load card'
# one?"  It carried two file pickers that meant different things beside a
# field whose meaning changed with a mode nothing showed.
# --------------------------------------------------------------------------

def test_the_source_row_is_one_path_and_two_buttons(tmp_path):
    root, panel = _panel()
    try:
        root.geometry("840x768")
        root.update()
        root.update_idletasks()
        # every widget of the row on screen at the narrowest width this tab
        # supports - the app unmaps the last widget of a row it cannot fit,
        # without a word
        for w in (panel._out_entry, panel._browse_btn,
                  panel._about_badge):
            assert w.winfo_ismapped(), str(w)
        assert not hasattr(panel, "_load_card_dialog")
        # TWO BUTTONS, NOT THREE.  There is no verb button any more: a card
        # picked in Browse… is a card you meant to read, so Browse… reads
        # it, and a second button asking "yes, really?" was the redundancy
        # that started this row's rewrite, moved along by one (David:
        # "shouldn't we have just a browse and a new button?").
        assert not hasattr(panel, "_load_btn")
        # ...and 'New card' is a real command, beside the field it clears
        # rather than in a menu (it opens no dialog, so no ellipsis on it
        # either) - see test_the_more_menu_is_gone_and_so_is_every_entry.
        assert panel._new_btn.cget("text") == "New card"
        assert "\u2026" not in panel._new_btn.cget("text")
    finally:
        root.destroy()


def test_the_verb_and_the_line_follow_what_the_probe_found(tmp_path):
    """_probe_done is the public seam: a facts dict, no disk at all."""
    root, panel = _panel()
    try:
        card = str(tmp_path / "multi" / "card.multi.raw")
        panel._out_var.set(card)
        panel._probe_done(card, {"kind": "missing", "parent": True})
        assert not panel._can_read
        assert "will write a new card" in panel._edit_lbl.cget("text")
        panel._probe_done(card, {"kind": "file"})
        assert panel._can_read
        assert "is on disk" in panel._edit_lbl.cget("text")
        panel._probe_done(card, {"kind": "unreachable", "root": "W:\\"})
        assert not panel._can_read
        assert "W:\\ is not there right now" in panel._edit_lbl.cget("text")
        # an answer about OTHER text is not shown against this path
        panel._probe_done(str(tmp_path / "elsewhere.raw"), {"kind": "file"})
        assert panel._edit_lbl.cget("text") == ""
        # ...and a path that is there is one <Return> would read
        panel._probe_done(card, {"kind": "file"})
        assert panel._can_read
        # ...while the busy guard, which used to be folded into the verb
        # button's state, now refuses the read itself
        panel._set_busy(True)
        assert panel._load_or_reload() is False
        panel._set_busy(False)
        assert panel._can_read
    finally:
        root.destroy()


def test_a_load_over_unsaved_changes_asks_before_it_reads(tmp_path,
                                                          monkeypatch):
    """The two-button row made it obvious you were leaving; one field is
    less obvious, so it has to ask - and a 'no' must not read the card."""
    root, panel, card, _media = _loaded(tmp_path)
    other = _card_file(tmp_path, "second.multi.raw")
    reads = []
    monkeypatch.setattr(panel, "load_card", lambda p: reads.append(p))
    asked = []

    def answer(title, message):
        asked.append(message)
        return False
    monkeypatch.setattr(multiboot_tab.messagebox, "askyesno", answer)
    try:
        # nothing unsaved: no question, and the read happens
        panel._out_var.set(other)
        panel._load_or_reload()
        assert reads == [other] and asked == []
        # one unsaved change: asked, and 'no' reads nothing
        reads.clear()
        panel._out_var.set(card)
        panel._timeout_var.set("8")
        panel._out_var.set(other)
        panel._load_or_reload()
        assert reads == []
        assert len(asked) == 1
        assert "1 unsaved change to card.multi.raw" in asked[0]
        assert "second.multi.raw" in asked[0]
    finally:
        root.destroy()


def test_browse_reads_a_card_it_picked_and_only_sets_a_new_one(tmp_path,
                                                               monkeypatch):
    root, panel = _panel()
    card = _card_file(tmp_path)
    reads = []
    monkeypatch.setattr(panel, "load_card", lambda p: reads.append(p))
    monkeypatch.setattr(
        multiboot_tab.messagebox, "askyesno",
        lambda *a, **kw: pytest.fail("asked with an empty tab"))
    try:
        # an EXISTING card is one you meant to read
        monkeypatch.setattr(multiboot_tab.filedialog, "asksaveasfilename",
                            lambda **kw: card)
        panel._browse_card()
        assert panel._out_var.get() == card and reads == [card]
        # a name that does not exist yet is a build target, and nothing runs
        reads.clear()
        fresh = str(tmp_path / "multi" / "new.multi.raw")
        monkeypatch.setattr(multiboot_tab.filedialog, "asksaveasfilename",
                            lambda **kw: fresh)
        panel._browse_card()
        assert panel._out_var.get() == fresh and reads == []
        # cancelling leaves the box alone
        monkeypatch.setattr(multiboot_tab.filedialog, "asksaveasfilename",
                            lambda **kw: "")
        panel._browse_card()
        assert panel._out_var.get() == fresh
    finally:
        root.destroy()


def test_the_browse_dialog_can_return_a_name_that_does_not_exist(tmp_path,
                                                                 monkeypatch):
    """A save dialog, with its own confirm OFF: an open dialog could never
    name a build target, and a confirm shown while picking a card to READ
    would be a lie.  The real overwrite gate is _confirm_overwrite, on the
    press of Build."""
    root, panel = _panel()
    seen = {}
    monkeypatch.setattr(multiboot_tab.filedialog, "asksaveasfilename",
                        lambda **kw: seen.update(kw) or "")
    try:
        panel._browse_card()
        assert seen["confirmoverwrite"] is False
        assert seen["defaultextension"] == ".raw"
        assert "*.raw *.img" in seen["filetypes"][0][1]
        assert "read" in seen["title"] and "build" in seen["title"]
    finally:
        root.destroy()


def test_the_path_box_is_the_cards_identity(tmp_path):
    """The one rule: editing mode is exactly "the file at that path has been
    read into this form".  Card image: Y on screen with Apply injecting into
    X used to be three keystrokes away."""
    root, panel, card, _media = _loaded(tmp_path)
    calls = _recorder(panel)
    try:
        assert str(panel._apply_btn.cget("state")) == "normal"
        panel._out_var.set(str(tmp_path / "multi" / "copy.multi.raw"))
        # ...and now the tab stops claiming to be editing it
        assert str(panel._apply_btn.cget("state")) == "disabled"
        assert "no longer names" in panel._edit_lbl.cget("text")
        assert "type that path back" in panel._edit_lbl.cget("text")
        assert str(panel._build_btn.cget("style")) == "Go.TButton"
        # the greying is a claim; this is the guarantee behind it
        assert panel.apply_to_card() is False
        assert calls == []
        assert "no longer names" in panel._hint.cget("text")
        # NOTHING WAS THROWN AWAY: the rows, the baseline and the media dir
        # are all still there, and the way back is one menu entry
        assert panel._loaded_card == card and panel._loaded_form is not None
        assert len(panel._rows) == 2
        panel._out_var.set(card)                # the way back IS the path
        assert str(panel._apply_btn.cget("state")) == "normal"
        assert "no longer names" not in panel._edit_lbl.cget("text")
    finally:
        root.destroy()


def test_the_probe_has_its_own_off_switch(tmp_path, monkeypatch):
    """PAD_MULTIBOOT_PROBE=0 stops the stat, and the row degrades to saying
    nothing with the verb still live - never to a dead row, which is what
    gating it on the preview's own switch would have made of every
    screenshot and most tests."""
    monkeypatch.setenv("PAD_MULTIBOOT_PROBE", "0")
    root, panel = _panel()
    try:
        card = _card_file(tmp_path)
        panel._out_var.set(card)
        _wait(root, lambda: False, seconds=0.8)
        assert panel._probe_for is None
        assert panel._probe_busy is False
        assert panel._edit_lbl.cget("text") == ""
        assert panel._can_read
    finally:
        root.destroy()


def test_the_probe_answers_on_a_worker_and_the_row_follows(tmp_path):
    """The whole stat is off the Tk thread - an arbitrary typed path can be
    a share that blocks os.stat for tens of seconds - so this drives the
    real debounce and waits for the answer to come back through the queue."""
    root, panel = _panel()
    try:
        card = _card_file(tmp_path)
        panel._out_var.set(card)
        _wait(root, lambda: panel._probe_for == card, seconds=10)
        assert panel._probe_facts["kind"] == "file"
        assert panel._probe_busy is False
        assert "is on disk" in panel._edit_lbl.cget("text")
        assert panel._can_read
        # ...and a path with nothing at it comes back the other way
        fresh = str(tmp_path / "multi" / "not-yet.multi.raw")
        panel._out_var.set(fresh)
        _wait(root, lambda: panel._probe_for == fresh, seconds=10)
        assert panel._probe_facts["kind"] == "missing"
        assert "will write a new card" in panel._edit_lbl.cget("text")
        assert not panel._can_read
    finally:
        root.destroy()


# --------------------------------------------------------------------------
# the tab comes back as it was left
# --------------------------------------------------------------------------

def test_the_form_survives_a_restart(tmp_path):
    root, panel = _panel()
    a, b = _images(tmp_path, 2)
    out = str(tmp_path / "multi" / "card.multi.raw")
    try:
        panel.add_image(a)
        panel.add_image(b)
        panel._tree.selection_set("1")
        root.update()
        panel._ed_title.set("Second")
        panel._ed_anim.set("auto")
        panel._timeout_var.set("8")
        panel._volume_var.set("70")
        panel._bypass_var.set(False)
        panel._out_var.set(out)
        doc = panel.state()
        assert doc["v"] == multiboot_tab.STATE_VERSION
        # THE SAME ImageRow the builders read, dumped - not a parallel copy
        assert doc["images"][1]["title"] == "Second"
        assert doc["images"][1]["anim"] == "auto"
        # ...and nothing transient or derived
        for gone in ("busy", "frames", "sound", "loaded_card", "loaded_form"):
            assert gone not in doc
    finally:
        root.destroy()

    root, panel = _panel()
    try:
        assert panel.restore_state(doc) is True
        assert panel._out_var.get() == out
        assert [r.title for r in panel._rows] == [suggest_title(a)[0],
                                                  "Second"]
        assert panel._rows[1].anim == "auto"
        assert panel._timeout_var.get() == "8"
        assert panel._volume_var.get() == "70"
        assert panel._bypass_var.get() is False
        assert panel.form().out == out
        # OUT OF EDITING MODE, on purpose: the baseline is not restored, so
        # Apply cannot inject a diff computed against a stale one.  One
        # click on the verb earns editing mode back honestly.
        assert panel._loaded_card == "" and panel._loaded_form is None
        assert str(panel._apply_btn.cget("state")) == "disabled"
        # THE SOUND STAYS OFF.  This app is used in the room with a machine
        # that is running; "he left it on once" is not a reason to make a
        # noise on the next launch.
        assert "sound" not in doc
        assert panel._sound_var.get() is False
        assert panel._audio is None
        # a restored path is the USER'S path: adding the first image of the
        # next card must not silently overwrite it
        assert panel._out_auto_value == ""
    finally:
        root.destroy()


def test_a_restore_starts_no_tool(tmp_path, monkeypatch):
    """The rig is a mutex between David's sessions: a startup that ran an
    inspect by itself could collide with a live one."""
    monkeypatch.setattr(multiboot_tab.subprocess, "Popen",
                        lambda *a, **kw: pytest.fail("a tool was started"))
    root, panel = _panel()
    try:
        card = _card_file(tmp_path)
        assert panel.restore_state(
            {"v": 1, "card": card,
             "images": [{"path": card, "title": "A"}],
             "menu": {"volume": 40}}) is True
        _wait(root, lambda: False, seconds=0.8)
        assert panel._loaded_card == ""
        assert panel._busy is False
        assert panel._volume_var.get() == "40"
    finally:
        root.destroy()


def test_a_half_written_document_leaves_the_tab_empty_not_broken(tmp_path):
    """...and EMPTY means emptied.  The panel is filled first on purpose:
    an early return read as "empty" on a fresh tab and as "keep the last
    project's card and image list" on a live one, which is the leak the
    rail above exists to prevent."""
    root, panel = _panel()
    try:
        a, b = _images(tmp_path, 2)
        full = {"v": 1, "card": str(tmp_path / "multi" / "card.multi.raw"),
                "images": [{"path": a, "title": "A"}, {"path": b}],
                "menu": {"volume": 70}}
        for junk in ({}, None, "not a dict", {"v": 0}, {"images": []},
                     {"v": "not a number"}):
            assert panel.restore_state(full) is True
            assert panel._rows and panel._out_var.get()
            assert panel.restore_state(junk) is False
            assert panel._rows == [] and panel._out_var.get() == ""
            # the menu came back to its defaults with the rest of the form
            assert panel._volume_var.get() == "50"
    finally:
        root.destroy()


def test_a_media_dir_that_belongs_to_another_card_is_dropped(tmp_path):
    """media-<stem> is per card.  Restoring one for a DIFFERENT card would
    send a build's prepare into the wrong extract directory."""
    root, panel = _panel()
    try:
        card = str(tmp_path / "multi" / "card.multi.raw")
        mine = loaded_media_dir(card)
        theirs = loaded_media_dir(str(tmp_path / "multi" / "other.raw"))
        assert panel.restore_state({"v": 1, "card": card, "images": [],
                                    "media_dir": theirs}) is True
        assert panel._media_override == ""
        assert panel.restore_state({"v": 1, "card": card, "images": [],
                                    "media_dir": mine}) is True
        assert panel._media_override == mine
    finally:
        root.destroy()


def test_a_restore_leaves_the_previous_projects_card_behind(tmp_path):
    """SWITCHING PROJECTS, not restarting: the same call arrives at a panel
    that is already in editing mode.  A restore is the THIRD way into this
    state and has to leave the tab somewhere load_inspect or new_card could
    also have left it - so it clears what they clear.  Leaving the last
    project's baseline standing had the tab naming a card THIS project has
    never heard of, with the media dir replaced underneath it."""
    root, panel, card, media = _loaded(tmp_path)
    try:
        assert panel._on_loaded_path() is True
        panel._plan_step("plan", 0, "image: 1 sectors = 2 bytes\n"
                                    "  fits Stern 16G image size 3: YES "
                                    "(spare 4)\n")
        ppm = _ppm(tmp_path / "f.ppm")
        panel._pv_cache[(preview_fingerprint(panel.form()), 0, 0)] = ppm
        panel.load_frame(ppm, 0, 0, 1)
        assert panel._pv_shown is not None and panel._pv_photo is not None
        other = _card_file(tmp_path, "b.multi.raw")
        assert panel.restore_state({"v": 1, "card": other, "images": [],
                                    "menu": {}}) is True
        root.update()
        assert panel._loaded_card == ""
        assert panel._loaded_form is None and panel._loaded_info is None
        assert panel._armed is False
        assert panel._alarm_text == ""
        # ...and nothing the last form drew is still on screen or claimed
        assert panel._pv_cache == {} and panel._pv_shown is None
        assert panel._pv_ready is None and panel._plan_text == ""
        # ...so there is no way back to it - the row says nothing about a
        # card being edited, and Apply refuses even past the button.
        assert "editing" not in panel._edit_lbl.cget("text")
        assert panel._out_var.get() == other
        assert panel.apply_to_card() is False
    finally:
        root.destroy()


def test_a_restore_draws_nothing_either(tmp_path, monkeypatch):
    """'NO TOOL RUNS' has to hold with the auto-preview remembered ON, which
    is its default: restore_state used to end in schedule_preview(), so a
    launch was a `make` of the selector and a selectmedia prepare ~350 ms
    in - and the rig is a mutex between David's sessions."""
    monkeypatch.setattr(multiboot_tab.subprocess, "Popen",
                        lambda *a, **kw: pytest.fail("a tool was started"))
    root, panel = _panel(auto=True, plan=True)
    try:
        a, b = _images(tmp_path, 2)
        assert panel.restore_state(
            {"v": 1, "card": str(tmp_path / "multi" / "card.multi.raw"),
             "images": [{"path": a, "title": "A"}, {"path": b, "title": "B"}],
             "auto_preview": True}) is True
        # the switch came back ON, and still nothing is armed or running
        assert panel._auto_preview.get() is True
        assert panel._pv_debounce_job is None
        assert panel._plan_job is None
        _wait(root, lambda: False, seconds=1.4)
        assert panel._pv_busy is False and panel._busy is False
        # ...and the picture never claims one is on its way: the hold is
        # what the caption's own wording is asked about.
        caption = panel._pv_status.cget("text")
        assert "has not been drawn yet" in caption
        assert "drawing it" not in caption
        # the headline names no button either: the restored path is usually
        # the card that was being EDITED, and 'then Build & verify' pointed
        # a ~7 GB overwrite at it.
        assert "Build & verify" not in panel._hint.cget("text")
        assert "came back from last time" in panel._hint.cget("text")
    finally:
        root.destroy()


def test_a_restored_media_dir_does_not_outlive_the_card_it_belongs_to(
        tmp_path):
    """media-<stem> is per card.  A restore brings one back with the card it
    was saved beside; the moment the path box names something else it is the
    WRONG directory, and there is no loaded card on screen to explain it."""
    root, panel = _panel()
    try:
        card = _card_file(tmp_path)
        mine = loaded_media_dir(card)
        assert panel.restore_state({"v": 1, "card": card, "images": [],
                                    "media_dir": mine}) is True
        assert panel.media_dir() == mine
        other = str(tmp_path / "multi" / "b.multi.raw")
        panel._out_var.set(other)
        assert panel._media_override == ""
        assert panel.media_dir() == multiboot_tab.media_dir_for(other)
    finally:
        root.destroy()


def test_a_loaded_cards_media_dir_survives_the_path_straying(tmp_path):
    """The other half of the rule: while a card IS loaded, nothing is thrown
    away by straying - the extract is still that card's, and typing the path
    back has to find it."""
    root, panel, card, media = _loaded(tmp_path)
    try:
        panel._out_var.set(str(tmp_path / "multi" / "copy.multi.raw"))
        assert panel._media_override == media
        panel._out_var.set(card)
        assert panel.media_dir() == media
    finally:
        root.destroy()


def test_a_name_the_file_system_refuses_is_not_an_unplugged_drive(tmp_path):
    """Windows raises the same class of OSError for a '?' in a file name as
    it does for a share that is down (errno 22 / winerror 123), so the row
    told David to plug in a drive that was plainly sitting there."""
    for bad in ("card?.raw", "card*.raw", "card|x.raw", "c" * 300 + ".raw"):
        facts = multiboot_tab.probe_card_path(str(tmp_path / bad))
        assert facts["kind"] == "badname", bad
    # ...and it reads as what it is, in the error colour, with no verb
    kind, text, tone, on = _state(str(tmp_path / "x?.raw"),
                                  kind="badname")
    assert (kind, tone, on) == ("badname", "error", False)
    assert "not a name" in text and "plug" not in text
    # a path that really is missing is still missing
    assert multiboot_tab.probe_card_path(
        str(tmp_path / "nope.raw"))["kind"] == "missing"


def test_the_probe_asks_again_when_the_answer_can_have_changed(tmp_path):
    """A stat is a fact with a shelf life.  The row kept its FIRST answer for
    ever: a card the build had just written went on reading 'will write a new
    card' with the verb grey, and a drive plugged in after the path was typed
    stayed 'not there right now' - the only way out of either was to alter
    the text."""
    root, panel = _panel()
    try:
        card = str(tmp_path / "multi" / "card.multi.raw")
        os.makedirs(os.path.dirname(card), exist_ok=True)
        panel._out_var.set(card)
        _wait(root, lambda: panel._probe_for == card, seconds=10)
        assert panel._probe_facts["kind"] == "missing"
        assert not panel._can_read
        # what a build does, without a build
        open(card, "wb").close()
        # 1. a run finishing re-asks
        panel._set_busy(True)
        panel._set_busy(False)
        _wait(root, lambda: panel._probe_facts.get("kind") == "file",
              seconds=10)
        assert "is on disk" in panel._edit_lbl.cget("text")
        assert panel._can_read
        # 2. so does the tab coming back on screen, and the box being
        #    clicked into - the two things a person does after plugging the
        #    drive in
        os.remove(card)
        panel._refresh_facts()
        _wait(root, lambda: panel._probe_facts.get("kind") == "missing",
              seconds=10)
        assert not panel._can_read
        # ...and an unreachable verdict does not latch either
        panel._probe_done(card, {"kind": "unreachable", "root": "Z:\\"})
        assert "not there right now" in panel._edit_lbl.cget("text")
        open(card, "wb").close()
        panel._refresh_facts()
        _wait(root, lambda: panel._probe_facts.get("kind") == "file",
              seconds=10)
        assert "is on disk" in panel._edit_lbl.cget("text")
    finally:
        root.destroy()


def test_a_dead_drive_is_answered_before_anything_stats_it(tmp_path,
                                                           monkeypatch):
    """The guard sat AFTER form(), and form() -> media_dir() -> isfile
    (media.json) is itself the blocking stat it was written to prevent - so
    a typing pause on an unreachable path still froze the Tk thread."""
    root, panel = _panel(auto=True)
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        out = "//deadhost/share/cards/card.multi.raw"
        panel._out_var.set(out)
        panel._probe_done(out, {"kind": "unreachable",
                                "root": "//deadhost/share"})
        stat_calls = []
        monkeypatch.setattr(multiboot_tab.os.path, "isfile",
                            lambda p: stat_calls.append(p) or False)
        assert panel._auto_render() is False
        assert stat_calls == []
        assert "is not there right now" in panel._pv_status.cget("text")
    finally:
        root.destroy()


def test_browse_asks_before_it_touches_the_box(tmp_path, monkeypatch):
    """'No, keep my edits' used to do half the job anyway: the read was
    skipped, but the box already named the other card, so the tab left
    editing mode and greyed the only button that could write them."""
    root, panel, card, _media = _loaded(tmp_path)
    other = _card_file(tmp_path, "second.multi.raw")
    reads = []
    monkeypatch.setattr(panel, "load_card", lambda p: reads.append(p))
    monkeypatch.setattr(multiboot_tab.filedialog, "asksaveasfilename",
                        lambda **kw: other)
    monkeypatch.setattr(multiboot_tab.messagebox, "askyesno",
                        lambda *a, **kw: False)
    try:
        panel._timeout_var.set("8")             # something to lose
        assert panel._browse_card() is False
        assert reads == []
        assert panel._out_var.get() == card     # ...and the box is untouched
        assert str(panel._apply_btn.cget("state")) == "normal"
        # ...and 'yes' does both, in that order
        monkeypatch.setattr(multiboot_tab.messagebox, "askyesno",
                            lambda *a, **kw: True)
        panel._browse_card()
        assert reads == [other] and panel._out_var.get() == other
    finally:
        root.destroy()


def test_a_refused_read_leaves_no_directory_behind(tmp_path, monkeypatch):
    """Browse… reads any existing card you pick and the row cannot tell a
    multi card from a stock one (a stat is all probe_card_path may do), so a
    mis-pick is ordinary - and it used to leave an empty media-<stem>/ next
    to the file for every one of them."""
    root, panel = _panel()
    try:
        card = _card_file(tmp_path, "stock.raw")
        media = loaded_media_dir(card)
        runs = []

        def fake(cmds, on_step=None, on_done=None, quiet=(), preview=False):
            runs.append(cmds)
            on_done(2, "inspect", {"inspect": "refusing: not a multi card"})
            return True
        panel._run_commands = fake
        assert panel.load_card(card) is True
        assert runs and "Cannot read" in panel._hint.cget("text")
        assert not os.path.isdir(media)
        # ...but a directory that was already there is not ours to remove
        os.makedirs(media)
        panel.load_card(card)
        assert os.path.isdir(media)
    finally:
        root.destroy()


def test_an_overwrite_says_what_it_would_destroy(tmp_path, monkeypatch):
    """A restart puts the path box back on the card that was being EDITED
    while deliberately not restoring the baseline, so 'a loaded card is not
    an output' cannot fire and Build & verify is the green button on a
    finished card.  A bare 'Rebuild over it?' is not enough to stop that."""
    root, panel = _panel()
    asked = {}
    monkeypatch.setattr(multiboot_tab.messagebox, "askyesno",
                        lambda title, message: asked.update(
                            title=title, message=message) or False)
    calls = _recorder(panel)
    try:
        for p in _images(tmp_path, 2):
            panel.add_image(p)
        out = _card_file(tmp_path, "already.multi.raw")
        panel._out_var.set(out)
        panel._build_card()
        assert calls == []                      # refused, nothing ran
        assert "Overwrite" in asked["title"]
        assert out in asked["message"]
        assert "GB, written " in asked["message"]
        assert "every image is copied again" in asked["message"]
    finally:
        root.destroy()


def test_the_consequence_line_survives_a_card_with_no_baseline(tmp_path):
    """card_path_state decides 'loaded' from _loaded_card and the path text
    alone and has never seen _loaded_form, so the pair reached .bypass on
    None.  Narrow today, and one keystroke away from not being."""
    root, panel = _panel()
    try:
        card = _card_file(tmp_path)
        panel._loaded_card = card
        panel._loaded_form = None
        panel._out_var.set(card)
        panel._update_edit_status()             # no AttributeError
        assert "Editing card.multi.raw" in panel._edit_lbl.cget("text")
    finally:
        root.destroy()


def test_two_spellings_of_the_loaded_card_are_one_card(tmp_path):
    """The row compares the text (no disk, every keystroke) and every GATE
    compares realpaths - so a junction spelling of the loaded card was
    'strayed' to the row, which greyed Apply, while _build_card's own _norm
    saw the loaded card and refused the build.  Neither writing button could
    be used."""
    root, panel, card, _media = _loaded(tmp_path)
    try:
        link = str(tmp_path / "multi" / "link.multi.raw")
        # the probe is what resolves it, on the worker: hand the row its
        # answer the way _probe_done does
        panel._out_var.set(link)
        panel._probe_done(link, {"kind": "file", "loaded": False})
        assert "no longer names" in panel._edit_lbl.cget("text")
        assert str(panel._apply_btn.cget("state")) == "disabled"
        panel._probe_done(link, {"kind": "file", "loaded": True})
        assert "Editing card.multi.raw" in panel._edit_lbl.cget("text")
        assert str(panel._apply_btn.cget("state")) == "normal"
        # ...and the worker really does answer that question
        facts = multiboot_tab.probe_card_path(card, card)
        assert facts["loaded"] is True
        assert multiboot_tab.probe_card_path(card, link)["loaded"] is False
    finally:
        root.destroy()


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


def test_switching_to_an_empty_project_clears_the_tab_on_screen(tmp_path):
    """The rule above, driven end to end into a REAL panel.  The stub above
    only proves the app handed {} down; what David sees is the row, and an
    empty answer that stopped at the panel's door left it naming the card of
    a project he has closed with Build & verify aimed at it - and the next
    quit wrote that card into the NEW project's anchor."""
    root, panel = _panel()
    try:
        a, b = _images(tmp_path, 2)
        card_a = str(tmp_path / "multi" / "a.multi.raw")
        assert panel.restore_state(
            {"v": 1, "card": card_a,
             "images": [{"path": a, "title": "STERN 1.59.0"},
                        {"path": b, "title": "TMNT 1987"}]}) is True
        proj = tmp_path / "empty-project"
        proj.mkdir()
        _multi_anchor(proj, multiboot={})
        _multi_restore(proj, {"multiboot_state": {"v": 1, "card": card_a}},
                       panel=panel)
        assert panel._rows == []
        assert panel._out_var.get() == ""
        # ...so a quit cannot copy the closed project's card into this one
        from pinball_decryptor.app import App
        stub = SimpleNamespace(window=SimpleNamespace(_multiboot_panel=panel))
        assert App.multiboot_state(stub)["card"] == ""
    finally:
        root.destroy()


def test_an_unreadable_anchor_clears_the_tab_on_screen_too(tmp_path):
    """The truncated-anchor branch hands the panel {} for the same reason,
    and it has to land the same way: a NAS hiccup must not leave the last
    project's image list on a different project's tab."""
    from pinball_decryptor.core import project_file
    root, panel = _panel()
    try:
        a, = _images(tmp_path, 1)
        assert panel.restore_state(
            {"v": 1, "card": str(tmp_path / "multi" / "a.multi.raw"),
             "images": [{"path": a, "title": "STERN 1.59.0"}]}) is True
        proj = tmp_path / "corrupt-anchor"
        proj.mkdir()
        with open(project_file.anchor_path(str(proj)), "w",
                  encoding="utf-8") as f:
            f.write("{not json")
        _multi_restore(proj, {"multiboot_state": {"v": 1, "card": "D:/g.raw"}},
                       panel=panel)
        assert panel._rows == [] and panel._out_var.get() == ""
    finally:
        root.destroy()


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
        _settings={}, _project_path=str(a),
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
        _save_settings=lambda: None)
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
        _last_normal_geometry=None,
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


def test_return_in_the_path_box_reads_the_card_there(tmp_path, monkeypatch):
    """The verb button is gone, so <Return> is how a TYPED or pasted path is
    read.  It is a deliberate act, like picking a file - but it is still
    never a keystroke on the way past: a path with nothing at it does
    nothing at all, because typing 'x.raw.bak' goes through 'x.raw'."""
    monkeypatch.setattr(multiboot_tab.messagebox, "askyesno",
                        lambda *a, **kw: True)
    root, panel = _panel()
    read = []
    panel.load_card = lambda p, **kw: read.append(p)
    try:
        # nothing typed: Return is silent, not an error
        panel._out_var.set("")
        panel._path_committed()
        assert read == []
        # a path with nothing at it: still silent - this is the way to a new
        # card, and a card that is not there cannot be read
        missing = str(tmp_path / "multi" / "not-yet.raw")
        panel._out_var.set(missing)
        panel._probe_done(missing, {"kind": "missing", "parent": True})
        panel._path_committed()
        assert read == []
        # a card that IS there: read it
        card = _card_file(tmp_path)
        panel._out_var.set(card)
        panel._probe_done(card, {"kind": "file"})
        assert panel._can_read
        panel._path_committed()
        assert read == [card]
    finally:
        root.destroy()


def test_return_before_the_probe_has_answered_says_so(tmp_path, monkeypatch):
    """The probe answers on a worker so an unplugged drive cannot freeze the
    tab, and Return can beat it.  Silence would read as a key that does
    nothing."""
    monkeypatch.setattr(multiboot_tab.messagebox, "askyesno",
                        lambda *a, **kw: True)
    root, panel = _panel()
    read = []
    panel.load_card = lambda p, **kw: read.append(p)
    try:
        card = _card_file(tmp_path)
        panel._out_var.set(card)
        panel._probe_done(card, {"kind": "looking"})
        panel._path_committed()
        assert read == []
        assert "press Return again" in panel._hint.cget("text")
    finally:
        root.destroy()


def test_a_restored_card_is_read_when_the_tab_is_opened(
        tmp_path, monkeypatch):
    """The restore runs no tools - the app must not start a WSL run merely
    by launching, and the rig is a mutex between David's sessions.  So the
    card comes back as a PATH, and opening the tab is the deliberate act
    that reads it.  Once: a card that will not read is not re-read on every
    visit."""
    monkeypatch.setattr(multiboot_tab.messagebox, "askyesno",
                        lambda *a, **kw: pytest.fail(
                            "a restored card is not an unsaved change"))
    root, panel = _panel()
    read = []
    panel.load_card = lambda p, **kw: read.append(p) or True
    try:
        card = _card_file(tmp_path)
        # nothing restored: opening the tab reads nothing
        assert panel.on_shown() is False
        assert read == []
        # a restore with a card at the path arms it, and the tab reads it
        panel.restore_state({"v": 1, "card": card,
                             "images": [{"path": card}], "menu": {}})
        assert read == []                       # ...not at restore time
        assert panel._pending_read is True
        panel.on_shown()
        assert read == [card]
        # ...and only once, however many times the tab is opened
        panel.on_shown()
        panel.on_shown()
        assert read == [card]
    finally:
        root.destroy()


def test_a_restored_card_that_is_gone_is_not_read(tmp_path, monkeypatch):
    """A .raw that has moved, or a drive that is not mounted, must not turn
    the first visit to the tab into a failed tool run."""
    monkeypatch.setattr(multiboot_tab.messagebox, "askyesno",
                        lambda *a, **kw: True)
    root, panel = _panel()
    read = []
    panel.load_card = lambda p, **kw: read.append(p) or True
    try:
        gone = str(tmp_path / "multi" / "gone.raw")
        panel.restore_state({"v": 1, "card": gone, "images": [], "menu": {}})
        assert panel.on_shown() is False
        assert read == []
        # ...and it does not keep asking on every visit either
        assert panel._pending_read is False
    finally:
        root.destroy()


def test_what_the_tab_says_sits_above_the_images_it_talks_about(tmp_path):
    """An empty tab's own words are "add the images below - the path fills
    itself in from the first one", and they used to be printed UNDERNEATH
    the images they pointed at (David: "this text should be above the table
    of images").  Guidance that names a direction has to be on the right
    side of the thing it names."""
    root, panel = _panel()
    try:
        order = [str(w) for w in panel._outer.pack_slaves()]
        assert order.index(str(panel._status_wrap)) <             order.index(str(panel._table_box))
        # ...and the sentence really does point downwards from there
        assert "below" in panel._edit_lbl.cget("text")
        # the actions stay at the foot, after the table
        assert order.index(str(panel._table_box)) <             order.index(str(panel._action_row))
    finally:
        root.destroy()
