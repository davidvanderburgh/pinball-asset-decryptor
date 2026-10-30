"""PAD-865 (DragonRR): a picture kept at its own size shows in the original's place and size.

"When PAD loads in a larger image it will reset the size of the image in a scene to suit
this larger size.  What should happen: retain the original image's size and initially force
the larger image to fit within that size, keep the image centered in the same location."

Keep size grew the picture's Bitmap to the new size, and the game draws a Bitmap's texels
1:1 from its node's origin, so a 4x picture drew 4x as big from the original's top-left.
Measured in the emulator (stock Godzilla LE 1.16, the in-game Tokyo map's tank icon, 147x105
on a 150x106 texture): a 588x420 texture under the stock 147x105 Bitmap is CROPPED to its
top-left corner, so the Bitmap must keep the new size and its node is scaled back instead.
With :func:`radium_grow.keep_boxes` the whole 588x420 picture (and an 800x200 one, centred
top to bottom) drew in the stock icon's place.

What holds now:

* every node that draws a kept picture is scaled to fit it into the original's box, centred,
  over whatever the Scenes window did to the node;
* a Shape's fill keeps its box, narrowed to the picture's shape when that differs;
* a node that draws something else too is left alone, and counted;
* the build logs it, and the Scenes preview draws the picture where the build puts it.
"""
import pytest

np = pytest.importorskip("numpy")
from PIL import Image                                               # noqa: E402

from pinball_decryptor.plugins.stern import (                       # noqa: E402
    dds, engine, radium_grow, scene_edit, scene_eval, scene_render, scene_tree)
from tests.test_pad857_fill_keep_size import (                      # noqa: E402
    BOX2, FILL, ICON, STAGE, _scene, _texture)
from tests.test_stern_image_grow import _Reader                     # noqa: E402
from tests.test_stern_scene_tree import (                           # noqa: E402
    FLAG, cls, fs, mat, node, s, sprite, u8, u32, u64)
from tests.test_stern_text_grow import RAD_PATH                     # noqa: E402


def _payload(w, h):
    pw, ph = ((w + 3) // 4) * 4, ((h + 3) // 4) * 4
    arr = np.zeros((ph, pw, 4), dtype=np.uint8)
    arr[:h, :w] = (255, 0, 255, 255)
    return dds.encode_bc3(arr)


def _kept(data, off, w, h):
    """*data* with the picture at *off* grown to *w* x *h* (the build's regrow), then fitted
    back: ``(stock, grown, fitted bytes, n nodes, n shapes, n left)``."""
    grown = radium_grow.regrow(data, images={off: (w, h, _payload(w, h))})["data"]
    return (data, grown) + radium_grow.keep_boxes(data, grown, [off])


def _m6(sc, nid):
    n = scene_edit._tree_index(sc)[nid][0]
    return tuple(round(v, 4) for v in scene_edit._m6_of16(n.tracks[0][1]))


def test_fit_box_scales_to_fit_whole_and_centres():
    assert radium_grow.fit_box(64, 16, 16, 8) == (0.25, 0.0, 0.0, 0.25, 0.0, 2.0)
    assert radium_grow.fit_box(10, 40, 20, 20) == (0.5, 0.0, 0.0, 0.5, 7.5, 0.0)
    assert radium_grow.fit_box(32, 16, 16, 8) == (0.5, 0.0, 0.0, 0.5, 0.0, 0.0)


def test_a_kept_picture_twice_the_size_draws_in_the_original_box():
    _d, _g, out, n_nodes, n_shapes, n_left = _kept(*_scene()[::2], 32, 16)
    assert (n_nodes, n_shapes, n_left) == (1, 0, 0)
    sc = scene_tree.parse(out)
    bm, = [o for o in sc.objects.values() if o.kind == "Bitmap" and o.body["tex"] == 21]
    # the Bitmap keeps its new size (a smaller one would crop the texture) ...
    assert (bm.body["w"], bm.body["h"]) == (32, 16)
    # ... and its node draws it at half: the stock 16x8 icon's box at (8, 8)
    assert _m6(sc, 52) == (0.5, 0.0, 0.0, 0.5, 8.0, 8.0)


def test_a_wider_one_is_fitted_and_centred_top_to_bottom():
    _d, _g, out, n_nodes, _s, _l = _kept(*_scene()[::2], 64, 16)
    assert n_nodes == 1
    # 64x16 into 16x8: a quarter, 16x4, two pixels down from the box's top
    assert _m6(scene_tree.parse(out), 52) == (0.25, 0.0, 0.0, 0.25, 8.0, 10.0)


def test_a_fill_of_another_shape_is_narrowed_to_it_in_its_box():
    data, fill, _icon = _scene()
    _d, _g, out, n_nodes, n_shapes, _l = _kept(data, fill, 128, 32)
    assert (n_nodes, n_shapes) == (0, 2)
    boxes = sorted(tuple(o.body["rect"]) for o in scene_tree.parse(out).objects.values()
                   if o.kind == "Shape")
    # 128x32 into 64x32: 64x16, centred in each box
    assert boxes == [(0.0, 8.0, 64.0, 24.0),
                     (BOX2[0], BOX2[1] + 8, BOX2[2], BOX2[3] - 8)]


def test_a_fill_of_the_same_shape_keeps_its_box_as_it_was():
    data, fill, _icon = _scene()
    _d, grown, out, n_nodes, n_shapes, _l = _kept(data, fill, 128, 64)
    assert (n_nodes, n_shapes) == (0, 0) and out == grown       # PAD-857, unchanged


def test_a_node_that_draws_something_else_too_is_left_alone():
    """The tank icon's own nodes switch between pictures over their timeline; one that
    switches to a picture that was NOT kept would squeeze that one too."""
    kids = [node(52, "Icon", [
        u32(1) + cls(1, "Bitmap") + u32(FLAG | 12) + u32(3) + s("") + u32(ICON[0])
        + u32(ICON[1]) + _texture(21, *ICON, (200, 40, 40, 255)),
        u32(20) + cls(1) + u32(FLAG | 13) + u32(3) + s("") + u32(ICON[0]) + u32(ICON[1])
        + _texture(22, *ICON, (40, 40, 200, 255))], tracks=((1, mat(1.0, 8, 8)),))]
    data = (u8(1) + u64(0) + u64(0) + u32(STAGE[0]) + u32(STAGE[1]) + fs(30.0)
            + fs(0, 0, 0, 1) + sprite(2, "", 30, kids))
    icon = scene_tree.parse(data).textures[21]["data_off"]
    _d, grown, out, n_nodes, _s, n_left = _kept(data, icon, 32, 16)
    assert (n_nodes, n_left) == (0, 1) and out == grown


def test_the_preview_and_the_build_agree_over_a_scenes_resize():
    """The Scenes window scales the node about a point in its own units; the build fits the
    picture inside that, and the preview draws the picture fitted inside the same node."""
    data, _fill, icon = _scene()
    ops = [{"op": "scale", "node": 52, "s": 2.0, "px": 8.0, "py": 4.0},
           {"op": "move", "node": 52, "dx": 3.0, "dy": -1.0}]
    # the build: regrow, the Scenes edits, then the fit (engine._stage_grown_radiums)
    grown = radium_grow.regrow(data, images={icon: (64, 16, _payload(64, 16))})["data"]
    sc = scene_tree.parse(grown)
    applied, _notes = scene_edit.apply_scene(sc, ops)
    assert applied == 2
    out = radium_grow.keep_boxes(data, scene_tree.serialize(sc), [icon])[0]
    built = scene_tree.parse(out)
    d_built, = [d for d in scene_eval.draw_list(scene_eval.manifest(
        built, {built.textures[21]["data_off"]: "icon.png"})) if d.get("image") == "icon.png"]
    # the preview: the stock scene with the same edits, the picture fitted in its draw
    stock = scene_tree.parse(data)
    man = scene_edit.apply_manifest(scene_eval.manifest(stock, {icon: "icon.png"}), ops)[0]
    d_prev, = [d for d in scene_eval.draw_list(man) if d.get("image") == "icon.png"]
    want = scene_eval.compose(d_prev["m"], radium_grow.fit_box(64, 16, d_prev["w"],
                                                                d_prev["h"]))
    assert [round(v, 4) for v in d_built["m"]] == [round(v, 4) for v in want]


def test_the_scenes_preview_draws_a_kept_picture_in_the_original_box(tmp_path):
    data, fill, icon = _scene()
    man = scene_eval.manifest(scene_tree.parse(data), {fill: "fill.png", icon: "icon.png"})
    tex = tmp_path / "images"
    tex.mkdir()
    Image.new("RGBA", FILL, (0, 0, 0, 0)).save(tex / "fill.png")
    Image.new("RGBA", ICON, (0, 0, 0, 0)).save(tex / "icon.png")
    pick = tmp_path / "big.png"
    Image.new("RGBA", (64, 16), (255, 0, 255, 255)).save(pick)
    pictures = {"icon.png": {"path": str(pick), "keep": True}}
    sizes = {"icon.png": ICON, "fill.png": FILL}
    img = scene_render.render_tree(str(tmp_path), man, pictures=pictures, sizes=sizes,
                                   background=(0, 0, 0))
    arr = np.asarray(img.convert("RGB")).astype(int)
    ys, xs = np.nonzero((arr[..., 0] > 128) & (arr[..., 2] > 128) & (arr[..., 1] < 64))
    # the 16x8 icon box at (8, 8); the 64x16 picture fitted: 16x4 at (8, 10)
    assert (xs.min(), xs.max() + 1, ys.min(), ys.max() + 1) == (8, 24, 10, 14)


def test_the_build_fits_it_and_says_so(tmp_path):
    data, _fill, icon = _scene()
    reader = _Reader(RAD_PATH, data)
    node_ = next(reader.iter_regular_files())[2]
    msgs = []
    jobs, _files = engine._stage_grown_radiums(
        reader, {RAD_PATH: (node_, {}, {icon: (32, 16, _payload(32, 16))})}, {},
        str(tmp_path), lambda m, lvl="info": msgs.append((lvl, m)))
    (_rel, staged), = jobs
    with open(staged, "rb") as f:
        sc = scene_tree.parse(f.read())
    assert _m6(sc, 52) == (0.5, 0.0, 0.0, 0.5, 8.0, 8.0)
    said = [m for lvl, m in msgs if "fitted and centered" in m]
    assert len(said) == 1 and "1 place(s)" in said[0] and lvl_of(msgs, said[0]) == "info"


def lvl_of(msgs, text):
    return next(lvl for lvl, m in msgs if m == text)
