"""PAD-364 (DragonRR): the Color profiles bar (the rainbow tab, PAD-350) on the Images and
Video tabs too, so a profile is picked from the Saved profiles list and tuned with each
file's own color switch in view.  It is the one set of profiles wherever it is opened: a
change made on the Images or Video tab is the change Scenes and the Color profile tab
see, and the other way round; the Images and Video tabs follow a move made in it."""

import json
import os
import re
import shutil
import subprocess

import pytest

from pinball_decryptor.core import colour_profile as cp

_TABS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                     "webui", "static", "js", "tabs")


def _src(name):
    return open(os.path.join(_TABS, name), encoding="utf-8").read()


def test_opening_the_bar_from_the_video_tab_reads_the_profiles_again(tmp_path):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "output", str(proj))
        w.call("ui.select_tab", "video")
        w.drain()
        # staged behind the view's back (Scenes' bar in another window, a Load on the tab)
        cp.store_asset_profile(str(proj), cp.Profile(name="Godzilla", gamma=(1.2, 1.1, 0.9)))
        rev = w.state("color").get("rev", 0)
        assert w.call("color.set_mode", "assets") == "assets"
        assert w.call("color.panel_open") is True
        w.drain()
        s = w.state("color")
        assert s["name"] == "Godzilla" and s["gamma"] == [1.2, 1.1, 0.9]
        assert s["rev"] > rev            # the bar's sliders take the numbers
        assert s["has_project"] is True  # what offers the bar on Images and Video


def test_a_move_in_the_bar_reaches_the_images_and_video_tabs(tmp_path, monkeypatch):
    """A profile tuned beside the Images list is the one the Video tab's players and the
    Scenes editor draw through, and the other way round: one store, every tab told."""
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "output", str(proj))
        w.call("ui.select_tab", "images")
        w.drain()
        w.call("color.panel_open")
        w.drain()
        seen = []
        for ns, name in (("images", "color_all_changed"), ("video", "publish_look"),
                         ("text", "scenes_pictures_changed")):
            monkeypatch.setattr(w.window.service(ns), name,
                                lambda ns=ns: seen.append(ns))
        assert w.call("color.set_mode", "assets") == "assets"
        w.call("color.set_params", {"name": "From Images", "gamma": [1.0, 1.0, 0.7]})
        w.drain()
        assert set(seen) == {"images", "text", "video"}   # video twice: switches + look
        got = cp.asset_profile(str(proj))
        assert got.name == "From Images" and got.gamma == (1.0, 1.0, 0.7)
        # the Scenes bar and the Color profile tab show the same profile
        w.call("ui.select_tab", "color")
        w.drain()
        assert w.state("color")["name"] == "From Images"


def test_the_help_names_every_tab_with_the_bar():
    from pinball_decryptor.webui import help_content
    text = open(help_content.__file__, encoding="utf-8").read()
    assert "Color profiles bar (Scenes, Images, Video)" in text
    assert "Color profiles bar (Scenes)\"" not in text


_LOAD = r"""
const bar = await import("./tabs/color_pane.js");
const images = await import("./tabs/images.js");
const video = await import("./tabs/video.js");
console.log(JSON.stringify({ bar: Object.keys(bar).sort(), images: Object.keys(images).sort(),
  video: Object.keys(video).sort() }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_the_bar_loads_on_the_images_and_video_pages(tmp_path):
    """images.js and video.js load with the bar (ui.js / store.js / look.js stubbed), each
    mounting it in the Scenes tab's shell with its own host and the Files profile first."""
    (tmp_path / "tabs").mkdir()
    (tmp_path / "core").mkdir()
    stubs = {}
    for name in ("color.js", "color_pane.js", "images.js", "video.js"):
        src = _src(name)
        (tmp_path / "tabs" / name).write_text(src, encoding="utf-8")
        for m in re.finditer(r"import \{([^}]*)\}\s*from \"\.\./core/(\w+)\.js\"", src):
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
    got = json.loads(run.stdout)
    assert got["bar"] == ["ColorBar", "barOpenAtStart", "rememberBarOpen"]
    assert "default" in got["images"] and "default" in got["video"]
    for name, host in (("images.js", "images"), ("video.js", "video")):
        src = _src(name)
        assert 'class="cpd-shell"' in src
        assert 'host="%s" startMode="assets"' % host in src
        assert 'barOpenAtStart("%s")' % host in src and 'rememberBarOpen(v, "%s")' % host in src
    # a name under the Video tab's Preview colors opens the bar on that profile
    assert "onOpen=${colorNs.has_project ? openColors : undefined}" in _src("video.js")
    # Scenes keeps the key it had, so a bar left open before PAD-364 still opens
    bar = _src("color_pane.js")
    assert 'host !== "scenes" ? OPEN_KEY + "." + host : OPEN_KEY' in bar
    assert 'host="scenes"' in _src("scenes.js")
