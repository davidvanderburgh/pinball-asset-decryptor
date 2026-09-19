"""PAD-154: "Keep this picture's own size" under the Replace Images preview.

A longer kaiju name squeezed into the stock banner was unreadable; a scene
picture (Source "Radium", not a font atlas) with a replacement assigned now
offers to keep the replacement's own size, spells out both sizes, and the
choice reaches the build through the pending tuple and the sidecar."""
import os

import pytest

from tests.conftest import HAS_DISPLAY
from tests.test_gui_smoke import app  # noqa: F401  (fixture)

Image = pytest.importorskip("PIL.Image")

from pinball_decryptor.core import staged_changes                   # noqa: E402
from pinball_decryptor.core.image_slots import scan_image_slots     # noqa: E402

pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(not HAS_DISPLAY, reason="no Tk display available"),
]

BANNER = "images/scene_textures/radimg_unnamed_instance_24_40x20_45402198.png"
ATLAS = "images/scene_textures/radimg_GameFont_Primary_64x64_3ce3aba2.png"
PLAIN = "images/backglass.png"


def _project(tmp_path):
    assets = tmp_path / "gz"
    tex = assets / "images" / "scene_textures"
    tex.mkdir(parents=True)
    Image.new("RGBA", (40, 20), (0, 0, 0, 255)).save(assets / BANNER)
    Image.new("RGBA", (64, 64), (0, 0, 0, 255)).save(assets / ATLAS)
    Image.new("RGBA", (64, 32), (0, 0, 0, 255)).save(assets / PLAIN)
    (tex / "glyph_images.txt").write_text(
        "# glyph output\tatlas output\tchar\tx\ty\tw\th\tfont\n"
        "scene_textures/glyphs/radimg_GameFont_Primary_64x64_3ce3aba2/"
        "U+0041_A.png\tscene_textures/radimg_GameFont_Primary_64x64_3ce3aba2"
        ".png\t0x0041\t0\t0\t8\t8\tGameFont\n", encoding="utf-8")
    rep = tmp_path / "SpaceGodzilla.png"
    Image.new("RGBA", (90, 22), (255, 255, 255, 255)).save(rep)
    return str(assets), str(rep)


@pytest.fixture
def window(app, manufacturers_by_key, tmp_path):
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    assets, rep = _project(tmp_path)
    w = app.window
    w.write_assets_var.set(assets)
    w._image_scan_dir = assets
    w._image_slots = scan_image_slots(assets)
    w._image_slots_by_rel = {s.rel_path: s for s in w._image_slots}
    yield w, assets, rep
    # The row re-pins the tab height on the NOTEBOOK's idle queue; run it
    # before the app fixture cancels callbacks through the root, which would
    # leave the notebook holding a command Tk has already deleted.
    app.root.update()


def _shown(w):
    return w._image_keep_row.winfo_manager() == "grid"


def test_the_tick_appears_for_a_scene_picture_and_reaches_the_build(window):
    w, assets, rep = window
    w._image_render_preview(BANNER)
    assert not _shown(w)                   # nothing assigned yet
    w._image_assignments[BANNER] = rep
    w._image_current_rel = BANNER
    w._image_render_preview(BANNER)
    assert _shown(w)
    assert w.image_keep_size_var.get() is False
    assert "90×22" in w._image_size_lbl["text"]
    assert "squeezed" in w._image_size_lbl["text"]
    assert w.pending_image_assignments(assets)[2] == frozenset()

    w.image_keep_size_var.set(True)
    w._image_on_keep_size_toggle()
    assert w._image_keep_size == {BANNER}
    assert w._image_size_lbl["text"].startswith("Kept at 90×22")
    assert w.pending_image_assignments(assets)[2] == frozenset({BANNER})
    assert staged_changes.load(assets)["image_keep_size"] == [BANNER]

    w.image_keep_size_var.set(False)
    w._image_on_keep_size_toggle()
    assert w.pending_image_assignments(assets)[2] == frozenset()
    assert staged_changes.load(assets)["image_keep_size"] == []


@pytest.mark.parametrize("rel", [ATLAS, PLAIN])
def test_no_tick_where_the_size_cannot_change(window, rel):
    w, assets, rep = window
    w._image_assignments[rel] = rep
    w._image_current_rel = rel
    w._image_render_preview(rel)
    assert not _shown(w)
    w._image_set_keep_size(rel, True)
    assert w._image_keep_size == set()


def _keep_cells(w):
    return {rel: w._image_tree.set(rel, "keep")
            for rel in (BANNER, ATLAS, PLAIN)}


def test_the_keep_size_column_shows_every_pick(window):
    # PAD-158: the tick under the preview only speaks for the selected row;
    # the list has to say it for every pick ("Perhaps make it a little more
    # obvious are incorporate into the window as another column?").
    w, assets, rep = window
    w._refresh_image_list()
    tree = w._image_tree
    assert "keep" in tree["displaycolumns"]
    assert tuple(tree["displaycolumns"])[-1] == "rep"
    assert _keep_cells(w) == {BANNER: "", ATLAS: "", PLAIN: ""}

    for rel in (BANNER, ATLAS, PLAIN):
        w._image_assignments[rel] = rep
    w._refresh_image_list()
    # A tick box only where the size can change; the Replacement cell is
    # still the last value (the batch-34 metadata pass relies on it).
    assert _keep_cells(w) == {BANNER: "☐", ATLAS: "", PLAIN: ""}
    assert tree.item(BANNER, "values")[-1] == "SpaceGodzilla.png"

    # The preview's tick and the column are the same flag, both ways.
    w._image_current_rel = BANNER
    w.image_keep_size_var.set(True)
    w._image_on_keep_size_toggle()
    assert tree.set(BANNER, "keep") == "☑"
    w._image_set_keep_size(BANNER, False)
    assert tree.set(BANNER, "keep") == "☐"

    # The metadata pass rebuilds the row and keeps the cell.
    w._image_set_keep_size(BANNER, True)
    w._image_scan_id = 3
    w._apply_image_meta(3, BANNER, w._image_slots_by_rel[BANNER].info)
    assert tree.set(BANNER, "keep") == "☑"
    assert tree.item(BANNER, "values")[-1] == "SpaceGodzilla.png"

    # Sorting on it puts the kept pick first.
    w._image_sort = ("keep", True)
    w._refresh_image_list()
    assert tree.get_children()[0] == BANNER


def _click(w, monkeypatch, rel, col):
    tree = w._image_tree
    monkeypatch.setattr(tree, "identify_region", lambda x, y: "cell")
    monkeypatch.setattr(tree, "identify_row", lambda y: rel)
    pos = list(tree["displaycolumns"]).index(col) + 1
    monkeypatch.setattr(tree, "identify_column", lambda x: "#%d" % pos)

    class _Ev:
        x = y = 5
    w._image_on_tree_click(_Ev)


def test_clicking_the_box_flips_it(window, monkeypatch):
    w, assets, rep = window
    w._image_assignments[BANNER] = rep
    w._image_assignments[ATLAS] = rep
    w._refresh_image_list()
    picked = []
    monkeypatch.setattr(w, "_image_assign_rel", picked.append)

    _click(w, monkeypatch, BANNER, "keep")
    assert w._image_keep_size == {BANNER}
    assert w._image_tree.set(BANNER, "keep") == "☑"
    assert staged_changes.load(assets)["image_keep_size"] == [BANNER]
    _click(w, monkeypatch, BANNER, "keep")
    assert w._image_keep_size == set()
    # An empty cell is not a box: nothing to flip on a font atlas.
    _click(w, monkeypatch, ATLAS, "keep")
    assert w._image_keep_size == set()
    assert picked == []

    # The Replacement column still opens the picker, in grouped mode too,
    # where the display positions shift (it used to be pinned to "#4").
    w.image_group_by_scene_var.set(True)
    w._refresh_image_list()
    _click(w, monkeypatch, BANNER, "src")
    assert picked == []
    _click(w, monkeypatch, BANNER, "rep")
    assert picked == [BANNER]


def test_no_column_without_a_picture_that_can_keep_its_size(window):
    w, assets, rep = window
    w._image_slots = [s for s in w._image_slots if s.rel_path != BANNER]
    w._image_slots_by_rel.pop(BANNER)
    w._refresh_image_list()
    assert "keep" not in w._image_tree["displaycolumns"]


def test_a_cleared_pick_takes_its_flag_out_of_the_sidecar(window):
    w, assets, rep = window
    w._image_assignments[BANNER] = rep
    w._image_current_rel = BANNER
    w._image_set_keep_size(BANNER, True)
    w._image_assignments.pop(BANNER)
    w._save_staged_changes()
    assert staged_changes.load(assets)["image_keep_size"] == []
    assert w.pending_image_assignments(assets) is None
    assert os.path.isfile(os.path.join(assets, BANNER))


def test_the_original_size_is_the_snapshots_once_a_pick_is_applied(window):
    # PAD-179: after a run applied a pick kept at its own size, the slot's
    # file IS that pick. The note called it the original ("Same size as the
    # original (90×22)") while the build fits to the real one.
    from pinball_decryptor.core import staged_originals
    w, assets, rep = window
    assert staged_originals.snapshot(assets, BANNER, None)
    Image.new("RGBA", (90, 22), (255, 255, 255, 255)).save(
        os.path.join(assets, BANNER))
    w._image_assignments[BANNER] = rep
    w._image_current_rel = BANNER
    w._image_render_preview(BANNER)
    assert _shown(w)
    assert "the original 40×20" in w._image_size_lbl["text"]
    assert "squeezed" in w._image_size_lbl["text"]
