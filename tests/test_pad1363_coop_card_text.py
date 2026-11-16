"""PAD-1363 (DoomWalrus666): a co-op character's own card text, the words under its badge on its pick card, in place
of its powers' fixed lines (84GOJI's "Press Action twice to add a ball, once a ball, not in multiball.")."""
import numpy as np

from pinball_decryptor.plugins.stern import coop_play as CP

MINE = "Smash the Action button twice for one more ball, once a ball. Not during a multiball."


def _chars(text=""):
    return CP._characters({"pick": True, "list": [
        {"name": "SHODAIGOJI", "powers": ["ball_save_x2"]},
        {"name": "84GOJI", "sub": "Return of Godzilla (1984)", "powers": ["addball"], "text": text},
        {"name": "PLAIN"}]})


def test_a_saved_character_keeps_its_own_card_text(tmp_path):
    project = str(tmp_path)
    chars = CP.save_characters(project, {"pick": True, "list": [
        {"name": "84goji", "powers": ["addball"], "text": "  Smash   Action twice:\n one more ball.  "},
        {"name": "old", "powers": ["addball"]}]})
    a, b = chars["list"]
    assert a["text"] == "Smash Action twice: one more ball." and b["text"] == ""       # the case it was typed in
    assert CP.load_characters(project) == chars
    assert CP.clean_text("x" * 500) == "x" * CP.MAX_TEXT


def test_the_card_line_is_its_own_text_else_its_powers_lines():
    a = _chars(MINE)["list"][1]
    assert CP.character_line(a) == MINE
    assert CP.character_line(dict(a, text="")) == "Press Action twice to add a ball, once a ball, not in multiball."
    assert CP.character_words(a) == "ADD A BALL"                        # the badge stays its powers' words


def test_the_pick_card_draws_its_own_text_and_is_as_before_without_it():
    with_text = CP.pick_card(None, _chars(MINE), 1, scale=1)
    without = CP.pick_card(None, _chars(), 1, scale=1)
    assert not np.array_equal(with_text, without)
    ys, xs = np.nonzero(np.any(with_text != without, axis=2))
    assert xs.min() > 40 + 380                                         # only the words right of the portrait change
    assert np.array_equal(CP.pick_card(None, _chars(), 0, scale=1), CP.pick_card(None, _chars(MINE), 0, scale=1))
    # a character with no powers but words of its own shows them in place of "Plays as the game always does."
    plain = CP.pick_card(None, _chars(), 2, scale=1)
    own = CP.pick_card(None, dict(_chars(), list=_chars()["list"][:2] + [dict(_chars()["list"][2], text=MINE)]), 2,
                       scale=1)
    assert not np.array_equal(plain, own)


def test_the_classic_patch_still_lays_back_to_the_plain_card():
    chars = _chars(MINE)
    got = CP.classic_patch(None, chars, 1)
    assert got is not None
    (x, y), art = got
    h, w = art.shape[:2]
    laid = CP.pick_card(None, chars, 1).copy()
    laid[y:y + h, x:x + w] = art
    plain = dict(chars, list=[dict(c, powers=[], header="", text="") if k == 1 else c
                              for k, c in enumerate(chars["list"])])
    assert np.array_equal(laid, CP.pick_card(None, plain, 1))


def test_text_too_long_for_the_card_says_where_it_stops():
    assert CP.text_on_card(MINE) == (MINE, False)
    long = " ".join(["Smash the Action button twice for one more ball."] * 6)
    shown, cut = CP.text_on_card(long)
    assert cut and shown.endswith("...") and len(shown) < len(long)
