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
