"""The Colors bar's panels below the profile tools (Simon, 2026-11-19: "We need to stop panels moving that can stay
where they are, keep colours consistent and reduce unneeded text"): a one-line status with the rest in its tooltip,
"Game's own assets ..." in a panel of its own, "X assets selected", and every selected Scenes layer reaching the bar."""
import os

TABS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor", "webui", "static", "js", "tabs")
CSS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor", "webui", "static", "css", "tabs")


def _src(name, where=TABS):
    with open(os.path.join(where, name), encoding="utf-8") as f:
        return f.read()


def test_status_is_one_line_with_the_words_in_its_tooltip():
    color = _src("color.js")
    assert "export function statusWords(" in color and "export function StatusLine(" in color
    assert "...${tip(sw.long)}" in color                      # the long words on hover
    pane = _src("color_pane.js")
    assert "<${StatusLine} s=${s}" in pane and "statusNote(" not in pane
    css = _src("color_pane.css", CSS)
    assert "min-height: 104px" not in css                     # the old tall box that changed size
    assert ".cpd-statusline { height: 34px;" in css


def test_game_own_assets_and_count_panels_are_always_there():
    color = _src("color.js")
    assert "export function gameOwnWords(" in color
    assert "Game's own assets: locked. Unlock them in the Advanced panel" in color
    assert "Now: ${words}" not in color                       # the old "Now: ..." words, the Color profile tab too
    pane = _src("color_pane.js")
    assert "${!f ? html`<${WhichFilesNotes}" not in pane      # was only there with nothing selected: it jumped
    assert "<${WhichFilesNotes} s=${s} />" in pane
    assert "<${SelectedCount} picked=${picked} file=${s.file} />" in pane
    for tab in ("scenes.js", "images.js", "video.js"):
        assert "picked=${" in _src(tab), tab


def test_every_selected_scenes_layer_reaches_the_bar():
    scenes = _src("scenes.js")
    assert "t.sels" in scenes and "more: [...new Set(" in scenes
