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
