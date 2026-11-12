"""PAD-1198: stop the emulator from the virtual playfield window.

David: "need a way to stop the emulator from the virtual playfield window -
maybe a button for stop next to pause. or when i x the window it should stop
the emulator. same for spike 2". Both: a Stop emulator button beside Pause,
and the window's X asks the same (as closing the game window ends the run).
The window cannot end the run itself - it is the app's, Spike 2 or Spike 3 -
so it asks through a request file beside Restart game's (PAD-735), one per
rig, and the Emulate tab's poll runs its own Stop.

An app on rig 0 runs a Spike 3 card on rig 1, and the window names its files
by its own rig: the tab reads both, which also puts right Restart game from a
Spike 3 window (it was written to restart_game_1.req and never read).
"""

import io
import os
import sys
import time
import types

import pytest

from tests.webui_harness import web_app
from tests.test_webui_emulate import NS, _lines, _patch, _svc  # noqa: F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
if RIG not in sys.path:
    sys.path.insert(0, RIG)
try:
    import playfield as pf
except Exception:                                        # noqa: BLE001
    pf = None
needs_pf = pytest.mark.skipif(pf is None, reason="playfield not importable")


def _text(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf8", newline="") as f:
        return f.read()


def _ctl_dir():
    from pinball_decryptor.webui.tabs import emulate as emod
    ctl = emod.audio_ctl_file()
    os.makedirs(os.path.dirname(ctl), exist_ok=True)
    return emod, ctl


@needs_pf
def test_the_window_stop_reaches_the_tab_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_SLOT", "3")
    with web_app(tmp_path, mfr="stern") as w:
        emod, ctl = _ctl_dir()
        svc = _svc(w)
        stops = []
        monkeypatch.setattr(svc, "stop", lambda: stops.append(1))
        assert pf.stop_req_path(ctl) == emod.stop_req_file()
        assert emod.stop_req_file().endswith("stop_emulator_3.req")
        run = pf.RunCtl(ctl)
        assert run.dyn()["stop"] is True and run.dyn()["stopping"] is False
        assert run.ask_stop() is True
        assert run.dyn()["stopping"] is True
        w.run(lambda: setattr(svc, "_last_up", True))
        assert w.run(svc._follow_stop_req) is True
        assert stops == [1]
        assert not os.path.exists(emod.stop_req_file())          # used once
        assert any("asked for by the playfield window" in ln for ln in _lines(w))
        assert w.run(svc._follow_stop_req) is False
        assert stops == [1]


@needs_pf
def test_a_stop_with_nothing_running_or_stale_ends_nothing(tmp_path, monkeypatch):
    """A window that closed with its run, a request from long ago, or one that
    lands while the tab is already stopping: taken away, nothing stopped -
    least of all the next run."""
    monkeypatch.setenv("PAD_SLOT", "2")
    with web_app(tmp_path, mfr="stern") as w:
        emod, ctl = _ctl_dir()
        svc = _svc(w)
        monkeypatch.setattr(svc, "stop", lambda: pytest.fail("stopped"))
        run = pf.RunCtl(ctl)
        # nothing up
        assert run.ask_stop() is True
        assert w.run(svc._follow_stop_req) is False
        assert not os.path.exists(emod.stop_req_file())
        # up, but the request is from a run that is gone
        w.run(lambda: setattr(svc, "_last_up", True))
        assert run.ask_stop() is True
        old = time.time() - emod.RESTART_REQ_S - 5
        os.utime(emod.stop_req_file(), (old, old))
        assert w.run(svc._follow_stop_req) is False
        assert not os.path.exists(emod.stop_req_file())
        # up and already stopping
        w.run(lambda: setattr(svc, "_stopping", True))
        assert run.ask_stop() is True
        assert w.run(svc._follow_stop_req) is False


@needs_pf
def test_start_clears_a_stop_left_behind(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_SLOT", "2")
    with web_app(tmp_path, mfr="stern") as w:
        emod, ctl = _ctl_dir()
        svc = _svc(w)
        _patch(svc, monkeypatch)
        assert pf.RunCtl(ctl).ask_stop() is True
        w.run(lambda: setattr(svc, "_proc", types.SimpleNamespace(poll=lambda: None)))
        w.run(svc.start)                     # refused: one is running
        assert not os.path.exists(emod.stop_req_file())


@needs_pf
def test_a_spike3_window_on_another_rig_is_heard(tmp_path, monkeypatch):
    """The app is rig 0, its Spike 3 run rig 1 (``slot or 1``): the window's
    Stop and Restart game land as rig 1's files, and the tab reads them."""
    monkeypatch.delenv("PAD_SLOT", raising=False)
    with web_app(tmp_path, mfr="stern") as w:
        emod, ctl = _ctl_dir()
        svc = _svc(w)
        asked = []
        monkeypatch.setattr(svc, "stop", lambda: asked.append("stop"))
        monkeypatch.setattr(svc, "restart", lambda: asked.append("restart") or True)
        w.run(lambda: setattr(svc, "_s3_slot", 1))
        monkeypatch.setenv("PAD_SLOT", "1")           # the window's own rig
        run = pf.RunCtl(ctl)
        assert run.ask_stop() is True and run.ask_restart() is True
        monkeypatch.delenv("PAD_SLOT")
        assert os.path.exists(emod.stop_req_file(1))
        assert emod.stop_req_file() != emod.stop_req_file(1)
        w.run(svc._follow_restart_req)
        assert w.run(svc._follow_stop_req) is True
        assert asked == ["restart", "stop"]
        assert not os.path.exists(emod.stop_req_file(1))
        assert not os.path.exists(emod.restart_req_file(1))


@needs_pf
def test_closing_the_window_asks_for_a_stop_unless_the_run_left(tmp_path,
                                                               monkeypatch):
    monkeypatch.setenv("PAD_SLOT", "0")
    ctl = str(tmp_path / "audio_ctl.json")
    req = pf.stop_req_path(ctl)

    def window(**kw):
        byes = []
        ns = types.SimpleNamespace(run=pf.RunCtl(ctl), _run_left=False,
                                   _closed=False,
                                   host=types.SimpleNamespace(_ready=True),
                                   bye=lambda: byes.append(1))
        for k, v in kw.items():
            setattr(ns, k, v)
        pf.Playfield.closed_by_user(ns)
        return byes

    # the X: the run is asked to stop, and the window still lets go of
    # everything it holds
    assert window() == [1] and os.path.exists(req)
    os.remove(req)
    # the run went first (the app's Stop, the game ended): no second Stop
    assert window(_run_left=True) == [1] and not os.path.exists(req)
    # a window that never came up was closed by no one
    assert window(host=types.SimpleNamespace(_ready=False)) == [1]
    assert not os.path.exists(req)
    # already closed (bye ran): nothing more
    assert window(_closed=True) == [1] and not os.path.exists(req)
    # a window with no app (the demo, a session's own run) has no Stop
    byes = []
    ns = types.SimpleNamespace(run=pf.RunCtl(None), _run_left=False,
                               _closed=False, host=None,
                               bye=lambda: byes.append(1))
    pf.Playfield.closed_by_user(ns)
    assert byes == [1] and ns.run.dyn()["stop"] is False


@needs_pf
def test_gone_marks_the_run_as_left(monkeypatch):
    ns = types.SimpleNamespace(_run_left=False, host=None,
                               save_state=lambda: None,
                               publish=lambda *a: None,
                               _stop=types.SimpleNamespace(set=lambda: None))
    pf.Playfield.gone(ns)
    assert ns._run_left is True


@needs_pf
def test_api_stop_publishes_stopping(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_SLOT", "0")
    said = []
    ns = types.SimpleNamespace(run=pf.RunCtl(str(tmp_path / "a.json")),
                               publish=lambda *a: said.append(a))
    assert pf.Playfield.api_stop(ns) is True
    assert said and said[-1][0] == "run" and said[-1][1]["stopping"] is True
    ns = types.SimpleNamespace(run=pf.RunCtl(None), publish=lambda *a: said.append(a))
    assert pf.Playfield.api_stop(ns) is False


def test_the_page_puts_stop_beside_pause():
    pf_js = _text("tools", "spike2_emu", "pfpage", "pf.js")
    body = pf_js[pf_js.index("function runCluster(R)"):]
    body = body[:body.index("\n  }\n") + 4]
    assert 'api("stop")' in body and "R.stop" in body and "r.stopping" in body
    assert "Stop emulator" in body and "Stopping…" in body
    # straight after Pause, before Restart game
    assert body.index("box.append(pause)") < body.index("box.append(stop)") \
        < body.index("box.append(restart)")
    assert "host.run(ctl.window_spec(), on_close=ctl.closed_by_user)" in \
        _text("tools", "spike2_emu", "playfield.py")


def test_the_mac_box_relays_the_stop(tmp_path, monkeypatch):
    """padbox (Mac): the window in the box writes the request; boxctl.py says
    STOP and padbox.sh's ctl_apply writes it beside the app's files."""
    sys.path.insert(0, os.path.join(RIG, "docker"))
    try:
        import boxctl
    finally:
        sys.path.pop(0)
    monkeypatch.setenv("PAD_SLOT", "0")
    out = io.StringIO()
    box = boxctl.BoxCtl(str(tmp_path), out=out)
    (tmp_path / "stop_emulator_0.req").write_text("0\n")
    box.poll()
    assert "STOP" in out.getvalue().split()
    assert not (tmp_path / "stop_emulator_0.req").exists()
    sh = _text("tools", "spike2_emu", "docker", "padbox.sh")
    assert 'STOP) printf \'%s\\n\' "$slot" > "$dir/stop_emulator_$slot.req"' in sh
