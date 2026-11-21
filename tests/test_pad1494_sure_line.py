"""PAD-1494: the Scenes preview draws a box the game fills with the first of its "Show it with"
lines only when that line reads as the box's own stand-in.  On Godzilla Pro 1.16 the old "always
the first" drew the Match screen's MATCH as the service menu's MATCH AWARD, every LINE n
stand-in as ``Line1`` and X,XXX,XXX as SPI-XXX-000000: lines that only share a word with it.
Those are still offered in the list; the box keeps its stand-in until one is picked."""

from pinball_decryptor.webui.game_filled import sure_line, try_lines

GAME = "/godzilla_pro/game"


def _rows(*lines):
    return [{"path": GAME, "original": s, "replacement": ""} for s in lines]


def test_a_line_only_sharing_a_word_is_offered_not_drawn():
    rows = _rows("MATCH AWARD", "ALLOW MATCH", "Line1", "SPI-XXX-000000", "MODE", "%d GAME%P1//S/%")
    for stand_in, offered in (("MATCH", "MATCH AWARD"), ("LINE 1", "Line1"), ("LINE 2 INSTRUCTIONS", "Line1"),
                              ("X,XXX,XXX", "SPI-XXX-000000"), ("MODE DESCRIPTION", "MODE"),
                              ("GAME NAME", "1 GAME")):
        assert try_lines(rows, stand_in)[0] == offered
        assert sure_line(rows, stand_in) is None, stand_in


def test_a_count_is_a_number_not_any_word():
    """%d TRAIN%P1//S/% does not read as ADVANCE TRAIN LIT, nor %d COMBO as CITY COMBO X/X."""
    rows = _rows("%d TRAIN%P1//S/%", "%d COMBO%P1//S/%", "%d SKILL SHOT%P1//S/%")
    for stand_in in ("ADVANCE TRAIN LIT", "CITY COMBO X/X", "UNIQUE SKILL SHOT +1X"):
        assert try_lines(rows, stand_in)
        assert sure_line(rows, stand_in) is None, stand_in


def test_the_line_reading_as_the_stand_in_is_drawn():
    rows = _rows("MATCH AWARD", "BALL %d", "CREDITS %d", "SECRET COMBO %d/%d", "INTEGRITY: %d%%",
                 "AWARDS +%d FLIP%P1//S/%", "SUPER JACKPOT MULTIPLIER %dX", "JACKPOT VALUE: %,llu",
                 "GIGAN JACKPOT!", "PLAYER %d - ENTER INITIALS", "GODZILLA\\nPOWERUP\\nLEVEL %d")
    for stand_in, drawn in (("BALL 0", "BALL 1"), ("CREDITS  0", "CREDITS 1"),
                            ("SECRET COMBO X/X", "SECRET COMBO 1/1"), ("INTEGRITY: 85%", "INTEGRITY: 1%"),
                            ("AWARDS +XX FLIPS", "AWARDS +1 FLIP"),
                            ("SUPER JACKPOT MULTIPLIER XX", "SUPER JACKPOT MULTIPLIER 1X"),
                            ("JACKPOT VALUE: 1,000,000", "JACKPOT VALUE: 1"), ("GIGAN JACKPOT", "GIGAN JACKPOT!"),
                            ("Player 1 - Enter Initials", "PLAYER 1 - ENTER INITIALS"),
                            ("GODZILLA POWERUP LEVEL 3", "GODZILLA\\nPOWERUP\\nLEVEL 1")):
        assert sure_line(rows, stand_in) == drawn, stand_in


def test_a_players_box_is_drawn_with_the_players_line():
    """Simon (2026-11-20): the score panel's "Inactive Player" stand-in "Simply replace this with the first option"."""
    rows = _rows("PLAYER %d - LOG IN", "PLAYER %d", "INACTIVE")
    path = "Player1_Instance.P2_InActiveScore_Instance.InActivePlayer_Username_Instance"
    assert sure_line(rows, "Inactive Player", path) == "PLAYER 2"
    # no player in the box's path: PLAYER %d only shares a word with it
    assert sure_line(rows, "Inactive Player") is None


def test_scenes_draws_the_sure_line_or_the_stand_in(tmp_path):
    """The Scenes preview through the app: the first of the lines when sure, else the stand-in."""
    from tests.test_gui_scene_editor import _tv
    from tests.test_pad485_game_line_in_scenes import _project, _wait
    from tests.test_pad513_filled_boxes import _open, _paths
    from tests.webui_harness import web_app
    import pytest
    pytest.importorskip("PIL")
    for program, words in (("KAIJU!", "KAIJU!"), ("KAIJU %d WINS!", "")):
        here = tmp_path / ("sure" if words else "guess")
        (here / "app").mkdir(parents=True)
        folder = _project(here, {"original": program}, two=True)
        _paths(folder, ["Award_Textbox.Title"])
        with web_app(here / "app", mfr="stern") as w:
            _open(w, folder)
            svc = w.window.service("text").scenes
            ids = {l["name"] + str(l["depth"]): l["id"] for l in _tv(w)["layers"]}
            box = ids["Title1"]
            w.call("text_scenes.tree_select", box)
            _wait(w, lambda: (_tv(w).get("props") or {}).get("id") == box)
            assert _tv(w)["props"]["try"]["words"] == words
            shown = {d["node"]: d.get("shown") for d in w.run(lambda: svc._tdraws) if d["kind"] == "text"}
            assert shown[box] == (words or None)
            w.call("text_scenes.close")
