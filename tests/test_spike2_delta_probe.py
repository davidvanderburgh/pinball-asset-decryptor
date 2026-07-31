"""Body-word offset (delta) probe robustness — fast, no card, no boot.

The probe marks body words with 0xFFFF and finds the sample whose recovered
S^K equals 0xFFFF.  Two UNRELATED keystream samples XOR to 0xFFFF once in
65536, so across ~200 samples per probe ~0.3% of sounds carry a false hit; on
a big catalog (Deadpool Pro 1.16: 8175 sounds) that is ~25 sounds.  Taking the
first hit mis-calibrated those: idx7146 collided at i=5 and produced delta=+5,
which shifted the whole encode window and made its re-encode decode to noise
(only 3 of 2708 samples survived).

Guarded here: two markers, and only a consistent PAIR is accepted.
"""
import pytest

from pinball_decryptor.plugins.stern.spike2.codec import (
    DELTA_MAX, DELTA_MIN, DELTA_Q1, DELTA_Q2, _delta_from_hits)


def _true_hits(delta, q1=DELTA_Q1, q2=DELTA_Q2):
    """Indices a correctly-marked probe produces for a given delta."""
    return [q1 - delta, q2 - delta]


@pytest.mark.parametrize("delta", [0, -1, -2, -3, -4])
def test_clean_probe_recovers_delta(delta):
    """With no noise, both markers land and the pair yields delta exactly."""
    assert _delta_from_hits(_true_hits(delta)) == delta


@pytest.mark.parametrize("collision", [0, 1, 3, 5, 7, 9])
def test_early_collision_is_ignored(collision):
    """A lone false hit BEFORE the real marker must not win -- this is the
    Deadpool idx7146 failure (collision at i=5 -> delta=+5)."""
    delta = -1
    hits = sorted(set([collision] + _true_hits(delta)))
    assert _delta_from_hits(hits) == delta


def test_idx7146_exact_shape():
    """The real capture: true delta -1 (markers at 11 and 38) plus the noise
    hit at 5 that the old first-hit rule turned into delta=+5."""
    hits = [5, 11, 38]
    assert _delta_from_hits(hits) == -1
    # the old rule, for the record: first hit wins -> DELTA_Q1 - 5 == 5
    assert DELTA_Q1 - hits[0] == 5


def test_multiple_collisions_ignored():
    delta = -2
    hits = sorted(set([2, 4, 9, 20, 33] + _true_hits(delta)))
    assert _delta_from_hits(hits) == delta


def test_late_collision_ignored():
    """A false hit AFTER the pair must not displace it either."""
    delta = 0
    hits = sorted(set(_true_hits(delta) + [90, 120]))
    assert _delta_from_hits(hits) == delta


def test_collision_pair_far_from_step_is_ignored():
    """Two collisions that are NOT q2-q1 apart never form a pair."""
    delta = -1
    step = DELTA_Q2 - DELTA_Q1
    hits = sorted(set([3, 3 + step + 1] + _true_hits(delta)))
    assert _delta_from_hits(hits) == delta


def test_single_marker_fallback_within_plausible_range():
    """If only ONE marker registered (e.g. the second sits past the emitted
    range of a very short sound), accept it — but only as a plausible delta."""
    assert _delta_from_hits([DELTA_Q1 + 1]) == -1
    assert _delta_from_hits([DELTA_Q1]) == 0


def test_single_implausible_hit_falls_back_to_zero():
    """A lone hit implying a positive or wildly negative delta is noise, not a
    measurement: fall back to 0 rather than shifting the window by it."""
    assert _delta_from_hits([5]) == 0            # would have been +5
    assert _delta_from_hits([0]) == 0            # would have been +10
    assert _delta_from_hits([DELTA_Q1 - DELTA_MIN + 5]) == 0


def test_no_hits_is_zero():
    assert _delta_from_hits([]) == 0


def test_plausible_range_excludes_positive():
    """A positive delta means a sample reading a body word AHEAD of itself; no
    build does that, and accepting one is exactly the shipped bug."""
    assert DELTA_MAX == 0
    assert DELTA_MIN < 0


def test_markers_far_enough_apart():
    """The two markers must be separated by more than the plausible delta span,
    otherwise a shifted marker could be mistaken for its partner."""
    assert DELTA_Q2 - DELTA_Q1 > (DELTA_MAX - DELTA_MIN)


def test_both_probes_use_the_shared_constants():
    """Mono and stereo must probe identically -- the stereo path carried the
    same first-hit flaw and has to stay fixed with it."""
    import inspect

    from pinball_decryptor.plugins.stern.spike2 import codec as CD
    for fn in (CD.GenRecover._calibrate, CD.StereoRecover._calibrate):
        src = inspect.getsource(fn)
        assert "DELTA_Q1" in src and "DELTA_Q2" in src, fn
        assert "_delta_from_hits" in src, fn
