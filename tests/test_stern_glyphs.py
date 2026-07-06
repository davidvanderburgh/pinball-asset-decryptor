"""Tests for the Stern Spike 2 font glyph-atlas slicer.

Pure/deterministic pieces on synthetic radium blobs: the glyph-table parser
(``radium.parse_glyph_tables``) with inline / back-referenced / absent atlas
textures, the pixel-rect helper, changed-glyph detection + atlas compositing
against the ``.checksums.md5`` baseline, and the surgical BC-block splice of
``_radium_image_writes`` (an edited glyph must leave every other character's
blocks bit-identical to stock).  The full extract + Write round-trip on a real
card is scratchpad-verified (turtles: 11k glyphs, 152 atlases, paste-back
identical, one-glyph edit confined to its blocks).
"""

import os
import struct

import pytest

from pinball_decryptor.core.checksums import generate_checksums, read_checksums
from pinball_decryptor.plugins.stern import engine
from pinball_decryptor.plugins.stern import radium as rad

pytest.importorskip("numpy")
PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402
import numpy as np      # noqa: E402

from pinball_decryptor.plugins.stern import dds  # noqa: E402


# ---- synthetic radium builder ----------------------------------------------

def _f32s(*vals):
    return struct.pack("<%df" % len(vals), *vals)


def _atlas_raw(w=16, h=16):
    """Deterministic BC3 atlas block data + its decoded RGBA (the extract
    writes the decode as the atlas PNG, so tests must do the same)."""
    grad = np.zeros((h, w, 4), np.uint8)
    grad[:, :, 0] = np.arange(w, dtype=np.uint8)[None, :] * 15
    grad[:, :, 1] = np.arange(h, dtype=np.uint8)[:, None] * 15
    grad[:, :, 3] = 255
    raw = dds.encode_bc3(grad)
    return raw, dds.decode_bc3(raw, w, h)


def _glyph_record(char, handle, rect, tex=0, inline=None):
    """One glyph-table record.  *inline* = ``(raw, w, h, fmt)`` embeds the
    atlas image (its first user introduces it); *tex* alone is a handle
    back-reference (0 = no bitmap)."""
    b = struct.pack("<HI", char, 0x80000000 | handle)
    b += _f32s(1.0, 1.0, 0.0, 0.0, 20.0, 0.0, 0.0)     # metrics (unused)
    b += b"\x00"                                        # flag byte
    b += _f32s(*rect)
    if inline is not None:
        raw, tw, th, fmt = inline
        b += struct.pack("<I", 0x80000000 | tex)
        b += struct.pack("<6I", tw, th, fmt, 0, 0, len(raw)) + raw
    else:
        b += struct.pack("<I", tex)
    b += b"\x00" * 8
    return b


def _font_blob(records, chars=None, name="TestFontFace", junk=24):
    """A radium fragment: junk, name string, char array, header filler, then
    the glyph table -- the layout ``parse_glyph_tables`` anchors on."""
    chars = chars or [c for c, _r in records]
    blob = b"\x7f" * junk
    blob += struct.pack("<Q", len(name)) + name.encode()
    blob += struct.pack("<Q", len(chars))
    blob += struct.pack("<%dH" % len(chars), *chars)
    blob += b"\x11" * 13                    # variable font-header stand-in
    blob += struct.pack("<Q", len(records))
    for _c, r in records:
        blob += r
    blob += b"\x7f" * 8
    return blob


def _basic_font(w=16, h=16):
    """Three glyphs: space (no bitmap), 'A' (introduces the atlas inline),
    'B' (back-references it)."""
    raw, rgba = _atlas_raw(w, h)
    recs = [
        (0x20, _glyph_record(0x20, 3, (0.0, 0.0, 0.0, 0.0), tex=0)),
        (0x41, _glyph_record(0x41, 4, (0.25, 0.25, 0.5, 0.5), tex=5,
                             inline=(raw, w, h, 5))),
        (0x42, _glyph_record(0x42, 6, (0.5, 0.5, 0.75, 1.0), tex=5)),
    ]
    return _font_blob(recs), raw, rgba


# ---- parse_glyph_tables ------------------------------------------------------

def test_parse_glyph_tables_inline_backref_and_none():
    blob, raw, _rgba = _basic_font()
    imgs = engine.parse_radium_images(blob)
    assert len(imgs) == 1                        # the inline atlas
    tables = rad.parse_glyph_tables(blob, imgs)
    assert len(tables) == 1
    t = tables[0]
    assert t["name"] == "TestFontFace"
    gs = {g["char"]: g for g in t["glyphs"]}
    assert set(gs) == {0x20, 0x41, 0x42}
    assert gs[0x20]["atlas"] is None             # no bitmap
    assert gs[0x41]["atlas"] is imgs[0]          # inline introduction
    assert gs[0x42]["atlas"] is imgs[0]          # back-reference resolved
    assert gs[0x41]["rect"] == (0.25, 0.25, 0.5, 0.5)


def test_parse_glyph_tables_rejects_corruption():
    blob, _raw, _rgba = _basic_font()
    imgs = engine.parse_radium_images(blob)
    ok = rad.parse_glyph_tables(blob, imgs)
    assert len(ok) == 1
    table_off = ok[0]["table_off"]
    # a record char that doesn't match the char array -> table dropped
    bad = bytearray(blob)
    struct.pack_into("<H", bad, table_off + 8, 0x21)
    assert rad.parse_glyph_tables(bytes(bad),
                                  engine.parse_radium_images(bytes(bad))) == []
    # a nonzero byte in a record's 8-zero tail -> table dropped
    bad = bytearray(blob)
    bad[table_off + 8 + len(_glyph_record(0x20, 3, (0, 0, 0, 0))) - 1] = 1
    assert rad.parse_glyph_tables(bytes(bad),
                                  engine.parse_radium_images(bytes(bad))) == []
    # plain data has no tables
    assert rad.parse_glyph_tables(b"\x00" * 4096, []) == []


def test_glyph_px_rect():
    atlas = dict(tex_w=512, tex_h=512, data_off=0, length=0, fmt=5,
                 pad_w=512, pad_h=512)
    g = {"rect": (1 / 512, 4 / 512, 14 / 512, 48 / 512), "atlas": atlas}
    assert rad.glyph_px_rect(g) == (1, 4, 13, 44)
    assert rad.glyph_px_rect({"rect": (0, 0, 0.5, 0.5), "atlas": None}) is None
    # zero-area rect (the 1x1 blank space pixel rounds to nothing at 0 width)
    g = {"rect": (0.5, 0.5, 0.5, 0.5), "atlas": atlas}
    assert rad.glyph_px_rect(g) is None


def test_glyph_png_name():
    assert engine._glyph_png_name(0x41) == "U+0041_A.png"
    assert engine._glyph_png_name(0x61) == "U+0061_a.png"   # distinct from 'A'
    assert engine._glyph_png_name(0x2F) == "U+002F.png"     # '/' unsafe
    assert engine._glyph_png_name(0x2122) == "U+2122.png"   # ™


# ---- _splice_changed_blocks: surgical BC-block patching ---------------------

def test_splice_changed_blocks_only_touched_block_differs():
    raw, rgba = _atlas_raw(16, 8)
    target = rgba.copy()
    target[4:8, 4:8] = (255, 0, 0, 255)          # block (1, 1)
    out = engine._splice_changed_blocks(raw, target, 16, 8, 5)
    assert len(out) == len(raw)
    nbx, bs = 4, 16
    for blk in range(len(raw) // bs):
        same = out[blk * bs:(blk + 1) * bs] == raw[blk * bs:(blk + 1) * bs]
        assert same == (blk != 1 * nbx + 1)      # only block (1,1) changed
    # the patched block decodes to the edit
    dec = dds.decode_bc3(out, 16, 8)
    assert (dec[4:8, 4:8] == (255, 0, 0, 255)).all()
    assert np.array_equal(dec[:4], rgba[:4])     # untouched rows bit-exact


def test_splice_changed_blocks_no_diff_returns_raw():
    raw, rgba = _atlas_raw(16, 8)
    assert engine._splice_changed_blocks(raw, rgba.copy(), 16, 8, 5) is raw


# ---- changed-glyph detection + atlas compositing -----------------------------

def _make_glyph_extract(tmp_path, w=16, h=16):
    """An extract with one atlas PNG, one glyph slice of it (rect 4,4 8x8),
    both manifests, and a checksum baseline."""
    raw, rgba = _atlas_raw(w, h)
    tex = tmp_path / "images" / "scene_textures"
    gdir = tex / "glyphs" / "radimg_16x16_cafe0001"
    gdir.mkdir(parents=True)
    Image.fromarray(rgba, "RGBA").save(tex / "radimg_16x16_cafe0001.png")
    Image.fromarray(rgba[4:12, 4:12], "RGBA").save(gdir / "U+0041_A.png")
    data_off = 32
    (tex / "radium_images.txt").write_text(
        "# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt\n"
        "scene_textures/radimg_16x16_cafe0001.png\t/lz/x/scene.radium\t"
        "%d\t%d\t%d\t%d\t5\n" % (data_off, len(raw), w, h),
        encoding="utf-8")
    (tex / "glyph_images.txt").write_text(
        "# glyph output\tatlas output\tchar\tx\ty\tw\th\tfont\n"
        "scene_textures/glyphs/radimg_16x16_cafe0001/U+0041_A.png\t"
        "scene_textures/radimg_16x16_cafe0001.png\t0x0041\t4\t4\t8\t8\tFace\n",
        encoding="utf-8")
    generate_checksums(str(tmp_path))
    return raw, rgba, data_off, gdir / "U+0041_A.png"


def test_changed_glyph_images_and_overrides(tmp_path):
    raw, rgba, _off, gpng = _make_glyph_extract(tmp_path)
    baseline = read_checksums(str(tmp_path))
    logs = []
    log = lambda m, lv="info": logs.append(m)

    # untouched -> nothing
    assert engine._changed_glyph_images(str(tmp_path), baseline) == {}
    assert engine._glyph_atlas_overrides(str(tmp_path), baseline, log) == {}

    # edit the slice -> its atlas gets a composited override
    tile = np.asarray(Image.open(gpng).convert("RGBA")).copy()
    tile[:] = (0, 255, 0, 255)
    Image.fromarray(tile, "RGBA").save(gpng)
    per = engine._changed_glyph_images(str(tmp_path), baseline)
    assert list(per) == ["scene_textures/radimg_16x16_cafe0001.png"]
    ov = engine._glyph_atlas_overrides(str(tmp_path), baseline, log)
    got = np.asarray(list(ov.values())[0])
    assert (got[4:12, 4:12] == (0, 255, 0, 255)).all()
    assert np.array_equal(got[:4], rgba[:4])     # rest of the atlas untouched

    # a wrong-size replacement slice is auto-scaled to its rect
    Image.new("RGBA", (16, 16), (0, 0, 255, 255)).save(gpng)
    ov = engine._glyph_atlas_overrides(str(tmp_path), baseline, log)
    got = np.asarray(list(ov.values())[0])
    assert (got[4:12, 4:12] == (0, 0, 255, 255)).all()
    assert any("scaling" in m for m in logs)


# ---- _radium_image_writes: glyph edits splice into stock atlas bytes ---------

class _FakeGlyphReader:
    """One scene.radium whose bytes hold the stock atlas at *data_off*;
    disk_ranges maps file offsets 1:1."""

    def __init__(self, card_path, data):
        self._path = card_path
        self._data = data

    def iter_regular_files(self, min_size=1):
        yield self._path, 0, {"size": len(self._data), "mode": 0, "flags": 0,
                              "i_block": b"\x42" * 8}

    def read_file_bytes(self, node):
        return self._data

    def disk_ranges(self, node, off, length):
        return [(off, length)]


def test_radium_image_writes_glyph_edit_splices_blocks(tmp_path):
    raw, rgba, data_off, gpng = _make_glyph_extract(tmp_path)
    baseline = read_checksums(str(tmp_path))
    reader = _FakeGlyphReader("/lz/x/scene.radium",
                              b"\x7f" * data_off + raw + b"\x7f" * 8)

    # untouched extract -> no writes at all
    writes, n, ov = engine._radium_image_writes(
        reader, str(tmp_path), baseline, lambda *a, **k: None, lambda: False)
    assert writes == [] and n == 0

    # edit one glyph slice (blocks (1,1)..(2,2) of the 4x4 block grid)
    tile = np.asarray(Image.open(gpng).convert("RGBA")).copy()
    tile[:] = (255, 0, 255, 255)
    Image.fromarray(tile, "RGBA").save(gpng)
    writes, n, ov = engine._radium_image_writes(
        reader, str(tmp_path), baseline, lambda *a, **k: None, lambda: False)
    assert n == 1
    assert [w[0] for w in writes] == [data_off]
    payload = writes[0][1]
    assert len(payload) == len(raw)              # size-neutral
    # byte-level: only the glyph's four BC blocks differ from stock
    changed = {blk for blk in range(len(raw) // 16)
               if payload[blk * 16:(blk + 1) * 16] != raw[blk * 16:(blk + 1) * 16]}
    assert changed == {5, 6, 9, 10}              # blocks (1,1) (2,1) (1,2) (2,2)
    # pixel-level: the edit landed, everything else identical
    dec = dds.decode_bc3(bytes(payload), 16, 16)
    assert (dec[4:12, 4:12] == (255, 0, 255, 255)).all()
    assert np.array_equal(dec[:4], rgba[:4])
    assert np.array_equal(dec[12:], rgba[12:])
    # the sidx overlay carries the same payload for the radium inode
    (node, fileov), = ov.values()
    assert fileov == {data_off: payload}


def test_radium_image_writes_atlas_and_glyph_edit_uses_full_reencode(tmp_path):
    """When the atlas PNG itself was edited too, the whole composited atlas is
    re-encoded (the stock-splice shortcut only applies to glyph-only edits)."""
    raw, rgba, data_off, gpng = _make_glyph_extract(tmp_path)
    baseline = read_checksums(str(tmp_path))
    reader = _FakeGlyphReader("/lz/x/scene.radium",
                              b"\x7f" * data_off + raw + b"\x7f" * 8)
    atlas_png = (tmp_path / "images" / "scene_textures"
                 / "radimg_16x16_cafe0001.png")
    edited = rgba.copy()
    edited[0:4, 0:4] = (9, 9, 9, 255)
    Image.fromarray(edited, "RGBA").save(atlas_png)
    tile = np.asarray(Image.open(gpng).convert("RGBA")).copy()
    tile[:] = (255, 255, 0, 255)
    Image.fromarray(tile, "RGBA").save(gpng)

    writes, n, _ov = engine._radium_image_writes(
        reader, str(tmp_path), baseline, lambda *a, **k: None, lambda: False)
    assert n == 1
    dec = dds.decode_bc3(bytes(writes[0][1]), 16, 16)
    assert (dec[4:12, 4:12] == (255, 255, 0, 255)).all()   # glyph pasted
    assert (dec[0:4, 0:4, 0] < 32).all()                   # atlas edit kept


# ---- GUI Source label ---------------------------------------------------------

def test_image_source_label_glyph():
    from pinball_decryptor.gui.main_window import MainWindow
    lbl = MainWindow._image_source_label
    assert lbl("images/scene_textures/glyphs/atlas_x/U+0041_A.png") == "Glyph"
    assert lbl("images/scene_textures/radimg_a_8x8_00000001.png") == "Radium"
    assert lbl("images/scene_textures/other.png") == "Scene texture"
    assert lbl("images/loose/logo.png") == "File"
