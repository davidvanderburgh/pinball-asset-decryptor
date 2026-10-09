"""PAD-447 (DragonRR): a click on a picture or a line of text in the Scenes preview often moved
it a little - the mouse jiggles a pixel or two while the button is down, and the preview took
any movement at all as a drag (one screen px is two glass px at the preview's usual size).
Now a press moves, resizes or scales nothing until the pointer has gone DRAG_SLOP screen px
from where it went down; from then on it follows the pointer from that spot, and a press that
never got that far is a click: it picks, and sends no edit."""

import json
import os
import re
import shutil
import subprocess

import pytest

_TABS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                     "webui", "static", "js", "tabs")

_RUN = r"""
const { dragTo, DRAG_SLOP } = await import("./tabs/text_scenes.js");
const out = { slop: DRAG_SLOP };
// screen px -> stage px at the preview's usual size (1360 px of glass drawn 644 px wide)
const k = 2.11;
const at = (sx, sy) => [sx, sy, 200 + (sx - 100) * k, 200 + (sy - 100) * k];

// a move: a jiggle of up to 4 screen px with the button held is still the press
const press = { mode: "move", id: "7", ids: [7], dx: 0, dy: 0, sx: 100, sy: 100, x0: 200, y0: 200 };
let d = press;
for (const [sx, sy] of [[101, 100], [102, 101], [103, 102], [102, 103], [103, 102]]) d = dragTo(d, ...at(sx, sy));
out.jiggle = { same: d === press, go: !!d.go, dx: d.dx, dy: d.dy };
// past the slop it is a drag, measured from where the button went down
d = dragTo(d, ...at(110, 100));
out.drag = { go: d.go, dx: d.dx, dy: d.dy };
// and stays one when the pointer comes back near the start (a small move on purpose)
d = dragTo(d, ...at(101, 100));
out.back = { go: d.go, dx: d.dx, dy: d.dy };

// a text's box: pressed 6 stage px off its bottom-right corner (110, 60)
const box = { mode: "box", node: 3, fx: 10, fy: 10, mx: 110, my: 60, x: 110, y: 60,
              sx: 50, sy: 50, x0: 104, y0: 57 };
out.boxJiggle = dragTo(box, 52, 51, 108.2, 59.1) === box;
const b = dragTo(box, 60, 50, 125.1, 57);
out.box = { go: b.go, x: b.x, y: b.y };

// a picture's corner: scaled about its middle
const sc = { mode: "scale", node: 4, cx: 0, cy: 0, d0: 10, f: 1, sx: 0, sy: 0, x0: 10, y0: 0 };
out.scaleJiggle = dragTo(sc, 3, 3, 16.3, 6.3) === sc;
out.scale = dragTo(sc, 6, 0, 20, 0).f;
console.log(JSON.stringify(out));
"""


def _src():
    with open(os.path.join(_TABS, "text_scenes.js"), encoding="utf-8") as f:
        return f.read()


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_a_jiggle_is_a_click_and_a_drag_follows_from_the_press(tmp_path):
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
    got = json.loads(run.stdout)
    assert got["slop"] == 5
    # the jiggle (up to 3.6 screen px from the press) never started the drag
    assert got["jiggle"] == {"same": True, "go": False, "dx": 0, "dy": 0}
    # 10 screen px right: the whole 10 px, not the 5 past the slop - what was grabbed
    # stays under the pointer
    assert got["drag"]["go"] is True
    assert got["drag"]["dx"] == pytest.approx(21.1) and got["drag"]["dy"] == 0
    assert got["back"]["go"] is True and got["back"]["dx"] == pytest.approx(2.11)
    # the box's corner moves as the pointer does, from the corner itself: the press was
    # near it, and the corner did not jump to the pointer
    assert got["boxJiggle"] is True
    assert got["box"]["go"] is True
    assert got["box"]["x"] == pytest.approx(131.1) and got["box"]["y"] == 60
    assert got["scaleJiggle"] is True
    assert got["scale"] == 2


def test_the_preview_uses_it_and_a_click_sends_no_edit():
    src = _src()
    body = src[src.index("function TreeCanvas("):]
    body = body[:body.index("\n}\n")]
    # every press keeps where it went down, on the screen and on the glass
    assert body.count("...at }") == 3 and "sx: e.clientX, sy: e.clientY, x0: x, y0: y" in body
    assert "dragTo(q, e.clientX, e.clientY, x, y)" in body
    # the release of a press that never became a drag sends nothing
    up = body[body.index("const up = () =>"):body.index("const key = (e) =>")]
    assert up.index("if (!d || !d.go) return;") < up.index("send(")
