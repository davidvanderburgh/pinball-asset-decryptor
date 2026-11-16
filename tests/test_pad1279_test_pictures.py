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
    ([("t%d.png" % k, "") for k in range(65)], "at most 64"),
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
    assert m["tests"] == [("test0.png", "Full screen", None, None), ("test1.gif", "Clip", None, None),
                          ("test2.wav", "Tone", None, None)]
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
    with pytest.raises(mk.Refused, match="png, .gif, .padv or .wav"):
        mk.plan_media(d3, 1)


# ---- selectmedia -----------------------------------------------------------------------------

def test_a_test_spec_is_a_path_and_an_optional_label(sm, tmp_path):
    p = _png(str(tmp_path / "Sunset photo.png"), 10, 10)
    assert sm.parse_test_spec(p) == (p, "Sunset photo", None)
    assert sm.parse_test_spec(p + "|On the beach") == (p, "On the beach", None)
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
    assert name == {"file": "test0.png", "sound": None}
    assert open(str(out / name["file"]), "rb").read() == open(src, "rb").read()


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
    assert sm._prepare_test(0, wav, str(out), str(tmp_path), log=said.append)["file"] == "test0.wav"
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
    assert sm.TEST_MAX == mk.TEST_MAX == 64
    assert sm.TEST_LABEL_MAX == mk.TEST_LABEL_MAX
    assert sm.TEST_PNG_MAX == mk.PNG_MAX
    conf_h = open(os.path.join(RIG, "codeselect", "conf.h"), encoding="utf-8").read()
    assert "#define CONF_MAX_TESTS 64" in conf_h


# ---- the app: the Multi-boot tab's Menu settings -----------------------------------------------

from pinball_decryptor.webui import multiboot_core as mbc  # noqa: E402


def _app_form(tmp_path, **kw):
    p = tmp_path / "turtles_pro-1_59_0.Release.8G.sdcard.raw"
    p.write_bytes(bytes(16))
    form = mbc.MultibootForm(images=[mbc.ImageRow(path=str(p), title="TMNT")],
                             out=str(tmp_path / "card.multi.raw"))
    for k, v in kw.items():
        setattr(form, k, v)
    return form


@pytest.fixture()
def _no_wsl(monkeypatch):
    monkeypatch.setattr(mbc, "wsl", lambda p: "/mnt/c/" + os.path.basename(p))


def test_a_multi_boot_build_carries_no_test_pictures_any_more(tmp_path, _no_wsl):
    """Round 2 (DragonRR: "remove this feature from the Multi-boot section"): the test
    pictures are the Test card tab's; a multi-boot card's SETTINGS keeps only the built-in
    patterns, and an older saved menu's test pictures are left out."""
    form = _app_form(tmp_path, tests=[(str(tmp_path / "card.png"), "Grey card"),
                                      (str(tmp_path / "clip.mp4"), "")])
    assert "--test" not in mbc.prepare_args(form, str(tmp_path / "media"))
    assert "--test" not in mbc.prepare_args(form, str(tmp_path / "media"), visual_only=True)


def test_clean_tests_keeps_what_the_conf_can_carry():
    got = mbc.clean_tests([("a.png", "one|two"), ["b.png"], {"path": "c.png", "label": "  x \n y "},
                           ("", "nothing"), 7] + [("f%d.png" % k, "") for k in range(20)])
    assert got[:3] == [("a.png", "one/two"), ("b.png", ""), ("c.png", "x y")]
    assert len(got) == mbc.TEST_MAX


def test_a_card_read_back_gives_its_test_pictures_by_source():
    info = {"tests": [{"file": "test0.png", "label": "Card", "source": "C:/pics/card.png"},
                      {"file": "test1.wav", "label": "Tone", "source": None}]}
    rows_from = mbc.rows_from_inspect
    try:
        mbc.rows_from_inspect = lambda i: ([], [])
        form, _warn = mbc.form_from_inspect(info, "card.raw")[:2]
    finally:
        mbc.rows_from_inspect = rows_from
    assert form.tests == [("C:/pics/card.png", "Card"), ("test1.wav", "Tone")]


def test_changing_the_test_pictures_is_a_menu_change_and_the_summary_says_so(tmp_path):
    before = _app_form(tmp_path)
    after = _app_form(tmp_path, tests=[("a.png", "A")])
    assert "test pictures" in mbc._menu_fields(before, after)
    assert "test pictures" not in mbc._menu_fields(before, _app_form(tmp_path))
    assert "1 test picture" in mbc.menu_summary(after)
    assert "test picture" not in mbc.menu_summary(before)


def test_the_preview_draws_the_settings_card_for_test_pictures(tmp_path):
    conf = mbc.write_preview_conf(_app_form(tmp_path, tests=[("a.png", "A")]))
    assert "test=preview0.png|A" in conf.splitlines()
    assert "test=" not in mbc.write_preview_conf(_app_form(tmp_path))


def test_a_saved_menu_keeps_its_test_pictures():
    menu = mbc.menu_from_state({"tests": [["C:/a.png", "A"], ["C:/b.wav", ""]]})
    assert menu["tests"] == [("C:/a.png", "A"), ("C:/b.wav", "")]
    assert mbc.menu_from_state({})["tests"] == []


def test_the_multi_boot_tab_has_no_test_pictures_list_any_more():
    """The list, its buttons and Build test card moved to the Test card tab."""
    import inspect
    from pinball_decryptor.webui.tabs import multiboot as mbt
    src = inspect.getsource(mbt)
    for gone in ("def test_add", "def test_remove", "def test_move", "def test_label", "def build_test_card"):
        assert gone not in src
    js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pinball_decryptor",
                           "webui", "static", "js", "tabs", "multiboot.js"), encoding="utf-8").read()
    assert "TestPictures" not in js and "multiboot.build_test_card" not in js

    class Var(object):
        v = json.dumps([["C:/a.png", "A"]])

        def get(self):
            return self.v
    panel = type("P", (), {})()
    panel._tests_var = Var()
    panel.test_pictures = mbc.MultibootPanel.test_pictures.__get__(panel)
    assert panel.test_pictures() == []                 # an older saved menu's are left out

# ---- the test card (mkmulticard.py testcard) -----------------------------------------------------

def test_a_test_card_conf_reads_back_as_one(mk):
    conf = mk.render_images_conf([mk.TESTCARD_DEVICE], [mk.TESTCARD_TITLE], [mk.TESTCARD_SUBTITLE],
                                 0, 0, colours={0: dict(mk.TESTCARD_NO_CHANGE)},
                                 tests=[("test0.png", "Card")], testcard=True)
    assert "testcard=on" in conf.splitlines()
    parsed = mk.parse_images_conf(conf)
    assert parsed["testcard"] is True
    assert mk.render_images_conf_text(parsed) == conf
    assert "testcard" not in mk.render_images_conf(["/dev/mmcblk0p3"], ["A"])


def test_the_test_card_colour_is_the_conf_fields_or_no_change(mk):
    assert mk.parse_testcard_colour("") == mk.TESTCARD_NO_CHANGE
    c = mk.parse_testcard_colour("1.1 1.2 1.35|1 1 1|0 0 0|0.9|Recommended")
    assert c == {"name": "Recommended", "gamma": [1.1, 1.2, 1.35], "gain": [1.0, 1.0, 1.0],
                 "lift": [0.0, 0.0, 0.0], "saturation": 0.9}
    for bad in ("1 1|1 1 1|0 0 0|1", "a b c|1 1 1|0 0 0|1", "1 1 1|1 1 1"):
        with pytest.raises(mk.Refused):
            mk.parse_testcard_colour(bad)


def test_the_test_card_keeps_boot_and_rootfs_where_they_are_and_the_rest_small(mk):
    class G(object):
        def part(self, n):
            return {1: (0x0C, 8192, 16384), 2: (0x83, 24576, 688128)}[n]

    prims, ext, ext_count, logs, total = mk.testcard_layout(G())
    assert prims[:2] == [(0x0C, 8192, 16384), (0x83, 24576, 688128)]
    assert prims[2] == (0x83, 712704, mk.TESTCARD_P3_MIB * 2048)       # where a stock p3 starts
    (e5, s5, c5), (e6, s6, c6) = logs
    assert e5 == ext and s5 == e5 + mk.ALIGN and e6 >= s5 + c5 and s6 == e6 + mk.ALIGN
    assert ext + ext_count == s6 + c6 and total == (s6 + c6) * 512
    assert total < 1 << 30                                              # under a gigabyte


def test_a_card_that_is_not_spike_2_is_refused(mk):
    class G(object):
        def part(self, n):
            return (0x0C, 8192, 16384) if n == 1 else (0x07, 24576, 688128)

    with pytest.raises(mk.Refused, match="not a Spike 2 card"):
        mk.testcard_layout(G())


# ---- the app: Build test card… -------------------------------------------------------------------

def _words(argv):
    import shlex
    if callable(argv):
        argv = argv({})
    return shlex.split(argv[-1])


def test_build_test_card_runs_the_selector_the_test_pictures_and_testcard(tmp_path, monkeypatch, _no_wsl):
    monkeypatch.setattr(mbc, "wsl_home", lambda: "/home/x")
    monkeypatch.setattr(mbc, "wsl_account", lambda: ("x", "/home/x"))
    form = _app_form(tmp_path, tests=[])
    form.colour_profiles = {0: {"name": "Recommended", "gamma": [1.1, 1.2, 1.35],
                                "gain": [1, 1, 1], "lift": [0, 0, 0], "saturation": 0.9}}
    specs = ["--test", "video:/mnt/c/clip.mp4|Red clip", "--test", "image:/mnt/c/card.png|Grey card"]
    cmds = mbc.testcard_commands(form, str(tmp_path / "pad_test_card.raw"), str(tmp_path / "m"),
                                 test_specs=specs)
    assert [label for label, _a in cmds][-2:] == ["prepare", "testcard"]
    prep = _words(cmds[-2][1])
    i = prep.index("--test")
    assert prep[i:i + 4] == specs
    for k in ("--art", "--anim", "--music"):
        assert prep[prep.index(k) + 1] == "0=none"
    tc = _words(cmds[-1][1])
    assert tc[tc.index("testcard") + 1:tc.index("testcard") + 3] == ["--primary", "/mnt/c/" + os.path.basename(form.images[0].path)]
    assert tc[tc.index("--color") + 1] == "1.1000 1.2000 1.3500|1.0000 1.0000 1.0000|0.0000 0.0000 0.0000|0.9000|Recommended"


def test_a_test_card_without_a_built_profile_starts_from_no_change(tmp_path):
    assert mbc.testcard_colour_arg(_app_form(tmp_path)) == []
