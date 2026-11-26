"""PAD-1621: the Godot game's pictures and clips on a Spike 3 card (Pokemon's
pokedex, battles, arenas, in ``assets/godot/main.pck``) - Extract puts them in
the project, Write rebuilds the pack from the changed ones.

Synthetic packs only: no Stern files.
"""
import hashlib
import io
import os
import struct

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from pinball_decryptor.plugins.stern import godot_pck as G  # noqa: E402
from pinball_decryptor.plugins.stern import spike3_godot as SG  # noqa: E402


def _ctex(im, mips, fmt=5, df=G.DF_WEBP):
    out = bytearray(b"GST2" + struct.pack("<5I", 1, im.width, im.height,
                                          0x0D800000, 0xFFFFFFFF) + b"\0" * 12)
    out += struct.pack("<IHHII", df, im.width, im.height, mips, fmt)
    for i in range(mips + 1):
        lvl = im.resize((max(1, im.width >> i), max(1, im.height >> i)))
        b = io.BytesIO()
        lvl.save(b, "WEBP" if df == G.DF_WEBP else "PNG", lossless=True)
        out += struct.pack("<I", len(b.getvalue())) + b.getvalue()
    return bytes(out)


def _pack(files, flags=0):
    """A format-2 pack of ``[(path, bytes)]``, laid out as Godot 4.4 does."""
    raws = []
    for p, _d in files:
        raw = ("res://" + p).encode()
        raw += b"\0" * ((-len(raw)) % 4)
        raws.append(raw)
    hdr = b"GDPC" + struct.pack("<5I", 2, 4, 4, 1, flags)
    dir_len = 4 + sum(4 + len(r) + 36 for r in raws)
    base = len(hdr) + 8 + 64 + dir_len
    base += (-base) % 16
    body, offs, pos = bytearray(), [], 0
    for _p, d in reversed(files):            # data order != directory order
        offs.append(pos)
        body += d + b"\0" * ((-len(d)) % 16)
        pos += len(d) + (-len(d)) % 16
    offs.reverse()
    dirb = struct.pack("<I", len(files))
    for (p, d), raw, off in zip(files, raws, offs):
        dirb += struct.pack("<I", len(raw)) + raw + struct.pack("<QQ", off, len(d))
        dirb += hashlib.md5(d).digest() + struct.pack("<I", 0)
    head = hdr + struct.pack("<Q", base) + b"\0" * 64 + dirb
    return head + b"\0" * (base - len(head)) + bytes(body)


def _picture(w=40, h=24):
    im = Image.new("RGBA", (w, h))
    im.putdata([(x * 6 % 256, y * 10 % 256, (x + y) % 256, 255 - x)
                for y in range(h) for x in range(w)])
    return im


CTEX = ".godot/imported/001_BULBASAUR.png-0123456789abcdef0123456789abcdef.ctex"
IMPORT = ('[remap]\n\nimporter="texture"\ntype="CompressedTexture2D"\n'
          'path="res://%s"\n' % CTEX)


def _files():
    return [("scenes/pokedex/gfx/001_BULBASAUR.png.import", IMPORT.encode()),
            (CTEX, _ctex(_picture(), mips=3)),
            ("scenes/shared/gfx/bknd/Arena/Stadium_h265.mp4", b"\0\0\0\x18ftypmp42" + b"x" * 333),
            ("project.binary", b"cfg" * 7)]


def _reader(data):
    return lambda off, n: data[off:off + n]


def test_parse_and_an_untouched_rebuild_is_the_same_pack():
    data = _pack(_files())
    pack = G.parse(_reader(data))
    assert [e.path for e in pack.entries] == [p for p, _d in _files()]
    for (p, d), e in zip(_files(), pack.entries):
        assert data[e.offset:e.offset + e.size] == d
    out = io.BytesIO()
    G.rewrite(pack, _reader(data), out, {})
    assert out.getvalue() == data


def test_a_rebuilt_pack_moves_the_files_after_and_keeps_md5s_true():
    data = _pack(_files())
    pack = G.parse(_reader(data))
    new = b"N" * 1001
    out = io.BytesIO()
    G.rewrite(pack, _reader(data), out, {"project.binary": new})
    b = out.getvalue()
    p2 = G.parse(_reader(b))
    for e in p2.entries:
        assert hashlib.md5(b[e.offset:e.offset + e.size]).digest() == e.md5
        assert (e.offset - p2.file_base) % 16 == 0
    e = p2.by_path["project.binary"]
    assert b[e.offset:e.offset + e.size] == new
    for p, d in _files()[:3]:
        e = p2.by_path[p]
        assert b[e.offset:e.offset + e.size] == d
    with pytest.raises(G.PckError):
        G.rewrite(pack, _reader(data), io.BytesIO(), {"no/such": b""})


def test_other_packs_are_refused_with_a_reason():
    with pytest.raises(G.PckError, match="encrypted"):
        G.parse(_reader(_pack(_files(), flags=1)))
    v3 = bytearray(_pack(_files()))
    v3[4:8] = struct.pack("<I", 3)
    with pytest.raises(G.PckError, match="format 3"):
        G.parse(_reader(bytes(v3)))
    with pytest.raises(G.PckError):
        G.parse(_reader(b"PK\3\4" + b"\0" * 200))


def test_a_texture_comes_out_and_goes_back_losslessly_with_every_mip():
    im = _picture(37, 21)
    orig = _ctex(im, mips=5)
    got = G.decode_texture(orig)
    assert got.mode == "RGBA" and got.tobytes() == im.tobytes()
    edited = im.transpose(Image.FLIP_LEFT_RIGHT)
    new = G.encode_texture(edited, orig)
    tex = G.Texture(new)
    assert (tex.width, tex.height, tex.mipmaps, tex.image_format) == (37, 21, 5, 5)
    assert new[:36] == orig[:36]                     # the header as it was
    sizes = [Image.open(io.BytesIO(lv)).size for lv in tex.levels]
    assert sizes == [(37, 21), (18, 10), (9, 5), (4, 2), (2, 1), (1, 1)]
    assert G.decode_texture(new).tobytes() == edited.tobytes()
    # a picture of another size is scaled to the texture's; RGB stays RGB
    rgb = _ctex(im.convert("RGB"), mips=0, fmt=4)
    back = G.Texture(G.encode_texture(_picture(80, 80), rgb))
    assert (back.width, back.height) == (37, 21)
    assert G.decode_texture(G.encode_texture(_picture(80, 80), rgb)).mode == "RGB"


def test_a_gpu_compressed_texture_is_not_a_picture():
    raw = bytearray(_ctex(_picture(), mips=0))
    struct.pack_into("<I", raw, 36, 0)              # DATA_FORMAT_IMAGE
    assert G.decode_texture(bytes(raw)) is None


def test_extract_names_pictures_from_their_source_and_writes_manifests(tmp_path):
    data = _pack(_files())
    logs = []
    n_img, n_vid = SG.extract_packs(
        [("/pokemon_pro/assets/godot/main.pck", _reader(data))], str(tmp_path),
        log=lambda m, *a: logs.append(m))
    assert (n_img, n_vid) == (1, 1)
    png = tmp_path / "images" / "godot" / "scenes" / "pokedex" / "gfx" / "001_BULBASAUR.png"
    assert Image.open(png).tobytes() == _picture().tobytes()
    clip = tmp_path / "video" / "godot" / "scenes" / "shared" / "gfx" / "bknd" / "Arena" / "Stadium_h265.mp4"
    assert clip.read_bytes() == _files()[2][1]
    assert SG.read_manifest(str(tmp_path), SG.IMAGE_DIR) == [
        ("godot/scenes/pokedex/gfx/001_BULBASAUR.png",
         "/pokemon_pro/assets/godot/main.pck", CTEX)]
    assert SG.read_manifest(str(tmp_path), SG.VIDEO_DIR)[0][2] == \
        "scenes/shared/gfx/bknd/Arena/Stadium_h265.mp4"
    # images only: no clips
    only = tmp_path / "only"
    assert SG.extract_packs([("/x/main.pck", _reader(data))], str(only),
                            want_video=False) == (1, 0)
    assert not (only / "video").exists()


class _Reader:
    def __init__(self, data):
        self.data = data

    def read_range(self, node, off, n):
        return self.data[off:off + n]


def test_write_rebuilds_the_pack_from_the_changed_files_only(tmp_path, monkeypatch):
    from pinball_decryptor.core.checksums import generate_checksums, read_checksums
    from pinball_decryptor.plugins.stern import spike3_extract
    data = _pack(_files())
    card = "/pokemon_pro/assets/godot/main.pck"
    proj = tmp_path / "proj"
    SG.extract_packs([(card, _reader(data))], str(proj))
    generate_checksums(str(proj))
    baseline = read_checksums(str(proj))
    monkeypatch.setattr(spike3_extract, "_node_at",
                        lambda r, p: {"size": len(data)} if p == card else None)
    reader = _Reader(data)
    assert SG.plan_write(str(proj), reader, baseline, str(tmp_path / "w"), print) is None

    png = proj / "images" / "godot" / "scenes" / "pokedex" / "gfx" / "001_BULBASAUR.png"
    edited = _picture().transpose(Image.FLIP_TOP_BOTTOM)
    edited.save(png)
    clip = proj / "video" / "godot" / "scenes" / "shared" / "gfx" / "bknd" / "Arena" / "Stadium_h265.mp4"
    clip.write_bytes(b"\0\0\0\x18ftypmp42NEW")
    plan = SG.plan_write(str(proj), reader, baseline, str(tmp_path / "w"), print)
    assert (plan.n_image, plan.n_video) == (1, 1)
    [(rel, staged)] = plan.jobs
    assert rel == card.lstrip("/")
    b = open(staged, "rb").read()
    p2 = G.parse(_reader(b))
    e = p2.by_path[CTEX]
    assert G.decode_texture(b[e.offset:e.offset + e.size]).tobytes() == edited.tobytes()
    e = p2.by_path["scenes/shared/gfx/bknd/Arena/Stadium_h265.mp4"]
    assert b[e.offset:e.offset + e.size] == b"\0\0\0\x18ftypmp42NEW"
    e = p2.by_path["project.binary"]
    assert b[e.offset:e.offset + e.size] == _files()[3][1]


def test_write_card_puts_the_rebuilt_pack_on_whole():
    """spike3_write plans the Godot packs and hands them to the grown-file
    copy, counted with the images and videos."""
    import inspect
    from pinball_decryptor.plugins.stern import spike3_write as W
    src = inspect.getsource(W.write_card)
    assert "spike3_godot.plan_write" in src
    assert "jobs += godot.jobs" in src
    assert "n_image += godot.n_image" in src and "godot is None" in src


def test_images_tab_labels_and_groups_godot_pictures(tmp_path):
    from pinball_decryptor.webui.tabs import images as T
    assert T.source_label("images/godot/scenes/pokedex/gfx/a.png") == "Godot"
    assert "Godot" in T.SOURCES
    SG.extract_packs([("/p/main.pck", _reader(_pack(_files())))], str(tmp_path))
    groups, _occ, _where = T.scan_image_groups(str(tmp_path))
    key, label, _i = groups["images/godot/scenes/pokedex/gfx/001_BULBASAUR.png"]
    assert key == "godot::godot/scenes/pokedex/gfx"
    assert label == "Godot: pokedex"
    assert T._godot_label("godot/scenes/shared_items/gfx/char_3_up/left") == \
        "Godot: shared_items/char_3_up/left"
    assert T._godot_label("godot/gfx") == "Godot"
