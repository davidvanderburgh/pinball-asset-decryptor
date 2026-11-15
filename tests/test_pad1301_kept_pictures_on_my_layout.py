"""PAD-1301, round 2 (DoomWalrus666 and DragonRR): DragonRR's Kaiju Battle Select file, made on
a card built from Nathan's own edits, now goes on top of them, and still came out wrong on
Nathan's PC: the monster card filled the screen.

Nathan's own edits of that scene predate PAD-865, so the nodes he moved over his 632x828
portraits keep drawing a picture kept at its own size at that size (PAD-981, ``_own``).
DragonRR's file replaces those portraits with 4000x2860 pictures, kept at their own size: on
his project (no ``_own``) each is fitted into the portrait's 632x828 box, on Nathan's it was
drawn 4000x2860.  His title, standing for Nathan's 2048x683 added logo, was likewise kept at
4211x602 and drew twice as wide.

What holds now:

* before a game picture is replaced (a file loaded, or a pick on the Images tab), each such
  own-size node keeps the size of the picture it draws as its box (``_own_box``), and a
  picture of another size is fitted and centred in it, in the preview and the build;
* a Shape's fill is fitted into the Shape by the build whoever laid it out, so the preview
  no longer draws it at its own size either (DragonRR's 6573x3712 monitor drew 5x);
* a picture kept at its own size standing for an added picture of mine is fitted and centred
  in the add's own box, which the add's moves and resizes were made over.
"""
import io
import json
import os
import types
import zipfile

import pytest

np = pytest.importorskip("numpy")
from PIL import Image                                               # noqa: E402

from pinball_decryptor.core import staged_changes                   # noqa: E402
from pinball_decryptor.plugins.stern import (                       # noqa: E402
    engine, radium_grow, scene_edit as X, scene_eval, scene_render, scene_share as S,
    scene_tree)
from tests.test_gui_scene_editor import CARD, _seed                 # noqa: E402
from tests.test_pad857_fill_keep_size import ICON, _scene            # noqa: E402
from tests.test_pad865_keep_size_in_box import _m6, _payload        # noqa: E402
from tests.test_stern_image_grow import _Reader                     # noqa: E402
from tests.test_stern_text_grow import RAD_PATH                     # noqa: E402

REL = "images/scene_textures/pic_21.png"          # node 50's 16x8 picture
MOVE = {"op": "move", "node": 50, "dx": 4.0, "dy": 2.0}
MAGENTA = (255, 0, 255, 255)


def _old_layout(proj, card=CARD, ops=(MOVE,)):
    """A scene edits file from before PAD-865: its moved nodes were laid out over their
    pictures at their own size."""
    path = X.path_of(str(proj))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({card: list(ops)}, f)


def _png(path, size, colour=MAGENTA):
    Image.new("RGBA", size, colour).save(str(path))
    return str(path)


def _file(tmp_path, size, keep=True, rel=REL):
    buf = io.BytesIO()
    Image.new("RGBA", size, MAGENTA).save(buf, "PNG")
    zp = tmp_path / "theirs.zip"
    with zipfile.ZipFile(str(zp), "w") as z:
        z.writestr("pad_scene_edits.json", json.dumps({"format": 1, "kind": "pad-scene-edits",
                                                       "scenes": {}}))
        z.writestr("pictures/CARD.png", buf.getvalue())
    extras = {"pictures": {rel: {"file": "pictures/CARD.png", "name": "CARD.png", "keep": keep}},
              "added": {}, "colored": {}, "lines": {}, "overlay": None, "text": []}
    return str(zp), extras


def _extent(proj, pick, keep=True):
    """Where node 50 draws *pick* in the Scenes preview: (x0, x1, y0, y1)."""
    with open(os.path.join(proj, "images", "scene_textures", "scene_tree.json"),
              encoding="utf-8") as f:
        man = json.load(f)[CARD]
    ed, _n = X.apply_manifest(man, X.to_apply(proj, CARD, man))
    X.mark_own_of(ed, proj, CARD)
    img = scene_render.render_tree(
        proj, ed, pictures={REL[len("images/"):]: {"path": pick, "keep": keep}},
        sizes=scene_render.picture_sizes(proj), background=(0, 0, 0))
    arr = np.asarray(img.convert("RGB")).astype(int)
    ys, xs = np.nonzero((arr[..., 0] > 120) & (arr[..., 2] > 120) & (arr[..., 1] < 60))
    return xs.min(), xs.max() + 1, ys.min(), ys.max() + 1


def test_a_loaded_picture_keeps_the_box_my_layout_was_made_over(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    _seed(proj)
    proj = str(proj)
    _old_layout(proj)
    assert X.own_size_nodes(proj, CARD) == {50}
    # my own picture there, 24x12, kept at its own size: the layout was made over it
    mine = _png(os.path.join(proj, "mine.png"), (24, 12))
    staged_changes.save(proj, {"image": {REL: mine}, "image_keep_size": [REL]})
    laid_out = _extent(proj, mine)
    zp, extras = _file(tmp_path, (96, 24))          # theirs: twice as wide for its height
    loaded, gone = S.import_extras(proj, zp, extras, cards_here=[CARD])
    assert loaded == [REL] and gone == []
    assert X.own_boxes(proj, CARD) == {50: (24, 12)}
    pick = (staged_changes.load(proj) or {})["image"][REL]
    x0, x1, y0, y1 = _extent(proj, pick)
    # fitted and centred in my picture's box: as wide, half as tall, not drawn 96x24
    assert (x0, x1) == laid_out[:2]
    assert (y1 - y0) * 2 == laid_out[3] - laid_out[2]
    assert y0 - laid_out[2] == laid_out[3] - y1
    # the box is the first picture's: loading again, or picking anew, does not move it
    S.pin_own_boxes(proj, [REL], {REL: pick}, {REL})
    assert X.own_boxes(proj, CARD) == {50: (24, 12)}


def test_without_a_pick_the_box_is_the_pictures_own(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    _seed(proj)
    proj = str(proj)
    _old_layout(proj)
    # the project's own file, as a Write left it, at its own size
    _png(os.path.join(proj, "images", "scene_textures", "pic_21.png"), (20, 12))
    S.pin_own_boxes(proj, [REL], {}, set())
    assert X.own_boxes(proj, CARD) == {50: (20, 12)}


def test_a_pick_that_is_gone_falls_back_to_the_projects_file(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    _seed(proj)
    proj = str(proj)
    _old_layout(proj)
    _png(os.path.join(proj, "images", "scene_textures", "pic_21.png"), (20, 12))
    S.pin_own_boxes(proj, [REL], {REL: os.path.join(proj, "moved away.png")}, {REL})
    assert X.own_boxes(proj, CARD) == {50: (20, 12)}


def test_a_node_fitted_anyway_gets_no_box(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    _seed(proj)
    proj = str(proj)
    X.save(proj, {CARD: [MOVE]})                    # laid out by a version that fits
    S.pin_own_boxes(proj, [REL], {}, set())
    assert X.own_boxes(proj, CARD) == {} and "_own_box" not in json.load(
        open(X.path_of(proj), encoding="utf-8"))


def test_the_images_tab_keeps_the_box_before_a_new_pick(tmp_path):
    from pinball_decryptor.webui.tabs.images import ImagesTab
    proj = tmp_path / "p"
    proj.mkdir()
    _seed(proj)
    proj = str(proj)
    _old_layout(proj)
    mine = _png(os.path.join(proj, "mine.png"), (24, 12))
    data = {"image": {REL: mine}, "image_keep_size": [REL]}
    big = _png(os.path.join(proj, "big.png"), (96, 24))
    tab = types.SimpleNamespace(_assignments={REL: big}, _keep_size={REL})
    ImagesTab._pin_own_boxes(tab, proj, data)
    assert X.own_boxes(proj, CARD) == {50: (24, 12)}


def test_a_save_carries_the_boxes_and_a_reset_node_drops_its_box(tmp_path):
    _old_layout(tmp_path, "c", [{"op": "move", "node": 52, "dx": 1.0, "dy": 1.0},
                                {"op": "move", "node": 70, "dx": 1.0, "dy": 1.0}])
    X.pin_own_boxes(str(tmp_path), {"c": {52: (24, 12), 70: (8, 8)}})
    X.add(str(tmp_path), "c", {"op": "visible", "node": 60, "on": False})
    assert X.own_boxes(str(tmp_path), "c") == {52: (24, 12), 70: (8, 8)}
    X.reset_node(str(tmp_path), "c", 52)
    assert X.own_boxes(str(tmp_path), "c") == {70: (8, 8)}


def test_the_build_fits_an_own_size_node_into_its_box(tmp_path):
    data, _fill, icon = _scene()
    grown = radium_grow.regrow(data, images={icon: (32, 16, _payload(32, 16))})["data"]
    # its box the stock size: as a node fitted from the start
    fitted = radium_grow.keep_boxes(data, grown, [icon])
    got = radium_grow.keep_boxes(data, grown, [icon], own={52}, own_boxes={52: ICON})
    assert got[1] == 1 and got[0] == fitted[0]
    # its box the picture's size: drawn as it is
    assert radium_grow.keep_boxes(data, grown, [icon], own={52},
                                  own_boxes={52: (32, 16)})[1] == 0

    def build(edits):
        assets = tmp_path / ("a%d" % len(list(tmp_path.iterdir())))
        path = X.path_of(str(assets))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(edits, f)
        reader = _Reader(RAD_PATH, data)
        node_ = next(reader.iter_regular_files())[2]
        mv = {"op": "move", "node": 52, "dx": -8.0, "dy": -4.0}
        jobs, _f = engine._stage_grown_radiums(
            reader, {RAD_PATH: (node_, {}, {icon: (32, 16, _payload(32, 16))})}, {},
            str(assets), lambda m, lvl="info": None,
            tree_ops={RAD_PATH: ([mv], {}, str(assets))}, assets_dir=str(assets))
        with open(jobs[0][1], "rb") as f:
            return _m6(scene_tree.parse(f.read()), 52)
    mv = {"op": "move", "node": 52, "dx": -8.0, "dy": -4.0}
    # laid out over its 16x8 picture before the fit, that picture since replaced by 32x16
    assert build({RAD_PATH: [mv], "_own_box": {RAD_PATH: {"52": list(ICON)}}}) == (
        0.5, 0.0, 0.0, 0.5, 0.0, 4.0)
    # no box: at its own size, as PAD-981 left it
    assert build({RAD_PATH: [mv]}) == (1.0, 0.0, 0.0, 1.0, 0.0, 4.0)


def test_a_shape_fill_is_never_drawn_at_its_own_size():
    data, fill, icon = _scene()
    man = scene_eval.manifest(scene_tree.parse(data), {fill: "fill.png", icon: "icon.png"})
    ids = {n["id"] for n, _s in X._man_index(man).values()}
    X.mark_own(man, ids, {i: (99, 99) for i in ids})
    draws = scene_eval.draw_list(man, 1)
    fills = [d for d in draws if d.get("image") == "fill.png"]
    icons = [d for d in draws if d.get("image") == "icon.png"]
    assert fills and not any(d.get("own") or d.get("own_box") for d in fills)
    assert icons and all(d.get("own") and d.get("own_box") == [99, 99] for d in icons)


def test_their_kept_picture_for_my_add_fits_in_the_adds_box(tmp_path):
    from tests.test_pad1301_file_from_my_built_card import CARD as C, _mine, _project
    proj = _project(tmp_path)
    X.save(proj, {C: _mine()})
    zp, extras = _file(tmp_path, (60, 4), rel="images/scene_textures/added/Logo1_1.png")
    S.import_extras(proj, zp, extras, cards_here=[C])
    op = X.load(proj)[C][3]
    assert (op["w"], op["h"]) == (30, 8) and op["image"] == "scene_textures/added/Logo1_2.png"
    with Image.open(os.path.join(proj, "images", *op["image"].split("/"))) as im:
        im = im.convert("RGBA")
        assert im.size == (30, 8)
        # 60x4 fitted: 30x2, centred
        assert im.getpixel((15, 0))[3] == 0 and im.getpixel((15, 7))[3] == 0
        assert im.getpixel((0, 4))[:3] == (255, 0, 255) and im.getpixel((29, 3))[3] > 200
