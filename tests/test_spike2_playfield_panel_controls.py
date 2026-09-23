"""The bottom action row retires when the key panel is up (PAD-134).

David, looking at Insert coin / Start / Plunge / Reset balls / Clear alerts:
"do we still need any of these buttons on the virtual playfield? most of them
are covered by the keyboard shortcuts anyways. do any of them still do
antyhing unique?" Then: "Yes do all these and label it 'clear switch alerts'".

So every action got a home on the key panel and the row only exists without
one:

  * Start Button and Left Coin are clickable rows in the key list, because a
    mouse-only player needs them and the row was their only way in;
  * Reset balls sits with Plunge and Drain in the BALLS section;
  * Clear switch alerts sits under SERVICE, renamed;
  * the row itself is hidden on attach, in BOTH views, and comes back if the
    panel does not.

THE WINDOW IS A WEB PAGE NOW (2026-09-23). The key panel is a MODEL
(`KeyPanel.spec()` / `dyn()`) that pf.js draws, and the page's presses come
back as the controller's api_* calls. So what is under test is what the model
OFFERS (which rows are clickable, whether there is a clear button, whether
the controller still sends the action row) and what the page's calls DO when
they land on a fake driver - the same two questions the Tk tests asked of
bindings and placement, asked of the half that is still Python.
"""
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)

BINDS = [
    "# key\tflags\tids\tlabel  (test)",
    "Enter\tc\t25\tService Select",
    "=\tc\t26\tService Plus",
    "-\tc\t27\tService Minus",
    "Bksp\tc\t28\tService Back",
    "1\tc\t36\tStart Button",
    "5\tc\t39\tLeft Coin",
    "C\tct\t33\tCoin Door Closed",
    "Left\t-\t60\tLeft Flipper",
    "B\tt\t66,67,68,69,70,71\t6 balls in trough",
]


class FakeDrv:
    """Records presses, releases and spawned helpers; spawns nothing.

    Installed as `playfield.SwitchDriver`, so the controller and the key
    panel it builds hold the same one, as they do in the real window."""

    def __init__(self):
        self.pressed, self.released, self.ran = [], [], []

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


def _switch_rows():
    rows = [dict(id=66 + i, num=15 + i, node=8, bit=32 + i,
                 name="Trough %d" % pos)
            for i, pos in enumerate((6, 5, 4, 3, 2, 1))]
    rows.append(dict(id=34, num=4, node=1, bit=4, name="Action Button"))
    return rows


#: Every wsl_run a test let through. The fixture fails the test on any.
_WSL = []


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """No rig, no WSL, no desk: every file the window reads is pinned under
    tmp_path, and every way out to WSL is stubbed BEFORE a Playfield (and so
    a SwitchDriver) is built. padbinds is ABSENT unless a test writes it."""
    import playfield
    del _WSL[:]
    monkeypatch.setattr(playfield, "wsl_run", lambda *a: _WSL.append(a))
    monkeypatch.setattr(playfield, "state_run", lambda *a, **k: None)
    monkeypatch.setattr(playfield, "state_slots", lambda: {})
    monkeypatch.setattr(playfield.SwitchPipe, "_ensure", lambda self: False)
    monkeypatch.setattr(playfield, "SwitchDriver", FakeDrv)
    monkeypatch.setattr(playfield, "BINDS_PATH", str(tmp_path / "padbinds"))
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


@pytest.fixture()
def with_binds(offline):
    """A padbinds file the controller will find."""
    playfield = offline
    with open(playfield.BINDS_PATH, "w", encoding="utf8") as f:
        f.write("\n".join(BINDS) + "\n")
    return playfield


def _window(playfield, monkeypatch, field=False):
    monkeypatch.setattr(playfield, "layout_is_usable", lambda: field)
    pf = playfield.Playfield()
    assert pf.kind == ("field" if field else "schematic")
    return pf


def _act_labels(pf):
    return [lbl for _i, lbl in pf.state("main")["acts"]]


def test_the_schematic_row_goes_when_the_panel_is_up_and_its_actions_stay(
        with_binds, monkeypatch):
    playfield = with_binds
    pf = _window(playfield, monkeypatch)
    panel = pf.key_panel
    assert panel is not None, "the padbinds file should build a panel"
    assert not pf.acts_shown
    assert _act_labels(pf) == [], \
        "the bottom row is still sent beside the panel"
    st = pf.state("main")
    assert st["panel"] is not None
    # Its actions, on the panel instead: the BALLS section (the page draws
    # Plunge / Drain / Reset balls off `balls` and sends api_ball) and the
    # SERVICE section's clear button.
    assert st["panel"]["spec"]["balls"] is not None
    assert st["panel"]["spec"]["clear"] == "Clear switch alerts"
    # a ball in play, so Drain is live (the greyed case refuses: see
    # test_spike2_playfield_balls.test_a_grey_drain_press_is_nothing)
    pf.key_panel._drain_live = True
    for what in ("plunge", "drain", "reset"):
        assert pf.api_ball(what) is True
    assert pf.drv.ran == [("plunge.py", ("plunge",)), ("plunge.py", ("drain",)),
                          ("plunge.py", ("reset",))]
    del pf.drv.ran[:]
    pf.api_clear_alerts()
    assert pf.drv.ran == [("swexercise.py", ())]


def test_without_a_panel_the_row_is_still_the_way_in(offline, monkeypatch):
    playfield = offline
    pf = _window(playfield, monkeypatch)
    assert pf.key_panel is None
    assert pf.acts_shown
    assert pf.state("main")["panel"] is None
    assert "Clear switch alerts" in _act_labels(pf)


def _poll_binds(pf):
    """One pass of the controller's paced switch read with the padbinds
    check due NOW - the path by which a panel arrives or leaves mid-run."""
    pf.view.sw.poll = lambda: True
    pf._binds_next = 0
    frame = {}
    assert pf.poll_switches(pf.view, frame)
    return frame


def test_the_artwork_row_hides_and_the_state_cluster_stays(
        offline, monkeypatch):
    """The artwork view's row goes with the panel's ARRIVAL mid-run (padglhost
    writes padbinds once it is up), comes back when the panel does not, and
    the state cluster is untouched either way.

    In Tk this also asserted that the state controls dropped to the bottom
    edge once the row was gone, and that a re-show did not duplicate
    widgets. The first is the page's flex layout now (the state cluster is
    its own element and the action row simply is not rendered); the second
    is checked as the model's half: the re-shown row is exactly
    WINDOW_ACTIONS again, once each."""
    playfield = offline
    monkeypatch.setattr(playfield, "SAVESTATES", True)
    pf = _window(playfield, monkeypatch, field=True)
    actions = [lbl for lbl, _s, _a in playfield.WINDOW_ACTIONS]
    assert _act_labels(pf) == actions
    assert pf.view.trough is not None and pf.view.trough.clickable

    with open(playfield.BINDS_PATH, "w", encoding="utf8") as f:
        f.write("\n".join(BINDS) + "\n")
    assert _poll_binds(pf).get("layout") is True
    assert pf.key_panel is not None
    st = pf.state("main")
    assert st["acts"] == []
    assert st["savestates"] is True and len(st["slots"]) == 10, \
        "the state cluster went with the row"
    # the trough moved onto the panel, read-only
    assert pf.view.trough is pf.key_panel.ball_dots
    assert st["view"]["trough"] is None

    os.remove(playfield.BINDS_PATH)
    assert _poll_binds(pf).get("layout") is True
    assert pf.key_panel is None
    st = pf.state("main")
    assert [lbl for _i, lbl in st["acts"]] == actions, \
        "a re-show must bring the row back once, whole"
    assert st["savestates"] is True
    # and the artwork corner's clickable strip is back as the fallback
    assert pf.view.trough is not None and pf.view.trough.clickable


def _panel(drv, on_action=None):
    import keybinds
    import playfield
    return playfield.KeyPanel(keybinds.parse(BINDS), drv, on_action=on_action)


def _spec_row(panel, label):
    return next(r for r in panel.spec()["rows"] if r["label"] == label)


def test_start_and_coin_rows_press_and_release_through_the_driver(
        with_binds, monkeypatch):
    """The model offers the two rows as clickable (their switch id is the
    page's hook), and the page's press and release - api_row down / up -
    reach the driver as a HOLD, not a pulse.

    In Tk this generated a real pointer press on the row's box, because the
    hit target (a filled box, not a fill="" one) was part of the risk. The
    hit target is the page's DOM element now; what Python owns is which rows
    carry a `click` id and what arrives when one is sent."""
    playfield = with_binds
    pf = _window(playfield, monkeypatch)
    panel, drv = pf.key_panel, pf.drv
    for label, sw in (("Start Button", 36), ("Left Coin", 39)):
        assert _spec_row(panel, label)["click"] == sw, label
        n_released = len(drv.released)
        assert pf.api_row(sw, True)
        assert drv.pressed[-1] == sw, label
        assert len(drv.released) == n_released, "%s: released on press" % label
        assert pf.api_row(sw, False)
        assert drv.released[-1] == sw, label


def test_other_key_rows_are_still_not_clickable():
    """Only the two the row stood in for; a flipper row that pressed on click
    would be a switch closed by a stray mouse button. Refused on both sides:
    the spec gives the page no click id for it, and a row_press for it (a
    stale or forged page call) does nothing."""
    drv = FakeDrv()
    panel = _panel(drv)
    assert _spec_row(panel, "Left Flipper")["click"] is None
    clickable = [r["label"] for r in panel.spec()["rows"] if r["click"]]
    assert sorted(clickable) == ["Left Coin", "Start Button"]
    panel.row_press(60)
    panel.row_release()
    assert drv.pressed == [] and drv.released == []


def test_a_panel_without_a_view_has_no_clear_button():
    panel = _panel(FakeDrv())
    assert panel.clear_action is None
    assert panel.spec()["clear"] is None
    # ...and with one, it is the swexercise.py action, under its new name
    with_view = _panel(FakeDrv(), on_action=lambda *a: None)
    assert with_view.spec()["clear"] == "Clear switch alerts"
