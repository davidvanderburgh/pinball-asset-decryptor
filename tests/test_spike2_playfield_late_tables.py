"""The playfield window picks up switch tables that land DURING a run.

Queue item 47. The fault this guards against is not "the window shows no
switches" - that is correct and unavoidable for the first few seconds of a
title's first run, because the game builds its switch table on the heap and it
only reaches us as the shim's `[sw]` dump. The fault is that the window never
looked again: it opened a few seconds early, drew the explanatory paragraph,
and stayed that way for the whole session while the tables it was describing
were written to disk behind it. On a title with no usable artwork - Bond ships
a 202x443 grayscale thumbnail and 0 devices positioned on it - that paragraph
IS the window, so the title's first run could not be played.

THE WINDOW IS A WEB PAGE NOW (2026-09-23): the paragraph is the controller's
WAITING state (`Playfield.kind == "waiting"`), and the look-again is its own
loop - `Playfield._tick` stats `load_switch_list()` every TABLES_EVERY_S until
TABLES_TIMEOUT_S and calls `swap_in(rows)`, which builds the view and tells the
page to re-lay itself out. This drives the REAL controller one tick at a time
against an injected clock, so it answers in milliseconds; everything that
would reach WSL or a run's files is faked first.
"""
import os
import sys
import types

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)

ROWS = [dict(id=77, num=15, node=8, bit=37, name="Trough 1")]


class _Clock:
    """monotonic, time and perf_counter all in one hand-wound clock."""

    def __init__(self):
        self.t = 1000.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


class _Host:
    def __init__(self):
        self.events = []

    def publish(self, etype, data=None):
        self.events.append(etype)


@pytest.fixture
def rig(monkeypatch, tmp_path):
    """playfield with a fake clock, a switch list the test controls, and
    nothing that can reach WSL, a pipe helper or a real run's files."""
    pf = pytest.importorskip("playfield")
    clock = _Clock()
    monkeypatch.setattr(pf, "time", types.SimpleNamespace(
        monotonic=clock.now, time=clock.now, perf_counter=clock.now,
        sleep=clock.sleep))
    monkeypatch.setattr(pf, "wsl_run", lambda *a, **k: None)
    monkeypatch.setattr(pf, "state_run", lambda *a, **k: None)
    monkeypatch.setattr(pf, "state_slots", lambda *a, **k: {})
    monkeypatch.setattr(pf.SwitchPipe, "_ensure", lambda self: False)
    monkeypatch.setattr(pf, "SAVESTATES", False)
    monkeypatch.setattr(pf, "layout_is_usable", lambda: False)
    for name in ("LED_PATH", "LCD_PATH", "SW_PATH", "BINDS_PATH",
                 "BALL_PATH"):
        monkeypatch.setattr(pf, name, str(tmp_path / ("absent_" + name)))
    monkeypatch.setattr(pf, "STATE", str(tmp_path / "state.json"))
    tables = {"rows": [], "loads": 0, "on_load": None}

    def load(*a, **k):
        tables["loads"] += 1
        if tables["on_load"] is not None:
            tables["on_load"]()
        return list(tables["rows"])

    monkeypatch.setattr(pf, "load_switch_list", load)
    return pf, clock, tables


def _waiting(pf, tables):
    ctl = pf.Playfield()
    ctl.host = _Host()
    assert ctl.kind == "waiting" and ctl.view is None
    tables["loads"] = 0                 # count the LOOP's looks, not the build's
    return ctl


def test_tables_arriving_mid_run_are_picked_up(rig):
    pf, clock, tables = rig
    ctl = _waiting(pf, tables)
    for _ in range(5):
        clock.sleep(pf.TABLES_EVERY_S)
        ctl._tick()
    assert ctl.kind == "waiting", "left the waiting page with no tables"
    assert tables["loads"] == 5, "did not keep looking"
    assert ctl.host.events == [], "told the page to re-lay out for nothing"

    tables["rows"] = ROWS
    clock.sleep(pf.TABLES_EVERY_S)
    ctl._tick()
    assert ctl.kind == "schematic", "did not pick up tables that landed mid-run"
    assert [e["id"] for e in ctl.view.entries if "id" in e] == [77]
    assert ctl.host.events == ["layout"]
    st = ctl.state("main")
    assert st["kind"] == "schematic" and "waiting" not in st


def test_it_looks_on_its_interval_not_every_frame(rig):
    """A stat every TABLES_EVERY_S costs nothing; one per 50 ms loop tick
    over \\\\wsl.localhost would not."""
    pf, clock, tables = rig
    ctl = _waiting(pf, tables)
    step = pf.TABLES_EVERY_S / 10.0
    for _ in range(9):
        clock.sleep(step)
        ctl._tick()
    assert tables["loads"] == 0
    clock.sleep(step * 1.5)
    ctl._tick()
    assert tables["loads"] == 1


def test_it_only_fires_once(rig):
    """The swap builds a view; twice would build two and orphan the first."""
    pf, clock, tables = rig
    ctl = _waiting(pf, tables)
    swaps = []
    real = ctl.swap_in
    ctl.swap_in = lambda rows: (swaps.append(rows), real(rows))
    tables["rows"] = ROWS
    for _ in range(20):
        clock.sleep(pf.TABLES_EVERY_S)
        ctl._tick()
    assert len(swaps) == 1, "fired %d times, not once" % len(swaps)
    assert ctl.host.events.count("layout") == 1


def test_it_gives_up_rather_than_polling_an_abandoned_window_forever(rig,
                                                                     monkeypatch):
    pf, clock, tables = rig
    monkeypatch.setattr(pf, "TABLES_TIMEOUT_S", 250)
    ctl = _waiting(pf, tables)
    # each look burns 100 s of the budget
    tables["on_load"] = lambda: clock.sleep(100.0)
    for _ in range(200):
        clock.sleep(pf.TABLES_EVERY_S)
        ctl._tick()
    # 250 s of budget at 100 s a look: it must stop, not keep looking.
    assert 1 <= tables["loads"] <= 4, (
        "looked %d times; it never gave up" % tables["loads"])
    assert ctl.kind == "waiting"
