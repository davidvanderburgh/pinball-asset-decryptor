"""Scenes window: text LAYOUT edits (move / alignment / font size).

Where a line of scene text sits, how it is aligned and how big it is drawn
are scene properties, like its colour — so they are edited on the text row of
the Scenes window, recorded in ``text/layout.tsv`` next to ``colors.tsv``,
previewed live, listed on the Write tab as pending changes, and put back with
"Back to the original layout".  These tests drive the same calls the
right-click menu makes (webui/text_scenes.py, ``text_scenes.*``).
"""

import json
import os
import time

import pytest

from tests.webui_harness import web_app

CARD = "/g/scene1/scene.radium"
TEXT = "CLOCK NOT SET"


def _wait(w, pred, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _seed_scene(tmp_path, px=50):
    """``_make_extract`` plus one editable string and a layout drawing it at a
    known size, so the Scenes window has a Text row with a font px to show."""
    from pinball_decryptor.plugins.stern import scene_render
    (tmp_path / "text").mkdir(exist_ok=True)
    (tmp_path / "text" / "strings.tsv").write_text(
        "# asset_path\toriginal\treplacement\n"
        "%s\t%s\t\n" % (CARD, TEXT), encoding="utf-8")
    layout = {CARD: {
        "stage": [320, 180, 60.0], "unplaced": 0, "offstage": 0,
        "sprites": [], "texts": [
            {"name": "Line1", "x": 0, "y": 100, "text": TEXT,
             "rect": [0, 0, 320, 180], "rgba": [1.0, 1.0, 1.0, 1.0],
             "align": 1, "font": "tbl", "font_px": px}]}}
    with open(str(tmp_path / scene_render.SCENE_LAYOUT_MANIFEST), "w",
              encoding="utf-8") as f:
        json.dump(layout, f)


def _set_folder(w, folder):
    def _do():
        try:
            w.window.write_assets_var.set(folder)
        except Exception:                            # noqa: BLE001
            pass
    w.run(_do)


def _open(w, tmp_path):
    from tests.test_stern_fontrender import _make_extract
    _make_extract(tmp_path)
    _seed_scene(tmp_path)
    _set_folder(w, str(tmp_path))
    text = w.window.service("text")
    assert w.run(text.open_scene_browser, str(tmp_path)) is True
    sb = text.scenes
    w.call("text_scenes.select", "/g/scene1")
    return text, sb


def _text_row(w):
    contents = w.state("text_scenes")["contents"] or {}
    for group in contents.get("groups") or ():
        for item in group["items"]:
            if (item.get("id") or "").startswith("txt::"):
                return item["info"]
    return ""


def test_scene_browser_moves_aligns_and_resizes_a_line(tmp_path):
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from pinball_decryptor.plugins.stern import text_layout
    from pinball_decryptor.webui import write_scan

    folder = tmp_path / "proj"
    folder.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _text, sb = _open(w, folder)
        manifest = text_layout.manifest_path(str(folder))
        assert "right-click to recolour" in _text_row(w)
        assert not os.path.isfile(manifest)

        # Move…: the dialog previews live WITHOUT writing, Apply records the
        # row
        dlg = w.call("text_scenes.layout_start", TEXT, "move")
        assert dlg is not None
        assert w.state("text_scenes")["layout_dialog"]["kind"] == "move"
        w.call("text_scenes.layout_preview", {"dx": "10", "dy": "-4"})
        assert w.run(sb._pending_layouts, CARD)[TEXT]["dx"] == 10.0
        assert w.run(sb._pending_layouts, CARD)[TEXT]["dy"] == -4.0
        assert not os.path.isfile(manifest)
        assert w.call("text_scenes.layout_done", {"dx": "10", "dy": "-4"})
        assert w.state("text_scenes")["layout_dialog"] is None
        assert sb._live_layout is None
        row = text_layout.load(str(folder))[CARD][TEXT]
        assert (row["dx"], row["dy"], row["align"], row["size"]) == (
            10.0, -4.0, None, None)
        assert os.path.isfile(manifest)
        # ...and the row says so, as a pending change
        assert text_layout.describe(row) in _text_row(w)
        assert "moved +10,-4" in _text_row(w)
        assert "not built yet" in _text_row(w)
        # the preview is handed the edit
        assert w.run(sb._pending_layouts, CARD) == {TEXT: row}

        # Alignment submenu: merges into the same row
        assert w.call("text_scenes.align_text", TEXT, "right") is True
        row = text_layout.load(str(folder))[CARD][TEXT]
        assert row["align"] == "right" and row["dx"] == 10.0
        assert "right" in _text_row(w)

        # Font size…: a percent of the scene's baked size, shown as px
        dlg = w.call("text_scenes.layout_start", TEXT, "size")
        assert dlg["px"] == 50
        assert "50 px → 50 px" in w.call("text_scenes.layout_px", {})
        assert "50 px → 60 px" in w.call("text_scenes.layout_preview",
                                         {"size": "120"})
        assert w.run(sb._pending_layouts, CARD)[TEXT]["size"] == 120
        w.call("text_scenes.layout_done", {"size": "120"})
        row = text_layout.load(str(folder))[CARD][TEXT]
        assert row["size"] == 120 and row["align"] == "right"
        assert "120 %" in _text_row(w)

        # A colour pick and a layout edit share the row's info
        from pinball_decryptor.plugins.stern import text_colors
        text_colors.set_color(str(folder), CARD, TEXT, (255, 255, 255),
                              (51, 204, 51))
        w.run(sb._on_select)
        info = _text_row(w)
        assert "#ffffff → #33cc33" in info and "120 %" in info
        assert info.count("not built yet") == 1
        text_colors.set_color(str(folder), CARD, TEXT, (255, 255, 255), None)

        # The Write tab lists it as a pending change and fingerprints it
        write = w.window.service("write")
        fp_before = w.run(write._fingerprint)
        rows = w.run(lambda: write_scan.pending_rows(
            w.window, w.window.current_mfr, str(folder), grow_on=True,
            direct=False))
        rows = [r for r in rows if r[2] == "Pending (text layout)"]
        assert rows and TEXT in rows[0][0] and "120 %" in rows[0][0]

        # Back to the original layout: the row and the file go away
        assert w.call("text_scenes.reset_layout", TEXT) is True
        assert text_layout.load(str(folder)) == {}
        assert not os.path.isfile(manifest)
        assert "right-click to recolour" in _text_row(w)
        assert w.run(write._fingerprint) != fp_before
        fp_after = w.run(write._fingerprint)
        text_layout.set_layout(str(folder), CARD, TEXT, dx=3)
        assert w.run(write._fingerprint) != fp_after
        text_layout.reset(str(folder), CARD, TEXT)

        w.call("text_scenes.close")


def test_scene_browser_layout_dialog_cancel_and_close(tmp_path):
    """Cancel puts the preview back and writes nothing; closing the Scenes
    window with a dialog open takes the dialog with it."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from pinball_decryptor.plugins.stern import text_layout

    folder = tmp_path / "proj"
    folder.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _text, sb = _open(w, folder)
        w.call("text_scenes.layout_start", TEXT, "move")
        w.call("text_scenes.layout_preview", {"dx": "25"})
        assert sb._live_layout is not None
        w.call("text_scenes.layout_done", None)          # Cancel
        assert w.state("text_scenes")["layout_dialog"] is None
        assert sb._live_layout is None
        assert w.run(sb._pending_layouts, CARD) == {}
        assert not os.path.isfile(text_layout.manifest_path(str(folder)))

        # a second dialog replaces the first
        w.call("text_scenes.layout_start", TEXT, "move")
        w.call("text_scenes.layout_start", TEXT, "size")
        assert w.state("text_scenes")["layout_dialog"]["kind"] == "size"
        # a neutral Apply (100 %) stores no row
        w.call("text_scenes.layout_done", {"size": "100"})
        assert text_layout.load(str(folder)) == {}

        w.call("text_scenes.layout_start", TEXT, "move")
        w.call("text_scenes.layout_preview", {"dx": "7"})
        w.call("text_scenes.close")
        assert w.state("text_scenes")["layout_dialog"] is None
        assert sb._live_layout is None


def test_scene_browser_layout_needs_a_recorded_layout(tmp_path):
    """A line the recorded layout does not draw can't be laid out — the same
    gate the colour pick has, with the same advice."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from pinball_decryptor.plugins.stern import text_layout

    folder = tmp_path / "proj"
    folder.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        n = len(w.asked)
        assert w.call("text_scenes.layout_start", "NOT IN THIS SCENE",
                      "move") is None
        assert w.call("text_scenes.align_text", "NOT IN THIS SCENE",
                      "left") is False
        shown = w.asked[n:]
        assert len(shown) == 2 and "Rebuild previews" in shown[0]["message"]
        assert text_layout.load(str(folder)) == {}
        w.call("text_scenes.close")


def _wait_for_render(w, captured, want):
    """Wait until the worker's render call for *want* text edits has been
    captured (or give up after a few seconds)."""
    return _wait(w, lambda: any(kw.get("text_edits") == want
                                for kw in list(captured)), timeout=8.0)


def _text_open(w, folder):
    w.call("ui.select_tab", "text")
    svc = w.window.service("text")
    assert _wait(w, lambda: not w.state("text")["scanning"]
                 and svc._text_scan_dir == folder)
    return svc


def _rescan_text(w, folder):
    svc = w.window.service("text")
    w.run(w.window.invalidate_asset_scans)
    w.call("ui.select_tab", "text")
    assert _wait(w, lambda: not w.state("text")["scanning"]
                 and svc._text_scan_dir == folder)


def _row_index(svc, original, path_part=""):
    for i, r in enumerate(svc._text_rows):
        if r["original"] == original and path_part in r["path"]:
            return i
    raise AssertionError("no row %r" % original)


def test_text_tab_edit_shows_in_the_scenes_window(tmp_path, monkeypatch):
    """David: "changes here would propagate everywhere and I would be able to
    easily view them to confirm it looks good."  Apply on the Text tab
    re-renders an open Scenes window with the pending replacement: the row
    says what the line now shows (not built yet) and the render job is handed
    the edit; Revert takes it away again."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from pinball_decryptor.core import text_manifest
    from pinball_decryptor.plugins.stern import scene_render

    captured = []
    real = scene_render.render_layout

    def spy(assets_dir, layout, **kw):
        captured.append(dict(kw))
        return real(assets_dir, layout, **kw)

    monkeypatch.setattr(scene_render, "render_layout", spy)

    folder = tmp_path / "proj"
    folder.mkdir()
    folder_s = str(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _text, sb = _open(w, folder)
        assert _wait_for_render(w, captured, {})       # the stock render
        assert "right-click to recolour" in _text_row(w)
        assert "shows:" not in _text_row(w)

        # The Text tab, on the same folder, with the fixture's row selected.
        svc = _text_open(w, folder_s)
        w.call("text.select", _row_index(svc, TEXT))
        new = "TIME NOT SET"                    # fits today's in-place budget
        captured.clear()
        assert w.call("text.apply", new) is True
        assert text_manifest.changed(folder_s) == {CARD: [(TEXT, new)]}
        # ...the Scenes window redrew with the edit and its row says so
        assert _wait_for_render(w, captured, {TEXT: new})
        info = _text_row(w)
        assert 'shows: "%s"' % new in info and "not built yet" in info
        assert w.run(sb._pending_texts, CARD) == {TEXT: new}

        # A longer edit written to the manifest by other means (a future
        # Write path that grows the radium) previews the same way once the
        # window is told: the renderer does not care about the slot.
        longer = "THE CLOCK HAS NOT BEEN SET YET"
        text_manifest.save(folder_s, [
            {"path": CARD, "original": TEXT, "replacement": longer}])
        captured.clear()
        w.run(sb.text_edits_changed)
        assert _wait_for_render(w, captured, {TEXT: longer})
        assert 'shows: "%s"' % longer in _text_row(w)

        # A game-program row whose original this scene draws reaches it too
        text_manifest.save(folder_s, [
            {"path": CARD, "original": TEXT, "replacement": ""},
            {"path": "/g/game", "original": TEXT, "replacement": "CLOCK UNSET",
             "budget": 96}])
        captured.clear()
        w.run(sb.text_edits_changed)
        assert _wait_for_render(w, captured, {TEXT: "CLOCK UNSET"})
        assert 'shows: "CLOCK UNSET"' in _text_row(w)

        # Revert on the Text tab: the row and the render lose the edit
        _rescan_text(w, folder_s)
        w.call("text.select", _row_index(svc, TEXT, "/g/game"))
        captured.clear()
        w.call("text.apply", TEXT)
        assert text_manifest.changed(folder_s) == {}
        assert _wait_for_render(w, captured, {})
        assert "shows:" not in _text_row(w)
        assert "right-click to recolour" in _text_row(w)

        # A Scenes window on a DIFFERENT folder is left alone
        def _elsewhere(path):
            sb.assets_dir = path
        w.run(_elsewhere, str(folder / "elsewhere"))
        captured.clear()
        w.call("text.apply", "CLOCK UNSET")
        time.sleep(0.3)
        w.drain()
        assert captured == []
        w.run(_elsewhere, folder_s)

        # a refused edit would have surfaced as a warning box
        assert not [a for a in w.asked if a.get("icon") == "warning"]
        w.call("text_scenes.close")
