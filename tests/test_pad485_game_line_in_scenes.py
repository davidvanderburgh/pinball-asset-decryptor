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


def _project(tmp_path, program):
    from pinball_decryptor.core import text_manifest
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
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
    folder = _project(tmp_path, {"original": "KAIJU AWARD", "modes": [gigan, megalon]})
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
        assert _tv(w)["sel"] == _title(w)
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
