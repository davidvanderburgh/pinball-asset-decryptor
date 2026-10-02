"""Scenes window: the scene EDITOR (PAD-251), driven through the calls the canvas and its
side panel make (webui/text_scenes_tree.py, ``text_scenes.tree_*``).

A scene the project has a tree for (``scene_tree.json``) is drawn from that tree and edited in
place: pick an element, drag it (a glass move turned into the node's own units), resize it from
a corner (about its middle), tint it, hide it, re-layer it, add a line of text, undo, put it
back.  Every edit lands in ``scene_edits.json``, is drawn at once, and is listed on the Write
tab as a pending change.
"""

import json
import os
import time

import pytest

from tests.webui_harness import web_app

pytest.importorskip("numpy")
pytest.importorskip("PIL")

CARD = "/g/scene1/scene.radium"


def _seed(folder, data=None):
    """A project with one scene the editor can draw: the synthetic scene of
    tests/test_stern_scene_tree.py (or *data*), its manifest, PNGs for its pictures."""
    from PIL import Image
    from pinball_decryptor.plugins.stern import scene_eval, scene_tree
    from tests.test_stern_scene_tree import scene
    sc = scene_tree.parse(data or scene())
    tex = folder / "images" / "scene_textures"
    tex.mkdir(parents=True)
    tex2rel = {}
    rows = []
    for tid, t in sc.textures.items():
        rel = "scene_textures/pic_%d.png" % tid
        Image.new("RGBA", (t["w"], t["h"]), (200, 40, 40, 255)).save(
            str(folder / "images" / rel))
        tex2rel[t["data_off"]] = rel
        rows.append("%s\t%s\t%d\t%d\t%d\t%d\t5" % (rel, CARD, t["data_off"], len(t["blob"]),
                                                   t["w"], t["h"]))
    (tex / "radium_images.txt").write_text(
        "# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt\n"
        + "\n".join(rows) + "\n", encoding="utf-8")
    man = scene_eval.manifest(sc, tex2rel)
    (tex / "scene_tree.json").write_text(json.dumps({CARD: man}), encoding="utf-8")
    return man


def _wait(w, pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _open(w, folder):
    def _set():
        w.window.write_assets_var.set(str(folder))
    w.run(_set)
    text = w.window.service("text")
    assert w.run(text.open_scene_browser, str(folder)) is True
    w.call("text_scenes.select", "/g/scene1")
    assert _wait(w, lambda: (w.state("text_scenes").get("frames") or []) != [])
    return text.scenes


def _tv(w):
    return w.state("text_scenes")["tree_view"]


def _ops(folder):
    from pinball_decryptor.plugins.stern import scene_edit
    return scene_edit.ops_for(str(folder), CARD)


def test_undo_and_redo_take_back_every_kind_of_edit(tmp_path):
    """PAD-283 (DragonRR): Undo steps back over ANY edit - Draw 1:1, Show, As shipped and a
    new tint too, which change the list in place rather than adding to its end - and Redo
    (Ctrl+Y, Ctrl+Shift+Z) steps forward again until a new edit is made."""
    from pinball_decryptor.plugins.stern import scene_edit
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    # an edit left by an earlier session: Undo still takes it off, one op at a time
    scene_edit.add(str(folder), CARD, {"op": "order", "node": 1, "index": 0})
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        tv = _tv(w)
        assert tv["can_undo"] and not tv["can_redo"]
        art = next(h for h in tv["hits"] if h["name"] == "Art")["id"]
        title = next(h for h in tv["hits"] if h["name"] == "Title")["id"]
        start = _ops(folder)

        assert w.call("text_scenes.tree_select", art)
        assert w.call("text_scenes.tree_set_scale", art, 40)
        s40 = _ops(folder)
        assert w.call("text_scenes.tree_one_to_one", art)
        one = _ops(folder)
        assert one[-1]["op"] == "scale" and one[-1]["node"] == art
        assert w.call("text_scenes.tree_visible", title, False)
        hid = _ops(folder)
        assert w.call("text_scenes.tree_visible", title, True)       # Show drops the hide
        assert _ops(folder) == one
        assert w.call("text_scenes.tree_tint", art, "#ff0000", 100)
        assert w.call("text_scenes.tree_tint", art, "#00ff00", 100)  # replaces the tint
        green = _ops(folder)
        assert w.call("text_scenes.tree_reset", art)                  # As shipped
        assert _ops(folder) == [op for op in green if op.get("node") != art]

        assert w.call("text_scenes.tree_undo")
        assert _ops(folder) == green
        assert _tv(w)["can_redo"]
        assert w.call("text_scenes.tree_undo")
        assert [op["mul"][:3] for op in _ops(folder) if op["op"] == "tint"] == [[1.0, 0.0, 0.0]]
        assert w.call("text_scenes.tree_undo")
        assert _ops(folder) == one
        assert w.call("text_scenes.tree_undo")
        assert _ops(folder) == hid                                    # back before the Show
        assert w.call("text_scenes.tree_undo")
        assert _ops(folder) == one
        assert w.call("text_scenes.tree_undo")                        # Draw 1:1 taken back
        assert _ops(folder) == s40
        assert w.call("text_scenes.tree_undo")
        assert _ops(folder) == start

        # forward again, step by step, to where it was
        for want in (s40, one, hid, one):
            assert w.call("text_scenes.tree_redo")
            assert _ops(folder) == want

        # a new edit ends the redo; the earlier session's edit still comes off at the end
        assert w.call("text_scenes.tree_move", title, 5, 0)
        assert not _tv(w)["can_redo"] and not w.call("text_scenes.tree_redo")
        for _ in range(5):
            assert w.call("text_scenes.tree_undo")
        assert _ops(folder) == start
        assert w.call("text_scenes.tree_undo")
        assert _ops(folder) == [] and not _tv(w)["can_undo"]
        assert not w.call("text_scenes.tree_undo")
        assert w.call("text_scenes.tree_redo") and _ops(folder) == start


def test_the_editor_draws_the_tree_and_edits_it(tmp_path):
    from pinball_decryptor.webui import write_scan
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        sb = _open(w, folder)
        st = w.state("text_scenes")
        assert st["tree"] is True
        tv = _tv(w)
        assert tv["stage"] == [1360, 768] and tv["frames"] == 20
        assert [m["label"] for m in tv["moments"]][1:] == ["Start (frame 1)", "End (frame 20)"]
        names = [h["name"] for h in tv["hits"]]
        assert "Art" in names and "Title" in names
        art = next(h for h in tv["hits"] if h["name"] == "Art")

        # pick it: its box and size show
        assert w.call("text_scenes.tree_select", art["id"])
        p = _tv(w)["props"]
        assert p["name"] == "Art" and p["scale"] == 100 and p["kind"] == "Bitmap"
        x0, y0 = p["x"], p["y"]

        # a drag of (30, -10) glass pixels: the Art node is scaled 0.8 on the glass, so its
        # own units are the same (its parent is the root) - and it lands 30, -10 away
        assert w.call("text_scenes.tree_move", art["id"], 30, -10)
        assert _ops(folder) == [{"op": "move", "node": art["id"], "dx": 30.0, "dy": -10.0}]
        p = _tv(w)["props"]
        assert (p["x"], p["y"]) == (x0 + 30, y0 - 10)

        # a corner drag to 150 %: about the middle, so the middle stays put
        mid = (p["x"] + p["w"] / 2.0, p["y"] + p["h"] / 2.0)
        assert w.call("text_scenes.tree_scale", art["id"], 1.5)
        p = _tv(w)["props"]
        assert p["scale"] == 150
        assert abs(p["x"] + p["w"] / 2.0 - mid[0]) <= 1 and abs(p["y"] + p["h"] / 2.0 - mid[1]) <= 1

        # width and height apart: a stretch, about the middle too
        assert w.call("text_scenes.tree_set_size", art["id"], 300, None)
        p = _tv(w)["props"]
        assert (p["scale"], p["scale_y"]) == (300, 150)
        assert w.call("text_scenes.tree_set_size", art["id"], 150, None)
        assert _tv(w)["props"]["scale"] == 150

        # tint, hide, re-layer
        assert w.call("text_scenes.tree_tint", art["id"], "#3366ff", 50)
        p = _tv(w)["props"]
        assert p["tint"] == "#3366ff" and p["alpha"] == 50
        title = next(h for h in _tv(w)["hits"] if h["name"] == "Title")["id"]
        assert w.call("text_scenes.tree_order", title, "back")
        assert w.call("text_scenes.tree_visible", title, False)
        assert any(h["id"] == title for h in _tv(w)["hits"])          # the game's eye (PAD-293)
        assert w.call("text_scenes.tree_visible", title, True)
        assert w.call("text_scenes.tree_view", title, False)
        assert all(h["id"] != title for h in _tv(w)["hits"])          # the preview's eye
        assert w.call("text_scenes.tree_view", title, True)
        assert any(h["id"] == title for h in _tv(w)["hits"])

        # add a line of text in the selected line's font; it is selected and drawn
        assert w.call("text_scenes.tree_select", title)
        assert w.call("text_scenes.tree_add_text", "HELLO THERE")
        tv = _tv(w)
        assert tv["props"]["added"] and tv["props"]["kind"] == "Text"
        assert any(h["name"] == "PAD_Text" for h in tv["hits"])
        added = tv["props"]["id"]

        # the Write tab lists the scene's edits and notices a change
        write = w.window.service("write")
        fp = w.run(write._fingerprint)
        rows = w.run(lambda: write_scan.pending_rows(
            w.window, w.window.current_mfr, str(folder), grow_on=True, direct=False))
        rows = [r for r in rows if r[2] == "Pending (scene edit)"]
        assert rows and "5 edit(s)" in rows[0][0]

        # undo drops the last edit (the added text), remove on an added node drops it too
        assert w.call("text_scenes.tree_undo")
        assert not any(h["name"] == "PAD_Text" for h in _tv(w)["hits"])
        assert w.run(write._fingerprint) != fp
        assert w.call("text_scenes.tree_reset", art["id"])
        assert [op["op"] for op in _ops(folder)] == ["order"]
        assert added not in [n["id"] for n in _tv(w)["layers"]]

        # the moment: a label seeks the root timeline
        assert w.call("text_scenes.tree_moment", "f:20")
        assert _tv(w)["frame"] == 20
        w.call("text_scenes.close")
        assert sb is not None


def test_a_scene_without_a_tree_keeps_the_old_preview(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    os.remove(str(folder / "images" / "scene_textures" / "scene_tree.json"))
    with web_app(tmp_path, mfr="stern") as w:
        def _set():
            w.window.write_assets_var.set(str(folder))
        w.run(_set)
        text = w.window.service("text")
        assert w.run(text.open_scene_browser, str(folder)) is True
        w.call("text_scenes.select", "/g/scene1")
        w.drain()
        assert not w.state("text_scenes").get("tree")
        w.call("text_scenes.close")


def test_a_project_without_trees_gets_them_read_off_the_card(tmp_path, monkeypatch):
    """A project extracted before the editor has previews but no scene_tree.json: the window
    reads the trees off the Extract tab's card by itself (no card: it says how), instead of
    quietly showing the old preview."""
    from pinball_decryptor.plugins.stern import engine
    folder = tmp_path / "proj"
    folder.mkdir()
    man = _seed(folder)
    tree_path = folder / "images" / "scene_textures" / "scene_tree.json"
    os.remove(str(tree_path))
    card = tmp_path / "card.raw"
    card.write_bytes(b"\0" * 16)
    calls = []

    def fake_rebuild(image, assets, log=None, progress=None, cancel=None, **kw):
        calls.append(image)
        tree_path.write_text(json.dumps({CARD: man}), encoding="utf-8")
        return 1

    monkeypatch.setattr(engine, "rebuild_scene_layouts_from_card", fake_rebuild)
    with web_app(tmp_path, mfr="stern") as w:
        def _set(path):
            w.window.write_assets_var.set(str(folder))
            w.window.extract_input_var.set(path)
        w.run(_set, "")
        text = w.window.service("text")
        assert w.run(text.open_scene_browser, str(folder)) is True
        assert "Extract tab's Input" in w.state("text_scenes")["rebuild_msg"]
        assert calls == []
        w.call("text_scenes.close")

        w.run(_set, str(card))
        assert w.run(text.open_scene_browser, str(folder)) is True
        assert _wait(w, lambda: calls == [str(card)] and not w.state("text_scenes")["rebuilding"])
        w.call("text_scenes.select", "/g/scene1")
        assert _wait(w, lambda: w.state("text_scenes").get("tree") is True)
        w.call("text_scenes.close")


def test_an_edit_keeps_the_picture_while_it_redraws_and_a_pick_gets_its_layers(tmp_path):
    """David: tweaking something must not blank the canvas and wait.  The scenes are a tab
    (opening them brings it forward); an edit leaves the picture up and says it is updating
    until the redraw lands, tagged with the edit count it draws; a picked element gets its own
    layers (under / it / over) so the page can move its pixels while it is dragged."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.state("shell")["tab"] == "scenes"
        st = w.state("text_scenes")
        assert st["tree_loading"] is False and st["tree_busy"] is False
        art = next(h for h in _tv(w)["hits"] if h["name"] == "Art")["id"]
        assert w.call("text_scenes.tree_select", art)
        assert _wait(w, lambda: (w.state("text_scenes").get("tree_layers") or {}).get("node") == art)
        layers = w.state("text_scenes")["tree_layers"]
        assert all(os.path.isfile(layers[k]) for k in ("under", "sel", "over"))

        shown = w.state("text_scenes")["frames"]
        rev = _tv(w)["rev"]
        assert w.call("text_scenes.tree_move", art, 12, 0)
        st = w.state("text_scenes")
        # the outline moved at once; the picture is the old one until the new one is drawn
        assert _tv(w)["rev"] == rev + 1
        if st["tree_img_rev"] < rev + 1:
            assert st["frames"] == shown and st["tree_busy"] is True
        assert _wait(w, lambda: w.state("text_scenes")["tree_img_rev"] == rev + 1)
        st = w.state("text_scenes")
        assert st["tree_busy"] is False and st["frames"] and st["frames"] != shown
        assert os.path.isfile(st["frames"][0])
        assert (st["tree_layers"] or {}).get("node") == art

        # a burst of edits: every one is kept, the last is what is drawn
        for _i in range(5):
            w.call("text_scenes.tree_move", art, 1, 0)
        assert _wait(w, lambda: w.state("text_scenes")["tree_img_rev"] == _tv(w)["rev"])
        assert sum(op["dx"] for op in _ops(folder) if op["op"] == "move") == 17.0
        w.call("text_scenes.close")


def test_reset_back_to_the_last_write_or_as_shipped_for_every_scene(tmp_path):
    """The Reset menu under the preview: back to what the last Write put on the card (this
    scene), as shipped (this scene), as shipped (every scene); each asks first."""
    from pinball_decryptor.plugins.stern import scene_edit
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        art = next(h for h in _tv(w)["hits"] if h["name"] == "Art")["id"]
        assert _tv(w)["built"] == "none"
        assert w.call("text_scenes.tree_revert_built") is False          # no Write yet: says so
        assert w.asked[-1]["title"] == "Scene edits"
        assert w.call("text_scenes.tree_move", art, 10, 0)
        w.run(scene_edit.mark_built, str(folder))                         # what a Write records
        assert w.call("text_scenes.tree_select", art)
        assert _tv(w)["built"] == "same"
        assert w.call("text_scenes.tree_move", art, 0, 25)
        assert w.call("text_scenes.tree_tint", art, "#ff0000", 100)
        assert _tv(w)["built"] == "changed" and _tv(w)["all_edits"] == 2   # the moves fold into one
        w.answers.append("no")
        assert w.call("text_scenes.tree_revert_built") is False
        w.answers.append("yes")
        assert w.call("text_scenes.tree_revert_built") is True
        assert _ops(folder) == [{"op": "move", "node": art, "dx": 10.0, "dy": 0.0}]
        assert _tv(w)["built"] == "same"
        w.answers.append("yes")
        assert w.call("text_scenes.tree_clear_all") is True
        assert _ops(folder) == [] and _tv(w)["all_edits"] == 0 and _tv(w)["built"] == "changed"
        assert w.call("text_scenes.tree_clear_all") is False              # nothing left to drop
        w.call("text_scenes.close")



def test_an_edit_reaches_a_running_emulator_on_the_fly(tmp_path, monkeypatch):
    """PAD-251 (DragonRR: "Can scenes also have that cool on the fly feature?"): with the
    Emulate tab running this project's edits, an edit to a scene the game loads on demand is
    rebuilt and handed to the running game; a scene loaded at start says to restart."""
    from pinball_decryptor.plugins.stern import engine
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    out = tmp_path / "set"
    in_set = out / "g" / "scene1" / "scene.radium"
    in_set.parent.mkdir(parents=True)
    from tests.test_stern_scene_tree import scene
    in_set.write_bytes(scene())
    pushed = []
    with web_app(tmp_path, mfr="stern") as w:
        emu = w.window.service("emulate")
        monkeypatch.setattr(emu, "live_scene_target", lambda assets: str(out))
        monkeypatch.setattr(emu, "push_live_scene",
                            lambda card, data: pushed.append((card, data)) or "sent")
        monkeypatch.setattr(engine, "scene_loads_on_demand", lambda card: True)
        _open(w, folder)
        assert w.state("text_scenes")["tree_live"]["kind"] == "live"
        art = next(h for h in _tv(w)["hits"] if h["name"] == "Art")["id"]
        assert w.call("text_scenes.tree_move", art, 15, 0)
        assert _wait(w, lambda: pushed)
        assert pushed[0][0] == CARD and pushed[0][1] != scene()
        assert _wait(w, lambda: "sent to the running game" in
                     (w.state("text_scenes")["tree_live"] or {}).get("text", ""))
        monkeypatch.setattr(engine, "scene_loads_on_demand", lambda card: False)
        assert w.call("text_scenes.tree_move", art, 1, 0)
        assert w.state("text_scenes")["tree_live"]["kind"] == "boot"
        assert "after a restart" in w.state("text_scenes")["tree_live"]["text"]
        n = len(pushed)
        w.drain()
        assert len(pushed) == n                                     # nothing handed over
        monkeypatch.setattr(emu, "live_scene_target", lambda assets: None)
        assert w.call("text_scenes.tree_move", art, 1, 0)
        assert w.state("text_scenes")["tree_live"] is None
        w.call("text_scenes.close")



def test_a_picture_picked_on_the_images_tab_shows_at_the_size_the_build_gives_it(tmp_path):
    """DragonRR: a replaced picture whose "keep its own size" is NOT ticked showed at its own
    size.  The Images tab's pick is drawn (not yet built, too), scaled to the card texture's
    size (radium_images.txt), unless keep-size is ticked."""
    import numpy as np
    from PIL import Image
    from pinball_decryptor.core import staged_changes
    from pinball_decryptor.plugins.stern import scene_render as R
    folder = tmp_path / "proj"
    folder.mkdir()
    man = _seed(folder)
    art = next(o for o in man["objects"].values() if o.get("kind") == "Bitmap" and o.get("image"))
    rel = art["image"]
    stock = Image.open(str(folder / "images" / rel)).size
    big = tmp_path / "big.png"
    Image.new("RGBA", (stock[0] * 3, stock[1] * 3), (20, 220, 40, 255)).save(str(big))
    data = staged_changes.load(str(folder)) or {}
    data["image"] = {"images/" + rel: str(big)}
    staged_changes.save(str(folder), data)
    pics = R.pending_pictures(str(folder))
    sizes = R.picture_sizes(str(folder))
    assert pics["scene_textures/" + rel.split("/")[-1]]["path"] == str(big)
    assert sizes[rel] == stock
    cache = {}
    got = R._picture(str(folder), rel, cache, pics, sizes)
    assert got.size == stock and np.asarray(got)[..., 1].mean() > 150
    data["image_keep_size"] = ["images/" + rel]
    staged_changes.save(str(folder), data)
    got = R._picture(str(folder), rel, {}, R.pending_pictures(str(folder)), sizes)
    assert got.size == (stock[0] * 3, stock[1] * 3)
    # a stock picture already is its texture's size: untouched
    assert R._picture(str(folder), rel, {}, {}, sizes).size == stock


def test_the_scenes_tab_warns_of_missing_pictures_and_another_games_project(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import engine
    folder = tmp_path / "proj"
    folder.mkdir()
    man = _seed(folder)
    rel = next(o["image"] for o in man["objects"].values() if o.get("kind") == "Bitmap" and o.get("image"))
    os.remove(str(folder / "images" / rel))
    card = tmp_path / "kong_le.raw"
    card.write_bytes(b"\0" * 16)
    monkeypatch.setattr(engine, "card_title_index", lambda path: ("kong_le-1_0_0.sidx",))
    with web_app(tmp_path, mfr="stern") as w:
        def _set():
            w.window.write_assets_var.set(str(folder))
            w.window.extract_input_var.set(str(card))
        w.run(_set)
        text = w.window.service("text")
        assert w.run(text.open_scene_browser, str(folder)) is True
        w.call("text_scenes.select", "/g/scene1")
        assert _wait(w, lambda: w.state("text_scenes").get("pic_note"))
        assert "not in this project folder" in w.state("text_scenes")["pic_note"]
        assert _wait(w, lambda: w.state("text_scenes").get("card_note"))
        note = w.state("text_scenes")["card_note"]
        assert "kong_le" in note and "g" in note
        w.call("text_scenes.close")


def test_an_older_manifest_is_re_read_quietly_when_the_card_is_there(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import engine, scene_eval
    folder = tmp_path / "proj"
    folder.mkdir()
    man = _seed(folder)
    tree_path = folder / "images" / "scene_textures" / "scene_tree.json"
    old = dict(man, v=2)
    tree_path.write_text(json.dumps({CARD: old}), encoding="utf-8")
    card = tmp_path / "card.raw"
    card.write_bytes(b"\0" * 16)
    calls = []

    def fake_rebuild(image, assets, log=None, progress=None, cancel=None, **kw):
        calls.append(image)
        tree_path.write_text(json.dumps({CARD: dict(man, v=scene_eval.MANIFEST_VERSION)}),
                             encoding="utf-8")
        return 1

    monkeypatch.setattr(engine, "rebuild_scene_layouts_from_card", fake_rebuild)
    monkeypatch.setattr(engine, "card_title_index", lambda path: ())
    with web_app(tmp_path, mfr="stern") as w:
        def _set():
            w.window.write_assets_var.set(str(folder))
            w.window.extract_input_var.set(str(card))
        w.run(_set)
        text = w.window.service("text")
        assert w.run(text.open_scene_browser, str(folder)) is True
        assert _wait(w, lambda: calls == [str(card)] and not w.state("text_scenes")["rebuilding"])
        assert w.state("text_scenes").get("preparing") is None         # the editor stayed up
        w.call("text_scenes.select", "/g/scene1")
        assert _wait(w, lambda: w.state("text_scenes").get("tree") is True)
        assert calls == [str(card)]                                       # once
        w.call("text_scenes.close")


def test_the_scene_list_is_coloured_by_what_is_not_written_yet(tmp_path):
    from pinball_decryptor.plugins.stern import scene_edit
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    row = lambda w: next(r for r in w.state("text_scenes")["scenes"] if r["d"] == "/g/scene1")  # noqa: E731
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert row(w)["state"] == ""
        art = next(h for h in _tv(w)["hits"] if h["name"] == "Art")["id"]
        assert w.call("text_scenes.tree_move", art, 5, 0)
        assert row(w)["state"] == "edited"
        w.run(scene_edit.mark_built, str(folder))                      # a Write
        w.run(w.window.service("text").scenes.refresh_view)           # the tab comes forward
        assert row(w)["state"] == "written" and _tv(w)["built"] == "same"
        assert w.call("text_scenes.tree_move", art, 1, 0)
        assert row(w)["state"] == "edited"
        w.call("text_scenes.close")


def test_an_exact_size_in_pixels(tmp_path):
    """DragonRR: "set the exact size I am after rather than %". W px / H px on the screen;
    with Keep its shape one sets both, without it only that side stretches."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        art = next(h for h in _tv(w)["hits"] if h["name"] == "Art")["id"]
        assert w.call("text_scenes.tree_select", art)
        p = _tv(w)["props"]
        w0, h0 = p["w"], p["h"]
        assert w.call("text_scenes.tree_set_pixels", art, w0 * 2, None, True)
        p = _tv(w)["props"]
        assert abs(p["w"] - w0 * 2) <= 1 and abs(p["h"] - h0 * 2) <= 1
        assert w.call("text_scenes.tree_set_pixels", art, None, 50, False)
        p = _tv(w)["props"]
        assert abs(p["h"] - 50) <= 1 and abs(p["w"] - w0 * 2) <= 1
        assert w.call("text_scenes.tree_set_pixels", art, 0, None, True) is False
        w.call("text_scenes.close")


def test_a_kept_size_pick_whose_file_is_gone_boxes_the_picture_drawn(tmp_path):
    """DragonRR (PAD-332): a Write puts a kept-size pick over the project's own file at its
    own size.  With the pick's source file gone (moved, renamed) the preview draws that
    project file, so its box is that size too, not the stock picture's (which sat up and
    left of the art)."""
    from PIL import Image
    from pinball_decryptor.core import staged_changes
    folder = tmp_path / "proj"
    folder.mkdir()
    man = _seed(folder)
    rel = next(o for o in man["objects"].values()
               if o.get("kind") == "Bitmap" and o.get("image"))["image"]
    stock = Image.open(str(folder / "images" / rel)).size
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        art = next(h for h in _tv(w)["hits"] if h["name"] == "Art")["id"]
        assert w.call("text_scenes.tree_select", art)
        p = _tv(w)["props"]
        sx, w0, h0 = p["pic"]["sx"], p["w"], p["h"]
        assert (p["pic"]["w"], p["pic"]["h"]) == stock
        # what the Write left: the project's file at the pick's own (bigger) size, and the
        # pick itself pointing at a file that is no longer there
        grown = (stock[0] * 2, stock[1] * 2)
        Image.new("RGBA", grown, (20, 220, 40, 255)).save(str(folder / "images" / rel))
        staged_changes.save(str(folder), {"image": {"images/" + rel: str(tmp_path / "gone.png")},
                                          "image_keep_size": ["images/" + rel]})
        w.call("text_scenes.tree_moment", "f:%d" % _tv(w)["frame"])
        tv = _tv(w)
        p = tv["props"]
        assert (p["pic"]["w"], p["pic"]["h"]) == grown
        assert abs(p["w"] - w0 * 2) <= 1.5 and abs(p["h"] - h0 * 2) <= 1.5
        assert p["pic"]["sx"] == sx
        pts = next(h for h in tv["hits"] if h["id"] == art)["pts"]
        xs = [q[0] for q in pts]
        assert abs((max(xs) - min(xs)) - w0 * 2) <= 1.5
        w.call("text_scenes.close")


def test_a_pictures_own_size_and_scale_and_draw_it_1_to_1(tmp_path):
    """DragonRR (PAD-277): Stern ships Credits_Text at 1044 x 264 and lets the game shrink it,
    which leaves jagged edges.  The panel shows a picture's own size and the scale it is drawn
    at; a picture made at the size it shows (kept at its own size on the Images tab) is then
    drawn pixel for pixel with Draw 1:1, its top-left corner where it was."""
    from PIL import Image
    from pinball_decryptor.core import staged_changes
    folder = tmp_path / "proj"
    folder.mkdir()
    man = _seed(folder)
    rel = next(o for o in man["objects"].values()
               if o.get("kind") == "Bitmap" and o.get("image"))["image"]
    stock = Image.open(str(folder / "images" / rel)).size
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        art = next(h for h in _tv(w)["hits"] if h["name"] == "Art")["id"]
        assert w.call("text_scenes.tree_select", art)
        assert w.call("text_scenes.tree_set_scale", art, 40)
        p = _tv(w)["props"]
        assert (p["pic"]["w"], p["pic"]["h"]) == stock
        s0 = p["pic"]["sx"]
        assert abs(p["w"] - stock[0] * s0 / 100.0) <= 1.5
        x0, y0 = p["x"], p["y"]
        # the Images tab's pick, made at the size it shows, keeping its own size
        small = tmp_path / "small.png"
        Image.new("RGBA", (round(p["w"]), round(p["h"])), (20, 220, 40, 255)).save(str(small))
        staged_changes.save(str(folder), {"image": {"images/" + rel: str(small)},
                                          "image_keep_size": ["images/" + rel]})
        w.call("text_scenes.tree_moment", "f:%d" % _tv(w)["frame"])
        p = _tv(w)["props"]
        assert (p["pic"]["w"], p["pic"]["h"]) == Image.open(str(small)).size
        assert p["pic"]["sx"] == s0 and p["w"] < stock[0] * s0 / 100.0 / 2
        assert w.call("text_scenes.tree_one_to_one", art)
        p = _tv(w)["props"]
        assert p["pic"]["sx"] == 100 and p["pic"]["sy"] == 100
        assert abs(p["w"] - p["pic"]["w"]) <= 1 and abs(p["h"] - p["pic"]["h"]) <= 1
        assert abs(p["x"] - x0) <= 1 and abs(p["y"] - y0) <= 1
        # already 1:1: nothing to do
        assert w.call("text_scenes.tree_one_to_one", art) is False
        w.call("text_scenes.close")


def test_a_greyed_layer_is_brought_into_view_where_the_game_shows_it(tmp_path):
    """DragonRR: the greyed eyes, "force them to show".  A layer the game is not drawing at
    this moment: tree_show goes to a moment where it is drawn and selects it; no edit."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_moment", "f:12")
        assert _wait(w, lambda: _tv(w)["frame"] == 12)
        off = [l for l in _tv(w)["layers"] if not l["drawn"]]
        assert off, "the synthetic scene has a layer that is gone by frame 12"
        assert w.call("text_scenes.tree_show", off[0]["id"])
        tv = _tv(w)
        assert tv["frame"] != 12 and tv["sel"] == off[0]["id"]
        assert next(l for l in tv["layers"] if l["id"] == off[0]["id"])["drawn"]
        assert _ops(folder) == []
        # and it is edited there like any other layer (DragonRR: "place/move/change all of
        # the greyed out stuff"); the edit holds whatever moment is shown
        nid = off[0]["id"]
        x0 = tv["props"]["x"]
        assert w.call("text_scenes.tree_move", nid, 25, 0)
        assert _ops(folder) == [{"op": "move", "node": nid, "dx": 25.0, "dy": 0.0}]
        assert abs(_tv(w)["props"]["x"] - (x0 + 25)) <= 1
        assert w.call("text_scenes.tree_moment", "f:12")
        assert _wait(w, lambda: _tv(w)["frame"] == 12)
        assert len(_ops(folder)) == 1
        w.call("text_scenes.close")


def test_a_greyed_layer_is_shown_on_top_where_it_is_while_selected(tmp_path):
    """DragonRR (PAD-276): clicking a greyed layer went to another moment and greyed the one
    that was showing.  Selecting it now draws it on top at THIS moment, for as long as it stays
    selected; selecting nothing puts the scene back as the game draws it."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_moment", "f:12")
        assert _wait(w, lambda: _tv(w)["frame"] == 12)
        on = {l["id"] for l in _tv(w)["layers"] if l["drawn"]}
        off = [l for l in _tv(w)["layers"] if not l["drawn"]]
        nid = off[0]["id"]
        assert w.call("text_scenes.tree_select", nid)
        tv = _tv(w)
        assert tv["frame"] == 12 and tv["sel"] == nid and tv["props"]["peek"]
        now = {l["id"] for l in tv["layers"] if l["drawn"]}
        assert now == on | {nid}                   # nothing that was showing greyed out
        assert tv["hits"][-1]["id"] == nid         # on top
        assert _ops(folder) == []
        x0 = tv["props"]["x"]
        assert w.call("text_scenes.tree_move", nid, 25, 0)
        assert _tv(w)["props"]["peek"] and abs(_tv(w)["props"]["x"] - (x0 + 25)) <= 1
        assert w.call("text_scenes.tree_select", None)
        tv = _tv(w)
        assert tv["frame"] == 12 and {l["id"] for l in tv["layers"] if l["drawn"]} == on
        w.call("text_scenes.close")


def test_the_scene_and_the_tab_come_back_with_nothing_selected(tmp_path):
    """DragonRR (PAD-294): a selected layer is drawn on top, and it stayed selected when the
    Scenes tab came forward again or the scene was picked again.  Both start with nothing
    selected now; the page drops the selection on a click outside the picture."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _open(w, folder)
        assert _tv(w)["sel"] is None and _tv(w)["sels"] == []
        assert w.call("text_scenes.tree_moment", "f:12")
        assert _wait(w, lambda: _tv(w)["frame"] == 12)
        off = [l for l in _tv(w)["layers"] if not l["drawn"]][0]["id"]
        assert w.call("text_scenes.tree_select", off)
        assert _tv(w)["sel"] == off and _tv(w)["props"]["peek"]
        w.run(svc.refresh_view)                                        # the tab comes forward
        assert _wait(w, lambda: _tv(w)["sel"] is None)
        tv = _tv(w)
        assert tv["sels"] == [] and tv["props"] is None
        assert off not in {l["id"] for l in tv["layers"] if l["drawn"]}   # no longer on top
        pic = tv["hits"][0]["id"]
        assert w.call("text_scenes.tree_select", pic)
        assert _tv(w)["sel"] == pic
        w.call("text_scenes.select", "/g/scene1")                      # the same scene again
        assert _wait(w, lambda: _tv(w)["sel"] is None)
        w.call("text_scenes.close")


def _meter_scene():
    """Godzilla's energy meter in small: a sprite the game picks a look of (Level 0, Level 1),
    one picture per level, and a picture the timeline only reaches at frame 10."""
    from tests.test_stern_scene_tree import (FLAG, bitmap, cls, node, sprite, texture, u8,
                                             u32, u64, fs)
    lib = [
        u32(3) + cls(1, "Bitmap") + u32(FLAG | 10) + bitmap(3, 8, 4, texture(20)),
        u32(4) + cls(2, "Sprite") + u32(FLAG | 11) + sprite(4, "", 2, [
            node(40, "Level0_Art", [u32(1) + cls(1) + u32(10)], kf=((1, 1), (2, 0))),
            node(41, "Level1_Art", [u32(2) + cls(1) + u32(10)], kf=((1, 0), (2, 1)))],
            labels=[("Level 0", 1), ("Level 1", 2)]),
    ]
    root_kids = [node(50, "Meter", [u32(1) + cls(2) + u32(11)]),
                 node(51, "Late", [u32(1) + cls(1) + u32(10)], kf=((1, 0), (10, 1)))]
    root = sprite(2, "", 20, root_kids, labels=[("Start", 1)])
    return (u8(1) + u64(len(lib)) + b"".join(lib) + u64(0)
            + u32(1360) + u32(768) + fs(30.0) + fs(0.2, 0.2, 0.2, 1.0) + root)


def test_a_part_the_game_picks_is_turned_on_in_the_preview_not_greyed(tmp_path):
    """DragonRR (PAD-276): the meter's levels are there at every moment - PAD picks which one
    the preview shows, not the timeline - so they are not greyed: their eye is off, and
    clicking it turns them on in the preview, where they sit; the card is not changed.  Only
    a layer the timeline has not reached yet stays greyed."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder, _meter_scene())
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_moment", "f:1")
        assert _wait(w, lambda: _tv(w)["frame"] == 1)
        lay = lambda: {l["name"]: l for l in _tv(w)["layers"]}      # noqa: E731
        ly = lay()
        on, off = ((ly["Level0_Art"], ly["Level1_Art"]) if ly["Level0_Art"]["drawn"]
                   else (ly["Level1_Art"], ly["Level0_Art"]))
        assert not off["drawn"] and off["state_off"] and not on["state_off"]
        assert not ly["Late"]["drawn"] and not ly["Late"]["state_off"]      # still greyed
        frame = _tv(w)["frame"]
        assert w.call("text_scenes.tree_force", off["id"], True)
        ly = lay()
        assert ly[off["name"]]["drawn"] and ly[off["name"]]["shown"]
        assert not ly[off["name"]]["state_off"]         # its eye is on (PAD-280)
        assert ly[on["name"]]["drawn"] and _tv(w)["frame"] == frame
        assert _ops(folder) == []
        assert w.call("text_scenes.tree_force", off["id"], False)
        ly = lay()
        assert not ly[off["name"]]["drawn"] and ly[off["name"]]["state_off"]
        # clicking its name shows it on top while selected, at this moment
        assert w.call("text_scenes.tree_select", off["id"])
        assert _tv(w)["props"]["peek"] and _tv(w)["frame"] == frame
        assert lay()[off["name"]]["state_off"]          # a peek does not turn its eye on
        assert w.call("text_scenes.tree_select", None)
        assert lay()[off["name"]]["state_off"]
        w.call("text_scenes.close")


def _body_scene():
    """Godzilla's battle select in small (PAD-284): the picker shows one body per state; the
    body it does not show is a sprite with a picture and a text box in it."""
    from tests.test_stern_scene_tree import (FLAG, bitmap, cls, mat, node, sprite, texture,
                                             u8, u32, u64, fs)
    lib = [
        u32(3) + cls(1, "Bitmap") + u32(FLAG | 10) + bitmap(3, 8, 4, texture(20)),
        u32(5) + cls(2, "Sprite") + u32(FLAG | 12) + sprite(5, "", 1, [
            node(60, "Body_Art", [u32(1) + cls(1) + u32(10)]),
            node(61, "Body_Textbox", [u32(1) + cls(1) + u32(10)], tracks=((1, mat(1, 30, 0)),))]),
        u32(4) + cls(2) + u32(FLAG | 11) + sprite(4, "", 2, [
            node(40, "BodyA", [u32(1) + cls(1) + u32(10)], kf=((1, 1), (2, 0))),
            node(41, "BodyB", [u32(1) + cls(2) + u32(12)], kf=((1, 0), (2, 1)))],
            labels=[("A", 1), ("B", 2)]),
    ]
    root = sprite(2, "", 20, [node(50, "Select", [u32(1) + cls(2) + u32(11)])],
                  labels=[("Start", 1)])
    return (u8(1) + u64(len(lib)) + b"".join(lib) + u64(0)
            + u32(1360) + u32(768) + fs(30.0) + fs(0.2, 0.2, 0.2, 1.0) + root)


def _battle_select_scene():
    """Godzilla's Kaiju Battle Select in small: a sprite the game picks a look of (Level 0,
    Level 1), each look a sprite of its own with a picture and a name box in it."""
    from tests.test_stern_scene_tree import (FLAG, bitmap, cls, node, sprite, texture, u8,
                                             u32, u64, fs)
    lib = [
        u32(3) + cls(1, "Bitmap") + u32(FLAG | 10) + bitmap(3, 8, 4, texture(20)),
        u32(5) + cls(2, "Sprite") + u32(FLAG | 12) + sprite(5, "", 1, [
            node(60, "Ebirah_Art", [u32(1) + cls(1) + u32(10)]),
            node(61, "Ebirah_Box", [u32(1) + cls(1) + u32(10)])]),
        u32(6) + cls(2) + u32(FLAG | 13) + sprite(6, "", 1, [
            node(70, "Gigan_Art", [u32(1) + cls(1) + u32(10)]),
            node(71, "Gigan_Box", [u32(1) + cls(1) + u32(10)])]),
        u32(4) + cls(2) + u32(FLAG | 11) + sprite(4, "", 2, [
            node(40, "Ebirah", [u32(1) + cls(2) + u32(12)], kf=((1, 1), (2, 0))),
            node(41, "Gigan", [u32(1) + cls(2) + u32(13)], kf=((1, 0), (2, 1)))],
            labels=[("Ebirah", 1), ("Gigan", 2)]),
    ]
    root = sprite(2, "", 20, [node(50, "Select", [u32(1) + cls(2) + u32(11)])],
                  labels=[("Start", 1)])
    return (u8(1) + u64(len(lib)) + b"".join(lib) + u64(0)
            + u32(1360) + u32(768) + fs(30.0) + fs(0.2, 0.2, 0.2, 1.0) + root)


def test_a_hidden_layer_in_a_sprite_is_shown_alone_and_the_sprite_whole(tmp_path):
    """DragonRR (PAD-284): picking the text box of a body the game is not showing drew the
    whole body; picking the body after it then did nothing.  The text box is drawn alone; the
    body, picked next, is drawn with everything in it."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder, _body_scene())
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_moment", "f:1")
        assert _wait(w, lambda: _tv(w)["frame"] == 1)
        ly = {l["name"]: l for l in _tv(w)["layers"]}
        body = ly["BodyA"] if not ly["BodyA"]["drawn"] else ly["BodyB"]
        assert body["name"] == "BodyB", "the picker rests on A"
        assert w.call("text_scenes.tree_select", ly["Body_Textbox"]["id"])
        tv = _tv(w)
        assert tv["props"]["peek"]
        hits = [h["id"] for h in tv["hits"]]
        assert ly["Body_Textbox"]["id"] in hits and ly["Body_Art"]["id"] not in hits
        assert w.call("text_scenes.tree_select", body["id"])
        tv = _tv(w)
        assert tv["props"]["peek"] and tv["sel"] == body["id"]
        hits = [h["id"] for h in tv["hits"]]
        assert ly["Body_Textbox"]["id"] in hits and ly["Body_Art"]["id"] in hits
        assert w.call("text_scenes.tree_select", None)
        hits = [h["id"] for h in _tv(w)["hits"]]
        assert ly["Body_Textbox"]["id"] not in hits and ly["Body_Art"]["id"] not in hits
        w.call("text_scenes.close")


def test_a_layer_in_a_sprite_hidden_with_its_eye_is_shown_when_picked(tmp_path):
    """DragonRR (PAD-286): with a body hidden with its eye, picking a picture in it said "The
    game does not draw that at any moment of this scene".  It is drawn alone on top, at any
    moment, and the Selected panel names the hidden sprite; no edit is made."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder, _body_scene())
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        ly = {l["name"]: l for l in _tv(w)["layers"]}
        body, box, art = ly["BodyB"]["id"], ly["Body_Textbox"]["id"], ly["Body_Art"]["id"]
        assert w.call("text_scenes.tree_view", body, False)
        for f in (1, 2):                        # the picker on A (B off anyway), then on B
            assert w.call("text_scenes.tree_moment", "f:%d" % f)
            assert _wait(w, lambda: _tv(w)["frame"] == f)
            assert w.call("text_scenes.tree_select", box)
            tv = _tv(w)
            assert tv["frame"] == f and tv["sel"] == box
            assert "The game does not draw that" not in " ".join(tv.get("notes") or [])
            assert tv["props"]["peek"] and tv["props"]["view_in"] == "BodyB"
            assert tv["props"]["hid_in"] == ""
            assert tv["props"]["x"] is not None
            hits = [h["id"] for h in tv["hits"]]
            assert box in hits and art not in hits
            assert w.call("text_scenes.tree_select", None)
            hits = [h["id"] for h in _tv(w)["hits"]]
            assert box not in hits and art not in hits
        assert _ops(folder) == []
        w.call("text_scenes.close")


def test_a_picked_layer_is_drawn_on_top_whatever_its_eye_says(tmp_path):
    """DragonRR (PAD-289): picking any layer shows it on top while it is picked - one hidden
    with its eye too - and picking a sprite shows every layer in it, those hidden with their
    eye included; no eye changes, and picking nothing puts the scene back."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder, _body_scene())
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        ly = {l["name"]: l for l in _tv(w)["layers"]}
        body, box, art = ly["BodyB"]["id"], ly["Body_Textbox"]["id"], ly["Body_Art"]["id"]
        assert w.call("text_scenes.tree_state", ly["Select"]["id"], 2)     # the picker on B
        hits = [h["id"] for h in _tv(w)["hits"]]
        assert hits.index(art) < hits.index(box), "the text box is drawn over the art"
        # a layer on the screen comes to the front while picked
        assert w.call("text_scenes.tree_select", art)
        tv = _tv(w)
        assert tv["hits"][-1]["id"] == art and not tv["props"]["peek"]
        assert w.call("text_scenes.tree_select", None)
        assert [h["id"] for h in _tv(w)["hits"]] == hits
        # hidden with its eye: picked, it is shown on top, and its eye stays shut
        assert w.call("text_scenes.tree_view", art, False)
        assert art not in [h["id"] for h in _tv(w)["hits"]]
        assert w.call("text_scenes.tree_select", art)
        tv = _tv(w)
        assert tv["hits"][-1]["id"] == art and tv["props"]["peek"] and tv["props"]["view_off"]
        assert tv["props"]["x"] is not None
        assert next(l for l in tv["layers"] if l["id"] == art)["view_off"]
        # the sprite it sits in, picked: every layer in it, the hidden one too, on top
        assert w.call("text_scenes.tree_select", body)
        tv = _tv(w)
        assert [h["id"] for h in tv["hits"]][-2:] == [art, box]
        assert w.call("text_scenes.tree_select", None)
        assert art not in [h["id"] for h in _tv(w)["hits"]]
        assert _ops(folder) == []
        # the sprite hidden too: its eye opened again, the art stays hidden (its own eye)
        assert w.call("text_scenes.tree_view", body, False)
        assert box not in [h["id"] for h in _tv(w)["hits"]]
        assert w.call("text_scenes.tree_view", body, True)
        hits = [h["id"] for h in _tv(w)["hits"]]
        assert box in hits and art not in hits
        w.call("text_scenes.close")


def test_an_eye_hide_is_named_as_hidden_in_the_game(tmp_path):
    """DragonRR (PAD-290): with the picker on a monster, its body's eye hides it on the card,
    not just the preview - the row and the status line say so, until its eye shows it again."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder, _body_scene())
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        ly = {l["name"]: l for l in _tv(w)["layers"]}
        assert w.call("text_scenes.tree_state", ly["Select"]["id"], 2)     # the picker on B
        assert _tv(w)["hidden_names"] == []
        assert w.call("text_scenes.tree_visible", ly["BodyB"]["id"], False)
        tv = _tv(w)
        assert tv["hidden_names"] == ["BodyB"]
        assert next(l for l in tv["layers"] if l["name"] == "BodyB")["edits"] == "hidden in game"
        assert ly["Body_Art"]["id"] in [h["id"] for h in tv["hits"]]   # not in the preview
        assert w.call("text_scenes.tree_visible", ly["BodyB"]["id"], True)
        assert _tv(w)["hidden_names"] == []
        w.call("text_scenes.close")


def test_the_game_eye_and_the_preview_eye_are_apart(tmp_path):
    """DragonRR (PAD-293): two eyes per layer.  The red eye hides a layer in the game (Write
    leaves it out) and never changes the preview; the blue eye hides it in the preview only.
    A scene opened for the first time starts with its blue eyes as its red ones; after that
    they are apart until the scene is reset."""
    from pinball_decryptor.plugins.stern import scene_edit
    folder = tmp_path / "proj"
    folder.mkdir()
    man = _seed(folder, _body_scene())
    from pinball_decryptor.webui.text_scenes_tree import _walk_man
    ids = {n["name"]: n["id"] for n, _p, _d in _walk_man(man)}
    art, box = ids["Body_Art"], ids["Body_Textbox"]
    # hidden in the game before the scene was ever opened
    scene_edit.add(str(folder), CARD, {"op": "visible", "node": art, "on": False})
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        ly = {l["name"]: l for l in _tv(w)["layers"]}
        assert w.call("text_scenes.tree_state", ly["Select"]["id"], 2)     # the picker on B
        hits = lambda: [h["id"] for h in _tv(w)["hits"]]                  # noqa: E731
        lay = lambda: {l["id"]: l for l in _tv(w)["layers"]}               # noqa: E731
        # first open: the blue eye copies the red one
        assert lay()[art]["hidden"] and lay()[art]["view_off"]
        assert art not in hits() and box in hits() and not _tv(w)["view_apart"]
        # the red eye alone: the card changes, the preview does not
        assert w.call("text_scenes.tree_visible", art, True)
        assert _ops(folder) == [] and not lay()[art]["hidden"] and lay()[art]["view_off"]
        assert art not in hits() and _tv(w)["view_apart"]
        assert w.call("text_scenes.tree_visible", box, False)
        assert lay()[box]["hidden"] and not lay()[box]["view_off"] and box in hits()
        assert _tv(w)["hidden_names"] == ["Body_Textbox"]
        # the blue eye alone: the preview changes, the card does not
        assert w.call("text_scenes.tree_view", art, True)
        assert art in hits()
        assert w.call("text_scenes.tree_view", box, False)
        assert box not in hits()
        assert _ops(folder) == [{"op": "visible", "node": box, "on": False}]
        # picked, a layer hidden with its blue eye is shown on top; no eye changes
        assert w.call("text_scenes.tree_select", box)
        assert hits()[-1] == box and lay()[box]["view_off"]
        assert w.call("text_scenes.tree_select", None)
        # kept while another scene is looked at, and put back to the game's by Reset
        w.call("text_scenes.select", "")
        _open(w, folder)
        assert lay()[box]["view_off"] and not lay()[art]["view_off"]
        assert w.call("text_scenes.tree_view_reset")
        assert lay()[box]["view_off"] and not lay()[art]["view_off"] and not _tv(w)["view_apart"]
        assert w.call("text_scenes.tree_view", box, True)
        w.answers.append("yes")
        assert w.call("text_scenes.tree_clear")                    # As shipped
        assert _ops(folder) == [] and not lay()[box]["view_off"] and box in hits()
        w.call("text_scenes.close")


def test_alt_click_on_an_eye_shows_that_layer_alone(tmp_path):
    """PAD-293, as in Photoshop: Alt+click on a layer's eye shows it alone in the preview,
    Alt+click on another moves the solo there, and Alt+click again puts every eye back as it
    was; a plain eye click ends it where it is.  The card is never changed."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder, _body_scene())
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        ly = {l["name"]: l for l in _tv(w)["layers"]}
        assert w.call("text_scenes.tree_state", ly["Select"]["id"], 2)     # the picker on B
        art, box = ly["Body_Art"]["id"], ly["Body_Textbox"]["id"]
        hits = lambda: [h["id"] for h in _tv(w)["hits"]]                  # noqa: E731
        before = hits()
        assert art in before and box in before
        assert w.call("text_scenes.tree_view", box, False)                 # an eye shut first
        assert w.call("text_scenes.tree_view_solo", art)
        assert hits() == [art] and _tv(w)["solo"] == art
        assert w.call("text_scenes.tree_view_solo", box)
        assert hits() == [box] and _tv(w)["solo"] == box
        assert w.call("text_scenes.tree_view_solo", box)
        assert _tv(w)["solo"] is None
        assert hits() == [h for h in before if h != box]                  # its eye still shut
        assert w.call("text_scenes.tree_view_solo", art)
        assert w.call("text_scenes.tree_view", box, True)                  # a plain click
        assert _tv(w)["solo"] is None and box in hits() and art in hits()
        assert _ops(folder) == []
        w.call("text_scenes.close")


def test_a_hidden_layer_the_game_draws_elsewhere_is_found_when_picked(tmp_path):
    """DragonRR (PAD-289): a layer hidden with its eye in a sprite the game is not drawing at
    this moment goes, picked, to where the game shows that sprite, and is drawn there."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder, _body_scene())
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_moment", "f:1")
        assert _wait(w, lambda: _tv(w)["frame"] == 1)
        ly = {l["name"]: l for l in _tv(w)["layers"]}
        art = ly["Body_Art"]["id"]
        assert w.call("text_scenes.tree_visible", art, False)
        assert w.call("text_scenes.tree_view", art, False)
        assert w.call("text_scenes.tree_select", art)
        tv = _tv(w)
        assert "The game does not draw that" not in " ".join(tv.get("notes") or [])
        assert tv["sel"] == art and tv["hits"][-1]["id"] == art
        assert _ops(folder) == [{"op": "visible", "node": art, "on": False}]
        w.call("text_scenes.close")


def test_a_layer_inside_a_look_that_is_off_keeps_its_own_eye(tmp_path):
    """DragonRR (PAD-285): with Gigan's name box selected (shown with the Gigan look it sits
    in), clicking the Gigan picture beside it showed nothing - the picture counted as drawn
    because the name box's peek had brought it along.  And the eyes work as in an editor's
    layers: a layer inside a look keeps its own eye, shows only while that look is on, and
    turning the look on leaves a layer hidden inside it hidden."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder, _battle_select_scene())
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_moment", "f:1")
        assert _wait(w, lambda: _tv(w)["frame"] == 1)
        lay = lambda: {l["name"]: l for l in _tv(w)["layers"]}      # noqa: E731
        ly = lay()
        assert ly["Gigan"]["state_off"] and not ly["Gigan"]["part_off"]
        for name in ("Gigan_Art", "Gigan_Box"):
            assert not ly[name]["drawn"] and ly[name]["part_off"] and not ly[name]["state_off"]
        art, box = ly["Gigan_Art"]["id"], ly["Gigan_Box"]["id"]

        # the name box, then the picture beside it: each is shown while selected
        assert w.call("text_scenes.tree_select", box)
        assert _tv(w)["props"]["peek"] and not lay()["Gigan_Art"]["drawn"]  # alone (PAD-284)
        assert w.call("text_scenes.tree_select", art)
        p = _tv(w)["props"]
        assert p["peek"] and p["x"] is not None
        assert w.call("text_scenes.tree_select", None)
        assert not any(lay()[n]["drawn"] for n in ("Gigan", "Gigan_Art", "Gigan_Box"))

        # an eye inside the look does not turn the look on
        assert w.call("text_scenes.tree_force", art, True)
        assert not lay()["Gigan_Art"]["drawn"] and lay()["Gigan"]["state_off"]
        assert w.call("text_scenes.tree_force", art, False)
        # the name box hidden while its look is off stays hidden when the look is turned on
        assert w.call("text_scenes.tree_view", box, False)
        assert w.call("text_scenes.tree_force", ly["Gigan"]["id"], True)
        ly = lay()
        assert ly["Gigan"]["drawn"] and ly["Gigan_Art"]["drawn"]
        assert not ly["Gigan_Box"]["drawn"] and ly["Gigan_Box"]["view_off"]
        assert ly["Ebirah_Art"]["drawn"]
        w.call("text_scenes.close")


def test_play_draws_each_different_frame_once_and_stops(tmp_path):
    """DragonRR: "play the animation as well as step through it". Play draws the scene's
    frames in the background (a held stretch once) and hands them to the page with a map
    from every frame to its picture; Stop, or an edit, ends it."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_play", True)
        assert w.state("text_scenes")["tree_play"]["frames"] == 20
        assert _wait(w, lambda: (w.state("text_scenes").get("tree_play") or {}).get("done"))
        play = w.state("text_scenes")["tree_play"]
        assert len(play["map"]) == 20 and 1 <= len(play["srcs"]) <= 20 and play["fps"] > 0
        assert all(os.path.isfile(p) for p in play["srcs"]) and play["run"]
        assert max(play["map"]) == len(play["srcs"]) - 1
        assert w.call("text_scenes.tree_play", False)
        assert w.state("text_scenes")["tree_play"] is None
        assert w.call("text_scenes.tree_play", True)
        art = next(h for h in _tv(w)["hits"] if h["name"] == "Art")["id"]
        assert w.call("text_scenes.tree_move", art, 5, 0)
        assert w.state("text_scenes")["tree_play"] is None             # an edit stops it
        w.call("text_scenes.close")


def test_turn_a_picture_and_give_text_a_drop_shadow(tmp_path):
    """DragonRR: "graphics can be rotated" and "can text have drop shadows?"."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        art = next(h for h in _tv(w)["hits"] if h["name"] == "Art")["id"]
        assert w.call("text_scenes.tree_select", art)
        p = _tv(w)["props"]
        mid = (p["x"] + p["w"] / 2.0, p["y"] + p["h"] / 2.0)
        w0, h0 = p["w"], p["h"]
        assert p["rotate"] == 0
        assert w.call("text_scenes.tree_rotate", art, 90)
        p = _tv(w)["props"]
        assert p["rotate"] == 90
        # a quarter turn about its middle: the box swaps sides and the middle stays put
        assert abs(p["w"] - h0) <= 1 and abs(p["h"] - w0) <= 1
        assert abs(p["x"] + p["w"] / 2.0 - mid[0]) <= 1 and abs(p["y"] + p["h"] / 2.0 - mid[1]) <= 1
        # the Turn box sets how far from as shipped; back to 0 leaves no edit
        assert w.call("text_scenes.tree_set_rotation", art, 0)
        assert _tv(w)["props"]["rotate"] == 0 and _ops(folder) == []

        title = next(h for h in _tv(w)["hits"] if h["name"] == "Title")["id"]
        assert w.call("text_scenes.tree_shadow", art) is False       # text only
        assert w.call("text_scenes.tree_shadow", title)
        tv = _tv(w)
        sh = tv["props"]
        assert sh["added"] and sh["kind"] == "Text" and sh["name"] == "Title_Shadow"
        names = [l["name"] for l in tv["layers"]]
        assert names.index("Title_Shadow") == names.index("Title") - 1
        # it is removed like anything added
        assert w.call("text_scenes.tree_reset", sh["id"])
        assert _ops(folder) == []
        w.call("text_scenes.close")


def test_several_picked_at_once_move_and_hide_together(tmp_path):
    """DragonRR (PAD-279): "select multiple items with shift" to move a line of words at
    once.  Ctrl-click adds to the selection (or takes one out), Shift-click in Layers picks a
    run; a move of the selection is one edit per node and one undo step."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        hits = _tv(w)["hits"]
        art = next(h for h in hits if h["name"] == "Art")["id"]
        title = next(h for h in hits if h["name"] == "Title")["id"]
        assert w.call("text_scenes.tree_select", art)
        a0 = _tv(w)["props"]
        assert w.call("text_scenes.tree_select", title, "add")
        tv = _tv(w)
        assert tv["sels"] == [art, title] and tv["sel"] == title
        assert len(tv["sel_boxes"]) == 2
        t0 = tv["props"]

        # moved together: one op each, one undo step
        assert w.call("text_scenes.tree_move_many", [art, title], 20, 5)
        ops = _ops(folder)
        assert sorted(op["node"] for op in ops) == sorted([art, title])
        assert len({op.get("group") for op in ops}) == 1
        # a second drag of the same pair folds in, as a drag of one does
        assert w.call("text_scenes.tree_move_many", [art, title], 5, 0)
        assert len(_ops(folder)) == 2
        tv = _tv(w)
        assert tv["sels"] == [art, title]
        assert (tv["props"]["x"], tv["props"]["y"]) == (t0["x"] + 25, t0["y"] + 5)
        assert w.call("text_scenes.tree_select", art)
        assert _tv(w)["sels"] == [art]
        assert (_tv(w)["props"]["x"], _tv(w)["props"]["y"]) == (a0["x"] + 25, a0["y"] + 5)
        # each drag is still its own undo step (PAD-283)
        assert w.call("text_scenes.tree_undo")
        assert sorted((op["dx"], op["dy"]) for op in _ops(folder)) == [(20.0, 5.0)] * 2
        assert w.call("text_scenes.tree_undo")
        assert _ops(folder) == []

        # Ctrl-click again takes it out; Shift-click in Layers picks the run between
        assert w.call("text_scenes.tree_select", title, "add")
        assert w.call("text_scenes.tree_select", title, "add")
        assert _tv(w)["sels"] == [art]
        order = [l["id"] for l in _tv(w)["layers"]]
        assert w.call("text_scenes.tree_select", art)       # (a range runs from the last click)
        assert w.call("text_scenes.tree_select", title, "range")
        a, b = sorted((order.index(art), order.index(title)))
        assert sorted(_tv(w)["sels"]) == sorted(order[a:b + 1])
        assert _tv(w)["sels"][-1] == title

        # hidden together, one undo step; a plain click picks one again
        assert w.call("text_scenes.tree_visible_many", [art, title], False)
        assert all(any(h["id"] == n for h in _tv(w)["hits"]) for n in (art, title))
        assert w.call("text_scenes.tree_undo")
        assert _ops(folder) == []
        assert w.call("text_scenes.tree_view_many", [art, title], False)
        assert not any(h["id"] in (art, title) for h in _tv(w)["hits"])
        assert w.call("text_scenes.tree_view_many", [art, title], True)
        assert _ops(folder) == []
        # Delete: gone from the card and the preview
        assert w.call("text_scenes.tree_remove_many", [art, title])
        assert {op["node"] for op in _ops(folder)} == {art, title}
        assert not any(h["id"] in (art, title) for h in _tv(w)["hits"])
        assert w.call("text_scenes.tree_visible_many", [art, title], True)
        assert _ops(folder) == []
        w.call("text_scenes.close")


def test_a_layers_picture_button_lands_on_it_on_the_images_tab(tmp_path):
    """PAD-287: every layer that draws a picture - itself or through what it holds - names
    it, and the button lands on it on the Images tab, even on the tab's first visit (the
    jump used to arrive before the scan and the scan then picked the first row)."""
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        layers = _tv(w)["layers"]
        art = next(l for l in layers if l["name"] == "Art")
        title = next(l for l in layers if l["name"] == "Title")
        assert len(art["pics"]) == 1
        assert art["pics"][0].startswith("images/scene_textures/pic_")
        assert os.path.isfile(os.path.join(str(folder), *art["pics"][0].split("/")))
        assert title["pics"] == []
        at = layers.index(art)
        holders = [l for l in layers[:at] if l["depth"] < art["depth"]]
        assert all(art["pics"][0] in l["pics"] for l in holders)

        assert w.call("text_scenes.activate", "img::" + art["pics"][0])
        assert _wait(w, lambda: ((w.state("images").get("focus") or {}).get("id")
                                 == art["pics"][0]), 20)
        assert w.state("shell")["tab"] == "images"
