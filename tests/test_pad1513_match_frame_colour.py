"""PAD-1513 (DoomWalrus666: "the option for each character's name text and corners to match the Character frame
color"): a tick in the co-op pick's Look draws each character's name, corners and arrows in its frame colour (its own,
or the look's Frame and lights) on its pick, award and bonus cards. Off (the default) the cards draw as before; the
RANDOM card keeps the look's own colours either way."""
import os
import pathlib
import types

import numpy as np

from pinball_decryptor.plugins.stern import coop_play as CP

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHARS = [{"name": "SHODAIGOJI", "sub": "Godzilla (1954)", "ability": "longer_save", "colour": "#00ff00"},
         {"name": "BIOGOJI", "ability": ""}]
IX = 40 + 380 + 44                                                       # the words column (card pixels)
NAME = (IX, 90, 1240, 150)                                               # the pick card's name line
CORNER = (24, 14, 58, 19)                                                # the top-left corner bracket's arm
GREEN = (0, 255, 0)


def _project(tmp_path):
    project = str(tmp_path / "p")
    os.makedirs(project)
    CP.save_characters(project, {"pick": True, "list": CHARS})
    return project


def _card(project, index=0, award=False):
    chars = CP.load_characters(project)
    if award:
        return CP.award_card(project, chars, index, chars.get("theme"))
    return CP.pick_card(project, chars, index, CP.words_for(), chars.get("theme"))


def _has(art, box, rgb, tol=40):
    x0, y0, x1, y1 = box
    px = np.asarray(art)[y0:y1, x0:x1, :3].astype(int)
    return bool((np.abs(px - np.array(rgb)).max(axis=2) < tol).any())


def _greens(art, box, tol=40):
    x0, y0, x1, y1 = box
    px = np.asarray(art)[y0:y1, x0:x1, :3].astype(int)
    return int((np.abs(px - np.array(GREEN)).max(axis=2) < tol).sum())


def test_off_by_default_and_the_cards_draw_as_before(tmp_path):
    project = _project(tmp_path)
    assert CP.THEME["match"] is False and CP.theme_of()["match"] is False
    th = CP.theme_of()
    assert CP.character_colours(th, CHARS[0]) == ("#00ff00", th["accent2"], th["name"])
    art = _card(project)
    assert not _has(art, NAME, GREEN) and not _has(art, CORNER, GREEN)
    assert _has(art, CORNER, CP._hex(th["accent2"])[:3])
    assert _has(art, NAME, (255, 255, 255), tol=10)


def test_match_draws_the_name_and_corners_in_the_frame_colour(tmp_path):
    project = _project(tmp_path)
    plain = _card(project, 1)
    CP.save_look(project, "match", True)
    assert CP.load_characters(project)["theme"] == {"match": True}
    art = _card(project)
    assert _has(art, NAME, GREEN) and _has(art, CORNER, GREEN)
    assert not _has(art, NAME, (255, 255, 255), tol=10)
    accent = CP._hex(CP.THEME["accent"])[:3]                     # no colour of its own: the look's frame colour
    art = _card(project, 1)
    assert _has(art, CORNER, accent) and not _has(art, CORNER, CP._hex(CP.THEME["accent2"])[:3])
    assert not np.array_equal(art, plain)
    rnd = _card(project, 2)                                      # RANDOM: the look's own colours
    assert _has(rnd, CORNER, CP._hex(CP.THEME["accent2"])[:3])
    view = CP.pick_card(project, CP.load_characters(project), 0, CP.words_for(), {"match": True}, view=True)
    assert _has(view, CORNER, GREEN)                             # a teammate's later-ball card too


def test_match_reaches_the_award_and_bonus_cards(tmp_path):
    project = _project(tmp_path)
    name = (IX - 64, 120, 860, 196)                              # the name, big (its sub header is green already)
    before = _greens(_card(project, award=True), name)
    CP.save_look(project, "match", "1")
    assert _greens(_card(project, award=True), name) > 4 * before + 500
    plain = np.asarray(CP.bonus_card("SHODAIGOJI", "#00ff00"))
    tinted = np.asarray(CP.bonus_card("SHODAIGOJI", "#00ff00", {"match": True}))
    px, py, pw, ph = CP.BONUS_PHOTO
    foot = (px, py + ph // 2, px + pw, py + ph)
    assert _greens(tinted, foot) > 4 * _greens(plain, foot) + 200      # the frame line is green in both


def test_the_tick_is_kept_dropped_and_carried(tmp_path, monkeypatch):
    project = _project(tmp_path)
    CP.save_look(project, "match", True)
    CP.save_look(project, "name", "#ffd400")
    assert CP.load_characters(project)["theme"] == {"match": True, "name": "#ffd400"}
    assert CP.theme_of({"match": "True"})["match"] and not CP.theme_of({"match": "False"})["match"]
    monkeypatch.setattr(CP, "project_title", lambda project, probe=False: types.SimpleNamespace(label="Godzilla"))
    out = str(tmp_path / "coop.json")
    CP.export_settings(project, out)
    dest = str(tmp_path / "d")
    os.makedirs(dest)
    CP.import_settings(dest, out)
    assert CP.load_characters(dest)["theme"] == {"match": True, "name": "#ffd400"}
    CP.save_look(project, "match", False)
    assert CP.load_characters(project)["theme"] == {"name": "#ffd400"}
    CP.save_characters(project, dict(CP.load_characters(project), theme={"match": "no"}))
    assert CP.load_characters(project).get("theme", {}) == {}


def test_the_dialog_ticks_it(tmp_path, monkeypatch):
    from pinball_decryptor.webui.tabs import modes as M
    project = _project(tmp_path)
    svc = M.ModesTab.__new__(M.ModesTab)
    state, said = {}, []
    monkeypatch.setattr(svc, "set", lambda **kw: state.update(kw), raising=False)
    monkeypatch.setattr(svc, "get", lambda k, d=None: state.get(k, d), raising=False)
    monkeypatch.setattr(svc, "project", lambda: project, raising=False)
    monkeypatch.setattr(svc, "_say", lambda w, *a, **k: said.append(w), raising=False)
    monkeypatch.setattr(CP, "project_powers", lambda project: ("", []))
    monkeypatch.setattr(CP, "project_abilities", lambda project: ("", []))
    monkeypatch.setattr(CP, "project_title", lambda project, probe=False: None)
    monkeypatch.setattr(svc, "_coop_preview", lambda project, chars: None, raising=False)
    assert svc.coop_chars_look("name", "#ffd400")
    look = state["coop_ch"]["look"]
    assert look["match"] is False and next(c for c in look["colours"] if c["key"] == "name")["hint"] == ""
    assert svc.coop_chars_look("match", True)
    look = state["coop_ch"]["look"]
    assert look["match"] is True
    for c in look["colours"]:
        assert ("RANDOM" in c["hint"]) == (c["key"] in CP.MATCH_ROLES), c
    assert svc.coop_chars_look("match", False) and state["coop_ch"]["look"]["match"] is False
    js = (ROOT / "pinball_decryptor" / "webui" / "static" / "js" / "tabs" / "modes_dialogs.js").read_text("utf-8")
    assert 'call("modes.coop_chars_look", "match"' in js and "look.match" in js
