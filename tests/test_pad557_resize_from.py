"""PAD-557 (DragonRR): "By DEFAULT please retain xy coord when scaling BUT include a button to
toggle to CENTER".  Resize from on the Scenes side panel: Top-left (the default) keeps the
layer's X and Y when Size %, Width %, Height % or W px / H px resize it; Middle keeps its
middle, as every resize did before.  A corner drag keeps the corner across from it (the point
the canvas sends).  The pick is kept in settings.json."""

import json

import pytest

from tests.webui_harness import web_app
from tests.test_gui_scene_editor import _open, _seed, _tv

pytest.importorskip("numpy")
pytest.importorskip("PIL")


def _art(w):
    art = next(h for h in _tv(w)["hits"] if h["name"] == "Art")["id"]
    assert w.call("text_scenes.tree_select", art)
    return art


def _box(w):
    p = _tv(w)["props"]
    return p["x"], p["y"], p["w"], p["h"]


def _near(a, b):
    return abs(a - b) <= 1


def test_top_left_is_the_default_and_keeps_x_and_y(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.state("text_scenes")["resize_from"] == "corner"
        art = _art(w)
        x, y, bw, bh = _box(w)
        for call in (("text_scenes.tree_set_scale", art, 60),
                     ("text_scenes.tree_set_size", art, 150, None),
                     ("text_scenes.tree_set_size", art, None, 40),
                     ("text_scenes.tree_set_pixels", art, 300, None, True),
                     ("text_scenes.tree_set_pixels", art, None, 90, False)):
            assert w.call(*call), call
            nx, ny, _nw, _nh = _box(w)
            assert _near(nx, x) and _near(ny, y), (call, (x, y), (nx, ny))
        nx, ny, nw, nh = _box(w)
        assert _near(nw, 300) and _near(nh, 90)
        w.call("text_scenes.close")


def test_middle_keeps_the_middle_and_is_kept_for_next_time(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_resize_from", "sideways") is False
        assert w.call("text_scenes.tree_resize_from", "middle")
        assert w.state("text_scenes")["resize_from"] == "middle"
        saved = json.loads((tmp_path / "cfg" / "settings.json").read_text(encoding="utf-8"))
        assert saved["scenes_resize_from"] == "middle"
        art = _art(w)
        x, y, bw, bh = _box(w)
        mid = (x + bw / 2.0, y + bh / 2.0)
        assert w.call("text_scenes.tree_set_scale", art, 50)
        x2, y2, bw2, bh2 = _box(w)
        assert _near(x2 + bw2 / 2.0, mid[0]) and _near(y2 + bh2 / 2.0, mid[1])
        assert not _near(x2, x)
        # back to Top-left: the next resize keeps X and Y again
        assert w.call("text_scenes.tree_resize_from", "corner")
        assert w.call("text_scenes.tree_set_scale", art, 100)
        x3, y3, _w3, _h3 = _box(w)
        assert _near(x3, x2) and _near(y3, y2)
        w.call("text_scenes.close")
    # a new session opens with Middle picked
    with web_app(tmp_path / "again", mfr="stern",
                 settings={"scenes_resize_from": "middle"}) as w:
        assert w.state("text_scenes")["resize_from"] == "middle"


def test_a_corner_drag_keeps_the_point_the_canvas_sends(tmp_path):
    """The canvas sends the corner across from the one dragged; that corner stays put."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        art = _art(w)
        x, y, bw, bh = _box(w)
        # the top-left handle dragged: the bottom-right corner stays
        assert w.call("text_scenes.tree_scale", art, 0.5, None, [x + bw, y + bh])
        x2, y2, bw2, bh2 = _box(w)
        assert _near(x2 + bw2, x + bw) and _near(y2 + bh2, y + bh)
        assert _near(bw2, bw / 2.0)
        w.call("text_scenes.close")
