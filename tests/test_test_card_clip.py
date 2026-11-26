"""Simon (2026-11-22): a TEST CARD clip through the machine's own video chain.

A test video used to go on a test card only as a .padv (JPEG frames the menu decodes on the
CPU).  ``--test clip:PATH`` puts the .mp4/.mov/.m4v on the card AS IT IS, in the Videos list,
and the menu (codeselect/gstclip.c) plays it through the game's GStreamer 0.10 chain -
filesrc ! qtdemux ! queue ! vpudec ! fakesink - so the video chip decodes it as in a game.
In the emulator the same calls are answered by padgst.so (the video bridge alone).  On a
moving test item ACTION freezes on a quick press and backs out when held ("quick press to
freeze, long press to back out")."""

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.join(os.path.dirname(HERE), "tools", "spike2_emu")
SEL = os.path.join(RIG, "codeselect")


@pytest.fixture()
def sm():
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    import selectmedia
    return selectmedia


@pytest.fixture()
def mk():
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    import mkmulticard
    return mkmulticard


def _mp4(path):
    # an ISO base media file's first box: size, "ftyp", brand
    with open(path, "wb") as f:
        f.write(b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 64)
    return path


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def test_a_clip_spec_is_a_video_kept_as_it_is(sm, tmp_path):
    clip = _mp4(str(tmp_path / "match.mp4"))
    assert sm.parse_test_spec("clip:%s|Match" % clip) == (clip, "Match", "clip")
    other = _mp4(str(tmp_path / "match.avi"))
    with pytest.raises(sm.Refused, match="mp4 / .mov / .m4v"):
        sm.parse_test_spec("clip:%s" % other)


def test_prepare_copies_the_clip_and_files_it_under_videos(sm, tmp_path, monkeypatch):
    clip = _mp4(str(tmp_path / "match.mp4"))
    out = tmp_path / "media"
    out.mkdir()
    monkeypatch.setattr(sm, "audio_stream_count", lambda p: 0)
    got = sm._prepare_test(0, clip, str(out), str(tmp_path), log=lambda *a: None, want="clip")
    assert got["file"] == "test0.mp4"
    with open(clip, "rb") as a, open(str(out / "test0.mp4"), "rb") as b:
        assert a.read() == b.read(), "the machine's decoder reads the file the game would"
    assert not os.path.exists(str(out / "test0.padv"))


def test_the_card_builder_takes_a_clip_and_refuses_a_fake_one(mk, tmp_path):
    good = _mp4(str(tmp_path / "test0.mp4"))
    word, size = mk.check_media_file(good, "test")
    assert word == "clip mp4" and size == os.path.getsize(good)
    bad = str(tmp_path / "test1.mp4")
    with open(bad, "wb") as f:
        f.write(b"not a movie at all")
    with pytest.raises(mk.Refused, match="not an MP4 / QuickTime file"):
        mk.check_media_file(bad, "test")


def test_the_media_set_check_takes_a_clip(sm, tmp_path):
    d = tmp_path / "media"
    d.mkdir()
    _mp4(str(d / "test0.mp4"))
    man = {"images": [{"art": None, "anim": None, "music": None, "confirm": None}],
           "sound_move": None, "sound_confirm": None, "volume": 50,
           "tests": [{"file": "test0.mp4", "label": "Match", "kind": "video"}]}
    (d / "media.json").write_text(json.dumps(man), encoding="utf-8")
    sm.check_media_dir(str(d), log=lambda *a: None)


def test_the_menu_plays_a_clip_through_the_games_chain():
    """The C side, read: the menu lists a clip as a video and hands it to gstclip.c, which
    builds the game's own elements and loads GStreamer at run time (never linked)."""
    conf = _read(SEL, "conf.c")
    assert '!strcasecmp(dot, ".mp4")' in conf and "gif || padv || clip ? TK_VIDEO" in conf
    assert '".mp4"' in _read(SEL, "testpics.c")
    video = _read(SEL, "video.c")
    assert "if (gclip_is_clip(path))" in video and "if (v->gc) return gclip_frame" in video
    clip = _read(SEL, "gstclip.c")
    for el in ('"filesrc"', '"qtdemux"', '"queue"', '"vpudec"', '"fakesink"'):
        assert el in clip
    assert 'dlopen("libgstreamer-0.10.so.0", RTLD_NOW | RTLD_GLOBAL)' in clip
    assert "dlsym(RTLD_DEFAULT" in clip, "so a preloaded bridge's gst_* are the ones called"
    assert 'dlsym(RTLD_DEFAULT, "pad_vid_prepare")' in clip, "the bridge's stand-in caps are not read"
    make = _read(SEL, "Makefile")
    assert "-DPAD_GSTCLIP" in make and "-l:libdl.so.2 -l:libc.so.6 $(ROOT)/usr/lib/libc_nonshared.a" in make
    assert "libdl.so.2|" in _read(SEL, "test", "check_elf.sh")


def test_action_freezes_on_a_quick_press_and_backs_out_when_held():
    s = _read(SEL, "settings.c")
    assert "} else if (back && test_moves(st)) {" in s
    assert "now - st.t_act_down >= TEST_HOLD_BACK_MS" in s
    assert "st.t_frozen = !st.t_frozen;" in s
    assert "if (st->t_frozen) return 0;" in s
    assert "K_BACK \": freeze / play, hold: back\"" in s          # K_BACK is "ACTION" on Spike 2 (David's button names)
    assert "#define TEST_HOLD_BACK_MS 700" in _read(SEL, "settings.h")
