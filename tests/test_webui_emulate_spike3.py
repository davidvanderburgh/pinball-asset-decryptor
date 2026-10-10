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
