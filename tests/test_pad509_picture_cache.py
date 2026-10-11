"""PAD-509 (DragonRR: "Emulation very slow to start ... Is it possible to store the
changed assets for the next emulation run - only altering those assets that have
changed? Currently it appears to re-encode every time", and a game window black for
15-20 s).

Three things made every Start of a Godzilla project with every picture
color-corrected cost two minutes and a black window:

* the "have the edits moved?" walk counted the project's own log, which the app
  writes on every line it logs, so no Start ever found its set current;
* every build encoded all 1,331 edited pictures again (``_PictureCache`` now keeps
  their bytes in the project's ``.write_cache``);
* every file of the set was written over itself and named in the delta, so the
  rig copied 518 MB into WSL while the game window sat black
  (``_patch_in_place`` writes, and hands on, only what differs).
"""

import os
import struct

import pytest

from pinball_decryptor.core.checksums import generate_checksums, read_checksums
from pinball_decryptor.plugins.stern import dds, engine, mode_write
from pinball_decryptor.webui import emulate_core

pytest.importorskip("numpy")
pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")


def _quiet(*_a, **_k):
    return None


# ---- the "have the edits moved?" walk -------------------------------------------------

@pytest.mark.parametrize("fingerprint", [emulate_core.assets_fingerprint,
                                         mode_write.assets_fingerprint])
def test_what_the_app_keeps_in_the_project_does_not_move_the_fingerprint(tmp_path,
                                                                         fingerprint):
    proj = tmp_path / "gz"
    (proj / "images").mkdir(parents=True)
    pic = proj / "images" / "a.png"
    pic.write_bytes(b"PNG")
    first = fingerprint(str(proj))
    for rel in ("logs/project.log", ".write_cache/picture_bytes.json", "build/x.raw",
                ".hashcache.json", ".history.log"):
        path = proj / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"the app's own")
    assert fingerprint(str(proj)) == first
    # an edit still moves it, and only the top of the folder is the app's
    (proj / "images" / "logs").mkdir()
    (proj / "images" / "logs" / "b.png").write_bytes(b"PNG")
    assert fingerprint(str(proj)) != first


def test_a_picture_staged_again_the_same_way_is_left_as_it_is(tmp_path):
    """The second half of "no Start found its set current": a picture with no .orig
    snapshot is staged again on every Start, and rewriting it with the same bytes moved
    the fingerprint (images/boot_screen/SternLogo.png on the gzho project)."""
    from pinball_decryptor.core.image import detect_image_info
    from pinball_decryptor.core.image_slots import ImageSlot, stage_replacement
    slot_file = tmp_path / "slot.png"
    Image.new("RGB", (16, 4), (0, 0, 0)).save(slot_file)
    slot = ImageSlot(rel_path="slot.png", abs_path=str(slot_file), ext=".png",
                     info=detect_image_info(str(slot_file)),
                     size=os.path.getsize(slot_file), probed=True)
    rep = tmp_path / "mine.png"
    Image.new("RGB", (16, 4), (200, 30, 30)).save(rep)
    assert stage_replacement(slot, str(rep))[0]
    first = slot_file.read_bytes()
    os.utime(slot_file, ns=(1_000_000_000, 1_000_000_000))
    assert stage_replacement(slot, str(rep))[0]
    assert slot_file.read_bytes() == first
    assert os.stat(slot_file).st_mtime_ns == 1_000_000_000      # not rewritten
    assert not (tmp_path / "slot.png.stage.png").exists()
    Image.new("RGB", (16, 4), (30, 200, 30)).save(rep)            # a new pick still lands
    assert stage_replacement(slot, str(rep))[0]
    assert slot_file.read_bytes() != first


def test_the_emulate_tab_reuses_a_set_after_the_log_moved(tmp_path):
    """The reuse test end to end: before PAD-509 the log line written after the build
    was enough to rebuild the set at the next Start."""
    img = tmp_path / "card.raw"
    img.write_bytes(b"x" * 32)
    proj = tmp_path / "gz"
    (proj / "images").mkdir(parents=True)
    (proj / "images" / "a.png").write_bytes(b"PNG")
    st = os.stat(img)
    manifest = {"card": {"path": os.path.abspath(str(img)), "size": st.st_size,
                         "mtime": int(st.st_mtime)},
                "assets": os.path.abspath(str(proj)),
                "assets_fingerprint": emulate_core.assets_fingerprint(str(proj))}
    (proj / "logs").mkdir()
    (proj / "logs" / "project.log").write_text("[emulate] the game ran\n")
    assert emulate_core.overrides_reason(
        manifest, str(img), str(proj),
        emulate_core.assets_fingerprint(str(proj))) == ""


# ---- the picture cache ------------------------------------------------------------------

def test_a_kept_picture_comes_back_in_the_next_build(tmp_path):
    c = engine._PictureCache(str(tmp_path))
    k = c.key("radium", 5, 4, 4, 16, "md5", b"stock")
    assert c.get(k) is None
    c.put(k, b"B" * 16)
    c.finish()
    again = engine._PictureCache(str(tmp_path))
    assert again.get(k) == b"B" * 16
    assert again.hits == 1
    assert again.get(c.key("radium", 5, 4, 4, 16, "md5", b"other stock")) is None


def test_another_encoder_starts_the_cache_again(tmp_path, monkeypatch):
    c = engine._PictureCache(str(tmp_path))
    c.put("k", b"old bytes")
    c.finish()
    monkeypatch.setattr(engine, "_PICTURE_CACHE_REV", engine._PICTURE_CACHE_REV + 1)
    again = engine._PictureCache(str(tmp_path))
    assert again.get("k") is None
    again.put("n", b"new")
    again.finish()
    # the old pack's bytes went with it
    assert os.path.getsize(os.path.join(str(tmp_path), engine._PICTURE_PACK)) == 3


def test_bytes_that_do_not_match_their_crc_are_a_miss(tmp_path):
    c = engine._PictureCache(str(tmp_path))
    c.put("k", b"ABCDEFGH")
    c.finish()
    pack = os.path.join(str(tmp_path), engine._PICTURE_PACK)
    with open(pack, "r+b") as f:
        f.write(b"Z")
    assert engine._PictureCache(str(tmp_path)).get("k") is None


def test_what_a_build_did_not_use_leaves_the_cache(tmp_path):
    c = engine._PictureCache(str(tmp_path))
    for i in range(4):
        c.put("k%d" % i, bytes([i]) * 100)
    c.finish()
    pack = os.path.join(str(tmp_path), engine._PICTURE_PACK)
    assert os.path.getsize(pack) == 400
    # a build that used one picture of four and made a new one
    b = engine._PictureCache(str(tmp_path))
    assert b.get("k0") == b"\0" * 100
    b.put("k9", b"9" * 100)
    b.finish()
    c3 = engine._PictureCache(str(tmp_path))
    assert set(c3.entries) == {"k0", "k9"}
    # three dead entries of five: written again, live only
    assert os.path.getsize(pack) == 200
    assert c3.get("k0") == b"\0" * 100 and c3.get("k9") == b"9" * 100


def test_a_build_that_changed_nothing_writes_nothing(tmp_path):
    c = engine._PictureCache(str(tmp_path))
    c.put("k", b"x" * 10)
    c.finish()
    index = os.path.join(str(tmp_path), engine._PICTURE_INDEX)
    before = os.stat(index).st_mtime_ns
    b = engine._PictureCache(str(tmp_path))
    assert b.get("k") == b"x" * 10
    b.finish()
    assert os.stat(index).st_mtime_ns == before


def test_the_cache_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_STERN_PICTURE_CACHE", "0")
    assert engine._PictureCache.open(str(tmp_path)) is None
    monkeypatch.delenv("PAD_STERN_PICTURE_CACHE")
    assert engine._PictureCache.open(str(tmp_path)) is not None


def _counting_encoder(monkeypatch):
    calls = []
    real = dds.encode_bc3

    def counted(arr):
        calls.append(arr.shape)
        return real(arr)
    monkeypatch.setattr(dds, "encode_bc3", counted)
    return calls


class _TextureReader:
    def __init__(self, card, stock):
        self.card, self.stock = card, stock

    def iter_regular_files(self, min_size=1):
        yield self.card, 0, {"size": len(self.stock), "mode": 0, "flags": 0,
                             "i_block": b""}

    def read_file_bytes(self, node):
        return self.stock


def test_a_texture_unchanged_since_the_last_build_is_not_encoded_again(tmp_path,
                                                                     monkeypatch):
    staged = tmp_path / "images" / "t.png"
    staged.parent.mkdir(parents=True)
    Image.new("RGBA", (16, 16), (40, 130, 200, 255)).save(staged)
    card = "/lz/assets/x/scene.assets/19.asset"
    reader = _TextureReader(card, bytes(256))
    edits = [("scene_textures/t.png", card, str(staged), 16, 16, 5)]
    calls = _counting_encoder(monkeypatch)

    def build():
        cache = engine._PictureCache(str(tmp_path))
        got, skipped = engine._prepare_texture_patches(reader, edits, _quiet,
                                                       lambda: False, cache=cache)
        cache.finish()
        assert skipped == 0 and len(got) == 1
        return got[0][1]

    first = build()
    assert len(calls) == 1
    assert build() == first
    assert len(calls) == 1                       # kept, not encoded
    Image.new("RGBA", (16, 16), (200, 10, 10, 255)).save(staged)
    assert build() != first
    assert len(calls) == 2                       # the changed one is
    # ... and another slot (other stock bytes) is not handed this one's bytes
    reader.stock = b"\xff" * 256
    build()
    assert len(calls) == 3


def test_a_scene_picture_unchanged_since_the_last_build_is_not_encoded_again(
        tmp_path, monkeypatch):
    tex = tmp_path / "images" / "scene_textures"
    tex.mkdir(parents=True)
    pw, ph = 16, 8
    Image.new("RGBA", (pw, ph), (10, 20, 30, 255)).save(tex / "img01.png")
    data_off, length = 44, pw * ph
    tex.joinpath("radium_images.txt").write_text(
        "# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\n"
        f"scene_textures/img01.png\t/lz/x/scene.radium\t{data_off}\t{length}\t{pw}\t{ph}\n"
        f"scene_textures/img01.png\t/lz/y/scene.radium\t{data_off}\t{length}\t{pw}\t{ph}\n",
        encoding="utf-8")
    generate_checksums(str(tmp_path))
    baseline = read_checksums(str(tmp_path))
    Image.new("RGBA", (pw, ph), (240, 0, 240, 255)).save(tex / "img01.png")
    scene = (b"\x7f" * 8 + struct.pack("<9I", pw, ph, 0x80000002, pw, ph, 5,
                                        0, 0, length) + bytes(length))

    class Reader:
        def read_file_bytes(self, node):
            return scene

        def iter_regular_files(self, min_size=1):
            for p in ("/lz/x/scene.radium", "/lz/y/scene.radium"):
                yield p, 0, {"size": len(scene), "mode": 0, "flags": 0,
                             "i_block": p.encode()}

        def disk_ranges(self, node, off, n):
            return [(off, n)]

    calls = _counting_encoder(monkeypatch)

    def build():
        cache = engine._PictureCache(str(tmp_path))
        writes, n, _ov = engine._radium_image_writes(
            Reader(), str(tmp_path), baseline, _quiet, lambda: False, cache=cache)
        cache.finish()
        assert n == 1 and len(writes) == 2       # both occurrences
        return [b for _o, b in writes], cache

    first, _c = build()
    assert len(calls) == 1
    again, cache = build()
    assert again == first and cache.hits == 1
    assert len(calls) == 1


# ---- the set: only what differs is written, and handed to the rig ------------------------

class _Card:
    """One card file of 1 MB on a 'disk' at offset 4096, mapped 1:1."""
    BASE = 4096
    SIZE = 1 << 20

    def __init__(self, tmp_path):
        self.img = tmp_path / "card.raw"
        self.stock = bytes(range(256)) * (self.SIZE // 256)
        with open(self.img, "wb") as f:
            f.write(b"\0" * self.BASE + self.stock)
        self.node = {"size": self.SIZE, "mode": 0o100644, "flags": 0,
                     "i_block": b"blk"}

    def disk_ranges(self, node, off, n):
        return [(self.BASE + off, n)]


def test_an_unchanged_span_is_left_alone_and_a_changed_one_is_named(tmp_path):
    card = _Card(tmp_path)
    dest = tmp_path / "set_file"
    dest.write_bytes(card.stock)
    with open(card.img, "rb") as disk:
        # the last build wrote 'A' * 10 at 100 and 'B' * 10 at 300000; this one the same
        writes = [(100, b"A" * 10), (300000, b"B" * 10)]
        engine._patch_in_place(disk, card, card.node, str(dest), [], writes)
        before = os.stat(dest).st_mtime_ns
        was = [(100, 10), (300000, 10)]
        assert engine._patch_in_place(disk, card, card.node, str(dest), was,
                                      writes) == []
        assert os.stat(dest).st_mtime_ns == before
        # one of the two changes, and one is taken back
        got = engine._patch_in_place(disk, card, card.node, str(dest), was,
                                     [(300000, b"C" * 10)])
    assert got == [(100, 10), (300000, 10)]
    data = dest.read_bytes()
    assert data[100:110] == card.stock[100:110]
    assert data[300000:300010] == b"C" * 10
    assert data[:100] == card.stock[:100] and data[110:300000] == card.stock[110:300000]


def test_a_long_span_is_handed_on_by_the_pieces_that_changed(tmp_path):
    card = _Card(tmp_path)
    dest = tmp_path / "set_file"
    dest.write_bytes(card.stock)
    big = bytes(400000)
    with open(card.img, "rb") as disk:
        engine._patch_in_place(disk, card, card.node, str(dest), [], [(0, big)])
        new = bytearray(big)
        new[200000] = 7                         # one byte of 400 KB
        got = engine._patch_in_place(disk, card, card.node, str(dest),
                                     [(0, len(big))], [(0, bytes(new))])
    assert len(got) == 1
    off, n = got[0]
    assert off <= 200000 < off + n and n <= engine._PATCH_CHUNK
    assert dest.read_bytes()[200000] == 7


def test_watch_stages_the_set_before_the_window_opens():
    with open(os.path.join(RIG, "watch.sh"), encoding="utf-8", errors="replace") as f:
        body = f.read()
    stage = body.index('bash "$S/overrides.sh" "$PAD_OVERRIDE_DIR" > /dev/null || true')
    assert stage < body.index('echo "[watch] starting renderer')
    # run_game.sh still stages (and refuses a set it cannot): watch.sh only goes first
    with open(os.path.join(RIG, "run_game.sh"), encoding="utf-8", errors="replace") as f:
        assert 'OVERRIDE_SRC=$(bash "$S/overrides.sh" "$PAD_OVERRIDE_DIR"' in f.read()
