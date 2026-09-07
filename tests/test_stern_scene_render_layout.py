"""The scene preview shows a pending text LAYOUT edit (move / align / size).

A layout edit (:mod:`text_layout`) is a size-neutral rewrite of a scene's
text keyframes and glyph table; the Scenes window has to show it before the
card is written, the way it already shows a pending colour.  These tests pin
the three effects on the synthetic one-glyph extract of
``test_stern_scene_render`` and the metric-scale seam in ``fontrender`` on
the fixture of ``test_stern_fontrender`` — and, above all, that a render
with NO edit is byte-identical to the render that has always been drawn.
"""

import json
import os
import pathlib
import tempfile

import pytest

pytest.importorskip("numpy")
pytest.importorskip("PIL")
import numpy as np                          # noqa: E402

from pinball_decryptor.plugins.stern import (                # noqa: E402
    fontrender as fr, scene_render)
from tests.test_stern_scene_render import (                   # noqa: E402
    _seed_preview_extract, _seed_outline_pair)
from tests.test_stern_fontrender import (                     # noqa: E402
    _make_extract, _font, GREEN, RED, BLUE)

CARD = "/g/s1/scene.radium"


def _text_only_layout(assets):
    """The seeded scene without its sprite, so every lit pixel is text."""
    path = os.path.join(assets, scene_render.SCENE_LAYOUT_MANIFEST)
    with open(path, encoding="utf-8") as f:
        lay = json.load(f)[CARD]
    lay["sprites"] = []
    return lay


def _ink_box(img, thresh=100):
    """``(x0, y0, x1, y1)`` of the lit pixels (exclusive right/bottom)."""
    a = np.asarray(img)
    lit = a.max(axis=2) > thresh
    ys, xs = np.nonzero(lit)
    assert len(xs), "nothing drawn"
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _render(assets, lay, edits=None, **kw):
    img = scene_render.render_layout(assets, lay, layout_edits=edits, **kw)
    assert img is not None
    return img


# ---------------------------------------------------------------------------
# no edit = the same picture
# ---------------------------------------------------------------------------

def test_no_layout_edit_renders_byte_identical():
    """``layout_edits`` absent, empty, for another string, or neutral: the
    frame is exactly the one the preview has always drawn."""
    with tempfile.TemporaryDirectory() as td:
        assets = _seed_preview_extract(pathlib.Path(td))
        lay = _text_only_layout(assets)
        base = np.asarray(scene_render.render_layout(assets, lay))
        for edits in (None, {}, {"Z": {"dx": 10, "dy": 10, "size": 200}},
                      {"A": {"dx": 0, "dy": "", "align": None, "size": 100}},
                      {"A": {}}, {"A": None}):
            got = np.asarray(_render(assets, lay, edits))
            assert np.array_equal(base, got), edits
        # and through render_scene, which is what the window calls
        via_scene = np.asarray(scene_render.render_scene(
            assets, CARD, layout_edits={"A": {"dx": 0}}))
        full = np.asarray(scene_render.render_scene(assets, CARD))
        assert np.array_equal(via_scene, full)


# ---------------------------------------------------------------------------
# move
# ---------------------------------------------------------------------------

def test_move_shifts_the_ink_by_exactly_dx_dy():
    """dx/dy are pixels: the lit box moves by that much, nothing else
    changes (same size, same ink)."""
    with tempfile.TemporaryDirectory() as td:
        assets = _seed_preview_extract(pathlib.Path(td))
        lay = _text_only_layout(assets)
        # Left-aligned so the line sits on a whole pixel: the seeded glyph
        # advances 9 for 8 px of ink, which centres the canvas on x=95.5,
        # and a half pixel rounds whichever way the odd/even shift lands.
        lay["texts"][0]["align"] = 0
        x0, y0, x1, y1 = _ink_box(_render(assets, lay))
        assert (x0, x1 - x0, y1 - y0) == (0, 8, 8)   # the one 8x8 glyph
        for dx, dy in ((10, -4), (7, 12), (3.0, 0), (0, -20), (25, 7)):
            box = _ink_box(_render(assets, lay,
                                   {"A": {"dx": dx, "dy": dy}}))
            assert box == (x0 + dx, y0 + dy, x1 + dx, y1 + dy), (dx, dy)
        # a negative dx pushes the ink off the left edge: it clips, never
        # wraps or raises
        box = _ink_box(_render(assets, lay, {"A": {"dx": -3, "dy": 0}}))
        assert box == (0, y0, x1 - 3, y1)
        # centred, an even shift lands exactly too
        lay["texts"][0]["align"] = 1
        cx0, cy0, cx1, cy1 = _ink_box(_render(assets, lay))
        box = _ink_box(_render(assets, lay, {"A": {"dx": -20, "dy": 6}}))
        assert box == (cx0 - 20, cy0 + 6, cx1 - 20, cy1 + 6)


def test_move_reads_the_manifest_row_shape():
    """The window feeds ``text_layout.layout_for`` rows straight in: strings
    for the offsets are fine, and a row with only one field set still
    moves."""
    with tempfile.TemporaryDirectory() as td:
        assets = _seed_preview_extract(pathlib.Path(td))
        lay = _text_only_layout(assets)
        x0, y0, x1, y1 = _ink_box(_render(assets, lay))
        box = _ink_box(_render(assets, lay,
                               {"A": {"dx": "6", "dy": "", "align": "",
                                      "size": ""}}))
        assert box == (x0 + 6, y0, x1 + 6, y1)


# ---------------------------------------------------------------------------
# align
# ---------------------------------------------------------------------------

def test_align_override_places_the_line_by_the_picked_edge():
    """The keyframe says centred; the pending edit wins, left < centre <
    right, and each matches what the keyframe's own align word draws."""
    with tempfile.TemporaryDirectory() as td:
        assets = _seed_preview_extract(pathlib.Path(td))
        lay = _text_only_layout(assets)
        assert lay["texts"][0]["align"] == 1
        picked = {}
        for name in ("left", "center", "right"):
            picked[name] = _ink_box(_render(assets, lay,
                                            {"A": {"align": name}}))[0]
        assert picked["left"] < picked["center"] < picked["right"], picked
        # the same placement the scene's own word gives
        for code, name in ((0, "left"), (1, "center"), (2, "right")):
            own = json.loads(json.dumps(lay))
            own["texts"][0]["align"] = code
            assert _ink_box(_render(assets, own))[0] == picked[name], name
        # rect 0..200: left at 0; right puts the line's 9 px advance box
        # against 200, so its 8 px of ink start at 191
        assert picked["left"] == 0
        assert picked["right"] == 200 - 9
        # British spelling and the u32 code are accepted too
        assert _ink_box(_render(assets, lay,
                                {"A": {"align": "centre"}}))[0] == \
            picked["center"]
        assert _ink_box(_render(assets, lay,
                                {"A": {"align": 2}}))[0] == picked["right"]


# ---------------------------------------------------------------------------
# size
# ---------------------------------------------------------------------------

def test_size_200_percent_doubles_the_ink_box_on_the_same_baseline():
    """A size edit scales the glyph metrics, so the ink box doubles; the
    baseline (track y) stays where it is and the ink grows UP from it,
    which is what a scaled table does on the machine."""
    with tempfile.TemporaryDirectory() as td:
        assets = _seed_preview_extract(pathlib.Path(td))
        lay = _text_only_layout(assets)
        x0, y0, x1, y1 = _ink_box(_render(assets, lay))
        assert (y1 - y0, x1 - x0) == (8, 8)
        assert y1 == 60                              # sits on the baseline
        bx0, by0, bx1, by1 = _ink_box(_render(assets, lay,
                                              {"A": {"size": 200}}))
        assert (by1 - by0, bx1 - bx0) == (16, 16)
        assert by1 == 60                             # same baseline
        # still centred in the same box
        assert bx0 + (bx1 - bx0) / 2.0 == pytest.approx(x0 + 4, abs=1)
        # and 50 % halves it
        hx0, hy0, hx1, hy1 = _ink_box(_render(assets, lay,
                                              {"A": {"size": 50}}))
        assert (hy1 - hy0, hx1 - hx0) == (4, 4)
        assert hy1 == 60


def test_size_and_move_and_align_compose():
    """One row can carry all three; they compose the way the Write path
    applies them (rect shifted, then aligned, glyphs scaled)."""
    with tempfile.TemporaryDirectory() as td:
        assets = _seed_preview_extract(pathlib.Path(td))
        lay = _text_only_layout(assets)
        box = _ink_box(_render(assets, lay, {"A": {"dx": 5, "dy": -10,
                                                    "align": "left",
                                                    "size": 200}}))
        # left edge = rect L (0) + dx; 16 px tall ending on baseline 60-10
        assert box == (5, 50 - 16, 5 + 16, 50)


# ---------------------------------------------------------------------------
# the outline pass follows its fill
# ---------------------------------------------------------------------------

def test_layout_edit_moves_the_outline_with_its_fill():
    """A colour edit must NOT touch the outline pass (it would erase the
    border); a layout edit MUST — the border is drawn round the same string
    and has to move, align and grow with it or the pair comes apart."""
    with tempfile.TemporaryDirectory() as td:
        assets = _seed_outline_pair(pathlib.Path(td))
        lay = _text_only_layout(assets)
        assert [t.get("outline", False) for t in lay["texts"]] == \
            [True, False]
        before = _render(assets, lay, background="White")
        after = _render(assets, lay, {"A": {"dx": 30, "dy": -6}},
                        background="White")
        b, a = np.asarray(before), np.asarray(after)
        # the whole pair (border + fill) shifted as one: the moved frame
        # equals the original translated by (30, -6)
        h, w = b.shape[:2]
        moved = np.full_like(b, 255)
        moved[:h - 6, 30:] = b[6:, :w - 30]
        assert np.array_equal(a, moved)
        # border still shows round the fill at the new place
        assert a[51 - 6, 100 + 30].max() < 40      # black border
        assert a[55 - 6, 100 + 30].min() > 200     # white fill on top


# ---------------------------------------------------------------------------
# fontrender.render_text(metric_scale=...)
# ---------------------------------------------------------------------------

def test_render_text_metric_scale_one_is_byte_identical(tmp_path):
    """The default and every junk value leave the layout untouched — the
    documented 20x7 canvas of ``test_render_text_layout_and_pixels`` and its
    pixels, byte for byte."""
    _make_extract(tmp_path)
    fo = _font(tmp_path)
    base, missing = fr.render_text(fo, "AB A")
    assert base.size == (20, 7) and missing == set()
    for ms in (1.0, 1, None, 0, -2.0, "x", float("nan"), float("inf")):
        img, m = fr.render_text(fo, "AB A", metric_scale=ms)
        assert m == set()
        assert img.size == base.size, ms
        assert img.tobytes() == base.tobytes(), ms


def test_render_text_metric_scale_scales_advances_bearings_and_bitmaps(
        tmp_path):
    """At 2.0 every metric doubles: pen A(6) B(5) sp(3) A -> 40 wide, ascent
    6 + descent 1 -> 14 tall, 'A' ink at bearing 1*2 and fitted to 8x12."""
    _make_extract(tmp_path)
    fo = _font(tmp_path)
    img, missing = fr.render_text(fo, "AB A", metric_scale=2.0)
    assert missing == set()
    assert img.size == (40, 14)
    arr = np.asarray(img)
    assert tuple(arr[0, 2]) == GREEN            # A's corner at pen 0 + bx 2
    assert tuple(arr[11, 3]) == RED             # 12 rows tall now
    assert arr[12].max() == 0                   # ...and no further
    assert tuple(arr[0, 12]) == BLUE            # B at pen 12 + bx 0
    assert tuple(arr[0, 30]) == GREEN           # 2nd A: (6+5+3)*2 + 2
    # and the whole thing is 2x the unscaled canvas, ink box included
    one, _ = fr.render_text(fo, "AB A")
    assert (img.size[0], img.size[1]) == (one.size[0] * 2, one.size[1] * 2)


def test_render_text_metric_scale_scales_kerning_too(tmp_path):
    """A kerning adjust is a metric of the table; a size edit scales it with
    the rest (the Write path patches the kern floats by the same factor)."""
    _make_extract(tmp_path)
    fo = _font(tmp_path)
    plain, _ = fr.render_text(fo, "AB", metric_scale=2.0)
    fo["glyphs"][ord("A")]["kern"] = {ord("B"): -3.0}
    kerned, _ = fr.render_text(fo, "AB", metric_scale=2.0)
    assert kerned.size[0] == plain.size[0] - 6
    assert tuple(np.asarray(kerned)[0, 6]) == BLUE   # B at (6-3)*2


def test_fit_to_metrics_scale_grows_the_box(tmp_path):
    """The atlas cell is master art; the fitted box scales with the metrics
    (a 4x6 glyph drawn at 150 % is 6x9)."""
    _make_extract(tmp_path)
    fo = _font(tmp_path)
    g = fo["glyphs"][ord("A")]
    img = fr.load_slice(g)
    assert fr._fit_to_metrics(img, g).size == (4, 6)
    assert fr._fit_to_metrics(img, g, 1.5).size == (6, 9)
    assert fr._fit_to_metrics(img, g, 0.5).size == (2, 3)
