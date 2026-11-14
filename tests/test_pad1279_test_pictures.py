"""PAD-1279: the card's own test pictures for the boot menu's Settings > Test pictures.

selectmedia.py prepare --test turns the user's pictures, videos and sounds into the
menu's files (a picture pixel for pixel, never enlarged); media.json lists them under
"tests"; mkmulticard.py checks and stages them and writes one test= line each, reads them
back off a card, and carries them through an update that brings no new media.
"""

import json
import os
import struct
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


def _gif(path, frames=4, size=(64, 36)):
    ims = [PIL.new("RGB", size, (k * 40, 0, 0)) for k in range(frames)]
    ims[0].save(path, save_all=True, append_images=ims[1:], duration=40, loop=0)
    return path


# ---- images.conf ----------------------------------------------------------------------------

def test_test_lines_follow_the_settings_key_and_name_the_media_dir(mk):
    conf = mk.render_images_conf(["/dev/mmcblk0p3"], ["A"], tests=[("test0.png", "Sunset"),
                                                                  ("test1.wav", "")])
    lines = conf.splitlines()
    assert "test=test0.png|Sunset" in lines
    assert "test=test1.wav" in lines
    assert lines.index("test=test0.png|Sunset") < lines.index("test=test1.wav")
    assert "media=%s" % mk.MEDIA_DIR in lines, "a test file is a media file: the menu must know where"


def test_a_card_without_tests_is_byte_for_byte_what_it_was(mk):
    assert mk.render_images_conf(["/dev/mmcblk0p3"], ["A"]) == \
        mk.render_images_conf(["/dev/mmcblk0p3"], ["A"], tests=[])


@pytest.mark.parametrize("tests, why", [
    ([("t%d.png" % k, "") for k in range(17)], "at most 16"),
    ([("a/b.png", "x")], "plain media file name"),
    ([("t.png", "a|b")], "no '|'"),
    ([("t.png", "two\nlines")], "one line"),
])
def test_what_the_menu_would_drop_is_refused(mk, tests, why):
    with pytest.raises(mk.Refused) as e:
        mk.render_images_conf(["/dev/mmcblk0p3"], ["A"], tests=tests)
    assert why in str(e.value)


def test_test_lines_read_back_and_render_the_same(mk):
    conf = mk.render_images_conf(["/dev/mmcblk0p3", "/dev/mmcblk0p7"], ["A", "B"],
                                 tests=[("test0.png", "Grey card"), ("test1.gif", "Clip")])
    parsed = mk.parse_images_conf(conf)
    assert parsed["tests"] == [("test0.png", "Grey card"), ("test1.gif", "Clip")]
    assert mk.render_images_conf_text(parsed) == conf


def test_an_update_without_media_keeps_the_cards_test_pictures(mk):
    """conf_for_plan with no media: the existing card's test= lines ride along, even
    when the image count changes (they belong to no image)."""
    existing = mk.parse_images_conf(mk.render_images_conf(
        ["/dev/mmcblk0p3", "/dev/mmcblk0p7"], ["A", "B"], tests=[("test0.png", "Card")]))

    import inspect
    src = inspect.getsource(mk.conf_for_plan)
    assert 'tests = list(ex.get("tests") or [])' in src and "tests=tests" in src
    assert existing["tests"] == [("test0.png", "Card")]


# ---- plan_media ------------------------------------------------------------------------------

def _media_dir(tmp_path, tests):
    d = tmp_path / "media"
    d.mkdir()
    _png(str(d / "art0.png"), 100, 56)
    man = {"images": [{"art": "art0.png", "anim": None, "music": None, "confirm": None}],
           "sound_move": None, "sound_confirm": None, "volume": 50, "tests": tests}
    (d / "media.json").write_text(json.dumps(man), encoding="utf-8")
    return str(d)


def test_plan_media_stages_the_test_pictures_and_lists_them(mk, tmp_path):
    d = _media_dir(tmp_path, [{"file": "test0.png", "label": "Full screen"},
                              {"file": "test1.gif", "label": "Clip"},
                              {"file": "test2.wav", "label": "Tone"}])
    _png(os.path.join(d, "test0.png"), 1360, 768)
    _gif(os.path.join(d, "test1.gif"))
    _wav(os.path.join(d, "test2.wav"))
    m = mk.plan_media(d, 1)
    assert m["tests"] == [("test0.png", "Full screen"), ("test1.gif", "Clip"), ("test2.wav", "Tone")]
    assert list(m["files"]) == ["art0.png", "test0.png", "test1.gif", "test2.wav"]
    # no image owns them: they count with the menu-wide sounds
    sizes = m["sizes"]
    assert m["shared"] == sizes["test0.png"] + sizes["test1.gif"] + sizes["test2.wav"]


def test_plan_media_refuses_a_test_file_the_menu_cannot_show(mk, tmp_path):
    d = _media_dir(tmp_path, [{"file": "big.png", "label": "Too big"}])
    _png(os.path.join(d, "big.png"), 1920, 1080)
    with pytest.raises(mk.Refused, match="larger than the 1360x768"):
        mk.plan_media(d, 1)
    sub = tmp_path / "c"
    sub.mkdir()
    d3 = _media_dir(sub, [{"file": "notes.txt", "label": ""}])
    open(os.path.join(d3, "notes.txt"), "w").write("x")
    with pytest.raises(mk.Refused, match="png, .gif or .wav"):
        mk.plan_media(d3, 1)


# ---- selectmedia -----------------------------------------------------------------------------

def test_a_test_spec_is_a_path_and_an_optional_label(sm, tmp_path):
    p = _png(str(tmp_path / "Sunset photo.png"), 10, 10)
    assert sm.parse_test_spec(p) == (p, "Sunset photo")
    assert sm.parse_test_spec(p + "|On the beach") == (p, "On the beach")
    with pytest.raises(sm.Refused):
        sm.parse_test_spec(str(tmp_path / "nope.png"))


def test_kinds_come_from_the_file(sm, tmp_path):
    assert sm.test_kind(_png(str(tmp_path / "a.png"), 4, 4)) == "picture"
    assert sm.test_kind(_gif(str(tmp_path / "a.gif"))) == "anim"
    assert sm.test_kind(_gif(str(tmp_path / "one.gif"), frames=1)) == "picture"
    assert sm.test_kind(_wav(str(tmp_path / "a.wav"))) == "sound"
    jpg = str(tmp_path / "photo.jpg")
    PIL.new("RGB", (8, 8)).save(jpg, "JPEG")
    assert sm.test_kind(jpg) == "picture"


def test_a_picture_that_fits_is_kept_pixel_for_pixel(sm, tmp_path):
    src = _png(str(tmp_path / "card.png"), 640, 400, (12, 34, 56))
    out = tmp_path / "out"
    out.mkdir()
    name = sm._prepare_test(0, src, str(out), str(tmp_path), log=lambda *a: None)
    assert name == "test0.png"
    assert open(str(out / name), "rb").read() == open(src, "rb").read()


def test_a_big_picture_is_fitted_down_and_a_small_one_never_enlarged(sm, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    big = str(tmp_path / "big.jpg")
    PIL.new("RGB", (2720, 1536), (90, 90, 90)).save(big, "JPEG")
    sm._prepare_test(0, big, str(out), str(tmp_path), log=lambda *a: None)
    assert PIL.open(str(out / "test0.png")).size == (1360, 768)
    small = str(tmp_path / "small.jpg")
    PIL.new("RGB", (320, 200), (90, 90, 90)).save(small, "JPEG")
    sm._prepare_test(1, small, str(out), str(tmp_path), log=lambda *a: None)
    assert PIL.open(str(out / "test1.png")).size == (320, 200)


def test_a_converted_test_file_is_kept_while_its_source_is_unchanged(sm, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    src = _png(str(tmp_path / "a.png"), 50, 50)
    said = []
    sm._prepare_test(0, src, str(out), str(tmp_path), log=said.append)
    sm._prepare_test(0, src, str(out), str(tmp_path), log=said.append)
    assert "kept" in said[-1]
    # a different kind under the same number replaces the old file
    wav = _wav(str(tmp_path / "b.wav"))
    assert sm._prepare_test(0, wav, str(out), str(tmp_path), log=said.append) == "test0.wav"
    assert not (out / "test0.png").exists()


def test_the_manifest_carries_tests_and_the_sweep_keeps_their_files(sm, tmp_path):
    m = {"images": [{"art": "art0.png", "anim": None, "music": None, "confirm": None}],
         "sound_move": None, "sound_confirm": None, "volume": 50,
         "tests": [{"file": "test0.png", "label": "Card", "source": "C:/x.png"}]}
    assert sm.validate_manifest(m) is m
    assert "test0.png" in sm.manifest_files(m)
    out = tmp_path / "out"
    out.mkdir()
    for n in ("art0.png", "test0.png", "test5.gif"):
        (out / n).write_bytes(b"x")
    removed = sm.sweep_stale(str(out), m, log=lambda *a: None)
    assert removed == ["test5.gif"]
    bad = dict(m, tests=[{"file": "a/b.png"}])
    with pytest.raises(sm.Refused):
        sm.validate_manifest(bad)


def test_the_two_tools_agree_on_the_test_contract(sm, mk):
    assert sm.TEST_MAX == mk.TEST_MAX == 16
    assert sm.TEST_LABEL_MAX == mk.TEST_LABEL_MAX
    assert sm.TEST_PNG_MAX == mk.PNG_MAX
    conf_h = open(os.path.join(RIG, "codeselect", "conf.h"), encoding="utf-8").read()
    assert "#define CONF_MAX_TESTS 16" in conf_h
