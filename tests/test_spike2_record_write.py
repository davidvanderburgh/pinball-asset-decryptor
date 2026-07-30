"""The chain replay must not scribble outside the master-directory record array
(fast; no boot, no card).

``_drive_step`` replays each record's band build and hands the record back to
the firmware by writing it at ``r9 - 8``.  On the validated build r9 at the
band-loop head IS the record cursor, so that address is the record's own slot.
On newer builds the loop head opens ``and r1, sb, #1`` -- r9 is a packed data
word, so ``r9 - 8`` is a pseudo-random 32-bit address, and the replay mapped a
page and wrote 24 bytes of live guest memory once per record.

Deadpool Pro 1.16 has 8175 records, i.e. 8175 darts: one landed at record 4714
and from there every record's predictor (obj+0x18) was derived from corrupted
state.  3461 of its 8175 sounds decoded to stationary noise -- 42% of the
extract.  Harvesting the objects from the firmware's own uninterrupted loop
proved it: bit-identical to the replay for records 0..4713, differing from 4714
on in pred16 and nothing else, and the firmware's pred16 decodes those sounds
to clean audio (spectral flatness 0.665 -> 0.14, rms 6454 -> 3415).

Bigger catalogs get hit harder because each record is another dart; TMNT 1.58
(2067 sounds) lost ~0.7%, Jaws 1.01 (1733) none.
"""
import pytest

from pinball_decryptor.plugins.stern.spike2.emulator import _record_write_addr

LO, HI = 0x30100000, 0x30100000 + 8175 * 24      # a Deadpool-sized record array


def _r9_for(addr):
    """The r9 a replay would carry for the record slot at *addr*."""
    return addr + 8


def test_record_cursor_writes_to_its_own_slot():
    """The validated build's r9 IS the record cursor: r9-8 is the record's slot
    inside the array, so the write is allowed (and is a no-op -- the record is
    already there)."""
    for idx in (0, 1, 4713, 4714, 8174):
        slot = LO + idx * 24
        assert _record_write_addr((LO, HI), _r9_for(slot)) == slot


@pytest.mark.parametrize("r9", [
    0x6b354697,   # real r9 values sampled at Deadpool 1.16's band-loop head --
    0x2c0e3393,   # packed data words, not pointers
    0xd301370c,
    0x896cd94b,
    0x00000000,   # would compute a huge address via the & 0xffffffff wrap
    0xffffffff,
])
def test_packed_data_word_writes_nothing(r9):
    """A pseudo-random r9 must NOT be written through: that write is what
    corrupted Deadpool 1.16 at record 4714."""
    assert _record_write_addr((LO, HI), r9) is None


def test_unknown_array_allows_no_write():
    """Before a chain declares the record array (default (0, 0)) nothing may be
    written -- an unbounded address can't be validated."""
    assert _record_write_addr((0, 0), _r9_for(LO)) is None
    assert _record_write_addr((0, 0), 0x6b354697) is None


@pytest.mark.parametrize("slot,ok", [
    (LO,           True),     # first record
    (LO - 24,      False),    # one record before the array
    (LO - 1,       False),    # straddles the low edge
    (HI - 24,      True),     # last record, exactly flush with the end
    (HI - 23,      False),    # last record + 1 byte: overruns the array
    (HI,           False),    # one past the end
])
def test_bounds_are_inclusive_of_whole_records_only(slot, ok):
    """The whole 24-byte record must land inside the array -- a write that
    straddles either edge is corruption of whatever sits next to it."""
    got = _record_write_addr((LO, HI), _r9_for(slot))
    assert (got == slot) if ok else (got is None)


def test_wrap_is_masked_not_negative():
    """r9 < 8 wraps to the top of the 32-bit space instead of going negative --
    a negative dst would sort below every array and could pass a naive
    ``dst + 24 <= hi`` check.  Wrapped, it can never fit any array."""
    assert _record_write_addr((LO, HI), 4) is None
    assert _record_write_addr((0, 0xffffffff), 0) is None      # 0xfffffff8 + 24 wraps past hi
