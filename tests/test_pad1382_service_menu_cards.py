"""PAD-1382 round 4 (David: "This game's service menu could not be read (The card image could not be opened: ... No
such file or directory ...). we need to make this work for all game images"): the Service menu tab finds a game
program for any project, and reads every menu shape - the category pages (Godzilla), the older dot-matrix Standard /
Feature Adjustments (Aerosmith, Venom, TMNT... 22 of the 53 newest builds) and Spike 3's 64-bit programs."""
import json
import os

import pytest

from pinball_decryptor.plugins.stern import menu_settings as MS
from pinball_decryptor.plugins.stern import service_menu as SM
from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable

from tests.test_pad1382_more_settings import LE116, _program

LIB = os.path.dirname(LE116)
AERO = os.path.join(LIB, "aerosmith_le-1_16_0.Release.8G.sdcard.raw")
SWELG = os.path.join(os.path.dirname(LIB), "spike3", "star_wars_elg-1_10_0_spike3.Release.64G.sdcard-secure.raw")
FIT = [("coop_play", 3, (), {"default": 1, "help_text": "0 Off. 1 Classic. 2 Enhanced.", "from_zero": True}),
       ("handicap", 2, (), {"default": 1, "help_text": "On: each player picks", "onoff": True})]
MACHINE = ["Machine Operation", "Device Enables", "Coil Settings", "LCD/Lamp", "Audio Settings", "Audio Content",
           "Audio Configuration", "Attract Mode", "Test Menu Settings"]


def _elf(card):
    if not os.path.isfile(card):
        pytest.skip("no %s on this machine" % os.path.basename(card))
    from pinball_decryptor.plugins.stern import title_reader as TR
    return TR.game_program(card)[2]


# ---- every Machine Settings page, by the game's own names -----------------------------------------------------------
def test_the_page_names_are_the_games_own():
    names = SM.category_names(AdjustmentTable(_program(LE116)))
    assert [names[c] for c in (3, 9, 11, 13, 16, 17)] == ["Machine Settings", "Device Enables", "LCD/Lamp",
                                                          "Audio Content", "Attract Mode", "Test Menu Settings"]


def test_every_machine_settings_page_shows_with_or_without_rows_of_ours():
    menu = SM.pages(_program(LE116), [])
    assert [(p["name"], p["rank"]) for p in menu["pages"]] == [(n, k) for k, n in enumerate(MACHINE)]
    assert not any(p["ours"] for p in menu["pages"])           # no row of ours: no page of our own either
    menu = SM.pages(_program(LE116), FIT)
    assert [p["name"] for p in menu["pages"] if p["ours"]] == ["Custom Code"]
    assert menu["pages"][7]["path"] == "Adjustments > Machine Settings > Custom Code"


# ---- the older dot-matrix menu --------------------------------------------------------------------------------------
def test_a_standard_adjustments_game_shows_its_two_pages_ours_at_the_end():
    elf = _elf(AERO)
    menu = SM.pages(elf, FIT)
    std, feat = menu["pages"]
    assert (std["name"], std["style"], std["rank"], feat["name"], feat["rank"]) == (
        "Standard Adjustments", "dmd", 0, "Feature Adjustments", 1)
    assert [r["caption"] for r in std["rows"][:2]] == ["Free Play", "Game Pricing"]
    assert [r["caption"] for r in std["rows"][-3:]] == ["Service Menu Backbox Brightness", "Co-op Play", "Handicap"]
    assert len(feat["rows"]) == 69 and not any(r["ours"] for r in feat["rows"])


def test_the_shared_row_is_listed_once():
    """The settings sharing MORE SETTINGS all name the row under it: a Standard Adjustments list once listed it five
    times (Aerosmith LE 1.16 in the emulator: #97-#101 all the value row)."""
    t = AdjustmentTable(_elf(AERO))
    rows = [("custom_%d" % k, 2, ["a", "b"], {}) for k in range(4)]
    for k, *_r in rows:
        MS.SETTINGS[k] = (None, k.upper(), k.title(), 16)
    settings, _w, cat, _r = MS.plan_many(t, rows)
    assert isinstance(cat, MS.StandardList)
    blob = cat.blob(*settings)
    ids = [int.from_bytes(blob[i:i + 2], "little") for i in range(0, len(blob), 2)]
    ids = ids[:ids.index(0)]
    assert len(ids) == len(cat.ids) + 2 and ids[-2:] == [s.id for s in settings
                                                         if s.key in (MS.MORE_SELECT, MS.MORE_VALUE)]
    gz = AdjustmentTable(_program(LE116))
    settings, _w, cat, _r = MS.plan_many(gz, rows)
    assert cat.records_with(*settings) == len(cat.records) + 2


def test_the_dot_matrix_walk_goes_round_from_the_first_row():
    w = SM.walk(0, 96, "dmd", 97)
    assert w[:10] == ["25", "w2", "25", "w2", "26", "26", "25", "w2", "25", "w2"] and w[10:] == ["27", "w1"]
    assert SM.walk(1, 2, "dmd", 69)[8:] == ["26", "25", "w2", "26", "26", "w1"]


# ---- Spike 3 --------------------------------------------------------------------------------------------------------
def test_a_spike3_program_shows_its_pages_and_our_rows():
    elf = _elf(SWELG)
    from pinball_decryptor.plugins.stern import spike3_menu as S3
    menu = SM.pages(elf, [S3._coop_row(), S3._hand_row()])
    assert menu["wide"] and menu["refused"] == {}
    attract = next(p for p in menu["pages"] if p["name"] == "Attract Mode")
    assert attract["rank"] is None                       # the real menu is read on Spike 2 only
    assert [r["caption"] for r in attract["rows"] if r["ours"]] == ["Co-op Play", "Handicap"]
    assert "Enable Spike 3 Boot Sound" in [r["caption"] for r in attract["rows"]]


# ---- which game program, for any project ----------------------------------------------------------------------------
def _project(tmp_path, card):
    p = str(tmp_path / "project")
    os.makedirs(p, exist_ok=True)
    with open(os.path.join(p, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": card, "input_name": os.path.basename(card), "card_version": "1.16.0"}, f)
    return p


def test_a_project_whose_card_is_gone_reads_another_card_of_its_game(tmp_path, monkeypatch):
    if not os.path.isfile(LE116):
        pytest.skip("no Godzilla LE 1.16 card on this machine")
    gone = os.path.join(str(tmp_path), "gone", "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
    p = _project(tmp_path, gone)
    monkeypatch.setenv("PAD_TITLE_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(SM, "_settings_cards", lambda: [os.path.join(LIB, "no such card.raw"), LE116])
    elf, source = SM.find_program(p)
    assert elf[:4] == b"\x7fELF" and os.path.normcase(source) == os.path.normcase(LE116)
    # and with no card anywhere, the copy kept from that read
    monkeypatch.setattr(SM, "_settings_cards", lambda: [])
    elf2, source2 = SM.find_program(p)
    assert elf2 == elf and "kept from an earlier read" in source2


def test_a_project_with_no_card_anywhere_says_so(tmp_path, monkeypatch):
    p = _project(tmp_path, os.path.join(str(tmp_path), "gone", "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"))
    monkeypatch.setenv("PAD_TITLE_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(SM, "_settings_cards", lambda: [])
    with pytest.raises(ValueError) as e:
        SM.find_program(p)
    assert "No card of godzilla_le 1.16" in str(e.value) and "Extract tab" in str(e.value)


def test_the_projects_own_build_output_is_a_candidate(tmp_path, monkeypatch):
    p = _project(tmp_path, os.path.join(str(tmp_path), "gone.raw"))
    os.makedirs(os.path.join(p, "build"))
    open(os.path.join(p, "build", "v38.raw"), "wb").close()
    monkeypatch.setattr(SM, "_settings_cards", lambda: [])
    assert [os.path.basename(c) for c in SM.card_candidates(p)] == ["gone.raw", "v38.raw"]


def test_the_older_menu_and_spike3_keep_the_pages_they_had():
    """No page can be added to the dot-matrix Standard Adjustments, nor (yet) to a 64-bit program."""
    t = AdjustmentTable(_elf(AERO))
    with pytest.raises(MS.MenuSettingError):
        MS.own_page(t)
    settings, _w, _c, refused = MS.plan_many(t, FIT)
    assert refused == {} and all(s.category != MS.OWN_CATEGORY for s in settings)
