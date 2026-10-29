"""Unit tests for the Stern Spike 2 per-category (image-scNN.bin) audio module.

The heavy path (booting the firmware in unicorn to decode a real bank) needs a
card image and is exercised manually; these cover the pure, build-independent
helpers + the graceful no-op paths so a regression can't silently break the
filename→cat-id mapping or the "nothing to do" skip."""
import pytest

from pinball_decryptor.plugins.stern.spike2 import category as C


@pytest.mark.parametrize("name,expected", [
    ("image-sc01.bin", 1),
    ("/card/games/foo/image-sc07.bin", 7),
    ("image-sc16.bin", 16),
    ("image-sc55.bin", 55),     # Deadpool-style non-sequential id
    ("image-sc1.bin", 1),       # tolerate a missing zero-pad
    ("image.bin", None),        # cat-0 base is not a category bank
    ("game_real", None),
    ("something.bin", None),
])
def test_read_category_id_from_filename(name, expected):
    # The firmware builds the path as image-sc%02d.bin from the cat id, so the
    # filename number IS the id (NOT a field inside the file — that varies).
    assert C.read_category_id(name) == expected


def test_extract_category_audio_no_banks_is_a_clean_noop():
    # No image-scNN.bin paths -> returns 0 without booting anything (so a title
    # with zero categories, or an audio-only re-run, never hangs or errors).
    calls = []
    n = C.extract_category_audio("no_fw", "no_img", [],
                                 lambda *a: calls.append(a))
    assert n == 0
    assert calls == []


def test_expand_imm_rotate_encoding():
    # ARM modified-immediate: value = ror(imm8, 2*rot4).
    assert C._expand_imm(0x000) == 0
    assert C._expand_imm(0x0ff) == 0xff          # rot=0
    assert C._expand_imm(0x1ff) == 0xC000003F    # imm=0xff, rot=2 -> ror by 4


# ---- music-bank Write coverage (engine helpers) --------------------------
@pytest.mark.parametrize("name,cat,idx", [
    ("music_cat01_0001.wav", 1, 1),
    ("music_cat24_0000 - Some Song.wav", 24, 0),   # survives the Music-ID rename
    ("music_cat07_0012.wav", 7, 12),
])
def test_music_name_parse(name, cat, idx):
    # The catNN_MMMM key drives which image-scNN.bin bank + sound a Write
    # re-encodes; it must survive the auto-name rename suffix.
    from pinball_decryptor.plugins.stern import engine as E
    m = E._MUSIC_NAME_RE.match(name)
    assert m is not None
    assert (int(m.group(1)), int(m.group(2))) == (cat, idx)


def test_changed_music_banks_detects_edits(tmp_path):
    # Only music_catNN_*.wav whose bytes differ from the baseline are returned;
    # untouched songs + cat-0 idx WAVs are ignored, and the prefix match still
    # works after an Auto-transcribe / Music-ID rename.
    import os
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.core.checksums import md5_file
    audio = tmp_path / "audio"
    audio.mkdir()
    song = audio / "music_cat01_0001.wav"
    song.write_bytes(b"ORIGINAL-SONG-BYTES")
    untouched = audio / "music_cat02_0000.wav"
    untouched.write_bytes(b"UNTOUCHED-SONG")
    idxf = audio / "idx0005.wav"
    idxf.write_bytes(b"CAT0-SOUND")
    baseline = {
        "audio/music_cat01_0001.wav": md5_file(str(song)),
        "audio/music_cat02_0000.wav": md5_file(str(untouched)),
        "audio/idx0005.wav": md5_file(str(idxf)),
    }
    assert E._changed_music_banks(str(tmp_path), baseline) == []
    # edit the song AND rename it (prefix preserved) — must still be detected
    song.unlink()
    renamed = audio / "music_cat01_0001 - Battery.wav"
    renamed.write_bytes(b"EDITED-DIFFERENT-BYTES")
    changed = E._changed_music_banks(str(tmp_path), baseline)
    assert [os.path.basename(p) for p in changed] == [
        "music_cat01_0001 - Battery.wav"]


def test_changed_music_banks_no_baseline_is_empty(tmp_path):
    # No baseline -> can't tell what changed -> report nothing (never warn /
    # re-encode blind).
    from pinball_decryptor.plugins.stern import engine as E
    audio = tmp_path / "audio"
    audio.mkdir()
    (audio / "music_cat01_0001.wav").write_bytes(b"x")
    assert E._changed_music_banks(str(tmp_path), {}) == []


# ---------------------------------------------- PAD-813: Deadpool's leaf helper
class _Fw:
    """A one-section stand-in for locate._FwView: .text at 0x1000."""

    def __init__(self, words):
        import struct
        self.raw = b"".join(struct.pack("<I", w) for w in words)
        self.secs = {".text": {"addr": 0x1000, "off": 0, "size": len(self.raw)}}


# Deadpool Pro 1.16's map-revalidation stub (0x3845e8), as the card has it:
# movw r3; movw ip; movt r3; movt ip; push {r4, r5}; ldrd; ...
DEADPOOL_REV = [0xE30F30B0, 0xE304C3A0, 0xE340306E, 0xE340C064, 0xE92D0030,
                0xE1C340D0, 0xE1CC20D8, 0xE0900004, 0xE0A11005, 0xE1510003]
# the stub the other titles have: a push that saves lr up front
LR_FUNC = [0xE30F30B0, 0xE340306E, 0xE92D4070, 0xE283500C, 0xE5934014,
           0xE1A06000, 0xE1540005, 0x08BD8070, 0xE5940010, 0xE1500006]


def test_a_leaf_function_with_globals_first_is_a_candidate():
    fw = _Fw(DEADPOOL_REV + [0] * 8)
    assert not C._is_funcstart(fw, 0x1000)          # what turned it down
    assert C._is_leaf_funcstart(fw, 0x1000)


def test_a_literal_pool_word_is_no_leaf_function():
    # data a raw bl scan lands in: no movw/movt run ending in a push
    fw = _Fw([0x00000000, 0x3F800000, 0xDEADBEEF, 0x00010203] + [0] * 10)
    assert not C._is_leaf_funcstart(fw, 0x1000)
    # a push with nothing in it is no function either
    fw = _Fw([0xE30F30B0, 0xE92D0000] + [0] * 10)
    assert not C._is_leaf_funcstart(fw, 0x1000)


def test_lr_functions_stay_first_and_leaves_follow(monkeypatch):
    """A title that worked keeps its candidates in the same order; a leaf
    helper is tried after them (so nothing that worked pays for it)."""
    # the loader at 0x1000: bl leaf(0x2000); bl lr_func(0x3000); bl mmap64
    def bl(site, tgt):
        return 0xEB000000 | (((tgt - site - 8) >> 2) & 0xFFFFFF)
    words = [0] * 0x1000
    words[0], words[1], words[2] = bl(0x1000, 0x2000), bl(0x1004, 0x3000), bl(0x1008, 0x1F00)
    words[0x400:0x40A] = DEADPOOL_REV
    words[0x800:0x80A] = LR_FUNC
    fw = _Fw(words)
    monkeypatch.setattr(C.L, "_FwView", lambda raw: fw)
    monkeypatch.setattr(C.L, "_func_end", lambda fw, va: 0x100C)
    monkeypatch.setattr(C, "_find_snprintf", lambda fw, a, b: 0x9999)
    monkeypatch.setattr(C, "_plt_got", lambda fw, tgt: tgt)      # the target is its GOT
    monkeypatch.setattr(C, "parse_elf", lambda raw: ([], [(0x1F00, "mmap64")]))
    out = C.category_locators(b"", {"CAT0_REGISTER": 0x1000})
    assert out == {"SNPRINTF": 0x9999, "REVALIDATE_CANDIDATES": [0x3000, 0x2000]}
