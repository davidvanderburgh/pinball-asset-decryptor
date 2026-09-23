"""The web UI's Emulate tab (Stern Spike 2), the port of the Tk EmulatePanel.

Driven through the in-process harness exactly as the page drives it: the
``@rpc`` calls run on the UI loop, modals and file pickers are answered from
``w.answers``.  ``PAD_UI_NO_RIG`` is set by the harness, so nothing here can
reach WSL, Docker or the rig: every rig command goes through the service's
``_run`` / ``_popen``, which each test replaces with a recorder.
"""

import json
import os
import subprocess
import sys
import time

import pytest

from tests.webui_harness import web_app

NS = "emulate"


def _svc(w):
    return w.window.service(NS)


def _wait(w, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if w.run(cond):
            return
        time.sleep(0.02)
    raise AssertionError("condition never came true")


def _lines(w):
    key = w.window.current_mfr.key if w.window.current_mfr else ""
    return [e["text"] for e in w.window._log.get(key, ())]


class _Done:
    def __init__(self, out=b"", err=b"", rc=0):
        self.stdout = out
        self.stderr = err
        self.returncode = rc


class _Proc:
    def __init__(self, lines=()):
        self.stdout = iter([ln.encode("utf-8") + b"\n" for ln in lines])
        self.returncode = 0

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0

    def kill(self):
        pass


class _Recorder:
    """Stands in for the service's ``_run`` / ``_popen``."""

    def __init__(self, answers=None, lines=()):
        self.calls = []
        self.answers = answers or {}
        self.lines = lines

    def run(self, cmd, **kw):
        self.calls.append(list(map(str, cmd)))
        joined = " ".join(map(str, cmd))
        for key, value in self.answers.items():
            if key in joined:
                return value
        return _Done()

    def popen(self, cmd, **kw):
        self.calls.append(list(map(str, cmd)))
        return _Proc(self.lines)


@pytest.fixture(autouse=True)
def no_wsl(monkeypatch):
    """Nothing in these tests may start wsl.exe, docker or a rig script:
    any attempt is refused and fails the test."""
    real = subprocess.Popen
    tried = []

    class Guard(real):
        def __init__(self, args, *a, **kw):
            argv = list(args) if isinstance(args, (list, tuple)) \
                else str(args).split()
            name = os.path.basename(str(argv[0] if argv else "")).lower()
            if name in ("wsl.exe", "wsl", "docker", "bash", "env", "open",
                        "osascript") or any(".sh" in str(a) for a in argv):
                tried.append(argv)
                raise OSError("the Emulate tests may not run %s" % name)
            super().__init__(args, *a, **kw)
    monkeypatch.setattr(subprocess, "Popen", Guard)
    yield
    assert not tried, "tried to run: %r" % tried


@pytest.fixture(autouse=True)
def rig_on(monkeypatch):
    """conftest points PAD_EMU_DIR at an empty folder (no rig); most tests
    here want the tab as it is on a machine that has one."""
    from pinball_decryptor.webui import emulate_rig
    monkeypatch.setattr(emulate_rig, "rig_available", lambda: True)


def _own_assets(w, svc):
    """A private stand-in for the Write tab's Assets Folder variable, bound
    the way the service binds the real one (the Write tab's own traces are
    that tab's business, not this test's)."""
    from pinball_decryptor.webui import compat

    def make():
        var = compat.StringVar()
        var.trace_add("write", lambda *_a: svc._overrides_paint())
        svc._assets_var = var
        return var
    return w.run(make)


def _patch(svc, monkeypatch, **kw):
    rec = _Recorder(**kw)
    monkeypatch.setattr(svc, "_run", rec.run)
    monkeypatch.setattr(svc, "_popen", rec.popen)
    return rec


# ---------------------------------------------------------------- gating
@pytest.mark.parametrize("mfr,era,visible", [
    ("stern", "", True), ("stern", "spike1", False),
    ("stern", "whitestar", False), ("jjp", "", False), ("spooky", "", False),
    ("pb", "", False), ("williams", "", False), ("cgc", "", False),
    ("dp", "", False), ("ap", "", False), ("bof", "", False),
    ("data_east", "", False), ("sega", "", False)])
def test_tab_follows_the_capability(tmp_path, mfr, era, visible):
    with web_app(tmp_path, mfr=mfr, era=era or None) as w:
        if mfr not in {m.key for m in w.window.manufacturers}:
            pytest.skip("no %s plugin" % mfr)
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs[NS]["visible"] is visible
        assert tabs[NS]["group"] == "Play"
        s = w.state(NS)
        # the tab's state is there whatever the manufacturer (the Tk panel
        # was built for every one, and its variables persist regardless)
        assert s["vals"]["state"] == "—"
        assert s["run_btn"]["label"] == "Start emulator"
        assert s["countries"][0] == "As set in the game"
        assert len(s["countries"]) == 31
        assert s["powers"] == ["60 Hz mains", "50 Hz mains, European machine",
                               "50 Hz mains, US machine"]
        missing = getattr(w.window, "missing_exports", None) or {}
        for name in _svc(w).exports:
            assert name not in missing


def test_no_rig_on_this_machine(tmp_path, monkeypatch):
    from pinball_decryptor.webui import emulate_core, emulate_rig
    monkeypatch.setattr(emulate_rig, "rig_available",
                        emulate_core.rig_available)
    with web_app(tmp_path, mfr="stern") as w:
        s = w.state(NS)
        assert s["rig"] is False
        assert s["rig_missing"].startswith("The emulator rig was not found in")
        assert s["run_btn"] == {"label": "Start emulator", "enabled": False,
                                "mode": "start"}
        assert s["fixaud_enabled"] is False
        assert s["winreset_enabled"] is False
        assert w.call(NS + ".open_cache") is False
        assert w.state(NS)["hint"] == ("No emulator rig on this machine — "
                                       "there is no card cache to manage.")
        svc = _svc(w)
        assert w.run(svc.launch_with, lambda c: []) is False
        assert svc.last_refusal.startswith("the emulator is not set up")


def test_exports_are_the_run_logic_variables(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        win = w.window
        assert win.emulate_card_var.get() == ""
        assert win.emulate_savestates_var.get() in (True, False)
        assert win.emulate_overrides_var.get() is False
        assert win.emulate_country_var.get() == "As set in the game"
        assert win.emulate_power_var.get() == "60 Hz mains"
        # the page's edit reaches the variable (and its traces)
        w.call("ui.set", NS, "overrides", True)
        assert win.emulate_overrides_var.get() is True
        w.call("ui.set", NS, "country", "Denmark")
        assert win.emulate_country_var.get() == "Denmark"
        svc = _svc(w)
        assert svc.machine_choices("emulate_country")[1] == "U.S.A."
        assert svc.machine_choices("emulate_power")[0] == "60 Hz mains"
        assert svc.machine_choices("other") == []


def test_machine_settings_restore_globally(tmp_path):
    settings = {"emulate_country": "Denmark",
                "emulate_power": "not a real choice"}
    with web_app(tmp_path, mfr="stern", settings=settings) as w:
        w.run(w.app._restore_emulate_machine)
        assert w.window.emulate_country_var.get() == "Denmark"
        assert w.window.emulate_power_var.get() == "60 Hz mains"


def test_no_rig_means_no_probe_and_no_poll(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        w.drain()
        assert svc._poll_job is None
        assert not svc._setup_busy
        assert w.state(NS)["no_rig"] is True
        with pytest.raises(OSError):
            svc._run(["true"])


def test_on_show_paints_the_stern_ladder(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.select_tab", NS)
        footer = w.state("shell")["footer"]
        assert footer["mode"] == "emulate"
        assert footer["phases"] == ["Copy card", "Boot", "Node boards",
                                    "Ready"]
        assert footer["index"] == -1


# ------------------------------------------------------------ Start/Stop
def test_start_refuses_without_a_card(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        w.call(NS + ".toggle")
        s = w.state(NS)
        assert s["hint"].startswith("Pick a card image first")
        assert s["vals"]["state"] == "Not running"
        assert s["run_btn"]["label"] == "Start emulator"
        assert svc.last_refusal == s["hint"]
        w.run(lambda: w.window.emulate_card_var.set(
            str(tmp_path / "missing.raw")))
        w.call(NS + ".toggle")
        assert w.state(NS)["hint"] == "No such image: %s" % (
            tmp_path / "missing.raw")


def test_start_launches_watch_with_the_machine_env(tmp_path, monkeypatch):
    card = tmp_path / "godzilla_le-1_16_0.Release.8G.sdcard.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch, lines=[
            "[card] copying godzilla_le-1_16_0: 3121 / 7497 MB (41%)",
            "[card] local cache ready",
        ])
        w.run(lambda: w.window.emulate_card_var.set(str(card)))
        assert w.state(NS)["game"] == "godzilla_le"
        w.call("ui.set", NS, "country", "Denmark")
        w.call("ui.set", NS, "power", "50 Hz mains, US machine")
        w.call("ui.set", NS, "topper", False)
        w.call(NS + ".set_select", True)
        serial = svc._launch_serial
        w.call(NS + ".toggle")
        _wait(w, lambda: any("watch.sh" in " ".join(c) for c in rec.calls))
        _wait(w, lambda: svc._proc is None and not svc._starting)
        w.drain()
        cmd = next(c for c in rec.calls if "watch.sh" in " ".join(c))
        assert any(a.startswith("PAD_CARD=") for a in cmd)
        assert "PAD_TOPPER=0" in cmd
        assert "PAD_CAB_DIP=9" in cmd and "PAD_COUNTRY=9" in cmd
        assert "PAD_MAINS_HZ=50" in cmd and "PAD_FACTORY_HZ=60" in cmd
        assert "PAD_SELECT=1" in cmd
        assert any(a.startswith("PAD_AUDIO_CTL=") for a in cmd)
        assert svc._launch_serial == serial + 1
        log = _lines(w)
        assert any("[card] copying godzilla_le-1_16_0" in ln for ln in log)


class _LiveProc:
    """A watch.sh that stays up (copying the card) until it is stopped."""

    def __init__(self):
        import threading
        self.gone = threading.Event()
        self.returncode = None

    @property
    def stdout(self):
        def lines():
            yield b"[card] copying godzilla_le-1_16_0: 1349 / 7497 MB (18%)\n"
            self.gone.wait(15)
        return lines()

    def poll(self):
        return 0 if self.gone.is_set() else None

    def wait(self, timeout=None):
        # stop()'s wait: killgame.sh has taken it down
        self.gone.set()
        return 0

    def kill(self):
        self.gone.set()


def test_one_launcher_while_watch_is_up(tmp_path, monkeypatch):
    """Must survive #0: right after watch.sh is launched the one button keeps
    the disabled "Starting…" (as Tk's did) and the rig is asked at once; a
    poll sampled before the rig counted watch.sh cannot offer Start again, and
    neither the button, start() nor launch_with can start a second one."""
    card = tmp_path / "godzilla_le-1_16_0.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        live = _LiveProc()

        def popen(cmd, **kw):
            rec.calls.append(list(map(str, cmd)))
            return live
        monkeypatch.setattr(svc, "_popen", popen)
        polls = []
        monkeypatch.setattr(svc, "_poll_soon", lambda: polls.append(1))
        w.run(lambda: w.window.emulate_card_var.set(str(card)))
        w.call(NS + ".toggle")
        _wait(w, lambda: svc._proc is live and not svc._starting)
        _wait(w, lambda: bool(polls))
        w.drain()

        def watches():
            return [c for c in rec.calls if "watch.sh" in " ".join(c)]
        try:
            assert w.state(NS)["run_btn"] == {
                "label": "Starting…", "enabled": False, "mode": "busy"}
            # a poll that sampled the rig before watch.sh showed up in it
            w.run(svc._apply, {"running": "0", "state": "off", "procs": "0"})
            assert w.state(NS)["run_btn"]["label"] == "Stop emulator"
            # every way in refuses a second launcher
            w.run(svc.start)
            assert svc.last_refusal.startswith("the emulator is already "
                                               "running")
            assert w.run(svc.launch_with, lambda c: []) is False
            assert len(watches()) == 1
            # the button dispatches on what is running: Stop, not Start
            w.call(NS + ".toggle")
            _wait(w, lambda: any("killgame.sh" in " ".join(c)
                                 for c in rec.calls))
            _wait(w, lambda: svc._proc is None and not svc._stopping)
            w.drain()
            assert len(polls) >= 2          # Stop asks the rig again too
            # ...and the verified answer gives the button back
            w.run(svc._apply, {"running": "0", "state": "off", "procs": "0"})
            assert len(watches()) == 1
            assert w.state(NS)["run_btn"] == {
                "label": "Start emulator", "enabled": True, "mode": "start"}
        finally:
            live.gone.set()


def test_no_stale_cancel_once_the_preparation_ends(tmp_path, monkeypatch):
    """The button reads Cancel while a preparation runs, and "Starting…" the
    moment it ends, not a dead Cancel until the next poll."""
    import threading
    card = tmp_path / "godzilla_le-1_16_0.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        hold, entered, gate = (threading.Event(), threading.Event(),
                               threading.Event())

        def popen(cmd, **kw):
            rec.calls.append(list(map(str, cmd)))
            entered.set()
            gate.wait(10)
            return _Proc()
        monkeypatch.setattr(svc, "_popen", popen)

        def prepare(path):
            hold.wait(10)
            return []
        w.run(lambda: w.window.emulate_card_var.set(str(card)))
        try:
            assert w.run(svc.launch_with, prepare) is True
            _wait(w, lambda: svc._preparing is not None)
            w.drain()
            assert w.state(NS)["run_btn"]["label"] == "Cancel"
            hold.set()
            _wait(w, lambda: entered.is_set())
            w.drain()
            assert w.state(NS)["run_btn"] == {
                "label": "Starting…", "enabled": False, "mode": "busy"}
        finally:
            hold.set()
            gate.set()
        _wait(w, lambda: svc._proc is None and not svc._starting)


def test_stop_is_verified_and_offers_the_wsl_cure(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch, answers={
            "killgame.sh": _Done(b"killed 5\nPAD_STOP_NEEDS_WSL_RESTART\n")})
        w.run(lambda: setattr(svc, "_last_up", True))
        w.answers.append("no")
        w.call(NS + ".toggle")
        assert w.state(NS)["vals"]["state"] == "Stopping…"
        assert w.state(NS)["run_btn"]["label"] == "Stopping…"
        _wait(w, lambda: not svc._stopping)
        w.drain()
        assert any("killgame.sh" in " ".join(c) for c in rec.calls)
        if sys.platform == "win32":
            _wait(w, lambda: any("leftovers kept" in ln for ln in _lines(w)))
            assert w.asked[-1]["title"] == "Stop emulator"


def test_apply_paints_the_status_grid_and_footer(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        ended = []
        svc.run_ended_cb = ended.append
        w.call("ui.select_tab", NS)
        w.run(svc._apply, {"running": "1", "state": "attract", "procs": "5",
                           "cpu": "138", "rss": "412", "host_cpu": "23",
                           "fps": "59", "pcm": "1841152", "drop": "96"})
        s = w.state(NS)
        assert s["vals"]["state"] == "Game running"
        assert s["state_kind"] == "ok"
        assert s["state_tip"] == ("Attract loop, operator menu, or a game "
                                  "in play.")
        assert s["vals"]["procs"] == "5 running"
        assert s["vals"]["cpu"] == "138% of one core, 412 MB"
        assert s["vals"]["host"] == "23% CPU, 59 fps"
        assert s["vals"]["audio"] == ("1841152 frames played, 96 dropped"
                                      "   <-- dropping")
        assert s["run_btn"]["label"] == "Stop emulator"
        assert s["fixaud_enabled"] is False and s["winreset_enabled"] is False
        footer = w.state("shell")["footer"]
        assert footer["index"] == 4 and footer["pct"] == 100
        assert footer["status"] == "Game running"
        w.run(svc._apply, {"running": "1", "state": "techalerts",
                           "auto": "1", "procs": "5"})
        assert w.state(NS)["vals"]["state"] == "Bringing up node boards…"
        assert w.state("shell")["footer"]["index"] == 2
        w.run(svc._apply, {"running": "1", "state": "techalerts",
                           "auto": "0", "auto_result": "mainslock",
                           "procs": "5"})
        assert w.state(NS)["vals"]["state"] == "Locked: US machine on 50 Hz"
        assert w.state(NS)["state_kind"] == "warn"
        w.run(svc._apply, {"running": "0", "state": "off", "procs": "0"})
        s = w.state(NS)
        assert s["vals"]["state"] == "Not running"
        assert s["vals"]["procs"] == "0 running  (all stopped)"
        assert s["vals"]["cpu"] == "—"
        assert s["run_btn"]["label"] == "Start emulator"
        assert ended == [svc._launch_serial]
        assert w.state("shell")["footer"]["status"] == "Ready"


def test_copy_and_preparing_hold_the_state_over_the_poll(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        w.call("ui.select_tab", NS)
        w.run(svc._push_copy, "[card] copying x: 1 / 2 MB (50%)", 50)
        svc._copying, svc._copying_pct = "[card] copying x: 1 / 2 MB (50%)", 50
        w.run(svc._apply, {"running": "0", "state": "off", "procs": "0"})
        s = w.state(NS)
        assert s["vals"]["state"].startswith("[card] copying x")
        assert s["state_tip"].startswith("First boot of this card")
        assert w.state("shell")["footer"]["pct"] == 20
        svc._copying = None
        svc.set_preparing("Preparing your modes…", 30)
        w.drain()
        s = w.state(NS)
        assert s["vals"]["state"] == "Preparing your modes…"
        assert s["state_tip"].startswith("Your modes are built")
        assert s["run_btn"]["label"] == "Cancel"
        w.call(NS + ".toggle")
        assert svc.prepare_cancelled() is True
        svc.set_preparing(None)
        w.drain()


def test_launch_with_refuses_beside_the_edits_box(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        assets = _own_assets(w, svc)
        w.run(lambda: assets.set(str(tmp_path)))
        w.call("ui.set", NS, "overrides", True)
        ok = w.run(svc.launch_with, lambda card: [])
        w.drain()
        assert ok is False
        assert "Try it runs your modes as an override set" in svc.last_refusal
        s = w.state(NS)
        assert s["ovr_refused"] is True
        assert s["ovr_hint"] == svc.last_refusal
        # the box or the folder changing takes the refusal down
        w.call("ui.set", NS, "overrides", False)
        assert w.state(NS)["ovr_refused"] is False
        w.run(lambda: setattr(svc, "_last_up", True))
        assert w.run(svc.launch_with, lambda card: []) is False
        assert svc.last_refusal.startswith("the emulator is already running")


def test_launch_with_runs_the_preparation(tmp_path, monkeypatch):
    card = tmp_path / "godzilla_le-1_16_0.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        w.run(lambda: w.window.emulate_card_var.set(str(card)))
        seen = []

        def prepare(path):
            seen.append(path)
            return ["PAD_MODE_SO=/lib/x.so"]
        assert w.run(svc.launch_with, prepare) is True
        _wait(w, lambda: any("watch.sh" in " ".join(c) for c in rec.calls))
        assert seen == [str(card)]
        cmd = next(c for c in rec.calls if "watch.sh" in " ".join(c))
        assert "PAD_MODE_SO=/lib/x.so" in cmd
        _wait(w, lambda: svc._proc is None and not svc._starting)

        # a preparation that says no: its reason stays beside the opt-in
        def refuse(path):
            return None
        refuse.last_reason = "the modes did not build"
        rec.calls.clear()
        assert w.run(svc.launch_with, refuse) is True
        _wait(w, lambda: not svc._starting)
        w.drain()
        assert w.state(NS)["ovr_hint"] == "the modes did not build"
        assert not any("watch.sh" in " ".join(c) for c in rec.calls)


def test_try_it_and_play_bring_the_tab_forward(tmp_path, monkeypatch):
    card = tmp_path / "godzilla_le-1_16_0.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _patch(svc, monkeypatch)
        w.call("ui.select_tab", "extract")
        ok, why = w.run(svc.try_it, lambda c: [])
        assert ok is False and why.startswith("Pick a card image first")
        assert w.state("shell")["tab"] == "extract"
        w.run(lambda: w.window.emulate_card_var.set(str(card)))
        ok, why = w.run(svc.try_it, lambda c: [])
        assert ok is True and why == ""
        assert w.state("shell")["tab"] == NS
        _wait(w, lambda: svc._proc is None and not svc._starting)
        st = w.run(svc.launch_state)
        assert st["card"] == str(card) and st["overrides"] is False
        assert svc.launch_as_root() is False


def test_launch_card_holds_the_boot_selector(tmp_path, monkeypatch):
    card = tmp_path / "multi-1_0.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        w.run(svc.run_card, str(card))
        assert w.state("shell")["tab"] == NS
        assert w.state(NS)["select"] is True
        _wait(w, lambda: any("watch.sh" in " ".join(c) for c in rec.calls))
        cmd = next(c for c in rec.calls if "watch.sh" in " ".join(c))
        assert "PAD_SELECT=1" in cmd


# ---------------------------------------------------------------- volume
def test_volume_and_mute_write_the_live_control_file(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        from pinball_decryptor.webui.tabs import emulate as emod
        w.call("ui.set", NS, "volume", 35)
        w.call("ui.set", NS, "mute", True)
        path = emod.audio_ctl_file()
        assert os.path.dirname(path) == str(tmp_path / "cfg")
        data = json.load(open(path, encoding="utf-8"))
        assert data == {"gain": 0.35, "muted": True}


# ---------------------------------------------------------- card, select
def test_browse_sets_the_card(tmp_path):
    card = tmp_path / "star_wars_le-1_30_0.raw"
    card.write_bytes(b"\0")
    with web_app(tmp_path, mfr="stern") as w:
        w.answers.append(str(card))
        w.call(NS + ".browse")
        assert w.window.emulate_card_var.get() == os.path.normpath(str(card))
        assert w.asked[-1]["title"] == "Pick a Spike 2 card image"
        assert w.state(NS)["game"] == "star_wars_le"


def test_browse_does_no_filesystem_call_on_the_loop(tmp_path, monkeypatch):
    """A card on a sleeping NAS share: Browse works the start folder out of
    the path's text, and never stats it on the UI loop (Tk's Browse made no
    filesystem call at all)."""
    from pinball_decryptor.webui.tabs import emulate as emod
    nas = r"\\sleepy-nas\pinball\cards\godzilla_le-1_16_0.raw"
    with web_app(tmp_path, mfr="stern") as w:
        w.run(lambda: w.window.emulate_card_var.set(nas))

        touched = []

        def guard(real):
            def fn(p, *a, **k):
                if "sleepy-nas" in str(p):
                    touched.append(p)
                    raise OSError("the share is asleep")
                return real(p, *a, **k)
            return fn

        def no_stat(*_a, **_k):
            raise AssertionError("Browse touched the filesystem on the loop")
        monkeypatch.setattr(w.window, "_initialdir_for", no_stat)
        with monkeypatch.context() as m:
            for mod, name in ((emod.os.path, "isdir"), (emod.os.path, "exists"),
                              (emod.os.path, "isfile"), (emod.os, "stat")):
                m.setattr(mod, name, guard(getattr(mod, name)))
            w.answers.append("")
            assert w.call(NS + ".browse") == ""
        assert touched == []
        assert w.asked[-1]["kind"] == "file"
        assert w.asked[-1]["initialdir"] == os.path.dirname(nas)
        assert w.window.emulate_card_var.get() == nas


def test_boot_selector_the_card_decides_a_hand_overrides(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        w.run(lambda: w.window.emulate_card_var.set("x-1.raw"))
        w.run(svc._select_apply, "x-1.raw", "yes", "images.conf names 3 "
              "images", (1, 2))
        s = w.state(NS)
        assert s["select"] is True
        assert s["select_tip"].startswith("This card carries a boot menu "
                                          "(images.conf names 3 images)")
        w.call(NS + ".set_select", False)
        w.run(svc._select_apply, "x-1.raw", "yes", "again", (1, 2))
        assert w.state(NS)["select"] is False       # the hand wins
        assert "PAD_SELECT=0" in w.run(svc._launch_env, ["PAD_CARD=x"])
        # a new card forgets the verdict and the touch
        w.run(lambda: w.window.emulate_card_var.set("y-1.raw"))
        assert svc._select_touched is False
        w.run(svc._select_apply, "y-1.raw", "no", "no codeselect on the card",
              (3, 4))
        assert w.state(NS)["select_tip"].startswith(
            "This card has no boot menu - no codeselect on the card")
        assert not any(a.startswith("PAD_SELECT")
                       for a in w.run(svc._launch_env, ["PAD_CARD=y"]))


def test_overrides_hint_follows_the_box_and_folder(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        from pinball_decryptor.webui import emulate_rig as rig
        assets = _own_assets(w, _svc(w))
        w.run(lambda: assets.set(""))
        assert w.state(NS)["ovr_hint"] == rig.OVR_OFF
        w.call("ui.set", NS, "overrides", True)
        assert w.state(NS)["ovr_hint"] == rig.OVR_NO_ASSETS
        w.run(lambda: assets.set(str(tmp_path)))
        s = w.state(NS)
        assert s["assets"] == str(tmp_path)
        # the WHOLE Tk paragraph is on the page, not its first sentence: it
        # names the wait and that a Replace-tab pick is written into the
        # project folder at Start (must survive #4)
        assert s["ovr_hint"] == rig.OVR_ON
        assert "ovr_short" not in s
        assert "Start prepares them first" in s["ovr_hint"]
        assert "Start applies it to your project folder" in s["ovr_hint"]


def test_overrides_refuse_without_a_baseline(tmp_path, monkeypatch):
    card = tmp_path / "godzilla_le-1_16_0.raw"
    card.write_bytes(b"\0" * 512)
    assets = tmp_path / "assets"
    assets.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        own = _own_assets(w, svc)
        w.run(lambda: own.set(str(assets)))
        w.run(lambda: w.window.emulate_card_var.set(str(card)))
        w.call("ui.set", NS, "overrides", True)
        w.call(NS + ".toggle")
        _wait(w, lambda: not svc._starting)
        w.drain()
        s = w.state(NS)
        assert s["ovr_refused"] is True
        assert "has no .checksums.md5 baseline" in s["ovr_hint"]
        assert s["vals"]["state"] == "Not running"
        assert not any("watch.sh" in " ".join(c) for c in rec.calls)


# ------------------------------------------------------------ save states
_SLOTS = [["godzilla_le/slot1", str(96 << 20), "godzilla_le",
           "Kaiju Rush start", "1758050640"],
          ["godzilla_le/slot2", str(1288490188), "godzilla_le", "",
           "1758101460"],
          ["star_wars_le/slot4", str(88 << 20), "star_wars_le",
           "before wizard", "1756559520"]]


def _slots(w, svc):
    def fill():
        svc._slots_rows = [list(r) for r in _SLOTS]
        svc._slots_total = 1500000000
        svc._slots_free = 65712999999
        svc._slots_paint()
    w.run(fill)


def test_slots_not_read_yet_is_not_no_slots(tmp_path):
    """Before the first slot read (and all through a WSL boot) the table
    claims nothing: the page shows "No save states" only after a read that
    answered, and a failed read says so in the summary instead."""
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        s = w.state(NS)
        assert s["slots"] == [] and s["slots_read"] is False

        def failed():
            svc._slots_rows, svc._slots_total, svc._slots_free = [], None, None
            svc._slots_paint()
        w.run(failed)
        s = w.state(NS)
        assert s["slots_read"] is False
        assert s["slots_sum"] == "Could not read the slots - is WSL up?"

        def empty():
            svc._slots_rows, svc._slots_total, svc._slots_free = [], 0, 1 << 30
            svc._slots_paint()
        w.run(empty)
        assert w.state(NS)["slots_read"] is True


def test_slots_are_scoped_to_the_card(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _slots(w, svc)
        assert w.state(NS)["slots_read"] is True
        assert len(w.state(NS)["slots"]) == 3
        assert w.state(NS)["slots_sum"].startswith("3 slots · all slots")
        w.run(lambda: w.window.emulate_card_var.set(
            r"D:\cards\godzilla_le-1_16_0.Release.8G.sdcard.raw"))
        s = w.state(NS)
        assert [r["slot"] for r in s["slots"]] == ["slot1", "slot2"]
        assert s["slots"][0]["name"] == "Kaiju Rush start"
        assert s["slots"][0]["size"] == "96 MB"
        assert s["slots"][1]["size"] == "1.2 GB"
        assert s["slots_sum"] == ("2 slots for godzilla_le · 1 for other game "
                                  "hidden · all slots 1.4 GB · free on the "
                                  "WSL disk: 61.2 GB")


def test_slot_guards_and_launch(tmp_path, monkeypatch):
    card = tmp_path / "godzilla_le-1_16_0.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        _slots(w, svc)
        w.call(NS + ".slot_launch")
        assert w.state(NS)["slots_sum"] == "Pick a slot to launch first."
        w.call(NS + ".slot_rename_begin")
        assert w.state(NS)["slots_sum"] == "Pick a slot to rename first."
        w.call(NS + ".slot_delete")
        assert w.state(NS)["slots_sum"] == "Pick a slot to delete first."
        w.run(lambda: w.window.emulate_card_var.set(
            str(tmp_path / "star_wars_le-1_30_0.raw")))
        assert w.call(NS + ".select_slot", "star_wars_le/slot4") is True
        w.run(lambda: w.window.emulate_card_var.set(str(card)))
        # the slot went out of scope with the card: nothing selected
        assert w.state(NS)["slot_sel"] is None
        w.call(NS + ".select_slot", "godzilla_le/slot1")
        w.call(NS + ".slot_launch")
        assert svc._launch_slot == "godzilla_le/slot1"
        assert any("will load slot 'godzilla_le/slot1' once the game is up"
                   in ln for ln in _lines(w))
        _wait(w, lambda: any("watch.sh" in " ".join(c) for c in rec.calls))
        cmd = next(c for c in rec.calls if "watch.sh" in " ".join(c))
        assert "PAD_SELECT=0" in cmd
        _wait(w, lambda: svc._proc is None and not svc._starting)
        # up: Launch loads into the run
        rec.calls.clear()
        w.run(lambda: setattr(svc, "_last_up", True))
        w.call(NS + ".slot_launch")
        assert w.state(NS)["vals"]["state"] == "Loading save…"
        _wait(w, lambda: any("loadgame.sh" in " ".join(c) for c in rec.calls))
        _wait(w, lambda: not svc._loading)


def test_slot_foreign_title_is_refused(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _slots(w, svc)
        w.call(NS + ".select_slot", "star_wars_le/slot4")
        w.run(lambda: setattr(svc, "_slot_sel", "star_wars_le/slot4"))
        w.run(lambda: w.window.emulate_card_var.set("godzilla_le-1_16_0.raw"))
        w.run(lambda: svc._slot_by_iid.__setitem__(
            "star_wars_le/slot4", {"game": "star_wars_le", "size": "88 MB"}))
        w.run(lambda: setattr(svc, "_slot_sel", "star_wars_le/slot4"))
        w.call(NS + ".slot_launch")
        assert w.state(NS)["slots_sum"] == ("That save is for star_wars_le - "
                                            "pick that title's card first.")


def test_slot_rename_filters_and_delete_confirms(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        listing = "".join("slot|%s\n" % "|".join(r) for r in _SLOTS) + \
            "total|1500000000\nfree|65712999999\n"
        rec = _patch(svc, monkeypatch, answers={
            "slots.sh list": _Done(listing.encode()),
            "slots.sh": _Done(b"labelled godzilla_le/slot1\n")})
        _slots(w, svc)
        w.call(NS + ".select_slot", "godzilla_le/slot1")
        w.call(NS + ".slot_rename_begin")
        assert w.state(NS)["rename"] == {"slot": "godzilla_le/slot1",
                                         "value": "Kaiju Rush start"}
        w.call(NS + ".slot_rename", "Wizard; rm -rf / $(x) " + "y" * 60)
        assert w.state(NS)["rename"] is None
        _wait(w, lambda: any("label" in c for c in rec.calls))
        cmd = next(c for c in rec.calls if "label" in c)
        label = cmd[-1]
        assert label.startswith("Wizard rm -rf  (x) yyy")
        assert len(label) <= 40 and ";" not in label and "$" not in label
        _wait(w, lambda: w.state(NS)["slots_enabled"] is True)
        if sys.platform == "win32":     # the list is read again after a change
            _wait(w, lambda: any(c[-1] == "list" for c in rec.calls))
            time.sleep(0.2)
            w.drain()
        w.call(NS + ".select_slot", "godzilla_le/slot1")
        w.answers.append("no")
        assert w.call(NS + ".slot_delete") is False
        assert w.asked[-1]["title"] == "Delete save state"
        assert w.asked[-1]["message"].startswith(
            "Delete slot 'godzilla_le/slot1' (96 MB)?")
        w.answers.append("yes")
        rec.calls.clear()
        assert w.call(NS + ".slot_delete") is True
        _wait(w, lambda: any("delete" in c for c in rec.calls))


# ------------------------------------------------------------ card cache
_CACHE = ("entry\tgodzilla_le-1_16_0\t6606028\t7680000\t0\tD:\\Pinball\\cards\\"
          "godzilla_le-1_16_0.raw\n"
          "entry\tjurassic_park_le-1_16_0\t6396314\t7680000\t0\tD:\\x y\\jp.raw\n"
          "disk\t64172851\t262144000\n")


def test_card_cache_manager(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch, answers={
            "--cache-list": _Done(_CACHE.encode()),
            "--cache-drop": _Done(b"dropped\n")})
        assert w.call(NS + ".open_cache") is True
        _wait(w, lambda: (w.state(NS)["cache"] or {}).get("busy") is False)
        c = w.state(NS)["cache"]
        assert [r["label"] for r in c["rows"]] == ["godzilla_le-1_16_0",
                                                   "jurassic_park_le-1_16_0"]
        assert c["rows"][0]["size"] == "6.3 GB"
        assert c["rows"][0]["booted"] == "never"
        assert c["head"] == ("2 cached cards — 12.4 GB on disk · 61.2 GB "
                             "free of 250.0 GB (WSL disk)")
        assert w.call(NS + ".cache_select", ["godzilla_le-1_16_0", "nope"]) == 1
        w.answers.append("no")
        assert w.call(NS + ".cache_delete") is False
        assert w.asked[-1]["message"].startswith(
            "Delete 1 cached card, freeing about 6.3 GB?")
        w.answers.append("yes")
        assert w.call(NS + ".cache_delete") is True
        _wait(w, lambda: any("--cache-drop" in c for c in rec.calls))
        _wait(w, lambda: (w.state(NS)["cache"] or {}).get("busy") is False)
        w.call(NS + ".cache_close")
        assert w.state(NS)["cache"] is None


# ------------------------------------------------- setup, runtime, Docker
def test_check_setup_without_a_rig_says_so(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        assert w.call(NS + ".check_setup") is False
        assert w.state(NS)["check_label"] == "Check setup…"
        assert w.state(NS)["check_enabled"] is True
        log = _lines(w)
        assert "[emulate] checking what this PC needs…" in log


def test_setup_notice_and_fix_button(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        from pinball_decryptor.webui import emulate_rig as rig
        svc = _svc(w)
        monkeypatch.setattr(rig, "setup_settled", lambda f: False)
        monkeypatch.setattr(rig, "setup_fixable", lambda f: True)
        monkeypatch.setattr(rig, "setup_notice",
                            lambda f, can_fix: "This PC cannot run the "
                                               "emulator yet.")
        monkeypatch.setattr(rig, "setup_report", lambda f: ["setup check:"])
        svc._setup_report_next = True
        w.run(svc._setup_apply, {"x": 1})
        s = w.state(NS)
        assert s["setup_msg"] == "This PC cannot run the emulator yet."
        assert s["setup_btn"] is (sys.platform == "win32")
        assert "[emulate] setup check:" in _lines(w)
        monkeypatch.setattr(rig, "setup_settled", lambda f: True)
        w.run(svc._setup_apply, {"x": 1})
        assert w.state(NS)["setup_msg"] == ""
        assert w.state(NS)["setup_btn"] is False


def test_setup_fix_asks_with_every_step(tmp_path, monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Set up emulator… is the WSL route")
    with web_app(tmp_path, mfr="stern") as w:
        from pinball_decryptor.webui import emulate_rig as rig
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        monkeypatch.setattr(rig, "setup_fix_steps",
                            lambda f: ["Install in WSL:  ffmpeg"])
        w.answers.append("no")
        assert w.call(NS + ".setup_fix") is False
        q = w.asked[-1]
        assert q["title"] == "Set up the emulator"
        assert "  •  Install in WSL:  ffmpeg" in q["message"]
        assert not rec.calls


def test_runtime_notice_only_when_stale(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        w.run(svc._runtime_apply, ("absent", ""))
        assert w.state(NS)["rt_msg"] == ""
        w.run(svc._runtime_apply, ("stale", "old"))
        s = w.state(NS)
        assert s["rt_msg"].startswith("The emulator's Linux is from an older")
        assert s["rt_btn"] is (sys.platform == "win32")
        w.run(svc._runtime_apply, ("foreign", ""))
        assert w.state(NS)["rt_btn"] is False
        assert "will not touch it" in w.state(NS)["rt_msg"]


def test_runtime_replace_asks_the_one_consent(tmp_path, monkeypatch):
    """Replacing the emulator's Linux deletes save states: the question is
    ``_runtime_ui.ask_before_replacing``'s own (one wording), on the page."""
    from pinball_decryptor.webui import emulate_rig as rig
    from pinball_decryptor.webui.tabs import emulate as emod
    with web_app(tmp_path, mfr="stern") as w:
        seen = []

        def ensure(say, progress=None, ask=None, on_blocked=None):
            seen.append(ask())
            return "stale"
        monkeypatch.setattr(rig._runtime_ui, "ensure", ensure)
        assert not hasattr(rig, "replace_runtime_question")
        with monkeypatch.context() as m:
            m.setattr(emod, "no_rig", lambda: False)
            w.answers.append("no")
            assert w.call(NS + ".runtime_fix") is True
            _wait(w, lambda: w.state(NS)["rt_enabled"] is True)
        assert seen == [False]
        asked = w.asked[-1]
        assert asked["title"] == "Replace the emulator's Linux?"
        assert "any SAVE STATES you made while running in it" in \
            asked["message"]


def test_runtime_from_a_file_installs_off_the_loop(tmp_path, monkeypatch):
    """The blocked-download route: the questions on the page (the replace one
    is _runtime_ui's own), and the status check and the install on a
    worker, never on the UI loop."""
    import threading
    from pinball_decryptor.core import runtime
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        loop_thread = w.run(threading.current_thread)
        where = []

        def status(*_a, **_k):
            where.append(threading.current_thread())
            return ("stale", "old")

        def install(**kw):
            where.append(threading.current_thread())
            installs.append(kw)
        installs = []
        monkeypatch.setattr(runtime, "status", status)
        monkeypatch.setattr(runtime, "install", install)
        image = tmp_path / runtime.IMAGE.filename
        image.write_bytes(b"x")
        w.answers.extend(["yes", str(image), "yes"])
        w.run(svc._offer_from_file, RuntimeError("the download was blocked"))
        _wait(w, lambda: bool(installs))
        titles = [a["title"] for a in w.asked[-3:]]
        assert titles == ["Install the runtime from a file",
                          "Choose the downloaded %s" % runtime.IMAGE.filename,
                          "Replace the emulator's Linux?"]
        assert w.asked[-3]["message"].startswith("the download was blocked")
        assert installs[0]["source"] == str(image)
        assert installs[0]["replace"] is True
        assert loop_thread not in where


def test_docker_notice_states(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        from pinball_decryptor.webui import emulate_rig as rig
        svc = _svc(w)
        monkeypatch.setattr(rig, "engine_setup_plan", lambda cli=None: None)
        w.run(svc._docker_apply, "stopped")
        s = w.state(NS)
        assert s["docker_btn"] == "Start Docker"
        assert s["docker_msg"].startswith("Docker is installed but not "
                                          "running")
        w.run(svc._docker_apply, "absent")
        assert w.state(NS)["docker_btn"] == "Get Docker…"
        w.run(svc._docker_apply, "ok")
        assert w.state(NS)["docker_msg"] == ""
        assert w.state(NS)["docker_btn"] is None


# ------------------------------------------------ Restart WSL / windows
def test_restart_wsl_and_reset_windows_refuse_while_up(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        w.run(lambda: setattr(svc, "_last_up", True))
        assert w.call(NS + ".reset_windows") is False
        assert w.asked[-1]["title"] == "Reset windows"
        assert w.asked[-1]["message"].startswith("Stop the emulator first.")
        if sys.platform == "win32":
            assert w.call(NS + ".restart_wsl") is False
            assert w.asked[-1]["title"] == "Restart WSL"
        else:
            assert w.call(NS + ".restart_wsl") is False
        assert not rec.calls


def test_reset_windows_runs_winreset(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        from pinball_decryptor.webui import emulate_rig as rig
        svc = _svc(w)
        rec = _patch(svc, monkeypatch, answers={
            "winreset.sh": _Done(b"forgot ~/.pad_windows\n")})
        monkeypatch.setattr(rig, "forget_playfield_pos",
                            lambda: "forgot the playfield window position "
                                    "(10, 20)")
        w.answers.append("yes")
        assert w.call(NS + ".reset_windows") is True
        assert w.asked[-1]["message"].startswith(
            "Forget where the emulator windows were?")
        _wait(w, lambda: not svc._winresetting)
        w.drain()
        assert any("winreset.sh" in " ".join(c) for c in rec.calls)
        assert any("forgot the playfield window position" in ln
                   for ln in _lines(w))
        assert w.state(NS)["winreset_enabled"] is True


def test_restart_wsl_shuts_wsl_down(tmp_path, monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Restart WSL… is Windows only")
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        w.answers.append("yes")
        assert w.call(NS + ".restart_wsl") is True
        assert w.state(NS)["vals"]["state"] == "Restarting WSL…"
        _wait(w, lambda: not svc._resetting)
        w.drain()
        joined = [" ".join(c) for c in rec.calls]
        assert any("killgame.sh" in c for c in joined)
        assert "wsl.exe --shutdown" in joined
        assert any("WSL is down; it restarts by itself" in ln
                   for ln in _lines(w))


# ---------------------------------------------------------------- quit
def test_shutdown_takes_a_run_down(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        w.run(w.window.emulate_shutdown)
        assert rec.calls == []
        w.run(lambda: setattr(svc, "_last_up", True))
        w.run(w.window.emulate_shutdown)
        assert any("killgame.sh" in " ".join(c) for c in rec.calls)
