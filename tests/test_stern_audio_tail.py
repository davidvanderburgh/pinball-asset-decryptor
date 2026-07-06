"""Spike 2 audio re-encode TAIL round-trip guard (heavy; gated on a bundled card).

The codec emits exactly ``length - BLOCK`` samples (see emulator.emitted_length).
Regression guarded here: decode() must return that many samples, and re-encoding
a target whose FINAL partial block is loud must round-trip bit-exact — i.e. the
last <200 samples are no longer dropped (which clicked at the loop point of
looping music).  Covers the validated build (turtles) AND a generic/located
build (led_zeppelin, the title the original bug was reported on).

These boot the firmware in unicorn (~1-2 min/title) and need a 7.8 GB card image
under images/Stern/spike2/, so they skip cleanly in CI where the cards aren't
present.  Extracted game_real/image.bin are cached in the temp dir between runs.
"""
import os
import struct
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.path.join(REPO, "images", "Stern", "spike2")
CARDS = {
    "turtles": "turtles_pro-1_58_0.Release.8G.sdcard.raw",      # validated build
    "led_zeppelin": "led_zeppelin_le-1_20_0.Release.8G.sdcard.raw",  # generic build
}


# --------------------------------------------------------------------------
# Fast unit tests (no card, no boot) — guard the emit-length contract + wiring.
# --------------------------------------------------------------------------

def test_emitted_length_formula():
    from pinball_decryptor.plugins.stern.spike2.emulator import (
        emitted_length, BLOCK)
    assert BLOCK == 200
    assert emitted_length(0) == 0
    assert emitted_length(200) == 0          # one block is the cursor lead-in
    assert emitted_length(150) == 0          # shorter than a block -> nothing
    assert emitted_length(250) == 50
    assert emitted_length(84878) == 84678    # TMNT idx0 (mono)
    assert emitted_length(74750) == 74550    # TMNT idx4 (stereo)


def test_encoders_fit_target_to_emitted_length(monkeypatch):
    """_encode_mono/_encode_stereo must size the re-encode target to the codec's
    TRUE emitted length (length-BLOCK), not the raw header length -- otherwise
    encode_sound drops the user's final ~200 samples (a click at the loop point
    of looping music)."""
    import numpy as np
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern.spike2.emulator import emitted_length

    length = 5000
    want = emitted_length(length)
    assert want == length - 200

    # a source LONGER than the emitted length, so a wrong fit-to-`length` would
    # keep ~200 extra samples that encode_sound then silently drops.
    monkeypatch.setattr(E, "_load_wav", lambda path, stereo, np_: (
        np.ones((length + 500, 2), np.int64) * 1000 if stereo
        else np.ones(length + 500, np.int64) * 1000))

    captured = {}

    class FakeGR:
        def encode_sound(self, pp, tgt):
            captured["mono"] = len(tgt)
            return b""

    class FakeSR:
        def encode_sound(self, pp, L, R):
            captured["L"] = len(L)
            captured["R"] = len(R)
            return b""

    E._encode_mono(None, FakeGR(), {"length": length, "chan": 1}, "x.wav", np)
    E._encode_stereo(None, FakeSR(), {"length": length, "chan": 2}, "x.wav", np)
    assert captured["mono"] == want
    assert captured["L"] == captured["R"] == want


def test_fit_fades_audio_tail_to_zero():
    """_fit must land the end of the actual audio at zero via a short fade:
    a replacement that ends non-zero (hard-trimmed to the slot, DC offset)
    is a step the machine plays as a click at the end of the callout
    (monkeybug, real-HW). Both the truncation point and the last real
    sample before zero-padding are audio ends."""
    import numpy as np
    from pinball_decryptor.plugins.stern.engine import _fit

    loud = np.full(5000, 10000, np.int64)
    fade_n = int(round(5.0 * 44.1))          # ~220 samples

    # Truncated: the cut lands mid-audio -> tail must ramp to 0.
    out = _fit(loud, 4000, np)
    assert len(out) == 4000
    assert out[-1] == 0
    assert out[3999 - fade_n] == 10000        # audio before the fade intact
    assert 0 < out[-fade_n // 2] < 10000      # it's a ramp, not a mute

    # Shorter than the slot: fade sits at the END OF THE AUDIO, then zeros.
    out = _fit(loud[:3000], 4000, np)
    assert len(out) == 4000
    assert out[2999] == 0                     # last real sample faded out
    assert not out[3000:].any()               # padding stays silent
    assert out[1000] == 10000

    # Exact-length audio still gets its tail faded.
    out = _fit(loud[:4000], 4000, np)
    assert out[-1] == 0 and out[0] == 10000

    # Degenerate inputs don't blow up.
    assert len(_fit(np.zeros(0, np.int64), 100, np)) == 100
    assert list(_fit(np.array([5], np.int64), 1, np)) == [5]


def _card_path(title):
    return os.path.join(IMG_DIR, CARDS[title])


def _have(title):
    return os.path.exists(_card_path(title))


def _extract_inputs_cached(title):
    """Extract (and cache in the temp dir) the card's game_real + image.bin."""
    from pinball_decryptor.plugins.stern import engine as E
    work = os.path.join(tempfile.gettempdir(), "pad_stern_tail_" + title)
    gr = os.path.join(work, "game_real")
    img = os.path.join(work, "image.bin")
    if os.path.exists(gr) and os.path.exists(img) and os.path.getsize(img) > 0:
        return gr, img
    os.makedirs(work, exist_ok=True)
    parts = E._linux_partitions(_card_path(title))
    disk_f = open(_card_path(title), "rb")
    try:
        E._extract_inputs(disk_f, parts, work, lambda *a, **k: None)
    finally:
        disk_f.close()
    return gr, img


def _shortest(rows, chan, minlen=600):
    cand = [r for r in rows if r["chan"] == chan and r["length"] > minlen]
    return min(cand, key=lambda r: r["length"]) if cand else None


@pytest.mark.slow
@pytest.mark.parametrize("title", list(CARDS))
def test_decode_length_and_tail_roundtrip(title):
    if not _have(title):
        pytest.skip("card image %s not present" % CARDS[title])
    import numpy as np
    from pinball_decryptor.plugins.stern.spike2.emulator import (
        Spike2Emu, emitted_length)
    from pinball_decryptor.plugins.stern.spike2.codec import (
        GenRecover, StereoRecover)
    from pinball_decryptor.plugins.stern.engine import _BodyOverlay

    gr_path, img_path = _extract_inputs_cached(title)
    emu = Spike2Emu(gr_path, img_path)
    if not emu.audio_supported:
        emu.close()
        pytest.skip("audio decode not supported for %s" % title)
    emu.boot()
    rows = emu.derive_params()
    gr = GenRecover(emu)
    sr = StereoRecover(emu)

    checked = 0
    for chan in (1, 2):
        p = _shortest(rows, chan)
        if p is None:
            continue
        length = p["length"]
        emit = emitted_length(length)
        tail = (length % 200) or 200          # size of the final partial block

        out = emu.decode(p)
        assert out is not None, "%s idx%d decode failed" % (title, p["idx"])
        L = np.asarray(out[0], np.int64)
        R = np.asarray(out[1], np.int64)
        # (1) decode returns exactly the emitted length (no trailing padding).
        assert len(L) == emit, (
            "%s idx%d: decode len %d != emitted_length %d"
            % (title, p["idx"], len(L), emit))

        # (2) force a LOUD, varied final partial block and re-encode it; the
        # round-trip must reproduce it bit-exact (old bug: the tail was dropped
        # to zeros).  Re-encode via the codec directly so the target is exact.
        ramp = (np.arange(tail) * 173 % 6000 + 1500).astype(np.int64)
        tgtL = L.copy(); tgtL[-tail:] = ramp
        if chan == 2:
            tgtR = R.copy(); tgtR[-tail:] = -ramp
            body = sr.encode_sound(p, tgtL, tgtR)
        else:
            tgtR = None
            body = gr.encode_sound(p, tgtL)

        # patch the one body in-memory (the patched sound's own params don't
        # shift -- the masterdir chain is forward-only -- so decoding it with the
        # same params is faithful, exactly as _recovery_valid relies on).
        if not isinstance(emu.mm, _BodyOverlay):
            emu.mm = _BodyOverlay(emu.mm)
        emu.mm.patch = (p["body_off"], bytes(body))
        try:
            out2 = emu.decode(p)
        finally:
            emu.mm.patch = None
        assert out2 is not None
        L2 = np.asarray(out2[0], np.int64)
        R2 = np.asarray(out2[1], np.int64)
        m = min(len(L2), emit)
        assert int(np.count_nonzero(L2[:m] != tgtL[:m])) == 0, (
            "%s idx%d: mono round-trip not bit-exact" % (title, p["idx"]))
        # the final partial block specifically must be present + correct
        assert int(np.count_nonzero(L2[emit - tail:emit] != tgtL[emit - tail:emit])) == 0
        assert int(np.count_nonzero(L2[emit - tail:emit])) >= tail - 2, (
            "%s idx%d: final block decoded to (near) silence -- tail dropped"
            % (title, p["idx"]))
        if chan == 2:
            mr = min(len(R2), emit)
            assert int(np.count_nonzero(R2[:mr] != tgtR[:mr])) == 0, (
                "%s idx%d: stereo R round-trip not bit-exact" % (title, p["idx"]))
        checked += 1

    emu.close()
    assert checked >= 1, "%s: no codec-0 sound found to test" % title
