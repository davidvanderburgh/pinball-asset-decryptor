"""PAD-735: a Restart game button for the Spike 2 emulator.

David: "I want a restart game button in the spike 2 emulator - should be the
same as restarting the whole game". So it is Stop then Start: the game shut
down and booted again. The Emulate tab carries it beside Stop emulator; the
virtual playfield window's status bar carries it beside Pause, and asks the
app that launched the run through a request file (one per rig) beside the
volume file, because the app's Stop closes that window.
"""

import os
import sys
import time

import pytest

from tests.webui_harness import web_app
from tests.test_webui_emulate import (NS, _lines, _patch, _svc, _wait,  # noqa: F401
                                      no_wsl, rig_on)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
if RIG not in sys.path:
    sys.path.insert(0, RIG)
# imported here, outside the Emulate tests' no-wsl guard: the playfield
# module asks WSL where its rig is when it loads
try:
    import playfield as pf
except Exception:                                        # noqa: BLE001
    pf = None
needs_pf = pytest.mark.skipif(pf is None, reason="playfield not importable")


def _text(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf8", newline="") as f:
        return f.read()


def test_restart_stops_the_game_then_starts_it_again(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        starts = []
        monkeypatch.setattr(svc, "start", lambda: starts.append(1))
        w.run(lambda: setattr(svc, "_last_up", True))
        w.run(svc._paint_run_btn)
        assert w.state(NS)["run_btn"]["mode"] == "stop"
        assert w.call(NS + ".restart") is True
        assert w.state(NS)["run_btn"] == {
            "label": "Restarting…", "enabled": False, "mode": "busy"}
        _wait(w, lambda: not svc._stopping)
        assert any("killgame.sh" in " ".join(c) for c in rec.calls)
        # a second press while it restarts does nothing
        assert w.call(NS + ".restart") is False
        assert not starts                      # the rig still says it is up
        w.run(svc._apply, {"running": "0", "state": "off", "procs": "0"})
        _wait(w, lambda: bool(starts))
        assert starts == [1] and svc._restart_wait == 0
        assert any("restarting the game" in ln for ln in _lines(w))


def test_restart_needs_a_running_game(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        assert w.call(NS + ".restart") is False
        w.run(lambda: setattr(svc, "_last_up", True))
        w.run(lambda: setattr(svc, "_starting", True))
        assert w.call(NS + ".restart") is False
        assert not rec.calls


def test_a_restart_that_never_sees_the_game_down_gives_the_button_back(
        tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _patch(svc, monkeypatch)
        monkeypatch.setattr(svc, "start", lambda: pytest.fail("started"))
        w.run(lambda: setattr(svc, "_last_up", True))
        w.run(lambda: setattr(svc, "_restart_wait", 1))
        w.run(svc._restart_when_down)
        assert svc._restart_wait == 0
        assert w.state(NS)["run_btn"]["label"] == "Stop emulator"
        assert any("did not stop in time" in ln for ln in _lines(w))


@needs_pf
def test_the_playfield_window_asks_through_the_request_file(tmp_path, monkeypatch):
    """The window writes the file the tab's poll reads: same folder (the
    volume file's), same name (this rig's)."""
    monkeypatch.setenv("PAD_SLOT", "3")
    with web_app(tmp_path, mfr="stern") as w:
        from pinball_decryptor.webui.tabs import emulate as emod
        svc = _svc(w)
        asked = []
        monkeypatch.setattr(svc, "restart", lambda: asked.append(1) or True)
        ctl = emod.audio_ctl_file()
        os.makedirs(os.path.dirname(ctl), exist_ok=True)
        assert pf.restart_req_path(ctl) == emod.restart_req_file()
        assert emod.restart_req_file().endswith("restart_game_3.req")
        run = pf.RunCtl(ctl)
        assert run.dyn()["restart"] is True
        assert run.ask_restart() is True
        w.run(svc._follow_restart_req)
        assert asked == [1]
        assert not os.path.exists(emod.restart_req_file())   # used once
        w.run(svc._follow_restart_req)
        assert asked == [1]
        # a request left over from a run that is gone is dropped, not acted on
        assert run.ask_restart() is True
        old = time.time() - emod.RESTART_REQ_S - 5
        os.utime(emod.restart_req_file(), (old, old))
        w.run(svc._follow_restart_req)
        assert asked == [1]
        assert not os.path.exists(emod.restart_req_file())


@needs_pf
def test_a_window_with_no_app_has_no_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(pf, "SW_PATH", str(tmp_path / "gone"))
    run = pf.RunCtl(None)
    assert run.dyn()["restart"] is False
    assert run.ask_restart() is False
    ctl = types_ns(keys=None, run=run)
    assert pf.Playfield.api_restart(ctl) is False


def types_ns(**kw):
    import types
    return types.SimpleNamespace(**kw)


def test_the_pages_draw_the_buttons():
    js = _text("pinball_decryptor", "webui", "static", "js", "tabs", "emulate.js")
    body = js[js.index("function RunButton("):]
    body = body[:body.index("\nfunction ")]
    assert 'call("emulate.restart")' in body and "Restart game" in body
    assert 'b.mode !== "stop"' in body          # only beside Stop emulator
    pf_js = _text("tools", "spike2_emu", "pfpage", "pf.js")
    body = pf_js[pf_js.index("function runCluster(R)"):]
    body = body[:body.index("\n  }\n") + 4]
    assert 'api("restart")' in body and "R.restart" in body
