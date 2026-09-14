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

Real Tk throughout, for the reason the rest of these files give: bindings and
pack/canvas placement are what is under test, and a stub would record calls
Tk never delivers.
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


def _root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError as exc:                          # no display / no Tcl
        pytest.skip("Tk unavailable: %s" % exc)
    root.attributes("-alpha", 0)
    root.geometry("+10000+10000")
    return root


class FakeDrv:
    """Records presses, releases and spawned helpers; spawns nothing."""

    def __init__(self):
        self.pressed, self.released, self.ran = [], [], []

    def press(self, sw):
        self.pressed.append(sw)

    def release(self, sw):
        self.released.append(sw)

    def run_script(self, script, *args, done=None):
        self.ran.append((script, args))


def _switch_rows():
    rows = [dict(id=66 + i, num=15 + i, node=8, bit=32 + i,
                 name="Trough %d" % pos)
            for i, pos in enumerate((6, 5, 4, 3, 2, 1))]
    rows.append(dict(id=34, num=4, node=1, bit=4, name="Action Button"))
    return rows


@pytest.fixture()
def with_binds(monkeypatch, tmp_path):
    """A padbinds file the views will find, and no persistent WSL helper."""
    import playfield
    path = tmp_path / "padbinds"
    path.write_text("\n".join(BINDS) + "\n", encoding="utf8")
    monkeypatch.setattr(playfield, "BINDS_PATH", str(path))
    monkeypatch.setattr(playfield.SwitchPipe, "_ensure", lambda self: False)
    return playfield


def test_the_schematic_row_goes_when_the_panel_is_up_and_its_actions_stay(
        with_binds):
    playfield = with_binds
    root = _root()
    try:
        view = playfield.Schematic(root, _switch_rows())
        panel = view.key_panel
        assert panel is not None, "the padbinds file should build a panel"
        assert all(b.winfo_manager() == "" for b in view._acts), \
            "the bottom row is still packed beside the panel"
        # Its actions, on the panel instead.
        assert [b.cget("text") for b in panel.ball_btns] == \
            ["Plunge", "Drain", "Reset balls"]
        assert panel.clear_btn.cget("text") == "Clear switch alerts"
        view.drv = FakeDrv()
        panel.clear_btn.invoke()
        assert view.drv.ran == [("swexercise.py", ())]
    finally:
        root.destroy()


def test_without_a_panel_the_row_is_still_the_way_in(monkeypatch, tmp_path):
    import playfield
    monkeypatch.setattr(playfield, "BINDS_PATH", str(tmp_path / "absent"))
    root = _root()
    try:
        view = playfield.Schematic(root, _switch_rows())
        assert view.key_panel is None
        assert all(b.winfo_manager() == "pack" for b in view._acts)
        assert "Clear switch alerts" in [b.cget("text") for b in view._acts]
    finally:
        root.destroy()


def _bare_field(root, w, h):
    """Enough of a Field to lay out its bottom edge - the actions tests'
    shortcut, for the same reason."""
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


def _labels_on_canvas(f):
    out = {}
    for item in f.cv.find_all():
        if f.cv.type(item) != "window":
            continue
        wdg = f.cv.nametowidget(f.cv.itemcget(item, "window"))
        try:
            label = wdg.cget("text")
        except Exception:                                   # noqa: BLE001
            label = "<picker>"
        out[label] = f.cv.bbox(item)
    return out


def test_the_artwork_row_hides_and_the_state_cluster_takes_the_bottom_edge():
    root = _root()
    import playfield
    saved, refresh = playfield.SAVESTATES, playfield.StateOps._slots_refresh
    playfield.SAVESTATES = True
    playfield.StateOps._slots_refresh = lambda self, **kw: None
    try:
        f = _bare_field(root, 420, 887)
        actions = [lbl for lbl, _s, _a in playfield.WINDOW_ACTIONS]
        shown = _labels_on_canvas(f)
        assert all(a in shown for a in actions), shown

        playfield.show_action_row(f, False)
        hidden = _labels_on_canvas(f)
        assert not any(a in hidden for a in actions), hidden
        assert hidden, "the state cluster went with the row"
        bottom = 887 - f.ACT_PAD
        assert {bb[3] for bb in hidden.values()} == {bottom}, \
            "with the row gone the state controls sit on the bottom edge"

        playfield.show_action_row(f, True)
        back = _labels_on_canvas(f)
        assert all(a in back for a in actions), back
        assert len(back) == len(shown), "a re-show must not duplicate widgets"
    finally:
        playfield.StateOps._slots_refresh = refresh
        playfield.SAVESTATES = saved
        root.destroy()


def _panel(drv):
    import keybinds
    import playfield
    root = _root()
    panel = playfield.KeyPanel(root, keybinds.parse(BINDS), drv)
    panel.cv.pack()
    root.update()
    return root, panel


def _row_index(panel, label):
    return next(i for i, r in enumerate(panel.rows) if r["label"] == label)


def test_start_and_coin_rows_press_and_release_through_the_driver():
    """A real pointer press and release on the row, so the hit target (a
    filled box, not a fill="" one) is under test and not just the handler."""
    drv = FakeDrv()
    root, panel = _panel(drv)
    try:
        for label, sw in (("Start Button", 36), ("Left Coin", 39)):
            box = panel._items[_row_index(panel, label)][0]
            x0, y0, x1, y1 = panel.cv.coords(box)
            x, y = int(x1 - 6), int((y0 + y1) / 2)    # off the text, on the box
            panel.cv.event_generate("<ButtonPress-1>", x=x, y=y)
            panel.cv.event_generate("<ButtonRelease-1>", x=x, y=y)
            root.update()
            assert drv.pressed[-1] == sw and drv.released[-1] == sw, label
    finally:
        root.destroy()


def test_other_key_rows_are_still_not_clickable():
    """Only the two the row stood in for; a flipper row that pressed on click
    would be a switch closed by a stray mouse button."""
    root, panel = _panel(FakeDrv())
    try:
        box = panel._items[_row_index(panel, "Left Flipper")][0]
        assert not panel.cv.tag_bind(box, "<ButtonPress-1>")
    finally:
        root.destroy()


def test_a_panel_without_a_view_has_no_clear_button():
    root, panel = _panel(FakeDrv())
    try:
        assert panel.clear_btn is None
    finally:
        root.destroy()
