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
    # Off-screen too, not just transparent: a transparent window is still
    # MAPPED - it takes the foreground and gets a taskbar button, which is
    # what drags a fullscreen game around on the developer's own machine.
    # Parking it is the half that actually works.
    root.geometry("+10000+10000")
    return root


class FakeReply:
    """A CompletedProcess as far as `helper_message()` cares."""

    def __init__(self, out=b"", err=b""):
        self.stdout, self.stderr, self.returncode = out, err, 0


class FakeDrv:
    """Records what would have been spawned, and spawns nothing.

    `done` is the PAD-128 result callback, and it is ANSWERED rather than
    swallowed: the window's fix is that the helper's own reply reaches the
    status bar, so a fake that dropped the callback would let that break with
    nothing noticing.  `reply` is what the pretend helper printed.
    """

    def __init__(self, reply=None):
        self.ran = []
        self.reply = reply

    def run_script(self, script, *args, done=None):
        self.ran.append((script, args))
        if done is not None and self.reply is not None:
            done(self.reply)


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


# --------------------------------------------------------------------------
# ...and they have to fit next to the state controls (PAD-119)
# --------------------------------------------------------------------------

def _bare_field(root, w, h):
    """A Field with just enough of one to lay its bottom row out.

    Building a real one wants the title's tables and its artwork, and none of
    that is what these assert - the same shortcut, and the same reason, as
    test_field_builds_the_same_row_from_the_same_list above.
    """
    import playfield
    import tkinter as tk
    f = playfield.Field.__new__(playfield.Field)
    f.cv = tk.Canvas(root, width=w, height=h)
    f.trough_panel = None
    f.key_panel = None
    f.sw = type("SW", (), {"positions": []})()
    f.drv = FakeDrv()
    f._place_actions(w, h)
    return f


def _placed(f):
    """[(label, x0, y0, x1, y1)] for every widget on the canvas."""
    out = []
    for item in f.cv.find_all():
        if f.cv.type(item) != "window":
            continue
        wdg = f.cv.nametowidget(f.cv.itemcget(item, "window"))
        try:
            label = wdg.cget("text")
        except Exception:                                   # noqa: BLE001
            label = "<picker>"                              # the slot combobox
        out.append((label,) + tuple(f.cv.bbox(item)))
    return out


def _overlaps(placed):
    return [(a[0], b[0]) for i, a in enumerate(placed) for b in placed[i + 1:]
            if a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]]


def test_the_bottom_row_never_draws_a_button_on_a_button():
    """PAD-119, C FB 2026-09-08: beatles on a 1080p screen.

    The state controls grow rightwards from the canvas's left edge and the
    actions leftwards from its right, and nothing stopped them meeting. On his
    window the slot picker was drawn over "Start" and "Load" over "Plunge":
    both buttons were there, neither could be pressed, and the log said
    nothing because nothing was wrong with the run.

    420x887 IS HIS WINDOW, not a contrived one. The canvas is the artwork
    (336x710 for beatles) times pick_scale(), which is the screen height over
    the artwork height - so this is exactly what a 1080p desk gets, and why a
    taller developer monitor never saw it.
    """
    root = _root()
    import playfield
    saved, refresh = playfield.SAVESTATES, playfield.StateOps._slots_refresh
    playfield.SAVESTATES = True
    # No worker thread: the slot names come off the rig through wsl.exe, and
    # what is under test is where the widgets land, not what is in them.
    playfield.StateOps._slots_refresh = lambda self, **kw: None
    try:
        f = _bare_field(root, 420, 887)
        placed = _placed(f)
        assert _overlaps(placed) == [], \
            "widgets drawn on top of each other: %r" % (placed,)
        for label, _s, _a in playfield.WINDOW_ACTIONS:
            assert any(p[0] == label for p in placed), \
                "%s is not on the canvas at all" % label
    finally:
        playfield.StateOps._slots_refresh = refresh
        playfield.SAVESTATES = saved
        root.destroy()


def test_a_canvas_with_the_room_keeps_them_on_one_row():
    """The second row is the narrow window's answer and must not become every
    window's: on a wide canvas the two clusters share the bottom edge exactly
    as they always did, which is also what keeps the trough panel where it is.
    """
    root = _root()
    import playfield
    saved, refresh = playfield.SAVESTATES, playfield.StateOps._slots_refresh
    playfield.SAVESTATES = True
    playfield.StateOps._slots_refresh = lambda self, **kw: None
    try:
        wide = _bare_field(root, 900, 887)
        assert _overlaps(_placed(wide)) == []
        assert len({p[4] for p in _placed(wide)}) == 1, \
            "one row means one bottom edge: %r" % (_placed(wide),)
        narrow = _bare_field(root, 420, 887)
        assert len({p[4] for p in _placed(narrow)}) == 2, \
            "the narrow window should have taken a second row"
        # The trough panel sits above whatever the row count came to, or it
        # lands on the state controls on exactly the windows that needed two.
        assert narrow._panel_at[1] < wide._panel_at[1]
    finally:
        playfield.StateOps._slots_refresh = refresh
        playfield.SAVESTATES = saved
        root.destroy()


# --------------------------------------------------------------------------
# PAD-128: the row can start a game, and it says what each press did
# --------------------------------------------------------------------------

def test_the_row_can_actually_start_a_game():
    """DragonRR, 2026-09-11: "If I click plunge a ball goes out but again
    nothing really happens."

    Start on a machine with no credits does nothing, and does it silently -
    plunge.py's do_coin() carries the measurement, and it cost item 6 five
    runs - so a row of Start / Plunge / Reset offered no way to begin a game
    at all unless the user went looking for LEFT COIN on the keyboard.  The
    coin is an action now, and it is FIRST because that is the order that
    works.
    """
    import playfield
    labels = [lbl for lbl, _s, _a in playfield.WINDOW_ACTIONS]
    assert labels[0] == "Insert coin", labels
    assert labels.index("Insert coin") < labels.index("Start")
    assert labels.index("Start") < labels.index("Plunge")
    assert ("Insert coin", "plunge.py", "coin") in playfield.WINDOW_ACTIONS


def test_the_coin_button_reaches_plunge_coin():
    """Through the driver, so a button wired to the wrong verb fails here."""
    root = _root()
    import playfield
    try:
        view = playfield.Schematic(root, _switch_rows())
        view.drv = FakeDrv()
        coin = [b for b in view._acts if b.cget("text") == "Insert coin"]
        assert len(coin) == 1
        coin[0].invoke()
        assert view.drv.ran == [("plunge.py", ("coin",))]
    finally:
        root.destroy()


def test_a_helper_message_carries_every_line_it_printed():
    """plunge.py's outcome is its FIRST line and its advice the second, so the
    save-state ladder's "last tagged line" rule would show the advice with the
    outcome missing."""
    import playfield
    msg = playfield.helper_message(
        "plunge.py", FakeReply(b"Start pressed\n  NOTE: a game needs CREDITS."
                               b" Press Insert coin (plunge.py coin) first,"
                               b" then Start.\n"))
    assert msg.startswith("Start pressed")
    assert "needs CREDITS" in msg and "Insert coin" in msg
    assert "\n" not in msg
    # stderr too, and after stdout: item 49's "using godzilla_pro's compiled
    # ids" warning is the reason a user is looking at nonsense.
    both = playfield.helper_message(
        "plunge.py", FakeReply(b"done\n", b"using guesses\n"))
    assert both == "done   using guesses"
    assert playfield.helper_message("plunge.py", None) == \
        "plunge.py did not run"
    assert playfield.helper_message("swexercise.py", FakeReply()) == \
        "swexercise.py: no output"
    long = playfield.helper_message("plunge.py", FakeReply(b"x" * 500))
    assert len(long) == playfield.HELPER_MSG_CAP and long.endswith("…")


def test_the_helpers_answer_lands_in_the_status_bar():
    """The whole of "the game acts like nothing has happened" from this side:
    the window ran the helper and threw its reply away.

    Real Tk, and the reply is delivered the way the driver delivers it, so
    this covers the after(0) hop as well as the text.
    """
    root = _root()
    import playfield
    try:
        view = playfield.Schematic(root, _switch_rows())
        view.drv = FakeDrv(reply=FakeReply(
            b"the trough is empty - nothing to eject\n"))
        assert view._state_status() is None, "nothing pressed yet"
        [b for b in view._acts if b.cget("text") == "Plunge"][0].invoke()
        root.update()                       # run the queued after(0)
        assert view._state_status() == "the trough is empty - nothing to eject"
    finally:
        root.destroy()


def test_a_trough_dot_click_also_says_what_it_did():
    """The dots are the other caller (`run_plunge`), and they are the ones he
    was clicking: "I can force it in using the black and white icons but the
    game acts like nothing has happened"."""
    root = _root()
    import playfield
    try:
        view = playfield.Schematic(root, _switch_rows())
        view.drv = FakeDrv(reply=FakeReply(
            b"trough switch 66 closed (ball drained home)\n"))
        view.run_plunge("drain")
        root.update()
        assert view.drv.ran == [("plunge.py", ("drain",))]
        assert view._state_status() == \
            "trough switch 66 closed (ball drained home)"
    finally:
        root.destroy()


def test_five_actions_still_fit_the_1080p_canvas():
    """PAD-119's window, one button later.  Four actions asked for 372 px of
    its 408 and five ask for ~470, and nothing stopped `create_window` putting
    the overflow at a NEGATIVE x - clipped off the canvas, no overlap for that
    test to catch, and a control simply missing.
    """
    root = _root()
    import playfield
    saved, refresh = playfield.SAVESTATES, playfield.StateOps._slots_refresh
    playfield.SAVESTATES = True
    playfield.StateOps._slots_refresh = lambda self, **kw: None
    try:
        f = _bare_field(root, 420, 887)
        placed = _placed(f)
        assert _overlaps(placed) == [], placed
        for label, _s, _a in playfield.WINDOW_ACTIONS:
            hit = [p for p in placed if p[0] == label]
            assert hit, "%s is not on the canvas at all" % label
            x0, _y0, x1, _y1 = hit[0][1:]
            assert x0 >= 0 and x1 <= 420, \
                "%s is off the canvas at x %d..%d" % (label, x0, x1)
        # Two rows, not three: only the BOTTOM action row pays for the state
        # cluster, so the rows above it keep the whole canvas width.
        assert len({p[4] for p in placed}) == 2, placed
    finally:
        playfield.StateOps._slots_refresh = refresh
        playfield.SAVESTATES = saved
        root.destroy()
