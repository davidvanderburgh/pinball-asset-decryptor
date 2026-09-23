"""The web Emulate tab for Stern Spike 1 (webui/tabs/emulate_spike1.py) and
its display / switch windows (webui/emulate_jjp_spike1view.py; cards on the
tab without a native window): the Tk panel's behaviour, without ever
touching a rig (PAD_UI_NO_RIG=1) or a window (pywebview is faked)."""

import sys
import time

import pytest

from tests.webui_harness import web_app

NS = "emulate_spike1"


def _svc(w):
    return w.window.service(NS)


def _log_text(w):
    return "\n".join(e["text"] for e in w.window.log_history())


def _wait(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _boom(*_a, **_k):
    raise AssertionError("a test must never start a process")


@pytest.fixture(autouse=True)
def _no_spike1_rig(tmp_path_factory, monkeypatch):
    """Like conftest's isolation of the other two rigs: the Spike 1 rig is
    pointed at an empty directory, so nothing here can reach the real one.
    And the run dir's \\\\wsl.localhost paths land in a local folder: opening
    a distro's UNC path starts that distro, which a test must never do."""
    monkeypatch.setenv("PAD_SPIKE1_EMU_DIR",
                       str(tmp_path_factory.mktemp("no-s1-rig")))
    from pinball_decryptor.webui import emulate_spike1_core as tkwin
    run_dir = tmp_path_factory.mktemp("s1-run")
    monkeypatch.setattr(tkwin, "wsl_unc", lambda distro, p: str(
        run_dir / p.rstrip("/").split("/")[-1]) if distro else None)


@pytest.fixture
def rig(monkeypatch):
    from pinball_decryptor.webui import emulate_spike1_core as tks1
    monkeypatch.setattr(tks1, "rig_available", lambda: True)


@pytest.fixture
def no_procs(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)


# ------------------------------------------------------------------ gating
def test_spike1_era_shows_the_tab(rig, tmp_path, no_procs):
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs[NS]["visible"]
        assert not tabs["emulate"]["visible"]
        assert not tabs["emulate_jjp"]["visible"]
        s = w.state(NS)
        assert [r["label"] for r in s["rows"]] == [
            "State:", "Processes:", "Game CPU / memory:", "DMD frames:",
            "Boards registered:"]
        assert s["go_label"] == "Start emulator"
        assert s["intro"].startswith("Run a Stern Spike 1 (DMD-era) game")
        if sys.platform == "win32":
            assert s["win"] and s["slots_enabled"]
            assert s["slots_sum"].startswith("The slots appear with the next")
            assert s["go_enabled"] and s["note"] == ""
        else:
            assert not s["go_enabled"] and not s["fix_enabled"]
            assert "Windows-only" in s["note"]
            assert s["slots_sum"] == \
                "Slot management is available on Windows (WSL)."


def test_a_missing_rig_says_so(tmp_path, no_procs):
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        s = w.state(NS)
        assert not s["go_enabled"] and not s["slots_enabled"]
        assert s["note"].startswith("The Spike 1 emulator rig is missing")
        # Tk greyed Fix setup only off Windows: with tools/spike1_emu
        # incomplete it still installs the Linux and the shipped binaries
        assert s["fix_enabled"] == (sys.platform == "win32")


def test_fix_setup_runs_with_an_incomplete_rig_on_windows(tmp_path,
                                                         no_procs):
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        assert w.call(NS + ".fix_setup") is False
        if sys.platform == "win32":
            # past the gate, to the session's rig switch (never further in
            # a test)
            assert "switched off in this session" in _log_text(w)
        else:
            assert "switched off" not in _log_text(w)


def test_spike2_and_whitestar_do_not_show_it(tmp_path, no_procs):
    with web_app(tmp_path, mfr="stern") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not tabs[NS]["visible"]
        w.call("ui.set_era", "whitestar")
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not tabs[NS]["visible"]


def test_the_card_var_is_the_windows_export(tmp_path, no_procs):
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        var = w.window.spike1_emulate_card_var
        assert var is _svc(w).spike1_emulate_card_var
        w.call("ui.set", NS, "card", r"D:\Pinball\images\Stern\spike1\got.img")
        assert var.get().endswith("got.img")


def test_showing_the_tab_puts_up_the_spike1_ladder(tmp_path, no_procs):
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        w.call("ui.select_tab", NS)
        f = w.state("shell")["footer"]
        assert f["phases"] == ["Extract", "Boot", "Node boards", "Ready"]


# ------------------------------------------------------------ the poll
RUNNING = {"wsl": "1", "game_procs": "4", "nodes_registered": "1",
           "cpu": "63", "rss_mb": "212", "game_uptime_s": "130",
           "dmd_frames": "5120", "qemu_built": "1", "game_ready": "1"}


def test_apply_running_fills_the_status_and_opens_the_cards(rig, tmp_path,
                                                           no_procs):
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        svc = _svc(w)
        info = dict(RUNNING, work="/home/u/s1emu/run", distro="PAD-Runtime")
        w.run(svc._apply, info)
        s = w.state(NS)
        rows = {r["key"]: r["value"] for r in s["rows"]}
        assert rows["state"] == "Game running"
        assert rows["procs"] == "4 running"
        assert rows["cpu"] == "63% of one core, 212 MB  ·  up 2:10"
        assert rows["dmd"] == "5120"
        assert rows["boards"] == "yes"
        assert s["go_label"] == "Stop" and s["tone"] == "ok"
        if sys.platform == "win32":
            assert s["note"].startswith("The game is running and the boards")
        assert s["view_open"]
        # the switch card exists (nameless until the rig writes the map)
        assert s["sw"]["readout"].startswith("(no switch names")
        assert [r["label"] for r in s["sw"]["key_rows"]] == [
            "Left Flipper", "Right Flipper", "Upper Left Flipper",
            "Start Button", "Left Coin", "Tilt Pendulum", "Shooter Lane"]
        # nothing was started behind the test's back
        assert svc._player is None and svc._log_tailer is None
        # stopped: the cards close
        w.run(svc._apply, {"wsl": "1", "game_procs": "0", "qemu_built": "1",
                           "game_ready": "1"})
        s = w.state(NS)
        assert not s["view_open"] and s["sw"] is None
        rows = {r["key"]: r["value"] for r in s["rows"]}
        assert rows["state"] == "Not running"
        assert rows["procs"] == "0 running  (all stopped)"
        assert rows["cpu"] == "—" and rows["boards"] == "—"


def test_apply_booting_and_setup_needed(tmp_path, no_procs):
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        svc = _svc(w)
        w.run(svc._apply, {"wsl": "1", "game_procs": "2"})
        rows = {r["key"]: r["value"] for r in w.state(NS)["rows"]}
        assert rows["state"] == "Booting…" and rows["boards"] == "not yet"
        w.run(svc._apply, {"wsl": "1", "game_procs": "0"})
        s = w.state(NS)
        assert s["rows"][0]["value"] == "Setup needed"
        assert s["hint"].startswith("The ARM emulator has to be built once")


# ------------------------------------------------------------ Start
def test_start_without_a_card_or_a_game_asks(tmp_path, no_procs):
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        w.call(NS + ".toggle")
        spec = w.asked[-1]
        assert spec["title"] == "Emulate"
        assert spec["message"].startswith("Pick a Spike 1 card image first.")


def test_start_is_refused_while_the_rig_is_switched_off(rig, tmp_path, no_procs):
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        w.window.spike1_emulate_card_var.set(r"D:\got.img")
        w.call(NS + ".toggle")
        w.drain()
        assert not _svc(w)._busy
        assert "switched off" in _log_text(w)


def test_restart_wsl_declined_does_nothing(tmp_path, no_procs):
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        w.answers.append("no")
        w.call(NS + ".fix_state")
        spec = w.asked[-1]
        assert spec["title"] == "Restart WSL"
        assert not _svc(w)._busy


def test_reset_windows_needs_a_running_game(tmp_path, no_procs):
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        assert not w.call(NS + ".window_reset")
        assert "nothing running — start the emulator first" in _log_text(w)
        svc = _svc(w)
        w.run(svc._apply, dict(RUNNING, work="/w", distro="D"))
        assert w.call(NS + ".window_reset")
        assert w.state(NS)["reveal"] == 1
        assert "DMD and switch windows reopened" in _log_text(w)


def test_the_setup_actions_never_touch_the_machine_in_tests(tmp_path,
                                                            no_procs):
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        for m in ("fix_setup", "delete_rig_data", "delete_downloads",
                  "remove_runtime", "check_setup"):
            w.call(NS + "." + m)
        w.drain()
        assert not w.asked


# ------------------------------------------------------------ save states
def _record_ops(svc, monkeypatch):
    ops = []
    monkeypatch.setattr(svc, "_slot_op",
                        lambda args, doing, then_refresh=True:
                        ops.append(args))
    return ops


def test_save_state_asks_for_a_name_then_checks_it(tmp_path, no_procs,
                                                   monkeypatch):
    """Tk's simpledialog.askstring, through the app's own prompt dialog:
    the question, "quicksave" filled in, the name rule, then the save."""
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        svc = _svc(w)
        assert w.call(NS + ".slot_save") is None
        assert w.asked[-1]["message"].startswith("No game is running")
        svc._info = dict(RUNNING)
        ops = _record_ops(svc, monkeypatch)
        w.answers.append("bad name!")
        assert w.call(NS + ".slot_save") is None
        prompt = w.asked[-2]
        assert prompt["kind"] == "prompt" and prompt["input"] == "str"
        assert prompt["title"] == "Save state"
        assert prompt["message"] == "Slot name (letters, digits, _ . - only):"
        assert prompt["initial"] == "quicksave"
        assert w.asked[-1]["message"] == \
            "Slot names use letters, digits, _ . - only."
        w.answers.append("  ball2 ")
        assert w.call(NS + ".slot_save") is True
        assert ops == [("s1savestate.sh", "ball2")]
        assert "saving the game to slot 'ball2'" in _log_text(w)


def test_save_state_cancel_or_empty_saves_nothing(tmp_path, no_procs,
                                                  monkeypatch):
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        svc = _svc(w)
        svc._info = dict(RUNNING)
        ops = _record_ops(svc, monkeypatch)
        for answer in ("cancel", None, ""):
            n = len(w.asked)
            w.answers.append(answer)
            assert w.call(NS + ".slot_save") is None
            assert len(w.asked) == n + 1       # the prompt, and no error box
        assert ops == []


def test_slot_buttons_without_a_selection_say_so(tmp_path, no_procs,
                                                 monkeypatch):
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        for m, title in (("slot_load", "Load state"), ("slot_rename",
                                                        "Rename"),
                         ("slot_delete", "Delete")):
            w.call(NS + "." + m)
            assert w.asked[-1]["title"] == title
        svc = _svc(w)
        svc._slots_rows = [{"ref": "got/slot1", "label": "attract",
                            "bytes": "1", "game": "got", "epoch": "0"}]
        ops = _record_ops(svc, monkeypatch)
        w.answers.append("ball 3")
        assert w.call(NS + ".slot_rename", "got/slot1") is True
        prompt = w.asked[-1]
        assert (prompt["kind"], prompt["title"], prompt["message"],
                prompt["initial"]) == ("prompt", "Rename slot",
                                       "Name for got/slot1:", "attract")
        # Cancel renames nothing (Tk: None = cancel); an empty name is a name
        w.answers.append("cancel")
        assert w.call(NS + ".slot_rename", "got/slot1") is None
        w.answers.append("yes")
        w.call(NS + ".slot_delete", "got/slot1")
        assert ops == [("s1slots.sh", "label", "got/slot1", "ball 3"),
                       ("s1slots.sh", "delete", "got/slot1")]


def test_slots_paint_formats_the_rows(tmp_path, no_procs):
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        svc = _svc(w)
        svc._slots_rows = [{"ref": "got/slot1", "label": "attract",
                            "bytes": str(20 * 1024 * 1024), "game": "got",
                            "epoch": "0"}]
        w.run(svc._slots_paint, str(20 * 1024 * 1024), str(5 * 1024 ** 3))
        s = w.state(NS)
        assert s["slots"][0]["slot"] == "slot1"
        assert s["slots"][0]["size"] == "20.0 MB"
        assert s["slots_sum"] == "1 slot — 20.0 MB on disk · 5.0 GB free " \
                                 "(WSL disk)"
        svc._slots_rows = []
        w.run(svc._slots_paint)
        assert w.state(NS)["slots_sum"].startswith("No save states yet")


# ------------------------------------------------------------ cache
@pytest.mark.skipif(sys.platform != "win32", reason="the cache is WSL's")
def test_cache_window_opens_and_reads(tmp_path, no_procs):
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        assert w.call(NS + ".cache_open")
        assert _wait(lambda: "cached" in (w.state(NS)["cache"]["header"]))
        c = w.state(NS)["cache"]
        assert c["open"] and c["rows"] == []
        assert c["header"] == "0 cached — 0 KB on disk · ? free (WSL disk)"
        svc = _svc(w)
        w.run(svc._cache_apply, [
            {"label": "got_le", "kb": "2048", "boot": str(int(time.time())),
             "game": "got", "active": True},
            {"label": "gb", "kb": "1048576", "boot": "0", "game": "gb",
             "active": False}], "4194304")
        c = w.state(NS)["cache"]
        assert c["rows"][0]["used"] == "just now"
        assert c["rows"][0]["size"] == "2.0 MB"
        # the active one cannot be deleted
        assert w.call(NS + ".cache_delete", "got_le") is False
        w.call(NS + ".cache_close")
        assert not w.state(NS)["cache"]["open"]


# ------------------------------------------------ display + switch model
class FakeIO:
    def __init__(self, names=None, era="", frame=None):
        self.names = names or {}
        self.era = era
        self.frame = frame
        self.injected = []
        self.cmds = []
        self.run_dir_wsl = "/w"
        self.distro = "D"

    def read_text(self, name):
        return self.era if name == "s1era" else ""

    def read_switch_names(self):
        return dict(self.names)

    def read_json(self, name):
        return None

    def tail_frame(self, name, nbytes):
        return self.frame

    def read_state(self):
        from pinball_decryptor.plugins.stern.spike1_emulate import \
            HardwareState
        st = HardwareState()
        st.set_switch(0, 3, 1)
        st.set_lamp(1, 2, 255, 0, 0)
        return st

    def read_ball_state(self):
        return {"balls": 3, "nballs": 4, "door_closed": False}

    def write_injected(self, slots, seq):
        self.injected.append((sorted(slots), seq))

    def append_ball_cmd(self, line):
        self.cmds.append(line)
        return True


NAMES = {(0, 1): "L. FLIPPER BUTTON", (0, 2): "R. FLIPPER BUTTON",
         (0, 5): "START BUTTON", (1, 20): "SHOOTER LANE"}


def _model(io, after=None):
    from pinball_decryptor.webui.emulate_jjp_spike1view import SwitchModel
    seen = {}
    m = SwitchModel(io, after=after or (lambda ms, fn: seen.setdefault(
        "after", (ms, fn))), on_change=lambda st: seen.update(st=st))
    return m, seen


def test_switch_model_resolves_the_play_keys_from_the_names():
    m, seen = _model(FakeIO(NAMES))
    rows = {r["label"]: r["slot"] for r in seen["st"]["key_rows"]}
    assert rows["Left Flipper"] == 1 and rows["Right Flipper"] == 2
    assert rows["Start Button"] == 5 and rows["Shooter Lane"] == 64 + 20
    assert rows["Tilt Pendulum"] is None
    assert seen["st"]["cols"] == 21
    assert seen["st"]["readout"].startswith("click a switch to hold it")


def test_switch_model_pulse_toggle_and_keys():
    io = FakeIO(NAMES)
    m, seen = _model(io)
    m.pulse(0, 5)
    assert io.injected[-1][0] == [5]
    assert seen["st"]["readout"] == "pulsed node 0 · index 5 — START BUTTON"
    ms, release = seen["after"]
    assert ms == 350
    release()
    assert io.injected[-1][0] == []
    m.toggle(1, 20)
    assert io.injected[-1][0] == [84]
    assert seen["st"]["readout"].startswith("held node 1 · index 20")
    m.toggle(1, 20)
    assert io.injected[-1][0] == []
    m.press_key("Left")
    m.press_key("Left")               # auto-repeat is one press
    assert io.injected[-1][0] == [1]
    n = len(io.injected)
    m.release_key("Left")
    assert io.injected[-1][0] == [] and len(io.injected) == n + 1
    m.press_key("Return")
    assert io.cmds[-1] == "svc select"
    m.press_key("c")
    assert io.cmds[-1] == "door toggle"
    m.press_key("b")
    assert io.cmds[-1] == "trough toggle"
    assert seen["st"]["readout"] == "sent 'trough toggle' to the ball keeper"


def test_the_early_era_has_no_service_buttons_or_door():
    io = FakeIO(NAMES, era="early")
    m, seen = _model(io)
    assert seen["st"]["early"]
    m.press_key("Return")
    m.press_key("c")
    assert io.cmds == []


def test_switch_model_snapshot_and_trough_click():
    io = FakeIO(NAMES)
    m, _seen = _model(io)
    snap = m.snapshot()
    assert 3 in snap["made"]
    assert snap["lamps"] == {str(64 + 2): "#ff0000"}
    assert snap["ball"] == {"balls": 3, "nballs": 4, "in_shooter": False,
                            "door_closed": False}
    assert ["lamp", "Lamps / LEDs"] in snap["sections"]
    m.ball_click(1)                   # balls=3 > 1: empty back down to 1
    assert io.cmds[-1] == "trough 1"
    m.ball_click(3)                   # fill up to ball 4
    assert io.cmds[-1] == "trough 4"


def test_names_that_arrive_later_are_adopted():
    io = FakeIO({})
    m, seen = _model(io)
    assert seen["st"]["names"] == []
    assert m.refresh_names(dict(NAMES))
    assert len(seen["st"]["names"]) == 4
    assert {r["label"]: r["slot"] for r in seen["st"]["key_rows"]}[
        "Start Button"] == 5
    assert not m.refresh_names(dict(NAMES))


def test_display_feed_renders_a_dmd_frame_once(monkeypatch):
    from pinball_decryptor.webui.emulate_jjp_spike1view import DisplayFeed
    from pinball_decryptor.webui import emulate_spike1_core as tks1
    # the decoder is a plain Python module of the repo's rig (read only)
    monkeypatch.setenv("PAD_SPIKE1_EMU_DIR", tks1.DEFAULT_RIG_DIR)
    dmd = tks1._load_dmd_decoder()
    frame = bytes([0xFF] * 64) + bytes(2048 - 64)
    feed = DisplayFeed(FakeIO(frame=frame), dmd.decode_frame, None)
    f = feed.frame("")
    assert f["png"].startswith("data:image/png;base64,")
    assert (f["w"], f["h"]) == (128, 32) and f["mode"] == "dmd"
    assert feed.frame(f["sig"]) == {"sig": f["sig"]}
    assert DisplayFeed(FakeIO(frame=None), dmd.decode_frame).frame("") \
        is None


def test_the_view_calls_answer_off_the_loop(tmp_path, no_procs):
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        assert w.call(NS + ".view_frame", "") is None
        assert w.call(NS + ".view_state") is None
        assert w.call(NS + ".sw_pulse", 0, 1) is False
        svc = _svc(w)
        io = FakeIO(NAMES)
        from pinball_decryptor.webui.emulate_jjp_spike1view import \
            SwitchModel
        svc._model = SwitchModel(io, after=lambda ms, fn: None,
                                 on_change=lambda st: svc.set(sw=st))
        assert w.call(NS + ".sw_pulse", 0, 1)
        assert io.injected[-1][0] == [1]
        assert w.call(NS + ".ball_cmd", "start")
        assert io.cmds[-1] == "start"
        assert w.call(NS + ".view_state")["ball"]["balls"] == 3
        assert w.state(NS)["sw"]["readout"] == \
            "sent 'start' to the ball keeper"


def test_emulate_shutdown_is_safe_in_tests(tmp_path, no_procs):
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        svc = _svc(w)
        svc._last_up = True
        w.run(w.window.emulate_shutdown)
        assert svc._stopped


def test_display_feed_draws_the_alphanumeric_displays(monkeypatch):
    """The 2012 home models: 256-byte frames, two 16-segment displays."""
    from pinball_decryptor.webui.emulate_jjp_spike1view import DisplayFeed
    from pinball_decryptor.webui import emulate_spike1_core as tks1
    monkeypatch.setenv("PAD_SPIKE1_EMU_DIR", tks1.DEFAULT_RIG_DIR)
    dmd = tks1._load_dmd_decoder()
    alpha = tks1._load_alpha()
    assert alpha is not None
    io = FakeIO(frame=bytes([0xFF] * 256))
    feed = DisplayFeed(io, dmd.decode_frame, alpha)
    feed.set_mode("alpha")
    assert feed.mode == "alpha"
    f = feed.frame("")
    assert f["mode"] == "alpha" and f["png"].startswith("data:image/png")
    assert f["labels"] == ["PLAYER 1", "PLAYER 2"]
    assert f["text"] is None          # no font dumped by the rig yet
    # a machine without the alpha decoder stays a DMD
    plain = DisplayFeed(io, dmd.decode_frame, None)
    plain.set_mode("alpha")
    assert plain.mode == "dmd"


# ------------------------------------------- the poll, from app start (Tk)
def test_the_poll_runs_whichever_manufacturer_shows(rig, tmp_path, no_procs,
                                                    monkeypatch):
    """The Tk panel was built for every manufacturer and polled from
    build(): a run this session never showed is still seen (and stopped at
    quit, below)."""
    from pinball_decryptor.webui import emulate_jjp_common as common
    with web_app(tmp_path, mfr="jjp") as w:
        svc = _svc(w)
        assert not svc._visible
        for ns in ("emulate_jjp", "emulate_spike1"):
            monkeypatch.setattr(w.window.service(ns), "_read_status",
                                lambda: {"wsl": "1", "game_procs": "0",
                                         "responder": "1"})
        monkeypatch.setattr(common, "rig_off", lambda: False)
        assert svc._poll_wanted() == (sys.platform == "win32")
        if sys.platform != "win32":
            return
        w.run(svc._start_polling)          # what __init__ does, rig on
        assert _wait(lambda: svc._polled_once)
        w.drain()
        assert svc._info.get("responder") == "1"
        w.run(svc._cancel_poll)


@pytest.mark.skipif(sys.platform != "win32", reason="the rig is WSL's")
def test_app_quit_stops_a_run_this_session_never_showed(rig, tmp_path,
                                                        no_procs,
                                                        monkeypatch):
    import subprocess
    from pinball_decryptor.webui import emulate_spike1_core as tks1
    import pinball_decryptor.webui.tabs.emulate_spike1 as mod
    with web_app(tmp_path, mfr="stern") as w:        # the Spike 2 era shows
        svc = _svc(w)
        w.run(svc._apply, {"wsl": "1", "game_procs": "0", "responder": "1"})
        stops = []
        monkeypatch.setattr(mod, "rig_off", lambda: False)
        monkeypatch.setattr(tks1, "rig_cmd_root",
                            lambda *a, **k: ["root"] + list(a))
        monkeypatch.setattr(subprocess, "run",
                            lambda cmd, **k: stops.append(cmd))
        w.run(w.window.emulate_shutdown)
        assert stops == [["root", "stop.sh"]]


def test_showing_the_tab_reads_a_stale_status_at_once(rig, tmp_path,
                                                      no_procs, monkeypatch):
    from pinball_decryptor.webui import emulate_jjp_common as common
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        svc = _svc(w)
        now = []
        monkeypatch.setattr(svc, "_poll_now", lambda: now.append(1))
        monkeypatch.setattr(svc, "_schedule_poll", lambda ms=None: None)
        monkeypatch.setattr(common, "rig_off", lambda: False)
        if sys.platform != "win32":
            return
        w.call("ui.select_tab", NS)
        assert now == [1]                  # never read: read now
        svc._last_poll_at = time.monotonic()
        w.call("ui.select_tab", "extract")
        w.call("ui.select_tab", NS)
        assert now == [1]                  # fresh: the schedule stands


# --------------------------------------------- busy: whose spinner is it
@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only recovery")
def test_restart_wsl_spins_its_own_button_and_only_greys_start(
        rig, tmp_path, monkeypatch):
    import subprocess
    import threading
    import pinball_decryptor.webui.tabs.emulate_spike1 as mod
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
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        svc = _svc(w)
        monkeypatch.setattr(mod, "rig_off", lambda: False)
        monkeypatch.setattr(common, "rig_off", lambda: False)
        monkeypatch.setattr(svc, "_poll_now", lambda: None)
        w.answers.append("yes")
        assert w.call(NS + ".fix_state")
        s = w.state(NS)
        assert s["reset_label"] == "Restarting…" and s["reset_busy"]
        assert not s["go_enabled"] and not s["go_busy"]
        gate.set()
        assert _wait(lambda: not svc._busy)
        w.drain()
        s = w.state(NS)
        assert s["reset_label"] == "Restart WSL…" and not s["reset_busy"]
        assert s["go_enabled"] and not s["go_busy"]


# ------------------------------------------- the runtime's own questions
def test_the_runtime_questions_reach_the_page_unpatched(tmp_path, no_procs):
    """runtime_prompt asks with compat's messagebox (the page's questions,
    in tkinter's call shapes), so nothing swaps the module for the app (and
    nothing is left swapped after it)."""
    from pinball_decryptor.webui import compat
    from pinball_decryptor.webui import runtime_prompt as _runtime_ui
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        assert _runtime_ui.messagebox is compat.messagebox
        w.answers.append("no")
        assert w.run(_svc(w)._ask_before_replacing) is False
        assert w.asked[-1]["title"] == "Replace the emulator's Linux?"
    assert _runtime_ui.messagebox is compat.messagebox


# ------------------------------------ the display and switch WINDOWS (Tk's)
class _FakeEvent:
    def __init__(self):
        self.fns = []

    def __iadd__(self, fn):
        self.fns.append(fn)
        return self

    def fire(self):
        for fn in list(self.fns):
            fn()


class _FakeWin:
    def __init__(self, title, url, **kw):
        import types
        self.title, self.url, self.kw = title, url, kw
        self.calls = []
        self.events = types.SimpleNamespace(closed=_FakeEvent())

    def destroy(self):
        self.calls.append("destroy")
        self.events.closed.fire()

    def restore(self):
        self.calls.append("restore")

    def move(self, x, y):
        self.calls.append(("move", x, y))

    def show(self):
        self.calls.append("show")


@pytest.fixture
def fake_webview(monkeypatch):
    """pywebview's create_window, recorded (no window is ever made)."""
    import types
    made = []

    def create_window(title, url, **kw):
        win = _FakeWin(title, url, **kw)
        made.append(win)
        return win

    mod = types.ModuleType("webview")
    mod.create_window = create_window
    monkeypatch.setitem(sys.modules, "webview", mod)
    return made


class _NativeHost:
    """webui/host.py's Host as the native app has it, without a window."""
    mode = "native"
    quitting = False

    def __init__(self, token):
        import types
        self.window = types.SimpleNamespace(
            original_url="http://127.0.0.1:5123/?t=%s" % token)

    def set_title(self, _text):
        pass

    def is_maximized(self):
        return False

    def maximize(self):
        pass

    def quit(self):
        pass


def _native_host(token):
    return _NativeHost(token)


class _Store:
    def get(self, ns, key=None, default=None):
        return "dark" if (ns, key) == ("shell", "theme") else default


def test_view_windows_open_reopen_replace_place_and_close(fake_webview):
    import types
    from pinball_decryptor.webui.emulate_jjp_spike1view import ViewWindows
    ctx = types.SimpleNamespace(host=None, token="tok", store=_Store())
    vw = ViewWindows(ctx)
    assert not vw.available()                       # tests, --serve
    ctx.host = types.SimpleNamespace(mode="browser", quitting=False,
                                     window=None)
    assert not vw.available()                       # --browser
    ctx.host = _native_host("tok")
    assert vw.available()
    vw.show("dmd")
    assert _wait(lambda: len(fake_webview) == 2)
    disp, sw = fake_webview
    page = "http://127.0.0.1:5123/static/js/tabs/emulate_spike1_view.html"
    assert disp.title == "Spike 1 — DMD"
    assert disp.url == page + "?t=tok&view=display"
    assert (disp.kw["x"], disp.kw["y"]) == (80, 80)          # Tk's +80+80
    assert (disp.kw["width"], disp.kw["height"]) == (940, 300)
    assert sw.title == "Spike 1 — switches / LEDs"
    assert sw.url == page + "?t=tok&view=switches"
    assert (sw.kw["x"], sw.kw["y"]) == (80, 360)             # Tk's +80+360
    # every poll asks again; nothing new opens
    vw.show("dmd")
    time.sleep(0.2)
    assert len(fake_webview) == 2
    # closed by the user: the next poll reopens it (Tk's Spike1Viewers.open)
    sw.events.closed.fire()
    vw.show("dmd")
    assert _wait(lambda: len(fake_webview) == 3)
    sw2 = fake_webview[2]
    assert sw2.title == "Spike 1 — switches / LEDs"
    # the machine turns out to have the 16-segment displays: a new window
    vw.show("alpha")
    assert _wait(lambda: len(fake_webview) == 4)
    disp2 = fake_webview[3]
    assert disp.calls == ["destroy"] and disp2.title == "Spike 1 — display"
    # Reset windows: back at their places, restored, in front
    vw.show("alpha", reset=True)
    assert _wait(lambda: "show" in disp2.calls and "show" in sw2.calls)
    assert disp2.calls == ["restore", ("move", 80, 80), "show"]
    assert sw2.calls == ["restore", ("move", 80, 360), "show"]
    # the run stops: both close
    vw.close()
    assert _wait(lambda: sw2.calls[-1] == "destroy"
                 and disp2.calls[-1] == "destroy")
    assert not vw.is_open("display") and not vw.is_open("switches")
    # app quit: nothing opens again
    vw.shutdown()
    vw.show("dmd")
    time.sleep(0.2)
    assert len(fake_webview) == 4 and not vw.available()


def test_each_view_window_gets_its_own_icon_and_taskbar_button(
        fake_webview, monkeypatch):
    """They are windows of the app's own process, so without this they sat
    under the PAD taskbar button wearing the PAD icon."""
    import types
    from pinball_decryptor.webui import winbrand
    from pinball_decryptor.webui.emulate_jjp_spike1view import ViewWindows
    branded = []
    monkeypatch.setattr(winbrand, "brand",
                        lambda win, icon, group: branded.append(
                            (win.title, icon, group)))
    ctx = types.SimpleNamespace(host=_native_host("tok"), token="tok",
                                store=_Store())
    vw = ViewWindows(ctx)
    vw.show("dmd")
    assert _wait(lambda: len(branded) == 2)
    assert sorted(branded) == [
        ("Spike 1 — DMD", "dmdwin", winbrand.GAME_SCREEN),
        ("Spike 1 — switches / LEDs", "playfield", winbrand.PLAYFIELD)]
    assert winbrand.icon_path("dmdwin") and winbrand.icon_path("playfield")
    vw.shutdown()


def test_brand_leaves_a_window_with_no_native_form_alone():
    import types
    from pinball_decryptor.webui import winbrand
    assert winbrand.brand(types.SimpleNamespace(), "playfield",
                          winbrand.PLAYFIELD) is False
    assert winbrand.set_app_id(0, winbrand.PLAYFIELD) is False


def test_a_run_opens_the_two_windows_in_the_native_app(rig, tmp_path,
                                                       no_procs, monkeypatch,
                                                       fake_webview):
    from pinball_decryptor.webui import emulate_spike1_core as tks1
    # the rig's own DMD / 16-segment decoders (pure Python in the repo)
    monkeypatch.setenv("PAD_SPIKE1_EMU_DIR", tks1.DEFAULT_RIG_DIR)
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        w.ctx.host = _native_host(w.ctx.token)
        svc = _svc(w)
        w.run(svc._apply, dict(RUNNING, work="/w", distro="D",
                               _display="alphanumeric"))
        s = w.state(NS)
        assert s["view_open"] and s["view_popout"] and s["view_display"]
        assert s["view_mode"] == "alpha"
        assert _wait(lambda: len(fake_webview) == 2)
        assert sorted(win.title for win in fake_webview) == [
            "Spike 1 — display", "Spike 1 — switches / LEDs"]
        # Reset windows puts them back rather than scrolling the tab
        assert w.call(NS + ".window_reset")
        assert w.state(NS)["reveal"] == 0
        assert _wait(lambda: all("show" in win.calls for win in fake_webview))
        # another manufacturer leaves them up
        w.call("ui.pick_manufacturer", "jjp")
        assert svc._windows.is_open("display")
        assert svc._windows.is_open("switches")
        # the run ends: they close
        w.run(svc._apply, {"wsl": "1", "game_procs": "0"})
        assert _wait(lambda: all(win.calls[-1] == "destroy"
                                 for win in fake_webview))
        assert not w.state(NS)["view_open"]
        # app quit: closed for good
        w.run(svc._apply, dict(RUNNING, work="/w", distro="D"))
        assert _wait(lambda: len(fake_webview) == 4)
        w.run(w.window.emulate_shutdown)
        assert _wait(lambda: all(win.calls[-1:] == ["destroy"]
                                 for win in fake_webview))
        assert not svc._windows.available()


def test_without_a_native_window_the_tab_draws_the_cards(rig, tmp_path,
                                                         no_procs):
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        svc = _svc(w)
        w.run(svc._apply, dict(RUNNING, work="/w", distro="D"))
        s = w.state(NS)
        assert s["view_open"] and not s["view_popout"]
        assert w.call(NS + ".window_reset")
        assert w.state(NS)["reveal"] == 1


def test_the_poll_that_first_sees_a_run_reads_its_display_kind(
        tmp_path, no_procs, monkeypatch):
    from pinball_decryptor.webui import emulate_spike1_core as tks1
    from pinball_decryptor.webui import emulate_spike1_core as tkwin
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        svc = _svc(w)
        assert svc._io is None
        with open(tkwin.wsl_unc("D", "/w/s1display"), "w") as f:
            f.write("alphanumeric\n")
        monkeypatch.setattr(tks1, "rig_cmd", lambda *a, **k: ["status"])
        monkeypatch.setattr(svc, "_run_status", lambda cmd, timeout=25: dict(
            RUNNING, work="/w", distro="D"))
        info = svc._read_status()
        assert info["_display"] == "alphanumeric" and info["_names"] == {}
        monkeypatch.setattr(svc, "_run_status", lambda cmd, timeout=25: {
            "wsl": "1", "game_procs": "0"})
        assert "_display" not in svc._read_status()


def test_a_window_that_will_not_open_hands_over_to_the_cards(
        rig, tmp_path, no_procs, monkeypatch, fake_webview):
    from pinball_decryptor.webui import emulate_spike1_core as tks1
    monkeypatch.setenv("PAD_SPIKE1_EMU_DIR", tks1.DEFAULT_RIG_DIR)
    wv = sys.modules["webview"]
    real = wv.create_window

    def create_window(title, url, **kw):
        if url.endswith("view=switches"):
            raise RuntimeError("no web view")
        return real(title, url, **kw)

    monkeypatch.setattr(wv, "create_window", create_window)
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        w.ctx.host = _native_host(w.ctx.token)
        svc = _svc(w)
        running = dict(RUNNING, work="/w", distro="D")
        w.run(svc._apply, running)
        assert _wait(lambda: "could not open the switch window"
                     in _log_text(w))
        w.run(svc._apply, running)          # the next poll
        s = w.state(NS)
        assert s["view_open"] and not s["view_popout"]
        # the display window that did open does not stay up alone
        assert _wait(lambda: bool(fake_webview) and
                     fake_webview[0].calls[-1:] == ["destroy"])
