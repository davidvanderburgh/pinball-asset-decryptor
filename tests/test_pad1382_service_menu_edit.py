"""PAD-1382 rounds 3 and 5: the Service menu tab's controls - the owner's order of the app's rows (round 5: only the
app's own settings, ticked; no settings of one's own - David: "making a new one here doesn't make sense") and the real
menu read from the game in the emulator (menushot.sh)."""
import json
import os

import pytest

from pinball_decryptor.plugins.stern import service_menu as SM

from tests.test_pad1382_more_settings import ROOT

RUNTIME = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk", "pad_mode_runtime.c")


def _project(tmp_path, side):
    p = str(tmp_path)
    with open(os.path.join(p, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump(side, f)
    return p


def test_the_order_lives_in_the_sidecar(tmp_path):
    p = _project(tmp_path, {})
    assert SM.load(p) == {"order": []}
    SM.save(p, {"order": ["handicap", "coop_play"]})
    assert SM.load(p) == {"order": ["handicap", "coop_play"]}
    SM.save(p, {"order": []})
    assert "service_menu" not in json.load(open(os.path.join(p, ".staged_changes.json"), encoding="utf-8"))


def test_the_owners_order_comes_first_then_the_engines(tmp_path):
    p = _project(tmp_path, {"coop_play": {"on": True, "menu": True}, "handicap": {"on": True},
                            "service_menu": {"order": ["handicap"],
                                             "custom": [{"name": "Old", "values": ["x", "y"]}]}})
    assert [r[0] for r in SM.wanted(p)] == ["handicap", "coop_play"]   # a round 3 project's own settings are gone


def test_there_are_no_settings_of_ones_own():
    assert not hasattr(SM, "CustomMenu") and not hasattr(SM, "custom_clean")
    assert "pm_setting" not in open(RUNTIME, encoding="utf-8").read()


def test_the_walk_reaches_each_machine_settings_page_by_its_place():
    w = SM.walk(7, 1)
    assert w[:14] == ["25", "w2", "25", "w2", "26", "26", "26", "26", "25", "w1.5", "26", "26", "25", "w1.5"]
    assert w[14:] == ["26"] * 7 + ["25", "w2", "26", "w1"]


def test_the_real_menu_is_read_by_a_rig_script_of_the_emulates():
    sh = open(os.path.join(ROOT, "tools", "spike2_emu", "menushot.sh"), encoding="utf-8").read()
    assert '. "$RIG/rigjob.sh"' in sh and "glshot.sh" in sh and "job_wait_attract" in sh
    from pinball_decryptor.webui.tabs import emulate
    assert hasattr(emulate.EmulateTab, "menu_shot")


def test_the_tab_orders_and_switches(tmp_path):
    from tests.webui_harness import web_app
    p = _project(tmp_path, {"handicap": {"on": True}, "coop_play": {"on": True, "menu": True}})
    with web_app(tmp_path / "app") as w:
        modes = w.window.service("modes")
        var = modes._project_var() if modes is not None else None
        if var is None:
            pytest.skip("no project folder variable in this window")
        w.run(lambda: var.set(p))
        w.drain()
        w.call("ui.select_tab", "svcmenu")
        w.drain()
        keys = [r["key"] for r in w.state("svcmenu")["settings"]]
        assert "handicap" in keys and "coop_play" in keys
        w.call("svcmenu.move", "handicap", -1)
        w.drain()
        keys2 = [r["key"] for r in w.state("svcmenu")["settings"]]
        assert keys2.index("handicap") == keys.index("handicap") - 1 and SM.load(p)["order"] == keys2
        w.call("svcmenu.set_row", "handicap", False)
        w.drain()
        assert not next(r for r in w.state("svcmenu")["settings"] if r["key"] == "handicap")["on"]
        with pytest.raises(Exception):
            w.call("svcmenu.add_custom", "X", "a,b", 1)
        assert w.call("svcmenu.set_real", True) and w.state("svcmenu")["real_on"]
