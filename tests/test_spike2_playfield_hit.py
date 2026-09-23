"""What a hover or a press on the virtual playfield reaches - on the page.

Queue item 81, spotted by David during item 80's live sweep on
avengers_infinity_le's switch list: "the switch matrix hover zones are not
perfectly aligned with the text". In the Tk window the mechanism was worse than
the tooltip - `_hit()`'s +-8 px search window plus the text's own ~15 px bbox
spanned nearly two ROW_H=17 rows at every cursor position, and reversed()
resolved every overlap to the LOWER row, so the lower half of a row's own
glyphs belonged to the row below it. A click there CLOSED THE WRONG SWITCH.

THE WINDOW IS A WEB PAGE NOW (2026-09-23), and that bug class went with the
canvas: every switch row is its OWN DOM element (pfpage/pf.js schematicView),
holding its own switch in a closure, so the browser - not a search window -
decides which row is under the pointer, and a row's box is exactly its text
line. What is pinned here is what keeps that true:

  * the model gives the page one entry per switch, in node/bit order, each
    carrying its OWN id and tooltip (Schematic.entries);
  * the page binds the press, the rip and the tooltip on the row element and
    sends that row's `e.id` - no coordinate hit test survives in the schematic;
  * the rows are a fixed pitch (pf.css), so no row's box reaches into its
    neighbour's line.

The artwork view's marker hit test is still geometry (Tk's semantics, kept on
purpose - item 24), and it is a pure function now: `pfHit()` in pf.js, run
under Node here. Rings and squares hit on their outline only, inserts on their
disc, switches over coils over inserts, the later marker over the earlier.
"""
import json
import os
import shutil
import subprocess
import sys
import types

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
PF_JS = os.path.join(RIG, "pfpage", "pf.js")
PF_CSS = os.path.join(RIG, "pfpage", "pf.css")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)


def _read(path):
    with open(path, encoding="utf8") as f:
        return f.read()


def _schematic_js():
    src = _read(PF_JS)
    i = src.index("function schematicView(")
    return src[i:src.index("function waitingView(", i)]


def _rows():
    """Two boards, deliberately given out of order: the view sorts them."""
    return [dict(id=62, num=3, node=9, bit=4, name="SHOOTER LANE"),
            dict(id=60, num=1, node=8, bit=33, name="Trough 5"),
            dict(id=61, num=2, node=8, bit=32, name="Trough 6"),
            dict(id=63, num=4, node=9, bit=1, name="Left Ramp Enter")]


@pytest.fixture
def pf(monkeypatch, tmp_path):
    mod = pytest.importorskip("playfield")
    # nothing here may reach WSL or a real run's files
    monkeypatch.setattr(mod, "wsl_run", lambda *a, **k: None)
    monkeypatch.setattr(mod, "load_switch_list", lambda *a, **k: [])
    monkeypatch.setattr(mod, "SW_PATH", str(tmp_path / "no_padsw"))
    return mod


# --------------------------------------------------------------- the schematic

def test_every_row_carries_its_own_switch(pf):
    """The model's half: one entry per switch, grouped by node and in bit
    order under a header per node, each carrying ITS OWN id and a tooltip that
    names that switch - so whatever the page draws a row from, the row can
    only ever act for the switch it shows."""
    view = pf.Schematic(types.SimpleNamespace(), _rows())
    shape = [("hdr", e["hdr"]) if "hdr" in e else ("row", e["id"])
             for e in view.entries]
    assert shape == [("hdr", 8), ("row", 61), ("row", 60),
                     ("hdr", 9), ("row", 63), ("row", 62)]
    for e in view.entries:
        if "id" in e:
            assert e["tip"].startswith("SWITCH  ")
            assert "id %d " % e["id"] in e["tip"], e
    # and that is exactly what the page is sent
    assert view.spec()["entries"] == view.entries


def test_a_row_acts_for_its_own_switch_and_nothing_else():
    """The page's half: the press, the rip and the tooltip hang off the ROW
    ELEMENT and send that row's own `e.id`. The browser decides which element
    is under the pointer, so the Tk bug - a search window wider than a row,
    resolved to the lower one - has nowhere to live."""
    js = _schematic_js()
    assert 'const r = el("div", "r" + (e.live ? "" : " dead"));' in js
    assert 'r.addEventListener("pointerdown"' in js
    assert 'api("hold", e.id)' in js
    assert 'api("rip", e.id, true)' in js and 'api("rip", e.id, false)' in js
    assert 'r.addEventListener("pointermove", (ev) => showTip(e.tip' in js
    # the hold's highlight is the row it was pressed on
    assert 'r.classList.add("held")' in js


def test_there_is_no_coordinate_hit_test_left_in_the_switch_list():
    """"Far from any row hits nothing" by construction: no geometry search is
    left to reach a row the pointer is not on."""
    js = _schematic_js()
    for probe in ("pfHit(", "elementFromPoint", "getBoundingClientRect",
                  "clientY -", "offsetTop"):
        assert probe not in js, probe


def test_the_rows_are_a_fixed_pitch_that_cannot_overlap():
    """A row's box is its line: header and row share one height, nothing pulls
    a row up into its neighbour, and a row never splits across columns."""
    css = _read(PF_CSS)

    def rule(sel):
        i = css.index(sel + " {")
        return css[i:css.index("}", i)]

    r, hdr = rule(".pf-rows .r"), rule(".pf-rows .hdr")
    assert "height: 19px" in r and "height: 19px" in hdr
    assert "break-inside: avoid" in r
    assert "margin" not in r and "margin" not in hdr


def test_the_led_swatches_are_never_a_press_target():
    """The old `_hit_led` rule: the grid beside the rows answers a HOVER (its
    tooltip names the lamp) and nothing else - a cell can never become
    something a press tries to close."""
    js = _schematic_js()
    i = js.index("for (const c of blk.cells)")
    cell = js[i:js.index("cs.append(d);", i)]
    assert 'addEventListener("pointermove"' in cell
    assert "pointerdown" not in cell and "api(" not in cell


# ---------------------------------------------------------- the artwork markers

def _node():
    return shutil.which("node")


needs_node = pytest.mark.skipif(_node() is None, reason="needs Node.js")


def _hits(cases):
    """pfHit(view, fx, scale, px, py) for each case, run by Node against the
    shipped pf.js (which require() can load: its DOM code is guarded)."""
    js = ("const { pfHit } = require(%s);\n"
          "const cases = JSON.parse(%s);\n"
          "console.log(JSON.stringify(cases.map((c) => pfHit(...c))));\n"
          % (json.dumps(PF_JS), json.dumps(json.dumps(cases))))
    run = subprocess.run([_node(), "-e", js], capture_output=True, text=True,
                         timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _view(switches=(), coils=(), fixtures=()):
    return {"switches": [list(s) for s in switches],
            "coils": [list(c) for c in coils],
            "fixtures": [list(f) for f in fixtures]}


@needs_node
def test_an_unfilled_ring_hits_on_its_outline_only():
    """Tk's find_overlapping on a fill="" oval: the 6 px box round the pointer
    has to touch the 2 px stroke at radius 6. The exact centre of a bare ring
    is NOTHING (swspintest.py measured it on ring 47)."""
    v = _view(switches=[(0, 100, 100, 47)])
    got = _hits([[v, {}, 1, 100, 100],        # dead centre: the hole
                 [v, {}, 1, 106, 100],        # on the stroke
                 [v, {}, 1, 100, 94],         # on the stroke, above
                 [v, {}, 1, 109.9, 100],      # the box still touches it
                 [v, {}, 1, 110.5, 100]])     # the box has left it
    assert got == [None, ["switch", 0], ["switch", 0], ["switch", 0], None]


@needs_node
def test_an_unfilled_coil_square_hits_on_its_outline_only():
    v = _view(coils=[(0, 200, 200, "6:8")])
    got = _hits([[v, {}, 1, 200, 200],        # inside the square: a hole
                 [v, {}, 1, 207, 200],        # on the stroke
                 [v, {}, 1, 209, 209],        # its corner
                 [v, {}, 1, 211.5, 200]])     # past it
    assert got == [None, ["coil", 0], ["coil", 0], None]


@needs_node
def test_an_insert_hits_on_its_disc_dark_or_lit():
    """A dark insert is drawn at LED_R with a 1 px outline (half a pixel more
    reach); a lit one at the radius its duty gives it and nothing more."""
    dark = _view(fixtures=[(0, 300, 300)])
    lit = {"0": [255, 128, 0, 1.0, 3.8]}
    got = _hits([[dark, {}, 1, 300, 300],         # centre: the disc
                 [dark, {}, 1, 308.9, 300],       # 5.9 from the box: in
                 [dark, {}, 1, 309.6, 300],       # 6.6: out
                 [dark, lit, 1, 300, 300],        # lit, centre
                 [dark, lit, 1, 306.7, 300],      # 3.7 from the box: in
                 [dark, lit, 1, 307.2, 300]])     # 4.2 > 3.8: out
    assert got == [["led", 0], ["led", 0], None, ["led", 0], ["led", 0], None]


@needs_node
def test_switches_over_coils_over_inserts():
    """The stacking the Tk canvas had: inserts drawn first, then coils, then
    switches - so where two markers are both under the pointer the higher kind
    wins, and in a hole the one below shows through."""
    v = _view(switches=[(0, 400, 400, 53)], coils=[(0, 400, 400, "6:8")],
              fixtures=[(0, 400, 400)])
    got = _hits([[v, {}, 1, 406, 400],        # ring AND square: the switch
                 [v, {}, 1, 409, 409],        # the square's corner only
                 [v, {}, 1, 400, 400]])       # both hollow: the insert
    assert got == [["switch", 0], ["coil", 0], ["led", 0]]
    no_switch = _view(coils=[(0, 400, 400, "6:8")], fixtures=[(0, 400, 400)])
    assert _hits([[no_switch, {}, 1, 407, 400]]) == [["coil", 0]]


@needs_node
def test_the_later_marker_of_a_kind_is_on_top():
    """reversed(find_overlapping): the last one created is the topmost."""
    v = _view(switches=[(0, 500, 500, 1), (1, 504, 500, 2)])
    assert _hits([[v, {}, 1, 497, 500]]) == [["switch", 1]]
    v = _view(fixtures=[(0, 600, 600), (1, 602, 600)])
    assert _hits([[v, {}, 1, 601, 600]]) == [["led", 1]]


@needs_node
def test_the_artwork_scale_moves_the_markers_not_their_size():
    """Positions are in artwork pixels and scale with the picture; the marker
    shapes are screen pixels and do not (the Tk window's rule)."""
    v = _view(switches=[(0, 100, 100, 47)])
    got = _hits([[v, {}, 2, 206, 200],        # on the ring at 2x (still r 6)
                 [v, {}, 2, 106, 100],        # where the ring was at 1x
                 [v, {}, 2, 200, 200],        # the hole moved with it
                 [v, {}, 2, 212, 200]])       # a ring scaled to r 12: no
    assert got == [["switch", 0], None, None, None]


def test_the_artwork_view_uses_the_pure_hit_test():
    """Hover and press both go through the one function tested above."""
    src = _read(PF_JS)
    i = src.index("function fieldView(")
    body = src[i:src.index("function schematicView(", i)]
    assert "function hit(px, py) { return pfHit(V, fx, scale, px, py); }" in body
    assert body.count("hit(...at(e))") == 2          # pointermove, pointerdown
