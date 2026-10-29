"""Stern S.A.M. pictures and fonts (PAD-583): reading the picture table out
of a code update, extracting every plain picture and font glyph to a PNG,
and writing edited ones back in place with the checksums moved along.

The tests build synthetic SAM images with the real layout (the code's four
table words, font table, picture table, 13- or 5-byte records in formats
0 / 12 / run-length / delta, glyph arrays); the format itself was proven
on 24 real titles and its writes in PinMAME by hand
(docs/plans/sam_compatibility.md).
"""

import os
import struct
import zlib

import numpy as np
import pytest
from PIL import Image

from pinball_decryptor.plugins.pinmame_classic import sam, sam_art, sam_sound
from pinball_decryptor.plugins.pinmame_classic.sam_games import SAM_GAME_DB
from pinball_decryptor.plugins.stern import sam_images
from pinball_decryptor.plugins.stern.pipeline import (
    SamExtractPipeline, SamRevertPipeline, SamWritePipeline)
from tests.test_stern_sam_audio import (_log, _run, _sums_ok, _tone,
                                        _write_wav, make_image)

M32 = 0xFFFFFFFF
LITERALS = 0x200             # where the code keeps the four table words
GLYPH_W, GLYPH_H = 5, 7


def _px(w, h, seed, transparent=True):
    rng = np.random.default_rng(seed)
    px = rng.integers(0, 16, (h, w)).astype(np.uint8)
    if transparent:
        px[0, 0] = sam_art.TRANSPARENT
    return px


def _record(new, ident, fmt, w, h, payload, flags=0):
    head = (struct.pack("<IIhhB", ident, flags, w, h, fmt) if new
            else struct.pack("<hhB", w, h, fmt))
    blob = head + payload
    return blob + b"\xff" * (-len(blob) % 4)


def _raw4(px):
    flat = px.reshape(-1)
    if len(flat) & 1:
        flat = np.concatenate((flat, [0]))
    out = bytearray((flat[0::2] | (flat[1::2] << 4)).astype(np.uint8))
    if px.size & 1:
        out[-1] |= 0xA0          # the spare top nibble the game ignores
    return bytes(out)


def add_art(body, at, new=True, swapped=False, glyph_stride=8):
    """Append an art area at *at* (>= len(body)) to *body* and point the
    code's four words at it.  Returns ``(body, pictures)``: ``pictures``
    maps picture number -> (fmt, pixels or None)."""
    body = bytearray(body) + b"\xff" * (at - len(body))
    pics = []                            # (record bytes, fmt, px)
    still = _px(20, 8, 1)
    pics.append((_record(new, 0x100, 0, 20, 8, still.tobytes()), 0, still))
    four = _px(9, 5, 2, transparent=False)
    pics.append((_record(new, 0x101, 12, 9, 5, _raw4(four)), 12, four))
    key = _px(16, 4, 3)
    pics.append((_record(new, 0x200, 0, 16, 4, key.tobytes(), flags=4),
                 0, key))                # a delta builds on it (new only)
    pics.append((_record(new, 0x201, 9, 16, 4, bytes([3, 1, 2, 3, 0])),
                 9, None))
    pics.append((_record(new, 0x300, 7, 16, 4, bytes([0x41, 7, 0])), 7,
                 None))
    glyphs = []
    for k in range(6):
        g = _px(GLYPH_W, GLYPH_H, 10 + k)
        glyphs.append(len(pics))
        pics.append((_record(new, 0x400 + k, 0, GLYPH_W, GLYPH_H,
                             g.tobytes()), 0, g))
    bad = _px(6, 3, 4)
    bad[1, 1] = 0x20                     # not a shade: not a plain picture
    pics.append((_record(new, 0x500, 0, 6, 3, bad.tobytes()), 0, None))
    for k in range(12):                  # an animation's run-length frames
        pics.append((_record(new, 0x600 + k, 7, 128, 32, bytes([0x41, k, 0])),
                     7, None))

    n_fonts = 2
    fonts_at = at
    table_at = fonts_at + 20 * n_fonts
    recs_at = table_at + 4 * len(pics)
    offs, blob = [], b""
    for rec, _fmt, _px_ in pics:
        offs.append(recs_at + len(blob))
        blob += rec
    arrays_at = recs_at + len(blob)
    font_glyphs = (glyphs[:4], glyphs[4:])
    arrays, spans = b"", []
    for gl in font_glyphs:
        start = arrays_at + len(arrays)
        for g in gl:
            entry = struct.pack("<Ihh", sam_sound.bank_pointer(offs[g]), 0, -1)
            arrays += entry + bytes(glyph_stride - 8)
        spans.append((start, arrays_at + len(arrays)))
    fonts = b"".join(struct.pack("<IIhhHHI", sam_sound.bank_pointer(e),
                                 sam_sound.bank_pointer(s), GLYPH_H, 1, 0, 0,
                                 1) for s, e in spans)
    table = b"".join(struct.pack("<I", sam_sound.bank_pointer(o))
                     for o in offs)
    body += fonts + table + blob + arrays
    words = [n_fonts, sam_sound.bank_pointer(fonts_at), len(pics),
             sam_sound.bank_pointer(table_at)]
    if swapped:
        words = words[2:] + words[:2]
    struct.pack_into("<4I", body, LITERALS, *words)
    plain = {}
    for i, (_rec, fmt, px) in enumerate(pics):
        if px is not None and not (new and i == 2):
            plain[i] = (fmt, px)
    return body, plain, font_glyphs


def make_art_image(new=True, swapped=False, glyph_stride=8, trailer=True):
    """A synthetic SAM image with sounds and art, its checksums right.
    Returns ``(bytes, plain pictures, font glyph lists)``."""
    snd, _pcms = make_image(trailer=False)
    body = bytearray(snd)
    body, plain, fonts = add_art(body, (len(body) + 15) & ~15, new=new,
                                 swapped=swapped, glyph_stride=glyph_stride)
    body += b"\x00" * 8 + (b"\x00" * 4 if trailer else b"")
    end1 = len(body) - (4 if trailer else 0) - 1
    base = 0x1000
    a = np.frombuffer(bytes(body), np.uint8)
    for k, (s, e) in enumerate(((0, base - 1), (base + 0x48, end1))):
        c = (~int(a[s:e + 1].sum(dtype=np.uint64))) & M32
        struct.pack_into("<3I", body, base + 12 * k, s, e, c)
    if trailer:
        n = len(body) - 4
        struct.pack_into("<I", body, n,
                         (~int(np.frombuffer(bytes(body), np.uint8, count=n)
                               .sum(dtype=np.uint64))) & M32)
    return bytes(body), plain, fonts


@pytest.fixture
def art_file(tmp_path, monkeypatch):
    """A synthetic image with art, registered as Mustang romset
    'mt_998h'."""
    data, plain, fonts = make_art_image()
    crc = zlib.crc32(data) & M32
    db = {k: dict(v) for k, v in SAM_GAME_DB.items()}
    db["mustang"]["romsets"] = dict(
        db["mustang"]["romsets"],
        mt_998h=("mt_998h.bin", crc, len(data),
                 "Mustang Limited Edition (V9.98)"))
    monkeypatch.setattr(sam, "SAM_GAME_DB", db)
    monkeypatch.setitem(sam._BY_CRC, (crc, len(data)), ("mustang", "mt_998h"))
    monkeypatch.setitem(sam._BY_SIZE, len(data), {("mustang", "mt_998h")})
    monkeypatch.setattr(sam, "MIN_BIN_SIZE", 1)
    p = tmp_path / "MT998LE.BIN"
    p.write_bytes(data)
    return str(p), data, plain, fonts


# ---------------------------------------------------------------------------
# The format
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("new,swapped,stride", [
    (True, False, 8), (True, False, 12), (False, True, 8), (False, False, 8)])
def test_read_art_finds_the_plain_pictures_and_fonts(new, swapped, stride):
    data, plain, fonts = make_art_image(new, swapped, stride)
    art = sam_art.read_art(data)
    assert art.header == (13 if new else 5)
    assert sorted(art.bitmaps) == sorted(plain)
    for n, (fmt, px) in plain.items():
        bm = art.bitmaps[n]
        assert bm.fmt == fmt
        assert (sam_art.pixels(data, bm) == px).all()
    assert [f.glyphs for f in art.fonts] == [tuple(g) for g in fonts]
    assert art.glyph_of[fonts[1][1]] == (1, 1)


def test_a_delta_frames_base_is_left_alone():
    data, _plain, _fonts = make_art_image()
    art = sam_art.read_art(data)
    # 2 is the keyframe the delta (3) patches; 3, 4 are compressed; 11 has
    # a byte that isn't a shade
    assert not {2, 3, 4, 11} & set(art.bitmaps)


def test_read_art_refuses_a_file_without_the_tables():
    data, _pcms = make_image()
    with pytest.raises(sam_art.SamArtError):
        sam_art.read_art(data)


def test_grey_alpha_round_trips_every_shade():
    px = np.array([list(range(16)) + [sam_art.TRANSPARENT]], np.uint8)
    la = sam_art.to_la(px)
    assert la[0, 15].tolist() == [255, 255] and la[0, 16, 1] == 0
    assert (sam_art.from_la(la) == px).all()
    # nearest shade; no transparency in a four-bit picture
    assert sam_art.from_la(np.array([[[25, 255], [9, 100]]],
                                    np.uint8)).tolist() == [[1, 255]]
    assert sam_art.from_la(np.array([[[9, 100]]], np.uint8),
                           transparent=False).tolist() == [[0]]


def test_replace_four_bit_keeps_the_spare_nibble():
    data, _plain, _fonts = make_art_image()
    art = sam_art.read_art(data)
    bm = art.bitmaps[1]                       # 9 x 5: an odd count
    img = bytearray(data)
    new = np.full((5, 9), 7, np.uint8)
    delta = sam_art.replace(img, bm, new)
    assert (sam_art.pixels(bytes(img), bm) == 7).all()
    last = bm.data_offset + bm.data_size - 1
    assert img[last] >> 4 == data[last] >> 4
    assert delta == sum(img) - sum(data)
    with pytest.raises(sam_art.SamArtError):
        sam_art.replace(img, bm, np.full((5, 9), 255, np.uint8))
    with pytest.raises(sam_art.SamArtError):
        sam_art.replace(img, bm, np.zeros((4, 9), np.uint8))


# ---------------------------------------------------------------------------
# Extract / Write / Revert
# ---------------------------------------------------------------------------

def _extract(path, tmp_path):
    out_dir = str(tmp_path / "proj")
    lines, log = _log()
    res = _run(SamExtractPipeline(path, out_dir, log, lambda i: None,
                                  lambda *a: None, None))
    assert res["ok"], res
    return out_dir, res, lines


def _png(out_dir, rel):
    return os.path.join(out_dir, *rel.split("/"))


def test_extract_writes_every_picture_and_glyph(art_file, tmp_path):
    path, data, plain, fonts = art_file
    out_dir, res, _lines = _extract(path, tmp_path)
    assert ("Extracted 20 SAM sound(s)" in res["msg"]
            and "2 picture(s) and 6 font glyph(s) in 2 font(s)" in res["msg"])
    still = Image.open(_png(out_dir, "images/pictures/img0000.png"))
    assert still.mode == "LA" and still.size == (20, 8)
    la = np.asarray(still)
    assert (sam_art.from_la(la) == plain[0][1]).all()
    assert la[0, 0, 1] == 0                   # transparent
    glyph = _png(out_dir, "images/fonts/font01 (7 px)/img%04d.png"
                 % fonts[1][0])
    assert Image.open(glyph).size == (GLYPH_W, GLYPH_H)
    assert os.path.isfile(_png(out_dir, "images/pictures/img0001.png"))
    assert not os.path.exists(_png(out_dir, "images/pictures/img0002.png"))
    sums = open(os.path.join(out_dir, ".checksums.md5")).read()
    assert "images/pictures/img0000.png" in sums


def test_extract_without_pictures_still_gives_the_sounds(tmp_path,
                                                         monkeypatch):
    data, _pcms = make_image()
    crc = zlib.crc32(data) & M32
    monkeypatch.setitem(sam._BY_CRC, (crc, len(data)), ("mustang", "mt_145h"))
    monkeypatch.setitem(sam._BY_SIZE, len(data), {("mustang", "mt_145h")})
    monkeypatch.setattr(sam, "MIN_BIN_SIZE", 1)
    p = tmp_path / "x.bin"
    p.write_bytes(data)
    out_dir, res, lines = _extract(str(p), tmp_path)
    assert "Extracted 20 SAM sound(s)" in res["msg"]
    assert "font glyph" not in res["msg"]
    assert any("extracting the sounds only" in x for x in lines)


def test_write_puts_the_edited_pictures_in_place(art_file, tmp_path):
    path, data, plain, fonts = art_file
    out_dir, _res, _lines = _extract(path, tmp_path)
    art = sam_art.read_art(data)
    # a colour picture of another size over the still...
    rgb = Image.new("RGB", (60, 24), (255, 255, 255))
    rgb.paste((0, 0, 0), (0, 0, 30, 24))
    rgb.save(_png(out_dir, "images/pictures/img0000.png"))
    # ...and a glyph drawn solid, at its own size
    g = fonts[0][2]
    glyph = _png(out_dir, "images/fonts/font00 (7 px)/img%04d.png" % g)
    Image.new("LA", (GLYPH_W, GLYPH_H), (136, 255)).save(glyph)
    out = str(tmp_path / "built.bin")
    lines, log = _log()
    res = _run(SamWritePipeline(path, out_dir, out, log, lambda i: None,
                                lambda *a: None, None))
    assert res["ok"], res
    assert "Wrote 2 replaced picture(s)" in res["msg"]
    built = open(out, "rb").read()
    assert len(built) == len(data)
    assert all(_sums_ok(built)) and sam_sound.has_trailer(built)
    still = sam_art.pixels(built, art.bitmaps[0])
    # (scaled down smoothly: the column at the edge goes between)
    assert (still[:, :9] == 0).all() and (still[:, 11:] == 15).all()
    assert (sam_art.pixels(built, art.bitmaps[g]) == 8).all()
    assert any("scaled from 60x24 to 20x8" in x for x in lines)
    # only those pictures' bytes and the checksums changed
    diff = {i for i in range(len(data)) if built[i] != data[i]}
    allowed = set()
    for n in (0, g):
        bm = art.bitmaps[n]
        allowed |= set(range(bm.data_offset, bm.data_offset + bm.data_size))
    allowed |= {at + 8 + k for at, *_ in sam_sound.section_table(data)
                for k in range(4)}
    allowed |= set(range(len(data) - 4, len(data)))
    assert diff and diff <= allowed


def test_write_sounds_and_pictures_together(art_file, tmp_path):
    path, data, _plain, _fonts = art_file
    out_dir, _res, _lines = _extract(path, tmp_path)
    s = sam_sound.read_bank(data).samples[2]
    _write_wav(os.path.join(out_dir, "audio", "idx0002.wav"),
               _tone(s.count, 800, s.rate), s.rate)
    Image.new("L", (9, 5), 255).save(
        _png(out_dir, "images/pictures/img0001.png"))
    out = str(tmp_path / "built.bin")
    res = _run(SamWritePipeline(path, out_dir, out, lambda *a, **k: None,
                                lambda i: None, lambda *a: None, None))
    assert res["ok"], res
    assert "Wrote 1 replaced sound(s) and 1 replaced picture(s)" in res["msg"]
    built = open(out, "rb").read()
    assert all(_sums_ok(built))
    art = sam_art.read_art(built)
    assert (sam_art.pixels(built, art.bitmaps[1]) == 15).all()


def test_write_with_nothing_changed_is_a_copy(art_file, tmp_path):
    path, data, _plain, _fonts = art_file
    out_dir, _res, _lines = _extract(path, tmp_path)
    out = str(tmp_path / "built.bin")
    res = _run(SamWritePipeline(path, out_dir, out, lambda *a, **k: None,
                                lambda i: None, lambda *a: None, None))
    assert res["ok"] and "No changed audio, pictures or animations found" in res["msg"]
    assert open(out, "rb").read() == data


def test_write_skips_a_bad_png_and_keeps_the_rest(art_file, tmp_path):
    path, data, _plain, _fonts = art_file
    out_dir, _res, _lines = _extract(path, tmp_path)
    Image.new("L", (20, 8), 0).save(
        _png(out_dir, "images/pictures/img0000.png"))
    with open(_png(out_dir, "images/pictures/img0001.png"), "wb") as f:
        f.write(b"not a png")
    Image.new("L", (4, 4), 0).save(
        _png(out_dir, "images/pictures/img0002.png"))   # the delta's base
    out = str(tmp_path / "built.bin")
    lines, log = _log()
    res = _run(SamWritePipeline(path, out_dir, out, log, lambda i: None,
                                lambda *a: None, None))
    assert res["ok"], res
    assert "Wrote 1 replaced picture(s) (2 skipped" in res["msg"]
    assert any("img0002.png: no such picture" in x for x in lines)
    built = open(out, "rb").read()
    assert all(_sums_ok(built))
    art = sam_art.read_art(data)
    assert (sam_art.pixels(built, art.bitmaps[1])
            == sam_art.pixels(data, art.bitmaps[1])).all()


def test_revert_restores_the_original_picture(art_file, tmp_path):
    path, _data, _plain, fonts = art_file
    out_dir, _res, _lines = _extract(path, tmp_path)
    rels = ["images/pictures/img0000.png",
            "images/fonts/font01 (7 px)/img%04d.png" % fonts[1][0]]
    before = [open(_png(out_dir, r), "rb").read() for r in rels]
    for r in rels:
        Image.new("L", (3, 3), 0).save(_png(out_dir, r))
    res = _run(SamRevertPipeline(path, out_dir,
                                 rels + ["images/pictures/img0777.png",
                                         "audio/idx0005.wav"],
                                 lambda *a, **k: None, lambda i: None,
                                 lambda *a: None, None))
    assert res["ok"] and "Restored 3 original file(s)" in res["msg"]
    assert "1 could not be restored" in res["msg"]
    assert [open(_png(out_dir, r), "rb").read() for r in rels] == before


def test_extract_names_a_picture_by_its_number():
    assert sam_images.parse_stem("img0042") == 42
    assert sam_images.parse_stem("logo - img12345") == 12345
    assert sam_images.parse_stem("logo") is None


# ---------------------------------------------------------------------------
# The Stern card's SAM era surface
# ---------------------------------------------------------------------------

@pytest.fixture
def stern(manufacturers_by_key):
    s = manufacturers_by_key["stern"]
    yield s
    s.set_era("")


def test_sam_era_offers_replace_images(stern, tmp_path):
    stern.set_era("sam")
    assert stern.capabilities.replace_image
    assert "16 shades" in stern.image_note()
    assert stern.image_slot_dirs(str(tmp_path)) == [
        os.path.join(str(tmp_path), "images"),
        os.path.join(str(tmp_path), "animations")]
    assert "picture" in stern.capture_basic_label
    stern.set_era("spike2")
    assert stern.image_slot_dirs(str(tmp_path)) is None
    assert stern.image_note() == ""


def test_sam_pages_leave_out_scenes_and_colors(stern):
    from types import SimpleNamespace

    from pinball_decryptor.webui.window import WebWindow
    me = SimpleNamespace(modes_preview_on=lambda mfr=None: False,
                         vpx_preview_on=lambda: False)
    stern.set_era("sam")
    gates = WebWindow._gate(me, stern)
    assert gates["Replace Images"] and gates["Replace Audio"]
    assert not gates["Scenes"] and not gates["Color Profile"]
    stern.set_era("spike2")
    gates = WebWindow._gate(me, stern)
    assert gates["Scenes"] and gates["Color Profile"]
