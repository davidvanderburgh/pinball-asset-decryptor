"""The audio codec is not always in the sound's own dispatch row (fast; no boot,
no card).

``_resolve_entry`` used to build its candidate list from four sub-slots of the
sound's OWN scale row.  Brute-forcing the whole dispatch table against real
sounds shows that is not where every build keeps the entry -- rows that decode
to band-limited audio, per scale S:

    Godzilla Pro 1.15   mono S (odd sub-slots)     stereo S      (even)
    Star Wars LE 1.30   mono S-1, S (odd)          stereo S-1, S (even)
    Venom LE 1.07       mono S-1, S (even)         stereo S-1    (odd)

Venom keeps no stereo entry in the own row at all, so all 1374 of its stereo
sounds -- 34.5% of the card, its entire stereo half -- decoded to white noise
(specflat 0.85, rms 12.4k of the 21452 stereo range, a third of the energy above
15 kHz).  That is the ticket: Venom LE 1.07 "00m04s887 - idx3935.wav" came out as
noise on every one of the 16 sub-slots of its own row, and decodes to speech
(specflat 0.20, rms 6910) from row S-1 sub-slot 1.

Searching the own row FIRST is what keeps the cards that already worked byte for
byte identical, and free: pass 1 stops at the first clearly-audio candidate.
"""
import pytest

from pinball_decryptor.plugins.stern.spike2.emulator import Spike2Emu

DISPATCH = 0x600000
ROW = 0x40


class _FakeMu:
    """Serves dispatch words out of a dict; raises for unmapped addresses the
    way unicorn does."""

    def __init__(self, words):
        self.words = words
        self.reads = []

    def mem_read(self, addr, n):
        self.reads.append(addr)
        if addr not in self.words:
            from unicorn import UcError
            raise UcError(6)
        return self.words[addr].to_bytes(4, "little")


def _emu(words, recipe=None, backed=lambda va: 1):
    e = Spike2Emu.__new__(Spike2Emu)
    e.DISPATCH = DISPATCH
    e.mu = _FakeMu(words)
    e._slot_recipe = dict(recipe or {})
    e._backing_off = backed
    return e


def _row(scale, slot):
    return DISPATCH + scale * ROW + slot * 4


def test_own_row_is_searched_first():
    """The ordering guarantee behind 'no working card changes': every own-row
    candidate is offered before any adjacent-row one."""
    assert Spike2Emu._PROBE_ROWS[0] == 0
    words = {}
    for d in (0, -1):
        for s in range(4):
            words[_row(9 + d, s)] = 0x1000 + (d + 1) * 0x100 + s
    cands = _emu(words)._slot_candidates({"scale": 9, "chan": 1})
    deltas = [place[0] for _fn, place in cands]
    assert deltas[:4] == [0, 0, 0, 0], deltas
    assert set(deltas) == {0, -1}


def test_venom_stereo_entry_in_the_row_below_is_reachable():
    """Venom's stereo codec sits at row S-1 sub-slot 1; it must appear as a
    candidate, which is what the own-row-only search could never do."""
    words = {}
    for s in range(4):
        words[_row(29, s)] = 0x2E9000 + s          # own row: all wrong codec
    for s in range(4):
        words[_row(28, s)] = 0x2ED000 + s
    words[_row(28, 1)] = 0x2EDD40                  # the real entry
    cands = _emu(words)._slot_candidates({"scale": 29, "chan": 2})
    assert 0x2EDD40 in [fn for fn, _p in cands]
    assert dict((fn, p) for fn, p in cands)[0x2EDD40] == (-1, 1)


def test_scale_zero_row_below_is_not_clamped():
    """Venom really keeps scale 0's stereo codec one row BELOW DISPATCH, so the
    row index must be allowed to go negative rather than clamped at 0."""
    words = {_row(0, s): 0x300000 + s for s in range(4)}
    words[_row(-1, 1)] = 0x2FFF00
    cands = _emu(words)._slot_candidates({"scale": 0, "chan": 2})
    assert 0x2FFF00 in [fn for fn, _p in cands]


def test_unmapped_row_is_skipped_not_fatal():
    """A row that falls off the mapped table must be skipped, not raise."""
    words = {_row(0, s): 0x300000 + s for s in range(4)}   # nothing below row 0
    cands = _emu(words)._slot_candidates({"scale": 0, "chan": 1})
    assert [fn for fn, _p in cands] == [0x300000, 0x300001, 0x300002, 0x300003]


def test_learned_recipe_is_tried_first():
    """The winning (row delta, sub-slot) is a build property, so later scales of
    the same channel count lead with it -- that is what stops the widened search
    from being re-walked for all 32 of a card's stereo scales."""
    words = {}
    for d in (0, -1):
        for s in range(4):
            words[_row(15 + d, s)] = 0x4000 + (d + 1) * 0x100 + s
    e = _emu(words, recipe={2: (-1, 1)})
    cands = e._slot_candidates({"scale": 15, "chan": 2})
    assert cands[0][1] == (-1, 1)
    # and the recipe for the OTHER channel count must not leak into this one
    e2 = _emu(words, recipe={1: (-1, 1)})
    assert e2._slot_candidates({"scale": 15, "chan": 2})[0][1] == (0, 0)


def test_candidates_are_deduplicated_by_function_pointer():
    """Sub-slots alias heavily; a pointer must be probed once, and keep the
    place it was first reached from."""
    words = {_row(5, s): 0xABCD for s in range(4)}
    for s in range(4):
        words[_row(4, s)] = 0xABCD
    cands = _emu(words)._slot_candidates({"scale": 5, "chan": 1})
    assert cands == [(0xABCD, (0, 0))]


def test_unbacked_pointers_are_rejected():
    """A word that is not a firmware code address is not a codec entry."""
    words = {_row(3, s): 0x900000 + s for s in range(4)}
    words[_row(3, 0)] = 0                       # null
    e = _emu(words, backed=lambda va: None if va == 0x900001 else 1)
    got = [fn for fn, _p in e._slot_candidates({"scale": 3, "chan": 1})]
    assert 0 not in got and 0x900001 not in got
    assert 0x900002 in got


@pytest.mark.parametrize("chan", [1, 2])
def test_no_probe_reads_outside_the_two_rows(chan):
    words = {}
    for d in (0, -1):
        for s in range(4):
            words[_row(20 + d, s)] = 0x5000 + (d + 1) * 0x10 + s
    e = _emu(words)
    e._slot_candidates({"scale": 20, "chan": chan})
    for addr in e.mu.reads:
        assert _row(19, 0) <= addr <= _row(20, 3)
