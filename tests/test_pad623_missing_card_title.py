"""PAD-623: a project whose card file was moved or deleted still knows its game in Modes.

* mode_project.project_card: a card whose game cannot be read (its file is gone, or its own index named none)
  takes the game the project's saved modes name (modes_title) - a mode.json's title, or a code/blocks mode's
  assets.json title when that is a game this app has modes for. Modes naming two games, or none, leave it unknown.
* A card that is there and not read yet is probed first, as before: the modes never hide what the card says.
* The tab says a gone card is gone, rather than "could not be read".
* playfield_art.game_art: the picture comes off the first card of the game that is on this computer, and is kept,
  so a project whose card is gone still shows it.
"""
import json
import os

from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import playfield_art as PA
from tests.test_webui_modes import preview_on  # noqa: F401

CUSTOM = "Godzilla Premium 1.16 Heisei Custom V1.99D Kaiju Edition.raw"
PNG = b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR\0\0\x019\0\0\x02\xc6" + b"\0" * 8


def _project(path, card, modes=()):
    """A project whose .pinproj names ``card``, with ``modes``: ``[(slug, file name, title)]``."""
    os.makedirs(str(path), exist_ok=True)
    with open(os.path.join(str(path), ".pinproj"), "w", encoding="utf-8") as f:
        json.dump({"kind": "pinball-asset-decryptor-project", "format": 2, "manufacturer": "stern",
                   "stock_image": card, "paths": {"extract_input": card, "write_original": card}}, f)
    for slug, fname, title in modes:
        os.makedirs(os.path.join(str(path), "modes", slug), exist_ok=True)
        with open(os.path.join(str(path), "modes", slug, fname), "w", encoding="utf-8") as f:
            json.dump({"name": slug.upper(), "title": title}, f)
    return str(path)


# the modes of David's project: a mode.json and a blocks mode name the game; the code modes' titles are screen words
HEISEI = [("new_mode", "mode.json", "godzilla_le_1_16"), ("blockhead", "assets.json", "godzilla_le_1_16"),
          ("kiryu", "assets.json", "SUPER X2"), ("anguirus_assist", "assets.json", " ")]


def test_a_gone_card_takes_the_game_its_modes_were_made_for(tmp_path):
    gone = str(tmp_path / "moved away" / CUSTOM)
    proj = _project(tmp_path / "heisei", gone, HEISEI)
    card = MP.project_card(proj)
    assert (card.image, card.game_dir, card.version) == (gone, "godzilla_le", "1.16")
    assert card.source == MP.MODES_TITLE_SOURCE
    got, prof = MP.project_profile(proj, probe=True)
    assert got == card and prof.key == "godzilla_le_1_16" and prof.label == "Godzilla Premium/LE 1.16"
    assert MP.modes_title(proj).key == "godzilla_le_1_16"


def test_modes_naming_no_game_or_two_leave_it_unknown(tmp_path):
    gone = str(tmp_path / CUSTOM)
    assert MP.project_card(_project(tmp_path / "none", gone)).game_dir == ""
    assert MP.project_card(_project(tmp_path / "words", gone, [("kiryu", "assets.json", "SUPER X2")])).game_dir == ""
    two = _project(tmp_path / "two", gone, [("a", "mode.json", "godzilla_le_1_16"),
                                            ("b", "mode.json", "godzilla_pro_1_15")])
    assert MP.modes_title(two) is None and MP.project_card(two).game_dir == ""


def test_a_card_that_is_there_is_read_first(tmp_path, monkeypatch):
    image = tmp_path / CUSTOM
    image.write_bytes(b"\0" * 4096)
    proj = _project(tmp_path / "heisei", str(image), HEISEI)
    # not probed yet: unknown, so the tab reads the card's own index
    assert MP.project_card(proj).game_dir == ""
    # the card's own index wins over the modes
    monkeypatch.setitem(MP._PROBED, MP._probe_key(str(image)), ("godzilla_pro", "1.15.0"))
    card = MP.project_card(proj)
    assert (card.game_dir, card.version, card.source) == ("godzilla_pro", "1.15.0", "the card's own index")
    # an index that names no game: the modes say which
    monkeypatch.setitem(MP._PROBED, MP._probe_key(str(image)), (None, None))
    card = MP.project_card(proj)
    assert (card.game_dir, card.source) == ("godzilla_le", MP.MODES_TITLE_UNREAD)


def test_a_stern_named_card_needs_no_modes(tmp_path):
    gone = str(tmp_path / "godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw")
    card = MP.project_card(_project(tmp_path / "p", gone, HEISEI))
    assert (card.game_dir, card.source) == ("godzilla_pro", "the card's file name")


# ------------------------------------------------------------ the picture
def test_the_picture_is_kept_for_a_card_that_goes(tmp_path, monkeypatch):
    image = tmp_path / "godzilla_le-1_16_0.raw"
    image.write_bytes(b"")
    asked = []
    monkeypatch.setattr(PA, "card_art", lambda img, game: asked.append(img) or (PNG, "/godzilla_le/x.png"))
    missing = str(tmp_path / CUSTOM)
    assert PA.game_art([missing, str(image)], "godzilla_le") == (PNG, "/godzilla_le/x.png")
    assert asked == [str(image)]                        # a card that is not there is never opened
    assert PA.kept_art("godzilla_le") == PNG
    image.unlink()
    data, where = PA.game_art([str(image)], "godzilla_le")
    assert data == PNG and where == "kept from an earlier read of a godzilla_le card"
    assert PA.game_art([], "godzilla_pro") == (None, "no godzilla_pro card is on this computer to read it from")


def test_a_card_that_gives_none_says_why(tmp_path, monkeypatch):
    image = tmp_path / "deadpool_le-1_14_0.raw"
    image.write_bytes(b"")
    monkeypatch.setattr(PA, "card_art", lambda img, game: (None, "deadpool_le ships no playfield picture"))
    assert PA.game_art([str(image)], "deadpool_le") == (None, "deadpool_le ships no playfield picture")


# ------------------------------------------------------------ the tab
def test_the_tab_shows_the_modes_game_and_the_picture(tmp_path, preview_on, monkeypatch):
    from tests.test_webui_modes import _project as point_at
    from tests.webui_harness import web_app
    gone = str(tmp_path / "moved away" / CUSTOM)
    proj = _project(tmp_path / "heisei", gone, HEISEI)
    stock = tmp_path / "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
    stock.write_bytes(b"")
    asked = []
    monkeypatch.setattr(PA, "card_art", lambda img, game: asked.append((img, game)) or (PNG, "/x.png"))
    with web_app(tmp_path, mfr="stern") as w:
        w.run(lambda: w.window.set_path_history({"extract_input": [gone, str(stock)]}))
        point_at(w, proj, card=None)
        st = w.state("modes")
        assert st["profile"]["label"] == "Godzilla Premium/LE 1.16" and st["new_ok"]
        assert st["title_text"].startswith("Card: %s, Godzilla Premium/LE 1.16 (from %s)."
                                           % (CUSTOM, MP.MODES_TITLE_SOURCE))
        got = w.call("modes.blocks_playfield")
        assert asked == [(str(stock), "godzilla_le")] and got["art"].startswith("data:image/png;base64,")
        assert got["why"] == ""


def test_the_tab_says_a_gone_card_is_gone(tmp_path, preview_on):
    from tests.test_webui_modes import _project as point_at
    from tests.webui_harness import web_app
    proj = _project(tmp_path / "bare", str(tmp_path / CUSTOM))
    with web_app(tmp_path, mfr="stern") as w:
        point_at(w, proj, card=None)
        st = w.state("modes")
        assert st["title_text"].startswith("Card: %s is not on this computer any more (moved or deleted?)" % CUSTOM)
        assert not st["new_ok"]
