"""The LAYERED TEST: a clip with the game's scenes over it (Simon, 2026-11-22/23).

Simon: "do the overlay with the match video and you may as well do the correct overlay too".
PAD renders the scenes (plugins/stern/layered_test.py) into a .pado beside the clip; the test
card's menu (codeselect/overlay.c) draws the frame for the clip's time over it.  This file pins
the file format both sides read, the media set and card builder carrying it, and the C side's
hooks; the emulator run is in the PR text (Godzilla 1.16 Match: MATCH, the digit zooming in, the
score panel at its MatchFrame).
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.join(os.path.dirname(HERE), "tools", "spike2_emu")
SEL = os.path.join(RIG, "codeselect")

from pinball_decryptor.plugins.stern import layered_test as lt  # noqa: E402


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


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def _frames():
    from PIL import Image
    blank = Image.new("RGBA", (64, 48), (0, 0, 0, 0))
    word = blank.copy()
    word.paste((255, 128, 0, 255), (4, 4, 20, 12))
    zoom = word.copy()
    zoom.paste((255, 255, 255, 200), (30, 20, 50, 40))
    return [blank, word, word, word, zoom, zoom]


def test_equal_frames_share_one_cropped_picture(tmp_path):
    out = str(tmp_path / "t.pado")
    n, npics, size = lt.write_pado(_frames(), 30.0, out)
    assert (n, npics) == (6, 2) and size == os.path.getsize(out)
    got = lt.read_pado(out)
    assert got["canvas"] == (64, 48) and got["fps"] == 30.0 and got["frames"] == 6
    assert got["table"] == [lt.NONE, 0, 0, 0, 1, 1]
    (x0, y0, png0), (x1, y1, png1) = got["pictures"]
    assert (x0, y0) == (4, 4)                     # cropped to what it draws
    from io import BytesIO
    from PIL import Image
    assert Image.open(BytesIO(png0)).size == (16, 8)
    assert Image.open(BytesIO(png1)).size == (46, 36) and (x1, y1) == (4, 4)


def test_the_header_is_what_overlay_h_says(tmp_path):
    out = str(tmp_path / "t.pado")
    lt.write_pado(_frames(), 29.97, out)
    with open(out, "rb") as f:
        head = f.read(32)
    import struct
    assert head[:8] == b"PADOVL01"
    w, h, fps, n, npics, zero = struct.unpack("<IIIIII", head[8:])
    assert (w, h, fps, n, npics, zero) == (64, 48, 29970, 6, 2, 0)
    h_text = _read(SEL, "overlay.h")
    assert '#define OVL_MAGIC "PADOVL01"' in h_text and "#define OVL_HEADER 32" in h_text


def test_a_canvas_bigger_than_the_screen_is_refused(tmp_path):
    from PIL import Image
    big = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    with pytest.raises(lt.Refused, match="1920x1080"):
        lt.write_pado([big], 30.0, str(tmp_path / "t.pado"))


def test_a_scene_is_named_by_its_hash_and_pinned_by_frame_or_label():
    assert lt.parse_scene("0335207f") == ("0335207f", None)
    assert lt.parse_scene("9D578751@MatchFrame") == ("9d578751", "MatchFrame")
    with pytest.raises(lt.Refused):
        lt.parse_scene("match")
    man = {"root": {"labels": [["MatchFrame", 5], ["Player1", 1]]}}
    assert lt.pin_frame(man, "MatchFrame") == 5 and lt.pin_frame(man, "7") == 7
    assert lt.pin_frame(man, None) is None
    with pytest.raises(lt.Refused, match="MatchFrame, Player1"):
        lt.pin_frame(man, "Nope")
    tree = {"/godzilla_le/assets/lcd/demand_loaded/0335207f5e84/scene.radium": {"m": 1},
            "/godzilla_le/assets/lcd/auto_loaded/9d57875196c6/scene.radium": {"m": 2}}
    assert lt.find_scene(tree, "0335207f")[1] == {"m": 1}
    with pytest.raises(lt.Refused, match="no scene"):
        lt.find_scene(tree, "abcdef12")


def _media(tmp_path, overlay=True):
    d = tmp_path / "media"
    d.mkdir()
    with open(str(d / "test0.mp4"), "wb") as f:
        f.write(b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 64)
    lt.write_pado(_frames(), 30.0, str(d / "test0.pado"))
    t = {"file": "test0.mp4", "label": "Match", "kind": "video"}
    if overlay:
        t["overlay"] = "test0.pado"
    man = {"images": [{"art": None, "anim": None, "music": None, "confirm": None}],
           "sound_move": None, "sound_confirm": None, "volume": 50, "tests": [t]}
    (d / "media.json").write_text(json.dumps(man), encoding="utf-8")
    return str(d)


def test_the_media_set_carries_the_overlay_with_its_video(sm, tmp_path):
    d = _media(tmp_path)
    m = sm.check_media_dir(d, log=lambda *a: None)
    assert "test0.pado" in sm.manifest_files(m) and "test0.pado" in sm.test_card_files(m)
    # only a TEST CARD video's, under the video's own name
    bad = json.loads(open(os.path.join(d, "media.json")).read())
    bad["tests"][0]["overlay"] = "other.pado"
    with pytest.raises(sm.Refused, match="overlay"):
        sm.validate_manifest(bad)


def test_the_card_builder_puts_the_overlay_with_the_test_files(mk, tmp_path):
    d = _media(tmp_path)
    media = mk.plan_media(d, 1, tests_apart=True)
    assert set(media["test_files"]) == {"test0.mp4", "test0.pado"}
    assert media["tests"] == [("test0.mp4", "Match", "video", None)]   # never in the conf
    bad = str(tmp_path / "x.pado")
    with open(bad, "wb") as f:
        f.write(b"nope")
    with pytest.raises(mk.Refused, match="not a scene overlay"):
        mk.check_media_file(bad, "pado")


def test_the_menu_draws_the_scene_over_the_clip():
    s = _read(SEL, "settings.c")
    assert 'strcpy(dot, ".pado");' in s and "ovl_open(snd, e->g->w, e->g->h" in s
    assert "ovl_at(st->t_ovl, scene_ms(st, now), &x, &y)" in s
    assert "    return now - st->t_vstart;" in s           # a .padv / the CPU path: the clock
    assert "st->t_vstart = now;                      /* the scene over it starts again too */" in s
    assert "if (st->t_ovl) { ovl_close(st->t_ovl); st->t_ovl = NULL; }" in s
    c = _read(SEL, "overlay.c")
    assert "art_jpeg_decode(" in c, "stb_image reads the PNGs (STBI_ONLY_PNG is in art.c)"
    # the table (2026-11-25): ~100 ms a whole-screen PNG on the Cortex-A9 each time the scene
    # changed picture - every picture is decoded once, when the overlay opens
    assert "overlay: %d pictures decoded in %lld ms" in c
    at = c[c.index("const struct art_image *ovl_at("):]
    assert "art_jpeg_decode(" not in at[:at.index("\n}\n")]
    make = _read(SEL, "Makefile")
    assert make.count("gstclip.c overlay.c") == 5 and make.count("gstclip.h overlay.h") == 5
    assert "codeselect/overlay.c codeselect/overlay.h" in _read(RIG, "padpath.sh")


def test_the_demuxers_video_pad_is_linked_when_it_appears():
    """The table, 2026-11-25 ("the decoder gave no picture size"): linking all five elements at
    once stops at qtdemux on a real GStreamer 0.10 - its pad is made once the file is read - so
    nothing reached vpudec.  The game links "video_00" by hand on "pad-added"; so does the menu."""
    c = _read(SEL, "gstclip.c")
    assert 'G.signal_connect(g->demux, "pad-added", (void *)on_pad_added, g, NULL, 0);' in c
    assert "G.link_many(g->src, g->demux, NULL)" in c
    assert "G.link_many(g->queue, g->dec, g->sink, NULL)" in c
    assert "G.link_many(g->src, g->demux, g->queue" not in c
    assert 'strncmp(name, "video", 5)' in c and "G.pad_link(pad, sinkpad)" in c
    for s in ('sym("gst_pad_link")', 'sym("gst_object_get_name")', 'sym("g_free")'):
        assert s in c


def test_a_frames_colour_conversion_has_no_divide_per_pixel():
    """The table, 2026-11-25 (Simon: "work but only at 1.4FPS"): a 64-bit divide per pixel is a
    library call on the Cortex-A9.  The column map is made once a clip."""
    c = _read(SEL, "gstclip.c")
    conv = c[c.index("static void convert(struct gclip *g"):c.index("/* fakesink's \"handoff\"")]
    inner = conv[conv.index("for (x = 0; x < g->ow; x++) {"):]
    assert "/" not in inner.split("o += 4;")[0], "nothing divides inside the pixel loop"
    assert "int sx = xm[x];" in inner
    assert "g->xmap[x] = (int)((long long)x * g->w / g->ow);" in c
    assert '"clip: %lld frames: copy %lld ms, convert %lld ms a frame (%s)"' in c
    # and it reads a cached copy: the decoder's frames are uncached (ffmpegcolorspace: 470 ms)
    assert "memcpy(g->raw[back], px, size);" in c
    assert "if (want) convert(g, g->raw_size[back] ? g->raw[back] : px, size, g->px[back]);" in c


def test_the_graphics_chip_converts_a_clip():
    """The table, 2026-11-25: 10 fps with the CPU converting (64 ms a 1360x768 frame).  The game
    hands vpudec's frames to the GPU; the menu uploads the YUV planes and a shader converts them,
    drawn under the canvas, which is see-through where the clip shows.  Emulator: 30.0 of 30 fps."""
    g = _read(SEL, "gstclip.c")
    assert "int gclip_yuv_take(struct gclip *g, struct gclip_yuv *f)" in g
    assert "if (back == g->held) {" in g, "no copy goes into the frame being uploaded"
    e = _read(SEL, "egl_stern.c")
    assert "int egl_stern_video(struct egl_stern *e" in e
    assert "video_plane(e, 1, GL_LUMINANCE_ALPHA, stride / 2, rows / 2, u, remake);" in e   # NV12
    assert "1.1640625 * (texture(ty, TexCoords).r - 0.0627451)" in e   # gstclip.c's 298/256
    frame = e[e.index("void egl_stern_frame("):]
    assert frame.index("if (e->y_on)") < frame.index("glBindTexture(GL_TEXTURE_2D, e->tex);")
    for other in ("egl_x11.c", "egl_kms.c", "fb_linux.c"):
        assert "int egl_stern_video(" in _read(SEL, other) and "return -1;" in _read(SEL, other)
    s = _read(SEL, "settings.c")
    assert "return st->t_gpu && st->t_vid && st->t_col < 0 && !st->t_err[0];" in s, \
        "a colour correction is the CPU's LUT: the CPU draws the clip then"
    assert "gfx_clear(e->g, (W - st->t_vw) / 2, (H - st->t_vh) / 2, st->t_vw, st->t_vh);" in s
    assert "== st->t_ovl_shown) return;" in s, "the canvas changes only with the scene's picture"
    c = _read(SEL, "codeselect.c")
    assert c.count("se.video = video_cb;") == 3 and 'getenv("CODESELECT_VIDEO_CPU")' in c
    gfx = _read(SEL, "gfx.c")
    assert "void gfx_clear(struct gfx *g" in gfx and "if (p[3] != 0xff) {" in gfx


def test_vivantes_direct_texture_first_as_the_game_does():
    """The table, 2026-11-25: the one-channel textures went up at ~40 ms a frame (20 fps).  The
    game asks vpudec for I420 and writes it into a Vivante direct texture; so does the menu, the
    shader staying for a machine without it.  Emulator (the bridge answers): 30 fps."""
    e = _read(SEL, "egl_stern.c")
    assert 'eglGetProcAddress("glTexDirectVIV")' in e and 'eglGetProcAddress("glTexDirectInvalidateVIV")' in e
    assert "#define GL_VIV_I420        0x8FC5" in e
    assert "e->v_on = video_direct(e, data, fourcc, w, h, stride, rows) == 0;" in e
    assert "p_viv_inval(GL_TEXTURE_2D);" in e
    g = _read(SEL, "gstclip.c")
    assert 'G.object_set(g->dec, "output-format", 1, NULL);' in g


def test_the_scene_follows_the_clips_own_frame():
    """The table, 2026-11-25: timed by the clock, the scene ran ahead of a clip a little behind its
    pace.  Each copy carries its frame number since the clip started; the caption's fps restarts
    with the clip too ("200FPS")."""
    g = _read(SEL, "gstclip.c")
    assert "k = g->pos++;" in g and "g->raw_k[back] = k;" in g and "f->k = g->raw_k[i];" in g
    assert "g->pos = 0;" in g and "g->shown = g->dropped = 0;" in g
    s = _read(SEL, "settings.c")
    assert "return (long long)((double)st->t_vk * 1000.0 / vid_fps(st->t_vid));" in s
    assert "im = ovl_at(st->t_ovl, scene_ms(st, now), &x, &y);" in s


def test_closing_a_clip_waits_for_a_frame_under_way():
    """2026-11-23: backing out of a clip crashed the menu in the emulator - its video bridge
    handed a frame over after set_state(NULL) - so the close waits, and a late frame leaves."""
    c = _read(SEL, "gstclip.c")
    assert "if (g->closing) { pthread_mutex_unlock(&g->mu); return; }" in c
    assert "busy = g->in_cb;" in c
    close = c[c.index("void gclip_close(struct gclip *g)\n{\n    long long until;"):]
    close = close[:close.index("\n}\n")]
    assert "free(g);" not in close, "a late handoff must find the record"
