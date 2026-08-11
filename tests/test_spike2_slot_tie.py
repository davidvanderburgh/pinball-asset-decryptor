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
