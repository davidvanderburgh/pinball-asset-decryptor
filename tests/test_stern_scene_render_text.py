"""Scene preview of PENDING Replace Text edits.

David (2026-09-07): "Ideally, changes here would propagate everywhere and I
would be able to easily view them to confirm it looks good."  The Scenes
window now hands the renderer ``text_edits`` — the strings.tsv replacements
that reach a scene: its own radium rows, and game-program rows whose original
is a placeholder the scene draws (the game's code overwrites that placeholder
at runtime, so the program edit is what the machine will show).  The line is
drawn with the new letters in the old line's place; rect, alignment, font,
colour and the outline pair are untouched, and a longer string simply runs
on.  These tests are Tk-free: the renderer directly, and the Scenes window's
``_pending_texts`` through a duck-typed stand-in.
"""

import json
import os

import pytest

pytest.importorskip("numpy")
pytest.importorskip("PIL")
import numpy as np                          # noqa: E402
from PIL import Image                       # noqa: E402

from pinball_decryptor.plugins.stern import scene_render     # noqa: E402

CARD = "/g/s1/scene.radium"
FONT = "radimg_font_64x64_aaaa0001"


def _seed(tmp_path, text="A", align=1, rect=(0, 0, 200, 100)):
    """A project folder with a two-glyph white font ('A' 8x8 advance 9, 'B'
    4x8 advance 5) and one scene drawing *text* in a known box."""
    st = tmp_path / "images" / "scene_textures"
    gdir = st / "glyphs" / FONT
    gdir.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(str(st / (FONT + ".png")))
    Image.new("RGBA", (8, 8), (255, 255, 255, 255)).save(
        str(gdir / "U+0041_A.png"))
    Image.new("RGBA", (4, 8), (255, 255, 255, 255)).save(
        str(gdir / "U+0042_B.png"))
    (st / "radium_images.txt").write_text(
        "# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt\n"
        "scene_textures/%s.png\t%s\t100\t16\t64\t64\t5\n" % (FONT, CARD),
        encoding="utf-8")
    (st / "glyph_images.txt").write_text(
        "# glyph output\tatlas output\tchar\tx\ty\tw\th\tfont\trot\tglyph_w"
        "\tglyph_h\tbearing_x\tbearing_y\tadvance\ttable\n"
        "scene_textures/glyphs/%s/U+0041_A.png\tscene_textures/%s.png\t0x0041"
        "\t0\t0\t8\t8\tTestFont\t0\t8\t8\t0\t8\t9\t%s\n"
        "scene_textures/glyphs/%s/U+0042_B.png\tscene_textures/%s.png\t0x0042"
        "\t8\t0\t4\t8\tTestFont\t0\t4\t8\t0\t8\t5\t%s\n"
        % (FONT, FONT, FONT, FONT, FONT, FONT), encoding="utf-8")
    _relayout(tmp_path, text, align, rect)
    return str(tmp_path)


def _relayout(tmp_path, text, align=1, rect=(0, 0, 200, 100)):
    layout = {CARD: {
        "stage": [200, 100, 60.0], "partial": False, "sprites": [],
        "texts": [{"name": "Line1", "x": 0, "y": 60, "text": text,
                   "rect": list(rect), "rgba": [1, 1, 1, 1], "align": align,
                   "font": FONT}]}}
    with open(str(tmp_path / scene_render.SCENE_LAYOUT_MANIFEST), "w",
              encoding="utf-8") as f:
        json.dump(layout, f)
    return layout[CARD]


def _ink_cols(img):
    """Columns holding any bright pixel."""
    a = np.asarray(img)
    return np.where((a.max(axis=2) > 200).any(axis=0))[0]


def test_render_with_text_edits_draws_the_replacement(tmp_path):
    """A pending edit changes the ink; the render equals the one a layout
    whose string IS the replacement produces — nothing but the letters."""
    assets = _seed(tmp_path, "A")
    lay = scene_render.load_layouts(assets)[CARD]
    stock = np.asarray(scene_render.render_layout(assets, lay))
    edited = np.asarray(scene_render.render_layout(
        assets, lay, text_edits={"A": "AB"}))
    assert not np.array_equal(stock, edited)
    # 'A' alone: 8 px of ink centred on 100; 'AB': 9 + 4 = 13 px wide
    assert len(_ink_cols(stock)) == 8
    assert len(_ink_cols(edited)) == 12          # A (8) + gap (1) + B (4)
    as_if = np.asarray(scene_render.render_layout(
        assets, _relayout(tmp_path, "AB")))
    assert np.array_equal(edited, as_if)


def test_render_ignores_an_edit_for_a_string_this_scene_does_not_draw(
        tmp_path):
    assets = _seed(tmp_path, "A")
    lay = scene_render.load_layouts(assets)[CARD]
    stock = np.asarray(scene_render.render_layout(assets, lay))
    same = np.asarray(scene_render.render_layout(
        assets, lay, text_edits={"B": "AB", "": "A"}))
    assert np.array_equal(stock, same)
    # an empty dict and None are the untouched render too
    assert np.array_equal(stock, np.asarray(
        scene_render.render_layout(assets, lay, text_edits={})))


def test_render_keeps_colour_and_layout_keyed_on_the_original(tmp_path):
    """colors.tsv / layout.tsv name their rows by the ORIGINAL string, so a
    pending colour and a pending move still apply to the replaced line."""
    from pinball_decryptor.plugins.stern import text_layout
    assets = _seed(tmp_path, "A")
    lay = scene_render.load_layouts(assets)[CARD]
    a = np.asarray(scene_render.render_layout(
        assets, lay, text_edits={"A": "AB"}, colors={"A": (0, 255, 0)},
        layout_edits={"A": text_layout.normalize({"dx": 20})}))
    cols = _ink_cols(a)
    assert len(cols) == 12
    # centred on 100 without the move (A alone spans 96..103); moved +20
    assert cols.min() >= 110
    ink = a[:, cols].reshape(-1, 3)
    ink = ink[ink.max(axis=1) > 200]
    assert (ink[:, 1] > 200).all() and (ink[:, 0] < 60).all()   # green


def test_render_longer_pending_text_runs_on_and_never_raises(tmp_path):
    """A replacement wider than its box is not re-fitted: a centred line
    grows both ways about the same centre, a right-aligned one grows to the
    left, and one wider than the stage just clips at the edges."""
    assets = _seed(tmp_path, "A")
    lay = scene_render.load_layouts(assets)[CARD]
    stock_cols = _ink_cols(scene_render.render_layout(assets, lay))
    wide_cols = _ink_cols(scene_render.render_layout(
        assets, lay, text_edits={"A": "AAAAA"}))
    c0 = (stock_cols.min() + stock_cols.max()) / 2.0
    c1 = (wide_cols.min() + wide_cols.max()) / 2.0
    assert abs(c0 - c1) <= 1.0 and len(wide_cols) > len(stock_cols)

    right = _relayout(tmp_path, "A", align=2, rect=(0, 0, 120, 100))
    r_stock = _ink_cols(scene_render.render_layout(assets, right))
    r_wide = _ink_cols(scene_render.render_layout(
        assets, right, text_edits={"A": "AAAAA"}))
    assert r_stock.max() == r_wide.max() and r_wide.min() < r_stock.min()

    huge = scene_render.render_layout(
        assets, lay, text_edits={"A": "A" * 40})       # 360 px on a 200 stage
    assert huge is not None
    cols = _ink_cols(huge)
    # ink reaches both stage edges (a 1 px glyph gap may land on a column)
    assert cols.min() <= 1 and cols.max() >= 198


def test_render_scene_passes_text_edits_through(tmp_path):
    assets = _seed(tmp_path, "A")
    a = scene_render.render_scene(assets, CARD, text_edits={"A": "AB"})
    b = scene_render.render_scene(assets, CARD)
    assert not np.array_equal(np.asarray(a), np.asarray(b))


# ---------------------------------------------------------------------------
# The Scenes window's pending-text source, without a Tk root
# ---------------------------------------------------------------------------

class _Stub:
    """Just the attributes ``SceneBrowserWindow._pending_texts`` reads, and
    the one helper it calls."""

    from pinball_decryptor.gui.scene_browser import SceneBrowserWindow as _SB
    _load_text_changes = _SB._load_text_changes

    def __init__(self, assets_dir, layouts):
        self.assets_dir = assets_dir
        self._layouts = layouts
        self._text_changes = None


def _pending(assets, layouts, card, layout=None):
    from pinball_decryptor.gui.scene_browser import SceneBrowserWindow
    stub = _Stub(assets, layouts)
    return SceneBrowserWindow._pending_texts(stub, card, layout)


def _write_manifest(tmp_path, rows):
    from pinball_decryptor.core import text_manifest
    text_manifest.save(str(tmp_path), rows)


def test_pending_texts_takes_the_scene_row_and_the_program_placeholder(
        tmp_path):
    """The scene's own rows apply to it; a game-program row (the manifest
    path that is not a .radium) applies wherever its original is drawn — and
    wins over a radium row for the same string, because the code overwrites
    the placeholder at runtime."""
    assets = _seed(tmp_path, "GODZILLA VS MEGALON")
    layouts = scene_render.load_layouts(assets)
    lay = layouts[CARD]
    _write_manifest(tmp_path, [
        {"path": CARD, "original": "GODZILLA VS MEGALON", "replacement": ""},
        {"path": CARD, "original": "PRESS START", "replacement": "GO"},
        {"path": "/g/game", "original": "GODZILLA VS MEGALON",
         "replacement": "GODZILLA VS SPACEGODZILLA", "budget": 96},
        {"path": "/g/game", "original": "NOT DRAWN HERE",
         "replacement": "STILL NOT", "budget": 20},
        {"path": "/g/other/scene.radium", "original": "GODZILLA VS MEGALON",
         "replacement": "ANOTHER SCENE'S ROW"},
    ])
    got = _pending(assets, layouts, CARD, lay)
    assert got == {"GODZILLA VS MEGALON": "GODZILLA VS SPACEGODZILLA",
                   "PRESS START": "GO"}
    # the layout is looked up by card when the caller has none to hand
    assert _pending(assets, layouts, CARD) == got
    # no card, or an unknown one, is nothing to show
    assert _pending(assets, layouts, None, lay) == {}
    assert _pending(assets, layouts, "/g/none/scene.radium") == {}

    # the program edit wins over the scene's own row for the same string
    _write_manifest(tmp_path, [
        {"path": CARD, "original": "GODZILLA VS MEGALON",
         "replacement": "GODZILLA VS EBIRAH"},
        {"path": "/g/game", "original": "GODZILLA VS MEGALON",
         "replacement": "GODZILLA VS SPACEGODZILLA", "budget": 96},
    ])
    assert _pending(assets, layouts, CARD, lay) == {
        "GODZILLA VS MEGALON": "GODZILLA VS SPACEGODZILLA"}
    # ...and the scene's row alone shows when there is no program edit
    _write_manifest(tmp_path, [
        {"path": CARD, "original": "GODZILLA VS MEGALON",
         "replacement": "GODZILLA VS EBIRAH"}])
    assert _pending(assets, layouts, CARD, lay) == {
        "GODZILLA VS MEGALON": "GODZILLA VS EBIRAH"}


def test_pending_texts_decodes_program_rows_and_caches_the_manifest(tmp_path):
    """Program rows are manifest-encoded (a two-character ``\\n``); the
    layout's strings carry a real newline.  The manifest is read once per
    stand-in and again only after ``text_edits_changed``-style invalidation."""
    from pinball_decryptor.gui.scene_browser import SceneBrowserWindow
    assets = _seed(tmp_path, "GODZILLA\nVS.\nMEGALON")
    layouts = scene_render.load_layouts(assets)
    _write_manifest(tmp_path, [
        {"path": "/g/game", "original": "GODZILLA\\nVS.\\nMEGALON",
         "replacement": "GODZILLA\\nVS.\\nSPACEGODZILLA", "budget": 96}])
    stub = _Stub(assets, layouts)
    got = SceneBrowserWindow._pending_texts(stub, CARD)
    assert got == {"GODZILLA\nVS.\nMEGALON": "GODZILLA\nVS.\nSPACEGODZILLA"}
    # cached: a manifest rewrite is not seen until the cache is dropped
    _write_manifest(tmp_path, [])
    assert SceneBrowserWindow._pending_texts(stub, CARD) == got
    stub._text_changes = None
    assert SceneBrowserWindow._pending_texts(stub, CARD) == {}
    # no manifest at all is fine
    os.remove(os.path.join(assets, "text", "strings.tsv"))
    stub._text_changes = None
    assert SceneBrowserWindow._pending_texts(stub, CARD) == {}
