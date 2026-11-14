"""PAD-1014 (DragonRR): snapping in the Scenes editor.  Snap to grid (on/off, a grid size),
Snap to other parts (edges and middles of the other pictures, lines of text and the screen),
and the point of what is dragged that snaps: Auto (any edge or the middle) or one of nine
handles.  The math is pure functions in text_scenes.js, run here under Node; the canvas puts
them on every move, box-corner and scale drag (Alt held: none)."""

import json
import os
import re
import shutil
import subprocess

import pytest

_TABS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                     "webui", "static", "js", "tabs")

_RUN = r"""
const m = await import("./tabs/text_scenes.js");
const { snapMove, snapPoint, snapScale, snapDrag, boxOfPts, dragTo, SNAP_HANDLES, exactBox, r3 } = m;
const out = { handles: SNAP_HANDLES.map(([k]) => k) };
const W = 1360, H = 768;
const other = { x: 400, y: 200, w: 100, h: 60 };          // edges 400/450/500 across, 200/230/260 down
const base = { W, H, tol: 6, others: [other], grid: false, size: 10, objects: true, handle: "auto" };
const b = { x: 100, y: 500, w: 40, h: 20 };

// Auto: its left edge comes to 403 (3 off the other's left edge): pulled onto 400
out.autoLeft = snapMove(b, 303, 0, base);
// its right edge near the other's middle (450): 140 + 312 = 452 -> 450
out.autoRight = snapMove(b, 312, 0, base);
// too far from any line: left as dragged (on neither grid nor part)
out.free = snapMove(b, 340, -11, base);
// a chosen handle: only its middle snaps (left edge near 400 does nothing; middle near 450 does)
out.midOnly = snapMove(b, 302, 0, { ...base, handle: "mc" });
out.midHit = snapMove(b, 328, 0, { ...base, handle: "mc" });
// bottom-right handle onto the other's top edge (200): y + 20 + dy = 198 -> 200
out.brTop = snapMove(b, 0, -322, { ...base, handle: "br" });
// the screen's middle across (680)
out.screenMid = snapMove(b, 559, 0, { ...base, others: [] });
// grid only: top-left on a 20 px grid
out.grid = snapMove(b, 33, 7, { ...base, objects: false, grid: true, size: 20 });
// grid with a chosen handle: the handle sits on the grid
out.gridHandle = snapMove(b, 33, 7, { ...base, objects: false, grid: true, size: 20, handle: "mc" });
// a part's line beats the grid
out.both = snapMove(b, 303, 0, { ...base, grid: true, size: 32 });
// a text box's corner
out.point = snapPoint(497, 263, base);
// a picture scaled about (0, 0) from its corner (100, 50): the corner at f=4.03 is (403, 201.5)
out.scale = snapScale([0, 0], [100, 50], 4.03, base);
// snapDrag: off / Alt (null) leaves the drag as dragTo made it
const press = { mode: "move", id: "7", ids: [7], dx: 0, dy: 0, sx: 0, sy: 0, x0: 100, y0: 500, b, others: [other] };
const d = dragTo(press, 50, 0, 403, 500);
out.off = snapDrag(d, null) === d;
out.notStarted = snapDrag(press, base) === press;
out.on = snapDrag(d, base);
out.box = boxOfPts([[3, 9], [10, 2], [7, 4]]);
// PAD-1211: a part whose left edge is at 485.7 snaps onto 400 by an exact move (-85.7), and the
// grid puts it on 480 (-5.7), not a whole-pixel move that leaves it 0.3 off
const fb = { x: 485.7, y: 189, w: 346.2, h: 476.3 };
out.fracPart = snapMove(fb, -82, 0, { ...base, others: [other] });
out.fracGrid = snapMove(fb, -3, 0, { ...base, objects: false, grid: true, size: 10 });
out.exact = exactBox({ x: 486, y: 189, w: 346, h: 476, box: [485.7, 189, 346.2, 476.3] });
out.shown = exactBox({ x: 486, y: 189, w: 346, h: 476 });
out.r3 = [r3(-85.70000000001), r3(0.1 + 0.2)];
console.log(JSON.stringify(out));
"""


def _src():
    with open(os.path.join(_TABS, "text_scenes.js"), encoding="utf-8") as f:
        return f.read()


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_snapping_math(tmp_path):
    (tmp_path / "tabs").mkdir()
    (tmp_path / "core").mkdir()
    src = _src()
    (tmp_path / "tabs" / "text_scenes.js").write_text(src, encoding="utf-8")
    stubs = {}
    for m in re.finditer(r"import \{([^}]*)\} from \"\.\./core/(\w+)\.js\"", src):
        stubs.setdefault(m.group(2), set()).update(
            n.strip() for n in m.group(1).split(",") if n.strip())
    for mod, names in stubs.items():
        (tmp_path / "core" / (mod + ".js")).write_text(
            "".join("export const %s = () => null;\n" % n for n in sorted(names)),
            encoding="utf-8")
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "run.js").write_text(_RUN, encoding="utf-8")
    run = subprocess.run([shutil.which("node"), str(tmp_path / "run.js")],
                         capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    assert run.returncode == 0, run.stderr
    g = json.loads(run.stdout)
    # which ways each snapped (PAD-1211: the drop keeps those exact)
    snapped = {k: v.pop("snapped") for k, v in g.items() if isinstance(v, dict) and "snapped" in v}
    assert snapped["autoLeft"] == [True, False] and snapped["free"] == [False, False]
    assert snapped["grid"] == [True, True] and snapped["both"] == [True, True]
    assert snapped["point"] == [True, True] and snapped["on"] == [True, False]
    assert g["handles"] == ["tl", "tc", "tr", "ml", "mc", "mr", "bl", "bc", "br"]
    assert g["autoLeft"] == {"dx": 300, "dy": 0, "guides": [{"x": 400}]}
    assert g["autoRight"] == {"dx": 310, "dy": 0, "guides": [{"x": 450}]}
    assert g["free"] == {"dx": 340, "dy": -11, "guides": []}
    assert g["midOnly"] == {"dx": 302, "dy": 0, "guides": []}
    assert g["midHit"] == {"dx": 330, "dy": 0, "guides": [{"x": 450}]}
    assert g["brTop"] == {"dx": 0, "dy": -320, "guides": [{"y": 200}]}
    assert g["screenMid"] == {"dx": 560, "dy": 0, "guides": [{"x": 680}]}
    # 133 -> 140, 507 -> 500 (top-left on the 20 px grid), no guides
    assert g["grid"] == {"dx": 40, "dy": 0, "guides": []}
    # middle (120 + 33 = 153 -> 160, 510 + 7 = 517 -> 520)
    assert g["gridHandle"] == {"dx": 40, "dy": 10, "guides": []}
    # across: the part's edge; down: 500 is not near a line, so the 32 px grid (500 -> 512)
    assert g["both"] == {"dx": 300, "dy": 12, "guides": [{"x": 400}]}
    assert g["point"] == {"x": 500, "y": 260, "guides": [{"x": 500}, {"y": 260}]}
    # the nearer: across is 3 off 400, down 1.5 off 200 -> down wins, f = 200 / 50
    assert g["scale"] == {"f": 4, "guides": [{"y": 200}]}
    assert g["off"] is True
    assert g["notStarted"] is True
    assert g["on"]["dx"] == 300 and g["on"]["guides"] == [{"x": 400}]
    assert g["box"] == {"x": 3, "y": 2, "w": 7, "h": 7}
    # PAD-1211: fractional edges land exactly on the line / grid
    assert snapped["fracPart"] == [True, False] and snapped["fracGrid"] == [True, True]
    assert abs(g["fracPart"]["dx"] - -85.7) < 1e-9 and g["fracPart"]["guides"] == [{"x": 400}]
    assert abs(g["fracGrid"]["dx"] - -5.7) < 1e-9 and g["fracGrid"]["dy"] == 1
    assert g["exact"] == {"x": 485.7, "y": 189, "w": 346.2, "h": 476.3}
    assert g["shown"] == {"x": 486, "y": 189, "w": 346, "h": 476}
    assert g["r3"] == [-85.7, 0.3]


def test_canvas_snaps_every_drag_and_offers_the_menu():
    src = _src()
    # every pointer move goes through the snapping, Alt held turns it off
    assert "snapDrag(dragTo(q, e.clientX, e.clientY, x, y), snapOf(e, q))" in src
    assert "e.altKey" in src
    # the Snap menu is on the bar under the preview
    tree_actions = src[src.index("function TreeActions"):]
    assert "<${SnapButton} />" in tree_actions[:2000]
    # the settings are the viewer's own and kept (and survive storage that throws)
    assert 'const SNAP_KEY = "pad.scenes.snap"' in src


def test_a_snapped_drop_lands_on_the_line():
    """PAD-1211 (DragonRR: "after letting go of the mouse there always seems to be a few pixels
    shift left of the snapped asset"): the drop rounded the snapped move to whole pixels and a
    selected part snapped by the rounded box the panel shows, so a part at 485.7 landed up to a
    pixel off the line (a few pixels on a zoomed preview).  A way that snapped now keeps the
    move exact; one dragged freely still moves by whole pixels."""
    src = _src()
    up = src[src.index("  const up = () => {\n    const d = drag;"):]
    up = up[:up.index("  const key = (e) =>")]
    assert "sn[0] ? r3(d.dx) : Math.round(d.dx)" in up
    assert "sn[1] ? r3(d.dy) : Math.round(d.dy)" in up
    assert "if (dx || dy) send(" in up                 # a snap under a pixel still moves it
    assert "x: r3(b.x), y: r3(b.y), w: r3(b.w), h: r3(b.h)" in up
    # the selection (what a drag snaps by, the corners a resize keeps) is the exact box
    assert "const selBox = boxLive || (p && !multi && p.x != null ? exactBox(p) : null);" in src
    # X and Y in the panel move to the number typed, from the exact box
    assert 'r3(Number(v) - exactBox(p).x)' in src and 'r3(Number(v) - exactBox(p).y)' in src
    # the pointer is read inside the canvas's border, where the picture and outlines are
    to = src[src.index("  const toStage = (e) =>"):]
    assert "el.clientLeft" in to[:400] and "r.width - 2 * bx" in to[:400]
    css = open(os.path.join(_TABS, "..", "..", "css", "tabs", "text_scenes.css"),
               encoding="utf-8").read()
    assert ".tree-canvas { border: none; box-shadow: 0 0 0 1px var(--line-2); }" in css
