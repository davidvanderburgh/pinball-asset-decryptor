"""PAD-1089: more sound banks than image.bin's header can name.

A Godzilla card with five songs at random on each of its eight music tracks (20 to 49 MB each)
was cut into 40 MB banks, one song each: 40 banks where the header names 35 more, and the Write
died with "Unexpected error: image.bin's header has room for 35 more sound bank(s), not 40".
The banks now grow towards each sound channel's share of the room beside image.bin, as little
as it takes, so the songs share fewer banks; a card that still cannot fit is refused with an
answer, not a traceback.

Fast, no card and no firmware (the PAD-606 planner fixtures).
"""
import pytest

from pinball_decryptor.plugins.stern import bank_build as BB
from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
from pinball_decryptor.plugins.stern.spike2 import soundbank as SB
from tests.test_pad606_game_sounds_in_banks import _Reader, _image, _rec

MB = 1_000_000


def _plan(monkeypatch, tmp_path, mapped, room):
    img = _image(tmp_path)
    sizes = {i: (20 - i) * MB for i in range(1, 11)}      # ten songs, 19 MB down to 10 MB
    params = [{"idx": i, "chan": 2, "length": 100, "findkey": bytes([i]) * 8} for i in sizes]
    grows = {i: (100, n // 4) for i, n in sizes.items()}
    audio_edits = {i: "C:/proj/audio/idx%04d - SONG %d.wav" % (i, i) for i in grows}
    monkeypatch.setenv(BB.BANK_CAP_ENV, "1000")
    monkeypatch.setattr(SB, "BANK_SLICE", 5 * MB)         # every song a bank of its own
    monkeypatch.setattr(SB, "MAPPED_MAX", mapped)
    real = SB.category_slots
    monkeypatch.setattr(SB, "category_slots",
                        lambda head: real(head)[:2] + (room,))
    monkeypatch.setattr(E, "_read_stock_directory",
                        lambda gr, im: MD.Directory(b"".join(_rec(i) for i in range(11)), 11,
                                                    0x9000, 0))
    logged = []
    plan = E._plan_sound_banks(
        "game", str(img), params, audio_edits, grows, dict(grows), [], _Reader(), None, None,
        lambda t, *a: logged.append(t), game_sids={i: 500 + i for i in grows})
    return plan, logged


def _bank_sizes(plan):
    return [SB.bank_bytes([e.body_bytes for e in g]) for _c, g in plan[0].banks]


def test_room_in_the_header_keeps_the_slice(monkeypatch, tmp_path):
    plan, logged = _plan(monkeypatch, tmp_path, 400 * MB, room=30)
    assert len(plan[0].banks) == 10
    assert not [t for t in logged if "can name only" in t]


def test_banks_grow_until_the_header_can_name_them(monkeypatch, tmp_path):
    plan, logged = _plan(monkeypatch, tmp_path, 400 * MB, room=6)
    banks = plan[0].banks
    assert len(banks) <= 6
    # every song is still in a bank, each once
    assert sorted(e.idx for _c, g in banks for e in g) == list(range(1, 11))
    # no bank past one sound channel's share of the room beside image.bin
    assert max(_bank_sizes(plan)) <= 400 * MB // SB.SOUND_CHANNELS
    # the categories are distinct and as many as the header has room for
    assert len({c for c, _g in banks}) == len(banks)
    assert [t for t in logged if "can name only 6 more" in t]


def test_the_slice_grows_only_as_far_as_it_takes(monkeypatch, tmp_path):
    loose, _l = _plan(monkeypatch, tmp_path, 400 * MB, room=8)
    tight, _t = _plan(monkeypatch, tmp_path, 400 * MB, room=5)
    assert max(_bank_sizes(loose)) < max(_bank_sizes(tight))


def test_too_many_banks_even_at_the_share_is_an_answer_not_a_crash(monkeypatch, tmp_path):
    # 160 MB beside image.bin: 20 MB a channel, so the ten songs cannot pair into 3 banks
    with pytest.raises(E.SoundRoomError) as got:
        _plan(monkeypatch, tmp_path, 160 * MB, room=3)
    msg = str(got.value)
    assert "image.bin can name only 3 more" in msg
    assert "fewer files at random or in turn, or shorter ones" in msg
