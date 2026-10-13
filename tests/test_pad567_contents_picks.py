"""PAD-567 (DragonRR): "Currently when any of the items in the list is selected it does
nothing ... I would like to FAST select the graphic on the preview screen and pop it into
the foreground."  In the scene editor a Contents row picks its layer, which the preview
draws on top while it is picked; the same row again goes on to the next layer that uses it.
And the list is one column, each picture row starting with a small copy of the picture."""

import os

import pytest

from tests.test_gui_scene_editor import CARD, _seed, _open, _tv
from tests.webui_harness import web_app

pytest.importorskip("PIL")

_JS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                   "webui", "static", "js", "tabs", "text_scenes.js")


def _project(tmp_path):
    from pinball_decryptor.core import text_manifest
    folder = tmp_path / "proj"
    folder.mkdir()
    man = _seed(folder)
    text_manifest.save(str(folder), [{"path": CARD, "original": "KAIJU", "replacement": ""}])
    return folder, man


def _row(w, group, pred):
    sc = w.state("text_scenes")
    g = next(g for g in sc["contents"]["groups"] if g["key"] == group)
    return next(it for it in g["items"] if pred(it))


def _named(w, name):
    return next(h for h in _tv(w)["hits"] if h["name"] == name)["id"]


def test_a_picture_row_picks_its_layer_and_carries_its_picture(tmp_path):
    folder, man = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        art = _named(w, "Art")
        rel = next(o["image"] for o in man["objects"].values()
                   if o.get("kind") == "Bitmap" and o.get("image"))
        row = _row(w, "img", lambda it: it["id"] == "img::images/" + rel)
        # its own picture, small, at the start of the row
        assert row["thumb"] and os.path.isfile(row["thumb"])
        assert row["thumb"].replace("\\", "/").endswith(rel)
        assert _tv(w)["sel"] is None
        assert w.call("text_scenes.select_item", row["id"]) is True
        assert _tv(w)["sel"] == art
        assert w.state("text_scenes")["item"] == row["id"]
        # picked again: still the only layer that draws it
        assert w.call("text_scenes.select_item", row["id"]) is True
        assert _tv(w)["sel"] == art
        # the list drawn again for the same scene (the Text tab's scan ends) keeps the row
        svc = w.window.service("text").scenes
        w.run(svc.text_edits_changed)
        assert w.state("text_scenes")["item"] == row["id"]
        # the scene picked again in the scene list: nothing in it is picked
        w.call("text_scenes.select", "/g/scene1")
        assert w.state("text_scenes")["item"] is None
        w.call("text_scenes.close")


def test_a_text_row_picks_its_line(tmp_path):
    folder, _man = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        title = _named(w, "Title")
        row = _row(w, "txt", lambda it: it["text"] == "KAIJU")
        assert w.call("text_scenes.select_item", row["id"]) is True
        assert _tv(w)["sel"] == title
        sc = w.state("text_scenes")
        assert sc["item"] == row["id"] and sc["find"]["pos"] == 1
        w.call("text_scenes.close")


def test_rows_map_to_every_layer_that_uses_them_in_turn(tmp_path):
    """The mapping itself: a picture drawn by two layers gives both, in drawing order, and a
    second pick of the row goes to the next; a font gives its lines; a video its layer."""
    folder, _man = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _open(w, folder)
        man = {"objects": {
            "1": {"kind": "Bitmap", "image": "scene_textures/a.png"},
            "2": {"kind": "Shape", "rect": [0, 0, 1, 1], "fill": 1},
            "3": {"kind": "Sprite", "kids": [{"id": 30, "name": "inner", "comps": [[0, 1]]}]},
            "4": {"kind": "Text", "text": "HI", "font": "radimg_F_512x512_aa"},
            "5": {"kind": "Video", "name": "v", "w": 1, "h": 1, "clips": ["Tokyo_Loop"]},
        }, "root": {"kids": [
            {"id": 10, "name": "pic", "comps": [[0, 1]]},
            {"id": 11, "name": "shape", "comps": [[0, 2]]},
            {"id": 12, "name": "group", "comps": [[0, 3]]},
            {"id": 13, "name": "words", "comps": [[0, 4]]},
            {"id": 14, "name": "tv", "comps": [[0, 5]]}]}}

        def nodes(iid):
            def go():
                svc._tman = man
                return svc._tree_item_nodes(iid)
            return w.run(go)
        # the group holding the picture is not picked while a layer draws it itself
        assert nodes("img::images/scene_textures/a.png") == [10, 11, 30]
        assert nodes("img::images/scene_textures/none.png") == []
        assert nodes("font::radimg_F_512x512_aa") == [13]
        assert nodes("vid::video/Tokyo_Loop.mp4") == [14]
        # a video no layer names: the scene's video layer
        assert nodes("vid::video/other.mp4") == [14]
        w.call("text_scenes.close")


def test_a_second_pick_of_a_row_goes_on_to_the_next_layer(tmp_path):
    folder, _man = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _open(w, folder)
        art = _named(w, "Art")
        title = _named(w, "Title")
        picked = []
        w.run(lambda: setattr(svc, "_tree_item_nodes", lambda iid: [art, title]))
        w.run(lambda: setattr(svc, "tree_select", lambda n: picked.append(n) or True))
        w.run(lambda: setattr(svc, "_tsel", None))
        w.run(svc._tree_pick_item, "img::x")
        w.run(lambda: setattr(svc, "_tsel", art))
        w.run(svc._tree_pick_item, "img::x")
        w.run(lambda: setattr(svc, "_tsel", title))
        w.run(svc._tree_pick_item, "img::x")
        assert picked == [art, title, art]
        w.call("text_scenes.close")


def test_contents_rows_are_one_column_with_a_small_picture():
    with open(_JS, encoding="utf-8") as f:
        src = f.read()
    body = src[src.index("function Contents("):]
    body = body[:body.index("\n}\n")]
    # the hints column is gone: its words are the row's tooltip
    assert 'class="sc-i' not in body
    assert "tip({ head: it.text, lines: [it.info] })" in body
    assert 'class="sc-pic"><img src=${mediaUrl(it.thumb)}' in body
    assert '"ct-item"' in body
