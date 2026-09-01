"""Schematic._hit(): the hover/click zone of a switch row is its own text.

Queue item 81, spotted by David during item 80's live sweep on
avengers_infinity_le's switch list: "the switch matrix hover zones are not
perfectly aligned with the text". The mechanism was worse than the tooltip -
`_hit()`'s ±8 px search window plus the text's own ~15 px bbox spanned nearly
two ROW_H=17 rows at every cursor position, and reversed() resolved every
overlap to the LOWER row, so the lower half of a row's own glyphs belonged to
the row below it. on_press() goes through the same `_hit()`, so a click there
CLOSED THE WRONG SWITCH.

REAL Tk, deliberately, like the late-tables and action-row tests: what is
under test is find_overlapping and bbox geometry - the exact font metrics of
Consolas 9 against a 17 px row pitch - which a stub canvas would fake into
whatever the test hoped for. The rows here are drawn at the real view's exact
geometry (anchor="w", y = 14 + ri * ROW_H, same font), and `Schematic._hit`
is called unbound on a minimal stand-in, so no window, driver or rig is
needed and this answers in milliseconds.
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

ROWS = 5


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


def _view(root):
    """A minimal Schematic stand-in: real canvas, real rows, real info dict.

    The geometry is the real view's, copied not parameterised, so a change
    to the view's layout that breaks this test is a change that needs the
    test looked at - that is the point of it.
    """
    import tkinter as tk
    import playfield

    cv = tk.Canvas(root, width=300, height=200, highlightthickness=0)
    cv.pack()
    obj = types.SimpleNamespace(cv=cv, info={})
    ids = []
    for ri in range(ROWS):
        y = 14 + ri * playfield.Schematic.ROW_H
        i = cv.create_text(18, y, anchor="w", font=("Consolas", 9),
                           text="%3d  SWITCH ROW %d" % (60 + ri, ri))
        obj.info[i] = dict(kind="switch", d=dict(id=60 + ri))
        ids.append(i)
    root.update_idletasks()
    return playfield, obj, ids


def _ev(x, y):
    return types.SimpleNamespace(x=x, y=y)


def test_every_point_of_a_rows_own_text_hits_that_row():
    """The acceptance line, literally: hovering anywhere over a row's visible
    glyphs resolves to THAT row. Before the fix this failed for the lower
    half of every row but the last - the ±8 window reached the next row's
    bbox and reversed() preferred it."""
    root = _root()
    try:
        playfield, obj, ids = _view(root)
        for i in ids:
            x0, y0, x1, y1 = obj.cv.bbox(i)
            x = (x0 + x1) // 2
            wrong = [y for y in range(y0 + 1, y1)
                     if playfield.Schematic._hit(obj, _ev(x, y)) != i]
            assert not wrong, (
                "row bbox y %d..%d: cursor at y=%s resolved to another row"
                % (y0, y1, wrong))
    finally:
        root.destroy()


def test_the_gap_between_rows_belongs_to_the_nearer_row():
    """The generous capture stays - a cursor in the 2 px gap between glyph
    boxes still hits, and it hits the row whose text is nearer."""
    root = _root()
    try:
        playfield, obj, ids = _view(root)
        a, b = ids[1], ids[2]
        _, ay0, _, ay1 = obj.cv.bbox(a)
        bx0, by0, bx1, by1 = obj.cv.bbox(b)
        ca, cb = (ay0 + ay1) / 2.0, (by0 + by1) / 2.0
        x = (bx0 + bx1) // 2
        just_above_mid = int(ca + (cb - ca) * 0.35)     # nearer a
        just_below_mid = int(ca + (cb - ca) * 0.65)     # nearer b
        assert playfield.Schematic._hit(obj, _ev(x, just_above_mid)) == a
        assert playfield.Schematic._hit(obj, _ev(x, just_below_mid)) == b
    finally:
        root.destroy()


def test_far_from_any_row_hits_nothing():
    root = _root()
    try:
        playfield, obj, ids = _view(root)
        _, _, x1, _ = obj.cv.bbox(ids[0])
        assert playfield.Schematic._hit(obj, _ev(x1 + 60, 14)) is None
    finally:
        root.destroy()
