"""PAD-1200 (DragonRR): a picture kept at its own size, far bigger than where it shows, came out
grainy and jagged in the emulator.

His Battle Select grid was a 2020x3070 PNG kept at its own size, which the Write fits into the
stock ~400x600 box (PAD-865): the game drew a 2020x3070 texture at about a fifth of its size.
The game samples a scene picture from one texture level with a LINEAR filter (no mipmaps), so
each pixel on the glass read one texel in about five each way.  PAD's own preview resized it
properly, so it looked clean there.

What holds now: the Write shrinks such a picture once, with a proper filter in premultiplied
colour, to twice the box it is fitted into (room left for where a scene zooms in), and it shows
in the same place and size.  A picture some place draws at its own size is left as it is.
"""
import pytest

np = pytest.importorskip("numpy")
from PIL import Image                                               # noqa: E402

from pinball_decryptor.plugins.stern import (                       # noqa: E402
    dds, engine, radium_grow, scene_edit, scene_tree)
from tests.test_pad857_fill_keep_size import FILL, ICON, _scene     # noqa: E402
from tests.test_pad865_keep_size_in_box import _m6                  # noqa: E402
from tests.test_stern_image_grow import _Reader, _project, _writes  # noqa: E402
from tests.test_stern_scene_tree import (                           # noqa: E402
    FLAG, cls, fs, mat, node, s, sprite, u8, u32, u64)
from tests.test_stern_text_grow import RAD_PATH                     # noqa: E402


def test_the_size_a_kept_picture_is_written_at():
    # DragonRR's grid: 2020x3070 into a ~400x608 box shows at ~0.2; written at twice that
    assert radium_grow.kept_texture_size(2020, 3070, [(400, 608)]) == (800, 1216)
    # twice the box or less is written as it is
    assert radium_grow.kept_texture_size(32, 16, [(16, 8)]) is None
    assert radium_grow.kept_texture_size(30, 10, [(16, 8)]) is None
    # the biggest box it is drawn in counts: a 64x32 fill box as well as the 16x8 picture
    assert radium_grow.kept_texture_size(640, 320, [(16, 8), (64, 32)]) == (128, 64)
    assert radium_grow.kept_texture_size(640, 320, []) is None


def _checker(w, h):
    """Black and white one-pixel squares: what a shrink without smoothing turns to noise."""
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[..., 3] = 255
    arr[(np.indices((h, w)).sum(axis=0) % 2) == 0, :3] = 255
    return Image.fromarray(arr, "RGBA")


def _kept(tmp_path, monkeypatch, off, size, pic, name):
    monkeypatch.setattr(engine, "_image_grow_gate", lambda d: (True, ""))
    data = _scene()[0]
    png = _project(tmp_path, data, off, *size, name=name)
    pic.save(png)
    writes, n, _ov, grown, msgs = _writes(tmp_path, _Reader(RAD_PATH, data))
    assert writes == [] and n == 1
    (_node, imgs), = grown.values()
    return data, imgs[off], msgs


def test_a_picture_ten_times_its_box_is_written_smoothed_at_twice_it(tmp_path, monkeypatch):
    _data, _fill, icon = _scene()
    data, (w, h, payload), msgs = _kept(tmp_path, monkeypatch, icon, ICON,
                                        _checker(160, 80), "icon")
    assert (w, h) == (32, 16)
    assert len(payload) == radium_grow.image_block_len(32, 16, 5)
    # every texel is the checkerboard's average grey, not black or white
    rgb = dds.decode_bc3(payload, 32, 16)[..., :3].astype(int)
    assert abs(rgb.mean() - 127.5) < 8 and rgb.std() < 12
    said = [m for _l, m in msgs if "written at 32x16 instead, smoothed" in m]
    assert len(said) == 1 and "160x80" in said[0]
    # and it shows where the stock icon did: the fit of a 32x16 picture into 16x8 is a half
    grown = radium_grow.regrow(data, images={icon: (w, h, payload)})["data"]
    out = radium_grow.keep_boxes(data, grown, [icon])[0]
    assert _m6(scene_tree.parse(out), 52) == (0.5, 0.0, 0.0, 0.5, 8.0, 8.0)


def test_a_clear_edge_does_not_darken_or_bleed(tmp_path, monkeypatch):
    """Resized in premultiplied colour: the clear half's (black) colour does not darken the
    opaque half, and the opaque half's colour does not tint the clear half."""
    _data, _fill, icon = _scene()
    arr = np.zeros((80, 160, 4), dtype=np.uint8)
    arr[:, :80] = (255, 255, 255, 255)
    arr[:, 80:] = (0, 0, 0, 0)
    _d, (w, h, payload), _m = _kept(tmp_path, monkeypatch, icon, ICON,
                                    Image.fromarray(arr, "RGBA"), "icon")
    dec = dds.decode_bc3(payload, w, h).astype(int)
    assert (w, h) == (32, 16)
    opaque, clear = dec[:, :14], dec[:, 18:]
    assert (opaque[..., 3] >= 248).all() and (opaque[..., :3] >= 240).all()
    assert (clear <= 8).all()


def test_up_to_twice_its_box_is_written_as_it_is(tmp_path, monkeypatch):
    _data, _fill, icon = _scene()
    _d, (w, h, _p), msgs = _kept(tmp_path, monkeypatch, icon, ICON, _checker(32, 16), "icon")
    assert (w, h) == (32, 16)
    assert not any("smoothed" in m for _l, m in msgs)


def test_a_fill_is_shrunk_to_twice_its_shape_box(tmp_path, monkeypatch):
    _data, fill, _icon = _scene()
    _d, (w, h, _p), msgs = _kept(tmp_path, monkeypatch, fill, FILL, _checker(640, 320), "fill")
    assert (w, h) == (128, 64)
    said = [m for _l, m in msgs if "box keeps its size" in m]
    assert len(said) == 1 and "128x64 pixels" in said[0]


def test_a_layout_made_over_its_own_size_keeps_it_whole(tmp_path, monkeypatch):
    """PAD-981: a node laid out over the picture at its own size draws it at that size, so a
    smaller texture would shrink it on the glass."""
    _data, _fill, icon = _scene()
    monkeypatch.setattr(scene_edit, "own_size_nodes", lambda d, c: frozenset({52}))
    _d, (w, h, _p), _m = _kept(tmp_path, monkeypatch, icon, ICON, _checker(160, 80), "icon")
    assert (w, h) == (160, 80)


def test_the_full_size_can_still_be_asked_for(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_KEEP_SIZE_FULL", "1")
    _data, _fill, icon = _scene()
    _d, (w, h, _p), _m = _kept(tmp_path, monkeypatch, icon, ICON, _checker(160, 80), "icon")
    assert (w, h) == (160, 80)


def test_a_node_drawing_something_else_too_is_not_fitted():
    """keep_boxes leaves such a node drawing the picture at its own size."""
    kids = [node(52, "Icon", [
        u32(1) + cls(1, "Bitmap") + u32(FLAG | 12) + u32(3) + s("") + u32(ICON[0])
        + u32(ICON[1]) + _texture(21, *ICON, (200, 40, 40, 255)),
        u32(20) + cls(1) + u32(FLAG | 13) + u32(3) + s("") + u32(ICON[0]) + u32(ICON[1])
        + _texture(22, *ICON, (40, 40, 200, 255))], tracks=((1, mat(1.0, 8, 8)),))]
    data = (u8(1) + u64(0) + u64(0) + u32(64) + u32(32) + fs(30.0)
            + fs(0, 0, 0, 1) + sprite(2, "", 30, kids))
    sc = scene_tree.parse(data)
    assert not radium_grow.every_draw_fitted(sc, {21})
    assert radium_grow.every_draw_fitted(scene_tree.parse(_scene()[0]), {21})
    assert not radium_grow.every_draw_fitted(scene_tree.parse(_scene()[0]), {21}, own={52})


def _texture(tid, w, h, rgba):
    from tests.test_pad857_fill_keep_size import _texture as t
    return t(tid, w, h, rgba)
