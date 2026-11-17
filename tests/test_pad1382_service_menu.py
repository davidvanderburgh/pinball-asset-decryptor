"""PAD-1382: the Service menu tab - the game's operator menu as the card will show it, the app's rows in it.

The page order was read in the emulator (Godzilla LE 1.16: artifacts/PAD-1382/emulator); the Write's own planner places
our rows, so the tab cannot disagree with the card. Round 5 (David: "it's really weird to shove in these settings into
the 'attract mode' tab"): every row of ours goes on a page of its own, Custom Code - the emulator showed it in Machine
Settings between Audio Configuration and Attract Mode, holding MORE SETTINGS and the row under it."""
import json
import os

import pytest

from pinball_decryptor.plugins.stern import menu_settings as MS
from pinball_decryptor.plugins.stern import service_menu as SM
from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable

from tests.test_pad1382_more_settings import LE116, _program, _wanted

#: Attract Mode on Godzilla LE 1.16 in the emulator (70TH BOOT SCREEN: the game hides it)
GAME_ROWS = ["Play Attract Tutorial Videos", "Custom Message", "Time Format", "Show How To Connect Msg",
             "Display Message of the Day", "Show Mode High Score Display", "Boot Screen", "70th Boot Screen",
             "DJ Mixer Background", "Attract Dev Credits"]
MACHINE = ["Machine Operation", "Device Enables", "Coil Settings", "LCD/Lamp", "Audio Settings", "Audio Content",
           "Audio Configuration", "Custom Code", "Attract Mode", "Test Menu Settings"]


def _page(menu, name):
    return next(p for p in menu["pages"] if p["name"] == name)


def test_the_apps_rows_go_on_a_page_of_their_own():
    menu = SM.pages(_program(LE116), [r for r in _wanted() if r[0] in ("coop_play", "handicap")])
    assert (menu["spare"], menu["used"], menu["shared"], menu["refused"], menu["own"]) == (3, 2, False, {}, "Custom Code")
    assert menu["machine_list"] == MACHINE
    own = _page(menu, "Custom Code")
    assert (own["category"], own["rank"], own["path"]) == (15, 7, "Adjustments > Machine Settings > Custom Code")
    assert [r["caption"] for r in own["rows"]] == ["Co-op Play", "Handicap"] and all(r["ours"] for r in own["rows"])
    by = {r["caption"]: r for r in own["rows"]}
    assert [v["text"] for v in by["Handicap"]["values"]] == ["Off", "On"]
    assert [v["text"] for v in by["Co-op Play"]["values"]] == ["0", "1", "2"]
    # the game's own pages stay as they were
    attract = _page(menu, "Attract Mode")
    assert [r["caption"] for r in attract["rows"]] == GAME_ROWS and not attract["ours"]
    by = {r["caption"]: r for r in attract["rows"]}
    assert [by[c]["value"] for c in GAME_ROWS[:6]] == ["Yes", "On", "", "", "Yes", "Yes"]
    assert by["Play Attract Tutorial Videos"]["help"] == "Turns on/off Tutorial Videos in Attract Mode"


def test_shared_rows_are_drawn_as_the_machine_drew_them():
    menu = SM.pages(_program(LE116), _wanted())
    assert menu["shared"] and menu["refused"] == {}
    own = _page(menu, "Custom Code")
    assert [r["caption"] for r in own["rows"]] == ["More Settings", "Brightness"]
    more = own["rows"][0]
    assert more["key"] == MS.MORE_SELECT and [v["v"] for v in more["values"]] == [1, 2, 3, 4, 5]
    assert [o["caption"] for o in more["options"]] == ["Brightness", "Contrast", "Saturation", "Co-op Play", "Handicap"]
    assert more["options"][3]["help"].startswith("0 Off. 1 Classic.")
    assert own["rows"][1]["shared_value"] and own["rows"][1]["value"] == "5"


def test_the_page_of_our_own_is_named_in_the_program():
    t = AdjustmentTable(_program(LE116))
    writes = MS.own_page(t)
    names = sorted(v.rstrip(b"\x00") for v in writes.values())
    assert names == [b"Custom Code", b"Settings added by this card's custom code."]
    # the page's name and its help in the Machine Settings list, each rewritten in place over the old
    old = sorted(t.data[o:t.data.find(b"\x00", o)] for o in writes)
    assert old == [b"Wireless Audio Devices", b"Wireless audio devices, such as headphones, can be connected to this game."]
    settings, all_writes, _c, _r = MS.plan_many(t, _wanted()[3:])
    assert all(s.category == MS.OWN_CATEGORY for s in settings) and set(writes) <= set(all_writes)


def test_no_rows_of_ours_still_shows_the_menu():
    """Round 4: every Machine Settings page shows, to see the menu before adding to it."""
    menu = SM.pages(_program(LE116), [])
    assert len(menu["pages"]) == 9 and not any(p["ours"] for p in menu["pages"]) and menu["own"] == ""
    assert [r["caption"] for r in _page(menu, "Attract Mode")["rows"]] == GAME_ROWS


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
    assert window.PHASE_ROW_BY_KEY.get("Service Menu") == "write"
    text = " ".join(" ".join(b) if isinstance(b, list) else "" for _t, b in help_content.HELP_CONTENT["Service Menu"])
    assert "Custom Code" in text and "Add a setting" not in text
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
    assert why == "" and [r["caption"] for r in _page(menu, "Custom Code")["rows"]] == ["Handicap"]
    why, menu = svcmenu.project_menu(str(tmp_path / "nothing"))
    assert why and menu is None
