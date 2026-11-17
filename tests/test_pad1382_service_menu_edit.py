"""PAD-1382 round 3: the Service menu tab's controls - the owner's order of the rows, settings of their own (read by
the card's own code through pm_setting), and the real menu read from the game in the emulator (menushot.sh)."""
import json
import os
import re

import pytest

from pinball_decryptor.plugins.stern import menu_settings as MS
from pinball_decryptor.plugins.stern import service_menu as SM

from tests.test_pad1382_more_settings import LE116, ROOT, _program

RUNTIME = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk", "pad_mode_runtime.c")
HEADER = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk", "pad_mode.h")


def _project(tmp_path, side):
    p = str(tmp_path)
    with open(os.path.join(p, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump(side, f)
    return p


# ---- the owner's settings, as kept ----------------------------------------------------------------------------------
def test_a_setting_of_ones_own_is_a_name_and_its_values():
    c = SM.custom_clean("  Dark   Screens ", "Off, On ,", 2)
    assert c == {"key": "custom_dark_screens", "name": "Dark Screens", "values": ["Off", "On"], "default": 2}
    assert SM.custom_clean("X1", ["a", "b", "c"], 9)["default"] == 1          # a default out of range starts at 1
    for name, values in (("", "a,b"), ("x" * 21, "a,b"), ("Bad/name", "a,b"), ("Ok", "only"), ("Ok", ",".join("abcdefghi")),
                         ("Handicap", "a,b"), ("co-op play", "a,b")):
        with pytest.raises(ValueError):
            SM.custom_clean(name, values)


def test_the_order_and_ones_own_settings_live_in_the_sidecar(tmp_path):
    p = _project(tmp_path, {})
    assert SM.load(p) == {"order": [], "custom": []}
    data = {"order": ["handicap", "custom_x"], "custom": [SM.custom_clean("X", "a,b")]}
    SM.save(p, data)
    assert SM.load(p) == data
    SM.save(p, {"order": [], "custom": []})
    assert "service_menu" not in json.load(open(os.path.join(p, ".staged_changes.json"), encoding="utf-8"))


def test_the_owners_order_comes_first_then_the_engines(tmp_path):
    p = _project(tmp_path, {"coop_play": {"on": True, "menu": True}, "handicap": {"on": True},
                            "service_menu": {"order": ["custom_b", "handicap"],
                                             "custom": [{"name": "A", "values": ["x", "y"]},
                                                        {"name": "B", "values": ["x", "y", "z"], "default": 3}]}})
    assert [r[0] for r in SM.wanted(p)] == ["custom_b", "handicap", "coop_play", "custom_a"]
    assert SM.wanted(p)[0] == ("custom_b", 3, ["x", "y", "z"], {"default": 3})


# ---- on the real program -------------------------------------------------------------------------------------------
def test_ones_own_settings_take_rows_as_the_apps_do_and_share_when_short(tmp_path):
    raw = _program(LE116)
    p = _project(tmp_path, {"service_menu": {"custom": [{"name": "Dark Screens", "values": ["Off", "On"]}]}})
    menu = SM.pages(raw, SM.wanted(p))
    rows = [r for p in menu["pages"] for r in p["rows"] if r["ours"]]
    assert [r["caption"] for r in rows] == ["Dark Screens"] and not menu["shared"]
    p = _project(tmp_path, {"coop_play": {"on": True, "menu": True}, "handicap": {"on": True},
                            "service_menu": {"order": ["custom_dark_screens"],
                                             "custom": [{"name": "Dark Screens", "values": ["Off", "On"]},
                                                        {"name": "Attract Music", "values": ["Q", "N", "L"]}]}})
    rows_wanted = SM.wanted(p)
    menu = SM.pages(raw, rows_wanted)
    assert menu["shared"] and menu["refused"] == {}
    more = next(r for p in menu["pages"] for r in p["rows"] if r.get("key") == MS.MORE_SELECT)
    assert [o["caption"] for o in more["options"]] == ["Dark Screens", "Co-op Play", "Handicap", "Attract Music"]
    from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable
    settings = MS.plan_many(AdjustmentTable(raw), rows_wanted)[0]
    text = MS.shared_cfg_text(settings)
    assert "custom\tcustom_dark_screens\t0xfade0004" in text and "custom\tcustom_attract_music\t0xfade0010" in text
    # a custom one on a row of its own: its row's .nonvol address
    p = _project(tmp_path, {"service_menu": {"custom": [{"name": "Solo", "values": ["a", "b"]}]}})
    settings = MS.plan_many(AdjustmentTable(raw), SM.wanted(p))[0]
    solo = next(s for s in settings if s.key == "custom_solo")
    assert MS.shared_cfg_text(settings).splitlines()[1:] == ["custom\tcustom_solo\t0x%08x" % solo.live]


def test_the_walk_reaches_each_machine_settings_page_by_its_place():
    t_pages = SM.pages(_program(LE116), [("coop_play", 3, (), {"from_zero": True})])["pages"]
    assert [(p["name"], p["rank"]) for p in t_pages if p["ours"]] == [("Attract Mode", 7)]
    w = SM.walk(7, 5)
    assert w[:14] == ["25", "w2", "25", "w2", "26", "26", "26", "26", "25", "w1.5", "26", "26", "25", "w1.5"]
    assert w[14:] == ["26"] * 7 + ["25", "w2"] + ["26"] * 5 + ["w1"]


# ---- the runtime, the rig script, the tab ---------------------------------------------------------------------------
def test_the_cards_own_code_reads_ones_own_settings():
    src = open(RUNTIME, encoding="utf-8").read()
    assert "unsigned pm_setting(const char *key)" in src and 'str_eq(f[0], "custom")' in src
    assert "unsigned pm_setting(const char *key);" in open(HEADER, encoding="utf-8").read()
    assert re.search(r"#define MSET_CUSTOM\s+%d" % SM.CUSTOM_MAX, src)


def test_the_real_menu_is_read_by_a_rig_script_of_the_emulates():
    sh = open(os.path.join(ROOT, "tools", "spike2_emu", "menushot.sh"), encoding="utf-8").read()
    assert '. "$RIG/rigjob.sh"' in sh and "glshot.sh" in sh and "job_wait_attract" in sh
    from pinball_decryptor.webui.tabs import emulate
    assert hasattr(emulate.EmulateTab if hasattr(emulate, "EmulateTab") else emulate.TAB, "menu_shot")


def test_the_tab_orders_adds_and_removes(tmp_path):
    from tests.webui_harness import web_app
    p = _project(tmp_path, {"handicap": {"on": True}})
    with web_app(tmp_path / "app") as w:
        modes = w.window.service("modes")
        var = modes._project_var() if modes is not None else None
        if var is None:
            pytest.skip("no project folder variable in this window")
        w.run(lambda: var.set(p))
        w.drain()
        w.call("ui.select_tab", "svcmenu")
        w.drain()
        assert w.call("svcmenu.add_custom", "Dark Screens", "Off, On", 1) == ""
        assert "1 to 20" in w.call("svcmenu.add_custom", "x" * 30, "a,b", 1)
        keys = [r["key"] for r in w.state("svcmenu")["settings"]]
        assert keys[-1] == "custom_dark_screens"
        w.call("svcmenu.move", "custom_dark_screens", -1)
        w.drain()
        keys2 = [r["key"] for r in w.state("svcmenu")["settings"]]
        assert keys2.index("custom_dark_screens") == keys.index("custom_dark_screens") - 1
        assert SM.load(p)["order"] == keys2
        w.call("svcmenu.remove_custom", "custom_dark_screens")
        w.drain()
        assert SM.load(p)["custom"] == [] and "custom_dark_screens" not in SM.load(p)["order"]
        assert w.call("svcmenu.set_real", True) and w.state("svcmenu")["real_on"]
