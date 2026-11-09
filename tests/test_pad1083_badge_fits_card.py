"""PAD-1083 (DoomWalrus666: "the summary of abilities is cutoff as it is too long. How can I shorten this to fit?"):
BIOGOJI's six powers listed one by one ran the pick card's blue badge off the card's edge. A badge too long for the
card now keeps the powers that fit and says how many more (or, in the owner's own words, stops at a whole word with
...), the Characters dialog says so and points at the box for the badge's own words, and Godzilla's set gives
BIOGOJI short words of its own."""
import os

import numpy as np

from pinball_decryptor.plugins.stern import coop_play as CP

SIX = ["maser_lit", "magna_grab", "powerlines_x2", "saucer_x2", "dj_lit", "perk_loop_2x"]
MAGENTA = (255, 0, 255)


def _fits(label):
    from PIL import Image, ImageDraw
    f = CP._face(CP._TEXT_FONTS, CP.BADGE_LEAST * 2)
    return ImageDraw.Draw(Image.new("L", (1, 1))).textlength(label, font=f) <= CP.BADGE_ROOM * 2


def test_six_powers_keep_the_ones_that_fit_and_count_the_rest():
    got, cut = CP.badge_on_card({"name": "BIOGOJI", "powers": SIX, "header": ""})
    assert cut and got == "MASER LIT, MAGNA GRAB LIT, DOUBLE POWERLINES, SAUCER MULTIBALL +2 MORE"
    assert _fits(got)


def test_own_words_too_long_stop_at_a_whole_word():
    long = "MASER LIT, MAGNA GRAB LIT, DOUBLE POWERLINES, SAUCER MULTIBALL, DESTRUCTION JACKPOT LIT, LOOP VALUE 2X"
    got, cut = CP.badge_on_card({"name": "X", "powers": SIX, "header": CP.clean_header(long)})
    assert cut and got.endswith("...") and _fits(got)
    assert long.startswith(got[:-3]) and long[len(got) - 3] in " ,"        # whole words, no dangling comma
    one = CP.badge_on_card({"name": "X", "powers": [], "header": "A" * CP.MAX_HEADER})[0]
    assert one.endswith("...") and _fits(one)                              # one word too long alone: cut inside it


def test_a_badge_that_fits_is_left_alone():
    for c in ({"name": "X", "powers": ["addball"], "header": ""}, {"name": "X", "powers": SIX, "header": "MY WORDS"},
              {"name": "X", "powers": [], "header": ""}):
        got, cut = CP.badge_on_card(c)
        assert not cut and got == (CP.character_words(c) or "NO SPECIAL ABILITY")


def test_every_shipped_set_fits_its_cards():
    for stem, path in CP.presets().items():
        for c in CP.read_preset(path)["characters"]["list"]:
            assert not CP.badge_on_card(c)[1], (stem, c["name"], CP.character_words(c))
    bio = next(c for c in CP.read_preset(CP.presets()["godzilla"])["characters"]["list"] if c["name"] == "BIOGOJI")
    assert bio["powers"] == SIX
    assert bio["header"] == "MASER, MAGNA GRAB, DESTRUCTION JACKPOT LIT, DOUBLE POWERLINES, POPS AND LOOPS"


def test_the_badge_stays_inside_the_card(tmp_path):
    project = str(tmp_path / "p")
    os.makedirs(project)
    for header in ("", "W" * CP.MAX_HEADER):
        chars = {"pick": True, "list": [{"name": "BIOGOJI", "sub": "Godzilla vs Biollante (1989)", "powers": SIX,
                                         "header": header}], "theme": {"badge": "#ff00ff"}}
        CP.save_characters(project, chars)
        chars = CP.load_characters(project)
        art = CP.pick_card(project, chars, 0, CP.words_for(), chars.get("theme"))
        assert art.shape[1] == CP.CARD_SIZE[0]
        band = art[200:290, :, :3].astype(int)
        pink = (np.abs(band - np.array(MAGENTA)).max(axis=2) < 40).any(axis=0)
        cols = np.nonzero(pink)[0]
        assert cols.size and cols.max() <= CP.CARD_SIZE[0] - 44, (header[:4], cols.max())   # its right margin


def test_the_dialog_says_a_badge_is_cut_and_what_shows(tmp_path, monkeypatch):
    from pinball_decryptor.webui.tabs import modes as M
    project = str(tmp_path / "p")
    os.makedirs(project)
    CP.save_characters(project, {"pick": True, "list": [{"name": "BIOGOJI", "powers": SIX},
                                                        {"name": "84GOJI", "powers": ["addball"]}]})
    svc = M.ModesTab.__new__(M.ModesTab)
    state = {}
    monkeypatch.setattr(svc, "set", lambda **kw: state.update(kw), raising=False)
    monkeypatch.setattr(svc, "get", lambda k, d=None: state.get(k, d), raising=False)
    monkeypatch.setattr(CP, "project_powers", lambda project: ("", []))
    monkeypatch.setattr(CP, "project_abilities", lambda project: ("", []))
    monkeypatch.setattr(CP, "project_title", lambda project, probe=False: None)
    monkeypatch.setattr(svc, "_coop_preview", lambda project, chars: None, raising=False)
    monkeypatch.setattr(svc, "_coop_look", lambda project, chars: None, raising=False)
    svc._publish_coop_chars(project)
    rows = state["coop_ch"]["rows"]
    assert rows[0]["badge_cut"] == "MASER LIT, MAGNA GRAB LIT, DOUBLE POWERLINES, SAUCER MULTIBALL +2 MORE"
    assert rows[1]["badge_cut"] == ""
