"""PAD-154: a scene picture that keeps its OWN size.

A name banner embedded in a ``scene.radium`` used to be squeezed into the
stock picture's pixels ("SpaceGodzilla is replacing Ebirah ... a 3 char name
156x70 PNG vs a 7 char 428x72 png file").  Now:

* :func:`radium_grow.regrow` re-serialises the image record at the new size
  and repoints every sprite instance that names it by its
  ``[dispW][dispH][handle]`` triple, and the repo's parsers agree the result
  is the stock scene shifted;
* ``engine._radium_image_writes`` routes a replacement of a different size to
  that growth (never a font atlas, never a picture nothing draws by size, never
  a direct-SD write), pads a texture-size PNG in place, and the Write ships the
  grown scene whole with its ``.sidx`` size refreshed;
* the Replace Images staging keeps a picture's own size when asked.

Verified in the PC emulator on Godzilla Pro 1.15: the language screen's
Japanese date picture grown from 404 to 700 pixels loaded and drew at its new
width, same scale and same top-left corner.
"""
import hashlib
import hmac
import struct

import pytest

np = pytest.importorskip("numpy")
from PIL import Image                                               # noqa: E402

from pinball_decryptor.core import image_slots                      # noqa: E402
from pinball_decryptor.core.checksums import (                      # noqa: E402
    generate_checksums, read_checksums)
from pinball_decryptor.plugins.stern import (                       # noqa: E402
    dds, engine, radium, radium_grow, scene_layout, sidx)
from tests.test_stern_scene_render import (                         # noqa: E402
    _image_ref, _s_instance, _sprite_scene)
from tests.test_stern_text_grow import (                            # noqa: E402
    RAD_PATH, _capture, _card, _CardReader, _compute, _grow_elf, _sidx_record,
    _writes_in)
from tests.test_stern_valpatch import _stub_sidx                    # noqa: E402


def _pixels(w, h, rgba):
    pw, ph = ((w + 3) // 4) * 4, ((h + 3) // 4) * 4
    arr = np.empty((ph, pw, 4), dtype=np.uint8)
    arr[:] = rgba
    return arr


def _record(w, h, handle, rgba=(20, 200, 90, 255), disp=None):
    """One inline BC3 image record: ``[dispW][dispH][handle][texW][texH][fmt]
    [0][0][len][block data]``."""
    raw = dds.encode_bc3(_pixels(w, h, rgba))
    dw, dh = disp or (w, h)
    return (struct.pack("<3I", dw, dh, 0x80000000 | handle)
            + struct.pack("<3I", w, h, 5) + struct.pack("<2I", 0, 0)
            + struct.pack("<I", len(raw)) + raw)


BANNER, ICON = (40, 20, 2, (38, 18)), (16, 16, 4, None)


def _scene():
    """A 40x20 banner (displayed 38x18) drawn by two instances and a 16x16
    icon drawn by one, each naming its picture by triple.  Returns
    ``(bytes, banner_off, icon_off)``."""
    head = bytearray(b"\x7f" * 8)
    head += _record(BANNER[0], BANNER[1], BANNER[2], disp=BANNER[3])
    banner_off = 8 + radium_grow.IMAGE_HEADER_LEN
    head += b"\x7f" * 4
    icon_off = len(head) + radium_grow.IMAGE_HEADER_LEN
    head += _record(ICON[0], ICON[1], ICON[2], rgba=(200, 30, 30, 255))
    tail = _sprite_scene([])
    tail += _s_instance("Banner", 100.0, 50.0, image_ref=_image_ref(38, 18, 2))
    tail += _s_instance("Icon", 300.0, 60.0, image_ref=_image_ref(16, 16, 4))
    tail += _s_instance("BannerAgain", 100.0, 400.0,
                        image_ref=_image_ref(38, 18, 2))
    return bytes(head) + tail, banner_off, icon_off


def _layout(data):
    imgs = engine.parse_radium_images(data)
    return scene_layout.parse_scene_layout(
        data, imgs, radium.parse_glyph_tables(data, imgs))


# ---------------------------------------------------------------------------
# radium_grow.regrow
# ---------------------------------------------------------------------------

def test_the_fixture_places_both_banner_instances():
    data, banner, icon = _scene()
    got = {s["name"]: s["image_off"] for s in _layout(data)["sprites"]}
    assert got == {"Banner": banner, "Icon": icon, "BannerAgain": banner}
    assert len(radium_grow.image_refs(data, banner)) == 2


def test_regrow_resizes_the_picture_and_every_sprite_follows():
    data, banner, icon = _scene()
    payload = dds.encode_bc3(_pixels(90, 22, (255, 0, 255, 255)))
    r = radium_grow.regrow(data, images={banner: (90, 22, payload)})
    new, shift = r["data"], r["shift"]
    assert r["images"] == {banner: 2} and r["texts"] == {}
    assert len(new) == len(data) + len(payload) - 40 * 20
    imgs = {i["data_off"]: i for i in engine.parse_radium_images(new)}
    grown = imgs[shift(banner)]
    assert (grown["tex_w"], grown["tex_h"], grown["disp_w"], grown["disp_h"],
            grown["length"]) == (90, 22, 90, 22, len(payload))
    assert (imgs[shift(icon)]["tex_w"], imgs[shift(icon)]["length"]) == \
        (16, 16 * 16)
    decoded = dds.decode_bc3(new[shift(banner):shift(banner) + len(payload)],
                             92, 24)
    assert (decoded[:22, :90] == (255, 0, 255, 255)).all()
    got = {s["name"]: s["image_off"] for s in _layout(new)["sprites"]}
    assert got == {"Banner": shift(banner), "Icon": shift(icon),
                   "BannerAgain": shift(banner)}
    bad, _stats = radium_grow.agree(data, new, {}, shift,
                                    images={banner: (90, 22)})
    assert bad == []


def test_agree_notices_a_sprite_that_did_not_follow():
    """The check is not vacuous: undo one repointed triple and it fails."""
    data, banner, _icon = _scene()
    payload = dds.encode_bc3(_pixels(90, 22, (255, 0, 255, 255)))
    r = radium_grow.regrow(data, images={banner: (90, 22, payload)})
    broken = bytearray(r["data"])
    ref = r["data"].find(struct.pack("<3I", 90, 22, 2),
                         r["shift"](banner) + len(payload))
    struct.pack_into("<2I", broken, ref, 38, 18)
    bad, _stats = radium_grow.agree(data, bytes(broken), {}, r["shift"],
                                    images={banner: (90, 22)})
    assert bad


def test_regrow_refuses_a_wrong_payload_or_an_unknown_offset():
    data, banner, _icon = _scene()
    with pytest.raises(ValueError, match="bytes of block data"):
        radium_grow.regrow(data, images={banner: (90, 22, b"\x00" * 16)})
    with pytest.raises(ValueError, match="no embedded image"):
        radium_grow.regrow(data, images={banner + 4: (4, 4, b"\x00" * 16)})


def test_image_refs_ignore_a_lookalike_inside_pixel_data():
    data, banner, icon = _scene()
    fake = bytearray(data)
    struct.pack_into("<3I", fake, icon + 16, 38, 18, 2)   # inside the icon
    assert engine.parse_radium_images(bytes(fake))       # still parses
    assert radium_grow.image_refs(bytes(fake), banner) == \
        radium_grow.image_refs(data, banner)


def test_grow_keeps_its_text_only_signature():
    from tests.test_stern_radium import _make_radium
    buf = _make_radium("REPLAY", 2)
    new, occ, shift = radium_grow.grow(buf, {"REPLAY": "EXTRA BALL LIT"})
    assert occ == {"REPLAY": 2} and callable(shift)
    assert new == radium_grow.regrow(buf, texts={"REPLAY": "EXTRA BALL LIT"})[
        "data"]


# ---------------------------------------------------------------------------
# engine._radium_image_writes
# ---------------------------------------------------------------------------

class _Reader:
    def __init__(self, card_path, data):
        self._path, self._data = card_path, data

    def iter_regular_files(self, min_size=1, max_depth=None):
        yield self._path, 0, {"size": len(self._data), "mode": 0, "flags": 0,
                              "i_block": b"\x42" * 8}

    def read_file_bytes(self, node):
        return self._data

    def disk_ranges(self, node, off, length):
        return [(off, length)]


def _project(tmp_path, data, off, w, h, card=RAD_PATH, name="banner"):
    """A project with the picture at *off* extracted (its padded grid) and
    baselined."""
    pw, ph = ((w + 3) // 4) * 4, ((h + 3) // 4) * 4
    rel = "scene_textures/radimg_%s_%dx%d_cafe0001.png" % (name, w, h)
    tex = tmp_path / "images" / "scene_textures"
    tex.mkdir(parents=True, exist_ok=True)
    Image.fromarray(dds.decode_bc3(data[off:off + pw * ph], pw, ph),
                    "RGBA").save(tmp_path / "images" / rel)
    (tex / "radium_images.txt").write_text(
        "# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt\n"
        "%s\t%s\t%d\t%d\t%d\t%d\t5\n" % (rel, card, off, pw * ph, pw, ph),
        encoding="utf-8")
    generate_checksums(str(tmp_path))
    return tmp_path / "images" / rel


def _writes(tmp_path, reader, grow=True, **kw):
    msgs, log = _capture()
    grown = {}
    writes, n, ov = engine._radium_image_writes(
        reader, str(tmp_path), read_checksums(str(tmp_path)), log,
        lambda: False, grow_dir=str(tmp_path) if grow else None,
        grown=grown, **kw)
    return writes, n, ov, grown, msgs


def test_a_bigger_replacement_goes_to_growth(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "_image_grow_gate", lambda d: (True, ""))
    data, banner, _icon = _scene()
    png = _project(tmp_path, data, banner, 40, 20)
    Image.new("RGBA", (90, 22), (255, 0, 255, 255)).save(png)
    writes, n, ov, grown, msgs = _writes(tmp_path, _Reader(RAD_PATH, data))
    assert writes == [] and ov == {} and n == 1
    (node, imgs), = grown.values()
    w, h, payload = imgs[banner]
    assert (w, h) == (90, 22)
    assert len(payload) == radium_grow.image_block_len(90, 22, 5)
    assert any("re-serialised around its new size" in m for _l, m in msgs)


def test_without_growth_it_is_the_old_skip(tmp_path):
    data, banner, _icon = _scene()
    png = _project(tmp_path, data, banner, 40, 20)
    Image.new("RGBA", (90, 22), (255, 0, 255, 255)).save(png)
    writes, n, _ov, grown, msgs = _writes(tmp_path, _Reader(RAD_PATH, data),
                                          grow=False)
    assert writes == [] and n == 0 and grown == {}
    assert any(l == "warning" and "must stay 40x20" in m for l, m in msgs)


@pytest.mark.parametrize("why, gate, patch", [
    ("direct-SD", (False, "a direct-SD write can't change a scene's size"),
     None),
    ("nothing in its scene draws it", (True, ""), "unref"),
])
def test_a_resize_that_cannot_land_says_why(tmp_path, monkeypatch, why, gate,
                                            patch):
    monkeypatch.setattr(engine, "_image_grow_gate", lambda d: gate)
    data, banner, _icon = _scene()
    if patch == "unref":
        buf = bytearray(data)
        for ref in radium_grow.image_refs(data, banner):
            struct.pack_into("<I", buf, ref, 999)
        data = bytes(buf)
    png = _project(tmp_path, data, banner, 40, 20)
    Image.new("RGBA", (90, 22), (255, 0, 255, 255)).save(png)
    writes, n, _ov, grown, msgs = _writes(tmp_path, _Reader(RAD_PATH, data))
    assert writes == [] and n == 0 and grown == {}
    assert any(l == "warning" and why in m for l, m in msgs)


def test_a_font_atlas_never_changes_size(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "_image_grow_gate", lambda d: (True, ""))
    data, banner, _icon = _scene()
    png = _project(tmp_path, data, banner, 40, 20)
    Image.new("RGBA", (90, 22), (255, 0, 255, 255)).save(png)
    monkeypatch.setattr(
        radium, "parse_glyph_tables",
        lambda d, imgs: [{"glyphs": [{"atlas": {"data_off": banner}}]}])
    _w, n, _ov, grown, msgs = _writes(tmp_path, _Reader(RAD_PATH, data))
    assert n == 0 and grown == {}
    assert any("font atlas" in m for _l, m in msgs)


def test_a_texture_size_png_is_padded_and_patched_in_place(tmp_path,
                                                           monkeypatch):
    """A 38x18 picture shares the stock 40x20 block grid: no growth at all."""
    def boom(d):
        raise AssertionError("the growth gate must not be asked")
    monkeypatch.setattr(engine, "_image_grow_gate", boom)
    data, banner, _icon = _scene()
    png = _project(tmp_path, data, banner, 40, 20)
    Image.new("RGBA", (38, 18), (0, 0, 255, 255)).save(png)
    writes, n, ov, grown, _msgs = _writes(tmp_path, _Reader(RAD_PATH, data))
    assert n == 1 and grown == {}
    assert [w[0] for w in writes] == [banner]
    dec = dds.decode_bc3(writes[0][1], 40, 20)
    assert (dec[:18, :38] == (0, 0, 255, 255)).all()
    assert (dec[18:, :, 3] == 0).all() and (dec[:, 38:, 3] == 0).all()


# ---------------------------------------------------------------------------
# premultiplied alpha: how the game blends scene pictures
# ---------------------------------------------------------------------------

def _straight_text(w, h):
    """What an image editor saves: white "ink" with soft edges, and a
    transparent background whose colour is white, not black."""
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[..., :3] = 255
    arr[:, : w // 2, 3] = 255
    arr[:, w // 2: w // 2 + 4, 3] = 96          # anti-aliased edge
    return arr


def _is_premultiplied(arr, tol=16):
    return bool((arr[..., :3].max(axis=2).astype(int)
                 <= arr[..., 3].astype(int) + tol).all())


def test_premultiply_only_where_slot_and_picture_call_for_it():
    stock = np.zeros((20, 40, 4), dtype=np.uint8)
    stock[..., :3] = 90
    stock[..., 3] = 255                         # premultiplied (opaque)
    straight = _straight_text(40, 20)
    out, changed = engine._premultiply_like_stock(straight, stock)
    assert changed and _is_premultiplied(out, tol=0)
    assert (out[..., :3][straight[..., 3] == 0] == 0).all()
    assert (out[:, :20] == 255).all()           # opaque ink untouched

    again, changed = engine._premultiply_like_stock(out, stock)
    assert not changed and again is out         # never multiplied twice

    loud = np.full((20, 40, 4), 200, dtype=np.uint8)
    loud[..., 3] = 40                           # a slot that is NOT premultiplied
    kept, changed = engine._premultiply_like_stock(straight, loud)
    assert not changed and kept is straight


def test_compression_noise_does_not_hide_a_premultiplied_slot():
    """Godzilla's language-screen date decodes with colour up to 28 on some
    transparent texels (2.2% of it past a slack of 12): still premultiplied."""
    stock = np.zeros((20, 40, 4), dtype=np.uint8)
    stock[:, :20] = 255
    stock[:1, 20:, :3] = 28                     # 20 of 800 px = 2.5%, A == 0
    _out, changed = engine._premultiply_like_stock(_straight_text(40, 20), stock)
    assert changed


def test_an_editor_picture_is_premultiplied_in_place(tmp_path):
    data, banner, _icon = _scene()
    png = _project(tmp_path, data, banner, 40, 20)
    Image.fromarray(_straight_text(40, 20), "RGBA").save(png)
    writes, n, _ov, _grown, msgs = _writes(tmp_path, _Reader(RAD_PATH, data))
    assert n == 1 and [w[0] for w in writes] == [banner]
    assert _is_premultiplied(dds.decode_bc3(writes[0][1], 40, 20))
    assert any("premultiplied by alpha" in m for _l, m in msgs)


def test_an_editor_picture_is_premultiplied_when_resized(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "_image_grow_gate", lambda d: (True, ""))
    data, banner, _icon = _scene()
    png = _project(tmp_path, data, banner, 40, 20)
    Image.fromarray(_straight_text(90, 22), "RGBA").save(png)
    _w, _n, _ov, grown, _msgs = _writes(tmp_path, _Reader(RAD_PATH, data))
    (_node, imgs), = grown.values()
    w, h, payload = imgs[banner]
    decoded = dds.decode_bc3(payload, 92, 24)[:h, :w]
    assert _is_premultiplied(decoded)
    assert decoded[:, 60:, :3].max() <= 16      # the "transparent" white is gone


# ---------------------------------------------------------------------------
# the Write
# ---------------------------------------------------------------------------

def test_write_ships_the_grown_scene_whole(tmp_path, monkeypatch):
    raw, _offs = _grow_elf()
    data, banner, _icon = _scene()
    blob = _stub_sidx(["gz/game", "gz/assets/a/scene.radium",
                       "spk/index/a.sidx"])
    reader = _CardReader(raw, blob, data)
    _card(monkeypatch, reader)
    assets = tmp_path / "assets"
    png = _project(assets, data, banner, 40, 20)
    pic = Image.new("RGBA", (90, 22), (255, 0, 255, 255))
    pic.save(png)
    msgs, log = _capture()
    writes, counts, grow_plan, _a, _v = _compute(assets, log)
    assert counts[2] == 1
    assert [rel for rel, _s in grow_plan["jobs"]] == ["gz/assets/a/scene.radium"]
    shipped = open(grow_plan["jobs"][0][1], "rb").read()
    grid = Image.new("RGBA", (92, 24), (0, 0, 0, 0))
    grid.paste(pic, (0, 0))
    want = radium_grow.regrow(data, images={banner: (
        90, 22, dds.encode_bc3(np.asarray(grid, dtype=np.uint8)))})
    assert shipped == want["data"]
    assert _writes_in(writes, reader.RAD_DISK, len(data)) == []
    rec = _sidx_record(blob, writes, "gz/assets/a/scene.radium",
                       reader.SIDX_DISK)
    assert rec["size"] == rec["size2"] == len(shipped)
    by_disk = dict(writes)
    recs, _crc, fmt = sidx.parse_records(blob)
    for foff, b in sidx.record_field_writes(
            recs["gz/assets/a/scene.radium"],
            hmac.new(sidx.SIDX_KEY, shipped, hashlib.sha1).digest(),
            hashlib.md5(shipped).digest(), fmt, size=len(shipped)):
        assert by_disk[reader.SIDX_DISK + foff] == b
    assert any("sprite reference(s) that draw it resized" in m
               for _l, m in msgs)


def test_direct_sd_write_skips_a_resize_and_says_why(tmp_path, monkeypatch):
    raw, _offs = _grow_elf()
    data, banner, _icon = _scene()
    blob = _stub_sidx(["gz/game", "gz/assets/a/scene.radium",
                       "spk/index/a.sidx"])
    _card(monkeypatch, _CardReader(raw, blob, data))
    assets = tmp_path / "assets"
    png = _project(assets, data, banner, 40, 20)
    Image.new("RGBA", (90, 22), (255, 0, 255, 255)).save(png)
    msgs, log = _capture()
    with pytest.raises(RuntimeError, match="Nothing could be written"):
        _compute(assets, log, dest_is_device=True)
    assert any(l == "warning" and "direct-SD" in m for l, m in msgs)


# ---------------------------------------------------------------------------
# Replace Images staging
# ---------------------------------------------------------------------------

def test_staging_keeps_the_pictures_own_size_only_when_asked(tmp_path):
    assets = tmp_path / "assets"
    (assets / "images").mkdir(parents=True)
    for name in ("a.png", "b.png"):
        Image.new("RGBA", (40, 20), (0, 0, 0, 255)).save(
            assets / "images" / name)
    rep = tmp_path / "long_name.png"
    Image.new("RGBA", (90, 22), (255, 255, 255, 255)).save(rep)
    slots = {s.rel_path: s for s in image_slots.scan_image_slots(str(assets))}
    staged, failures = image_slots.stage_replacements(
        slots, {"images/a.png": str(rep), "images/b.png": str(rep)},
        keep_size=frozenset({"images/a.png"}))
    assert (staged, failures) == (2, [])
    assert Image.open(assets / "images" / "a.png").size == (90, 22)
    assert Image.open(assets / "images" / "b.png").size == (40, 20)
