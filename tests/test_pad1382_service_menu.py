"""PAD-1382 round 2: the Service menu tab - the game's operator menu as the card will show it, the app's rows in it.

The page order was read in the emulator (Godzilla LE 1.16, Attract Mode: artifacts/PAD-1382/emulator/after_c1.png);
the Write's own planner places our rows, so the tab cannot disagree with the card."""
import json
import os

import pytest

from pinball_decryptor.plugins.stern import menu_settings as MS
from pinball_decryptor.plugins.stern import service_menu as SM

from tests.test_pad1382_more_settings import LE116, _program, _wanted

#: Attract Mode on Godzilla LE 1.16 in the emulator, our rows where they went (70TH BOOT SCREEN: the game hides it)
GAME_ROWS = ["Play Attract Tutorial Videos", "Custom Message", "Time Format", "Show How To Connect Msg",
             "Display Message of the Day", "Show Mode High Score Display", "Boot Screen", "70th Boot Screen",
             "DJ Mixer Background", "Attract Dev Credits"]


def _attract(menu):
    return next(p for p in menu["pages"] if p["name"] == "Attract Mode")


def test_rows_that_fit_sit_where_the_emulator_showed_them():
    menu = SM.pages(_program(LE116), [r for r in _wanted() if r[0] in ("coop_play", "handicap")])
    assert (menu["spare"], menu["used"], menu["shared"], menu["refused"]) == (3, 2, False, {})
    rows = _attract(menu)["rows"]
    assert [r["caption"] for r in rows] == GAME_ROWS[:5] + ["Co-op Play", "Handicap"] + GAME_ROWS[5:]
    by = {r["caption"]: r for r in rows}
    # the values the machine showed for the game's own rows that the kind words (the rest left blank)
    assert [by[c]["value"] for c in GAME_ROWS[:6]] == ["Yes", "On", "", "", "Yes", "Yes"]
    assert by["Handicap"]["ours"] and by["Handicap"]["value"] == "Off"
    assert [v["text"] for v in by["Handicap"]["values"]] == ["Off", "On"]
    assert [v["text"] for v in by["Co-op Play"]["values"]] == ["0", "1", "2"]
    assert by["Play Attract Tutorial Videos"]["help"] == "Turns on/off Tutorial Videos in Attract Mode"


def test_shared_rows_are_drawn_as_the_machine_drew_them():
    menu = SM.pages(_program(LE116), _wanted())
    assert menu["shared"] and menu["refused"] == {}
    page = _attract(menu)
    assert [r["caption"] for r in page["rows"]] == GAME_ROWS[:5] + ["More Settings", "Brightness"] + GAME_ROWS[5:]
    more = page["rows"][5]
    assert more["key"] == MS.MORE_SELECT and [v["v"] for v in more["values"]] == [1, 2, 3, 4, 5]
    assert [o["caption"] for o in more["options"]] == ["Brightness", "Contrast", "Saturation", "Co-op Play", "Handicap"]
    assert more["options"][3]["help"].startswith("0 Off. 1 Classic.")
    assert page["rows"][6]["shared_value"] and page["rows"][6]["value"] == "5"


def test_no_rows_of_ours_still_shows_the_menu():
    """Round 4: every Machine Settings page shows, to see the menu before adding to it."""
    pages = SM.pages(_program(LE116), [])["pages"]
    assert len(pages) == 9 and not any(p["ours"] for p in pages)
    assert [r["caption"] for r in _attract({"pages": pages})["rows"]] == GAME_ROWS


def test_the_project_asks_for_what_its_tabs_switched(tmp_path):
    p = str(tmp_path)
    with open(os.path.join(p, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"coop_play": {"on": True, "menu": True}, "handicap": {"on": True}}, f)
    assert [r[0] for r in SM.wanted(p)] == ["coop_play", "handicap"]
    with open(os.path.join(p, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"coop_play": {"on": True}}, f)                 # co-op always on: no row
    assert SM.wanted(p) == []


def test_the_tab_is_on_the_rail_for_spike2_with_its_help():
    from pinball_decryptor.webui import tabs, help_content, window
    assert ("svcmenu", "svcmenu", "Service Menu", "Service menu", "Make", "list") in tabs.TABS
    assert window.PHASE_ROW_BY_KEY.get("Service Menu", "x") in ("x", None, "write")
    assert help_content.sections_for("Service Menu")
    src = open(window.__file__, encoding="utf-8").read()
    assert '"Service Menu": g("modes"),' in src


def test_the_tab_reads_the_projects_card(tmp_path):
    if not os.path.isfile(LE116):
        pytest.skip("no Godzilla LE 1.16 card on this machine")
    from pinball_decryptor.webui.tabs import svcmenu
    p = str(tmp_path)
    with open(os.path.join(p, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": LE116, "input_name": os.path.basename(LE116), "card_version": "1.16.0"}, f)
    with open(os.path.join(p, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"handicap": {"on": True}}, f)
    why, menu = svcmenu.project_menu(p)
    assert why == "" and [r["caption"] for r in _attract(menu)["rows"] if r["ours"]] == ["Handicap"]
    why, menu = svcmenu.project_menu(str(tmp_path / "nothing"))
    assert why and menu is None
