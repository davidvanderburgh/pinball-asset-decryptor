"""PAD-515 (DragonRR): "Painted by the game as it plays" was extremely easy to forget.

- A box's outline on the Scenes preview shows only under the mouse and on the selection, the
  teal one of a box the game fills in (PAD-485) too, which used to be drawn all the time.
- Selected, a box the game fills in or paints is outlined in its own color, not the usual
  amber with the teal left under it.
- A line the game paints (Godzilla's score panel, PAD-507) has its own outline color, violet,
  and its own mark in Layers.
- The Selected panel keeps its shape: the game-fills and game-paints bars, Words, the picture
  row, Keep its shape and Font controls are always there, greyed out when they do not apply."""

import json
import os
import re
import shutil
import subprocess
import time

import pytest

from tests.test_gui_scene_editor import _seed, _tv
from tests.webui_harness import web_app

pytest.importorskip("PIL")

_JS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                   "webui", "static", "js")
_CSS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                    "webui", "static", "css", "tabs", "text_scenes.css")


def _wait(w, pred, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        w.drain()
        if pred():
            return True
        time.sleep(0.03)
    raise AssertionError("timed out waiting")


def _panel_scene():
    """The synthetic scene's Art and KAIJU title, plus a player's score box the way Godzilla's
    score panel has it: a Text named score inside P1_ActiveScore_Instance."""
    from tests.test_stern_scene_tree import (FLAG, bitmap, cls, fs, mat, node, sprite, text,
                                             texture, u32, u64, u8)
    score = node(61, "score", [u32(1) + cls(3) + u32(FLAG | 31) + text(12, "22,000", (9, 7))],
                 tracks=((1, mat(1, 100, 500)),))
    root_kids = [
        node(50, "Art", [u32(1) + cls(1, "Bitmap") + u32(FLAG | 12) + bitmap(3, 16, 8, texture(21, 16, 8))]),
        node(53, "Title", [u32(1) + cls(3, "Text") + u32(FLAG | 13) + text(5, "KAIJU", (9, 7))]),
        node(60, "P1_ActiveScore_Instance",
             [u32(1) + cls(2, "Sprite") + u32(FLAG | 30) + sprite(11, "", 2, [score])],
             tracks=((1, mat(1, 0, 0)),)),
    ]
    root = sprite(2, "", 20, root_kids, labels=[("Start", 1), ("End", 20)])
    return (u8(1) + u64(0) + u64(0) + u32(1360) + u32(768) + fs(30.0) + fs(0.2, 0.2, 0.2, 1.0) + root)


def test_a_line_the_game_paints_is_marked_on_its_outline_and_in_layers(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder, _panel_scene())
    with web_app(tmp_path, mfr="stern") as w:
        w.run(lambda: w.window.write_assets_var.set(str(folder)))
        text = w.window.service("text")
        assert w.run(text.open_scene_browser, str(folder)) is True
        w.call("text_scenes.select", "/g/scene1")
        _wait(w, lambda: (w.state("text_scenes").get("frames") or []) != [])
        tv = _tv(w)
        hits = {h["name"]: h for h in tv["hits"]}
        assert hits["score"]["painted"] is True
        assert hits["Title"]["painted"] is False and hits["Art"]["painted"] is False
        layers = {l["name"]: l for l in tv["layers"]}
        assert layers["score"]["painted"] is True
        assert layers["Title"]["painted"] is False and layers["P1_ActiveScore_Instance"]["painted"] is False
        # selected, the score lights the panel's game-paints bar; the title leaves it greyed
        w.call("text_scenes.tree_select", 61)
        _wait(w, lambda: (_tv(w).get("props") or {}).get("id") == 61)
        g = _tv(w)["props"]["game_colors"]
        assert g and g["group"] == "up" and [r["role"] for r in g["roles"]] == [
            "up", "others", "start", "coins"]
        w.call("text_scenes.tree_select", 53)
        _wait(w, lambda: (_tv(w).get("props") or {}).get("id") == 53)
        props = _tv(w)["props"]
        assert props["game_colors"] is None and props["filled"] is None
        w.call("text_scenes.close")


_RUN = r"""
const { outlineKind } = await import("./tabs/text_scenes.js");
const out = {
  filledHit: outlineKind({ filled: true, painted: false }),
  paintedHit: outlineKind({ filled: false, painted: true }),
  plainHit: outlineKind({ filled: false, painted: false }),
  filledLayer: outlineKind({ filled: { line: "HIGH SCORE:", modes: [] }, painted: false }),
  paintedProps: outlineKind({ filled: null, game_colors: { group: "up", roles: [] } }),
  plainProps: outlineKind({ filled: null, game_colors: null }),
  none: outlineKind(null),
};
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_each_kind_of_box_has_its_own_outline(tmp_path):
    (tmp_path / "tabs").mkdir()
    (tmp_path / "core").mkdir()
    with open(os.path.join(_JS, "tabs", "text_scenes.js"), encoding="utf-8") as f:
        src = f.read()
    (tmp_path / "tabs" / "text_scenes.js").write_text(src, encoding="utf-8")
    stubs = {}
    for m in re.finditer(r"import \{([^}]*)\} from \"\.\./core/(\w+)\.js\"", src):
        stubs.setdefault(m.group(2), set()).update(
            n.strip() for n in m.group(1).split(",") if n.strip())
    hooks = {"useRef": "(v) => ({ current: v })", "useEffect": "() => {}"}
    for mod, names in stubs.items():
        (tmp_path / "core" / (mod + ".js")).write_text(
            "".join("export const %s = %s;\n" % (n, hooks.get(n, "() => null"))
                    for n in sorted(names)), encoding="utf-8")
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "run.js").write_text(_RUN, encoding="utf-8")
    run = subprocess.run([shutil.which("node"), str(tmp_path / "run.js")],
                         capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == {
        "filledHit": "filled", "paintedHit": "painted", "plainHit": "",
        "filledLayer": "filled", "paintedProps": "painted", "plainProps": "", "none": ""}


def _src():
    with open(os.path.join(_JS, "tabs", "text_scenes.js"), encoding="utf-8") as f:
        return f.read()


def test_outlines_show_only_under_the_mouse_and_selected_in_their_own_color():
    src = _src()
    body = src[src.index("function TreeCanvas("):]
    body = body[:body.index("\n}\n")]
    svg = body[body.index('class="tree-svg"'):]
    # the only outlines drawn: the one under the mouse and the selection's
    assert re.findall(r'poly\(h, "(\w)" \+ i, "([\w-]+)"\)', svg) == [
        ("h", "tree-hover"), ("s", "tree-sel")]
    assert "tree-filled" not in src
    # each in its own kind's color, the selected box and its handles too
    assert "class=${cx(cls, outlineKind(h))}" in body
    assert 'class=${cx("tree-box", pk)}' in svg and 'class=${cx("tree-handle", pk)}' in svg
    with open(_CSS, encoding="utf-8") as f:
        css = f.read()
    for kind in ("filled", "painted"):
        for cls in ("tree-hover", "tree-sel", "tree-box", "tree-handle"):
            assert re.search(r"\.%s\.%s\b" % (cls, kind), css), (cls, kind)


def test_the_selected_panel_keeps_every_section_greyed_out_not_gone():
    src = _src()
    side = src[src.index("function TreeSide("):]
    side = side[:side.index("\n}\n")]
    one = side[side.index(": p ? html`<div class=\"tree-props\">"):]
    for part in ("<${GameFills} p=${p} proven=${t.fills_proven !== false} />",
                 "<${GameColors} g=${p.game_colors} />",
                 "<${Words} p=${p} find=${find} searching=${searching} />"):
        assert part in one and ("? " + part) not in one and ("? html`" + part) not in one
    # the picture row, X / Y, W / H and Keep its shape are not left out either
    assert "${p.pic ? html`<div" not in one and "${p.w != null ? html`" not in one
    assert "${isText ? null : html`<label" not in one
    assert 'disabled=${isText || p.w == null}' in one
    assert "disabled=${!p.pic ||" in one
    # Font controls: there for a picture too, greyed out
    assert 'p.kind === "Text" && p.font && openFont ?' not in one
    assert "disabled=${!(isText && p.font)}" in one
    words = src[src.index("function Words("):]
    words = words[:words.index("\n}\n")]
    # PAD-513: a line the game writes itself is locked, greyed out the same way
    assert "disabled=${off}" in words and "const off = !p.words || !!p.words.locked;" in words
    fills = src[src.index("function GameFills("):]
    fills = fills[:fills.index("\n}\n")]
    # PAD-513: the button is greyed out too when the game writes words of its own
    assert 'cx("tree-game fills", !f && "off")' in fills and "disabled=${!filledFinds(f)}" in fills
    assert "const filledFinds = (f) => !!(f && " in src
    paints = src[src.index("function GameColors("):]
    paints = paints[:paints.index("\n}\n")]
    assert 'cx("tree-game paints", !g && "off")' in paints
