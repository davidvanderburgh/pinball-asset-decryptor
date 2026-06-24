"""BC3/DXT5 codec for Stern Spike 2 scene textures (pinball_decryptor.plugins.stern.dds)."""
import numpy as np
import pytest

dds = pytest.importorskip("pinball_decryptor.plugins.stern.dds")


def _checker(h, w):
    img = np.zeros((h, w, 4), dtype=np.uint8)
    yy, xx = np.mgrid[0:h, 0:w]
    img[..., 0] = (xx * 255 // max(w - 1, 1)).astype(np.uint8)
    img[..., 1] = (yy * 255 // max(h - 1, 1)).astype(np.uint8)
    img[..., 2] = (((xx // 4 + yy // 4) % 2) * 200).astype(np.uint8)
    img[..., 3] = (255 - xx * 255 // max(w - 1, 1)).astype(np.uint8)   # alpha ramp
    return img


def test_encode_is_size_neutral():
    for (h, w) in [(512, 512), (132, 132), (452, 400), (64, 64)]:
        raw = dds.encode_bc3(_checker(h, w))
        blocks = ((w + 3) // 4) * ((h + 3) // 4)
        assert len(raw) == blocks * 16            # 1 byte/pixel for aligned dims
        # decode round-trips to the same shape
        out = dds.decode_bc3(raw, w, h)
        assert out.shape == (h, w, 4)


def test_solid_colour_roundtrips_exactly():
    img = np.empty((16, 16, 4), dtype=np.uint8)
    img[:] = (40, 130, 200, 255)
    out = dds.decode_bc3(dds.encode_bc3(img), 16, 16)
    # a single colour + opaque alpha must survive BC3 quantisation within 565 step
    assert np.abs(out[..., :3].astype(int) - img[..., :3]).max() <= 8
    assert (out[..., 3] == 255).all()


def test_transparent_and_opaque_alpha_preserved():
    img = np.zeros((8, 8, 4), dtype=np.uint8)
    img[..., 3] = 0                       # fully transparent left half
    img[:, 4:, 3] = 255                   # fully opaque right half
    img[..., :3] = 100
    out = dds.decode_bc3(dds.encode_bc3(img), 8, 8)
    assert (out[:, :4, 3] == 0).all()
    assert (out[:, 4:, 3] == 255).all()


def test_roundtrip_gradient_low_error():
    img = _checker(64, 64)
    out = dds.decode_bc3(dds.encode_bc3(img), 64, 64)
    rgb_err = np.abs(out[..., :3].astype(int) - img[..., :3]).mean()
    a_err = np.abs(out[..., 3].astype(int) - img[..., 3]).mean()
    assert rgb_err < 6.0
    assert a_err < 3.0


def test_non_multiple_of_four_dims():
    # 30x18 -> padded to 32x20 internally; output cropped back to 30x18
    img = _checker(18, 30)
    raw = dds.encode_bc3(img)
    assert len(raw) == (8 * 5) * 16
    out = dds.decode_bc3(raw, 30, 18)
    assert out.shape == (18, 30, 4)


def test_dds_wrap_unwrap_roundtrip():
    raw = dds.encode_bc3(_checker(132, 132))
    blob = dds.to_dds(raw, 132, 132)
    assert blob[:4] == b"DDS " and len(blob) == 128 + len(raw)
    back, w, h, fourcc = dds.from_dds(blob)
    assert (w, h, fourcc) == (132, 132, b"DXT5")
    assert back == raw


def test_from_dds_rejects_non_dxt5():
    bad = dds.dds_header(64, 64, 4096, fourcc=b"DXT1") + b"\x00" * 4096
    with pytest.raises(ValueError):
        dds.from_dds(bad)


def test_decode_rejects_short_data():
    with pytest.raises(ValueError):
        dds.decode_bc3(b"\x00" * 16, 512, 512)


# --------------------------------------------------------------------------
# BC1 / DXT1 (fmt == 4): 8 bytes / 4×4 block, half of BC3
# --------------------------------------------------------------------------

def test_bc1_encode_is_size_neutral():
    for (h, w) in [(512, 512), (132, 132), (452, 400), (64, 64)]:
        rgba = _checker(h, w)
        rgba[..., 3] = 255                         # opaque -> 4-colour mode
        raw = dds.encode_bc1(rgba)
        blocks = ((w + 3) // 4) * ((h + 3) // 4)
        assert len(raw) == blocks * 8              # half a byte/pixel for aligned dims
        out = dds.decode_bc1(raw, w, h)
        assert out.shape == (h, w, 4)


def test_bc1_solid_colour_roundtrips_exactly():
    img = np.empty((16, 16, 4), dtype=np.uint8)
    img[:] = (40, 130, 200, 255)
    out = dds.decode_bc1(dds.encode_bc1(img), 16, 16)
    assert np.abs(out[..., :3].astype(int) - img[..., :3]).max() <= 8
    assert (out[..., 3] == 255).all()


def test_bc1_punch_through_alpha():
    # 3-colour mode: transparent texels survive as index 3 (alpha 0).
    img = np.zeros((8, 8, 4), dtype=np.uint8)
    img[..., :3] = 100
    img[..., 3] = 0                                # transparent left half
    img[:, 4:, 3] = 255                            # opaque right half
    out = dds.decode_bc1(dds.encode_bc1(img), 8, 8)
    assert (out[:, :4, 3] == 0).all()
    assert (out[:, 4:, 3] == 255).all()


def test_bc1_opaque_block_has_no_transparent_texels():
    # A fully-opaque, multi-colour block must use 4-colour mode (no false
    # transparency from index 3).
    img = _checker(16, 16)
    img[..., 3] = 255
    out = dds.decode_bc1(dds.encode_bc1(img), 16, 16)
    assert (out[..., 3] == 255).all()


def test_bc1_roundtrip_gradient_low_error():
    img = _checker(64, 64)
    img[..., 3] = 255                              # BC1 colour fidelity only
    out = dds.decode_bc1(dds.encode_bc1(img), 64, 64)
    rgb_err = np.abs(out[..., :3].astype(int) - img[..., :3]).mean()
    assert rgb_err < 6.0


def test_bc1_non_multiple_of_four_dims():
    img = _checker(18, 30)
    img[..., 3] = 255
    raw = dds.encode_bc1(img)
    assert len(raw) == (8 * 5) * 8                 # ceil(30/4)*ceil(18/4)*8
    out = dds.decode_bc1(raw, 30, 18)
    assert out.shape == (18, 30, 4)


def test_bc1_decode_rejects_short_data():
    with pytest.raises(ValueError):
        dds.decode_bc1(b"\x00" * 8, 512, 512)
