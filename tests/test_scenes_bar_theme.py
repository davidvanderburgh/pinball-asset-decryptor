"""The Scenes Colors bar works on the theme Scenes shows (Simon, 2026-11-19: with "Show theme 2" picked the bar still
changed theme 1 and its Copy went to the Images tab's theme - he copied into theme 1 while looking at theme 2)."""
import os
import types

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.plugins.stern import scene_variants as SV
from pinball_decryptor.webui.tabs import color

from tests.test_theme_colour import TREL

TABS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor", "webui", "static", "js", "tabs")


def _src(name):
    with open(os.path.join(TABS, name), encoding="utf-8") as f:
        return f.read()


def test_scenes_sends_the_theme_shown():
    scenes = _src("scenes.js")
    assert "s.preview_theme || 1" in scenes
    assert "const key = (r) => `@${shownTheme}:${r}`;" in scenes
    assert 'attach: { ns: "images" }' in scenes                 # the theme's switch, through the Images tab
    pane = _src("color_pane.js")
    # the THEME box and "This theme" are the theme on show; the copy is sent that theme, not the Images tab's
    assert 'host === "scenes" ? (scn.preview_theme || 1) : (sets.current || 1)' in pane
    assert 'const themes = !themesOk ? "this" : where === "this" ? [t] : picks;' in pane


def test_the_bar_reads_the_themes_own_switch(tmp_path):
    """Scenes' layers carry theme 1's switch: set_file reads the theme's."""
    p = str(tmp_path)
    SV.set_themes_on(p, True)
    SV.add_set(p, "Dark")
    cp.set_asset_slot(p, "images", TREL, True)                 # on in theme 1
    cp.set_asset_slot(p, "images", SV.theme_key(2, TREL), False)
    bar = types.SimpleNamespace(_project=p, _on_display=True, _file=None, _mode="assets", _rev=0)
    bar._publish = lambda **kw: None
    assert color.ColorTab.set_file(bar, "images", SV.theme_key(2, TREL), "x", True, {"ns": "images"}, [])
    assert bar._file["on"] is False


def test_this_theme_is_the_files_theme():
    bar = types.SimpleNamespace(_theme_now=lambda: 2)
    names = ["Standard", "Dark"]
    said = color.ColorTab._themes_said
    assert said(bar, "images", "this", names, TREL) == " in theme 1 (Standard)"    # plain = theme 1, on show in Scenes
    assert said(bar, "images", "this", names, SV.theme_key(2, TREL)) == " in theme 2 (Dark)"
    assert said(bar, "images", "this", names, None) == " in theme 2 (Dark)"        # no file: the theme on show
