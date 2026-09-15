"""The virtual playfield's BALLS section, rebuilt in the JJP window's shape.

PAD-134, David: "i think our ball in and out feedback on the switch matrix is a
little confusing from the ui perspective too. what we did on the jjp virtual
playfield does look much better." The key panel's six clickable dots - a full
one for a ball out, an empty one for a ball in, the stack deciding which switch
moved - became one status line, read-only dots, Plunge and Drain buttons, and
the ball feeder's newest lines under them.

WHAT THESE GUARD:

  * the line's arithmetic. The old caption's "in play" was a learned
    complement and read 0 whenever the window opened with a ball out; the
    denominator is the trough's positions now, and a ball waiting in the
    shooter lane is neither home nor in play.
  * the feeder-to-window channel. ballfeed.py runs inside WSL and the window is
    a Windows process, so the feeder's sentences reached a log nobody at the
    window opened. The status file is the channel, and both ends are tested
    against the same shape.
  * the buttons do what they say, and the dots are no longer a gesture - on the
    key panel. The fallback strip keeps its clickable dots (no panel, no
    buttons, and a drain has to exist somewhere).
"""
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)


GZ_TROUGH = [dict(pos=i + 1, id=71 - i, name="TROUGH %d" % (i + 1))
             for i in range(6)]


def _watch(playfield, made, lane=None):
    """A SwitchWatch over a hand-written merged array - no block, no run."""
    w = playfield.SwitchWatch.__new__(playfield.SwitchWatch)
    w.positions, w.how, w.lane_id = GZ_TROUGH, "named", lane
    w.mrg = bytearray(256)
    for i in made:
        w.mrg[i] = 1
    return w


@pytest.fixture()
def playfield(monkeypatch, tmp_path):
    tk = pytest.importorskip("tkinter")                  # playfield imports it
    del tk
    monkeypatch.setenv("PAD_ROOT", str(tmp_path))
    import playfield as mod
    return mod


# --- the line ---------------------------------------------------------------

def test_a_window_opened_with_a_ball_out_says_one_in_play_not_zero(playfield):
    """The shot that started this: five home, one out, and the old caption
    said "0 in play" because it had never seen six."""
    w = _watch(playfield, [71, 70, 69, 68, 67], lane=62)
    assert playfield.ball_line(w, 3) == "balls 5/6 trough   in play 1   fed 3"


def test_a_ball_waiting_in_the_lane_is_neither_home_nor_in_play(playfield):
    w = _watch(playfield, [71, 70, 69, 68, 67, 62], lane=62)
    assert playfield.ball_line(w, 1) == \
        "balls 5/6 trough   lane 1   in play 0   fed 1"


def test_no_feeder_means_no_fed_count_rather_than_a_zero(playfield):
    """PAD_BALL_FEED=0, or a feeder that has not started: nobody is counting."""
    w = _watch(playfield, [71, 70, 69, 68, 67, 66])
    assert playfield.ball_line(w, None) == "balls 6/6 trough   in play 0"


def test_nothing_read_yet_says_so(playfield):
    w = _watch(playfield, [])
    w.mrg = None
    assert "waiting" in playfield.ball_line(w, None)


# --- the feeder's status file, both ends ------------------------------------

def test_the_feeder_publishes_its_count_and_newest_three_lines(monkeypatch,
                                                              tmp_path,
                                                              playfield):
    monkeypatch.setenv("PAD_SW_FILE", str(tmp_path / "padsw"))
    monkeypatch.setenv("PAD_LED_FILE", str(tmp_path / "padled"))
    import ballfeed
    path = str(tmp_path / "padball")
    monkeypatch.setattr(ballfeed, "STATUS_PATH", path)
    monkeypatch.setattr(ballfeed, "_recent", [])
    monkeypatch.setattr(ballfeed, "_fed", 0)
    for n in range(5):
        ballfeed.say("line %d" % n)
    ballfeed.publish(4)
    fed, lines = playfield.read_ball_status(path)
    assert fed == 4
    assert lines == ["line 2", "line 3", "line 4"]
    assert not os.path.exists(path + ".tmp")          # tmp+rename, not a stub


def test_no_status_file_is_no_feeder_not_an_error(playfield, tmp_path):
    assert playfield.read_ball_status(str(tmp_path / "absent")) == (None, [])


def test_only_the_lines_after_the_overlap_are_new(playfield):
    """The file is a sliding window; re-reading it must not repeat lines."""
    assert playfield.new_lines([], ["a", "b"]) == ["a", "b"]
    assert playfield.new_lines(["a", "b", "c"], ["b", "c", "d"]) == ["d"]
    assert playfield.new_lines(["a", "b", "c"], ["a", "b", "c"]) == []
    assert playfield.new_lines(["a", "b", "c"], ["x", "y", "z"]) == \
        ["x", "y", "z"]


# --- the section itself, real Tk --------------------------------------------

def _panel(playfield, on_ball):
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as exc:                         # no display / no Tcl
        pytest.skip("Tk unavailable: %s" % exc)
    root.attributes("-alpha", 0)
    root.geometry("+10000+10000")
    import keybinds
    rows = keybinds.parse(["C\tct\t33\tCoin Door Closed",
                           "Left\t-\t60\tLeft Flipper",
                           "B\tt\t66,67,68,69,70,71\t6 balls in trough"])
    panel = playfield.KeyPanel(root, rows, drv=None)
    panel.cv.pack()
    dots = panel.add_trough(GZ_TROUGH, "named", on_ball)
    root.update()
    return root, panel, dots


def test_plunge_drain_and_reset_are_buttons_that_say_what_they_do(playfield):
    """Reset balls moved in from the bottom action row, which the key panel
    retires (PAD-134)."""
    said = []
    root, panel, dots = _panel(playfield, said.append)
    try:
        assert [b.cget("text") for b in panel.ball_btns] == \
            ["Plunge", "Drain", "Reset balls"]
        panel.show_balls(_watch(playfield, [71, 70, 69, 68, 67], lane=62),
                         None, [])                     # a ball in play
        for b in panel.ball_btns:
            b.invoke()
        assert said == ["plunge", "drain", "reset"]
    finally:
        root.destroy()


# --- Drain is greyed until a ball is in play (PAD-153) ----------------------

def test_drain_is_ready_only_with_a_ball_in_play(playfield):
    """DragonRR: "I drained before I plunged.. and that forces an endless
    cycle. Is it possible to grey out the drain until it is valid?" """
    served = _watch(playfield, [71, 70, 69, 68, 67, 62], lane=62)
    assert not playfield.drain_ready(served)            # waiting in the lane
    assert playfield.drain_ready(_watch(playfield, [71, 70, 69, 68, 67],
                                        lane=62))       # launched
    assert not playfield.drain_ready(_watch(playfield, [71, 70, 69, 68, 67,
                                                        66], lane=62))
    # A multiball with a ball waiting still has two out there to drain.
    assert playfield.drain_ready(_watch(playfield, [71, 70, 69, 62], lane=62))
    unread = _watch(playfield, [])
    unread.mrg = None
    assert not playfield.drain_ready(unread)


def test_drain_is_greyed_while_the_ball_waits_and_lights_once_launched(
        playfield):
    said = []
    root, panel, dots = _panel(playfield, said.append)
    try:
        drain = panel.ball_btns[1]
        assert drain is panel.drain_btn
        assert drain.cget("state") == "disabled"        # nothing read yet
        panel.show_balls(_watch(playfield, [71, 70, 69, 68, 67, 62], lane=62),
                         1, [])
        assert drain.cget("state") == "disabled"
        drain.invoke()
        assert said == []                               # a grey press is nothing
        assert panel.ball_btns[0].cget("state") == "normal"   # Plunge is live
        panel.show_balls(_watch(playfield, [71, 70, 69, 68, 67], lane=62),
                         1, [])
        assert drain.cget("state") == "normal"
        drain.invoke()
        assert said == ["drain"]
        panel.show_balls(_watch(playfield, [71, 70, 69, 68, 67, 66], lane=62),
                         1, [])
        assert drain.cget("state") == "disabled"        # home again
    finally:
        root.destroy()


def test_the_dots_on_the_panel_are_no_longer_a_gesture(playfield):
    said = []
    root, panel, dots = _panel(playfield, said.append)
    try:
        assert not dots.cv.tag_bind(dots.balls[0], "<Button-1>")
    finally:
        root.destroy()


def test_the_note_keeps_the_newest_three_and_folds_in_new_feeder_lines(
        playfield):
    root, panel, dots = _panel(playfield, lambda w: None)
    try:
        w = _watch(playfield, [71, 70, 69, 68, 67], lane=62)
        panel.show_balls(w, 2, ["fed ball one", "fed ball two"])
        panel.ball_say("drain: ball home")
        # The feeder's window slides by one; only the new line may arrive.
        panel.show_balls(w, 3, ["fed ball two", "fed ball three"])
        text = panel.cv.itemcget(panel.ball_note, "text").splitlines()
        assert text == ["fed ball two", "drain: ball home", "fed ball three"]
        assert panel.cv.itemcget(panel.ball_state, "text") == \
            "balls 5/6 trough   in play 1   fed 3"
    finally:
        root.destroy()


def test_a_long_reply_keeps_its_opening_words_and_drops_older_messages(
        playfield):
    """The first note kept the newest ROWS, so a Plunge reply that wrapped
    past three rows showed "launch   the game puts one there..." with the
    outcome cut off the front."""
    root, panel, dots = _panel(playfield, lambda w: None)
    try:
        width = panel._w - 2 * panel.PAD
        panel.ball_say("an older message")
        long_reply = "plunge: nothing in the shooter lane to launch " + \
            " ".join(["because of a reason"] * 12)
        assert len(playfield.wrap_rows(panel._f8, long_reply, width)) > 3
        panel.ball_say(long_reply)
        rows = panel.cv.itemcget(panel.ball_note, "text").splitlines()
        assert len(rows) == 3
        assert rows[0].startswith("plunge: nothing")
        assert rows[-1].endswith("…")
        assert "an older message" not in rows
    finally:
        root.destroy()
