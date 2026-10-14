"""The web Emulate BoF tab (webui/tabs/emulate_bof.py, PAD-257), without
ever touching a rig: the harness sets PAD_UI_NO_RIG, conftest points the rig
dir at an empty directory, and the tests that need more stub it."""

import json
import time

import pytest

from tests.webui_harness import web_app

NS = "emulate_bof"


def _svc(w):
    return w.window.service(NS)


@pytest.fixture(autouse=True)
def _no_theme_probe(monkeypatch):
    """On macOS the app asks ``defaults read -g AppleInterfaceStyle`` for the
    theme through subprocess, which the tests here spy on to see what the tab
    runs: answer the theme without running anything."""
    from pinball_decryptor.webui import theme
    monkeypatch.setattr(theme, "detect_system_theme", lambda: "light")


@pytest.fixture
def rig(monkeypatch):
    from pinball_decryptor.webui import emulate_bof_core as core
    monkeypatch.setattr(core, "rig_available", lambda: True)
    monkeypatch.setattr(core, "platform_ok", lambda: True)


@pytest.fixture
def real_profiles(monkeypatch):
    """The repo's own profiles (source files only - nothing is run)."""
    from pinball_decryptor.webui import emulate_bof_core as core
    monkeypatch.setenv("PAD_BOF_EMU_DIR", core.DEFAULT_RIG_DIR)


# ------------------------------------------------------------------ gating
def test_bof_shows_the_tab_with_its_idle_state(rig, tmp_path):
    with web_app(tmp_path, mfr="bof") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs[NS]["visible"] and tabs[NS]["label"] == "Emulate"
        for other in ("emulate", "emulate_jjp", "emulate_spike1"):
            assert not tabs[other]["visible"]
        s = w.state(NS)
        assert s["go_label"] == "Start" and s["go_enabled"]
        assert s["note"] == ""
        assert [c["label"] for c in s["cells"]] == [
            "Game", "Boards", "Balls", "LEDs lit", "Drivers set up",
            "Memory", "Uptime"]
        assert _svc(w)._poll_job is None


@pytest.mark.parametrize("mfr", ["stern", "jjp", "spooky"])
def test_other_manufacturers_do_not_get_the_bof_tab(tmp_path, mfr):
    with web_app(tmp_path, mfr=mfr) as w:
        if mfr not in {m.key for m in w.window.manufacturers}:
            pytest.skip("no %s plugin" % mfr)
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not tabs[NS]["visible"]


def test_a_missing_rig_says_so_and_greys_start(tmp_path):
    with web_app(tmp_path, mfr="bof") as w:
        s = w.state(NS)
        assert not s["go_enabled"] and not s["rig_ok"]
        assert "tools/bof_emu" in s["note"]


def test_off_windows_it_says_windows_only(monkeypatch, tmp_path):
    from pinball_decryptor.webui import emulate_bof_core as core
    monkeypatch.setattr(core, "rig_available", lambda: True)
    monkeypatch.setattr(core, "platform_ok", lambda: False)
    with web_app(tmp_path, mfr="bof") as w:
        s = w.state(NS)
        assert not s["go_enabled"] and "Windows only" in s["note"]


def test_the_fun_var_is_the_windows_export(tmp_path):
    with web_app(tmp_path, mfr="bof") as w:
        var = w.window.bof_emulate_fun_var
        assert var is _svc(w).bof_emulate_fun_var
        w.call("ui.set", NS, "fun", r"D:\Pinball\images\BoF\dune.fun")
        assert var.get() == r"D:\Pinball\images\BoF\dune.fun"


def test_browse_asks_for_a_fun(tmp_path):
    with web_app(tmp_path, mfr="bof") as w:
        f = tmp_path / "dune.fun"
        f.write_bytes(b"")
        w.answers.append(str(f))
        assert w.call(NS + ".browse")
        spec = w.asked[-1]
        assert ["Barrels of Fun update", "*.fun"] in spec["filetypes"]
        assert w.window.bof_emulate_fun_var.get() == str(f)


def test_showing_the_tab_puts_up_the_bof_ladder(tmp_path):
    with web_app(tmp_path, mfr="bof") as w:
        w.call("ui.select_tab", NS)
        f = w.state("shell")["footer"]
        assert f["phases"] == ["Decrypt", "Boards", "Game", "Ready"]
        assert f["mode"] == "emulate"


def test_start_without_a_file_asks_and_runs_nothing(rig, monkeypatch, tmp_path):
    ran = []
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: ran.append(a))
    with web_app(tmp_path, mfr="bof") as w:
        w.call(NS + ".toggle")
        assert ran == []
        assert not _svc(w)._busy


def test_start_is_refused_while_the_rig_is_switched_off(rig, tmp_path):
    with web_app(tmp_path, mfr="bof") as w:
        f = tmp_path / "dune.fun"
        f.write_bytes(b"x")
        w.window.bof_emulate_fun_var.set(str(f))
        w.call(NS + ".toggle")
        assert not _svc(w)._busy


# ------------------------------------------------------------ the poll
HW = {"title": "Dune", "switches": {"12": 1, "72": 1, "79": 1},
      "balls": {"trough": 5, "in_play": 0, "shooter": True},
      "drivers_configured": 32, "leds_lit": 429,
      "status": {"net_id": True, "configured": True, "nodes": True,
                 "exp": ["48", "84", "86", "b4"], "bics_id": True,
                 "hardware_connected": True}}
RUNNING = {"wsl": "1", "running": "1", "title": "dune", "pid": "42",
           "rss_kb": str(2 * 1048576), "uptime_s": "75", "display": ":0",
           "visible": "1", "hw": json.dumps(HW)}


def test_apply_running_fills_the_grid(rig, tmp_path):
    with web_app(tmp_path, mfr="bof") as w:
        _svc(w)._apply(dict(RUNNING))
        s = w.state(NS)
        assert s["up"] and s["ready"] and s["go_label"] == "Stop"
        assert s["state_label"] == "Running" and s["tone"] == "ok"
        v = {c["label"]: c["value"] for c in s["cells"]}
        assert v["Game"] == "Dune"
        assert v["Boards"] == "Neuron, 4 expansion, BICS"
        assert v["Balls"] == "5 in trough, 0 in play, 1 in shooter lane"
        assert v["Memory"] == "2.0 GB" and v["Uptime"] == "1:15"


def test_starting_up_is_not_yet_running(rig, tmp_path):
    hw = dict(HW, status=dict(HW["status"], hardware_connected=False))
    with web_app(tmp_path, mfr="bof") as w:
        _svc(w)._apply(dict(RUNNING, hw=json.dumps(hw)))
        s = w.state(NS)
        assert s["state_label"] == "Starting" and not s["ready"]


def test_stopped(rig, tmp_path):
    with web_app(tmp_path, mfr="bof") as w:
        _svc(w)._apply({"wsl": "1", "running": "0"})
        s = w.state(NS)
        assert not s["up"] and s["state_label"] == "Stopped"
        assert s["go_label"] == "Start"


# ------------------------------------------------------- the switch window
def test_the_switch_window_command(rig, monkeypatch, tmp_path):
    """bofpf.py on the app's Windows Python, told the title, the slot, the
    distro, and the playfield picture through the distro's share."""
    from pinball_decryptor.webui import emulate_bof_core as core
    from pinball_decryptor.webui.tabs import emulate_bof as tab
    monkeypatch.setattr(tab, "windows_python", lambda: "pythonw.exe")
    monkeypatch.setattr(core, "rig_distro", lambda: "PAD-Runtime")
    with web_app(tmp_path, mfr="bof") as w:
        cmd = _svc(w)._switch_window_cmd(dict(
            RUNNING, slot="0",
            art="/var/tmp/pad_bof/cache/dune-1-2/pfart.webp"))
        assert cmd[0] == "pythonw.exe"
        assert cmd[1].endswith("bofpf.py")
        assert cmd[cmd.index("--title") + 1] == "dune"
        assert cmd[cmd.index("--distro") + 1] == "PAD-Runtime"
        assert cmd[cmd.index("--art") + 1] == '\\\\wsl.localhost\\PAD-Runtime\\var\\tmp\\pad_bof\\cache\\dune-1-2\\pfart.webp'
        # no game, no window
        assert _svc(w)._switch_window_cmd({"running": "0"}) is None


def test_switches_button_needs_a_running_game(rig, monkeypatch, tmp_path):
    with web_app(tmp_path, mfr="bof") as w:
        assert not w.call(NS + ".switches")


def test_launch_lines_move_the_footer(rig, tmp_path):
    with web_app(tmp_path, mfr="bof") as w:
        w.call("ui.select_tab", NS)
        svc = _svc(w)
        seen = []
        svc._footer = lambda kind, pct=None, text="": seen.append((kind, pct))
        for line in ("== Decrypt ==", "progress 40", "== Boards ==",
                     "== Game ==", "== Ready =="):
            svc._footer_line(line)
        assert seen == [("copy", 0), ("copy", 40), ("boot", None),
                        ("techalerts", None), ("run", None)]


def test_title_keys_come_from_the_plugin():
    from pinball_decryptor.webui import emulate_bof_core as core
    from pinball_decryptor.plugins.bof.games import GAME_DB
    # Only the GPG-symmetric titles have a passphrase and a rig profile; Bon
    # Jovi ships a signed disk image (no key) and is extract-only, so it is
    # not part of the emulator rig.
    keyed = {k: v for k, v in GAME_DB.items() if v.get("passphrase")}
    keys = dict(p.split(":", 1) for p in core.title_keys().split(","))
    assert keys == {k: v["passphrase"] for k, v in keyed.items()}
    import os
    for k in keyed:
        assert os.path.isfile(os.path.join(core.DEFAULT_RIG_DIR, "profiles",
                                           k + ".json")), k


def test_quit_stops_only_a_run_this_app_started(rig, monkeypatch, tmp_path):
    import subprocess
    ran = []
    from pinball_decryptor.webui import emulate_bof_core as core
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: ran.append(a))
    monkeypatch.setattr(core, "rig_cmd_root",
                        lambda *a, **k: ["bash"] + list(a))
    monkeypatch.setattr(
        "pinball_decryptor.webui.tabs.emulate_bof.rig_off", lambda: False)
    with web_app(tmp_path, mfr="bof") as w:
        svc = _svc(w)
        svc._last_up = True
        svc._started_here = False
        svc.emulate_shutdown()
        assert ran == []
        svc._started_here = True
        svc.emulate_shutdown()
        assert len(ran) == 1 and "stop.sh" in " ".join(ran[0][0])


def test_an_empty_field_uses_the_fun_picked_on_select_card(tmp_path):
    with web_app(tmp_path, mfr="bof") as w:
        svc = _svc(w)
        assert svc.fun_path() == ""
        w.window.extract_input_var.set(r"D:\Pinball\images\BoF\dune.fun")
        assert svc.fun_path() == r"D:\Pinball\images\BoF\dune.fun"
        # its own field wins
        w.window.bof_emulate_fun_var.set(r"C:\mods\dune_mod.fun")
        assert svc.fun_path() == r"C:\mods\dune_mod.fun"
        # a non-.fun card is not a game file for this tab
        w.window.bof_emulate_fun_var.set("")
        w.window.extract_input_var.set(r"D:\somewhere\else.img")
        assert svc.fun_path() == ""


def test_while_starting_the_button_is_cancel(rig, monkeypatch, tmp_path):
    """A start unpacking a big build off a slow disk must be cancellable:
    the Start button turns into Cancel, and pressing it runs cancel.sh."""
    import subprocess
    from pinball_decryptor.webui import emulate_bof_core as core
    ran = []
    monkeypatch.setattr(core, "rig_cmd_root",
                        lambda *a, **k: ["bash"] + list(a))
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **k: ran.append(cmd) or
                        subprocess.CompletedProcess(cmd, 0, b"cancelled=1", b""))
    with web_app(tmp_path, mfr="bof") as w:
        svc = _svc(w)
        # as _start_async leaves it while watch.sh runs
        svc._busy = True
        svc._starting = True
        svc._set_go("Cancel", True)
        s = w.state(NS)
        assert s["go_label"] == "Cancel" and s["go_enabled"] and s["starting"]
        assert not s["go_busy"]
        assert w.call(NS + ".toggle")
        assert w.state(NS)["go_label"] == "Canceling…"
        assert not w.state(NS)["go_enabled"]
        end = time.time() + 5
        while not ran and time.time() < end:
            time.sleep(0.02)
        assert ran and ran[0][-1] == "cancel.sh"
        # a second press does nothing while the cancel runs
        assert not w.call(NS + ".cancel")


def test_cancel_does_nothing_when_nothing_is_starting(rig, tmp_path):
    with web_app(tmp_path, mfr="bof") as w:
        assert not w.call(NS + ".cancel")
