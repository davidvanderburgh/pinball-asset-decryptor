"""Scenes window: text LAYOUT edits (move / alignment / font size).

Where a line of scene text sits, how it is aligned and how big it is drawn
are scene properties, like its colour — so they are edited on the text row of
the Scenes window, recorded in ``text/layout.tsv`` next to ``colors.tsv``,
previewed live, listed on the Write tab as pending changes, and put back with
"Back to the original layout".  These tests drive the same methods the
right-click menu calls.
"""

import json
import os

import pytest

from tests.test_gui_smoke import app  # noqa: F401  (fixture)

CARD = "/g/scene1/scene.radium"
TEXT = "CLOCK NOT SET"


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


def _open(app, tmp_path):
    from tests.test_stern_fontrender import _make_extract
    _make_extract(tmp_path)
    _seed_scene(tmp_path)
    w = app.window
    w.write_assets_var.set(str(tmp_path))
    w._open_scene_browser()
    sb = w._scene_browser
    sb._tree.selection_set("/g/scene1")
    sb._on_select()
    return w, sb


def _text_row(sb):
    for sect in sb._detail.get_children():
        for row in sb._detail.get_children(sect):
            if row.startswith("txt::"):
                return sb._detail.item(row, "values")[0]
    return ""


def test_scene_browser_moves_aligns_and_resizes_a_line(app, tmp_path):
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from pinball_decryptor.plugins.stern import text_layout

    w, sb = _open(app, tmp_path)
    manifest = text_layout.manifest_path(str(tmp_path))
    assert "right-click to recolour" in _text_row(sb)
    assert not os.path.isfile(manifest)

    # Move…: the dialog previews live WITHOUT writing, Apply records the row
    dlg = sb._move_text(TEXT)
    assert dlg is not None and sb._layout_dialog is dlg
    dlg.vars["dx"].set("10")
    dlg.vars["dy"].set("-4")
    assert sb._pending_layouts(CARD)[TEXT]["dx"] == 10.0
    assert sb._pending_layouts(CARD)[TEXT]["dy"] == -4.0
    assert not os.path.isfile(manifest)
    dlg.apply()
    assert sb._layout_dialog is None and sb._live_layout is None
    row = text_layout.load(str(tmp_path))[CARD][TEXT]
    assert (row["dx"], row["dy"], row["align"], row["size"]) == (
        10.0, -4.0, None, None)
    assert os.path.isfile(manifest)
    # ...and the row says so, as a pending change
    assert text_layout.describe(row) in _text_row(sb)
    assert "moved +10,-4" in _text_row(sb)
    assert "not built yet" in _text_row(sb)
    # the preview is handed the edit
    assert sb._pending_layouts(CARD) == {TEXT: row}

    # Alignment submenu: merges into the same row
    sb._align_text(TEXT, "right")
    row = text_layout.load(str(tmp_path))[CARD][TEXT]
    assert row["align"] == "right" and row["dx"] == 10.0
    assert "right" in _text_row(sb)

    # Font size…: a percent of the scene's baked size, shown as px
    dlg = sb._size_text(TEXT)
    assert dlg.px == 50
    assert "50 px → 50 px" in dlg.px_lbl.cget("text")
    dlg.vars["size"].set("120")
    assert "50 px → 60 px" in dlg.px_lbl.cget("text")
    assert sb._pending_layouts(CARD)[TEXT]["size"] == 120
    dlg.apply()
    row = text_layout.load(str(tmp_path))[CARD][TEXT]
    assert row["size"] == 120 and row["align"] == "right"
    assert "120 %" in _text_row(sb)

    # A colour pick and a layout edit share the row's info
    from pinball_decryptor.plugins.stern import text_colors
    text_colors.set_color(str(tmp_path), CARD, TEXT, (255, 255, 255),
                          (51, 204, 51))
    sb._on_select()
    info = _text_row(sb)
    assert "#ffffff → #33cc33" in info and "120 %" in info
    assert info.count("not built yet") == 1
    text_colors.set_color(str(tmp_path), CARD, TEXT, (255, 255, 255), None)

    # The Write tab lists it as a pending change and fingerprints it
    fp_before = w._current_write_fingerprint()
    from pinball_decryptor.core.registry import all_manufacturers
    stern = next(m for m in all_manufacturers() if m.key == "stern")
    app._on_manufacturer_change(stern)
    app.root.update()
    w.write_assets_var.set(str(tmp_path))
    sid = w._write_preview_scan_id
    n = w._add_pending_preview_rows(str(tmp_path), sid)
    assert n >= 1
    rows = [r for r in w._write_preview_rows if r[2] == "Pending (text layout)"]
    assert rows and TEXT in rows[0][0] and "120 %" in rows[0][0]

    # Back to the original layout: the row and the file go away
    sb._reset_layout(TEXT)
    assert text_layout.load(str(tmp_path)) == {}
    assert not os.path.isfile(manifest)
    assert "right-click to recolour" in _text_row(sb)
    assert w._current_write_fingerprint() != fp_before
    fp_after = w._current_write_fingerprint()
    text_layout.set_layout(str(tmp_path), CARD, TEXT, dx=3)
    assert w._current_write_fingerprint() != fp_after
    text_layout.reset(str(tmp_path), CARD, TEXT)

    sb._close()
    app.root.update()


def test_scene_browser_layout_dialog_cancel_and_close(app, tmp_path):
    """Cancel puts the preview back and writes nothing; closing the Scenes
    window with a dialog open takes the dialog with it."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from pinball_decryptor.plugins.stern import text_layout

    _w, sb = _open(app, tmp_path)
    dlg = sb._move_text(TEXT)
    dlg.vars["dx"].set("25")
    assert sb._live_layout is not None
    dlg.cancel()
    assert sb._layout_dialog is None and sb._live_layout is None
    assert sb._pending_layouts(CARD) == {}
    assert not os.path.isfile(text_layout.manifest_path(str(tmp_path)))

    # a second dialog replaces the first
    d1 = sb._move_text(TEXT)
    d2 = sb._size_text(TEXT)
    assert sb._layout_dialog is d2 and d1._done
    # a neutral Apply (100 %) stores no row
    d2.apply()
    assert text_layout.load(str(tmp_path)) == {}

    d3 = sb._move_text(TEXT)
    sb._close()
    assert d3._done
    app.root.update()


def test_scene_browser_layout_needs_a_recorded_layout(app, tmp_path,
                                                      monkeypatch):
    """A line the recorded layout does not draw can't be laid out — the same
    gate the colour pick has, with the same advice."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from pinball_decryptor.gui import scene_browser as sb_mod
    from pinball_decryptor.plugins.stern import text_layout

    _w, sb = _open(app, tmp_path)
    shown = []
    monkeypatch.setattr(sb_mod.messagebox, "showinfo",
                        lambda *a, **k: shown.append(a))
    assert sb._move_text("NOT IN THIS SCENE") is None
    assert sb._align_text("NOT IN THIS SCENE", "left") is None
    assert len(shown) == 2 and "Rebuild previews" in shown[0][1]
    assert text_layout.load(str(tmp_path)) == {}
    sb._close()
    app.root.update()
