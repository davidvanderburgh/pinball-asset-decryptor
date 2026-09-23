"""The Insert coin / Start / Plunge / Reset balls / Clear switch alerts row
exists in BOTH playfield views.

Queue item 60. The fault this guards against is not "the button looks wrong",
it is "the window has no way to reach plunge.py at all". The artwork view
built the row beside the plunger (item 25); the schematic view - the one that
runs on every title shipping no device table - had `run_plunge()` and nothing
calling it but the trough dots, which only ever pass "take" and "drain". So on
those titles David asked the obvious question: "where is my 'plunge' button
now when there's no playfield image?"

THE WINDOW IS A WEB PAGE NOW (2026-09-23). The row is drawn by pf.js from the
`acts` list the controller's `state()` hands it, and a press comes back as
`api_action(i)`. So the row is decided in ONE place for both views by
construction, and what is under test is that decision and the call path the
page uses - not widget construction, which no longer exists in Python.

INVOKED, NOT LOOKED AT. A button that is drawn, labelled and wired to nothing
is exactly what a screenshot cannot see, so every assertion here goes through
the controller's own entry point (`api_action`, `api_trough`, `run_plunge`)
and lands on a fake driver: the script NAME and the verb are what the guest
actually receives.

The live half of item 60's acceptance is a run: a plunge on a schematic-view
title has to put a ball into play. This is the half that answers in a second.
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


class FakeReply:
    """A CompletedProcess as far as `helper_message()` cares."""

    def __init__(self, out=b"", err=b""):
        self.stdout, self.stderr, self.returncode = out, err, 0


class FakeDrv:
    """Records what would have been spawned, and spawns nothing.

    Installed as `playfield.SwitchDriver`, so the controller, its key panel
    and its keyboard fallback all hold THIS object - the same sharing the real
    window has.

    `done` is the PAD-128 result callback, and it is ANSWERED rather than
    swallowed: the window's fix is that the helper's own reply reaches the
    status line, so a fake that dropped the callback would let that break with
    nothing noticing.  `reply` is what the pretend helper printed.
    """

    def __init__(self, reply=None):
        self.ran = []
        self.pressed, self.released = [], []
        self.reply = reply

    def press(self, sw):
        self.pressed.append(sw)

    def release(self, sw):
        self.released.append(sw)

    def spin(self, sw, on):
        pass

    def release_all(self):
        pass

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


#: Every wsl_run a test let through. The fixture fails the test on any.
_WSL = []

#: The module's own objects, taken by the fixture BEFORE it patches them
#: (monkeypatch undoes every patch after each test, so these are the real
#: ones), for the tests that need the real thing back.
_REAL = {}


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """No rig, no WSL, no desk: every file the window reads is pinned to a
    path that does not exist, and every way out to WSL is stubbed BEFORE a
    Playfield (and so a SwitchDriver) is built.

    THE KEY PANEL IS PINNED ABSENT TOO. Every test here is about the bottom
    ACTION ROW, which PAD-134 hides whenever a key panel attaches - and a
    panel attaches whenever dump/padbinds exists. On a developer box that
    file is whatever the last emulator run left, so the row vanished under a
    test while CI, which has no rig, stayed green. Pinned to a file that does
    not exist, so the answer does not depend on the desk; the panel side has
    its own tests in test_spike2_playfield_panel_controls.py."""
    import playfield
    del _WSL[:]
    for name in ("SwitchDriver", "load_switch_list", "load_coils"):
        _REAL[name] = getattr(playfield, name)
    monkeypatch.setattr(playfield, "wsl_run",
                        lambda *a: _WSL.append(a))
    monkeypatch.setattr(playfield, "state_run", lambda *a, **k: None)
    monkeypatch.setattr(playfield, "state_slots", lambda: {})
    monkeypatch.setattr(playfield.SwitchPipe, "_ensure", lambda self: False)
    monkeypatch.setattr(playfield, "SwitchDriver", FakeDrv)
    monkeypatch.setattr(playfield, "BINDS_PATH", str(tmp_path / "no-padbinds"))
    for name in ("LED_PATH", "SW_PATH", "BALL_PATH", "LCD_PATH"):
        monkeypatch.setattr(playfield, name, str(tmp_path / name.lower()))
    monkeypatch.setattr(playfield, "STATE", str(tmp_path / "state.json"))
    monkeypatch.setattr(playfield, "SAVESTATES", False)
    monkeypatch.setattr(playfield, "load_switch_list", _switch_rows)
    monkeypatch.setattr(playfield, "load_switches", lambda: [])
    monkeypatch.setattr(playfield, "load_leds", lambda: [])
    monkeypatch.setattr(playfield, "load_coils", lambda: [])
    monkeypatch.setattr(playfield, "load_led_names", lambda: {})
    monkeypatch.setattr(playfield, "layout_art", lambda: None)
    monkeypatch.setattr(playfield, "layout_extent", lambda pad=0: None)
    monkeypatch.setattr(playfield, "layout_is_usable", lambda: False)
    yield playfield
    assert _WSL == [], "a test reached wsl_run: %r" % (_WSL,)


def _window(playfield, monkeypatch, field=False):
    """The controller the page talks to, on the schematic (default) or the
    artwork view. Building a real Field with no tables gives a blank field,
    which is all these need: the row is not the view's business."""
    monkeypatch.setattr(playfield, "layout_is_usable", lambda: field)
    pf = playfield.Playfield()
    assert pf.kind == ("field" if field else "schematic")
    return pf


def _acts(pf):
    return pf.state("main")["acts"]


def _expected_acts(playfield):
    return [[i, lbl] for i, (lbl, _s, _a) in enumerate(playfield.WINDOW_ACTIONS)]


def _expected_runs(playfield):
    return [(script, () if arg is None else (arg,))
            for _, script, arg in playfield.WINDOW_ACTIONS]


def test_schematic_offers_the_action_row_and_it_drives_plunge(offline,
                                                             monkeypatch):
    """The whole of item 60: no artwork, and the actions are still there.

    Through the controller's api_action - the call the page's buttons make -
    so a row that was renamed or wired to the wrong script fails here rather
    than on the glass.
    """
    playfield = offline
    pf = _window(playfield, monkeypatch)
    assert pf.key_panel is None and pf.acts_shown
    assert _acts(pf) == _expected_acts(playfield)
    for i, label in _acts(pf):
        assert pf.api_action(i) == label
    assert pf.drv.ran == _expected_runs(playfield)


def test_schematic_keeps_the_state_cluster_away_from_the_actions(offline,
                                                                 monkeypatch):
    """Item 25's separation, carried over: a misclicked "Load state" yanks the
    game back to the save, so it is not a neighbour "Plunge" wants.

    Which SIDE each cluster sits on is the page's CSS now (the actions are
    their own flex row, pushed right; the save-state controls are a separate
    element). What Python still decides is that they ARE separate: the state
    cluster travels as `savestates` / `slots`, never as an entry in `acts`,
    so the page cannot draw a state control inside the action row."""
    playfield = offline
    monkeypatch.setattr(playfield, "SAVESTATES", True)
    pf = _window(playfield, monkeypatch)
    st = pf.state("main")
    assert st["savestates"] is True, "no state cluster to be apart from"
    assert len(st["slots"]) == len(playfield.SLOT_IDS)
    labels = [lbl for _i, lbl in st["acts"]]
    assert labels == [lbl for lbl, _s, _a in playfield.WINDOW_ACTIONS]
    assert not any(w in lbl.lower() for lbl in labels
                   for w in ("save", "load", "slot")), labels


def test_field_builds_the_same_row_from_the_same_list(offline, monkeypatch):
    """The two views must not drift. They cannot any more: the row is the
    controller's, built from WINDOW_ACTIONS whatever the view - and this pins
    that the artwork view gets it, and that it drives the same helpers."""
    playfield = offline
    pf = _window(playfield, monkeypatch, field=True)
    assert _acts(pf) == _expected_acts(playfield)
    for i, _label in _acts(pf):
        pf.api_action(i)
    assert pf.drv.ran == _expected_runs(playfield)


def test_clear_alerts_runs_the_exerciser_with_no_argument(offline,
                                                          monkeypatch):
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
    Both ways in are checked: the row's button and the key panel's
    (api_clear_alerts), which must land on the same call.
    """
    playfield = offline
    pf = _window(playfield, monkeypatch)
    clear = [i for i, lbl in _acts(pf) if lbl == "Clear switch alerts"]
    assert len(clear) == 1, \
        "the row should offer exactly one Clear switch alerts"
    pf.api_action(clear[0])
    assert pf.drv.ran == [("swexercise.py", ())]
    pf.api_clear_alerts()
    assert pf.drv.ran == [("swexercise.py", ())] * 2


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
        # The module's own readers, not the fixture's stand-ins.
        assert _REAL["load_switch_list"]() == []
        assert _REAL["load_coils"]() == []
    finally:
        playfield.TDIR = saved


# --------------------------------------------------------------------------
# ...and they have to fit next to the state controls (PAD-119)
#
# THE LAYOUT IS THE PAGE'S NOW. PAD-119 (C FB 2026-09-08, beatles on a 1080p
# screen) was the Tk canvas placing the state controls from the left edge and
# the actions from the right with nothing stopping them meeting: the slot
# picker was drawn over "Start" and "Load" over "Plunge", both there, neither
# pressable. Its follow-up was a fifth action placed at a NEGATIVE x - clipped
# off the canvas, a control simply missing. And v0.207.0 was yanked because a
# test asserted a row COUNT that is really a font measurement.
#
# pf.css makes the action row a flex-wrap row (.pf-acts, wrap-reverse so the
# overflow climbs upward the way the Tk wrap did) beside a separate state
# cluster. A flex container lays every child out in flow: two buttons cannot
# overlap and none can land off the left edge, BY CONSTRUCTION, at any window
# width and in any font, so there is no geometry left in Python to measure.
# What stays checkable here is the half Python still owns - that the page is
# handed every action, once, in order, beside (never inside) the state
# cluster, whatever else is on the window.
# --------------------------------------------------------------------------

def test_the_bottom_row_offers_every_action_once_beside_the_state_cluster(
        offline, monkeypatch):
    """PAD-119's window, as far as Python can see it: with the state cluster
    up, the page is still handed all five actions - none dropped to make
    room, none duplicated - and every index it can send back reaches its own
    helper. A missing control used to be a clipped widget; now it could only
    be a missing entry, and that is what this catches."""
    playfield = offline
    monkeypatch.setattr(playfield, "SAVESTATES", True)
    pf = _window(playfield, monkeypatch, field=True)
    acts = _acts(pf)
    labels = [lbl for _i, lbl in acts]
    assert len(labels) == len(set(labels)) == len(playfield.WINDOW_ACTIONS)
    for label, _s, _a in playfield.WINDOW_ACTIONS:
        assert label in labels, "%s is not offered at all" % label
    for i, label in acts:
        assert playfield.WINDOW_ACTIONS[i][0] == label
        assert pf.api_action(i) == label
    assert pf.drv.ran == _expected_runs(playfield)


def test_the_row_is_the_same_with_or_without_the_state_cluster(offline,
                                                               monkeypatch):
    """The extra row was the narrow window's answer and must not become a
    change in WHAT is offered: the wrap is layout (the page's flex-wrap), so
    the row's content cannot depend on whether the state cluster shares its
    edge."""
    playfield = offline
    without = _acts(_window(playfield, monkeypatch, field=True))
    monkeypatch.setattr(playfield, "SAVESTATES", True)
    with_state = _acts(_window(playfield, monkeypatch, field=True))
    assert without == with_state == _expected_acts(playfield)


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


def test_the_coin_button_reaches_plunge_coin(offline, monkeypatch):
    """Through the controller, so a button wired to the wrong verb fails
    here."""
    playfield = offline
    pf = _window(playfield, monkeypatch)
    coin = [i for i, lbl in _acts(pf) if lbl == "Insert coin"]
    assert len(coin) == 1
    pf.api_action(coin[0])
    assert pf.drv.ran == [("plunge.py", ("coin",))]


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


def test_the_helpers_answer_lands_in_the_status_bar(offline, monkeypatch):
    """The whole of "the game acts like nothing has happened" from this side:
    the window ran the helper and threw its reply away.

    The REAL SwitchDriver this time, with only wsl_run faked, so the reply is
    delivered the way the driver delivers it - on the driver's own thread,
    into the controller's flash slot under its lock - and then read back the
    way the page reads it: the view's tick puts it on the status line, and
    `state()` carries that line to the page."""
    playfield = offline
    got = []

    def fake_wsl(script, *args):
        got.append((script, args))
        return FakeReply(b"the trough is empty - nothing to eject\n")

    monkeypatch.setattr(playfield, "SwitchDriver", _REAL["SwitchDriver"])
    monkeypatch.setattr(playfield, "wsl_run", fake_wsl)
    pf = _window(playfield, monkeypatch)
    assert isinstance(pf.drv, _REAL["SwitchDriver"])
    assert pf.state_status() is None, "nothing pressed yet"
    plunge = [i for i, lbl in _acts(pf) if lbl == "Plunge"][0]
    pf.api_action(plunge)
    deadline = time.monotonic() + 10
    while pf.state_status() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert got == [("plunge.py", ("plunge",))]
    assert pf.state_status() == "the trough is empty - nothing to eject"
    frame = pf.view.tick(time.monotonic())
    assert frame.get("status") == "the trough is empty - nothing to eject"
    assert pf.state("main")["status"] == \
        "the trough is empty - nothing to eject"


def test_a_trough_dot_click_also_says_what_it_did(offline, monkeypatch):
    """The dots are the other caller (`run_plunge`), and they are the ones he
    was clicking: "I can force it in using the black and white icons but the
    game acts like nothing has happened".

    Without a key panel the schematic's trough strip is the clickable
    fallback, and the page's click on a dot arrives as api_trough: an empty
    dot drains a ball in, and the helper's answer reaches the status line."""
    playfield = offline
    pf = _window(playfield, monkeypatch)
    pf.drv.reply = FakeReply(b"trough switch 66 closed (ball drained home)\n")
    assert pf.view.trough is not None and pf.view.trough.clickable
    assert pf.api_trough(0) == "drain"
    assert pf.drv.ran == [("plunge.py", ("drain",))]
    assert pf.state_status() == "trough switch 66 closed (ball drained home)"
    # ...and run_plunge itself, the one both callers share.
    pf.run_plunge("drain")
    assert pf.drv.ran == [("plunge.py", ("drain",))] * 2
