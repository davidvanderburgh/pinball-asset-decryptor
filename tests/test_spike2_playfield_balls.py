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

THE WINDOW IS A WEB PAGE NOW (2026-09-23). The section is `KeyPanel`'s model
(`spec()` / `dyn()`: the line, Drain's live flag, the note, the dots) drawn by
pf.js, and its buttons come back as the controller's `api_ball(what)`. So the
section is tested as that model plus the controller call, on a fake driver.
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

PANEL_BINDS = ["C\tct\t33\tCoin Door Closed",
               "Left\t-\t60\tLeft Flipper",
               "B\tt\t66,67,68,69,70,71\t6 balls in trough"]


def _watch(playfield, made, lane=None):
    """A SwitchWatch over a hand-written merged array - no block, no run."""
    w = playfield.SwitchWatch.__new__(playfield.SwitchWatch)
    w.positions, w.how, w.lane_id = GZ_TROUGH, "named", lane
    w.mrg = bytearray(256)
    for i in made:
        w.mrg[i] = 1
    return w


class FakeReply:
    def __init__(self, out=b"", err=b""):
        self.stdout, self.stderr, self.returncode = out, err, 0


class FakeDrv:
    """Records presses, releases and spawned helpers; spawns nothing. A set
    `reply` is answered through `done`, the way the real driver delivers a
    helper's output."""

    def __init__(self):
        self.pressed, self.released, self.ran = [], [], []
        self.reply = None

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


@pytest.fixture()
def playfield(monkeypatch, tmp_path):
    monkeypatch.setenv("PAD_ROOT", str(tmp_path))
    import playfield as mod
    return mod


#: Every wsl_run a test let through. The window fixture fails on any.
_WSL = []


@pytest.fixture()
def window(playfield, monkeypatch, tmp_path):
    """Builds the controller the page talks to, offline: every way out to
    WSL stubbed BEFORE the SwitchDriver exists, every file it reads pinned
    under tmp_path, and padbinds written (so the key panel - and with it the
    BALLS section - is up) unless the test asks for none."""
    del _WSL[:]
    monkeypatch.setattr(playfield, "wsl_run", lambda *a: _WSL.append(a))
    monkeypatch.setattr(playfield, "state_run", lambda *a, **k: None)
    monkeypatch.setattr(playfield, "state_slots", lambda: {})
    monkeypatch.setattr(playfield.SwitchPipe, "_ensure", lambda self: False)
    monkeypatch.setattr(playfield, "SwitchDriver", FakeDrv)
    binds = tmp_path / "padbinds"
    monkeypatch.setattr(playfield, "BINDS_PATH", str(binds))
    for name in ("LED_PATH", "SW_PATH", "BALL_PATH", "LCD_PATH"):
        monkeypatch.setattr(playfield, name, str(tmp_path / name.lower()))
    monkeypatch.setattr(playfield, "STATE", str(tmp_path / "state.json"))
    monkeypatch.setattr(playfield, "SAVESTATES", False)
    rows = [dict(id=r["id"], num=r["id"], node=8, bit=r["pos"],
                 name="Trough %d" % r["pos"]) for r in GZ_TROUGH]
    monkeypatch.setattr(playfield, "load_switch_list", lambda: rows)
    monkeypatch.setattr(playfield, "load_led_names", lambda: {})
    monkeypatch.setattr(playfield, "layout_is_usable", lambda: False)

    def build(panel=True):
        if panel:
            binds.write_text("\n".join(PANEL_BINDS) + "\n", encoding="utf8")
        elif binds.exists():
            binds.unlink()
        return playfield.Playfield()

    yield build
    assert _WSL == [], "a test reached wsl_run: %r" % (_WSL,)


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


# --- the section itself: the model and the controller -----------------------

def _panel(playfield, drv=None):
    """The section as the model holds it: a key panel with its read-only
    trough dots added."""
    import keybinds
    panel = playfield.KeyPanel(keybinds.parse(PANEL_BINDS), drv)
    dots = panel.add_trough(GZ_TROUGH, "named")
    return panel, dots


def test_plunge_drain_and_reset_are_buttons_that_say_what_they_do(window):
    """Reset balls moved in from the bottom action row, which the key panel
    retires (PAD-134).

    The three buttons are pf.js's (labelled Plunge / Drain / Reset balls,
    each sending api_ball with its verb); this pins the controller's half:
    the three verbs, and only those, reach plunge.py - and the helper's
    answer lands in the section's own note, under the button that asked."""
    pf = window()
    assert pf.key_panel is not None and pf.state("main")["acts"] == []
    pf.drv.reply = FakeReply(b"shooter lane opened (ball launched)\n")
    # a ball in play, so Drain is live (a greyed Drain refusing is
    # test_a_grey_drain_press_is_nothing)
    pf.key_panel._drain_live = True
    for what in ("plunge", "drain", "reset"):
        assert pf.api_ball(what) is True
    assert pf.drv.ran == [("plunge.py", (w,))
                          for w in ("plunge", "drain", "reset")]
    assert pf.api_ball("take") is False, "an unknown verb reached plunge.py"
    assert len(pf.drv.ran) == 3
    assert pf.key_panel.dyn()["note"][-1] == \
        "reset: shooter lane opened (ball launched)"


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
    """The model's `drain` flag is what pf.js sets the button's disabled
    state from (`drain.disabled = !d.drain`); Plunge has no such flag and is
    always live."""
    panel, _dots = _panel(playfield)
    assert panel.dyn()["drain"] is False                # nothing read yet
    panel.show_balls(_watch(playfield, [71, 70, 69, 68, 67, 62], lane=62),
                     1, [])
    assert panel.dyn()["drain"] is False
    panel.show_balls(_watch(playfield, [71, 70, 69, 68, 67], lane=62), 1, [])
    assert panel.dyn()["drain"] is True
    panel.show_balls(_watch(playfield, [71, 70, 69, 68, 67, 66], lane=62),
                     1, [])
    assert panel.dyn()["drain"] is False                # home again


def test_a_grey_drain_press_is_nothing(window):
    """The Tk test pressed the greyed button and saw nothing run, because a
    disabled Tk button cannot be invoked. On the page the button is disabled
    too - but the controller is the one that runs plunge.py, and it must
    refuse a drain the panel is showing as not valid, whatever sent it (a
    frame the page had not applied yet, a stale page after a reload): a
    drain with nothing in play is the endless cycle PAD-153 was about."""
    pf = window()
    assert pf.key_panel.dyn()["drain"] is False          # nothing in play
    assert pf.api_ball("drain") is False
    assert pf.drv.ran == []
    assert pf.api_ball("plunge") is True                 # Plunge stays live
    assert pf.drv.ran == [("plunge.py", ("plunge",))]


def test_the_dots_on_the_panel_are_no_longer_a_gesture(window):
    """On the panel the dots are read-only: the model marks them so, the
    view hands the page no clickable strip, and a trough click that arrives
    anyway runs nothing. Without a panel the strip is the fallback control
    and still is one."""
    pf = window()
    dots = pf.key_panel.ball_dots
    assert pf.view.trough is dots and not dots.clickable
    st = pf.state("main")
    assert st["panel"]["spec"]["balls"]["clickable"] is False
    assert st["view"]["trough"] is None
    assert pf.api_trough(0) is None
    assert pf.drv.ran == []

    bare = window(panel=False)
    assert bare.key_panel is None
    assert bare.view.trough.clickable
    assert bare.state("main")["view"]["trough"]["clickable"] is True
    assert bare.api_trough(0) == "drain"
    assert bare.drv.ran == [("plunge.py", ("drain",))]


def test_the_note_keeps_the_newest_three_and_folds_in_new_feeder_lines(
        playfield):
    panel, _dots = _panel(playfield)
    w = _watch(playfield, [71, 70, 69, 68, 67], lane=62)
    panel.show_balls(w, 2, ["fed ball one", "fed ball two"])
    panel.ball_say("drain: ball home")
    # The feeder's window slides by one; only the new line may arrive.
    panel.show_balls(w, 3, ["fed ball two", "fed ball three"])
    assert panel.dyn()["note"] == \
        ["fed ball two", "drain: ball home", "fed ball three"]
    assert panel.dyn()["ball"] == "balls 5/6 trough   in play 1   fed 3"


def test_a_long_reply_keeps_its_opening_words_and_drops_older_messages(
        playfield):
    """The first note kept the newest ROWS, so a Plunge reply that wrapped
    past three rows showed "launch   the game puts one there..." with the
    outcome cut off the front.

    The fix has two halves and the WRAP is the page's now. pf.js fitNote()
    renders the note's messages into three rows, DROPPING WHOLE MESSAGES,
    OLDEST FIRST, and a message that alone needs more rows is line-clamped to
    its FIRST three with the browser's ellipsis at the end - so the outcome,
    at the start, is what shows. It measures the rendered font, which Python
    cannot, so it is not tested here.

    The MODEL's half is tested here: the note hands the page WHOLE messages,
    never a row-cut fragment, at most NOTE_LINES of them, newest last and
    oldest dropped first - so the long reply reaches the page intact, opening
    words and all, and the page has what it needs to drop the older one."""
    panel, _dots = _panel(playfield)
    long_reply = "plunge: nothing in the shooter lane to launch " + \
        " ".join(["because of a reason"] * 12)
    panel.ball_say("an older message")
    panel.ball_say(long_reply)
    note = panel.dyn()["note"]
    assert note == ["an older message", long_reply], "whole messages, in order"
    assert note[-1].startswith("plunge: nothing")
    # Newest NOTE_LINES messages; the oldest go first, whole.
    n = playfield.KeyPanel.NOTE_LINES
    for k in range(n + 2):
        panel.ball_say("msg %d" % k)
    assert panel.dyn()["note"] == ["msg %d" % k for k in range(2, n + 2)]
    assert long_reply not in panel.dyn()["note"]
    # A batch that alone overflows keeps its newest, still whole.
    panel.ball_say(*["batch %d" % k for k in range(n + 1)])
    assert panel.dyn()["note"] == ["batch %d" % k for k in range(1, n + 1)]
