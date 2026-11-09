"""PAD-1079 (DoomWalrus666: "change the colors of certain text ... other alterations and customizations of the
character selection screen"): the co-op pick screen's look is the owner's - its title, a colour for each of its
words, the frame and the panel, a background picture behind every card, and a frame colour of a character's own -
kept with the characters, drawn on the pick and award cards, and carried by the co-op settings file. Left alone, the
cards draw exactly as before."""
import os
import pathlib
import types

import numpy as np
import pytest

from pinball_decryptor.plugins.stern import coop_play as CP

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHARS = [{"name": "SHODAIGOJI", "sub": "Godzilla (1954)", "ability": "longer_save"},
         {"name": "BIOGOJI", "ability": ""}]
IX = 40 + 380 + 44                                                       # the words column (card pixels)


def _png(path, rgb, size=(64, 48)):
    from PIL import Image
    Image.new("RGB", size, rgb).save(path)


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
    """Whether *art* (premultiplied, opaque inside the card) has a pixel near *rgb* in *box* (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = box
    px = art[y0:y1, x0:x1, :3].astype(int)
    return bool((np.abs(px - np.array(rgb)).max(axis=2) < tol).any())


def test_the_look_is_kept_with_the_characters_and_checked(tmp_path):
    project = _project(tmp_path)
    CP.save_look(project, "title", "  pick   your kaiju ")
    CP.save_look(project, "name", "#FFD400")
    CP.save_look(project, "dim", "60")
    th = CP.load_characters(project)["theme"]
    assert th == {"title": "PICK YOUR KAIJU", "name": "#ffd400", "dim": 60}
    for key, bad in (("name", "gold"), ("name", "#ffd4"), ("dim", 35), ("glow", "#ffffff"), ("backdrop", "x.png")):
        with pytest.raises(CP.CoopError):
            CP.save_look(project, key, bad)
    CP.save_look(project, "name", "")                                    # empty: the default again
    assert "name" not in CP.load_characters(project)["theme"]
    full = CP.theme_of(CP.load_characters(project)["theme"])
    assert full["name"] == "#ffffff" and full["title"] == "PICK YOUR KAIJU" and full["dim"] == 60
    assert CP.theme_of({"accent": "red", "dim": 33})["accent"] == CP.THEME["accent"]   # junk in a file: default
    assert CP.theme_of({"dim": 33})["dim"] == CP.THEME["dim"]


def test_left_alone_the_cards_draw_as_before(tmp_path):
    """The stock look through the new keys is the old look: every colour the card drew by hand is the default."""
    assert CP.THEME["heading"] == CP.THEME["name"] == CP.THEME["help"] == "#ffffff"
    assert CP._hex(CP.THEME["does"]) == (222, 228, 240, 255) and CP._hex(CP.THEME["badge_text"]) == (12, 12, 18, 255)
    assert CP.THEME["sub"] == CP.THEME["badge"] == CP.THEME["count"] == CP.THEME["panel"] == ""   # the frame's
    project = _project(tmp_path)
    a = _card(project)
    CP.save_look(project, "name", CP.THEME["name"])                      # the default, chosen: the same card
    assert np.array_equal(a, _card(project))


def test_each_colour_reaches_its_words(tmp_path):
    project = _project(tmp_path)
    for key, colour, box in (("name", "#00ff00", (IX, 90, 1240, 150)),           # the name's line
                             ("sub", "#ff00ff", (IX, 180, 1240, 206)),           # the sub header
                             ("badge", "#0000ff", (IX, 222, 1240, 268)),         # the badge
                             ("does", "#ff0000", (IX, 280, 1240, 350)),          # what it does
                             ("help", "#00ffff", (IX + 50, 362, 1240, 384)),     # how to choose
                             ("heading", "#ff8000", (40, 26, 600, 62))):         # the title
        before = _card(project)
        assert not _has(before, box, CP._hex(colour)[:3]), key
        CP.save_look(project, key, colour)
        assert _has(_card(project), box, CP._hex(colour)[:3]), key
    award = _card(project, award=True)
    assert _has(award, (380, 120, 860, 210), (0, 255, 0)) and _has(award, (380, 230, 860, 270), (255, 0, 255))


def test_a_character_has_a_frame_colour_of_its_own(tmp_path):
    project = _project(tmp_path)
    chars = CP.load_characters(project)
    chars["list"][0]["colour"] = "#7A3CFF"
    chars["list"][1]["colour"] = "purple"                                 # not a colour: the look's
    got = CP.save_characters(project, chars)
    assert [c["colour"] for c in got["list"]] == ["#7a3cff", ""]
    frame = (38, 82, 424, 88)                                            # the portrait frame's top edge
    assert _has(_card(project, 0), frame, (122, 60, 255), 30)
    assert not _has(_card(project, 1), frame, (122, 60, 255), 30)
    assert _has(_card(project, 1), frame, CP._hex(CP.THEME["accent"])[:3], 30)


def test_a_background_picture_goes_behind_every_card_darkened(tmp_path):
    project = _project(tmp_path)
    _png(tmp_path / "bg.png", (0, 0, 250))
    CP.save_look(project, "dim", 0)
    CP.save_backdrop(project, str(tmp_path / "bg.png"))
    th = CP.load_characters(project)["theme"]
    assert th["backdrop"] == "coop/backdrop.png" and os.path.isfile(os.path.join(project, "coop", "backdrop.png"))
    spot = (1080, 388, 1120, 400)                                        # bare panel over the roster strip
    assert _has(_card(project), spot, (0, 0, 250), 12)
    assert _has(_card(project, award=True), (600, 300, 620, 320), (0, 0, 250), 12)
    CP.save_look(project, "dim", 60)
    assert _has(_card(project), spot, (0, 0, 100), 12)                   # 60 % darker
    _png(tmp_path / "bg2.jpg", (250, 0, 0))
    CP.save_backdrop(project, str(tmp_path / "bg2.jpg"))
    assert sorted(os.listdir(os.path.join(project, "coop"))) == ["backdrop.jpg"]   # one background
    CP.save_backdrop(project, None)
    assert "backdrop" not in CP.load_characters(project)["theme"]
    (tmp_path / "no.png").write_text("not a picture")
    with pytest.raises(CP.CoopError):
        CP.save_backdrop(project, str(tmp_path / "no.png"))


def test_default_look_is_the_games_set_again(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.setattr(CP, "project_title", lambda project, probe=False: object())
    monkeypatch.setattr(CP, "preset_for", lambda prof: CP.presets()["godzilla"])
    CP.save_look(project, "name", "#123456")
    _png(tmp_path / "bg.png", (1, 2, 3))
    CP.save_backdrop(project, str(tmp_path / "bg.png"))
    CP.save_look_default(project)
    th = CP.load_characters(project)["theme"]
    assert th == CP.read_preset(CP.presets()["godzilla"])["characters"]["theme"]


def test_the_settings_file_carries_the_look_and_its_background(tmp_path, monkeypatch):
    monkeypatch.setattr(CP, "project_title", lambda project, probe=False: types.SimpleNamespace(label="Godzilla"))
    src = _project(tmp_path)
    CP.save(src, True)
    CP.save_look(src, "does", "#a8ffb0")
    chars = CP.load_characters(src)
    chars["list"][1]["colour"] = "#7a3cff"
    CP.save_characters(src, chars)
    _png(tmp_path / "bg.jpg", (0, 0, 250))
    CP.save_backdrop(src, str(tmp_path / "bg.jpg"))
    out = str(tmp_path / "coop.zip")
    assert CP.export_settings(src, out)["pictures"] == 1
    dest = str(tmp_path / "d")
    os.makedirs(dest)
    assert CP.import_settings(dest, out)["pictures"] == 1
    got = CP.load_characters(dest)
    assert got["theme"] == {"does": "#a8ffb0", "backdrop": "coop/backdrop.jpg"} and got["list"][1]["colour"] == "#7a3cff"
    assert os.path.isfile(os.path.join(dest, "coop", "backdrop.jpg"))
    js = str(tmp_path / "coop.json")                                     # a .json cannot carry the picture
    assert CP.export_settings(src, js)["left_out"] == 1
    dest2 = str(tmp_path / "d2")
    os.makedirs(dest2)
    CP.import_settings(dest2, js)
    assert CP.load_characters(dest2)["theme"] == {"does": "#a8ffb0"}


def test_the_dialog_sets_the_look(tmp_path, monkeypatch):
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
    assert not svc.coop_chars_look("name", "gold") and "not a colour" in said[-1]
    look = state["coop_ch"]["look"]
    name = next(c for c in look["colours"] if c["key"] == "name")
    assert name == {"key": "name", "label": "Name", "value": "#ffd400", "own": True, "follows": False}
    sub = next(c for c in look["colours"] if c["key"] == "sub")
    assert sub["follows"] and sub["value"] == CP.THEME["accent"]           # the frame's colour, shown as it draws
    _png(tmp_path / "bg.png", (0, 0, 250))
    monkeypatch.setattr(svc, "window", types.SimpleNamespace(ask_open=lambda *a: str(tmp_path / "bg.png")),
                        raising=False)
    assert svc.coop_chars_backdrop() and state["coop_ch"]["look"]["backdrop"]
    assert svc.coop_char_colour(1, "#7a3cff") and state["coop_ch"]["rows"][1]["colour"] == "#7a3cff"
    assert svc.coop_chars_look_default() and not state["coop_ch"]["look"]["backdrop"]
    js = (ROOT / "pinball_decryptor" / "webui" / "static" / "js" / "tabs" / "modes_dialogs.js").read_text("utf-8")
    for rpc in ("coop_chars_look", "coop_chars_look_default", "coop_chars_backdrop", "coop_char_colour"):
        assert 'call("modes.%s"' % rpc in js
