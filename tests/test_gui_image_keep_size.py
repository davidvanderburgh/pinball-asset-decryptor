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
    return w, assets, rep


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
