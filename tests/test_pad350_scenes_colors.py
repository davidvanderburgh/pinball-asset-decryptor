"""PAD-350 (DragonRR): the Scenes inspector's Colors view.  It is the Color profile tab's
controls (ns "color") beside the scene, next to Layers and Contents: it reads the profiles
again as it opens, a move made in it is staged like one made on the tab and the Scenes
editor draws its scene again, and its module loads with every name it imports."""

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


_LOAD = r"""
const pane = await import("./tabs/color_pane.js");
console.log(JSON.stringify(Object.keys(pane).sort()));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_the_colors_view_loads_and_sits_in_the_inspector(tmp_path):
    """Every name color_pane.js takes from color.js is exported there (ui.js / store.js
    stubbed), and the Scenes inspector offers it beside Layers and Contents."""
    (tmp_path / "tabs").mkdir()
    (tmp_path / "core").mkdir()
    stubs = {}
    for name in ("color.js", "color_pane.js"):
        src = open(os.path.join(_TABS, name), encoding="utf-8").read()
        (tmp_path / "tabs" / name).write_text(src, encoding="utf-8")
        for m in re.finditer(r"import \{([^}]*)\} from \"\.\./core/(\w+)\.js\"", src):
            stubs.setdefault(m.group(2), set()).update(
                n.strip() for n in m.group(1).split(",") if n.strip())
    for mod, names in stubs.items():
        (tmp_path / "core" / (mod + ".js")).write_text(
            "".join("export const %s = () => null;\n" % n for n in sorted(names)),
            encoding="utf-8")
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "load.js").write_text(_LOAD, encoding="utf-8")
    run = subprocess.run([shutil.which("node"), str(tmp_path / "load.js")],
                         capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == ["ColorPane"]
    src = open(os.path.join(_TABS, "text_scenes.js"), encoding="utf-8").read()
    assert 'import { ColorPane } from "./color_pane.js";' in src
    assert 'value: "colors"' in src and "<${ColorPane} />" in src
