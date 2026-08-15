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

REAL Tk, deliberately, like the trough panel's tests: what is under test is a
`root.after` loop and a widget swap. A stub root would happily record an
`after` that Tk itself never runs, which is the one thing this needs to know.
The clock and both intervals are injected so this answers in milliseconds.
"""
import os
import sys
import time

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)


def _root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError as exc:                          # no display / no Tcl
        pytest.skip("Tk unavailable: %s" % exc)
    root.attributes("-alpha", 0)
    return root


def _pump(root, times=40):
    """Let Tk actually run its timers, rather than trusting it will.

    WITH A REAL WAIT PER SPIN (item 49 found this): 40 bare update() calls
    can finish in under a millisecond of wall clock, so an after(1, ...)
    timer is genuinely not due yet and the poll under test never fires -
    a flake that bites only on a fast, unloaded machine, the worst
    polarity. 2 ms per spin makes the 1 ms timer due ~40 times over."""
    for _ in range(times):
        root.update()
        time.sleep(0.002)


def test_tables_arriving_mid_run_are_picked_up():
    root = _root()
    import playfield
    try:
        state = {"rows": []}
        seen = []
        playfield.poll_for_tables(root, lambda: state["rows"], seen.append,
                                  every_ms=1)
        _pump(root)
        assert seen == [], "fired before the tables existed"

        rows = [dict(id=77, num=15, node=8, bit=37, name="Trough 1")]
        state["rows"] = rows
        _pump(root)
        assert seen == [rows], "did not pick up tables that landed mid-run"
    finally:
        root.destroy()


def test_it_only_fires_once():
    """The swap destroys a widget and builds a view; twice would stack two."""
    root = _root()
    import playfield
    try:
        rows = [dict(id=77, num=15, node=8, bit=37, name="Trough 1")]
        seen = []
        playfield.poll_for_tables(root, lambda: rows, seen.append, every_ms=1)
        _pump(root)
        assert len(seen) == 1, "fired %d times, not once" % len(seen)
    finally:
        root.destroy()


def test_it_gives_up_rather_than_polling_an_abandoned_window_forever():
    root = _root()
    import playfield
    try:
        clock = {"t": 1000.0}
        calls = []

        def load():
            calls.append(1)
            clock["t"] += 100.0          # each poll burns 100 s of the budget
            return []

        playfield.poll_for_tables(root, load, lambda rows: None, every_ms=1,
                                  timeout_s=250, _now=lambda: clock["t"])
        _pump(root)
        # 250 s of budget at 100 s a poll: it must stop, not keep rescheduling.
        assert 1 <= len(calls) <= 4, "polled %d times; it never gave up" % len(calls)
    finally:
        root.destroy()
