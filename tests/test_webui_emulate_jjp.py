"""The web Emulate JJP tab (webui/tabs/emulate_jjp.py): the Tk panel's
behaviour on the web service, without ever touching a rig.

Every test runs with PAD_UI_NO_RIG=1 (the harness sets it), so no poll and
no launch reaches WSL; the tests that walk a launch switch the guard off
for themselves and stub every subprocess the service would run.
"""

import json
import sys
import time

import pytest

from tests.webui_harness import web_app

NS = "emulate_jjp"


def _svc(w):
    return w.window.service(NS)


def _wait(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _log_text(w):
    return "\n".join(e["text"] for e in w.window.log_history())


@pytest.fixture
def rig(monkeypatch):
    """The rig 'present' (conftest points it at an empty directory so no
    test can reach the real one; nothing here runs it either way)."""
    from pinball_decryptor.webui import emulate_jjp_core as tkjjp
    monkeypatch.setattr(tkjjp, "rig_available", lambda: True)


# ------------------------------------------------------------------ gating
def test_jjp_shows_the_tab_with_its_idle_state(rig, tmp_path):
    with web_app(tmp_path, mfr="jjp") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs[NS]["visible"]
        assert tabs[NS]["label"] == "Emulate"
        assert not tabs["emulate"]["visible"]
        assert not tabs["emulate_spike1"]["visible"]
        s = w.state(NS)
        assert s["go_label"] == "Start"
        assert s["state_label"] == "Checking…"
        assert s["fix_label"] == "Fix stuck state"
        assert [c["label"] for c in s["cells"]] == [
            "Security key", "Licence daemon", "Image mounted", "Game",
            "Processes", "Memory", "Uptime", "Display", "Boards",
            "Frames in / out", "LED writes"]
        assert s["intro"].startswith("Run a Jersey Jack game on this PC.")
        assert s["go_enabled"] and s["note"] == ""
        # the poller is off in a test session
        assert _svc(w)._poll_job is None


@pytest.mark.parametrize("mfr", ["stern", "spooky", "pb", "williams"])
def test_other_manufacturers_do_not_get_the_jjp_tab(tmp_path, mfr):
    with web_app(tmp_path, mfr=mfr) as w:
        if mfr not in {m.key for m in w.window.manufacturers}:
            pytest.skip("no %s plugin" % mfr)
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not tabs[NS]["visible"]


def test_the_iso_var_is_the_windows_export(tmp_path):
    with web_app(tmp_path, mfr="jjp") as w:
        var = w.window.jjp_emulate_iso_var
        assert var is _svc(w).jjp_emulate_iso_var
        w.call("ui.set", NS, "iso", r"D:\Pinball\images\JJP\game.iso")
        assert var.get() == r"D:\Pinball\images\JJP\game.iso"
        var.set("")
        assert w.state(NS)["iso"] == ""
        assert not getattr(w.window, "missing_exports", {}).get(
            "jjp_emulate_iso_var")


def test_browse_sets_the_iso(tmp_path):
    with web_app(tmp_path, mfr="jjp") as w:
        iso = tmp_path / "game.iso"
        iso.write_bytes(b"")
        w.answers.append(str(iso))
        assert w.call(NS + ".browse")
        spec = w.asked[-1]
        assert spec["kind"] == "file" and spec["title"] == \
            "Select a JJP game ISO"
        assert ["JJP game image", "*.iso"] in spec["filetypes"]
        assert w.window.jjp_emulate_iso_var.get() == str(iso)


def test_showing_the_tab_puts_up_the_jjp_ladder(tmp_path):
    with web_app(tmp_path, mfr="jjp") as w:
        w.call("ui.select_tab", NS)
        f = w.state("shell")["footer"]
        assert f["phases"] == ["Restore image", "Boot", "Game", "Ready"]
        assert f["mode"] == "emulate"
        # another manufacturer takes it back to the default ladder
        w.call("ui.pick_manufacturer", "stern")
        assert tuple(w.window._phases["emulate"]) != (
            "Restore image", "Boot", "Game", "Ready")


def test_a_missing_rig_says_so_and_greys_start(tmp_path):
    with web_app(tmp_path, mfr="jjp") as w:
        s = w.state(NS)
        assert not s["go_enabled"] and not s["rig_ok"]
        assert s["note"] == ("The JJP emulator rig is missing from "
                             "tools/jjp_emu — this checkout looks incomplete.")


# ------------------------------------------------------------ the poll
RUNNING = {"wsl": "1", "game_procs": "3", "game_rss_kb": str(2 * 1024 * 1024),
           "game_uptime_s": "75", "frames_in": "40", "frames_out": "38",
           "board_nodes": "5", "dongle_present": "1", "hasp_port_1947": "1",
           "image_mounted": "1", "game": "GunsNRoses", "nested_display": "1",
           "led_writes": "1234"}


def test_apply_running_fills_the_grid_and_flips_the_button(rig, tmp_path):
    with web_app(tmp_path, mfr="jjp") as w:
        w.run(_svc(w)._apply, dict(RUNNING))
        s = w.state(NS)
        assert s["go_label"] == "Stop" and s["up"] and s["tone"] == "ok"
        assert s["state_label"] == "Running"
        assert "2.0 GB" in s["state_hint"] and "1:15" in s["state_hint"]
        cells = {c["key"]: c["value"] for c in s["cells"]}
        assert cells["dongle_present"] == "yes"
        assert cells["game_rss_kb"] == "2.0 GB"
        assert cells["game_uptime_s"] == "1:15"
        assert cells["nested_display"] == "windowed"
        assert cells["board_nodes"] == "5 devices"
        assert cells["frames_in"] == "40 / 38"
        assert cells["led_writes"] == "1234"
        assert s["game"] == "GunsNRoses"
        assert s["note"] == ""


def test_apply_running_without_boards_warns(rig, tmp_path):
    with web_app(tmp_path, mfr="jjp") as w:
        info = dict(RUNNING, board_nodes="0")
        w.run(_svc(w)._apply, info)
        s = w.state(NS)
        assert "playfield boards are not present" in s["note"]
        assert {c["key"]: c["value"] for c in s["cells"]}["board_nodes"] \
            == "none"


def test_apply_stopped_without_key_says_so(rig, tmp_path):
    with web_app(tmp_path, mfr="jjp") as w:
        w.run(_svc(w)._apply, {"wsl": "1", "game_procs": "0",
                               "dongle_present": "0"})
        s = w.state(NS)
        assert s["go_label"] == "Start" and not s["up"]
        assert s["state_label"] == "No security key" and s["tone"] == "warn"
        assert s["note"].startswith("No security key detected.")


def test_a_key_in_the_pc_is_handed_over_not_reported_missing(rig, tmp_path):
    with web_app(tmp_path, mfr="jjp") as w:
        svc = _svc(w)
        w.run(svc._apply, {"wsl": "1", "game_procs": "0",
                           "dongle_present": "0", "key_on_pc": "1"})
        s = w.state(NS)
        assert s["state_label"] == "Key not passed through yet"
        assert "Handing it over" in s["note"]
        # the automatic hand-over never runs in a test session
        assert not svc._auto_attached


def test_wrong_key_verdict_sticks_until_the_game_runs(tmp_path):
    with web_app(tmp_path, mfr="jjp") as w:
        svc = _svc(w)
        w.run(svc._mark_key_failure, "Key not accepted", "hint text")
        w.drain()
        w.run(svc._apply, {"wsl": "1", "game_procs": "0",
                           "dongle_present": "1", "image_mounted": "1"})
        assert w.state(NS)["state_label"] == "Key not accepted"
        w.run(svc._apply, dict(RUNNING))
        assert w.state(NS)["state_label"] == "Running"


def test_selector_showing_moves_the_footer_to_the_game_slot(tmp_path):
    with web_app(tmp_path, mfr="jjp") as w:
        w.call("ui.select_tab", NS)
        w.run(_svc(w)._apply, {"wsl": "1", "game_procs": "0",
                               "selector_procs": "1", "dongle_present": "1",
                               "image_mounted": "1"})
        w.drain()
        f = w.state("shell")["footer"]
        assert f["index"] == 2 and f["status"] == "Boot menu showing…"
        w.run(_svc(w)._apply, dict(RUNNING))
        w.drain()
        f = w.state("shell")["footer"]
        assert f["index"] == 4 and f["status"] == "Game running"


# ------------------------------------------------------------ Start / Stop
def test_start_without_an_iso_or_a_mount_asks_and_does_not_shell_out(
        rig, tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    with web_app(tmp_path, mfr="jjp") as w:
        w.call(NS + ".toggle")
        spec = w.asked[-1]
        assert spec["title"] == "Emulate"
        assert spec["message"].startswith("Pick a JJP game ISO first.")
        assert not _svc(w)._busy


def test_start_is_refused_while_the_rig_is_switched_off(rig, tmp_path,
                                                        monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    with web_app(tmp_path, mfr="jjp") as w:
        w.window.jjp_emulate_iso_var.set(r"D:\x.iso")
        w.call(NS + ".toggle")
        w.drain()
        assert not _svc(w)._busy
        assert "switched off" in _log_text(w)


def _boom(*_a, **_k):
    raise AssertionError("a test must never start a process")


class _FakeProc:
    def __init__(self, lines, rc=0):
        self.stdout = iter([ln + "\n" for ln in lines])
        self.returncode = rc

    def wait(self):
        return self.returncode

    def kill(self):
        pass


def _stdout_close(proc):
    proc.stdout = _Closable(proc.stdout)
    return proc


class _Closable:
    def __init__(self, it):
        self._it = it

    def __iter__(self):
        return self._it

    def close(self):
        pass


def test_fix_state_declined_does_nothing(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run", _boom)
    with web_app(tmp_path, mfr="jjp") as w:
        w.answers.append("no")
        w.call(NS + ".fix_state")
        spec = w.asked[-1]
        if sys.platform == "win32":
            assert spec["title"] == "Fix stuck state"
            assert spec["message"].startswith(
                "Force-restart WSL to clear a wedged emulator?")
        else:
            assert "only applies on Windows" in spec["message"]
        assert not _svc(w)._busy
        assert w.state(NS)["fix_label"] == "Fix stuck state"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only recovery")
def test_fix_state_confirmed_shuts_wsl_down(rig, tmp_path, monkeypatch):
    import subprocess
    import pinball_decryptor.webui.tabs.emulate_jjp as mod
    calls = []

    class Out:
        returncode = 0
        stdout = b""

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return Out()

    monkeypatch.setattr(subprocess, "run", fake_run)
    from pinball_decryptor.webui import emulate_jjp_common as common
    with web_app(tmp_path, mfr="jjp") as w:
        monkeypatch.setattr(mod, "rig_off", lambda: False)
        monkeypatch.setattr(common, "rig_off", lambda: False)
        svc = _svc(w)
        monkeypatch.setattr(svc, "_poll_now", lambda: None)
        w.answers.append("yes")
        assert w.call(NS + ".fix_state")
        assert _wait(lambda: not svc._busy)
        w.drain()
        assert ["wsl.exe", "--shutdown"] in calls
        assert "WSL was shut down" in _log_text(w)
        assert w.state(NS)["fix_label"] == "Fix stuck state"


# ------------------------------------------------------------ the knob
def test_volume_and_mute_write_the_shared_control_file(tmp_path,
                                                       monkeypatch):
    from pinball_decryptor.webui import emulate_core as et
    ctl = tmp_path / "audio_ctl.json"
    monkeypatch.setattr(et, "AUDIO_CTL_FILE", str(ctl))
    with web_app(tmp_path, mfr="jjp") as w:
        w.call("ui.set", NS, "volume", 40)
        data = json.loads(ctl.read_text())
        assert abs(data["gain"] - 0.4) < 1e-6 and data["muted"] is False
        w.call("ui.set", NS, "mute", True)
        assert json.loads(ctl.read_text())["muted"] is True
        # showing the tab reads the knob back without rewriting it
        ctl.write_text(json.dumps({"gain": 0.25, "muted": False}))
        w.call("ui.select_tab", NS)
        assert w.state(NS)["volume"] == 25.0
        assert w.state(NS)["mute"] is False


# --------------------------------------------- multi-boot / app quit
def test_launch_iso_sets_the_iso_and_starts(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="jjp") as w:
        svc = _svc(w)
        started = []
        monkeypatch.setattr(svc, "_start_async", lambda: started.append(1))
        assert w.run(svc.launch_iso, r"D:\multi\jjp_multi.iso")
        assert w.window.jjp_emulate_iso_var.get() == r"D:\multi\jjp_multi.iso"
        assert started == [1]
        svc._busy = True
        assert not w.run(svc.launch_iso, r"D:\other.iso")
        w.drain()
        assert "a start or stop is already running" in _log_text(w)
        svc._busy = False
        assert not w.run(svc.launch_iso, "")


def test_emulate_shutdown_fans_out_and_never_runs_a_rig_in_tests(
        tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run", _boom)
    with web_app(tmp_path, mfr="jjp") as w:
        svc = _svc(w)
        svc._last_up = True
        w.run(w.window.emulate_shutdown)
        assert svc._stopped


# --------------------------------- the poll runs from app start, as Tk's
def _rig_on(monkeypatch, w, info):
    """Switch the session's rig guard off for the pollers only, with every
    poller in the app reading *info* (no status call is ever made)."""
    from pinball_decryptor.webui import emulate_jjp_common as common
    for ns in ("emulate_jjp", "emulate_spike1"):
        monkeypatch.setattr(w.window.service(ns), "_read_status",
                            lambda: dict(info))
    monkeypatch.setattr(common, "rig_off", lambda: False)


def test_the_poll_runs_whichever_manufacturer_shows(rig, tmp_path,
                                                    monkeypatch):
    """The Tk panel was built for every manufacturer and polled from
    build(): a JJP game this session never showed is still seen."""
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        assert not svc._visible
        _rig_on(monkeypatch, w, dict(RUNNING, cuse_daemons="5"))
        assert svc._poll_wanted()
        w.run(svc._start_polling)          # what __init__ does, rig on
        assert _wait(lambda: svc._polled_once)
        w.drain()
        assert svc._last_up
        # the ladder is the showing tab's: a hidden JJP run leaves it alone
        assert w.state("shell")["footer"]["status"] != "Game running"
        w.run(svc._cancel_poll)


@pytest.mark.skipif(sys.platform != "win32", reason="the rig is WSL's")
def test_app_quit_stops_a_run_this_session_never_showed(rig, tmp_path,
                                                        monkeypatch):
    import subprocess
    from pinball_decryptor.webui import emulate_jjp_core as tkjjp
    import pinball_decryptor.webui.tabs.emulate_jjp as mod
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        # the CUSE daemons alone are reason enough (Tk's shutdown_sync)
        w.run(svc._apply, {"wsl": "1", "game_procs": "0",
                           "cuse_daemons": "5"})
        stops = []
        monkeypatch.setattr(mod, "rig_off", lambda: False)
        monkeypatch.setattr(tkjjp, "rig_cmd_root",
                            lambda *a, **k: ["root"] + list(a))
        monkeypatch.setattr(subprocess, "run",
                            lambda cmd, **k: stops.append(cmd))
        w.run(w.window.emulate_shutdown)
        assert stops == [["root", "stop.sh"]]


def test_a_key_in_the_pc_is_handed_over_whatever_shows(rig, tmp_path,
                                                        monkeypatch):
    import subprocess
    import pinball_decryptor.webui.tabs.emulate_jjp as mod
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _rig_on(monkeypatch, w, {"wsl": "1", "game_procs": "0",
                                 "dongle_present": "1"})
        monkeypatch.setattr(mod, "rig_off", lambda: False)
        attached = []
        monkeypatch.setattr(svc, "_attach_dongle",
                            lambda: attached.append(1) or True)
        w.run(svc._apply, {"wsl": "1", "game_procs": "0",
                           "dongle_present": "0", "key_on_pc": "1"})
        assert _wait(lambda: attached == [1])
        assert _wait(lambda: "JJP: security key attached." in _log_text(w))
        w.run(svc._cancel_poll)


def test_showing_the_tab_reads_a_stale_status_at_once(rig, tmp_path,
                                                      monkeypatch):
    from pinball_decryptor.webui import emulate_jjp_common as common
    with web_app(tmp_path, mfr="jjp") as w:
        svc = _svc(w)
        now = []
        monkeypatch.setattr(svc, "_poll_now", lambda: now.append(1))
        monkeypatch.setattr(svc, "_schedule_poll", lambda ms=None: None)
        monkeypatch.setattr(common, "rig_off", lambda: False)
        w.call("ui.select_tab", "extract")
        w.call("ui.select_tab", NS)
        assert now == [1]                  # never read: read now
        svc._last_poll_at = time.monotonic()
        w.call("ui.select_tab", "extract")
        w.call("ui.select_tab", NS)
        assert now == [1]                  # fresh: the schedule stands


# ------------------------------------------- whose spinner is it
@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only recovery")
def test_fix_stuck_state_spins_its_own_button_and_only_greys_start(
        rig, tmp_path, monkeypatch):
    import subprocess
    import threading
    import pinball_decryptor.webui.tabs.emulate_jjp as mod
    from pinball_decryptor.webui import emulate_jjp_common as common
    gate = threading.Event()

    class Out:
        returncode = 0
        stdout = b""

    def fake_run(cmd, **kw):
        assert cmd == ["wsl.exe", "--shutdown"]
        gate.wait(5)
        return Out()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    with web_app(tmp_path, mfr="jjp") as w:
        svc = _svc(w)
        monkeypatch.setattr(mod, "rig_off", lambda: False)
        monkeypatch.setattr(common, "rig_off", lambda: False)
        monkeypatch.setattr(svc, "_poll_now", lambda: None)
        w.answers.append("yes")
        assert w.call(NS + ".fix_state")
        s = w.state(NS)
        assert s["fix_label"] == "Resetting…" and s["fix_busy"]
        assert not s["go_enabled"] and not s["go_busy"]
        assert s["go_label"] == "Start"
        gate.set()
        assert _wait(lambda: not svc._busy)
        w.drain()
        s = w.state(NS)
        assert s["fix_label"] == "Fix stuck state" and not s["fix_busy"]
        assert s["go_enabled"] and not s["go_busy"]
