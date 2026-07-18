"""Shared-boundary word resolution (Spike 2, delta<0 encode windows).

The head word of a delta<0 encode window physically lives in the
layout-predecessor's slot, and hardware decodes that storage twice — once
with each sound's keystream.  ``pick_shared_word`` must keep the
PREDECESSOR side essentially exact (its contested sample lands at the end of
its faded-out tail, where the old ``enc[0]`` choice decoded as a random
up-to-full-scale pop — the Elvira HoH spinner click), while reporting the
signed sample our own side gets so the engine can absorb it with a decay
ramp.  Pure math — no emulator needed.
"""
import numpy as np

from pinball_decryptor.plugins.stern.spike2.codec import (
    _invG, _rolv, _rorv, decode_word, pick_shared_word)

QMUL = 22294        # ~mono scale: decode spans about +/-11147


def _encode_single(target, K, rb):
    """The encoder's own single-context choice for one word (enc[0])."""
    S, _ = _invG(np.array([target], np.int64), QMUL)
    return int(_rolv((int(S[0]) ^ K) & 0xffff, rb))


def test_decode_word_matches_encode_roundtrip():
    # decode_word must invert the encoder's word construction.
    for t in (-9000, -500, -1, 0, 3, 777, 11000):
        for K, rb in ((0x1234, 3), (0xBEEF, 0), (0x00FF, 15)):
            w = _encode_single(t, K, rb)
            got = decode_word(w, rb, K, QMUL)
            assert abs(got - t) <= 1, (t, K, rb, got)


def test_pred_side_is_essentially_exact():
    # The whole point: whatever the two keystreams are, the neighbor's
    # contested sample must stay within a few counts of its stock value
    # (the decode map is onto the quantized output range, so an exact-ish
    # word always exists; the old enc[0] choice measured +7389 off on EHOH).
    rng = np.random.RandomState(42)
    for _ in range(40):
        Kp, Ks = int(rng.randint(0x10000)), int(rng.randint(0x10000))
        rp, rs = int(rng.randint(16)), int(rng.randint(16))
        tp = int(rng.randint(-40, 40))      # quiet stock tail
        w, pred_err, self_val = pick_shared_word(
            (rp, Kp, QMUL, tp), (rs, Ks, QMUL, 0))
        assert pred_err <= 3, (Kp, Ks, rp, rs, pred_err)
        assert decode_word(w, rp, Kp, QMUL) == \
            pred_err + tp or abs(decode_word(w, rp, Kp, QMUL) - tp) == pred_err
        # self_val is reported faithfully (the engine ramps it away)
        assert decode_word(w, rs, Ks, QMUL) == self_val
        assert abs(self_val) <= QMUL // 2 + 1


def test_self_side_uses_remaining_freedom():
    # Among the pred-optimal candidates the pick must favor our target: with
    # identical contexts both sides can be exact at once.
    K, r, t = 0x5A5A, 7, -1234
    w, pred_err, self_val = pick_shared_word((r, K, QMUL, t), (r, K, QMUL, t))
    assert pred_err <= 1 and abs(self_val - t) <= 3


def test_stereo_coupling_folds_into_x():
    # The u1 context folds KR ^ ROR(u0, aR) into x — spot-check the algebra by
    # simulating the stereo decode of a chosen u1.
    KR, bR, aR, u0 = 0x1111, 5, 9, 0xABCD
    x = KR ^ _rorv(u0, aR)
    t = -20
    w, pred_err, _ = pick_shared_word((bR, x, QMUL, t), (3, 0x77, QMUL, 0))
    S = (_rorv(w, bR) ^ KR ^ _rorv(u0, aR)) & 0xffff
    v = S - 0x10000 if S & 0x8000 else S
    assert abs(((QMUL * v) >> 16) - t) == pred_err <= 3
