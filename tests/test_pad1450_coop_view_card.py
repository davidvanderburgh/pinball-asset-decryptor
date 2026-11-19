"""PAD-1450 (DoomWalrus666: "hold left flipper to see character card" at the start of each later ball): each
character gets a view card beside its pick card - the pick card's look with only that character on it (no roster
strip, no count, no how to choose, the title without its CHOOSE, a box for the runtime's PLAYER n) - and the HUD gets
the hint pill. The runtime half (when they show) is emulator-proven on Godzilla LE 1.16."""
import os
import pathlib

import numpy as np

from pinball_decryptor.plugins.stern import coop_play as CP

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c"
CHARS = [{"name": "SHODAIGOJI", "sub": "Godzilla (1954)", "ability": "longer_save"},
         {"name": "BIOGOJI", "ability": ""}, {"name": "KINGOJI", "ability": ""}]


def _project(tmp_path, theme=None):
    project = str(tmp_path / "p")
    os.makedirs(project)
    CP.save_characters(project, dict({"pick": True, "list": CHARS}, **({"theme": theme} if theme else {})))
    return project


def test_view_title_drops_choose():
    assert CP.view_title("CHOOSE YOUR GODZILLA") == "YOUR GODZILLA"
    assert CP.view_title("  choose   your kaiju ") == "your kaiju"
    assert CP.view_title("PICK A FIGHTER") == "YOUR CHARACTER"
    assert CP.view_title("CHOOSE") == "YOUR CHARACTER"
    assert CP.view_title("") == "YOUR CHARACTER"


def test_view_card_is_the_pick_card_without_the_roster(tmp_path):
    project = _project(tmp_path)
    chars = CP.load_characters(project)
    pick = CP.pick_card(project, chars, 0, CP.words_for(), chars.get("theme"))
    view = CP.pick_card(project, chars, 0, CP.words_for(), chars.get("theme"), view=True)
    assert pick.shape == (CP.CARD_SIZE[1], CP.CARD_SIZE[0], 4)
    assert view.shape == (CP.VIEW_SIZE[1], CP.VIEW_SIZE[0], 4)
    # the portrait and the words are where the pick card has them (the top of both cards matches but for the header's
    # right end: the count and the clock are gone, the box is wider)
    top = slice(84, 390)
    diff = np.abs(view[top, 40:420].astype(int) - pick[top, 40:420].astype(int))
    assert diff.mean() < 3                                       # (the panel's wash follows the card's height)
    # no "FLIPPERS TO CHOOSE" line: the pick card's help row has bright words the view card does not
    help_row = (slice(360, 384), slice(470, 1000))
    assert pick[help_row][..., :3].max() > 200
    assert view[help_row][..., :3].max() < 200
    # the count's place in the header is plain panel on the view card
    assert view[30:60, 1180:1230, :3].max() < pick[30:60, 1180:1230, :3].max()
    # the card's bottom edge is its frame, opaque inside
    assert view[CP.VIEW_SIZE[1] // 2, 2:CP.VIEW_SIZE[0] - 2, 3].min() == 255


def test_pick_screens_carry_a_view_card_each_and_the_hint(tmp_path):
    project = _project(tmp_path, theme={"title": "CHOOSE YOUR GODZILLA"})
    got = {s["name"]: s for s in CP.pick_screens(project, words_for=CP.words_for(project), classic=False,
                                                    videos=False)}
    n = len(CHARS)
    for i in range(n):
        s = got[CP.VIEW_NODE % (i + 1)]
        assert s["words_name"] == CP.VIEW_NODE % (i + 1) + "_Words" and s["words"] == " "
        assert (s["x"], s["y"]) == (float(CP.VIEW_AT[0]), float(CP.VIEW_AT[1]))
        assert s["art_rgba"].shape[:2] == (CP.VIEW_SIZE[1], CP.VIEW_SIZE[0])
        assert s["words_scale"] == CP.VIEW_WORDS_SCALE
    assert CP.VIEW_NODE % (n + 1) not in got                     # RANDOM has none: nobody is RANDOM after the pick
    hint = got[CP.PEEK_NODE]
    assert hint["art_rgba"].shape[:2] == (CP.PEEK_SIZE[1], CP.PEEK_SIZE[0])
    assert "words_name" not in hint                              # the hint's words are drawn, not the runtime's
    x, y = hint["x"], hint["y"]
    assert x + CP.PEEK_SIZE[0] <= 1360 and y + CP.PEEK_SIZE[1] <= CP.CARD_AT[1] + CP.CARD_SIZE[1] + 6
    # the view card sits inside the pick card's place, and its words box centre is the header box's centre
    assert CP.VIEW_AT[1] + CP.VIEW_SIZE[1] <= CP.CARD_AT[1] + CP.CARD_SIZE[1]
    wx = CP.VIEW_WORDS_AT[0] + CP.VIEW_SIZE[0] / 2 * CP.VIEW_WORDS_SCALE
    assert abs(wx - (CP.VIEW_BOX[0] + CP.VIEW_BOX[2]) / 2) < 1


def test_no_pick_no_view_cards(tmp_path):
    project = str(tmp_path / "p")
    os.makedirs(project)
    CP.save_characters(project, {"pick": False, "list": CHARS})
    assert CP.pick_screens(project) == []


def test_hint_pill_is_premultiplied_with_words():
    art = CP.peek_hint()
    assert art.shape == (CP.PEEK_SIZE[1], CP.PEEK_SIZE[0], 4)
    assert (art[..., :3] <= art[..., 3:4]).all()                 # premultiplied
    assert art[..., 3].min() == 0 and art[CP.PEEK_SIZE[1] // 2, CP.PEEK_SIZE[0] // 2, 3] > 150
    assert (art[..., :3].min(axis=2) > 200).sum() > 200          # white words


def test_runtime_names_match_the_builder():
    src = RUNTIME.read_text(encoding="utf-8")
    assert '"PadCoopView_%d"' in src and CP.VIEW_NODE == "PadCoopView_%d"
    assert '"PadCoopPeek"' in src and CP.PEEK_NODE == "PadCoopPeek"
    # the window opens only at a turn whose teammate already has a character (never the ball they pick on)
    turn = src[src.index("static void coop_view_turn(void)"):]
    turn = turn[:turn.index("\n}\n")]
    assert "coop_pick_of[coop.turn]" in turn and "c >= 0" in turn
    chars_turn = src[src.index("static void coop_chars_turn(void)"):]
    assert chars_turn.index("coop_view_turn();") < chars_turn.index("coop_pick_open(coop.turn);")
