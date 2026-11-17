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
from pinball_decryptor.plugins.jjp import custom_modes as CM

#: every title whose port report can run modes (MODES.md "Titles")
RUNNABLE = {"GunsNRoses-v03.03", "CHAKAs_LOTLJ_V1.0_GNR_LE_3.03", "EltonJohn-v02.03", "Godfather-v02.03",
            "Pirates-v01.01", "Wonka-v03.03", "DialedIn-v02.02", "Hobbit-v04.02", "ToyStory-v02.04",
            "WizardOfOz-v08.02"}      # PAD-1365: the proc engine (no Mode class)


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


def test_wizard_of_oz_runs_modes_and_offers_pause_not_hold(tmp_path, preview_on):
    """PAD-1365: The Wizard of Oz (older engine, no Mode class) opens its starter modes; with no
    Mode class to hold off, the form offers pause as the default and no hold, and its game
    modes for start_after are its mode procs."""
    with web_app(tmp_path, mfr="jjp") as w:
        w.call("ui.select_tab", "modes")
        w.call("modes.jjp_pick_title", "WizardOfOz-v08.02")
        j = _jjp(w)
        assert j["can_run"] and j["modes"]
        gm = j["fields"]["game_modes"]
        assert gm["default"] == "pause" and "hold" not in gm["choices"] and "end" in gm["choices"]
        w.call("modes.jjp_pick_title", "Wonka-v03.03")
        gm = _jjp(w)["fields"]["game_modes"]
        assert gm["default"] == "hold" and "hold" in gm["choices"]
    from pinball_decryptor.plugins.jjp import custom_modes as CM
    after = CM.names_for(CM.load_port("WizardOfOz-v08.02"), "after")
    assert "ecmb_run_proc" in after and "twister_mode_proc_run" in after


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
    assert sorted(keys + list(CM.NOT_ON_FORM)) == sorted(CM.mk().KEYS)
    assert set(CM.TITLE_FORM) <= set(CM.mk().KEYS) | set(CM.mk().TITLE_KEYS)
    assert all(k in CM.LABELS for k in keys + list(CM.TITLE_FORM))


# ------------------------------------------------------------------ Write to USB stick (PAD-1375)
FAKE_RUNTIME = r'''
import sys
out = sys.argv[sys.argv.index("--out") + 1]
print("runtime: built against the image's glibc (69040 bytes)", flush=True)
open(out, "wb").write(b"\x7fELF" + b"\x01" * 60)
'''


def _fake_runtime(tmp_path, monkeypatch):
    fake = tmp_path / "fake_runtime.py"
    fake.write_text(FAKE_RUNTIME)
    calls = []

    def argv(self, iso_, out_):
        from pinball_decryptor.plugins.jjp import custom_modes as CM
        args = CM.runtime_args(iso_, out_, lambda p: p)
        calls.append(args)
        return [sys.executable, str(fake)] + args[1:]

    from pinball_decryptor.webui import modes_jjp
    monkeypatch.setattr(modes_jjp.JjpModesMixin, "jjp_runtime_argv", argv)
    return calls


def _stock_iso(tmp_path):
    iso = tmp_path / "lib" / "Wonka-v03.03.iso"
    iso.parent.mkdir(exist_ok=True)
    iso.write_bytes(b"\0" * 1024)
    return iso


def test_stick_builds_the_runtime_once_and_writes_the_hot_fix(tmp_path, preview_on, monkeypatch):
    calls = _fake_runtime(tmp_path, monkeypatch)
    iso = _stock_iso(tmp_path)
    stick = tmp_path / "E"
    stick.mkdir()
    with web_app(tmp_path, mfr="jjp") as w:
        _open_wonka(w)
        w.call("modes.jjp_set_iso", str(iso))
        w.call("modes.jjp_set_stick", str(stick))
        k = _jjp(w)["stick"]
        assert k["path"] == str(stick) and k["action"] == "install" and not k["runtime_ready"]
        assert any("LEFT FLIPPER" in s for s in k["steps"])
        w.call("modes.jjp_write_stick")
        assert _wait(w, lambda: _jjp(w)["stick"].get("done"))
        k = _jjp(w)["stick"]
        assert k["ok"], k
        n = len(_jjp(w)["modes"])                   # the title's starter modes
        assert n >= 1 and k["msg"] == "Written: the stick installs %d mode(s)." % n
        assert len(list((stick / "hotfix" / "padmodes" / "modes").glob("*.mode"))) == n
        assert k["owner"] == "pad" and k["runtime_ready"]
        a = calls[0]
        assert a[:2] == ["tools/jjp_emu/mkjjpmodes.py", "runtime"] and a[a.index("--iso") + 1] == str(iso)
        hot = stick / "hotfix"
        assert (hot / "padmodes" / "jjpmodes.so").read_bytes() == b"\x7fELF" + b"\x01" * 60
        assert (hot / "padmodes" / "modes" / "title.cfg").is_file()
        runme = (hot / "runme.sh").read_text()
        assert "ACTION=install" in runme or "install" in runme
        assert (stick / "PADMODES_README.txt").is_file()
        # the second stick reuses the runtime and replaces our own hot fix
        w.call("modes.jjp_write_stick")
        assert _wait(w, lambda: _jjp(w)["stick"].get("done"))
        assert _jjp(w)["stick"]["ok"] and len(calls) == 1
        # the stick is remembered
        assert svc_settings(w)["stick"] == str(stick)


def svc_settings(w):
    return _svc(w)._jjp_settings()


def test_an_off_stick_needs_no_iso_or_runtime(tmp_path, preview_on, monkeypatch):
    calls = _fake_runtime(tmp_path, monkeypatch)
    stick = tmp_path / "F"
    stick.mkdir()
    with web_app(tmp_path, mfr="jjp") as w:
        _open_wonka(w)
        w.call("modes.jjp_set_iso", "")
        w.call("modes.jjp_set_stick", str(stick))
        w.call("modes.jjp_stick_action", "off")
        assert _jjp(w)["stick"]["action"] == "off"
        w.call("modes.jjp_write_stick")
        assert _wait(w, lambda: _jjp(w)["stick"].get("done"))
        k = _jjp(w)["stick"]
        assert k["ok"] and k["msg"] == "Written: the stick turns the modes off.", k
        runme = (stick / "hotfix" / "runme.sh").read_text()
        assert "Wonka" in runme                     # only runs on the game it was written for
        assert not (stick / "hotfix" / "padmodes").exists() and calls == []
        with pytest.raises(Exception, match="unknown stick action"):
            w.call("modes.jjp_stick_action", "format")


def test_install_stick_waits_for_the_stock_iso_and_a_clean_check(tmp_path, preview_on, monkeypatch):
    _fake_runtime(tmp_path, monkeypatch)
    stick = tmp_path / "G"
    stick.mkdir()
    with web_app(tmp_path, mfr="jjp") as w:
        _open_wonka(w)
        w.call("modes.jjp_set_iso", str(tmp_path / "missing.iso"))
        w.call("modes.jjp_set_stick", str(stick))
        with pytest.raises(Exception, match="stock install ISO"):
            w.call("modes.jjp_write_stick")
        w.call("modes.jjp_set_iso", str(_stock_iso(tmp_path)))
        w.call("modes.jjp_set", "start", "switch_typo")
        with pytest.raises(Exception, match="problem"):
            w.call("modes.jjp_write_stick")
        assert not (stick / "hotfix").exists()


def test_a_stick_with_someone_elses_hot_fix_is_never_overwritten(tmp_path, preview_on, monkeypatch):
    _fake_runtime(tmp_path, monkeypatch)
    stick = tmp_path / "H"
    (stick / "hotfix").mkdir(parents=True)
    (stick / "hotfix" / "runme.sh").write_text("#!/bin/sh\necho a JJP field fix\n")
    with web_app(tmp_path, mfr="jjp") as w:
        _open_wonka(w)
        w.call("modes.jjp_set_stick", str(stick))
        assert _jjp(w)["stick"]["owner"] == "other"
        with pytest.raises(Exception, match="already has a hot fix"):
            w.call("modes.jjp_write_stick")
        assert (stick / "hotfix" / "runme.sh").read_text() == "#!/bin/sh\necho a JJP field fix\n"


def test_the_stick_defaults_to_a_removable_drive(tmp_path, preview_on, monkeypatch):
    from pinball_decryptor.plugins.jjp import custom_modes as CM
    usb = tmp_path / "usb"
    usb.mkdir()
    monkeypatch.setattr(CM, "removable_drives", lambda: [str(usb)])
    with web_app(tmp_path, mfr="jjp") as w:
        _open_wonka(w)
        k = _jjp(w)["stick"]
        assert k["path"] == str(usb) and k["drives"] == [str(usb)]
        # the stick's file system is asked only of a removable drive, never of a folder on C:
        asked = []
        monkeypatch.setattr(CM, "stick_filesystem", lambda p: asked.append(p) or "NTFS")
        monkeypatch.setattr(CM, "removable_drives", lambda: ["Q:\\"])
        w.call("modes.jjp_set_stick", str(usb))
        assert _jjp(w)["stick"]["fs"] == "" and asked == []
        monkeypatch.setattr(CM, "removable_drives", lambda: [str(usb)])
        # a remembered stick that is gone falls back to the drive there now
        svc_settings(w)["stick"] = str(tmp_path / "gone")
        w.call("modes.jjp_stick_refresh")
        assert _jjp(w)["stick"]["path"] == str(usb)


def test_the_runtime_is_kept_per_iso(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.jjp import custom_modes as CM
    monkeypatch.setenv("PAD_JJP_MODES_DIR", str(tmp_path / "m"))
    a, b = tmp_path / "Wonka-v03.03.iso", tmp_path / "GunsNRoses-v03.03.iso"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    pa = CM.runtime_path(str(a))
    assert pa == CM.runtime_path(str(a)) and pa != CM.runtime_path(str(b))
    assert os.path.basename(pa).startswith("Wonka-v03.03-") and pa.endswith(".so")
    a.write_bytes(b"a longer iso")                  # a different ISO at the same path builds again
    assert CM.runtime_path(str(a)) != pa


def test_a_live_report_is_not_a_title():
    # PAD-1351 keeps <title>.live.json (a running game's read) beside the port reports
    from pinball_decryptor.plugins.jjp import custom_modes as CM
    labels = [t["label"] for t in CM.titles()]
    assert not [l for l in labels if l.endswith(".live")]
    assert len(labels) == len(set(labels))


def test_a_modes_own_media_files_are_offered_and_check(tmp_path, preview_on):
    """PAD-1352: files of the person's own in the mode folder are what the media keys pick from;
    a sound key offers them beside the game's own sounds."""
    with web_app(tmp_path, mfr="jjp") as w:
        j = _open_wonka(w)
        for fn in ("start.wav", "logo.png", "clip.webm", "notes.txt"):
            open(os.path.join(j["folder"], fn), "wb").close()
        w.call("modes.jjp_pick_title", "Wonka-v03.03")
        j = _jjp(w)
        names = j["names"]
        assert names["sound_or_file"][0] == "start.wav" and "se_Fanfare_Jackpot" in names["sound_or_file"]
        assert (names["sound_file"], names["picture_file"], names["video_file"]) == (["start.wav"], ["logo.png"], ["clip.webm"])
        f = j["fields"]
        assert f["sound_start"]["kind"] == "sound_or_file" and f["picture"]["kind"] == "picture_file"
        assert f["video_loop"]["kind"] == "choice" and f["video_loop"]["choices"] == ["yes", "no"]
        assert any(g["title"] == "Picture and video" for g in j["groups"])
        w.call("modes.jjp_set", "sound_start", "start.wav")
        w.call("modes.jjp_set", "picture", "logo.png")
        w.call("modes.jjp_set", "video", "clip.webm")
        w.call("modes.jjp_set", "video_at", "25 4 50 58")
        assert _jjp(w)["check"]["ok"], _jjp(w)["check"]
        w.call("modes.jjp_set", "video", "gone.webm")
        assert any("no gone.webm in the mode folder" in p for p in _jjp(w)["check"]["problems"])


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


def test_coil_pickers_offer_the_ports_coils(tmp_path, preview_on):
    """PAD-1376: the Coils pickers list the title's port-report coils a mode may pulse, and hold."""
    with web_app(tmp_path, mfr="jjp") as w:
        j = _open_wonka(w)
        port = CM.load_port("Wonka-v03.03")
        coils = {c["symbol"]: c for c in port["coils"]}
        pulse, hold = j["names"]["coil_pulse"], j["names"]["coil_hold"]
        assert pulse == [s for s, c in coils.items() if c["pulse"]] and len(pulse) == 24
        assert hold == [s for s, c in coils.items() if c["hold"]] and len(hold) == 14
        assert "coil_knocker" in pulse and "coil_knocker" not in hold
        assert "coil_magnet_left_lane" in hold
        assert "coil_autolaunch" not in pulse and "coil_flipper_power_left" not in pulse
        for k, kind in (("multiball", "multiball"), ("ball_save", "ball_save"), ("add_ball", "add_ball"),
                        ("coil_start", "coil_pulse"), ("coil_hold", "coil_hold"), ("coil_hold_on", "hold_on")):
            assert j["fields"][k]["kind"] == kind      # the page gives each its own inputs by these
    for label in CM.titles():
        if label["can_run"]:
            p = CM.load_port(label["label"]) or {}
            assert CM.names_for(p, "coil_pulse"), label["label"]     # every runnable title has coils to pick


def test_a_mode_started_by_start_rules_says_so_in_the_list(tmp_path, preview_on):
    """PAD-1377: a mode needs no start switch now; the list says what starts it."""
    with web_app(tmp_path, mfr="jjp") as w:
        j = _open_wonka(w)
        first = j["open"]
        assert j["modes"][0]["starts"] == j["modes"][0]["start"]           # the starter's switch
        w.call("modes.jjp_set", "start", "")
        j = _jjp(w)
        assert not j["check"]["ok"] and j["modes"][0]["starts"] == ""     # nothing starts it
        w.call("modes.jjp_set", "start_on", "ball_start multiball_end")
        w.call("modes.jjp_set", "start_after", "any")
        w.call("modes.jjp_set", "start_combo", "switch_ramp_left_made switch_ramp_center_made")
        w.call("modes.jjp_set", "start_once", "ball")
        j = _jjp(w)
        assert j["check"]["ok"], j["check"]
        row = [m for m in j["modes"] if m["file"] == first][0]
        assert row["start"] == ""
        assert row["starts"] == ("on ball_start multiball_end; after any; "
                                 "combo switch_ramp_left_made switch_ramp_center_made")
        text = open(os.path.join(j["folder"], first), encoding="utf-8").read().splitlines()
        assert "start_on = ball_start multiball_end" in text and "start_once = ball" in text


def test_the_tips_tell_the_start_rules():
    from pinball_decryptor.webui import help_content as H
    making = dict(H.JJP_MODES_HELP)["Making a mode"][0]
    for label in ("Starts on a game event", "Starts after a game mode ends", "Starts at a score",
                  "Starts on a combo", "Combo seconds", "Start count resets", "Starts at most once a"):
        assert label in making, label
        assert label.split(" (")[0] in " ".join(CM.LABELS.values()), label     # the form's own words
