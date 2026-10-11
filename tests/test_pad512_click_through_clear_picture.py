"""PAD-512 (DragonRR): "I can't change the colour of the items I am pointing to" - a mode
screen's title, info line and timer.  The screen's top layer is a full-screen picture of the
score panel, clear everywhere but the panel, and the Scenes preview picked by outline, so
every click on the screen picked that picture and his colours went on it.  Now the server
sends a grid of where each picture shows (``tree_see``) and the click test goes through a
picture where it is clear, to what is drawn under it."""

import base64
import json
import os
import re
import shutil
import subprocess

import pytest

pytest.importorskip("numpy")
pytest.importorskip("PIL")

_JS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                   "webui", "static", "js")


def _hud(w=1360, h=768, band=150):
    """A picture like the one on Godzilla's mode screens: clear, but for a band at the
    bottom (the score panel) and a pip at the top middle."""
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([0, h - band, w - 1, h - 1], fill=(120, 120, 120, 255))
    d.rectangle([w // 2 - 100, 0, w // 2 + 100, 60], fill=(200, 200, 200, 255))
    return im


def _shows(grid, col, row):
    bits = base64.b64decode(grid["b"])
    i = row * grid["c"] + col
    return bool((bits[i >> 3] >> (7 - (i & 7))) & 1)


def test_a_pictures_grid_says_where_it_shows():
    from PIL import Image
    from pinball_decryptor.plugins.stern import scene_render as sr
    g = sr.see_through(_hud())
    # 1360 px over at most 64 cells: 22 px cells, 62 across and 35 down
    assert (g["w"], g["h"], g["s"], g["c"]) == (1360, 768, 22, 62)
    assert len(base64.b64decode(g["b"])) == (62 * 35 + 7) // 8
    # the middle of the screen (where the title is) is clear; the panel and the pip show
    assert not _shows(g, 31, 6) and not _shows(g, 5, 20)
    assert _shows(g, 31, 0) and _shows(g, 0, 34) and _shows(g, 61, 30)
    # a cell with any pixel showing shows (the panel's top edge at 618 is in row 28)
    assert _shows(g, 10, 618 // 22) and not _shows(g, 10, 617 // 22 - 1)
    # solid all over, or no picture: nothing to go through
    assert sr.see_through(Image.new("RGBA", (300, 200), (10, 20, 30, 255))) is None
    assert sr.see_through(Image.new("RGB", (300, 200), (0, 0, 0))) is None
    assert sr.see_through(None) is None
    # a premultiplied pixel with no alpha but some colour adds light: it shows
    glow = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    glow.putpixel((40, 40), (90, 60, 0, 0))
    g = sr.see_through(glow)
    assert g["s"] == 1 and _shows(g, 40, 40) and not _shows(g, 39, 40)
    # faint dust (at most SEE_LEVEL) does not
    dust = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    dust.putpixel((3, 3), (sr.SEE_LEVEL,) * 4)
    assert not _shows(sr.see_through(dust), 3, 3)


_RUN = r"""
import { readFileSync } from "fs";
const { clearAt } = await import("./tabs/text_scenes.js");
globalThis.atob = globalThis.atob || ((b) => Buffer.from(b, "base64").toString("binary"));
const { grid, solid } = JSON.parse(readFileSync("./grid.json", "utf8"));
const see = { "scene_textures/hud.png": grid };
const flat = { img: "scene_textures/hud.png", pts: [[0, 0], [1360, 0], [1360, 768], [0, 768]] };
// the same picture at half size, turned 90 degrees clockwise, its corner at (800, 100):
// the picture's x runs down the glass and its y runs right to left
const turned = { img: "scene_textures/hud.png",
  pts: [[800, 100], [800, 780], [416, 780], [416, 100]] };
const out = {
  title: clearAt(flat, see, 682, 128), panel: clearAt(flat, see, 682, 700),
  pip: clearAt(flat, see, 680, 20), edge: clearAt(flat, see, 1359.9, 767.9),
  turnedClear: clearAt(turned, see, 600, 440),
  // the panel (picture y near the bottom) is at the left of the turned picture
  turnedPanel: clearAt(turned, see, 430, 440),
  noGrid: clearAt({ img: "scene_textures/other.png", pts: flat.pts }, see, 682, 128),
  text: clearAt({ img: null, pts: flat.pts }, see, 682, 128),
  noSee: clearAt(flat, undefined, 682, 128),
  flatLine: clearAt({ img: "scene_textures/hud.png", pts: [[0, 0], [10, 0], [10, 0], [0, 0]] }, see, 5, 0),
  solidGrid: solid,
};
console.log(JSON.stringify(out));
"""

_UI_HOOKS = {"useRef": "(v) => ({ current: v })", "useEffect": "() => {}"}


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_the_click_goes_through_a_picture_where_it_is_clear(tmp_path):
    from pinball_decryptor.plugins.stern import scene_render as sr
    (tmp_path / "tabs").mkdir()
    (tmp_path / "core").mkdir()
    with open(os.path.join(_JS, "tabs", "text_scenes.js"), encoding="utf-8") as f:
        src = f.read()
    (tmp_path / "tabs" / "text_scenes.js").write_text(src, encoding="utf-8")
    stubs = {}
    for m in re.finditer(r"import \{([^}]*)\} from \"\.\./core/(\w+)\.js\"", src):
        stubs.setdefault(m.group(2), set()).update(
            n.strip() for n in m.group(1).split(",") if n.strip())
    for mod, names in stubs.items():
        (tmp_path / "core" / (mod + ".js")).write_text(
            "".join("export const %s = %s;\n" % (n, _UI_HOOKS.get(n, "() => null"))
                    for n in sorted(names)), encoding="utf-8")
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "grid.json").write_text(json.dumps(
        {"grid": sr.see_through(_hud()), "solid": None}), encoding="utf-8")
    (tmp_path / "run.js").write_text(_RUN, encoding="utf-8")
    run = subprocess.run([shutil.which("node"), str(tmp_path / "run.js")],
                         capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    # DragonRR's click on the title goes through; the panel and the pip still pick it
    assert got["title"] is True
    assert got["panel"] is False and got["pip"] is False and got["edge"] is False
    # scaled and turned, the grid turns with it
    assert got["turnedClear"] is True and got["turnedPanel"] is False
    # no grid (a solid picture, a line of text, an older server): the outline is the truth
    assert got["noGrid"] is False and got["text"] is False and got["noSee"] is False
    assert got["flatLine"] is False


def test_the_pick_skips_a_clear_picture_and_hover_does_too():
    with open(os.path.join(_JS, "tabs", "text_scenes.js"), encoding="utf-8") as f:
        src = f.read()
    body = src[src.index("function TreeCanvas("):]
    pick = body[body.index("const pick = (x, y) => {"):]
    pick = pick[:pick.index("\n  };\n")]
    assert "inPoly(hits[i].pts, x, y) && !clearAt(hits[i], s.tree_see, x, y)" in pick
    # the hover outline and a press both go through pick
    assert "const h = pick(x, y);" in body and "setHover(h ? h.id : null)" in body


def test_the_server_sends_where_each_picture_can_be_clicked_through(tmp_path):
    from PIL import Image
    from tests.test_gui_scene_editor import _open, _seed, _tv, _wait
    from tests.webui_harness import web_app
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        hits = _tv(w)["hits"]
        art = next(h for h in hits if h["name"] == "Art")
        title = next(h for h in hits if h["name"] == "Title")
        assert art["img"] and art["img"].endswith(".png")
        assert title["img"] is None
        # every picture of the seeded scene is solid: nothing to go through
        assert _wait(w, lambda: w.state("text_scenes").get("tree_see") == {})
    # Art's picture clear on its left half
    pic = folder / "images" / art["img"]
    w0, h0 = Image.open(str(pic)).size
    im = Image.new("RGBA", (w0, h0), (0, 0, 0, 0))
    for x in range(w0 // 2, w0):
        for y in range(h0):
            im.putpixel((x, y), (200, 40, 40, 255))
    im.save(str(pic))
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert _wait(w, lambda: art["img"] in (w.state("text_scenes").get("tree_see") or {}))
        see = w.state("text_scenes")["tree_see"]
        assert list(see) == [art["img"]]
        g = see[art["img"]]
        assert (g["w"], g["h"], g["s"]) == (w0, h0, 1)
        assert not _shows(g, 0, 0) and not _shows(g, w0 // 2 - 1, h0 - 1)
        assert _shows(g, w0 // 2, 0) and _shows(g, w0 - 1, h0 - 1)
