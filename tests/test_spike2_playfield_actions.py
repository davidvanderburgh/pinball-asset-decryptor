"""The Start / Plunge / Reset balls row exists in BOTH playfield views.

Queue item 60. The fault this guards against is not "the button looks wrong",
it is "the window has no way to reach plunge.py at all". `Field` built the row
in `_place_actions()` as canvas widgets beside the plunger (item 25); the
`Schematic` view - the one that runs on every title shipping no device table -
had `run_plunge()` and nothing calling it but the trough dots, which only ever
pass "take" and "drain". So on those titles David asked the obvious question:
"where is my 'plunge' button now when there's no playfield image?"

INVOKED, NOT LOOKED AT. A button that is drawn, labelled and wired to nothing
is exactly what a screenshot cannot see, so every assertion here goes through
`invoke()` and lands on a fake driver: the script NAME and the verb are what
the guest actually receives. Real Tk, like the late-tables tests, because the
thing under test is widget construction and a command binding - a stub Tk would
happily record a command that Tk itself never fires.

The live half of item 60's acceptance is a run: a plunge on a schematic-view
title has to put a ball into play. This is the half that answers in a second.
"""
import os
import sys

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


class FakeDrv:
    """Records what would have been spawned, and spawns nothing."""

    def __init__(self):
        self.ran = []

    def run_script(self, script, *args):
        self.ran.append((script, args))


def _switch_rows():
    """turtles_pro's shape as far as this test cares: a trough and a button."""
    rows = [dict(id=66 + i, num=15 + i, node=8, bit=32 + i,
                 name="Trough %d" % pos)
            for i, pos in enumerate((6, 5, 4, 3, 2, 1))]
    rows.append(dict(id=34, num=4, node=1, bit=4, name="Action Button"))
    return rows


def test_schematic_offers_the_action_row_and_it_drives_plunge():
    """The whole of item 60: no artwork, and the three actions are still there.

    Through the driver, so a row that was renamed or wired to the wrong script
    fails here rather than on the glass.
    """
    root = _root()
    import playfield
    try:
        view = playfield.Schematic(root, _switch_rows())
        assert [b.cget("text") for b in view._acts] == \
            [lbl for lbl, _, _ in playfield.WINDOW_ACTIONS]
        view.drv = FakeDrv()
        for b in view._acts:
            b.invoke()
        assert view.drv.ran == [(script, () if arg is None else (arg,))
                                for _, script, arg in playfield.WINDOW_ACTIONS]
    finally:
        root.destroy()


def test_schematic_keeps_the_state_cluster_away_from_the_actions():
    """Item 25's separation, carried over: a misclicked "Load state" yanks the
    game back to the save, so it is not a neighbour "Plunge" wants."""
    root = _root()
    import playfield
    saved = playfield.SAVESTATES
    playfield.SAVESTATES = True
    try:
        view = playfield.Schematic(root, _switch_rows())
        sides = {b.pack_info()["side"] for b in view._acts}
        assert sides == {"left"}
        assert view._state_btns, "no state cluster to be apart from"
        assert {w.pack_info()["side"] for w in view._state_btns} == {"right"}
    finally:
        playfield.SAVESTATES = saved
        root.destroy()


def test_field_builds_the_same_row_from_the_same_list():
    """The two views must not drift. `_place_actions` on a bare instance -
    building a real Field wants the title's tables and its artwork, and none
    of that is what this asserts."""
    root = _root()
    import playfield
    import tkinter as tk
    saved = playfield.SAVESTATES
    playfield.SAVESTATES = False        # the state cluster is not under test
    try:
        f = playfield.Field.__new__(playfield.Field)
        f.cv = tk.Canvas(root, width=400, height=300)
        f.trough_panel = None
        f.sw = type("SW", (), {"positions": []})()
        f.drv = FakeDrv()
        f._place_actions(400, 300)
        assert [b.cget("text") for b in f._acts] == \
            [lbl for lbl, _, _ in playfield.WINDOW_ACTIONS]
        for b in f._acts:
            b.invoke()
        assert f.drv.ran == [(script, () if arg is None else (arg,))
                             for _, script, arg in playfield.WINDOW_ACTIONS]
    finally:
        playfield.SAVESTATES = saved
        root.destroy()
def test_clear_alerts_runs_the_exerciser_with_no_argument():
    """Item 59, David's ask: an opt-in button that clears the CHECK SWITCH
    tech alerts.

    IT EXISTS BECAUSE THE BOOT-TIME PASS IS NOT ALWAYS ENOUGH, which is a
    measurement rather than a worry. turtles_pro, 2026-08-21: swexercise.sh
    ran at boot+8 s and moved all 50 switches (99 tagged edges in the guest
    log), and the screen still listed twelve CHECK SWITCH rows a minute later
    - the game had not built its audit yet. The identical exercise run by hand
    afterwards cleared every one of them.

    It must reach swexercise.py with NO argument: that script takes none, and
    passing a verb would make it a plunge.py-shaped call, which is exactly the
    special case WINDOW_ACTIONS carrying the script name exists to avoid.
    """
    root = _root()
    import playfield
    try:
        view = playfield.Schematic(root, _switch_rows())
        view.drv = FakeDrv()
        clear = [b for b in view._acts if b.cget("text") == "Clear alerts"]
        assert len(clear) == 1, "the row should offer exactly one Clear alerts"
        clear[0].invoke()
        assert view.drv.ran == [("swexercise.py", ())]
    finally:
        root.destroy()


def test_the_action_row_stays_one_fact_as_it_grows():
    """Item 60's list, kept honest now that it carries more than plunge verbs:
    a reader must be able to say which helper each button reaches without
    opening both views. A short entry or a bare verb means one has drifted.
    """
    import playfield
    for entry in playfield.WINDOW_ACTIONS:
        assert len(entry) == 3, entry
        label, script, arg = entry
        assert label and script.endswith(".py"), entry
        assert arg is None or isinstance(arg, str), entry


def test_a_machine_with_no_tables_still_opens_the_window():
    """CI is the machine that has no prepared card, and for three releases it
    was the only one that saw this: `gameinfo.table_dir()` answers None when no
    title has ever been built here, item 73 made `set_rows()` consult the
    switch list on EVERY window, and the join died before the window existed.
    Every reader underneath is already silent about a file that is not there,
    so the table-less machine must get the same empty answer, not a TypeError.
    """
    import playfield
    saved = playfield.TDIR
    playfield.TDIR = None
    try:
        assert playfield.load_switch_list() == []
        assert playfield.load_coils() == []
    finally:
        playfield.TDIR = saved
