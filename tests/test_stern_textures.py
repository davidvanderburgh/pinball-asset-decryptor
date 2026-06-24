"""Tests for the Stern Spike 2 scene-texture (BC3/DXT5) extract + replace path.

Pure/deterministic pieces: the radium texture-descriptor parser, changed-texture
detection against the ``.checksums.md5`` baseline, and the encode + inode-resolve
path of ``_prepare_texture_patches`` driven by a fake ext4 reader.  No real card
needed (the full extract is exercised by the manual round-trip on bundled images).
"""

import os
import struct

import pytest

from pinball_decryptor.core.checksums import generate_checksums, read_checksums
from pinball_decryptor.plugins.stern import engine

pytest.importorskip("numpy")
PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402
import numpy as np      # noqa: E402


# ---- parse_texture_descriptor --------------------------------------------

def _radium_with(ref, w, h, fmt, handle_top=0x80):
    """Build a radium fragment: junk, then [w][h][fmt][handle][len][name]."""
    handle = struct.pack("<I", (handle_top << 24) | 0x000001)
    return (b"\x7f" * 8
            + struct.pack("<III", w, h, fmt)
            + handle
            + struct.pack("<Q", len(ref))
            + ref.encode("latin1")
            + b"\x00" * 4)


def test_parse_texture_descriptor_reads_wh_fmt():
    data = _radium_with("19.asset", 512, 512, 5)
    assert engine.parse_texture_descriptor(data, "19.asset") == (512, 512, 5)


def test_parse_texture_descriptor_non_square():
    data = _radium_with("56.asset", 400, 452, 5)
    assert engine.parse_texture_descriptor(data, "56.asset") == (400, 452, 5)


def test_parse_texture_descriptor_requires_handle_byte():
    # Without the 0x80 handle top byte the match is a stray substring -> None.
    data = _radium_with("7.asset", 256, 256, 5, handle_top=0x00)
    assert engine.parse_texture_descriptor(data, "7.asset") is None


def test_parse_texture_descriptor_missing_ref():
    assert engine.parse_texture_descriptor(b"\x00" * 64, "9.asset") is None


# ---- _changed_scene_textures: diff staged PNGs vs the Extract baseline -----

def _make_texture_extract(tmp_path, w=8, h=8):
    tex = tmp_path / "images" / "scene_textures"
    tex.mkdir(parents=True)
    Image.new("RGBA", (w, h), (1, 2, 3, 255)).save(tex / "sceneA_19.png")
    Image.new("RGBA", (w, h), (9, 9, 9, 255)).save(tex / "sceneA_20.png")
    size = w * h           # BC3 = 1 byte/pixel for 4-aligned dims
    tex.joinpath("manifest.txt").write_text(
        "# output\tcard path\tbytes\twidth\theight\tformat\n"
        f"scene_textures/sceneA_19.png\t/lz/assets/.../scene.assets/19.asset\t{size}\t{w}\t{h}\t5\n"
        f"scene_textures/sceneA_20.png\t/lz/assets/.../scene.assets/20.asset\t{size}\t{w}\t{h}\t5\n",
        encoding="utf-8")
    return tex


def test_changed_scene_textures_returns_only_edited(tmp_path):
    tex = _make_texture_extract(tmp_path)
    generate_checksums(str(tmp_path))
    baseline = read_checksums(str(tmp_path))

    Image.new("RGBA", (8, 8), (200, 0, 0, 255)).save(tex / "sceneA_19.png")

    changed = engine._changed_scene_textures(str(tmp_path), baseline)
    assert [c[0] for c in changed] == ["scene_textures/sceneA_19.png"]
    output, card_path, staged, w, h, fmt = changed[0]
    assert card_path.endswith("/scene.assets/19.asset")
    assert (w, h, fmt) == (8, 8, 5)
    assert os.path.isfile(staged)


def test_changed_scene_textures_no_manifest_is_empty(tmp_path):
    assert engine._changed_scene_textures(str(tmp_path), {}) == []


# ---- _prepare_texture_patches: encode + resolve inode ----------------------

class _FakeReader:
    def __init__(self, sizes):
        self._sizes = sizes

    def iter_regular_files(self, min_size=1):
        for path, size in self._sizes.items():
            yield path, 0, {"size": size, "mode": 0, "flags": 0, "i_block": b""}


def _prep(reader, edits):
    return engine._prepare_texture_patches(
        reader, edits, log=lambda *a, **k: None, cancel=lambda: False)


def test_prepare_texture_patches_encodes_size_neutral(tmp_path):
    staged = tmp_path / "t.png"
    Image.new("RGBA", (16, 16), (40, 130, 200, 255)).save(staged)
    card = "/lz/assets/x/scene.assets/19.asset"
    reader = _FakeReader({card: 16 * 16})          # BC3 slot = w*h bytes
    edits = [("scene_textures/t.png", card, str(staged), 16, 16, 5)]

    patches, skipped = _prep(reader, edits)
    assert skipped == 0 and len(patches) == 1
    node, payload = patches[0]
    assert len(payload) == node["size"] == 256


def test_prepare_texture_patches_rejects_dimension_mismatch(tmp_path):
    staged = tmp_path / "t.png"
    Image.new("RGBA", (32, 32), (0, 0, 0, 255)).save(staged)   # wrong size
    card = "/lz/assets/x/scene.assets/19.asset"
    reader = _FakeReader({card: 16 * 16})
    edits = [("scene_textures/t.png", card, str(staged), 16, 16, 5)]

    patches, skipped = _prep(reader, edits)
    assert patches == [] and skipped == 1


def test_prepare_texture_patches_skips_when_inode_missing(tmp_path):
    staged = tmp_path / "t.png"
    Image.new("RGBA", (16, 16), (0, 0, 0, 255)).save(staged)
    reader = _FakeReader({})                        # card path not found
    edits = [("scene_textures/t.png", "/lz/x/19.asset", str(staged), 16, 16, 5)]

    patches, skipped = _prep(reader, edits)
    assert patches == [] and skipped == 1


# ---- parse_radium_images: find DXT5 images embedded inline in a radium -------

def _embed_radium_image(tex_w, tex_h, fill=(20, 200, 90, 255), junk=8):
    """Build a radium fragment with one inline DXT5 image (the
    [dispW][dispH][handle][texW][texH][fmt=5][0][0][length][BC3 data] record)."""
    from pinball_decryptor.plugins.stern import dds
    import struct
    pw = ((tex_w + 3) // 4) * 4
    ph = ((tex_h + 3) // 4) * 4
    img = np.empty((ph, pw, 4), dtype=np.uint8)
    img[:] = fill
    raw = dds.encode_bc3(img)
    assert len(raw) == pw * ph
    blob = (b"\x7f" * junk
            + struct.pack("<II", tex_w, tex_h)          # dispW, dispH
            + struct.pack("<I", 0x80000003)             # handle
            + struct.pack("<II", tex_w, tex_h)          # texW, texH
            + struct.pack("<I", 5)                      # format = DXT5
            + struct.pack("<II", 0, 0)
            + struct.pack("<I", len(raw))               # length
            + raw)
    data_off = junk + 4 * 9
    return blob, data_off, len(raw), pw, ph


def test_parse_radium_images_finds_embedded_dxt5():
    blob, data_off, length, pw, ph = _embed_radium_image(462, 66)
    imgs = engine.parse_radium_images(blob)
    assert len(imgs) == 1
    im = imgs[0]
    assert (im["data_off"], im["length"], im["pad_w"], im["pad_h"]) == (
        data_off, length, pw, ph)
    assert (im["tex_w"], im["tex_h"]) == (462, 66)


def test_parse_radium_images_rejects_bad_length():
    # Corrupt the length so it no longer matches padded(W)*padded(H).
    blob, data_off, length, pw, ph = _embed_radium_image(16, 16)
    bad = bytearray(blob)
    import struct
    struct.pack_into("<I", bad, data_off - 4, length + 4)   # wrong length field
    assert engine.parse_radium_images(bytes(bad)) == []


def test_parse_radium_images_none_in_plain_data():
    assert engine.parse_radium_images(b"\x00" * 4096) == []


# ---- radium-image replace: diff + size-neutral in-place writes --------------

class _FakeRadiumReader:
    """Yields one scene.radium file; disk_ranges maps file offset 1:1 to disk."""
    def __init__(self, card_path, size):
        self._path = card_path
        self._size = size

    def iter_regular_files(self, min_size=1):
        yield self._path, 0, {"size": self._size, "mode": 0, "flags": 0,
                              "i_block": b""}

    def disk_ranges(self, node, off, length):
        return [(off, length)]               # identity mapping for the test


def test_changed_and_writes_radium_images_size_neutral(tmp_path):
    from pinball_decryptor.core.checksums import generate_checksums, read_checksums
    tex = tmp_path / "images" / "scene_textures"
    tex.mkdir(parents=True)
    pw, ph = 464, 68
    Image.new("RGBA", (pw, ph), (10, 20, 30, 255)).save(tex / "ea0_img01.png")
    data_off, length = 44, pw * ph
    tex.joinpath("radium_images.txt").write_text(
        "# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\n"
        f"scene_textures/ea0_img01.png\t/lz/x/scene.radium\t{data_off}\t{length}\t{pw}\t{ph}\n",
        encoding="utf-8")
    generate_checksums(str(tmp_path))
    baseline = read_checksums(str(tmp_path))

    # untouched -> no edits
    assert engine._changed_radium_images(str(tmp_path), baseline) == []

    # edit the glyph PNG
    Image.new("RGBA", (pw, ph), (240, 0, 240, 255)).save(tex / "ea0_img01.png")
    edits = engine._changed_radium_images(str(tmp_path), baseline)
    assert len(edits) == 1 and edits[0][3:7] == (data_off, length, pw, ph)

    reader = _FakeRadiumReader("/lz/x/scene.radium", size=data_off + length)
    writes, n = engine._radium_image_writes(
        reader, str(tmp_path), baseline, lambda *a, **k: None, lambda: False)
    assert n == 1
    assert sum(len(b) for _, b in writes) == length      # size-neutral
    assert writes[0][0] == data_off                      # patched at the offset


# ---- per-type Extract selection (capabilities.extract_categories) -----------

def test_category_flags_default_and_partial():
    from pinball_decryptor.plugins.stern.pipeline import _category_flags
    assert _category_flags(None) == dict(
        do_audio=True, do_video=True, do_images=True, do_text=True)
    assert _category_flags({"audio": False, "text": False}) == dict(
        do_audio=False, do_video=True, do_images=True, do_text=False)


def test_stern_advertises_extract_categories():
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    cats = dict(SternManufacturer().capabilities.extract_categories)
    assert cats == {"audio": "Audio", "video": "Video",
                    "images": "Images", "text": "Text"}


def test_make_extract_pipeline_threads_categories():
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    noop = lambda *a, **k: None
    sel = {"audio": False, "video": True, "images": True, "text": True}
    p = SternManufacturer().make_extract_pipeline(
        "in.raw", "out", noop, noop, noop, noop, extract_categories=sel)
    assert p.extract_categories == sel
