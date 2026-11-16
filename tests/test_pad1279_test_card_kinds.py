"""PAD-1279, DragonRR's second round: the TEST CARD boots to a menu - DEFAULT PAD TEST CARD,
IMAGES, VIDEOS, SCENES, SOUNDS - so every test item says which list it goes in
(test_<kind>= lines), a video plays WHOLE in full colour (a .padv of 4:4:4 JPEG frames,
codeselect video.h, with its sound as a WAV beside it), and a test card's own files ride
on its own p3, sized to them, which the menu finds through test_dir=.
"""
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import wave

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
PIL = pytest.importorskip("PIL.Image")


@pytest.fixture()
def mk():
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    import mkmulticard
    return mkmulticard


@pytest.fixture()
def sm():
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    import selectmedia
    return selectmedia


def _png(path, w, h, rgb=(200, 40, 40)):
    PIL.new("RGB", (w, h), rgb).save(path, "PNG")
    return path


def _wav(path, seconds=0.2):
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(struct.pack("<hh", 1000, -1000) * int(44100 * seconds))
    return path


def _jpeg(rgb, size=(64, 48)):
    b = io.BytesIO()
    PIL.new("RGB", size, rgb).save(b, "JPEG", quality=95, subsampling=0)
    return b.getvalue()


needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="no ffmpeg here")


def _video(path, size="160x90", seconds=2, fps=10, colour=None, sound=True):
    src = ("color=c=%s:s=%s:r=%d:d=%d" % (colour, size, fps, seconds) if colour
           else "testsrc=s=%s:r=%d:d=%d" % (size, fps, seconds))
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src]
    if sound:
        cmd += ["-f", "lavfi", "-i", "sine=f=440:d=%d" % seconds, "-shortest"]
    cmd += ["-pix_fmt", "yuv444p", "-c:v", "libx264", "-qp", "0", path]
    subprocess.run(cmd, check=True)
    return path


# ---- images.conf ----------------------------------------------------------------------------

def test_each_kind_is_its_own_line_and_a_plain_test_stays_test(mk):
    assert mk.conf_test_lines([("a.png", "A", "image"), ("v.padv", "V", "video", "v.wav"),
                               ("s.png", "", "scene"), ("t.wav", "T", "sound"), ("old.gif", "Old")]) == [
        "test_image=a.png|A", "test_video=v.padv|V", "test_scene=s.png", "test_sound=t.wav|T",
        "test=old.gif|Old"]
    with pytest.raises(mk.Refused, match="kind 'film'"):
        mk.conf_test_lines([("a.png", "A", "film")])


def test_a_test_card_conf_reads_back_with_its_kinds_and_test_dir(mk):
    conf = mk.render_images_conf([mk.TESTCARD_DEVICE], ["TEST CARD"], testcard=True, test_dir="/games/testcard",
                                 tests=[("test0.png", "Card", "image"), ("test1.padv", "Clip", "video", "test1.wav"),
                                        ("test2.png", "Scene", "scene")])
    assert "test_dir=/games/testcard\n" in conf and "test_video=test1.padv|Clip\n" in conf
    parsed = mk.parse_images_conf(conf)
    assert parsed["test_dir"] == "/games/testcard"
    assert parsed["tests"] == [("test0.png", "Card", "image"), ("test1.padv", "Clip", "video"),
                               ("test2.png", "Scene", "scene")]
    assert mk.render_images_conf_text(parsed) == conf
    with pytest.raises(mk.Refused, match="absolute"):
        mk.render_images_conf([mk.TESTCARD_DEVICE], ["T"], test_dir="games")


def test_the_conf_and_the_menu_agree_on_the_kinds(mk):
    conf_c = open(os.path.join(RIG, "codeselect", "conf.c"), encoding="utf-8").read()
    for kind in mk.TEST_KINDS:
        assert '"test_%s"' % kind in conf_c
    assert '"test_dir"' in conf_c


# ---- selectmedia: the specs and the conversions ----------------------------------------------

def test_a_spec_may_name_its_list(sm, tmp_path):
    p = _png(str(tmp_path / "Sunset.png"), 64, 48)
    w = _wav(str(tmp_path / "tone.wav"))
    assert sm.parse_test_spec("image:" + p) == (p, "Sunset", "image")
    assert sm.parse_test_spec("scene:" + p + "|Title screen") == (p, "Title screen", "scene")
    assert sm.parse_test_spec("sound:" + w) == (w, "tone", "sound")
    with pytest.raises(sm.Refused, match="a video is asked for, but it is a sound"):
        sm.parse_test_spec("video:" + w)
    with pytest.raises(sm.Refused, match="an? image is asked for|a image is asked for"):
        sm.parse_test_spec("image:" + w)


def test_the_frame_splitter_finds_every_jpeg_in_any_chunking(sm):
    frames = [_jpeg((200, 40, 40)), _jpeg((40, 200, 40), (32, 32)), _jpeg((1, 2, 3))]
    blob = b"".join(frames)
    for chunk in (1, 7, 4096, 1 << 20):
        assert list(sm.jpeg_frames(io.BytesIO(blob), chunk=chunk)) == frames
    with pytest.raises(sm.Refused, match="no end"):
        list(sm.jpeg_frames(io.BytesIO(frames[0][:-2])))
    assert sm.jpeg_size(frames[1]) == (32, 32)


def test_a_padv_is_what_the_menu_reads(sm, mk, tmp_path):
    out = str(tmp_path / "t.padv")
    frames = [_jpeg((200, 40, 40))] * 3 + [_jpeg((40, 40, 200))] * 2
    assert sm.write_padv(iter(frames), out, 12.5) == (64, 48, 5)
    data = open(out, "rb").read()
    assert data[:8] == b"PADVJPG1"
    w, h, fps1000, n = struct.unpack("<4I", data[8:24])
    assert (w, h, fps1000, n) == (64, 48, 12500, 5)
    off = struct.unpack("<6I", data[32:56])
    assert [data[off[k]:off[k + 1]] for k in range(5)] == frames and off[5] == len(data)
    assert sm.padv_info(out) == (64, 48, 12.5, 5)
    assert mk.padv_check(out, "t.padv") == "padv 64x48 5 frames"
    # the header the selector reads (video.h) is the one written
    vh = open(os.path.join(RIG, "codeselect", "video.h"), encoding="utf-8").read()
    assert '#define VID_MAGIC "PADVJPG1"' in vh and "#define VID_HEADER 32" in vh
    with pytest.raises(sm.Refused, match="change size"):
        sm.write_padv(iter([_jpeg((1, 1, 1)), _jpeg((1, 1, 1), (8, 8))]), out + "2", 10)
    bad = tmp_path / "bad.padv"
    bad.write_bytes(data[:40])
    with pytest.raises(mk.Refused, match="index"):
        mk.padv_check(str(bad), "bad.padv")


@needs_ffmpeg
def test_a_video_becomes_a_whole_padv_in_full_colour_with_its_sound(sm, tmp_path):
    src = _video(str(tmp_path / "clip.mp4"), seconds=2, fps=10, colour="0xC83228")
    out = tmp_path / "out"
    out.mkdir()
    got = sm._prepare_test(0, src, str(out), str(tmp_path), log=lambda *a: None, want="video")
    assert got == {"file": "test0.padv", "sound": "test0.wav"}
    w, h, fps, n = sm.padv_info(str(out / "test0.padv"))
    assert (w, h, fps, n) == (160, 90, 10.0, 20)           # every frame, at its own rate
    data = open(str(out / "test0.padv"), "rb").read()
    off = struct.unpack("<%dI" % (n + 1), data[32:32 + 4 * (n + 1)])
    im = PIL.open(io.BytesIO(data[off[0]:off[1]]))
    # 4:4:4: the colour is not halved
    # (the same sampling factors on all three: chroma at luma's own resolution)
    assert len(im.layer) == 3 and len(set((hs, vs) for _id, hs, vs, _q in im.layer)) == 1
    r, g, b = im.convert("RGB").getpixel((80, 45))
    assert abs(r - 0xC8) <= 4 and abs(g - 0x32) <= 4 and abs(b - 0x28) <= 4
    with wave.open(str(out / "test0.wav")) as wv:
        assert wv.getframerate() == 44100 and wv.getnchannels() == 2
        assert abs(wv.getnframes() / 44100.0 - 2.0) < 0.1
    # unchanged source: kept, not converted again
    said = []
    assert sm._prepare_test(0, src, str(out), str(tmp_path), log=said.append, want="video") == got
    assert "kept" in said[0]


@needs_ffmpeg
def test_a_big_video_is_fitted_down_and_one_without_sound_has_none(sm, tmp_path):
    src = _video(str(tmp_path / "big.mp4"), size="1920x1080", seconds=1, fps=5, sound=False)
    out = tmp_path / "out"
    out.mkdir()
    got = sm._prepare_test(3, src, str(out), str(tmp_path), log=lambda *a: None, want="video")
    assert got == {"file": "test3.padv", "sound": None}
    assert sm.padv_info(str(out / "test3.padv"))[:2] == (1360, 765)
    assert not (out / "test3.wav").exists()


@needs_ffmpeg
def test_a_plain_test_video_is_still_a_menu_clip(sm, tmp_path):
    """--test without a kind (a multi-boot card's Settings > Test pictures) is as before."""
    src = _video(str(tmp_path / "clip.mp4"), seconds=1, fps=10, sound=False)
    out = tmp_path / "out"
    out.mkdir()
    assert sm._prepare_test(0, src, str(out), str(tmp_path), log=lambda *a: None)["file"] == "test0.gif"


# ---- the manifest and the build ---------------------------------------------------------------

def _media_dir(tmp_path, tests):
    d = tmp_path / "media"
    d.mkdir()
    _png(str(d / "art0.png"), 100, 56)
    man = {"images": [{"art": "art0.png", "anim": None, "music": None, "confirm": None}],
           "sound_move": None, "sound_confirm": None, "volume": 50, "tests": tests}
    (d / "media.json").write_text(json.dumps(man), encoding="utf-8")
    return str(d)


def _write_padv(sm, path, n=4):
    sm.write_padv(iter([_jpeg((200, 40, 40))] * n), path, 10)


def test_a_test_cards_own_files_are_apart_from_the_menus_budget(mk, sm, tmp_path):
    d = _media_dir(tmp_path, [{"file": "test0.png", "label": "Card", "kind": "image"},
                              {"file": "test1.padv", "label": "Clip", "kind": "video", "sound": "test1.wav"},
                              {"file": "test2.wav", "label": "Tone", "kind": "sound"}])
    _png(os.path.join(d, "test0.png"), 1360, 768)
    _write_padv(sm, os.path.join(d, "test1.padv"))
    _wav(os.path.join(d, "test1.wav"))
    _wav(os.path.join(d, "test2.wav"))
    apart = mk.plan_media(d, 1, tests_apart=True)
    assert list(apart["files"]) == ["art0.png"]
    assert list(apart["test_files"]) == ["test0.png", "test1.padv", "test1.wav", "test2.wav"]
    assert apart["test_bytes"] == sum(os.path.getsize(os.path.join(d, n)) for n in apart["test_files"])
    assert apart["shared"] == 0
    assert apart["tests"][1] == ("test1.padv", "Clip", "video", "test1.wav")
    # a multi-boot card stages them with the media, as before
    together = mk.plan_media(d, 1)
    assert list(together["files"]) == ["art0.png", "test0.png", "test1.padv", "test1.wav", "test2.wav"]
    assert not together["test_files"]
    # selectmedia's own check agrees: on the card's own partition, not the menu's budget
    said = []
    m = sm.check_media_dir(d, log=said.append)
    assert sm.test_card_files(m) == ["test0.png", "test1.padv", "test1.wav", "test2.wav"]
    assert any(s.startswith("test card files: 4,") for s in said)


def test_the_manifest_refuses_a_kind_the_menu_has_no_list_for(sm, tmp_path):
    with pytest.raises(sm.Refused, match="kind"):
        sm.validate_manifest({"images": [{"art": None, "anim": None, "music": None, "confirm": None}],
                              "sound_move": None, "sound_confirm": None, "volume": 50,
                              "tests": [{"file": "a.png", "label": "", "kind": "film"}]})


def test_the_test_cards_p3_is_sized_to_its_files(mk):
    assert mk.testcard_p3_mib(0) == mk.TESTCARD_P3_MIB
    assert mk.testcard_p3_mib(500 << 20) == -(-(int((500 << 20) * 1.10) + (16 << 20)) // (1 << 20))

    class G(object):
        def part(self, n):
            return {1: (0x0C, 8192, 16384), 2: (0x83, 24576, 688128)}[n]
    prims, _ext, _c, _logs, _total = mk.testcard_layout(G(), 600)
    assert prims[2] == (0x83, 712704, 600 * 2048)
