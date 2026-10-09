"""PAD-471 (DragonRR): "I had previously set ALL images and text to BW", yet the first scene's
green line stayed green, and after the update "all the palette icons are red as if no profile
assigned".

All images reached the pictures of Godzilla's orange font, so every line in it came out black
and white, but each such line's palette stayed red (its own switch was off); and a line whose
colour is its own (a plain font, or white letters) has only its own switch, which nothing set
for all lines at once.  Now a line its font's pictures correct shows a green palette (with the
link), and the Colors bar on a line of text has Apply to all profiled lines of text / Apply to
all lines of text, and Which files has All text, each one Undo step.
"""

import os

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes
from pinball_decryptor.plugins.stern import scene_edit as X, text_colour as TC
from tests.test_pad451_line_own_font import (
    BW, CARD, MINE, OTHER, P1, P2, _atlases, _seed_font)

pytest.importorskip("PIL.Image")

WHITE = (255, 255, 255)
SEPIA = cp.Profile(name="Sepia", gain=(1.2, 1.0, 0.8))


def _white_font(folder):
    """The PAD-451 scene with its font's pictures white: each line's colour is its own."""
    _seed_font(folder)
    _atlases(folder, colour=WHITE)


def _added(folder, node_id=X.FIRST_ADDED_ID + 1, color=None):
    op = {"op": "add_text", "parent": None, "index": 0, "id": node_id, "name": "Mine copy",
          "text": "AB", "x": 0, "y": 0, "like": MINE}
    if color is not None:
        op["color"] = color
    X.set_ops(str(folder), CARD, [op])
    return node_id


def _rel(node):
    return cp.text_rel(CARD, node)


# ---------------------------------------------------------------------------------------------
# every line, and their switches at once (plugins.stern.text_colour)
# ---------------------------------------------------------------------------------------------
def test_every_line_lists_each_line_not_locked(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    _white_font(folder)
    a = str(folder)
    assert TC.every_line(a) == {}                         # the game's lines are locked
    staged_changes.save(a, {cp.STOCK_IMAGES_KEY: True})
    got = TC.every_line(a)
    assert set(got) == {_rel(MINE), _rel(OTHER)}
    assert all(sw["on"] is False and sw["stock"] and "art" not in sw for sw in got.values())
    # a line added in Scenes is one too, with its own edit's switch
    added = _added(folder, color=True)
    got = TC.every_line(a)
    assert set(got) == {_rel(MINE), _rel(OTHER), _rel(added)}
    assert got[_rel(added)]["added"] is True and got[_rel(added)]["on"] is True
    # locked again: only the added line has a switch
    staged_changes.save(a, {})
    assert set(TC.every_line(a)) == {_rel(added)}


def test_a_line_its_fonts_pictures_correct_says_so(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed_font(folder)                                    # orange letters: the font's own
    a = str(folder)
    staged_changes.save(a, {cp.STOCK_IMAGES_KEY: True,
                            cp.IMAGE_SLOTS_KEY: {"images/" + P1: True}})
    got = TC.every_line(a)
    assert got[_rel(MINE)]["art"] is True and got[_rel(MINE)]["font_on"] is False
    staged_changes.save(a, {cp.STOCK_IMAGES_KEY: True,
                            cp.IMAGE_SLOTS_KEY: {"images/" + P1: True, "images/" + P2: True}})
    got = TC.every_line(a)
    assert got[_rel(MINE)]["font_on"] is True and got[_rel(OTHER)]["font_on"] is True
    assert TC.font_on({"font_pictures": ["images/" + P1, "images/" + P2]},
                      staged_changes.peek(a)) is True
    assert TC.font_on({"font_pictures": []}, staged_changes.peek(a)) is False


def test_put_line_switches_sets_game_and_added_lines_and_says_what_they_were(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    _white_font(folder)
    a = str(folder)
    added = _added(folder)
    staged_changes.save(a, {cp.STOCK_IMAGES_KEY: True, cp.TEXT_SLOTS_KEY: {_rel(OTHER): True}})
    was = TC.put_line_switches(a, {_rel(MINE): True, _rel(OTHER): True, _rel(added): True})
    assert was == {_rel(MINE): None, _rel(OTHER): True, _rel(added): None}
    assert cp.text_lines_on(a) == {_rel(MINE), _rel(OTHER)}
    assert X.ops_for(a, CARD)[0]["color"] is True
    # what it was puts it back
    assert TC.put_line_switches(a, was) == {_rel(MINE): True, _rel(OTHER): True,
                                            _rel(added): True}
    assert cp.text_lines_on(a) == {_rel(OTHER)}
    assert "color" not in X.ops_for(a, CARD)[0]
    # the game's lines are switched only while they are unlocked
    staged_changes.save(a, {})
    assert TC.put_line_switches(a, {_rel(MINE): True}) == {}
    assert cp.TEXT_SLOTS_KEY not in staged_changes.load(a)


# ---------------------------------------------------------------------------------------------
# the app
# ---------------------------------------------------------------------------------------------
def _layer(w, nid):
    from tests.test_gui_scene_editor import _tv
    return next((l for l in _tv(w)["layers"] if l["id"] == nid), {})


def _on_line(w, nid):
    c = _layer(w, nid)["color"]
    assert w.call("color.panel_open")
    assert w.call("color.set_mode", "assets")
    assert w.call("color.set_file", "text", c["rel"], "line", bool(c["on"]),
                  {"ns": "scenes", "node": nid})
    w.drain()


def test_apply_to_all_lines_of_text_asks_first_and_undoes_as_one_step(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _open, _wait
    folder = tmp_path / "proj"
    folder.mkdir()
    _white_font(folder)
    a = str(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_color_unlocked", True)
        assert _wait(w, lambda: (_layer(w, MINE).get("color") or {}).get("on") is False)
        # Mine gets a profile of its own (attached by the pick); Other has nothing attached
        _on_line(w, MINE)
        assert w.call("color.preset", "bw")
        w.drain()
        assert cp.text_lines_on(a) == {_rel(MINE)}
        assert cp.own_profile_names(a)["text"] == {_rel(MINE): "Black and white"}
        # the bar on a line of text offers it
        assert w.state("color")["file"]["kind"] == "text"
        # profiled: only Mine has one attached, so there is nothing else to give it to
        n = len(w.asked)
        assert w.call("color.apply_to_all", "profiled") is False
        assert len(w.asked) == n
        toasts = w.state("shell").get("toasts") or []
        assert "palette in the Scenes layers" in toasts[-1]["text"]
        # all: No changes nothing
        w.answers.append("no")
        assert w.call("color.apply_to_all", "all") is False
        q = w.asked[-1]
        assert q["title"] == "Apply to all lines of text"
        assert "Every line of text that is not locked (each one added in Scenes, and the " \
               "game's own lines while they are unlocked), all 2 of them" in q["message"]
        assert "“Black and white”" in q["message"]
        assert "attached to the one that has none" in q["message"]
        assert cp.text_lines_on(a) == {_rel(MINE)}
        # Yes: both lines have it, attached, Other's palette green
        w.answers.append("yes")
        assert w.call("color.apply_to_all", "all") is True
        w.drain()
        assert cp.text_lines_on(a) == {_rel(MINE), _rel(OTHER)}
        assert cp.own_profile_names(a)["text"] == {_rel(MINE): "Black and white",
                                                   _rel(OTHER): "Black and white"}
        assert _wait(w, lambda: (_layer(w, OTHER).get("color") or {}).get("on") is True)
        log = [l["text"] for l in w.run(w.window.log_history)]
        assert any("applied to all 2 lines of text (attached to 1)" in t for t in log)
        # Undo: Other's profile and switch as they were; Redo: again
        assert w.call("color.undo")
        w.drain()
        assert cp.text_lines_on(a) == {_rel(MINE)}
        assert cp.own_profile_names(a)["text"] == {_rel(MINE): "Black and white"}
        assert _wait(w, lambda: (_layer(w, OTHER).get("color") or {}).get("on") is False)
        assert w.call("color.undo", True)
        w.drain()
        assert cp.text_lines_on(a) == {_rel(MINE), _rel(OTHER)}


def test_all_text_gives_every_line_the_individual_files_profile(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _open, _wait
    folder = tmp_path / "proj"
    folder.mkdir()
    _white_font(folder)
    a = str(folder)
    added = _added(folder)
    cp.store_asset_profile(a, BW)
    cp.store_own_profile(a, "text", _rel(OTHER), SEPIA)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_color_unlocked", True)
        assert _wait(w, lambda: (_layer(w, MINE).get("color") or {}).get("on") is False)
        assert w.call("color.panel_open")
        assert w.call("color.set_mode", "assets")
        w.answers.append("yes")
        assert w.call("color.apply_to_all", "all", "text") is True
        q = w.asked[-1]
        assert q["title"] == "All lines of text"
        assert "all 3 of them" in q["message"] and "One of them loses" in q["message"]
        w.drain()
        assert cp.text_lines_on(a) == {_rel(MINE), _rel(OTHER)}
        assert X.ops_for(a, CARD)[0]["color"] is True
        assert cp.own_profile_names(a)["text"] == {}
        # one Undo: the switches and Other's own profile back
        assert w.call("color.undo")
        w.drain()
        assert not cp.text_lines_on(a)
        assert "color" not in X.ops_for(a, CARD)[0]
        assert cp.own_profile_names(a)["text"] == {_rel(OTHER): "Sepia"}
        del added


def test_a_line_its_fonts_pictures_correct_is_green_and_left_out_of_all(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _open, _wait
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed_font(folder)                                    # orange: GameFont_Secondary
    a = str(folder)
    cp.store_asset_profile(a, BW)
    staged_changes.save(a, dict(staged_changes.load(a), **{
        cp.STOCK_IMAGES_KEY: True,
        cp.IMAGE_SLOTS_KEY: {"images/" + P1: True, "images/" + P2: True}}))
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert _wait(w, lambda: (_layer(w, MINE).get("color") or {}).get("font_on") is True)
        c = _layer(w, MINE)["color"]
        assert c["on"] is False and c["art"] is True
        # its palette's click says where the profile comes from; no copy of the font for it
        assert w.call("text_scenes.tree_color", MINE, True, True) is False
        toasts = w.state("shell").get("toasts") or []
        assert "corrected with every line in GameFont_Secondary" in toasts[-1]["text"]
        assert not cp.text_lines_on(a)
        # the Colors bar's pick still gives it one of its own (no palette click)
        assert w.call("text_scenes.tree_color", MINE, True) is True
        assert cp.text_lines_on(a) == {_rel(MINE)}
        # Apply to all lines of text leaves Other out: its font corrects it already
        _on_line(w, MINE)
        n = len(w.asked)
        assert w.call("color.apply_to_all", "all") is False
        assert len(w.asked) == n                          # nothing else to give it to
        assert w.window.service("color")._lines.left_out == 1


def test_the_page_offers_it():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tabs = os.path.join(here, "pinball_decryptor", "webui", "static", "js", "tabs")

    def src(name):
        with open(os.path.join(tabs, name), encoding="utf-8") as f:
            return f.read()
    scenes = src("text_scenes.js")
    assert 'l.color.on || l.color.font_on ? "on" : "off"' in scenes
    assert 'call("text_scenes.tree_color", l.id, !l.color.on, true)' in scenes
    assert "Color profile attached through its font" in scenes
    pane = src("color_pane.js")
    assert 'scenes: "text"' in pane and '"lines of text", "line of text"' in pane
    # the videos' and images' tooltip is still DragonRR's own words (PAD-462)
    assert ("every single ${one} existing and replaced will be affected. You can undo this "
            "function") in pane
    assert '["text", "All text…"' in src("color.js")
