"""The chain replay may write a master-directory record ONLY onto that
record's own slot (fast; no boot, no card).

``_drive_step`` replays each record's band build and hands the record back to
the firmware by writing it at ``r9 - 8``.  On the validated build r9 at the
band-loop head IS the record cursor, so that address is the record's own slot
and the write is a no-op -- the record is already there.  On newer builds the
loop head opens ``and r1, sb, #1`` -- r9 is a packed data word, so ``r9 - 8``
is a pseudo-random 32-bit address, and the replay mapped a page and wrote 24
bytes of live guest memory once per record.

Deadpool Pro 1.16 has 8175 records, i.e. 8175 darts: one landed at record 4714
and from there every record's predictor (obj+0x18) was derived from corrupted
state.  3461 of its 8175 sounds decoded to stationary noise -- 42% of the
extract.  Harvesting the objects from the firmware's own uninterrupted loop
proved it: bit-identical to the replay for records 0..4713, differing from 4714
on in pred16 and nothing else, and the firmware's pred16 decodes those sounds
to clean audio (spectral flatness 0.665 -> 0.14, rms 6454 -> 3415).

Bounding the dart to the record ARRAY was not enough, which is what PAD-108
cost: a dart that lands inside the array is still a dart.  Beatles 1.29 threw
exactly one accepted write in 933 records -- during record 66, at ``md+10062``,
i.e. slot 419.25 -- and those 24 bytes rewrote the tail of slot 419 and the
head of slot 420 with record 66's bytes.  Record 419's band object came out
structurally impossible (length 3011441464, stride 8, band-0 key offset 0), and
all 514 records from 419 to the end of the catalog decoded to noise: 55% of the
card, and the reason a user's mods for those sounds would not transfer onto it.

So the address has to be the record's OWN slot, the one place the write is
provably a no-op -- not merely somewhere inside the array.
"""
import pytest

from pinball_decryptor.plugins.stern.spike2.emulator import _record_write_addr

NREC = 8175                                       # a Deadpool-sized catalog
LO, HI = 0x30100000, 0x30100000 + NREC * 24


def _r9_for(addr):
    """The r9 a replay would carry for the record slot at *addr*."""
    return addr + 8


def test_record_cursor_writes_to_its_own_slot():
    """The validated build's r9 IS the record cursor: r9-8 is the record's own
    slot, so the write is allowed (and is a no-op -- the record is already
    there).  Measured on TMNT 1.58: record N writes slot N, for every N."""
    for idx in (0, 1, 4713, 4714, NREC - 1):
        slot = LO + idx * 24
        assert _record_write_addr((LO, HI), _r9_for(slot), idx) == slot


@pytest.mark.parametrize("r9", [
    0x6b354697,   # real r9 values sampled at Deadpool 1.16's band-loop head --
    0x2c0e3393,   # packed data words, not pointers
    0xd301370c,
    0x896cd94b,
    0x8a5c336a,   # and Beatles 1.29's, at the record that threw the live dart
    0x00000000,   # would compute a huge address via the & 0xffffffff wrap
    0xffffffff,
])
def test_packed_data_word_writes_nothing(r9):
    """A pseudo-random r9 must NOT be written through: that write is what
    corrupted Deadpool 1.16 at record 4714."""
    assert _record_write_addr((LO, HI), r9, 100) is None


def test_a_dart_inside_the_array_is_still_a_dart():
    """PAD-108: the Beatles 1.29 dart landed INSIDE the record array, six bytes
    into slot 419, while record 66 was being replayed.  Bounds alone accepted
    it; those 24 bytes straddled two records and rewrote both."""
    dart = LO + 419 * 24 + 6
    assert _record_write_addr((LO, HI), _r9_for(dart), 66) is None
    # ... and it stays rejected even if the record being replayed were the one
    # whose slot it clips into: the address still is not that slot.
    assert _record_write_addr((LO, HI), _r9_for(dart), 419) is None
    assert _record_write_addr((LO, HI), _r9_for(dart), 420) is None


@pytest.mark.parametrize("hit_idx", [0, 65, 67, 419, NREC - 1])
def test_another_records_slot_is_refused(hit_idx):
    """A dart that happens to land slot-ALIGNED is no better: it would rewrite
    a different record with this one's 24 bytes."""
    slot = LO + hit_idx * 24
    assert _record_write_addr((LO, HI), _r9_for(slot), 66) is None


def test_unknown_array_allows_no_write():
    """Before a chain declares the record array (default (0, 0)) nothing may be
    written -- an unbounded address can't be validated."""
    assert _record_write_addr((0, 0), _r9_for(LO), 0) is None
    assert _record_write_addr((0, 0), 0x6b354697, 0) is None


def test_no_record_index_allows_no_write():
    """Without the index there is no address that can be shown to be a no-op,
    so a caller that doesn't say which record it is replaying gets nothing."""
    assert _record_write_addr((LO, HI), _r9_for(LO)) is None
    assert _record_write_addr((LO, HI), _r9_for(LO), None) is None


@pytest.mark.parametrize("idx,ok", [
    (0,        True),     # first record
    (NREC - 1, True),     # last record, exactly flush with the end
    (NREC,     False),    # one record past the end
    (-1,       False),    # one record before the array
])
def test_only_whole_records_inside_the_array(idx, ok):
    """The whole 24-byte record must land inside the array -- an index off
    either end is corruption of whatever sits next to it."""
    slot = LO + idx * 24
    got = _record_write_addr((LO, HI), _r9_for(slot), idx)
    assert (got == slot) if ok else (got is None)


def test_wrap_is_masked_not_negative():
    """r9 < 8 wraps to the top of the 32-bit space instead of going negative --
    a negative dst would sort below every array and could pass a naive
    ``dst + 24 <= hi`` check.  Wrapped, it can never equal a real slot."""
    assert _record_write_addr((LO, HI), 4, 0) is None
    assert _record_write_addr((0, 0xffffffff), 0, 0) is None
