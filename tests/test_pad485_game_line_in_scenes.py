"""PAD-485 (DragonRR): Show in Scenes on a game-program line said "no scene file to show".

The game puts its line into a text box on one of its screens as it runs, and that box's own
words are a stand-in (Godzilla's Megalon and Gigan jackpot award screen holds "GIGAN
JACKPOT" where the game program has "GIGAN JACKPOT!").  Show in Scenes now opens that screen
with the line's layer picked in the scene editor, so its box and Font controls are at hand,
and the preview draws the game line's new words in it."""

import time

import pytest

from tests.test_gui_scene_editor import CARD, _seed, _tv
from tests.webui_harness import web_app

pytest.importorskip("PIL")


def _wait(w, pred, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        w.drain()
        if pred():
            return True
        time.sleep(0.03)
    raise AssertionError("timed out waiting")


def _two_title_scene():
    """The synthetic scene's Art and KAIJU title, plus a second KAIJU title inside an
    Award_Textbox sprite: two lines with the same words, as Godzilla's award screens have."""
    from tests.test_stern_scene_tree import (FLAG, bitmap, cls, fs, mat, node, sprite, text,
                                             texture, u32, u64, u8)
    award = node(61, "Title", [u32(1) + cls(3) + u32(FLAG | 31) + text(12, "KAIJU", (9, 7))],
                 tracks=((1, mat(1, 100, 500)),))
    root_kids = [
        node(50, "Art", [u32(1) + cls(1, "Bitmap") + u32(FLAG | 12) + bitmap(3, 16, 8, texture(21, 16, 8))]),
        node(53, "Title", [u32(1) + cls(3, "Text") + u32(FLAG | 13) + text(5, "KAIJU", (9, 7))]),
        node(60, "Award_Textbox", [u32(1) + cls(2, "Sprite") + u32(FLAG | 30) + sprite(11, "", 2, [award])],
             tracks=((1, mat(1, 0, 0)),)),
    ]
    root = sprite(2, "", 20, root_kids, labels=[("Start", 1), ("End", 20)])
    return (u8(1) + u64(0) + u64(0) + u32(1360) + u32(768) + fs(30.0) + fs(0.2, 0.2, 0.2, 1.0) + root)


def _project(tmp_path, program, two=False):
    from pinball_decryptor.core import text_manifest
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder, _two_title_scene() if two else None)
    text_manifest.save(str(folder), [
        {"path": CARD, "original": "KAIJU", "replacement": ""},
        {"path": "/g/scene2/scene.radium", "original": "BALL ONE", "replacement": ""},
        dict({"path": "/g/game", "replacement": "", "budget": 96, "grow": True},
             **program)])
    return folder


def _row(w, original, path_part):
    rows = w.window.service("text")._text_rows
    return next(i for i, r in enumerate(rows)
                if r["original"] == original and path_part in r["path"])


def _show(w, folder, original):
    w.run(lambda: w.window.write_assets_var.set(str(folder)))
    w.call("ui.select_tab", "text")
    _wait(w, lambda: not w.state("text")["scanning"] and w.state("text").get("total", 0) > 0)
    w.call("text.select", _row(w, original, "/game"))
    assert w.call("text.show_in_scene") is True
    _wait(w, lambda: (w.state("text_scenes").get("frames") or []) != [])


def _title(w):
    return next(h for h in _tv(w)["hits"] if h["name"] == "Title")["id"]


def test_a_game_line_opens_its_screen_with_the_layer_picked(tmp_path):
    folder = _project(tmp_path, {"original": "KAIJU!"})
    with web_app(tmp_path, mfr="stern") as w:
        _show(w, folder, "KAIJU!")
        sc = w.state("text_scenes")
        assert sc["sel"] == "/g/scene1" and sc["item"] == "txt::0"
        assert w.state("shell")["tab"] == "scenes"
        # the box the game fills is picked in the scene editor
        assert _tv(w)["sel"] == _title(w)
        w.call("text_scenes.close")


def test_the_preview_draws_the_game_lines_new_words_in_its_box(tmp_path):
    import json
    from pinball_decryptor.plugins.stern import scene_render
    folder = _project(tmp_path, {"original": "KAIJU!",
                                 "replacement": "GODZILLA UNLEASHED!"})
    # the lines the scene draws, as an extract lists them
    with open(str(folder / scene_render.SCENE_LAYOUT_MANIFEST), "w", encoding="utf-8") as f:
        json.dump({CARD: {"stage": [320, 180, 60.0], "unplaced": 0, "offstage": 0,
                          "sprites": [], "texts": [
                              {"name": "Title", "x": 0, "y": 100, "text": "KAIJU",
                               "rect": [0, 0, 320, 180], "rgba": [1.0, 1.0, 1.0, 1.0],
                               "align": 1, "font": "tbl", "font_px": 8}]}}, f)
    with web_app(tmp_path, mfr="stern") as w:
        _show(w, folder, "KAIJU!")
        svc = w.window.service("text").scenes
        assert w.run(svc._pending_texts, CARD) == {"KAIJU": "GODZILLA UNLEASHED!"}
        groups = {g["key"]: g for g in w.state("text_scenes")["contents"]["groups"]}
        assert groups["txt"]["items"][0]["info"].startswith('shows: "GODZILLA UNLEASHED!"')
        w.call("text_scenes.close")


def _layout(folder, scenes):
    import json
    from pinball_decryptor.plugins.stern import scene_render
    out = {}
    for card, (groups, texts) in scenes.items():
        out[card] = {"stage": [320, 180, 60.0], "unplaced": 0, "offstage": 0, "sprites": [],
                     "groups": groups, "texts": [
                         {"name": name, "group": g, "x": 0, "y": 100, "text": text,
                          "rect": [0, 0, 320, 180], "rgba": [1.0, 1.0, 1.0, 1.0], "align": 1,
                          "font": "tbl", "font_px": 8} for name, g, text in texts]}
    with open(str(folder / scene_render.SCENE_LAYOUT_MANIFEST), "w", encoding="utf-8") as f:
        json.dump(out, f)


def test_a_game_line_no_screen_reads_like_opens_its_battles_award_box(tmp_path):
    """Round 3 (DragonRR): the Heisei card's KAIJU AWARD, the award line of the battles vs Gigan
    and vs Megalon, said there was no screen: no screen's own words read like it.  Its Shown
    in names the battle, and the card's game program names the battle's screens; the award
    box there (its own words the battle's name) is the one that shares the line's words.
    The Scenes search lists the battle's screens by its name; a mode's own row goes to that
    mode's screens."""
    from pinball_decryptor.plugins.stern import engine
    gigan, megalon = "cmode_battle_vs_gigan", "cmode_battle_vs_megalon"
    folder = _project(tmp_path, {"original": "KAIJU AWARD", "modes": [gigan, megalon]}, two=True)
    from pinball_decryptor.core import text_manifest
    rows = text_manifest.load(str(folder))
    rows.insert(1, {"path": "/g/scene2/scene.radium", "original": "GODZILLA VS GIGAN",
                    "replacement": ""})
    rows.append({"path": "/g/game#" + megalon, "original": "KAIJU AWARD", "replacement": "",
                 "budget": 96, "grow": True, "modes": [megalon]})
    rows.append({"path": "/g/scene3/scene.radium", "original": "GODZILLA VS MEGALON",
                 "replacement": ""})
    text_manifest.save(str(folder), rows)
    _layout(folder, {
        CARD: (["Award_Textbox"], [("Title", 0, "KAIJU")]),
        "/g/scene2/scene.radium": (["Lines_Textbox"], [("Line1", 0, "BALL ONE"),
                                                       ("Title", 0, "GODZILLA VS GIGAN")]),
        "/g/scene3/scene.radium": (["Award_Textbox"], [("Title", 0, "GODZILLA VS MEGALON")])})
    engine._program_modes_read(str(folder), {gigan: ["g/scene2", "g/scene1"],
                                             megalon: ["scene3"]})
    with web_app(tmp_path, mfr="stern") as w:
        _show(w, folder, "KAIJU AWARD")
        sc = w.state("text_scenes")
        assert sc["sel"] == "/g/scene1" and sc["item"] == "txt::0"
        assert sc["search"] == "Battle vs Gigan"
        assert [r["d"] for r in sc["scenes"]] == ["/g/scene1", "/g/scene2"]
        # no box named: the first of the scene's two KAIJU lines, the root's own
        assert _tv(w)["sel"] == next(h["id"] for h in _tv(w)["hits"] if h["path"] == "Title")
        w.call("text_scenes.close")
    # the box the game names with the screen wins over the words, and among the named ones
    # the first (Godzilla names Award_Textbox's title before Award_Textbox2's and the
    # emulator drew GIGAN AWARD in the first); the jump picks that very layer, the second
    # of the scene's two "KAIJU" lines, by its dotted path
    engine._program_modes_read(str(folder), {gigan: ["g/scene2", "g/scene1"],
                                             megalon: ["scene3"]},
                               {gigan: {"g/scene1": ["Award_Textbox", "Award_Textbox.Title",
                                                     "Title"]}})
    with web_app(tmp_path, mfr="stern") as w:
        _show(w, folder, "KAIJU AWARD")
        assert w.state("text_scenes")["sel"] == "/g/scene1"
        hits = _tv(w)["hits"]
        named = [h["id"] for h in hits if h["path"] == "Award_Textbox › Title"]
        root = next(h["id"] for h in hits if h["path"] == "Title")
        assert named and _tv(w)["sel"] == named[0] != root
        # the Megalon battle's own row: its one screen, nothing to search for
        w.call("ui.select_tab", "text")
        w.call("text.select", _row(w, "KAIJU AWARD", "#" + megalon))
        assert w.call("text.show_in_scene") is True
        sc = w.state("text_scenes")
        assert sc["sel"] == "/g/scene3" and sc["item"] == "txt::0" and sc["search"] == ""
        w.call("text_scenes.close")


def test_rules_score_a_box_by_the_lines_words():
    from pinball_decryptor.webui import text_rules as R
    assert R.box_score("KAIJU AWARD", "GODZILLA VS GIGAN", "Title_Instance",
                       "Award_Textbox2") == 1
    assert R.box_score("KAIJU AWARD", "LINE 1 INSTRUCTIONS", "Line1_Instance",
                       "Lines_Textbox") == 0
    assert R.box_score("MEGALON JACKPOT!", "GIGAN JACKPOT", "Title_Instance") == 1
    assert R.box_score("GODZILLA VS GIGAN", "GODZILLA VS MEGALON") == 1   # "VS" is no word
    idx = R.scene_dir_index(["/g/a/b", "/h/c"])
    assert idx["a/b"] == idx["b"] == "/g/a/b" and idx["c"] == "/h/c"


def test_a_mode_line_without_its_cards_screens_says_why(tmp_path):
    """The screens each mode names are read from the project's card; with no card to read
    them from, the dialog says so instead of that no screen holds the line."""
    folder = _project(tmp_path, {"original": "KAIJU AWARD",
                                 "modes": ["cmode_battle_vs_gigan"]})
    with web_app(tmp_path, mfr="stern") as w:
        w.run(lambda: w.window.write_assets_var.set(str(folder)))
        w.call("ui.select_tab", "text")
        _wait(w, lambda: not w.state("text")["scanning"]
              and w.state("text").get("total", 0) > 0)
        w.call("text.select", _row(w, "KAIJU AWARD", "/game"))
        n = len(w.asked)
        assert w.call("text.show_in_scene") is False
        assert len(w.asked) == n + 1
        said = str(w.asked[-1])
        assert "Battle vs Gigan" in said and "isn't where it was" in said


def test_a_box_the_game_fills_is_marked_and_its_t_goes_to_the_line(tmp_path):
    """Round 4 (DragonRR): "some kind of alert that this item in scenes is subject to being
    replaced by text".  A box whose words are a stand-in for a game-program line (KAIJU for the
    game's KAIJU!) is marked in Layers, in the outlines and in the Selected panel, naming the
    line and its modes; its T lands on that line's game-program row on the Text tab.  A box a
    mode's code names with the screen is marked with the mode, and its T lists that mode's
    lines (the search in:<mode>)."""
    gigan = "cmode_battle_vs_gigan"
    folder = _project(tmp_path, {"original": "KAIJU!", "modes": [gigan]}, two=True)
    from pinball_decryptor.plugins.stern import engine
    engine._program_modes_read(str(folder), {gigan: ["g/scene1"]},
                               {gigan: {"g/scene1": ["Award_Textbox.Title"]}})
    with web_app(tmp_path, mfr="stern") as w:
        _show(w, folder, "KAIJU!")
        tv = _tv(w)
        by_path = {h["path"]: h for h in tv["hits"]}
        assert by_path["Title"]["filled"] and by_path["Award_Textbox › Title"]["filled"]
        assert not by_path["Art"]["filled"]
        layers = {l["name"] + str(l["depth"]): l for l in tv["layers"]}
        # the root's KAIJU: a stand-in for the game's KAIJU! (both titles read the same, so
        # the words win for both; the line names its mode)
        assert layers["Title0"]["filled"] == {"line": "KAIJU!", "modes": ["Battle vs Gigan"]}
        assert layers["Title1"]["filled"] == {"line": "KAIJU!", "modes": ["Battle vs Gigan"]}
        assert layers["Art0"]["filled"] is None
        assert tv["props"]["filled"] == {"line": "KAIJU!", "modes": ["Battle vs Gigan"]}
        # the T: the game-program row, not the scene's own KAIJU row
        assert w.call("text_scenes.activate", "prog::KAIJU!") is True
        st = w.state("text")
        assert w.state("shell")["tab"] == "text"
        assert st["rows"][st["sel"]]["o"] == "KAIJU!" and st["rows"][st["sel"]]["sc"] == "game program"
        # a box only a mode names: marked with the mode, its T lists the mode's lines
        from pinball_decryptor.core import text_manifest
        rows = [r for r in text_manifest.load(str(folder)) if r["original"] != "KAIJU!"]
        rows.append({"path": "/g/game", "original": "GIGAN AWARD", "replacement": "",
                     "budget": 96, "grow": True, "modes": [gigan]})
        rows.append({"path": "/g/game", "original": "TILT", "replacement": "", "budget": 4,
                     "fixed": True})
        text_manifest.save(str(folder), rows)
        w.call("text.scan")
        _wait(w, lambda: not w.state("text")["scanning"] and w.state("text").get("total", 0) > 0)
        svc = w.window.service("text").scenes
        w.run(svc.text_edits_changed)
        w.call("ui.select_tab", "scenes")
        w.call("text_scenes.select", "/g/scene1")
        _wait(w, lambda: (w.state("text_scenes").get("frames") or []) != [])
        layers = {l["name"] + str(l["depth"]): l for l in _tv(w)["layers"]}
        assert layers["Title0"]["filled"] is None
        assert layers["Title1"]["filled"] == {"line": None, "modes": ["Battle vs Gigan"]}
        assert w.call("text_scenes.activate", "mode::Battle vs Gigan") is True
        st = w.state("text")
        assert w.window.text_search_var.get() == "in:Battle vs Gigan"
        assert [st["rows"][i]["o"] for i in st["view"]] == ["GIGAN AWARD"]
        w.call("text_scenes.close")


def test_rules_search_in_a_mode():
    from pinball_decryptor.webui import text_rules as R
    line = {"path": "/g/game", "original": "GIGAN AWARD", "replacement": "",
            "modes": ["cmode_battle_vs_gigan"]}
    other = {"path": "/g/game", "original": "TILT", "replacement": ""}
    assert R.row_matches(line, "in:gigan", None, None)
    assert R.row_matches(line, "in:battle vs gigan", None, None)
    assert not R.row_matches(other, "in:gigan", None, None)
    assert R.row_matches(other, "in:", None, None)            # nothing typed yet: everything
    assert not R.row_matches(line, "in:megalon", None, None)
    assert R.row_matches(line, "gigan", None, None) and not R.row_matches(other, "gigan", None, None)
