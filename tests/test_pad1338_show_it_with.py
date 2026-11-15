"""PAD-1338 (DragonRR): "Is there a way to show what the machine might show in this location - it
just shows 'Inactive Player' but the machine CAN display PLAYER 2 - LOG IN".

Godzilla's score panel holds the stand-in "Inactive Player" in each InActivePlayer_Username box;
the game writes "PLAYER %d", "PLAYER %d - LOG IN" and the like there (the PAD-513 emulator probe
logged "PLAYER 2" in P2_InActiveScore_Instance.InActivePlayer_Username_Instance).  For a box the
game fills, the Scenes Selected panel offers those lines ("Show it with") and the preview draws
the one picked in that box only, laid out by the box's own settings; nothing is written."""

import pytest

from tests.test_gui_scene_editor import _tv
from tests.test_pad485_game_line_in_scenes import _project, _wait
from tests.test_pad513_filled_boxes import _open, _paths
from tests.webui_harness import web_app

pytest.importorskip("PIL")

GAME = "/godzilla_le/game"


def _rows(*lines, **extra):
    return [dict({"path": GAME, "original": s, "replacement": ""}, **extra) for s in lines]


def test_a_sample_fills_the_games_fill_ins():
    from pinball_decryptor.webui.game_filled import sample_line
    assert sample_line("PLAYER %d - LOG IN", "2") == "PLAYER 2 - LOG IN"
    assert sample_line("%,llu POINTS", "3") == "3 POINTS"
    assert sample_line("%d BALL%P1//S/% LEFT", "1") == "1 BALL LEFT"
    assert sample_line("%d BALL%P1//S/% LEFT", "3") == "3 BALLS LEFT"
    assert sample_line("HI %s", "1") == "HI NAME"
    assert sample_line("100%% DONE") == "100% DONE"


def test_the_inactive_player_box_is_offered_the_player_lines_first():
    from pinball_decryptor.webui.game_filled import try_lines
    rows = _rows("SPEECH: PLAYER 4 UP", "Player", "PLAYER %d - LOG IN", "PLAYER %d",
                 "LOG IN TO PLAY NETWORK GAME", "PLAYER %d - ENTER INITIALS",
                 "Scan QR to log in or hold left flipper to activate Home Team&trade;",
                 "Log in to Stern Insider\\ncomplete registration.", "INACTIVE")
    rows += _rows("PLAYER %d - LOADING", unused=True)                 # never read: not offered
    rows += [{"path": "/g/s/scene.radium", "original": "Inactive Player", "replacement": ""}]
    got = try_lines(rows, "Inactive Player",
                    "Player1_Instance.P2_InActiveScore_Instance.InActivePlayer_Username_Instance")
    # lines with the player's number (2, from P2_) ahead of plain ones; shorter first
    assert got[:3] == ["PLAYER 2", "PLAYER 2 - LOG IN", "PLAYER 2 - ENTER INITIALS"]
    assert set(got[3:]) == {"Player", "INACTIVE", "SPEECH: PLAYER 4 UP"}
    assert "LOG IN TO PLAY NETWORK GAME" not in got                   # shares no word
    # no player in the path: a sample number of 1
    assert try_lines(rows, "Inactive Player")[0] == "PLAYER 1"


def test_the_line_reading_like_the_stand_in_leads():
    from pinball_decryptor.webui.game_filled import try_lines
    rows = _rows("GIGAN RAMP COMBO!", "SHOOT %d RAMPS TO DEFEAT GIGAN", "GIGAN JACKPOT!")
    assert try_lines(rows, "GIGAN JACKPOT")[0] == "GIGAN JACKPOT!"
    assert try_lines(rows, "") == []


def test_scenes_shows_a_filled_box_with_a_line_of_the_games(tmp_path):
    folder = _project(tmp_path, {"original": "KAIJU %d WINS!"}, two=True)
    _paths(folder, ["Award_Textbox.Title"])
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        svc = w.window.service("text").scenes
        ids = {l["name"] + str(l["depth"]): l["id"] for l in _tv(w)["layers"]}
        box, own = ids["Title1"], ids["Title0"]
        w.call("text_scenes.tree_select", box)
        _wait(w, lambda: (_tv(w).get("props") or {}).get("id") == box)
        props = _tv(w)["props"]
        assert props["try"] == {"words": "", "options": ["KAIJU 1 WINS!"]}
        hist = lambda: w.run(lambda: repr(svc._thist.get((svc.assets_dir,  # noqa: E731
                                                          svc._tree_card()[0]))))
        before = hist()
        # the box the game fills is drawn with the words picked, the root's own KAIJU is not
        assert w.call("text_scenes.tree_try_words", box, "KAIJU 2 WINS!") is True
        _wait(w, lambda: _tv(w)["props"]["try"]["words"] == "KAIJU 2 WINS!")
        shown = {d["node"]: d.get("shown") for d in w.run(lambda: svc._tdraws)
                 if d["kind"] == "text"}
        assert shown[box] == "KAIJU 2 WINS!" and shown[own] is None
        assert w.call("text_scenes.tree_try_words", box, "KAIJU 2 WINS!") is False   # no change
        # the preview only: no edit made, no undo step
        assert w.run(lambda: svc._tree_ops(svc._tree_card()[0])) == []
        assert hist() == before
        # a box the game does not fill offers nothing
        w.call("text_scenes.tree_select", own)
        _wait(w, lambda: (_tv(w).get("props") or {}).get("id") == own)
        assert _tv(w)["props"]["try"] is None
        # Its own: the stand-in again
        assert w.call("text_scenes.tree_try_words", box, None) is True
        assert all(d.get("shown") is None for d in w.run(lambda: svc._tdraws))
        w.call("text_scenes.close")


def test_the_renderer_draws_the_words_asked_for():
    """The renderer takes a draw's ``shown`` over its card words and any pending edit."""
    from pinball_decryptor.webui.text_scenes_tree import _with_tries
    draws = [{"kind": "text", "node": 7, "text": "Inactive Player"},
             {"kind": "text", "node": 8, "text": "Inactive Player"},
             {"kind": "image", "node": 7}]
    got = _with_tries(draws, {7: "PLAYER 2 - LOG IN"})
    assert [d.get("shown") for d in got] == ["PLAYER 2 - LOG IN", None, None]
    assert _with_tries(draws, None) is draws and _with_tries(draws, {}) is draws
