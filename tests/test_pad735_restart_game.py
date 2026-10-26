"""PAD-735: a Restart game button for the Spike 2 emulator.

David: "I want a restart game button in the spike 2 emulator - should be the
same as restarting the whole game". The Emulate tab carries it beside Stop
emulator; the virtual playfield window's status bar carries it beside Pause,
and asks the app that launched the run through a request file (one per rig)
beside the volume file. PAD-738: it reboots only the game, inside the run
(restartgame.sh), so the playfield window stays open; Stop then Start is the
fallback for a run that does not take the request.
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


def test_restart_asks_the_run_to_reboot_the_game(tmp_path, monkeypatch):
    """PAD-738: the run reboots the game itself (restartgame.sh); nothing is
    stopped, so the playfield window stays open."""
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        monkeypatch.setattr(svc, "start", lambda: pytest.fail("started"))
        monkeypatch.setattr(svc, "stop", lambda: pytest.fail("stopped"))
        w.run(lambda: setattr(svc, "_last_up", True))
        w.run(svc._paint_run_btn)
        assert w.state(NS)["run_btn"]["mode"] == "stop"
        assert w.call(NS + ".restart") is True
        _wait(w, lambda: not svc._rebooting)
        assert any("restartgame.sh" in " ".join(c) for c in rec.calls)
        assert not any("killgame.sh" in " ".join(c) for c in rec.calls)
        assert w.state(NS)["run_btn"]["label"] == "Stop emulator"
        assert any("restarting the game" in ln for ln in _lines(w))


def test_a_run_that_does_not_take_it_is_stopped_and_started(
        tmp_path, monkeypatch):
    """restartgame.sh exit 3: a run is up but no session took the request -
    the PAD-735 restart, Stop and then Start."""
    from tests.test_webui_emulate import _Done
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch,
                     answers={"restartgame.sh": _Done(b"not taken", rc=3)})
        starts = []
        monkeypatch.setattr(svc, "start", lambda: starts.append(1))
        w.run(lambda: setattr(svc, "_last_up", True))
        assert w.call(NS + ".restart") is True
        _wait(w, lambda: any("killgame.sh" in " ".join(c) for c in rec.calls))
        assert w.state(NS)["run_btn"] == {
            "label": "Restarting…", "enabled": False, "mode": "busy"}
        _wait(w, lambda: not svc._stopping)
        # a second press while it restarts does nothing
        assert w.call(NS + ".restart") is False
        assert not starts                      # the rig still says it is up
        w.run(svc._apply, {"running": "0", "state": "off", "procs": "0"})
        _wait(w, lambda: bool(starts))
        assert starts == [1] and svc._restart_wait == 0


def test_a_press_while_the_reboot_is_asked_does_nothing(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _patch(svc, monkeypatch)
        w.run(lambda: setattr(svc, "_last_up", True))
        w.run(lambda: setattr(svc, "_rebooting", True))
        assert w.call(NS + ".restart") is False
        w.run(svc._paint_run_btn)
        assert w.state(NS)["run_btn"]["label"] == "Restarting…"


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
def test_the_window_button_comes_back_once_the_run_takes_it(monkeypatch,
                                                           tmp_path):
    """PAD-744: the window stays open on a restart (PAD-738), so its button
    says Restarting… only while the request is in flight - not the old 45 s."""
    monkeypatch.setattr(pf, "SW_PATH", str(tmp_path / "gone"))
    dump = tmp_path / "dump"
    dump.mkdir()
    monkeypatch.setattr(pf.padpath, "dump", lambda: str(dump))
    monkeypatch.setenv("PAD_SLOT", "0")
    run = pf.RunCtl(str(tmp_path / "audio.json"))
    assert run.dyn()["restarting"] is False
    assert run.ask_restart() is True
    t0 = run._restart_t
    req = pf.restart_req_path(run.ctl_path)
    assert run.dyn()["restarting"] is True
    # the app's poll has it, then the run (dump/reboot.req) has it
    assert run._restart_pending(t0 + 10) is True
    os.remove(req)
    (dump / "reboot.req").write_text("")
    assert run._restart_pending(t0 + 12) is True
    os.remove(dump / "reboot.req")
    assert run._restart_pending(t0 + 12 + pf.RESTART_GRACE_S - 1) is True
    assert run._restart_pending(t0 + 12 + pf.RESTART_GRACE_S + 1) is False
    # and through poll(), which publishes the change to the page
    run._restart_t = run._taken_t = time.time() - pf.RESTART_GRACE_S - 1
    run.restarting = True
    assert run.poll(time.time()) is True and run.dyn()["restarting"] is False
    # a request nobody takes still gives the button back
    assert run.ask_restart() is True
    assert run._restart_pending(run._restart_t + pf.RESTART_CAP_S + 1) is False


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
    assert "r.restarting" in body and "45000" not in body       # PAD-744


# ---- PAD-738: the reboot inside the run --------------------------------------
def _fn(src, name):
    body = src[src.index("\n%s() {" % name):]
    return body[:body.index("\n}\n") + 3]


def test_watch_reboots_the_guest_inside_the_session():
    src = _text("tools", "spike2_emu", "watch.sh")
    # one launch, used by the start and by the reboot
    assert src.count('bash "$RIG/run_game.sh"') == 1
    assert "\nlaunch_game\n" in src
    reboot = _fn(src, "reboot_game")
    assert "launch_game" in reboot and "launch_autoattract" in reboot
    # the ball feeder reads the zeroed LED block as "the run is over" and
    # counts coils from the boot: it is started again with the game
    assert reboot.index("ballfeed[.]py") < reboot.index("launch_game")
    assert "launch_ballfeed" in reboot
    # the namespace init before the selector (killgame.sh's order)
    assert reboot.index('bash -s $ROOT') < reboot.index("codeselect")
    # the renderer and the playfield are NOT touched; their rings are reset
    # in place, never removed or truncated
    assert "padglhost" not in reboot.replace("pad_pids -x padglhost", "")
    assert "playfield.py" not in reboot and "pf_up" not in reboot
    assert 'rm -f "$LED_HOST"' not in reboot and 'rm -f "$VID_HOST"' not in reboot
    assert reboot.count("conv=notrunc") == 3
    # an empty GL journal: magic only
    assert "printf 'PJL1" in reboot and "glreplay.req" in reboot
    assert "boot.id" in reboot
    # the poll loop takes the request before it can read the gap as an exit
    loop = src[src.index("\nwhile :; do"):]
    assert loop.index('[ -f "$REBOOT_REQ" ]') < loop.index("if ! pad_guest_up; then")
    assert 'rm -f "$REBOOT_REQ"\n        reboot_game' in loop


def test_restartgame_asks_through_the_request_file():
    src = _text("tools", "spike2_emu", "restartgame.sh")
    assert "REQ=$ROOT/dump/reboot.req" in src
    assert "pad_slot_use" in src            # another session's rig is refused
    assert "exit 3" in src
    watch = _text("tools", "spike2_emu", "watch.sh")
    assert "REBOOT_REQ=$ROOT/dump/reboot.req" in watch


def test_restart_cmd_runs_as_root_on_windows(monkeypatch):
    from pinball_decryptor.webui import emulate_core as core
    monkeypatch.setattr(core.sys, "platform", "win32")
    monkeypatch.setattr(core, "wsl_home", lambda: "/home/u")
    monkeypatch.setattr(core, "_wsl_head", lambda root=False: ["wsl.exe"] + (["-u", "root"] if root else []))
    monkeypatch.setattr(core, "_rig_env", lambda: [])
    monkeypatch.setattr(core, "rig_dir", lambda: "/rig")
    monkeypatch.setattr(core, "_wsl_path", lambda p: p)
    cmd = core.restart_cmd()
    assert cmd[:3] == ["wsl.exe", "-u", "root"]
    assert "HOME=/home/u" in cmd and cmd[-1] == "/rig/restartgame.sh"
