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
