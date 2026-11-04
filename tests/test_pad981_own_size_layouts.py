"""PAD-981 (DoomWalrus666): "the portraits are very small now and the pop outs don't line up
with the battle grid".

His Kaiju Battle Select (the Heisei cards' look) has a grid frame grown 444x740 -> 544x840 and
seven portraits 527x725 -> 632x828, each centred by hand in the Scenes window over the picture
at its own size.  PAD-865 (v1.301.1) then fitted every picture kept at its own size back into
the original's box, inside the Scenes window's moves: the grid and portraits came out shrunk
AND still shifted up-left by the moves that centred the bigger picture, while the thumbnails
over the grid (pictures of the original size, never fitted) stayed where they were.  On the
real Heisei V2.1 scene that put the grid 27 px low and 100 px short and the portraits 120 px
off (``C:\\tmp\\PAD-981\\e2e.py``).

What holds now:

* ``scene_edits.json`` is stamped ``_fit`` by a version that fits; a file without the stamp
  was laid out over pictures at their own size, so every node it moves or resizes keeps its
  picture at that size (``_own``, carried on through every later save);
* the build (``radium_grow.keep_boxes``) and the Scenes preview leave those nodes unfitted;
* a node whose edits are reset is fitted like any other, and so is every node of a project
  first edited by a fitting version.
"""
import json
import os

import pytest

np = pytest.importorskip("numpy")
from PIL import Image                                               # noqa: E402

from pinball_decryptor.plugins.stern import (                       # noqa: E402
    engine, radium_grow, scene_edit, scene_eval, scene_render, scene_tree)
from tests.test_pad857_fill_keep_size import FILL, ICON, _scene      # noqa: E402
from tests.test_pad865_keep_size_in_box import _m6, _payload        # noqa: E402
from tests.test_stern_image_grow import _Reader                     # noqa: E402
from tests.test_stern_text_grow import RAD_PATH                     # noqa: E402

MOVE = {"op": "move", "node": 52, "dx": -8.0, "dy": -4.0}


def _write(assets, data):
    path = scene_edit.path_of(str(assets))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _raw(assets):
    with open(scene_edit.path_of(str(assets)), encoding="utf-8") as f:
        return json.load(f)


def test_a_file_from_before_the_fit_keeps_its_moved_nodes_at_own_size(tmp_path):
    _write(tmp_path, {"c": [MOVE, {"op": "visible", "node": 60, "on": False}]})
    assert scene_edit.own_size_nodes(str(tmp_path), "c") == {52}
    assert scene_edit.own_size_nodes(str(tmp_path), "other") == set()


def test_a_save_stamps_the_file_and_carries_the_old_layout_on(tmp_path):
    _write(tmp_path, {"c": [MOVE]})
    scene_edit.add(str(tmp_path), "c", {"op": "move", "node": 70, "dx": 1.0, "dy": 1.0})
    raw = _raw(tmp_path)
    assert raw["_fit"] == 1 and raw["_own"] == {"c": [52]}
    # 70 was moved by a version that fits: it is fitted
    assert scene_edit.own_size_nodes(str(tmp_path), "c") == {52}
    moved = {"op": "move", "node": 70, "dx": 1.0, "dy": 1.0}
    assert scene_edit.load(str(tmp_path)) == {"c": [MOVE, moved]}


def test_a_new_project_fits_everything(tmp_path):
    scene_edit.add(str(tmp_path), "c", dict(MOVE))
    assert _raw(tmp_path)["_fit"] == 1 and "_own" not in _raw(tmp_path)
    assert scene_edit.own_size_nodes(str(tmp_path), "c") == set()


def test_a_reset_node_is_fitted_again(tmp_path):
    _write(tmp_path, {"c": [MOVE, {"op": "move", "node": 70, "dx": 1.0, "dy": 1.0}]})
    scene_edit.reset_node(str(tmp_path), "c", 52)
    assert scene_edit.own_size_nodes(str(tmp_path), "c") == {70}


def test_keep_boxes_leaves_an_own_size_node():
    data, _fill, icon = _scene()
    grown = radium_grow.regrow(data, images={icon: (32, 16, _payload(32, 16))})["data"]
    out, n_nodes, _s, _l = radium_grow.keep_boxes(data, grown, [icon], own={52})
    assert n_nodes == 0 and out == grown
    assert radium_grow.keep_boxes(data, grown, [icon])[1] == 1


def test_the_build_keeps_an_old_layout_and_fits_a_new_one(tmp_path):
    data, _fill, icon = _scene()

    def build(edits):
        assets = tmp_path / ("a%d" % len(list(tmp_path.iterdir())))
        _write(assets, edits)
        reader = _Reader(RAD_PATH, data)
        node_ = next(reader.iter_regular_files())[2]
        jobs, _f = engine._stage_grown_radiums(
            reader, {RAD_PATH: (node_, {}, {icon: (32, 16, _payload(32, 16))})}, {},
            str(assets), lambda m, lvl="info": None,
            tree_ops={RAD_PATH: ([MOVE], {}, str(assets))}, assets_dir=str(assets))
        with open(jobs[0][1], "rb") as f:
            return _m6(scene_tree.parse(f.read()), 52)
    # laid out before the fit: the move as made, the picture at its own size
    assert build({RAD_PATH: [MOVE]}) == (1.0, 0.0, 0.0, 1.0, 0.0, 4.0)
    # by a version that fits: the picture at half, inside the move
    assert build({RAD_PATH: [MOVE], "_fit": 1}) == (0.5, 0.0, 0.0, 0.5, 0.0, 4.0)


def test_the_scenes_preview_draws_an_own_size_node_at_its_own_size(tmp_path):
    data, fill, icon = _scene()
    man = scene_eval.manifest(scene_tree.parse(data), {fill: "fill.png", icon: "icon.png"})
    _write(tmp_path, {"c": [{"op": "move", "node": 52, "dx": 0.0, "dy": 0.0}]})
    scene_edit.mark_own(man, scene_edit.own_size_nodes(str(tmp_path), "c"))
    tex = tmp_path / "images"
    Image.new("RGBA", FILL, (0, 0, 0, 0)).save(tex / "fill.png")
    Image.new("RGBA", ICON, (0, 0, 0, 0)).save(tex / "icon.png")
    pick = tmp_path / "big.png"
    Image.new("RGBA", (32, 16), (255, 0, 255, 255)).save(pick)
    img = scene_render.render_tree(str(tmp_path), man,
                                   pictures={"icon.png": {"path": str(pick), "keep": True}},
                                   sizes={"icon.png": ICON, "fill.png": FILL},
                                   background=(0, 0, 0))
    arr = np.asarray(img.convert("RGB")).astype(int)
    ys, xs = np.nonzero((arr[..., 0] > 128) & (arr[..., 2] > 128) & (arr[..., 1] < 64))
    # the 32x16 picture whole from the icon's corner (8, 8), not fitted into its 16x8 box
    assert (xs.min(), xs.max() + 1, ys.min(), ys.max() + 1) == (8, 40, 8, 24)
