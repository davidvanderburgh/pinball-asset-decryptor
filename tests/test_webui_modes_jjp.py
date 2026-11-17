"""The Modes tab on a Jersey Jack game (PAD-1350, webui/modes_jjp.py + plugins/jjp/custom_modes.py).

Every test runs the real app in-process (tests/webui_harness.py: the settings file, and so
the mode folders beside it, are scratch).  The build is stood in by a small Python command,
so nothing mounts an ISO; the real build is proven on the Wonka emulator (docs/plans).
"""
import os
import sys
import time

import pytest

from tests.webui_harness import web_app

#: every title whose port report can run modes (MODES.md "Titles")
RUNNABLE = {"GunsNRoses-v03.03", "CHAKAs_LOTLJ_V1.0_GNR_LE_3.03", "EltonJohn-v02.03", "Godfather-v02.03",
            "Pirates-v01.01", "Wonka-v03.03", "DialedIn-v02.02", "Hobbit-v04.02", "ToyStory-v02.04"}


@pytest.fixture
def preview_on(monkeypatch):
    from pinball_decryptor.core import preview
    monkeypatch.setattr(preview, "enabled", lambda feature: feature == "modes")
    return True


def _svc(w):
    return w.window.service("modes")


def _jjp(w):
    return w.state("modes").get("jjp") or {}


def _wait(w, cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def _open_wonka(w):
    w.call("ui.select_tab", "modes")
    w.call("modes.jjp_pick_title", "Wonka-v03.03")
    return _jjp(w)


def test_the_tab_shows_on_jjp_with_every_title_that_can_run_modes(tmp_path, preview_on):
    with web_app(tmp_path, mfr="jjp") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["modes"]["visible"]
        # the Stern-only tabs the mode runtime carries stay off on JJP
        for ns in ("attract", "play_options", "expression_lights"):
            if ns in tabs:
                assert not tabs[ns]["visible"], ns
        assert _svc(w).rail_needs() == "none"
        j = _open_wonka(w)
        assert j["on"] and j["label"] == "Wonka-v03.03" and j["can_run"]
        runnable = {t["label"] for t in j["titles"] if t["can_run"]}
        assert runnable == RUNNABLE
        # the runnable ones come first; the rest say why
        flags = [t["can_run"] for t in j["titles"]]
        assert flags == sorted(flags, reverse=True)
        assert all(t["why"] for t in j["titles"] if not t["can_run"])
        assert next(t for t in j["titles"] if t["label"] == "Wonka-v03.03")["name"] == \
            "Willy Wonka & the Chocolate Factory 03.03"


def test_hidden_on_jjp_without_the_preview_switch(tmp_path, monkeypatch):
    from pinball_decryptor.core import preview
    monkeypatch.setattr(preview, "enabled", lambda feature: False)
    with web_app(tmp_path, mfr="jjp") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not tabs["modes"]["visible"]


def test_a_title_is_seeded_from_its_starter_and_checks_clean(tmp_path, preview_on):
    with web_app(tmp_path, mfr="jjp") as w:
        j = _open_wonka(w)
        assert [m["file"] for m in j["modes"]] == ["1_example.mode", "2_multiball.mode"]   # PAD-1353
        assert j["open"] == "1_example.mode"
        assert j["form"]["start"] == "switch_target_tv"
        assert j["title_cfg"]["game"] == "Wonka"
        assert j["check"]["ok"], j["check"]
        assert os.path.isfile(os.path.join(j["folder"], "1_example.mode"))
        assert j["folder"].startswith(str(tmp_path))
        # the pickers carry the port report's names; lamps include lamp groups
        assert "switch_target_tv" in j["names"]["switches"]
        assert "ls_all" in j["names"]["lamps"] and "lp_gi_tv" in j["names"]["lamps"]
        assert "se_Fanfare_Jackpot" in j["names"]["sound"]
        assert "font_wba_title" in j["names"]["font"]


def test_editing_saves_the_file_and_the_check_follows(tmp_path, preview_on):
    with web_app(tmp_path, mfr="jjp") as w:
        j = _open_wonka(w)
        path = os.path.join(j["folder"], j["open"])
        w.call("modes.jjp_set", "start", "switch_typo")
        j = _jjp(w)
        assert not j["check"]["ok"]
        assert any("switch_typo" in p for p in j["check"]["problems"])
        w.call("modes.jjp_set", "start", "switch_ramp_left_made")
        w.call("modes.jjp_set", "lamps", "lp_gi_tv ls_all")            # a lamp group is a lamp name too
        w.call("modes.jjp_set", "panel_color", "102030c0")
        w.call("modes.jjp_set", "game_modes", "end")
        w.call("modes.jjp_set", "name", "Golden Ticket")
        j = _jjp(w)
        assert j["check"]["ok"], j["check"]
        text = open(path, encoding="utf-8").read()
        assert "\r" not in text
        for line in ("start = switch_ramp_left_made", "lamps = lp_gi_tv ls_all", "panel_color = 102030c0",
                     "game_modes = end", "name = Golden Ticket"):
            assert line in text.splitlines()
        assert j["modes"][0]["name"] == "Golden Ticket"
        # an emptied key is left out, so the runtime's default applies
        w.call("modes.jjp_set", "panel_color", "")
        assert "panel_color" not in open(path, encoding="utf-8").read()
        # title.cfg: a default for every mode; the game stays the port report's
        w.call("modes.jjp_set", "title:font_title", "font_wba_mode_totals")
        w.call("modes.jjp_set", "title:game", "GunsNRoses")
        cfg = _jjp(w)["title_cfg"]
        assert cfg["font_title"] == "font_wba_mode_totals" and cfg["game"] == "Wonka"
        with pytest.raises(Exception):
            w.call("modes.jjp_set", "wobble", "1")


def test_new_duplicate_delete(tmp_path, preview_on):
    with web_app(tmp_path, mfr="jjp") as w:
        _open_wonka(w)
        fn = w.call("modes.jjp_new", "Fizzy Lifting")
        j = _jjp(w)
        assert fn == "3_fizzy_lifting.mode" and j["open"] == fn
        assert j["form"]["name"] == "Fizzy Lifting" and j["form"]["start"]      # the port's starter picks
        assert j["check"]["ok"], j["check"]
        w.call("modes.jjp_duplicate")
        j = _jjp(w)
        assert [m["name"] for m in j["modes"]] == ["PAD Mode", "PAD Multiball", "Fizzy Lifting", "Fizzy Lifting copy"]
        w.answers.append("no")
        w.call("modes.jjp_delete")
        assert len(_jjp(w)["modes"]) == 4
        w.answers.append("yes")
        w.call("modes.jjp_delete")
        j = _jjp(w)
        assert [m["name"] for m in j["modes"]] == ["PAD Mode", "PAD Multiball", "Fizzy Lifting"]
        assert j["open"] == "1_example.mode"


def test_the_title_is_remembered(tmp_path, preview_on):
    with web_app(tmp_path, mfr="jjp") as w:
        w.call("ui.select_tab", "modes")
        w.call("modes.jjp_pick_title", "Hobbit-v04.02")
        j = _jjp(w)
        assert j["label"] == "Hobbit-v04.02" and j["check"]["ok"], j["check"]
        assert w.app._settings["jjp_modes"]["label"] == "Hobbit-v04.02"
        with pytest.raises(Exception):
            w.call("modes.jjp_pick_title", "NoSuchGame-v1.0")


def test_a_title_that_cannot_run_modes_says_why(tmp_path, preview_on):
    with web_app(tmp_path, mfr="jjp") as w:
        w.call("ui.select_tab", "modes")
        w.call("modes.jjp_pick_title", "HarryPotter-v01.26")
        j = _jjp(w)
        assert not j["can_run"] and "export" in j["title"]["why"] and "modes" not in j


def test_sounds_are_heard_from_an_extract_folder(tmp_path, preview_on):
    ext = tmp_path / "wonka_extract" / "sound" / "fanfare"
    ext.mkdir(parents=True)
    (ext / "Fanfare_Jackpot.wav").write_bytes(b"RIFF....WAVE")
    with web_app(tmp_path, mfr="jjp") as w:
        j = _open_wonka(w)
        assert j["sounds"]["folder"] == "" and j["sounds"]["have"] == []
        w.call("modes.jjp_set_sounds", str(tmp_path / "wonka_extract"))
        s = _jjp(w)["sounds"]
        assert s["have"] == ["se_Fanfare_Jackpot"] and s["total"] > 2000
        assert w.call("modes.jjp_sound_path", "se_Fanfare_Jackpot") == str(ext / "Fanfare_Jackpot.wav")
        assert w.call("modes.jjp_sound_path", "se_Fanfare_GobMB_Intro") == ""


FAKE_BUILD = r'''
import os, sys
out = sys.argv[sys.argv.index("--out") + 1]
print("runtime: built against the image's glibc (55760 bytes)", flush=True)
print("[card] staged 5 file(s) into sda3.raw (e2fsck rc 0)", flush=True)
open(out, "wb").write(b"\0" * 4096)
print("iso-size 4096 written", flush=True)
'''


def test_build_runs_the_tool_and_says_where_the_iso_went(tmp_path, preview_on, monkeypatch):
    iso = tmp_path / "lib" / "Wonka-v03.03.iso"
    iso.parent.mkdir()
    iso.write_bytes(b"\0" * 1024)
    fake = tmp_path / "fake_build.py"
    fake.write_text(FAKE_BUILD)
    seen = {}

    def argv(self, iso_, out_):
        from pinball_decryptor.plugins.jjp import custom_modes as CM
        args = CM.build_args(iso_, self._jjp_label, out_, lambda p: p)
        seen["args"] = args
        return [sys.executable, str(fake)] + args[1:]

    from pinball_decryptor.webui import modes_jjp
    monkeypatch.setattr(modes_jjp.JjpModesMixin, "jjp_build_argv", argv)
    with web_app(tmp_path, mfr="jjp") as w:
        _open_wonka(w)
        w.call("modes.jjp_set_iso", str(iso))
        b = _jjp(w)["build"]
        assert b["iso"] == str(iso) and b["out"].endswith("Wonka-v03.03.modes.iso")
        out = str(tmp_path / "Wonka-v03.03.modes.iso")
        w.call("modes.jjp_set_out", out)
        w.call("modes.jjp_build")
        assert _wait(w, lambda: _jjp(w)["build"].get("done"))
        b = _jjp(w)["build"]
        assert b["ok"], b
        assert b["msg"].startswith("Built Wonka-v03.03.modes.iso")
        assert os.path.getsize(out) == 4096
        a = seen["args"]
        assert a[:2] == ["tools/jjp_emu/mkjjpmodes.py", "build"] and "--so" not in a and "--overwrite" in a
        assert a[a.index("--modes") + 1] == _jjp(w)["folder"]
        assert a[a.index("--port") + 1].endswith(os.path.join("ports", "Wonka-v03.03.json"))


def test_build_refuses_with_problems_or_no_iso(tmp_path, preview_on):
    with web_app(tmp_path, mfr="jjp") as w:
        _open_wonka(w)
        w.call("modes.jjp_set_iso", str(tmp_path / "missing.iso"))
        with pytest.raises(Exception, match="stock install ISO"):
            w.call("modes.jjp_build")
        iso = tmp_path / "Wonka-v03.03.iso"
        iso.write_bytes(b"\0")
        w.call("modes.jjp_set_iso", str(iso))
        w.call("modes.jjp_set", "start", "switch_typo")
        with pytest.raises(Exception, match="problem"):
            w.call("modes.jjp_build")


def test_the_default_output_is_never_the_image_library(tmp_path, preview_on):
    with web_app(tmp_path, mfr="jjp") as w:
        svc = _svc(w)
        d = svc._jjp_out_folder(r"D:\Pinball\images\JJP\Wonka-v03.03.iso")
        assert not d.replace("\\", "/").lower().startswith("d:/pinball/images")


def test_stern_keeps_its_own_tab(tmp_path, preview_on):
    with web_app(tmp_path, mfr="stern") as w:
        assert not _jjp(w).get("on")
        assert _svc(w).rail_needs() is None


def test_every_mode_key_is_on_the_form_once():
    from pinball_decryptor.plugins.jjp import custom_modes as CM
    keys = [k for _g, ks in CM.FORM_GROUPS for k in ks]
    assert sorted(keys) == sorted(CM.mk().KEYS)
    assert set(CM.TITLE_FORM) <= set(CM.mk().KEYS) | set(CM.mk().TITLE_KEYS)
    assert all(k in CM.LABELS for k in keys + list(CM.TITLE_FORM))


def test_a_live_report_is_not_a_title():
    # PAD-1351 keeps <title>.live.json (a running game's read) beside the port reports
    from pinball_decryptor.plugins.jjp import custom_modes as CM
    labels = [t["label"] for t in CM.titles()]
    assert not [l for l in labels if l.endswith(".live")]
    assert len(labels) == len(set(labels))


def test_balls_and_coils_from_the_form(tmp_path, preview_on):
    """PAD-1353: the Balls and Coils groups write the runtime's keys, and a hold needs the title's coil_holds."""
    with web_app(tmp_path, mfr="jjp") as w:
        j = _open_wonka(w)
        groups = {g["title"]: g["keys"] for g in j["groups"]} if j.get("groups") else dict(
            (g, list(ks)) for g, ks in CM.FORM_GROUPS)
        assert "multiball" in groups["Balls"] and "coil_hold" in groups["Coils"]
        path = os.path.join(j["folder"], j["open"])
        w.call("modes.jjp_set", "multiball", "3 10")
        w.call("modes.jjp_set", "coil_shot", "coil_knocker")
        w.call("modes.jjp_set", "coil_hold", "coil_magnet_1 1500 8")
        j = _jjp(w)
        assert any("coil_holds = on" in p for p in j["check"]["problems"]), j["check"]
        w.call("modes.jjp_set", "title:coil_holds", "on")
        j = _jjp(w)
        assert j["check"]["ok"], j["check"]
        assert j["title_cfg"]["coil_holds"] == "on"
        lines = open(path, encoding="utf-8").read().splitlines()
        for line in ("multiball = 3 10", "coil_shot = coil_knocker", "coil_hold = coil_magnet_1 1500 8"):
            assert line in lines
        w.call("modes.jjp_set", "coil_shot", "coil_flipper_power_left")
        assert any("coil_flipper_power_left" in p for p in _jjp(w)["check"]["problems"])
