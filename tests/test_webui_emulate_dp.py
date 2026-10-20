"""The web Emulate DP tab (webui/tabs/emulate_dp.py, PAD-263), without ever
touching a rig: the harness sets PAD_UI_NO_RIG, conftest points the rig dir
at an empty directory, and the tests that need more stub it."""

import time

import pytest

from tests.webui_harness import web_app

NS = "emulate_dp"
IMG = r"D:\Pinball\TBL\justin_img\TBL_justin_113_v10.img"
ZIP = r"D:\Pinball\images\Dutch Pinball\TBL-v1.15.zip"


def _svc(w):
    return w.window.service(NS)


@pytest.fixture(autouse=True)
def _no_theme_probe(monkeypatch):
    from pinball_decryptor.webui import theme
    monkeypatch.setattr(theme, "detect_system_theme", lambda: "light")


@pytest.fixture
def rig(monkeypatch):
    from pinball_decryptor.webui import emulate_dp_core as core
    monkeypatch.setattr(core, "rig_available", lambda: True)
    monkeypatch.setattr(core, "platform_ok", lambda: True)


# ------------------------------------------------------------------ gating
def test_dp_shows_the_tab_with_its_idle_state(rig, tmp_path):
    with web_app(tmp_path, mfr="dp") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs[NS]["visible"] and tabs[NS]["label"] == "Emulate"
        for other in ("emulate", "emulate_jjp", "emulate_spike1", "emulate_bof"):
            assert not tabs[other]["visible"]
        s = w.state(NS)
        assert s["go_label"] == "Start" and s["go_enabled"]
        assert s["note"] == ""
        assert [c["label"] for c in s["cells"]] == [
            "Game", "Version", "Switches", "Window", "Memory", "Uptime"]


@pytest.mark.parametrize("mfr", ["stern", "jjp", "bof"])
def test_other_manufacturers_do_not_get_the_dp_tab(tmp_path, mfr):
    with web_app(tmp_path, mfr=mfr) as w:
        if mfr not in {m.key for m in w.window.manufacturers}:
            pytest.skip("no %s plugin" % mfr)
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not tabs[NS]["visible"]


def test_a_missing_rig_says_so_and_greys_start(tmp_path):
    with web_app(tmp_path, mfr="dp") as w:
        s = w.state(NS)
        assert not s["go_enabled"] and not s["rig_ok"]
        assert "tools/dp_emu" in s["note"]


def test_off_windows_it_says_windows_only(monkeypatch, tmp_path):
    from pinball_decryptor.webui import emulate_dp_core as core
    monkeypatch.setattr(core, "rig_available", lambda: True)
    monkeypatch.setattr(core, "platform_ok", lambda: False)
    with web_app(tmp_path, mfr="dp") as w:
        s = w.state(NS)
        assert not s["go_enabled"] and "Windows only" in s["note"]


def test_the_repo_rig_is_complete():
    """rig_available() checks the scripts the tab runs; the repo carries
    every one of them."""
    import os
    from pinball_decryptor.webui import emulate_dp_core as core
    for s in ("watch.sh", "stop.sh", "status.sh", "ctl.sh", "cancel.sh",
              "dpinput.c", "dppf.py", "dpswitches.py", "dpctl.py",
              "prepare.py", "run_game.sh", "killgame.sh", "dppath.sh"):
        assert os.path.isfile(os.path.join(core.DEFAULT_RIG_DIR, s)), s
    for s in ("index.html", "dp.js", "dp.css"):
        assert os.path.isfile(os.path.join(core.DEFAULT_RIG_DIR, "dppage", s)), s


# ------------------------------------------------------------ the two files
def test_the_vars_are_the_windows_exports(tmp_path):
    with web_app(tmp_path, mfr="dp") as w:
        assert w.window.dp_emulate_img_var is _svc(w).dp_emulate_img_var
        assert w.window.dp_emulate_zip_var is _svc(w).dp_emulate_zip_var
        w.call("ui.set", NS, "img", IMG)
        w.call("ui.set", NS, "zip", ZIP)
        assert w.window.dp_emulate_img_var.get() == IMG
        assert w.window.dp_emulate_zip_var.get() == ZIP


def test_browse_asks_for_an_image_then_an_update(tmp_path):
    with web_app(tmp_path, mfr="dp") as w:
        img = tmp_path / "tbl.img"
        img.write_bytes(b"")
        w.answers.append(str(img))
        assert w.call(NS + ".browse")
        assert ["Disk image", "*.img *.bin *.raw"] in w.asked[-1]["filetypes"]
        assert w.window.dp_emulate_img_var.get() == str(img)
        z = tmp_path / "TBL-v1.15.zip"
        z.write_bytes(b"")
        w.answers.append(str(z))
        assert w.call(NS + ".browse_zip")
        assert ["Dutch Pinball update", "*.zip"] in w.asked[-1]["filetypes"]
        assert w.window.dp_emulate_zip_var.get() == str(z)


def test_the_select_card_pick_fills_whichever_field_it_fits(tmp_path):
    with web_app(tmp_path, mfr="dp") as w:
        svc = _svc(w)
        assert svc.img_path() == "" and svc.zip_path() == ""
        w.window.extract_input_var.set(IMG)
        assert svc.img_path() == IMG and svc.zip_path() == ""
        w.window.extract_input_var.set(ZIP)
        assert svc.img_path() == "" and svc.zip_path() == ZIP
        # its own fields win
        w.window.dp_emulate_zip_var.set(r"C:\mods\tbl_mod.zip")
        assert svc.zip_path() == r"C:\mods\tbl_mod.zip"


def test_start_without_an_image_asks_and_runs_nothing(rig, monkeypatch, tmp_path):
    ran = []
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: ran.append(a))
    with web_app(tmp_path, mfr="dp") as w:
        # an update alone is not enough: the base assets are on the image
        z = tmp_path / "TBL-v1.15.zip"
        z.write_bytes(b"x")
        w.window.dp_emulate_zip_var.set(str(z))
        w.call(NS + ".toggle")
        assert ran == []
        assert not _svc(w)._busy


def test_start_runs_watch_with_the_image_then_the_update(rig, monkeypatch, tmp_path):
    from pinball_decryptor.webui import emulate_dp_core as core
    from pinball_decryptor.webui.tabs import emulate_dp as tab
    from pinball_decryptor.webui import emulate_jjp_common as common
    monkeypatch.setattr(tab, "rig_off", lambda: False)
    monkeypatch.setattr(common, "rig_off", lambda: False)
    monkeypatch.setattr(tab, "load_audio_ctl", lambda: (1.0, True))
    seen = {}
    monkeypatch.setattr(core, "rig_cmd_root",
                        lambda *a, **k: seen.update(args=a, env=k.get("env")) or ["x"])
    with web_app(tmp_path, mfr="dp") as w:
        svc = _svc(w)
        svc._run_streaming = lambda cmd, timeout=0, on_line=None: 0
        svc._open_switches = lambda info=None: True
        img = tmp_path / "tbl.img"
        img.write_bytes(b"x")
        z = tmp_path / "TBL-v1.15.zip"
        z.write_bytes(b"x")
        w.window.dp_emulate_img_var.set(str(img))
        w.window.dp_emulate_zip_var.set(str(z))
        w.call(NS + ".toggle")
        end = time.time() + 5
        while "args" not in seen and time.time() < end:
            time.sleep(0.02)
        assert seen["args"][0] == "watch.sh"
        assert seen["args"][1].endswith("tbl.img")
        assert seen["args"][2].endswith("TBL-v1.15.zip")
        assert "PAD_VISIBLE=1" in seen["env"] and "PAD_AUDIO=0" in seen["env"]


def test_showing_the_tab_puts_up_the_dp_ladder(tmp_path):
    with web_app(tmp_path, mfr="dp") as w:
        w.call("ui.select_tab", NS)
        f = w.state("shell")["footer"]
        assert f["phases"] == ["Prepare", "Game", "Ready"]
        assert f["mode"] == "emulate"


def test_launch_lines_move_the_footer(rig, tmp_path):
    with web_app(tmp_path, mfr="dp") as w:
        w.call("ui.select_tab", NS)
        svc = _svc(w)
        seen = []
        svc._footer = lambda kind, pct=None, text="": seen.append((kind, pct))
        for line in ("== Prepare ==", "progress 40", "== Game ==", "== Ready =="):
            svc._footer_line(line)
        assert seen == [("copy", 0), ("copy", 40), ("boot", None), ("run", None)]


# ------------------------------------------------------------ the poll
RUNNING = {"wsl": "1", "running": "1", "title": "The Big Lebowski Pinball",
           "version": "1.15", "build": "TBL_justin_113_v10+TBL-v1.15",
           "pid": "42", "rss_kb": str(int(1.4 * 1048576)), "uptime_s": "75",
           "display": ":0", "visible": "1", "window": "1366x512",
           "switches": "80", "slot": "0",
           "switches_json": "/var/tmp/pad_dp/rig0/switches.json"}


def test_apply_running_fills_the_grid(rig, tmp_path):
    with web_app(tmp_path, mfr="dp") as w:
        _svc(w)._apply(dict(RUNNING))
        s = w.state(NS)
        assert s["up"] and s["go_label"] == "Stop"
        assert s["state_label"] == "Running" and s["tone"] == "ok"
        assert s["game"] == "The Big Lebowski"
        v = {c["label"]: c["value"] for c in s["cells"]}
        assert v == {"Game": "The Big Lebowski", "Version": "1.15",
                     "Switches": "80", "Window": "1366 × 512",
                     "Memory": "1.4 GB", "Uptime": "1:15"}


def test_stopped(rig, tmp_path):
    with web_app(tmp_path, mfr="dp") as w:
        _svc(w)._apply({"wsl": "1", "running": "0"})
        s = w.state(NS)
        assert not s["up"] and s["state_label"] == "Stopped"
        assert s["go_label"] == "Start"
        assert {c["value"] for c in s["cells"]} == {"—"}


def test_wsl_not_answering_warns(rig, tmp_path):
    with web_app(tmp_path, mfr="dp") as w:
        _svc(w)._apply({})
        _svc(w)._apply({"wsl": "0"})
        s = w.state(NS)
        assert s["state_label"] == "WSL not answering" and s["tone"] == "warn"


# ------------------------------------------------------- the switch window
def test_the_switch_window_command(rig, monkeypatch, tmp_path):
    """dppf.py on the app's Windows Python, told the slot, the title, the
    distro, and the rig's switch table through the distro's share."""
    from pinball_decryptor.webui import emulate_dp_core as core
    from pinball_decryptor.webui.tabs import emulate_dp as tab
    monkeypatch.setattr(tab, "windows_python", lambda: "pythonw.exe")
    monkeypatch.setattr(core, "rig_distro", lambda: "PAD-Runtime")
    with web_app(tmp_path, mfr="dp") as w:
        cmd = _svc(w)._switch_window_cmd(dict(RUNNING))
        assert cmd[0] == "pythonw.exe" and cmd[1].endswith("dppf.py")
        assert cmd[cmd.index("--slot") + 1] == "0"
        assert cmd[cmd.index("--title") + 1] == "The Big Lebowski"
        assert cmd[cmd.index("--distro") + 1] == "PAD-Runtime"
        assert cmd[cmd.index("--table") + 1] == \
            '\\\\wsl.localhost\\PAD-Runtime\\var\\tmp\\pad_dp\\rig0\\switches.json'
        assert _svc(w)._switch_window_cmd({"running": "0"}) is None


def test_switches_button_needs_a_running_game(rig, tmp_path):
    with web_app(tmp_path, mfr="dp") as w:
        assert not w.call(NS + ".switches")


def test_quit_stops_only_a_run_this_app_started(rig, monkeypatch, tmp_path):
    import subprocess
    ran = []
    from pinball_decryptor.webui import emulate_dp_core as core
    # only the stop counts: the tab's own status.sh poll may run meanwhile on a busy machine
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: ran.append(a) if "stop.sh" in " ".join(a[0]) else None)
    monkeypatch.setattr(core, "rig_cmd_root",
                        lambda *a, **k: ["bash"] + list(a))
    monkeypatch.setattr(
        "pinball_decryptor.webui.tabs.emulate_dp.rig_off", lambda: False)
    with web_app(tmp_path, mfr="dp") as w:
        svc = _svc(w)
        svc._last_up = True
        svc._started_here = False
        svc.emulate_shutdown()
        assert ran == []
        svc._started_here = True
        svc.emulate_shutdown()
        assert len(ran) == 1 and "stop.sh" in " ".join(ran[0][0])


def test_while_starting_the_button_is_cancel(rig, monkeypatch, tmp_path):
    import subprocess
    from pinball_decryptor.webui import emulate_dp_core as core
    ran = []
    monkeypatch.setattr(core, "rig_cmd_root",
                        lambda *a, **k: ["bash"] + list(a))
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **k: ran.append(cmd) or
                        subprocess.CompletedProcess(cmd, 0, b"cancelled=1", b""))
    with web_app(tmp_path, mfr="dp") as w:
        svc = _svc(w)
        svc._busy = True
        svc._starting = True
        svc._set_go("Cancel", True)
        s = w.state(NS)
        assert s["go_label"] == "Cancel" and s["go_enabled"] and s["starting"]
        assert w.call(NS + ".toggle")
        assert w.state(NS)["go_label"] == "Canceling…"
        # the tab's own status poll may run too: look for the cancel
        end = time.time() + 5
        while not any(c[-1] == "cancel.sh" for c in ran) and time.time() < end:
            time.sleep(0.02)
        assert any(c[-1] == "cancel.sh" for c in ran)
        assert not w.call(NS + ".cancel")


def test_the_switch_page_model(tmp_path):
    """dppf.page_model: groups, keys the page listens for, the coin door."""
    import importlib.util
    from pinball_decryptor.webui import emulate_dp_core as core
    import os
    import sys
    spec = importlib.util.spec_from_file_location(
        "dppf", os.path.join(core.DEFAULT_RIG_DIR, "dppf.py"))
    sys.path.insert(0, os.path.join(os.path.dirname(core.DEFAULT_RIG_DIR), "spike2_emu"))
    try:
        dppf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dppf)
    finally:
        sys.path.pop(0)
    table = {"switches": [
        {"n": 0, "name": "trough1", "title": "Trough 1", "nc": True, "x": 1, "y": 2, "key": ""},
        {"n": 1, "name": "leftSling", "title": "Left Slingshot", "x": 5, "y": 6, "key": ""},
        {"n": 2, "name": "startButton", "title": "Start Button", "x": None, "y": None, "key": "1"},
        {"n": 3, "name": "flipperLwL", "title": "Left Flipper", "x": None, "y": None, "key": "n"},
        {"n": 4, "name": "coinDoor", "title": "Coin Door", "x": None, "y": None, "key": "c"},
    ]}
    m = dppf.page_model(table, "The Big Lebowski")
    rows = {r["name"]: r for r in m["switches"]}
    assert [r["group"] for r in m["switches"]] == [
        "Cabinet", "Cabinet", "Cabinet", "Playfield", "Trough"]
    assert rows["startButton"]["codes"] == ["Digit1", "Numpad1"]
    assert rows["flipperLwL"]["codes"] == ["KeyN"] and rows["flipperLwL"]["hold"]
    assert rows["trough1"]["opto"] and rows["trough1"]["placed"]
    assert not rows["startButton"]["placed"]
    assert m["coin_door"] == 4


def test_a_game_that_ends_by_itself_says_how(rig, tmp_path):
    """Alice once ended a minute into a game with nothing in its output; the
    rig now records the exit status and the tab logs what it means."""
    from pinball_decryptor.webui import emulate_dp_core as core
    assert "killed from outside" in core.ended_text("137")
    assert "aborted" in core.ended_text("134")
    assert "quit by itself" in core.ended_text("0")
    assert core.ended_text("") == "the game ended."
    with web_app(tmp_path, mfr="dp") as w:
        svc = _svc(w)
        logged = []
        svc._log = logged.append
        svc._apply(dict(RUNNING))
        svc._apply({"wsl": "1", "running": "0", "last_exit": "137"})
        assert logged and "killed from outside" in logged[-1]
        # our own Stop is not "ended by itself"
        logged.clear()
        svc._apply(dict(RUNNING))
        svc._busy = True
        svc._apply({"wsl": "1", "running": "0", "last_exit": "137"})
        assert logged == []
