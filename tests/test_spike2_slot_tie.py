"""Codec-slot resolution must not depend on which sound seeds it (fast; no boot,
no card).

A generic Spike 2 build reaches its audio codec through four dispatch sub-slots
per scale, and two of them are the SAME codec a second way: they decode the same
stream, one starting a body word earlier.  ``_resolve_entry``'s second pass used
to rank the survivors by spectral flatness and take the minimum, so a difference
of ~1e-5 -- pure measurement jitter between two equivalent entries -- chose the
winner.

Extract decodes the catalog across worker processes that each cache their own
(scale, chan) map, seeded by whichever sound that worker happened to reach first,
so the choice flipped between runs.  When the "one word earlier" entry won, every
sound of that scale came out shifted a sample with the layout predecessor's body
word as sample 0: on Star Wars LE 1.30 idx0088 that lone sample is 11326 of the
21452 stereo range, in front of an otherwise silent head.

:func:`pick_slot` resolves the tie by dispatch order instead, which is both
stable and the sub-slot convention the validated build uses in ``codec_fns``.
"""
import pytest

from pinball_decryptor.plugins.stern.spike2.emulator import Spike2Emu, pick_slot

TIE = Spike2Emu._SLOT_TIE

# Real specflat scores, Star Wars LE 1.30 scale 2 / chan 2 (stereo), probed over
# 3.5 s.  Slots 0 and 2 are the audio codec twice; 1 and 3 are the mono codec fed
# a stereo body.  The pool reaching pick_slot is in dispatch order.
SW_S2_AUDIO_LOW = [(0x27CCF0, 0.42100), (0x27C2F8, 0.42099)]   # slot0, slot2
SW_S2_AUDIO_HIGH = [(0x27CCF0, 0.42099), (0x27C2F8, 0.42100)]


@pytest.mark.parametrize("pool", [SW_S2_AUDIO_LOW, SW_S2_AUDIO_HIGH])
def test_equivalent_twins_always_resolve_to_the_lower_slot(pool):
    """Whichever twin measures marginally flatter, the lower dispatch slot wins
    -- otherwise the answer flips with the seeding sound."""
    assert pick_slot(pool, TIE) == 0x27CCF0


def test_twin_order_in_the_pool_does_not_change_the_answer():
    """Same two entries, and the one that scores lower is listed second: the
    old ``min`` rule returned it, which is the flip this guards."""
    assert pick_slot([(0x27CCF0, 0.42100), (0x27C2F8, 0.42099)], TIE) == 0x27CCF0


def test_wrong_codec_never_wins_on_slot_order():
    """Order only breaks TIES.  A candidate that is genuinely worse loses even
    though it sits earlier in dispatch order."""
    # mono codec fed a stereo body sits ~0.42 away from the audio codec here
    pool = [(0xDEAD00, 0.845), (0x27CCF0, 0.421)]
    assert pick_slot(pool, TIE) == 0x27CCF0


def test_tie_window_separates_twins_from_the_wrong_codec():
    """The window has to be wider than the twins' jitter and narrower than the
    gap to the wrong codec.  Measured over 200 Star Wars LE 1.30 sounds:
    twins differ by at most 6e-5, the wrong codec by at least 0.0993."""
    assert 6e-5 < TIE < 0.0993


def test_single_candidate_and_empty_pool():
    assert pick_slot([(0x1234, 0.9)], TIE) == 0x1234
    assert pick_slot([], TIE) is None


def test_first_within_tie_wins_not_merely_the_first_entry():
    """A leading candidate outside the window is skipped for the next one that
    is inside it."""
    pool = [(0xAAA, 0.90), (0xBBB, 0.40), (0xCCC, 0.4001)]
    assert pick_slot(pool, TIE) == 0xBBB


# ---------------------------------------------------------------------------
# _resolve_entry: pass 1 and the candidate ORDER have to obey the same rule
# (PAD-77, Godzilla LE 1.13 -- 29 of 2523 sounds decoded differently between
# two runs of the same card because they didn't).
# ---------------------------------------------------------------------------

# One scale's four dispatch sub-slots, row 0: 0 = stereo codec, 1 = the mono
# codec (the right one for a mono sound), 2 and 3 the same two a second way.
FN = {(0, 0): 0xA000, (0, 1): 0xA004, (0, 2): 0xA008, (0, 3): 0xA00C,
      (-1, 0): 0xB000, (-1, 1): 0xB004, (-1, 2): 0xB008, (-1, 3): 0xB00C}


def _emu(metrics):
    """A Spike2Emu with no card behind it: only the slot resolution is real.

    *metrics* is ``{(place, secs): (specflat, rms)}``; anything unlisted reads
    as the wrong codec (loud noise), which is what the other sub-slots are.
    """
    emu = Spike2Emu.__new__(Spike2Emu)
    emu._slot_cache = {}
    emu._slot_candidates = lambda p: [(FN[pl], pl) for pl in
                                      ((0, 0), (0, 1), (0, 2), (0, 3),
                                       (-1, 0), (-1, 1), (-1, 2), (-1, 3))]
    place_of = {v: k for k, v in FN.items()}
    emu._slot_metrics = lambda p, fnv, secs: metrics.get(
        (place_of[fnv], secs), (0.85, 12400.0))
    return emu, place_of


def test_silent_head_does_not_hand_pass_one_to_the_alias():
    """The real Godzilla LE numbers for idx0040 (scale 2, mono).

    Its first 0.6 s is digital silence, so the CORRECT entry scores 1.0 there
    (the flat-signal guard in _specflat) while the alias -- whose extra
    predecessor word is a click in that silence -- scores 0.0 and reads as
    "clearly audio".  Pass 1 must decline the alias and let pass 2, which
    sees the two score identically over 3.5 s, keep the lower sub-slot.
    """
    emu, place_of = _emu({
        ((0, 0), 0.6): (0.6696, 6407.0), ((0, 0), 3.5): (0.6639, 6446.0),
        ((0, 1), 0.6): (1.0000, 1346.0), ((0, 1), 3.5): (0.2222, 3499.0),
        ((0, 2), 0.6): (0.8398, 6400.0), ((0, 2), 3.5): (0.8449, 6436.0),
        ((0, 3), 0.6): (0.0000, 1347.0), ((0, 3), 3.5): (0.2222, 3499.0),
    })
    got = emu._resolve_entry({"scale": 2, "chan": 1, "idx": 40})
    assert place_of[got] == (0, 1)


def test_loud_sound_still_resolves_on_the_cheap_first_pass():
    """The common case is untouched: sub-slot 1 is clearly audio at 0.6 s, so
    it wins without the 3.5 s re-probe (which this metrics map has no entry
    for -- reaching pass 2 would answer the wrong codec)."""
    emu, place_of = _emu({((0, 1), 0.6): (0.0221, 3089.0)})
    got = emu._resolve_entry({"scale": 5, "chan": 1, "idx": 96})
    assert place_of[got] == (0, 1)


def test_the_answer_does_not_depend_on_which_scale_came_first():
    """A worker that resolves several scales must answer each one the same way
    it would have on its own.  This is the cascade: the winning place used to
    be remembered per channel and probed FIRST for every later scale, where
    the twins score a dead tie -- so one quiet-intro sound flipped every later
    mono sound in that worker onto the alias."""
    metrics = {
        ((0, 0), 0.6): (0.6696, 6407.0), ((0, 0), 3.5): (0.6639, 6446.0),
        ((0, 1), 0.6): (1.0000, 1346.0), ((0, 1), 3.5): (0.2222, 3499.0),
        ((0, 2), 0.6): (0.8398, 6400.0), ((0, 2), 3.5): (0.8449, 6436.0),
        ((0, 3), 0.6): (0.0000, 1347.0), ((0, 3), 3.5): (0.2222, 3499.0),
    }
    emu, place_of = _emu(metrics)
    emu._resolve_entry({"scale": 2, "chan": 1, "idx": 40})     # the quiet one
    # a later scale whose twins tie on the cheap probe, as they always do
    tied = dict(metrics)
    tied[((0, 1), 0.6)] = tied[((0, 3), 0.6)] = (0.0304, 4552.0)
    emu2, _ = _emu(tied)
    alone = emu2._resolve_entry({"scale": 16, "chan": 1, "idx": 41})
    emu._slot_metrics = emu2._slot_metrics
    after = emu._resolve_entry({"scale": 16, "chan": 1, "idx": 41})
    assert place_of[after] == place_of[alone] == (0, 1)


def test_an_alias_only_build_still_resolves():
    """Declining the alias in pass 1 must not lose a build that really does
    keep its only audio entry there: pass 2 scores everything and takes it."""
    emu, place_of = _emu({((0, 3), 0.6): (0.02, 3000.0),
                          ((0, 3), 3.5): (0.03, 3000.0)})
    got = emu._resolve_entry({"scale": 7, "chan": 1, "idx": 1})
    assert place_of[got] == (0, 3)


def test_candidates_are_offered_in_dispatch_order():
    """The real _slot_candidates walk, against a fake dispatch table: every
    place, own row first, low sub-slot first, and no history in the order."""
    emu = Spike2Emu.__new__(Spike2Emu)
    emu.DISPATCH = 0x1000
    emu._segs = [(0, 0, 0x100000, 0x100000)]

    class _Mu:
        @staticmethod
        def mem_read(addr, n):
            return (addr & 0xFFFF).to_bytes(4, "little")

    emu.mu = _Mu()
    places = [pl for _fn, pl in emu._slot_candidates({"scale": 2, "chan": 1})]
    assert places == [(0, 0), (0, 1), (0, 2), (0, 3),
                      (-1, 0), (-1, 1), (-1, 2), (-1, 3)]
