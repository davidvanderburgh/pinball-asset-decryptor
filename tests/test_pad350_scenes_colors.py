"""PAD-350 (DragonRR): the Scenes tab's Color profiles bar.  It is the Color profile tab's
controls (ns "color") in a rainbow pop-out on the page's right edge: it reads the profiles
again as it opens, a move made in it is staged like one made on the tab and the Scenes
editor draws its scene again, Paste carries one profile's numbers to another, and its
module loads with every name it imports."""

import json
import os
import re
import shutil
import subprocess

import pytest

from pinball_decryptor.core import colour_profile as cp

_TABS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                     "webui", "static", "js", "tabs")


def test_opening_colors_reads_the_profiles_again(tmp_path):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "output", str(proj))
        w.call("ui.select_tab", "scenes")
        w.drain()
        # staged behind the view's back (another window, a Load on the tab)
        cp.store(str(proj), cp.Profile(name="Godzilla", gamma=(1.2, 1.1, 0.9)))
        rev = w.state("color").get("rev", 0)
        assert w.call("color.panel_open") is True
        w.drain()
        s = w.state("color")
        assert s["name"] == "Godzilla" and s["gamma"] == [1.2, 1.1, 0.9]
        assert s["rev"] > rev            # the view's sliders take the numbers


def test_a_move_in_colors_redraws_the_scene(tmp_path, monkeypatch):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "output", str(proj))
        w.call("ui.select_tab", "scenes")
        w.drain()
        w.call("color.panel_open")
        w.drain()
        text = w.window.service("text")
        seen = []
        monkeypatch.setattr(text, "scenes_pictures_changed", lambda: seen.append(1))
        for mode in ("display", "assets", "screen"):
            assert w.call("color.set_mode", mode) == mode
            w.call("color.set_params", {"gamma": [1.0, 1.0, 0.7]})
            w.drain()
        assert len(seen) == 3
        assert cp.for_project(str(proj)).gamma == (1.0, 1.0, 0.7)
        assert cp.asset_profile(str(proj)).gamma == (1.0, 1.0, 0.7)
        assert cp.screen_profile(str(proj)).gamma == (1.0, 1.0, 0.7)


def test_paste_carries_a_profile_to_another_and_keeps_its_name(tmp_path):
    """The bar's Paste sends every number Copy kept (ranges and curves too) to the profile
    on show, without a name: the one pasted into keeps its own."""
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "output", str(proj))
        w.call("ui.select_tab", "scenes")
        w.drain()
        w.call("color.panel_open")             # as the bar does when it opens
        w.drain()
        assert w.call("color.set_mode", "screen") == "screen"
        w.call("color.set_params", {"name": "Garage Godzilla"})
        w.drain()
        copied = {"gamma": [0.8, 0.9, 1.3], "gain": [1.0, 0.95, 1.05], "lift": 0.02,
                  "saturation": 1.1, "brightness": 1.0, "contrast": 1.05,
                  "ranges": [[205, 50, 30, 15, 0.8, 0.85, 0.15]],
                  "curves": {"rgb": [[0, 0], [64, 48], [255, 255]]}}
        w.call("color.set_params", copied)
        w.drain()
        scr = cp.screen_profile(str(proj))
        assert scr.name == "Garage Godzilla"
        assert scr.gamma == (0.8, 0.9, 1.3) and scr.contrast == 1.05
        assert len(scr.ranges) == 1 and scr.curves


_LOAD = r"""
const bar = await import("./tabs/color_pane.js");
const scenes = await import("./tabs/scenes.js");
console.log(JSON.stringify({ bar: Object.keys(bar).sort(), scenes: Object.keys(scenes).sort() }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_the_bar_loads_on_the_scenes_page(tmp_path):
    """Every name color_pane.js takes from color.js is exported there, and scenes.js loads
    with the bar (ui.js / store.js / text_scenes.js stubbed); Layers / Contents and the
    scene list are left as they were."""
    (tmp_path / "tabs").mkdir()
    (tmp_path / "core").mkdir()
    stubs = {}
    for name in ("color.js", "color_pane.js", "scenes.js"):
        src = open(os.path.join(_TABS, name), encoding="utf-8").read()
        (tmp_path / "tabs" / name).write_text(src, encoding="utf-8")
        for m in re.finditer(r"import \{([^}]*)\} from \"\.\./core/(\w+)\.js\"", src):
            stubs.setdefault(m.group(2), set()).update(
                n.strip() for n in m.group(1).split(",") if n.strip())
    for mod, names in stubs.items():
        (tmp_path / "core" / (mod + ".js")).write_text(
            "".join("export const %s = () => null;\n" % n for n in sorted(names)),
            encoding="utf-8")
    (tmp_path / "tabs" / "text_scenes.js").write_text(
        "export const ScenesPage = () => null;" + chr(10)
        + "export const ScenesActions = () => null;" + chr(10), encoding="utf-8")
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "load.js").write_text(_LOAD, encoding="utf-8")
    run = subprocess.run([shutil.which("node"), str(tmp_path / "load.js")],
                         capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    assert got["bar"] == ["ColorBar", "barOpenAtStart", "rememberBarOpen"]
    assert "default" in got["scenes"]
    src = open(os.path.join(_TABS, "text_scenes.js"), encoding="utf-8").read()
    assert "color_pane" not in src and 'value: "colors"' not in src
    assert "onOpen=${openColors}" in src
