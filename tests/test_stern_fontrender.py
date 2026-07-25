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
    """Peter round 2: a wide typeface must not be crushed by its widest
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
