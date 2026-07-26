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


def _glyph_record(char, handle, rect, tex=0, inline=None,
                  metrics=(1.0, 1.0, 0.0, 0.0, 20.0), flag=0, kern=()):
    """One glyph-table record.  *inline* = ``(raw, w, h, fmt)`` embeds the
    atlas image (its first user introduces it); *tex* alone is a handle
    back-reference (0 = no bitmap).  *metrics* = (w, h, bearing_x,
    bearing_y, advance); *flag* bit0 = stored rotated; *kern* =
    ((right_char, adjust), ...) pair-kerning entries."""
    b = struct.pack("<HI", char, 0x80000000 | handle)
    b += _f32s(*(tuple(metrics) + (0.0, 0.0)))
    b += bytes([flag])
    b += _f32s(*rect)
    if inline is not None:
        raw, tw, th, fmt = inline
        b += struct.pack("<I", 0x80000000 | tex)
        b += struct.pack("<6I", tw, th, fmt, 0, 0, len(raw)) + raw
    else:
        b += struct.pack("<I", tex)
    b += struct.pack("<Q", len(kern))
    for kch, adj in kern:
        b += struct.pack("<Hf", kch, adj)
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
    # layout metrics + rotation flag pass through (Font Preview / Import)
    assert gs[0x41]["metrics"] == (1.0, 1.0, 0.0, 0.0, 20.0)
    assert gs[0x41]["rot"] is False
    assert gs[0x41]["kern"] == {}


def test_parse_glyph_tables_kerning(tmp_path):
    """A record tail with kerning pairs (Munsters '-' vs A/B — Peter's
    scenes-without-fonts) parses, and pair chars outside the font's char
    array reject the table (the strictness the old zeros check provided)."""
    raw, _rgba = _atlas_raw(16, 16)
    recs = [
        (0x41, _glyph_record(0x41, 3, (0.25, 0.25, 0.5, 0.5), tex=5,
                             inline=(raw, 16, 16, 5),
                             kern=((0x42, -4.0), (0x43, 2.5)))),
        (0x42, _glyph_record(0x42, 6, (0.5, 0.5, 0.75, 1.0), tex=5)),
        (0x43, _glyph_record(0x43, 7, (0.0, 0.5, 0.25, 1.0), tex=5)),
    ]
    blob = _font_blob(recs)
    tables = rad.parse_glyph_tables(blob, engine.parse_radium_images(blob))
    assert len(tables) == 1
    gs = {g["char"]: g for g in tables[0]["glyphs"]}
    assert gs[0x41]["kern"] == {0x42: -4.0, 0x43: 2.5}
    assert gs[0x42]["kern"] == {}
    # a kern pair char that is NOT in the char array -> table rejected
    bad_recs = [
        (0x41, _glyph_record(0x41, 3, (0.25, 0.25, 0.5, 0.5), tex=5,
                             inline=(raw, 16, 16, 5),
                             kern=((0x5A, -4.0),))),   # 'Z' not in table
        (0x42, _glyph_record(0x42, 6, (0.5, 0.5, 0.75, 1.0), tex=5)),
    ]
    bad = _font_blob(bad_recs)
    assert rad.parse_glyph_tables(bad, engine.parse_radium_images(bad)) == []


def test_parse_glyph_tables_rejects_corruption():
    blob, _raw, _rgba = _basic_font()
    imgs = engine.parse_radium_images(blob)
    ok = rad.parse_glyph_tables(blob, imgs)
    assert len(ok) == 1
    table_off = ok[0]["table_off"]
    # a record char that doesn't match the char array: the array-paired walk
    # drops it, but the ARRAY-LESS pass (outline-font support) legitimately
    # accepts the record run on its own terms -- records carry their own
    # ascending chars (0x21, 0x41, 0x42), so the table survives with THOSE
    bad = bytearray(blob)
    struct.pack_into("<H", bad, table_off + 8, 0x21)
    rescued = rad.parse_glyph_tables(bytes(bad),
                                     engine.parse_radium_images(bytes(bad)))
    assert [g["char"] for t in rescued for g in t["glyphs"]] == [0x21, 0x41,
                                                                0x42]
    # a nonzero byte in a record's 8-zero tail -> table dropped
    bad = bytearray(blob)
    bad[table_off + 8 + len(_glyph_record(0x20, 3, (0, 0, 0, 0))) - 1] = 1
    assert rad.parse_glyph_tables(bytes(bad),
                                  engine.parse_radium_images(bytes(bad))) == []
    # plain data has no tables
    assert rad.parse_glyph_tables(b"\x00" * 4096, []) == []


def test_parse_glyph_tables_arrayless_outline_variant():
    """Outline companion fonts (Munsters Stern_CenturyBold_Outline) have NO
    char array — [u64 N] runs straight into N records carrying their own
    ascending chars, which may start with control glyphs (0x0000, 0x000D)."""
    raw, _rgba = _atlas_raw(16, 16)
    recs = [
        _glyph_record(0x0000, 3, (0.0, 0.0, 0.0, 0.0), tex=0),
        _glyph_record(0x000D, 4, (0.0, 0.0, 0.0, 0.0), tex=0),
        _glyph_record(0x41, 5, (0.25, 0.25, 0.5, 0.5), tex=7,
                      inline=(raw, 16, 16, 5)),
    ]
    name = "OutlineFace"
    blob = b"\x7f" * 24
    blob += struct.pack("<Q", len(name)) + name.encode()
    blob += struct.pack("<Q", len(recs))
    for r in recs:
        blob += r
    blob += b"\x7f" * 8
    tables = rad.parse_glyph_tables(blob, engine.parse_radium_images(blob))
    assert len(tables) == 1
    t = tables[0]
    assert t["name"] == name
    assert [g["char"] for g in t["glyphs"]] == [0x0000, 0x000D, 0x41]
    assert t["glyphs"][2]["atlas"] is not None


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


# ---- font scope: an edit can be limited to chosen scenes ---------------------

class _FakeTwoSceneReader:
    """Two scene.radium files that embed the SAME atlas bytes (what the card
    really looks like — every scene carries its own copy), at different disk
    offsets so a write can be attributed to one scene."""

    def __init__(self, paths, data):
        self._files = [(p, {"size": len(data), "mode": 0, "flags": 0,
                            "i_block": bytes([0x40 + i]) * 8, "base": base})
                       for i, (p, base) in enumerate(paths)]
        self._data = data

    def iter_regular_files(self, min_size=1):
        for p, node in self._files:
            yield p, 0, node

    def read_file_bytes(self, node):
        return self._data

    def disk_ranges(self, node, off, length):
        return [(node["base"] + off, length)]


def _make_two_scene_glyph_extract(tmp_path):
    """The one-atlas glyph extract, but the atlas occurs in TWO scenes (one
    deduped PNG, two manifest rows)."""
    raw, rgba, data_off, gpng = _make_glyph_extract(tmp_path)
    tex = tmp_path / "images" / "scene_textures"
    row = ("scene_textures/radimg_16x16_cafe0001.png\t%s\t%d\t%d\t16\t16\t5\n")
    (tex / "radium_images.txt").write_text(
        "# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt\n"
        + row % ("/lz/a/scene.radium", data_off, len(raw))
        + row % ("/lz/b/scene.radium", data_off, len(raw)),
        encoding="utf-8")
    return raw, rgba, data_off, gpng


def test_radium_image_writes_scope_limits_edit_to_chosen_scene(tmp_path):
    """With no scope a glyph edit patches BOTH scenes; scoped to one scene it
    patches only that one, leaving the other on the stock font."""
    from pinball_decryptor.plugins.stern import fontrender as fr
    raw, _rgba, data_off, gpng = _make_two_scene_glyph_extract(tmp_path)
    baseline = read_checksums(str(tmp_path))
    reader = _FakeTwoSceneReader(
        [("/lz/a/scene.radium", 0), ("/lz/b/scene.radium", 10000)],
        b"\x7f" * data_off + raw + b"\x7f" * 8)
    tile = np.asarray(Image.open(gpng).convert("RGBA")).copy()
    tile[:] = (255, 0, 255, 255)
    Image.fromarray(tile, "RGBA").save(gpng)

    # default: every occurrence is patched
    writes, n, ov = engine._radium_image_writes(
        reader, str(tmp_path), baseline, lambda *a, **k: None, lambda: False)
    assert sorted(w[0] for w in writes) == [data_off, 10000 + data_off]
    assert n == 1 and len(ov) == 2               # both scenes' sidx refreshed

    # scoped to scene b: only its occurrence is written
    fonts = {f["key"]: f for f in fr.load_fonts(str(tmp_path))}
    fo = list(fonts.values())[0]
    fr.set_font_scope(str(tmp_path), fo, ["/lz/b/scene.radium"])
    logs = []
    writes, n, ov = engine._radium_image_writes(
        reader, str(tmp_path), baseline,
        lambda m, lv="info": logs.append(m), lambda: False)
    assert [w[0] for w in writes] == [10000 + data_off]
    assert n == 1 and len(ov) == 1
    assert any("limited to 1 scene" in m for m in logs)
    # the payload is still the real edit, just delivered to one scene
    assert (dds.decode_bc3(bytes(writes[0][1]), 16, 16)[4:12, 4:12]
            == (255, 0, 255, 255)).all()

    # clearing the scope restores the all-occurrences default
    fr.set_font_scope(str(tmp_path), fo, None)
    writes, _n, _ov = engine._radium_image_writes(
        reader, str(tmp_path), baseline, lambda *a, **k: None, lambda: False)
    assert sorted(w[0] for w in writes) == [data_off, 10000 + data_off]


def test_radium_image_writes_scope_naming_absent_scene_warns(tmp_path):
    """A scope pointing at scenes this project doesn't have writes nothing —
    and says so, instead of looking like the edit silently didn't take."""
    from pinball_decryptor.plugins.stern import fontrender as fr
    raw, _rgba, data_off, gpng = _make_two_scene_glyph_extract(tmp_path)
    baseline = read_checksums(str(tmp_path))
    reader = _FakeTwoSceneReader(
        [("/lz/a/scene.radium", 0), ("/lz/b/scene.radium", 10000)],
        b"\x7f" * data_off + raw + b"\x7f" * 8)
    tile = np.asarray(Image.open(gpng).convert("RGBA")).copy()
    tile[:] = (0, 255, 0, 255)
    Image.fromarray(tile, "RGBA").save(gpng)
    fonts = {f["key"]: f for f in fr.load_fonts(str(tmp_path))}
    fr.set_font_scope(str(tmp_path), list(fonts.values())[0],
                      ["/other/game/scene.radium"])
    logs = []
    writes, n, _ov = engine._radium_image_writes(
        reader, str(tmp_path), baseline,
        lambda m, lv="info": logs.append(m), lambda: False)
    assert writes == [] and n == 0
    assert any("aren't in this project" in m for m in logs)


# ---- extract -> font loader round trip ---------------------------------------

def test_extract_writes_metrics_and_font_loader_roundtrip(tmp_path):
    """extract_radium_images writes the metrics + table columns and the Font
    Preview loader reads them back — including a rotated slot whose atlas
    rect is the logical dims swapped."""
    raw, _rgba = _atlas_raw(16, 16)
    recs = [
        (0x41, _glyph_record(0x41, 4, (0.25, 0.25, 0.5, 0.5), tex=5,
                             inline=(raw, 16, 16, 5),
                             metrics=(4.0, 4.0, 1.0, 4.0, 6.0),
                             kern=((0x42, -1.5),))),
        (0x42, _glyph_record(0x42, 6, (0.5, 0.5, 0.75, 1.0), tex=5,
                             metrics=(8.0, 4.0, 0.0, 4.0, 9.0), flag=1)),
    ]
    reader = _FakeGlyphReader("/g/scenex/scene.radium", _font_blob(recs))
    assert engine.extract_radium_images(reader, str(tmp_path)) >= 1

    from pinball_decryptor.plugins.stern import fontrender as fr
    fonts = fr.load_fonts(str(tmp_path))
    assert len(fonts) == 1
    fo = fonts[0]
    assert fo["has_metrics"]
    A = fo["glyphs"][0x41]
    assert (A["lw"], A["lh"], A["bx"], A["by"], A["adv"]) == (4, 4, 1, 4, 6)
    assert not A["rot"]
    assert A["kern"] == {0x42: -1.5}          # survived the manifest round trip
    B = fo["glyphs"][0x42]
    assert B["rot"]
    assert (B["w"], B["h"]) == (4, 8)            # as stored in the atlas
    assert (B["lw"], B["lh"]) == (8, 4)          # upright
    img, missing = fr.render_text(fo, "AB")
    assert missing == set() and img.size[1] >= 4


# ---- GUI Source label ---------------------------------------------------------

def test_image_source_label_glyph():
    from pinball_decryptor.gui.main_window import MainWindow
    lbl = MainWindow._image_source_label
    assert lbl("images/scene_textures/glyphs/atlas_x/U+0041_A.png") == "Glyph"
    assert lbl("images/scene_textures/radimg_a_8x8_00000001.png") == "Radium"
    assert lbl("images/scene_textures/other.png") == "Scene texture"
    assert lbl("images/loose/logo.png") == "File"
