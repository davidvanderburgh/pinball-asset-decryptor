"""Tests for the Spike 2 font renderer / desktop-font importer.

Synthetic extract folders (manifests + slice PNGs) drive the pure pieces:
manifest loading (table grouping across atlas pages, old-manifest fallback),
text layout (bearings / baseline / advance, rotated slots), the uniform-fit
sizing rule, revert-from-atlas, and the Scene Browser's manifest grouping.
The desktop-font import runs against a real system TTF when one exists
(always on Windows; DejaVu paths on CI), otherwise skips.  The full pipeline
was additionally validated against the real TMNT 1.59 card (137 fonts,
10k glyphs — see the Spike 2 memory notes).
"""

import os
import struct

import pytest

pytest.importorskip("numpy")
pytest.importorskip("PIL")
import numpy as np                    # noqa: E402
from PIL import Image                 # noqa: E402

from pinball_decryptor.plugins.stern import fontrender as fr  # noqa: E402


RED = (255, 0, 0, 255)
GREEN = (0, 255, 0, 255)
BLUE = (0, 0, 255, 255)


def _png(path, arr):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.fromarray(np.asarray(arr, np.uint8), "RGBA").save(path)


def _make_extract(tmp_path, with_metrics=True):
    """Two-atlas-page font ``tbl`` ('A' page 1, 'B' page 2, rotated 'j'
    page 1, space) + a second single-glyph BC1 font ``tbl2``."""
    tex = tmp_path / "images" / "scene_textures"
    g1 = tex / "glyphs" / "radimg_TestA_8x8_00000001"
    g2 = tex / "glyphs" / "radimg_TestA_8x8_00000002"
    g3 = tex / "glyphs" / "radimg_bc1_8x8_00000003"

    # 'A': 4x6 upright red block with a green top-left pixel
    A = np.zeros((6, 4, 4), np.uint8)
    A[:] = RED
    A[0, 0] = GREEN
    _png(str(g1 / "U+0041_A.png"), A)
    # 'B': 3x6 blue
    B = np.zeros((6, 3, 4), np.uint8)
    B[:] = BLUE
    _png(str(g2 / "U+0042_B.png"), B)
    # 'j': upright 3x6 = red left column; stored rotated 90 CW (6x3)
    j_up = np.zeros((6, 3, 4), np.uint8)
    j_up[:, 0] = RED
    j_st = np.rot90(j_up, -1)                     # store = upright turned CW
    _png(str(g1 / "U+006A_j.png"), j_st)
    # space: 1x1 transparent
    _png(str(g1 / "U+0020.png"), np.zeros((1, 1, 4), np.uint8))
    # BC1 font glyph 'C': 4x6 white on opaque black
    C = np.zeros((6, 4, 4), np.uint8)
    C[:] = (0, 0, 0, 255)
    C[1:5, 1:3] = (255, 255, 255, 255)
    _png(str(g3 / "U+0043_C.png"), C)

    # Atlas PNGs (for revert): page 1 holds A at (0,0) and stored-j at (0,8)
    a1 = np.zeros((16, 16, 4), np.uint8)
    a1[0:6, 0:4] = A
    a1[8:11, 0:6] = j_st
    a1[15, 15] = GREEN
    _png(str(tex / "radimg_TestA_8x8_00000001.png"), a1)
    a2 = np.zeros((16, 16, 4), np.uint8)
    a2[1:7, 2:5] = B
    _png(str(tex / "radimg_TestA_8x8_00000002.png"), a2)
    a3 = np.zeros((16, 16, 4), np.uint8)
    a3[:, :, 3] = 255
    a3[0:6, 0:4] = C
    _png(str(tex / "radimg_bc1_8x8_00000003.png"), a3)

    (tex / "radium_images.txt").write_text(
        "# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt\n"
        "scene_textures/radimg_TestA_8x8_00000001.png\t/g/scene1/scene.radium"
        "\t100\t256\t16\t16\t5\n"
        "scene_textures/radimg_TestA_8x8_00000002.png\t/g/scene1/scene.radium"
        "\t300\t256\t16\t16\t5\n"
        "scene_textures/radimg_TestA_8x8_00000001.png\t/g/scene9/scene.radium"
        "\t100\t256\t16\t16\t5\n"
        "scene_textures/radimg_bc1_8x8_00000003.png\t/g/scene2/scene.radium"
        "\t100\t128\t16\t16\t4\n",
        encoding="utf-8")

    if with_metrics:
        rows = [
            # rel, atlas, char, x, y, w, h, font, rot, lw, lh, bx, by, adv, tbl
            ("scene_textures/glyphs/radimg_TestA_8x8_00000001/U+0041_A.png",
             "scene_textures/radimg_TestA_8x8_00000001.png", "0x0041",
             "0", "0", "4", "6", "TestFont", "0", "4", "6", "1", "6", "6",
             "tbl"),
            ("scene_textures/glyphs/radimg_TestA_8x8_00000002/U+0042_B.png",
             "scene_textures/radimg_TestA_8x8_00000002.png", "0x0042",
             "2", "1", "3", "6", "TestFont", "0", "3", "6", "0", "6", "5",
             "tbl"),
            ("scene_textures/glyphs/radimg_TestA_8x8_00000001/U+006A_j.png",
             "scene_textures/radimg_TestA_8x8_00000001.png", "0x006A",
             "0", "8", "6", "3", "TestFont", "1", "3", "6", "0", "5", "4",
             "tbl"),
            ("scene_textures/glyphs/radimg_TestA_8x8_00000001/U+0020.png",
             "scene_textures/radimg_TestA_8x8_00000001.png", "0x0020",
             "15", "15", "1", "1", "TestFont", "0", "1", "1", "0", "0", "3",
             "tbl"),
            ("scene_textures/glyphs/radimg_bc1_8x8_00000003/U+0043_C.png",
             "scene_textures/radimg_bc1_8x8_00000003.png", "0x0043",
             "0", "0", "4", "6", "Bc1Font", "0", "4", "6", "0", "6", "5",
             "tbl2"),
        ]
        head = ("# glyph output\tatlas output\tchar\tx\ty\tw\th\tfont\trot"
                "\tglyph_w\tglyph_h\tbearing_x\tbearing_y\tadvance\ttable\n")
    else:
        rows = [
            ("scene_textures/glyphs/radimg_TestA_8x8_00000001/U+0041_A.png",
             "scene_textures/radimg_TestA_8x8_00000001.png", "0x0041",
             "0", "0", "4", "6", "TestFont"),
        ]
        head = "# glyph output\tatlas output\tchar\tx\ty\tw\th\tfont\n"
    (tex / "glyph_images.txt").write_text(
        head + "".join("\t".join(r) + "\n" for r in rows), encoding="utf-8")
    return tmp_path


def _font(tmp_path, key="tbl"):
    fonts = {f["key"]: f for f in fr.load_fonts(str(tmp_path))}
    return fonts[key]


# ---- load_fonts --------------------------------------------------------------

def test_load_fonts_groups_by_table_across_atlas_pages(tmp_path):
    _make_extract(tmp_path)
    fonts = fr.load_fonts(str(tmp_path))
    by_key = {f["key"]: f for f in fonts}
    assert set(by_key) == {"tbl", "tbl2"}
    fo = by_key["tbl"]
    assert set(fo["glyphs"]) == {0x20, 0x41, 0x42, 0x6A}
    assert len(fo["atlas_rels"]) == 2            # both pages of the font
    assert fo["has_metrics"]
    assert fo["ascent"] == 6 and fo["descent"] == 1   # j: 6 tall, baseline 5
    g = fo["glyphs"][0x6A]
    assert g["rot"] and (g["w"], g["h"]) == (6, 3) and (g["lw"], g["lh"]) == (3, 6)
    assert by_key["tbl2"]["glyphs"][0x43]["fmt"] == 4  # BC1 page


def test_load_fonts_old_manifest_fallback(tmp_path):
    _make_extract(tmp_path, with_metrics=False)
    fonts = fr.load_fonts(str(tmp_path))
    assert len(fonts) == 1
    fo = fonts[0]
    assert not fo["has_metrics"]
    g = fo["glyphs"][0x41]
    # approximations: upright, baseline at bitmap bottom, advance ~ width
    assert not g["rot"] and g["by"] == 6 and g["adv"] > g["lw"]


# ---- load_slice / rotation ---------------------------------------------------

def test_load_slice_unrotates_ccw(tmp_path):
    _make_extract(tmp_path)
    fo = _font(tmp_path)
    up = np.asarray(fr.load_slice(fo["glyphs"][0x6A]))
    assert up.shape == (6, 3, 4)                 # logical/upright dims
    assert (up[:, 0] == RED).all()               # red left column restored
    assert (up[:, 1:, :3] == 0).all()


# ---- render_text -------------------------------------------------------------

def test_render_text_layout_and_pixels(tmp_path):
    _make_extract(tmp_path)
    fo = _font(tmp_path)
    img, missing = fr.render_text(fo, "AB A")
    assert missing == set()
    # ascent 6, descent 1 -> H = 7; pen: A(adv 6) B(adv 5) sp(adv 3) A -> 20
    assert img.size == (20, 7)
    arr = np.asarray(img)
    # 'A' ink at pen 0 + bx 1 = x1, top = asc - by = 0; green corner pixel
    assert tuple(arr[0, 1]) == GREEN
    assert tuple(arr[5, 2]) == RED
    # 'B' at pen 6 + bx 0
    assert tuple(arr[0, 6]) == BLUE
    # second 'A' after space: pen 6+5+3 = 14, +bx = 15
    assert tuple(arr[0, 15]) == GREEN
    # nothing above baseline+descent row: bottom row (descent) is empty here
    assert arr[6].max() == 0


def test_render_text_applies_kerning(tmp_path):
    _make_extract(tmp_path)
    fo = _font(tmp_path)
    img_plain, _ = fr.render_text(fo, "AB")
    fo["glyphs"][ord("A")]["kern"] = {ord("B"): -3.0}
    img_kern, _ = fr.render_text(fo, "AB")
    assert img_kern.size[0] == img_plain.size[0] - 3
    arr = np.asarray(img_kern)
    # 'B' (blue) starts 3px earlier: at pen 6-3=3
    assert tuple(arr[0, 3]) == BLUE


def test_render_text_missing_and_multiline(tmp_path):
    _make_extract(tmp_path)
    fo = _font(tmp_path)
    img, missing = fr.render_text(fo, "AZ\nB")
    assert missing == {"Z"}
    # two lines: H = 2 * (6 + 1 + gap) - gap
    assert img.size[1] == 2 * (7 + fr.LINE_GAP) - fr.LINE_GAP


def test_render_text_rotated_slot_upright(tmp_path):
    _make_extract(tmp_path)
    fo = _font(tmp_path)
    img, _ = fr.render_text(fo, "j")
    arr = np.asarray(img)
    # baseline = ascent 6, by 5 -> top row 1; left column red, 3 wide 6 tall
    assert tuple(arr[1, 0]) == RED
    assert tuple(arr[6, 0]) == RED
    assert arr[0].max() == 0


def _supersampled_extract(tmp_path, sizes=((6, 4, 6, 6),)):
    """A font whose ATLAS CELL is 12x18 while its metrics box is much smaller.

    *sizes* is ``(size_id, lw, lh, adv)`` per table — several entries put one
    atlas at several sizes, which is what JAWS does with ``GameFont_Primary``
    (eight sizes over one 512x512 atlas) and TMNT with ``Stern_Impact_Outline``.
    """
    tex = tmp_path / "images" / "scene_textures"
    cell = np.zeros((18, 12, 4), np.uint8)
    cell[:] = RED
    _png(str(tex / "glyphs" / "radimg_Big_16x16_0000000f" / "U+0041_A.png"),
         cell)
    _png(str(tex / "radimg_Big_16x16_0000000f.png"),
         np.zeros((32, 32, 4), np.uint8))
    (tex / "radium_images.txt").write_text(
        "# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt\n"
        "scene_textures/radimg_Big_16x16_0000000f.png\t/g/s/scene.radium"
        "\t100\t1024\t32\t32\t5\n", encoding="utf-8")
    rows = []
    for size_id, lw, lh, adv in sizes:
        rows.append("\t".join((
            "scene_textures/glyphs/radimg_Big_16x16_0000000f/U+0041_A.png",
            "scene_textures/radimg_Big_16x16_0000000f.png", "0x0041",
            "0", "0", "12", "18", "BigFont", "0", str(lw), str(lh), "0",
            str(lh), str(adv), "tbl", "", str(size_id))))
    (tex / "glyph_images.txt").write_text("\n".join(rows) + "\n",
                                          encoding="utf-8")
    return tmp_path


def test_glyph_ink_is_scaled_to_its_metric_box(tmp_path):
    """The atlas cell is the font's MASTER art, not the size it is drawn at.

    JAWS bakes one typeface over a shared high-resolution atlas and each table
    scales it: '0' is a single 82x94 cell drawn at 28x31 by one table and 54x64
    by another.  Pasting the cell at its native size drew every JAWS text line
    about 3x too big — glyphs overlapped their neighbours and lines ran off the
    stage while the advances stayed right.  TMNT's cells already equal their
    metrics box exactly, which is why this went unnoticed."""
    _supersampled_extract(tmp_path)
    fo = _font(tmp_path)
    img, _ = fr.render_text(fo, "A")
    # ink 4 wide at bearing 0, advance 6 -> canvas is the advance, not the
    # 12px cell; height is ascent+descent, which the cell would overflow.
    assert img.size == (6, 6)
    arr = np.asarray(img)
    assert arr[..., 3].max() == 255          # the glyph still drew
    assert arr[0, 4:, 3].max() == 0          # and stayed inside its box


def test_one_atlas_drawn_at_two_sizes_keeps_both(tmp_path):
    """One atlas, two sizes: both sets of metrics have to survive the extract.

    The manifest used to be deduped per (font, glyph), so the first table to
    claim a typeface won and every other size of it was dropped — card-wide.
    Every scene then drew its text at that one size: JAWS' "MODE TITLE /
    LINE 0..8" screen wants 45px and rendered at the 150px a different scene
    had already claimed."""
    _supersampled_extract(tmp_path, sizes=((6, 4, 6, 6), (18, 12, 18, 14)))
    fonts = fr.load_fonts(str(tmp_path))
    # still ONE entry per font — the sizes share an atlas and its slices, so
    # the Fonts window has one thing to show and one thing to import into
    assert [f["key"] for f in fonts] == ["tbl"]
    assert sorted(fonts[0]["sizes"]) == [6, 18]
    small = fr.font_at_size(fonts[0], 6)
    big = fr.font_at_size(fonts[0], 18)
    assert (small["px"], big["px"]) == (6, 18)
    assert fr.render_text(small, "A")[0].size == (6, 6)
    assert fr.render_text(big, "A")[0].size == (14, 18)
    # an unknown size (a project extracted before sizes were recorded) falls
    # back to the representative rather than failing to draw
    assert fr.font_at_size(fonts[0], 99) is fonts[0]


# ---- fit_size ----------------------------------------------------------------

def test_fit_size_core_chars_only():
    slots = {ord("A"): {"lw": 10, "lh": 20},
             ord("_"): {"lw": 30, "lh": 3}}      # oddball must not throttle

    def measure(size):
        return {ord("A"): (size, 2 * size), ord("_"): (size, size)}

    assert fr.fit_size(measure, slots) == 10
    # without a core char, everything constrains
    assert fr.fit_size(measure, {ord("_"): {"lw": 30, "lh": 3}}) == 3


def test_fit_size_squeeze_lets_height_govern():
    """a tester round 2: a wide typeface must not be crushed by its widest
    letter — with squeeze, width may overflow (raster compresses it) and
    HEIGHT picks the size."""
    slots = {ord("A"): {"lw": 10, "lh": 20}}

    def measure(size):
        return {ord("A"): (2 * size, size)}     # twice as wide as tall

    assert fr.fit_size(measure, slots) == 5                  # strict: width
    assert fr.fit_size(measure, slots, squeeze=0.5) == 10    # height + squeeze


def test_fit_size_unfittable():
    slots = {ord("A"): {"lw": 1, "lh": 1}}
    assert fr.fit_size(lambda s: {ord("A"): (s + 5, s + 5)}, slots) == 0


# ---- desktop-font import -----------------------------------------------------

def _system_ttf():
    for p in (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\verdana.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/dejavu/DejaVuSans.ttf",
              "/System/Library/Fonts/Supplemental/Arial.ttf",
              "/Library/Fonts/Arial.ttf"):
        if os.path.isfile(p):
            return p
    return None


@pytest.mark.skipif(_system_ttf() is None, reason="no system TTF found")
def test_rasterize_ttf_fits_slots_and_flattens_bc1(tmp_path):
    _make_extract(tmp_path)
    fo = _font(tmp_path)
    slices, size, kept = fr.rasterize_ttf(fo, _system_ttf(),
                                          color=(255, 255, 255))
    assert size >= 2
    # every redrawn glyph comes back at its as-stored dims
    for ch, img in slices.items():
        g = fo["glyphs"][ch]
        assert img.size == (g["w"], g["h"])
    # space (1x1) is never redrawn
    assert 0x20 not in slices

    bc1 = _font(tmp_path, "tbl2")
    s2, _size2, _kept2 = fr.rasterize_ttf(bc1, _system_ttf())
    cell = np.asarray(s2[0x43])
    assert (cell[..., 3] == 255).all()           # opaque background kept


@pytest.mark.skipif(_system_ttf() is None, reason="no system TTF found")
def test_save_slices_then_render_shows_import(tmp_path):
    _make_extract(tmp_path)
    fo = _font(tmp_path)
    slices, _size, _kept = fr.rasterize_ttf(fo, _system_ttf(),
                                            color=(255, 255, 0))
    assert fr.save_slices(fo, slices) == len(slices)
    img, _ = fr.render_text(fo, "A")
    arr = np.asarray(img)
    ink = arr[arr[..., 3] > 0]                   # tiny slots = faint AA ink
    assert len(ink) and (ink[:, 2] < 64).all()   # yellow ink, not the old red
    assert (ink[:, 1] > 128).any()               # some green channel present


# ---- revert ------------------------------------------------------------------

def test_revert_slices_restores_from_atlas(tmp_path):
    _make_extract(tmp_path)
    fo = _font(tmp_path)
    a_png = fo["glyphs"][0x41]["abs"]
    orig = np.asarray(Image.open(a_png).convert("RGBA")).copy()
    _png(a_png, np.full((6, 4, 4), 255, np.uint8))       # vandalize
    assert fr.revert_slices(str(tmp_path), fo) >= 3
    back = np.asarray(Image.open(a_png).convert("RGBA"))
    assert np.array_equal(back, orig)
    # the rotated slot reverts to its AS-STORED orientation
    j = np.asarray(Image.open(fo["glyphs"][0x6A]["abs"]).convert("RGBA"))
    assert j.shape == (3, 6, 4)


# ---- scenes_for_font ---------------------------------------------------------

def test_scenes_for_font(tmp_path):
    _make_extract(tmp_path)
    fo = _font(tmp_path)
    assert fr.scenes_for_font(str(tmp_path), fo) == [
        "/g/scene1/scene.radium", "/g/scene9/scene.radium"]


# ---- font scope (which scenes an edit lands in) ------------------------------

def test_font_scope_round_trip_and_clear(tmp_path):
    """A font with no scope applies everywhere; scoping writes one row per
    atlas page x scene and reads back; clearing removes the file."""
    _make_extract(tmp_path)
    fo = _font(tmp_path)
    assert fr.get_font_scope(str(tmp_path), fo) is None      # default = all
    fr.set_font_scope(str(tmp_path), fo, ["/g/scene9/scene.radium"])
    assert fr.get_font_scope(str(tmp_path), fo) == [
        "/g/scene9/scene.radium"]
    # The font spans two atlas pages, so both are narrowed together.
    scopes = fr.load_scopes(str(tmp_path))
    assert set(scopes) == set(fo["atlas_rels"])
    assert all(v == {"/g/scene9/scene.radium"} for v in scopes.values())
    fr.set_font_scope(str(tmp_path), fo, None)
    assert fr.get_font_scope(str(tmp_path), fo) is None
    assert not os.path.exists(os.path.join(str(tmp_path), fr.SCOPE_MANIFEST))


def test_font_scope_leaves_other_fonts_alone(tmp_path):
    """Narrowing one font rewrites the file without disturbing another's
    rows (they share one scope file)."""
    _make_extract(tmp_path)
    a, b = _font(tmp_path, "tbl"), _font(tmp_path, "tbl2")
    fr.set_font_scope(str(tmp_path), a, ["/g/scene1/scene.radium"])
    fr.set_font_scope(str(tmp_path), b, ["/g/scene2/scene.radium"])
    assert fr.get_font_scope(str(tmp_path), a) == ["/g/scene1/scene.radium"]
    assert fr.get_font_scope(str(tmp_path), b) == ["/g/scene2/scene.radium"]
    fr.set_font_scope(str(tmp_path), a, None)
    assert fr.get_font_scope(str(tmp_path), a) is None
    assert fr.get_font_scope(str(tmp_path), b) == ["/g/scene2/scene.radium"]


# ---- font_color --------------------------------------------------------------

def test_font_color_ignores_bc1_black_background(tmp_path):
    _make_extract(tmp_path)
    r, g, b = fr.font_color(_font(tmp_path, "tbl2"))
    assert min(r, g, b) > 200                    # white ink, not gray


# ---- Scene Browser grouping --------------------------------------------------

def test_collect_scenes_groups_manifests(tmp_path):
    _make_extract(tmp_path)
    from pinball_decryptor.core import text_manifest
    text_manifest.save(str(tmp_path), [
        {"path": "/g/scene1/scene.radium", "original": "HELLO",
         "replacement": ""},
        {"path": "/g/scene2/scene.radium", "original": "WORLD",
         "replacement": ""},
    ])
    from pinball_decryptor.gui.scene_browser import collect_scenes
    scenes = collect_scenes(str(tmp_path))
    s1 = scenes["/g/scene1"]
    assert [r for _o, r in s1["images"]] == [
        "images/scene_textures/radimg_TestA_8x8_00000001.png",
        "images/scene_textures/radimg_TestA_8x8_00000002.png"]
    assert s1["fonts"] == {"tbl": ("TestFont", 6)}
    assert s1["texts"] == ["HELLO"]
    assert s1["label"] == "TestA · scene1"
    s2 = scenes["/g/scene2"]
    assert s2["fonts"] == {"tbl2": ("Bc1Font", 6)}
    assert s2["texts"] == ["WORLD"]
    # scene9 shares atlas page 1 -> same font, same first image
    assert scenes["/g/scene9"]["fonts"] == {"tbl": ("TestFont", 6)}


# ---- outline companions ------------------------------------------------------
#
# A Stern title draws an outline instance with a fill instance on top, from two
# DIFFERENT fonts.  Restyling only the fill leaves the original typeface's black
# silhouette around the new letters — a tester reported that three times over
# ("strange inconsistent black border", "everything else from white as black",
# "i do still see font glyphs on some places") without being able to find it,
# because the companion is listed here as an unrelated font.

def _outline_row(rel, atlas, char, w, h, name, lw, lh, by, table):
    return (rel, atlas, char, "0", "0", str(w), str(h), name, "0",
            str(lw), str(lh), "0", str(by), str(lw + 1), table)


def _make_outline_extract(tmp_path):
    """A body font plus three would-be outline companions: one real, one whose
    letters are a different size, and one drawn in no shared scene."""
    tex = tmp_path / "images" / "scene_textures"
    # Sized like a real title font (px = lh): small enough to build fast, big
    # enough that MIN_RESTYLE_PX is not also in play here.
    specs = [
        # table,     atlas id, name,               lw, lh, by, scene
        ("body",  "0001", "TestFont",         20, 34, 34, "/g/scene1"),
        ("ok",    "0002", "TestFont_Outline", 20, 34, 34, "/g/scene1"),
        ("wrong", "0003", "TestFont_OUTLINE4", 45, 70, 70, "/g/scene1"),
        ("far",   "0004", "TestFont_Outline", 20, 34, 34, "/g/scene7"),
        # the SAME typeface at a second size — on TMNT there are 94 of these
        ("body2", "0005", "TestFont",         30, 50, 50, "/g/scene1"),
    ]
    img_rows, g_rows = [], []
    for table, aid, name, lw, lh, by, scene in specs:
        stem = "radimg_T_8x8_0000%s" % aid
        arel = "scene_textures/%s.png" % stem
        _png(str(tex / ("%s.png" % stem)), np.zeros((32, 32, 4), np.uint8))
        img_rows.append("%s\t%s/scene.radium\t100\t256\t32\t32\t5" % (arel, scene))
        if table == "ok":
            # the companion ALSO turns up in a scene its body font is not in —
            # on TMNT that happens 440 times, and blanking is card-wide
            img_rows.append("%s\t/g/scene5/scene.radium\t100\t256\t32\t32\t5"
                            % arel)
        for ch, hexc in (("A", "0x0041"), ("B", "0x0042")):
            tile = np.zeros((lh, lw, 4), np.uint8)
            tile[:] = (0, 0, 0, 255) if table != "body" else RED
            rel = "scene_textures/glyphs/%s/U+00%s_%s.png" % (
                stem, hexc[-2:], ch)
            _png(str(tmp_path / "images" / rel.replace("/", os.sep)), tile)
            g_rows.append(_outline_row(rel, arel, hexc, lw, lh, name,
                                       lw, lh, by, table))
    (tex / "radium_images.txt").write_text(
        "# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt\n"
        + "\n".join(img_rows) + "\n", encoding="utf-8")
    (tex / "glyph_images.txt").write_text(
        "# glyph output\tatlas output\tchar\tx\ty\tw\th\tfont\trot\tglyph_w"
        "\tglyph_h\tbearing_x\tbearing_y\tadvance\ttable\n"
        + "".join("\t".join(r) + "\n" for r in g_rows), encoding="utf-8")
    return tmp_path


def test_outline_base_reads_sterns_suffixes():
    assert fr.outline_base("Stern_CCZoinks_OUTLINE4") == "Stern_CCZoinks"
    assert fr.outline_base("Stern_Impact_Outline_8") == "Stern_Impact"
    assert fr.outline_base("Blackmoor_Outline") == "Blackmoor"
    assert fr.outline_base("Stern_Impact") == ""
    assert fr.outline_base("") == ""


def test_outline_companion_needs_a_shared_scene_and_matching_letters(tmp_path):
    """The name alone is Stern's authoring convention — acting on it would
    modify a font the user never picked.  A pair is only accepted when the two
    fonts are drawn in the same scene AND their letters have the identical
    logical box, which is what actually makes them the same letters."""
    _make_outline_extract(tmp_path)
    fonts = fr.load_fonts(str(tmp_path))
    by_key = {f["key"]: f for f in fonts}
    comp = fr.outline_companions(str(tmp_path), fonts)
    assert set(comp) == {"body"}, "only the corroborated pair may match"
    assert comp["body"]["key"] == "ok"
    # the two rejects are still recognisably outline fonts, just unpaired
    assert fr.outline_base(by_key["wrong"]["name"]) == "TestFont"
    assert fr.outline_base(by_key["far"]["name"]) == "TestFont"


def test_recolor_slices_repaints_by_the_channel_that_holds_the_shape(tmp_path):
    """A colour with no font file imported used to do nothing at all.  Now it
    repaints the current letters — and which channel carries the letter's shape
    is format-specific, so the two atlas formats take different routes."""
    _make_extract(tmp_path)
    green = (51, 204, 51)

    # BC3 ('A' is flat red with the shape in alpha): the ink is replaced and
    # the alpha kept, which is what lets a solid-black outline be recoloured.
    out = fr.recolor_slices(_font(tmp_path, "tbl"), green)
    a = np.asarray(out[0x41])
    assert a.shape[:2] == (6, 4)
    ink = a[a[..., 3] > 0]
    assert len(ink) and (ink[:, :3] == green).all()

    # BC1 ('C' is white ink on OPAQUE black): brightness is the shape, so the
    # colour is scaled by it — the background stays black and the slot stays
    # opaque, because a BC1 slot has no usable alpha.
    c = np.asarray(fr.recolor_slices(_font(tmp_path, "tbl2"), green)[0x43])
    assert (c[..., 3] == 255).all(), "a BC1 slot must not gain transparency"
    assert tuple(c[0, 0][:3]) == (0, 0, 0), "the black background must stay"
    assert tuple(c[2, 1][:3]) == green


def test_recolor_slices_round_trips_through_save_and_revert(tmp_path):
    """A recolour is an ordinary glyph edit: it saves over the slice PNGs and
    Revert re-cuts the originals from the atlas."""
    _make_extract(tmp_path)
    font = _font(tmp_path, "tbl")
    before = np.asarray(Image.open(font["glyphs"][0x41]["abs"]).convert("RGBA"))
    assert fr.save_slices(font, fr.recolor_slices(font, (51, 204, 51))) >= 1
    after = np.asarray(Image.open(font["glyphs"][0x41]["abs"]).convert("RGBA"))
    assert after.shape == before.shape
    assert not np.array_equal(after, before)
    fr.revert_slices(str(tmp_path), font)
    back = np.asarray(Image.open(font["glyphs"][0x41]["abs"]).convert("RGBA"))
    assert np.array_equal(back, before)


def test_clear_font_blanks_by_atlas_format(tmp_path):
    """Removing the companion is a tester's own fix ("removing the shadow font in
    total").  A BC3 slot goes transparent; a BC1 slot has no usable alpha, so
    it goes opaque BLACK — the machine ADDS BC1 art, and black adds nothing."""
    _make_extract(tmp_path)
    bc3, bc1 = _font(tmp_path, "tbl"), _font(tmp_path, "tbl2")
    assert fr.clear_font(bc3) == len(bc3["glyphs"])
    assert fr.clear_font(bc1) == len(bc1["glyphs"])
    a = np.asarray(Image.open(bc3["glyphs"][0x41]["abs"]).convert("RGBA"))
    assert a[..., 3].max() == 0                      # nothing drawn
    c = np.asarray(Image.open(bc1["glyphs"][0x43]["abs"]).convert("RGBA"))
    assert c[..., 3].min() == 255 and c[..., :3].max() == 0
    # and it is undoable, which is what makes it safe to offer
    assert fr.revert_slices(str(tmp_path), bc3) == len(bc3["glyphs"])
    back = np.asarray(Image.open(bc3["glyphs"][0x41]["abs"]).convert("RGBA"))
    assert back[..., 3].max() == 255


def test_font_color_reads_black_ink_instead_of_falling_back_to_white(tmp_path):
    """Outline companions are solid BLACK, which zeroes the luminance
    weighting; answering "white" for one made "match original" produce a white
    halo where the game wanted a dark one."""
    _make_outline_extract(tmp_path)
    fonts = {f["key"]: f for f in fr.load_fonts(str(tmp_path))}
    assert fr.font_color(fonts["ok"]) == (0, 0, 0)
    assert max(fr.font_color(fonts["body"])) > 200      # red body ink


def test_glyph_io_goes_through_the_long_path_form(tmp_path, monkeypatch):
    """Glyph slices are the deepest files in a project (120+ characters below
    the folder), so every read and write of one has to be able to exceed
    Windows' 260-character limit.  This asserts the WIRING — that the calls go
    through ``longpath.ext`` — because a machine with LongPathsEnabled opens
    them either way and would hide a regression."""
    from PIL import Image as _Image
    from pinball_decryptor.core import longpath

    _make_extract(tmp_path)
    fo = _font(tmp_path, "tbl")
    seen = []
    real_open = _Image.open
    monkeypatch.setattr(_Image, "open",
                        lambda p, *a, **k: (seen.append(p), real_open(p, *a, **k))[1])
    fr.load_slice(fo["glyphs"][0x41])
    assert seen and seen[0] == longpath.ext(fo["glyphs"][0x41]["abs"])

    saved = []
    monkeypatch.setattr(type(_Image.new("RGBA", (1, 1))), "save",
                        lambda self, p, *a, **k: saved.append(p))
    fr.save_slices(fo, {0x41: _Image.new("RGBA", (4, 6))})
    assert saved == [longpath.ext(fo["glyphs"][0x41]["abs"])]


@pytest.mark.skipif(_system_ttf() is None, reason="no system TTF found")
def test_width_scale_leaves_side_bearings_without_losing_height(tmp_path):
    """The card's own advances lay text out and an import must not change
    them, so a letter that fills its slot sits hard against its neighbour
    (a tester: "some of the letters are very near together").  Narrowing the INK
    inside the same slot buys the gap; shrinking the font would buy it by
    giving up height, which is what Size already does."""
    _make_outline_extract(tmp_path)
    fonts = {f["key"]: f for f in fr.load_fonts(str(tmp_path))}
    fo = fonts["body2"]

    def ink_box(slices, ch):
        a = np.asarray(slices[ch].convert("RGBA"))
        cols = np.nonzero(a[..., 3].max(axis=0) > 24)[0]
        rows = np.nonzero(a[..., 3].max(axis=1) > 24)[0]
        return (cols.max() - cols.min() + 1, rows.max() - rows.min() + 1)

    full, size_full, _k = fr.rasterize_ttf(fo, _system_ttf(),
                                           color=(255, 255, 255))
    narrow, size_narrow, _k2 = fr.rasterize_ttf(fo, _system_ttf(),
                                                color=(255, 255, 255),
                                                width_scale=0.7)
    assert size_narrow == size_full, "the fitted size must not move"
    for ch in (0x41, 0x42):
        assert narrow[ch].size == full[ch].size, "the atlas rect is fixed"
        wf, hf = ink_box(full, ch)
        wn, hn = ink_box(narrow, ch)
        assert wn < wf, "ink should be narrower, leaving a side bearing"
        assert hn >= hf - 1, "…and keep its height"


def test_snapshot_and_restore_round_trips_including_missing_files(tmp_path):
    """Undo has to put back what was THERE — a previous import, a hand edit,
    or stock — which is why it snapshots bytes rather than re-cutting from the
    atlas the way Revert does."""
    _make_extract(tmp_path)
    fo = _font(tmp_path, "tbl")
    before = fr.snapshot_fonts([fo])
    assert len(before) == len(fo["glyphs"])
    assert fr.snapshot_bytes(before) > 0

    # a file that does not exist is recorded as None, so restoring removes it
    gone = fo["glyphs"][0x41]["abs"]
    os.remove(gone)
    mid = fr.snapshot_fonts([fo])
    assert mid[gone] is None

    assert fr.restore_snapshot(before) == len(before)
    assert os.path.isfile(gone)
    with open(gone, "rb") as f:
        assert f.read() == before[gone]

    assert fr.restore_snapshot(mid) >= 1
    assert not os.path.isfile(gone), "restoring a None entry deletes the file"


def test_outline_companion_appears_beyond_its_body_font(tmp_path):
    """Blanking a companion is CARD-WIDE — one atlas serves every scene that
    draws it.  On TMNT a paired outline font turns up in 446 scene
    occurrences but overlaps its body font in only 6, so a plain blank strips
    outlines off 440 screens the user never touched.  That is what a tester did
    by hand: "i did remove to much shadow, now on the normal font some are
    missing too"."""
    _make_outline_extract(tmp_path)
    fonts = {f["key"]: f for f in fr.load_fonts(str(tmp_path))}
    body, comp = fonts["body"], fonts["ok"]
    mine = set(fr.scenes_for_font(str(tmp_path), body))
    theirs = set(fr.scenes_for_font(str(tmp_path), comp))
    assert theirs - mine, "the companion must reach beyond its body font"
    assert mine & theirs, "…and still overlap it somewhere"
