"""Tests for :mod:`pinball_decryptor.plugins.stern.mode_assets` (item 127).

A project's modes build into the game tree's own layout from the STOCK scenes: every
screen added to the HUD scene in one pass, every clip into the video bank with its file
at the path the bank names, and one runtime mode file per slot. The encoded clips are
checked for what the machine plays (H.264 Constrained Baseline, 4:2:0, silent, the
bank's size). Tests that need ffmpeg or the stock scenes skip without them.
Desk only: no card, no emulator, no rig.
"""

import hashlib
import json
import os
import struct
import subprocess

import numpy as np
import pytest

from pinball_decryptor.core import audio
from pinball_decryptor.plugins.stern import mode_assets as MA
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import video_bank as VB

CORPUS = r"C:\tmp\radium_scene_re\godzilla_pro_1_15"
HUD = os.path.join(CORPUS, "auto_loaded_%s.radium" % MP.GODZILLA_PRO_1_15.hud_scene)


def _ffmpeg():
    p = audio.find_ffmpeg()
    if not p:
        pytest.skip("no ffmpeg")
    return p


def _probe(path):
    probe = audio.find_ffprobe()
    if not probe:
        pytest.skip("no ffprobe")
    r = subprocess.run([probe, "-v", "error", "-show_streams", "-count_frames", "-of", "json", path],
                       capture_output=True, text=True)
    return json.loads(r.stdout)["streams"]


def _synthetic_bank(n=3):
    """A bank laid out like the stock one (the same builder test_stern_video_bank uses)."""
    from tests.test_stern_video_bank import synthetic
    return synthetic(tuple("Clip%d" % i for i in range(n)))


# ---- art and frames ---------------------------------------------------------------------
def test_panel_art_is_rgba_and_bc3_sized():
    a = MA.panel_art("KAIJU RUSH")
    assert a.shape == (160, 640, 4) and a.dtype == np.uint8
    assert a[80, 20, 3] > 0 and a[0, 0, 3] == 0          # a panel inside, clear corners


def test_load_art_pads_to_a_multiple_of_four(tmp_path):
    from PIL import Image
    p = tmp_path / "art.png"
    Image.new("RGBA", (101, 50), (255, 0, 0, 255)).save(p)
    a = MA.load_art(str(p))
    assert a.shape == (52, 104, 4) and a[0, 0, 0] == 255 and a[51, 103, 3] == 0


def test_title_frames_move():
    frames = list(MA.title_frames("GO", 160, 96, 1.0, "#146e28", "#ffe600"))
    assert len(frames) == 30 and frames[0].shape == (96, 160, 3)
    # the bar enters and leaves off-screen, so compare the ends against the middle
    assert not np.array_equal(frames[0], frames[15])
    assert not np.array_equal(frames[10], frames[20])


# ---- encoding ---------------------------------------------------------------------------
def test_render_title_clip_encodes_what_the_machine_plays(tmp_path):
    ff = _ffmpeg()
    out = str(tmp_path / "clip.asset")
    MA.render_title_clip(out, "KAIJU RUSH", 320, 180, 1.0, "#146e28", "#ffe600", ff)
    (v,) = _probe(out)
    assert v["codec_name"] == "h264" and v["profile"] == "Constrained Baseline"
    assert (v["width"], v["height"], v["pix_fmt"]) == (320, 180, "yuv420p")
    assert int(v["nb_read_frames"]) == 30


def test_convert_clip_letterboxes_to_the_bank_size_and_drops_audio(tmp_path):
    ff = _ffmpeg()
    src = str(tmp_path / "src.mp4")
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=200x200:rate=25:duration=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-shortest", src],
                   check=True, capture_output=True)
    out = str(tmp_path / "out.asset")
    MA.convert_clip(src, out, 320, 180, ff)
    streams = _probe(out)
    assert [s["codec_type"] for s in streams] == ["video"]
    assert (streams[0]["width"], streams[0]["height"]) == (320, 180)


# ---- the whole build --------------------------------------------------------------------
def _mode(project, name, **kw):
    slug, spec = MP.new_mode(project, name)
    for k, v in kw.items():
        setattr(spec, k, v)
    MP.save(project, slug, spec)
    return slug


def test_build_two_modes_with_clips_into_the_bank(tmp_path):
    ff = _ffmpeg()
    project, out = str(tmp_path / "proj"), str(tmp_path / "out")
    _mode(project, "Alpha", screen=False, clip="title", clip_seconds=1.0)
    _mode(project, "Beta", screen=False, clip="title", clip_seconds=1.0, clip_when="end")
    stock = _synthetic_bank(3)
    res = MA.build(project, b"not needed without screens", stock, out, ffmpeg=ff)
    bank_rel = "assets/lcd/auto_loaded/%s" % MP.GODZILLA_PRO_1_15.bank_scene
    assert res.new_files == [bank_rel + "/scene.assets/2.asset/3.asset",
                             bank_rel + "/scene.assets/2.asset/4.asset"]
    bank = VB.parse(open(os.path.join(out, *(bank_rel + "/scene.radium").split("/")), "rb").read())
    by_name = {c.name: c for c in bank.library.entries}
    for slug, path in (("alpha", "2.asset/3.asset"), ("beta", "2.asset/4.asset")):
        clip = by_name[MP.asset_names(slug)["clip"]]
        assert clip.path == path
        assert clip.size == os.path.getsize(os.path.join(out, *(bank_rel + "/scene.assets/" + path).split("/")))
    assert res.mode_files == ["mode.cfg", "mode1.cfg"]
    beta = open(os.path.join(out, "padmode", "mode1.cfg"), encoding="utf-8").read()
    assert "clip_end       PadMode_beta_Clip" in beta and "name           Beta" in beta
    assert res.slots == [(0, "alpha", "Alpha"), (1, "beta", "Beta")]


def test_build_refuses_naming_every_bad_mode(tmp_path):
    project = str(tmp_path / "proj")
    _mode(project, "Good", screen=False)
    _mode(project, "Bad", screen=False, seconds=0, start_count=0)
    with pytest.raises(MA.ModeAssetError) as e:
        MA.build(project, b"", _synthetic_bank(), str(tmp_path / "out"))
    assert "Bad:" in str(e.value) and "at least a second" in str(e.value) and "Good:" not in str(e.value)


def test_build_with_no_clip_needs_no_ffmpeg_and_writes_no_bank(tmp_path):
    project, out = str(tmp_path / "proj"), str(tmp_path / "out")
    _mode(project, "Quiet", screen=False, clip="none")
    res = MA.build(project, b"", _synthetic_bank(), out, ffmpeg=None)
    assert res.files == [] and res.mode_files == ["mode.cfg"]


def test_build_screens_on_the_stock_hud(tmp_path):
    if not os.path.exists(HUD):
        pytest.skip("stock HUD scene not present")
    stock = open(HUD, "rb").read()
    project, out = str(tmp_path / "proj"), str(tmp_path / "out")
    _mode(project, "Alpha", clip="none")
    _mode(project, "Beta", clip="none", panel_color="#202080")
    res = MA.build(project, stock, b"", out)
    rel = "assets/lcd/auto_loaded/%s/scene.radium" % MP.GODZILLA_PRO_1_15.hud_scene
    assert res.files == [rel]
    hud = open(os.path.join(out, *rel.split("/")), "rb").read()
    assert struct.unpack_from("<Q", hud, 0x0E16E1)[0] == 5
    for slug in ("alpha", "beta"):
        assert MP.asset_names(slug)["screen_node"].encode() in hud
    assert hashlib.md5(stock).hexdigest() == "f9daed5a19aafc807bf9eb3c2def6c27"   # input untouched


def test_build_adds_a_second_clip_for_clip_both(tmp_path):
    """Item 141: a title-card second clip joins the bank as PadMode_<slug>_Clip2, after the
    first; "same" adds nothing and plays the first clip at both ends."""
    ff = _ffmpeg()
    project, out = str(tmp_path / "proj"), str(tmp_path / "out")
    _mode(project, "Alpha", screen=False, clip="title", clip_seconds=1.0,
          clip_both={"clip": "title", "title": "ALPHA OVER", "seconds": 1})
    _mode(project, "Beta", screen=False, clip="title", clip_seconds=1.0, clip_both={"clip": "same"})
    res = MA.build(project, b"", _synthetic_bank(3), out, ffmpeg=ff)
    bank_rel = "assets/lcd/auto_loaded/%s" % MP.GODZILLA_PRO_1_15.bank_scene
    assert res.new_files == [bank_rel + "/scene.assets/2.asset/%d.asset" % i for i in (3, 4, 5)]
    bank = VB.parse(open(os.path.join(out, *(bank_rel + "/scene.radium").split("/")), "rb").read())
    by_name = {c.name: c.path for c in bank.library.entries}
    assert by_name["PadMode_alpha_Clip"] == "2.asset/3.asset"
    assert by_name["PadMode_alpha_Clip2"] == "2.asset/4.asset"
    assert by_name["PadMode_beta_Clip"] == "2.asset/5.asset" and "PadMode_beta_Clip2" not in by_name
    alpha = open(os.path.join(out, "padmode", "mode.cfg"), encoding="utf-8").read()
    assert "clip_start     PadMode_alpha_Clip\n" in alpha and "clip_end       PadMode_alpha_Clip2\n" in alpha


def test_grafted_clips_go_in_the_hud_beside_the_screens(tmp_path, monkeypatch):
    """item 164: a title that draws no bank in play names its HUD as the bank; every clip goes in a
    Video grafted into the HUD, its file at <hud>/scene.assets/<n>.asset, in one pass with the screens."""
    import dataclasses
    from pinball_decryptor.plugins.stern import scene_write as SW
    from tests.test_stern_scene_write import _fake_hud, _art
    hud, _p, _ = _fake_hud(monkeypatch)
    project, out = str(tmp_path / "proj"), str(tmp_path / "out")
    alpha = _mode(project, "Alpha", screen=False, clip="title", clip_seconds=1.0)
    found, _broken = MP.list_modes(project)
    prof = dataclasses.replace(MP.GODZILLA_PRO_1_15, bank_scene=MP.GODZILLA_PRO_1_15.hud_scene)
    sizes = []

    def encode(job, path, ffmpeg):
        sizes.append((job.w, job.h))
        with open(path, "wb") as f:
            f.write(b"\0" * 1234)
    monkeypatch.setattr(MA, "_encode_clip", encode)
    monkeypatch.setattr(MA, "make_clips", lambda jobs, ffmpeg, progress=None: ({}, None))
    result = MA.ModeBuild(out_dir=out)
    written = {}

    def write(rel, data):
        written[rel] = data
        result.files.append(rel)
    MA._build_grafted(project, prof, hud, [dict(name="S", art_rgba=_art(), words="HI")], found, [], out,
                      "ffmpeg", result, write)
    rel = prof.lcd("hud") + "/scene.assets/1.asset"
    assert result.new_files == [rel] and os.path.getsize(os.path.join(out, *rel.split("/"))) == 1234
    assert sizes == [(1360, 768)]                                    # the HUD's stage
    new = written[prof.lcd("hud") + "/scene.radium"]
    assert SW.string(MP.asset_names(alpha)["clip"]) + struct.pack("<I", SW.FLAG | (_p.first_free_id + 7 + 5)) in new
    assert SW.string("PadMode_Clips") in new and SW.string("S") in new


# ---- PAD-314 (Ales's Metallica picture): where a mode's screen goes on the glass ---------------------------
def test_the_generated_panel_sits_where_it_always_has_and_a_big_picture_stays_on_the_glass():
    import numpy as np
    from pinball_decryptor.plugins.stern import mode_assets as MA
    panel = np.zeros((160, 640, 4), dtype=np.uint8)
    assert MA.screen_place(panel) == (360.0, 200.0, None)
    # a picture capped by load_art (1360x768 at most): from the top-left corner, words on its bottom band
    big = np.zeros((756, 1360, 4), dtype=np.uint8)
    assert MA.screen_place(big) == (0.0, 0.0, (20.0, 742.0))
    # a middling picture is centred on the panel's band, words under it as before
    mid = np.zeros((300, 800, 4), dtype=np.uint8)
    assert MA.screen_place(mid) == (280.0, 130.0, None)
    # a code mode's words on its own band are kept
    assert MA.screen_place(big, (20.0, 700.0)) == (0.0, 0.0, (20.0, 700.0))


def test_the_words_band_darkens_only_the_bottom_of_a_picture():
    """Ales (PAD-314 thread): with a picture for the screen the "+1,000,000" words never showed - they
    were 50 px under a picture that already reached the bottom of the glass. They go on the picture's
    bottom band now, darkened so they read over any picture; the top is untouched."""
    import numpy as np
    from pinball_decryptor.plugins.stern import mode_assets as MA
    art = np.full((400, 200, 4), 200, dtype=np.uint8)
    out = MA.band_art(art)
    assert out.shape == art.shape and out is not art
    assert (out[:328] == 200).all()                       # above the 72 px band: as it was
    assert (out[-1, :, :3] < 40).all() and (out[-1, :, 3] >= 217).all()   # the bottom row: 85% black
    assert (out[328 + 10, :, :3] < out[328 + 2, :, :3]).all()             # darker on the way down
    assert (art == 200).all()                              # the mode's picture itself is untouched


# ---- PAD-323: a screen laid out in the Scenes editor -------------------------------------------
def test_a_screen_layout_overrides_only_what_it_gives():
    """mode.json ``screen_layout`` (the Scenes editor's): each key it gives replaces the automatic
    placement; a key it does not give, or none at all, leaves the screen as it was placed."""
    art = MA.panel_art("ALPHA")
    auto = dict(name="S", art_rgba=art, words="W", x=360.0, y=200.0, words_at=None)
    assert MA.with_layout(auto, {}) is auto and MA.with_layout(auto, None) is auto
    got = MA.with_layout(auto, {"x": 12, "y": 30.5, "scale": 0.5, "words_x": 4, "words_y": 90,
                                "words_scale": 2, "order": 0})
    assert (got["x"], got["y"], got["scale"], got["words_at"], got["words_scale"], got["order"]) \
        == (12.0, 30.5, 0.5, (4.0, 90.0), 2.0, 0)
    assert auto["x"] == 360.0                              # the automatic one is not changed
    assert MA.with_layout(auto, {"y": 10})["x"] == 360.0
    # what cannot be built is named by validation and never built
    bad = {"x": "left", "scale": 0, "order": 1.5, "words_x": 3, "colour": 1}
    words = " ".join(MA.layout_problems(bad))
    for k in ("x is 'left'", "scale is 0", "order is 1.5", "words' x without their y", "'colour'"):
        assert k in words, k
    assert MA.clean_layout(bad) == {}
    spec = MP.ModeSpec(title=MP.GODZILLA_PRO_1_15.key, screen_layout={"scale": -1})
    assert any("cannot be placed" in p for p in MP.validate(spec))


def test_a_mode_without_a_layout_builds_byte_for_byte_as_before(tmp_path):
    """Every mode made before PAD-323 has no ``screen_layout``: its screen is the same bytes."""
    from pinball_decryptor.plugins.stern import scene_write as SW
    art = MA.panel_art("ALPHA")
    p = SW.PROFILES["f9daed5a19aafc807bf9eb3c2def6c27"]
    plain, _ = SW.screen(p, "PadMode_a_Screen", art, "1,000,000 A SHOT", 360.0, 200.0)
    same, _ = SW.screen(p, "PadMode_a_Screen", art, "1,000,000 A SHOT", 360.0, 200.0,
                        scale=1.0, words_scale=1.0)
    assert plain == same
    half, _ = SW.screen(p, "PadMode_a_Screen", art, "1,000,000 A SHOT", 360.0, 200.0, scale=0.5)
    assert len(half) == len(plain) and half != plain
    assert SW.matrix(0.5, 0.5, tx=360.0, ty=200.0) in half
    if not os.path.exists(HUD):
        pytest.skip("stock HUD scene not present")
    stock = open(HUD, "rb").read()
    outs = []
    for i, layout in enumerate(({}, {"order": None})):
        project, out = str(tmp_path / ("p%d" % i)), str(tmp_path / ("o%d" % i))
        _mode(project, "Alpha", clip="none", screen_layout=layout)
        MA.build(project, stock, b"", out)
        rel = "assets/lcd/auto_loaded/%s/scene.radium" % MP.GODZILLA_PRO_1_15.hud_scene
        outs.append(open(os.path.join(out, *rel.split("/")), "rb").read())
    assert outs[0] == outs[1]


def test_a_screen_laid_out_under_the_hud_is_the_scenes_first_child(tmp_path):
    """``order`` 0: the screen is the HUD scene's FIRST root child, drawn under every one of its own
    pictures (David: "the wall image below the HUD"); the other modes stay where they always go, and
    the scene still walks as a tree to its last byte with each screen where it was laid out."""
    if not os.path.exists(HUD):
        pytest.skip("stock HUD scene not present")
    from pinball_decryptor.plugins.stern import scene_tree as ST
    stock = open(HUD, "rb").read()
    project, out = str(tmp_path / "proj"), str(tmp_path / "out")
    _mode(project, "Alpha", clip="none", screen_layout={"order": 0, "x": 0, "y": 0, "scale": 2.0,
                                                         "words_x": 300, "words_y": 120})
    _mode(project, "Beta", clip="none")
    _mode(project, "Gamma", clip="none", screen_layout={"order": 2})
    MA.build(project, stock, b"", out)
    rel = "assets/lcd/auto_loaded/%s/scene.radium" % MP.GODZILLA_PRO_1_15.hud_scene
    hud = open(os.path.join(out, *rel.split("/")), "rb").read()
    kids = ST.parse(hud).root["kids"]
    assert [k.name for k in kids] == [
        "PadMode_alpha_Screen", "TeslaSlideOut_Artbox", "DoubleScoringSlideOut_Artbox",
        "PadMode_gamma_Screen", "PadMode_beta_Screen", "BattleSlideOut_Artbox"]
    alpha = kids[0]
    m = alpha.tracks[0][1]
    assert (m[0], m[5], m[12], m[13]) == (2.0, 2.0, 0.0, 0.0)
    words = alpha.components[0].obj.body["kids"][1]
    assert (words.tracks[0][1][12], words.tracks[0][1][13]) == (300.0, 120.0)
    # the object ids are still handed out in slot order: alpha's are the first seven
    assert alpha.id == SW_first_free()


def SW_first_free():
    from pinball_decryptor.plugins.stern import scene_write as SW
    return SW.PROFILES["f9daed5a19aafc807bf9eb3c2def6c27"].first_free_id
