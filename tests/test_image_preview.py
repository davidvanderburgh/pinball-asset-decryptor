"""Tests for the Replace-Images preview thumbnail (core.image.thumbnail_png).

A black font glyph with a transparent background was invisible on the dark
theme (the canvas matched the glyph), so transparent images composite over
the editors' checkerboard; and tiny images (glyph slices) upscale by a whole
factor with nearest-neighbour so they're inspectable at all.
"""

import io

import pytest

pytest.importorskip("numpy")
PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402
import numpy as np      # noqa: E402

from pinball_decryptor.core.image import thumbnail_png


def _png(tmp_path, arr, name="t.png"):
    p = tmp_path / name
    Image.fromarray(arr, "RGBA").save(p)
    return str(p)


def _decode(png_bytes):
    return np.asarray(Image.open(io.BytesIO(png_bytes)).convert("RGBA"))


def test_transparent_glyph_gets_checkerboard(tmp_path):
    # a black glyph stroke on a fully transparent tile
    tile = np.zeros((40, 20, 4), np.uint8)
    tile[4:36, 8:12] = (0, 0, 0, 255)
    out = _decode(thumbnail_png(_png(tmp_path, tile), 320, 214))
    assert (out[:, :, 3] == 255).all()            # nothing transparent left
    # the backdrop shows BOTH checker grays, and the glyph stayed black
    colors = {tuple(px) for px in out[0].tolist()}     # top row = backdrop
    assert (204, 204, 204, 255) in colors and (153, 153, 153, 255) in colors
    h, w = out.shape[:2]
    assert tuple(out[h // 2, w // 2]) == (0, 0, 0, 255)


def test_small_image_upscales_integer_nearest(tmp_path):
    tile = np.zeros((16, 16, 4), np.uint8)
    tile[:8, :8] = (255, 0, 0, 255)
    tile[8:, 8:] = (0, 0, 255, 255)
    out = _decode(thumbnail_png(_png(tmp_path, tile), 320, 214))
    k = min(320 // 16, 214 // 16)                 # whole-number factor
    assert out.shape[:2] == (16 * k, 16 * k)
    assert tuple(out[0, 0]) == (255, 0, 0, 255)   # crisp: no resample blur
    assert tuple(out[-1, -1]) == (0, 0, 255, 255)


def test_opaque_image_downscales_without_checker(tmp_path):
    big = np.full((600, 600, 4), (10, 200, 60, 255), np.uint8)
    out = _decode(thumbnail_png(_png(tmp_path, big), 320, 214))
    assert max(out.shape[:2]) <= 320
    assert (out[:, :, :3] == (10, 200, 60)).all()  # no checker bleed
