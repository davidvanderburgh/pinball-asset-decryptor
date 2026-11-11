"""PAD-367 - the Emulate tab refuses a Stern Spike 3 card up front.

Merlin1896 picked a walking_dead_remastered_le ...sdcard-secure card and the
tab copied 62 GB to the cache before failing to mount it (Spike 3 is a LUKS-
encrypted, CM4-fused layout PAD cannot read). These cover the GUI half of the
fix: a pick-time probe (webui/emulate_core.spike3_cmd / parse_spike3) tells the
tab, it says so in the log, and Start refuses before the rig is claimed or a
byte is copied. The rig half (parts.py --spike3, cardmount.sh, watch.sh) is in
tests/test_spike2_spike3_detect.py.
"""

import os
import sys

import pytest

from pinball_decryptor.webui import emulate_core, emulate_rig
from pinball_decryptor.webui.tabs import emulate as emulate_tab
from tests.test_webui_emulate import _Done, _lines, _patch, _svc, _wait
from tests.webui_harness import web_app

NS = "emulate"


@pytest.fixture(autouse=True)
def rig_on(monkeypatch):
    """conftest points PAD_EMU_DIR at an empty folder (no rig); these want the
    tab as it is on a machine that has one."""
    monkeypatch.setattr(emulate_rig, "rig_available", lambda: True)


# ---------------------------------------------------------------------------
# parse_spike3 - the one line cardmount/watch and the tab all read
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expect", [
    ("spike3: yes - partitions p2, p3 are LUKS-encrypted", (True, "partitions p2, p3 are LUKS-encrypted")),
    ("spike3: no", (False, "")),
    ("spike3: no - no such image: x", (False, "no such image: x")),
    ("your screen size is bogus\nspike3: yes - the boot partition is labelled SPIKE3",
     (True, "the boot partition is labelled SPIKE3")),
    ("nothing to see", (None, "")),
    ("", (None, "")),
])
def test_parse_spike3(text, expect):
    assert emulate_core.parse_spike3(text) == expect


def test_spike3_cmd_runs_parts_py_on_this_platform():
    cmd = emulate_rig.spike3_cmd("/some/card.raw")
    if cmd is None:                       # macOS: the container cannot be asked
        import sys
        assert sys.platform == "darwin"
    else:
        assert "parts.py" in " ".join(cmd) and "--spike3" in cmd


# ---------------------------------------------------------------------------
# the tab
# ---------------------------------------------------------------------------

def test_a_confirmed_spike3_card_is_refused_before_any_copy(tmp_path, monkeypatch):
    card = tmp_path / "walking_dead_remastered_le-0_93_0.Release.64G.sdcard-secure.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        w.run(lambda: w.window.emulate_card_var.set(str(card)))
        # the pick-time probe has confirmed it (simulated here; the probe
        # itself is exercised below)
        w.run(lambda: svc._spike3_apply(str(card), True,
                                        "partitions p2, p3, p5, p6 are LUKS-encrypted"))
        w.call(NS + ".toggle")
        w.drain()
        assert "Spike 3 card" in svc.last_refusal
        assert "cannot be emulated" in svc.last_refusal
        # nothing was launched - watch.sh never ran, so nothing was copied
        assert not any("watch.sh" in " ".join(c) for c in rec.calls)
        assert svc._proc is None and not svc._starting


def test_the_pick_logs_the_spike3_notice(tmp_path):
    card = tmp_path / "wdr-secure.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        # picking the card sets _spike3_probed, which _spike3_apply checks
        w.run(lambda: w.window.emulate_card_var.set(str(card)))
        w.run(lambda: svc._spike3_apply(str(card), True,
                                        "the boot partition is labelled SPIKE3"))
        w.drain()
        log = _lines(w)
        assert any("is a Stern Spike 3 card" in ln for ln in log)
        assert any("SPIKE3" in ln for ln in log)


def test_a_non_spike3_card_is_not_refused_for_that_reason(tmp_path, monkeypatch):
    card = tmp_path / "godzilla_le-1_16_0.Release.8G.sdcard.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch)
        w.run(lambda: w.window.emulate_card_var.set(str(card)))
        w.run(lambda: svc._spike3_apply(str(card), False, ""))
        w.call(NS + ".toggle")
        _wait(w, lambda: any("watch.sh" in " ".join(c) for c in rec.calls))
        _wait(w, lambda: svc._proc is None and not svc._starting)
        assert "Spike 3" not in (svc.last_refusal or "")


@pytest.mark.skipif(sys.platform == "darwin",
                    reason="macOS never asks (spike3_cmd is None: the container cannot open "
                           "the card's host path); the rig's own refusal speaks there")
def test_the_probe_asks_parts_py_and_records_the_verdict(tmp_path, monkeypatch):
    card = tmp_path / "wdr-secure.raw"
    card.write_bytes(b"\0" * 512)
    # the probe's guard skips it under PAD_UI_NO_RIG (what web_app sets) and
    # when rig_dir() holds no parts.py (conftest points it at an empty dir);
    # here we let it run and answer the --spike3 call from the recorder.
    monkeypatch.setattr(emulate_tab, "no_rig", lambda: False)
    (tmp_path / "parts.py").write_text("")
    monkeypatch.setattr(emulate_rig, "rig_dir", lambda: str(tmp_path))
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _patch(svc, monkeypatch, answers={
            "--spike3": _Done(out=b"spike3: yes - partitions p2 are LUKS-encrypted\n"),
        })
        # picking the card fires the probe through the card-var trace
        w.run(lambda: w.window.emulate_card_var.set(str(card)))
        _wait(w, lambda: svc._spike3 is True)
        assert any("--spike3" in " ".join(c) for c in rec.calls)
        assert "LUKS" in svc._spike3_why


# ---------------------------------------------------------------------------
# PAD-1090: on a PC with the Spike 3 rig, the card runs instead
# ---------------------------------------------------------------------------

def _s3_rig(monkeypatch, check=b"s3check: ok\n"):
    monkeypatch.setattr(emulate_rig, "spike3_rig_present", lambda: True)
    monkeypatch.setattr(emulate_rig, "spike3_check_cmd",
                        lambda: ["bash", "s3launch.sh", "--check"])
    monkeypatch.setattr(emulate_rig, "spike3_launch_cmd",
                        lambda card, slot, minutes, audio=False:
                        ["bash", "s3launch.sh", card, str(slot), str(minutes)]
                        + (["--audio"] if audio else []))
    monkeypatch.setattr(emulate_rig, "spike3_stop_cmd",
                        lambda slot: ["bash", "s3launch.sh", "--stop", str(slot)])
    return {"--check": _Done(check)}


def _pick(w, svc, card):
    w.run(lambda: w.window.emulate_card_var.set(str(card)))
    w.run(lambda: svc._spike3_apply(str(card), True, "partitions p2, p3 are LUKS-encrypted"))


def test_a_spike3_card_runs_on_the_spike3_rig(tmp_path, monkeypatch):
    from tests.test_webui_emulate import _Recorder
    card = tmp_path / "pokemon_le-0_82_0.Release.64G.sdcard-secure.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        answers = _s3_rig(monkeypatch)
        rec = _Recorder(answers=answers, lines=(
            "s3launch: starting slot 1 for 240 min",
            "[s3run] exec /games/game  (14400s cap)"))
        monkeypatch.setattr(svc, "_run", rec.run)
        monkeypatch.setattr(svc, "_popen", rec.popen)
        _pick(w, svc, card)
        w.call(NS + ".toggle")
        _wait(w, lambda: any("s3launch.sh" in c and str(card) in c
                             for c in (" ".join(x) for x in rec.calls)))
        assert not (svc.last_refusal or "")
        assert not any("watch.sh" in " ".join(c) for c in rec.calls)
        log = _lines(w)
        assert any("[s3run] exec /games/game" in ln for ln in log)
        # Stop asks the launcher, not killgame.sh
        w.run(lambda: setattr(svc, "_s3_slot", 1))
        w.run(svc.stop)
        _wait(w, lambda: any("--stop" in c for c in rec.calls))
        _wait(w, lambda: not svc._stopping)
        assert not any("killgame.sh" in " ".join(c) for c in rec.calls)


def test_a_spike3_rig_that_is_not_set_up_says_what_is_missing(tmp_path, monkeypatch):
    from tests.test_webui_emulate import _Recorder
    card = tmp_path / "fallout_le-0_81_0.Release.64G.sdcard-secure.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        answers = _s3_rig(monkeypatch, check=b"s3check: missing - CUSE (/dev/cuse)\n")
        rec = _Recorder(answers=answers)
        monkeypatch.setattr(svc, "_run", rec.run)
        monkeypatch.setattr(svc, "_popen", rec.popen)
        _pick(w, svc, card)
        w.call(NS + ".toggle")
        _wait(w, lambda: "not set up" in (svc.last_refusal or ""))
        assert "CUSE" in svc.last_refusal
        assert not any(len(c) > 2 and c[2] == str(card) for c in rec.calls)
        _wait(w, lambda: not svc._starting and svc._proc is None)


def test_spike3_sound_follows_the_panel_mute(tmp_path, monkeypatch):
    from tests.test_webui_emulate import _Recorder
    card = tmp_path / "star_wars_2025_le-0_96_0.Release.64G.sdcard-secure.raw"
    card.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _Recorder(answers=_s3_rig(monkeypatch))
        monkeypatch.setattr(svc, "_run", rec.run)
        monkeypatch.setattr(svc, "_popen", rec.popen)
        w.run(lambda: svc._mute_var.set(False))
        _pick(w, svc, card)
        w.call(NS + ".toggle")
        _wait(w, lambda: any(str(card) in c for c in rec.calls))
        launch = [c for c in rec.calls if str(card) in c][0]
        assert launch[-1] == "--audio"


@pytest.mark.parametrize("text,expect", [
    ("s3check: ok", (True, "")),
    ("warn\ns3check: missing - root;CUSE (/dev/cuse)", (False, "root;CUSE (/dev/cuse)")),
    ("", (None, "")),
])
def test_parse_s3check(text, expect):
    assert emulate_core.parse_s3check(text) == expect


def test_spike3_launch_cmd_runs_the_launcher_as_root(monkeypatch):
    if sys.platform != "win32":
        pytest.skip("the WSL argv is Windows-only")
    monkeypatch.setattr(emulate_core, "_wsl_head", lambda root=False: ["wsl.exe"] + (["-u", "root"] if root else []) + ["-e"])
    cmd = emulate_core.spike3_launch_cmd(r"D:\cards\x.raw", 3, 240, audio=True)
    assert cmd[:4] == ["wsl.exe", "-u", "root", "-e"]
    assert cmd[5].endswith("/spike3_emu/s3launch.sh")
    assert cmd[6:] == ["/mnt/d/cards/x.raw", "3", "240", "--audio"]
    assert emulate_core.spike3_stop_cmd(3)[-2:] == ["--stop", "3"]
