"""PAD-1056 (DoomWalrus666): a co-op character's sub header - a smaller line under its name on its pick and award
cards ("BIOGOJI" over "Godzilla vs Biollante (1989)"), kept with the characters, in the settings file, and never on
the game's top line."""
import numpy as np

from pinball_decryptor.plugins.stern import coop_play as CP

SUB = "Godzilla vs Biollante (1989)"
CHARS = [{"name": "BIOGOJI", "sub": SUB, "ability": ""}, {"name": "GODZILLA 1954", "ability": ""}]


def test_the_sub_header_is_kept_as_typed_with_the_characters(tmp_path):
    project = str(tmp_path)
    got = CP.save_characters(project, {"pick": True, "list": [
        {"name": "biogoji", "sub": "  Godzilla   vs Biollante (1989) "}, {"name": "x", "sub": "y" * 80},
        {"name": "z"}]})
    assert [c["sub"] for c in got["list"]] == [SUB, "y" * CP.MAX_SUB, ""]
    assert got["list"][0]["name"] == "BIOGOJI"                          # the name is still the top line's capitals
    assert CP.load_characters(project) == got


def test_the_sub_header_never_reaches_the_games_top_line(monkeypatch):
    monkeypatch.setattr(CP, "abilities", lambda *a, **k: [])          # no program here: only the character lines
    monkeypatch.setattr(CP._SMo, "flipper_buttons", lambda elf: [])
    monkeypatch.setattr(CP, "action_button", lambda elf: None)
    lines = CP.character_lines(b"", {"pick": True, "list": CHARS})
    assert any(ln.startswith("character - BIOGOJI|") for ln in lines)
    assert not any(SUB in ln for ln in lines)


def test_the_settings_file_carries_the_sub_header(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    CP.save(str(a), True)
    CP.save_characters(str(a), {"pick": True, "list": CHARS})
    path = str(tmp_path / "coop.json")
    CP.export_settings(str(a), path)
    CP.import_settings(str(b), path)
    assert [c["sub"] for c in CP.load_characters(str(b))["list"]] == [SUB, ""]


def _band(art, y0, y1, x0):
    return art[y0:y1, x0:].astype(int)


def test_the_pick_card_draws_the_sub_header_under_the_name(tmp_path):
    project = str(tmp_path)
    plain = CP.pick_card(project, {"pick": True, "list": [dict(CHARS[0], sub="")]}, 0, CP.words_for())
    with_sub = CP.pick_card(project, {"pick": True, "list": CHARS[:1]}, 0, CP.words_for())
    ix = 40 + 380 + 44                                                   # the words column (card pixels)
    # the sub header's line (baseline 204, clear of the rule): lit only with one; how to choose stays put
    assert np.abs(_band(with_sub, 190, 206, ix) - _band(plain, 190, 206, ix)).sum() > 0
    assert np.array_equal(_band(with_sub, 360, 384, ix), _band(plain, 360, 384, ix))
    rnd = CP.pick_card(project, {"pick": True, "list": CHARS[:1]}, 1, CP.words_for())
    rnd_plain = CP.pick_card(project, {"pick": True, "list": [dict(CHARS[0], sub="")]}, 1, CP.words_for())
    assert np.array_equal(rnd[100:300, ix:], rnd_plain[100:300, ix:])   # RANDOM has none


def test_the_award_card_draws_the_sub_header_under_the_name(tmp_path):
    project = str(tmp_path)
    plain = CP.award_card(project, {"pick": True, "list": [dict(CHARS[0], sub="")]}, 0)
    with_sub = CP.award_card(project, {"pick": True, "list": CHARS[:1]}, 0)
    ix = 40 + 340 + 40
    assert np.abs(_band(with_sub, 236, 266, ix) - _band(plain, 236, 266, ix)).sum() > 0
    assert np.array_equal(with_sub[CP.AWARD_WORDS_Y - 10:, :], plain[CP.AWARD_WORDS_Y - 10:, :])   # the words band
