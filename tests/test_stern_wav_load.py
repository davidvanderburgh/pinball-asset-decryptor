"""Tests for the Spike 2 replacement-WAV loader and the loudness fit.

A tester's callouts exported at their editor's default bit depth encoded to
pure static: the old loader read every WAV as 16-bit PCM.  These tests pin the
fix — every common editor export (8/16/24/32-bit int, 32/64-bit float, any
sample rate) must decode to the same sine — and the match-original-loudness
gain (their other report: replacements were clearly quieter than stock).
"""

import struct
import wave

import numpy as np
import pytest

from pinball_decryptor.plugins.stern.engine import (
    _load_wav, _fit_level, _amplitude_fit, _MONO_RANGE)


def _sine(rate, secs=0.25, hz=440.0, amp=0.5):
    t = np.arange(int(rate * secs)) / rate
    return amp * np.sin(2 * np.pi * hz * t)


def _write_pcm(path, s, sampwidth, rate):
    w = wave.open(str(path), "wb")
    w.setnchannels(1)
    w.setsampwidth(sampwidth)
    w.setframerate(rate)
    if sampwidth == 1:
        w.writeframes((s * 127 + 128).astype("u1").tobytes())
    elif sampwidth == 2:
        w.writeframes((s * 32767).astype("<i2").tobytes())
    elif sampwidth == 3:
        v = (s * 8388607).astype("<i4").tobytes()
        w.writeframes(b"".join(v[i:i + 3] for i in range(0, len(v), 4)))
    elif sampwidth == 4:
        w.writeframes((s * 2147483647).astype("<i4").tobytes())
    w.close()


def _write_float(path, s, rate, bits=32):
    data = s.astype("<f4" if bits == 32 else "<f8").tobytes()
    blk = bits // 8
    hdr = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    hdr += b"fmt " + struct.pack("<IHHIIHH", 16, 3, 1, rate, rate * blk,
                                 blk, bits)
    hdr += b"data" + struct.pack("<I", len(data))
    path.write_bytes(hdr + data)


def _tonality(a):
    """Energy fraction near 440 Hz — 1.0 for a clean tone, ~0 for static."""
    a = np.asarray(a, np.float64)
    S = np.abs(np.fft.rfft(a * np.hanning(len(a)))) ** 2
    f = np.fft.rfftfreq(len(a), 1 / 44100.0)
    return float(S[(f > 380) & (f < 500)].sum() / max(S.sum(), 1e-9))


@pytest.mark.parametrize("sampwidth,rate", [
    (1, 44100), (2, 44100), (2, 24000), (2, 48000),
    (3, 44100), (3, 48000), (4, 44100)])
def test_pcm_formats_decode_clean(tmp_path, sampwidth, rate):
    p = tmp_path / "t.wav"
    _write_pcm(p, _sine(rate), sampwidth, rate)
    s = _load_wav(str(p), False, np)
    assert len(s) == pytest.approx(44100 * 0.25, abs=2)
    assert _tonality(s) > 0.9, "decoded to noise — bit depth misread"
    pk = int(np.abs(s).max())
    assert 14000 < pk < 17500          # ~0.5 full scale survives the convert


@pytest.mark.parametrize("bits", [32, 64])
def test_float_formats_decode_clean(tmp_path, bits):
    p = tmp_path / "f.wav"
    _write_float(p, _sine(44100), 44100, bits)
    s = _load_wav(str(p), False, np)
    assert _tonality(s) > 0.9
    assert 14000 < int(np.abs(s).max()) < 17500


def test_stereo_and_downmix(tmp_path):
    s = _sine(44100)
    p = tmp_path / "st.wav"
    w = wave.open(str(p), "wb")
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100)
    inter = np.empty(len(s) * 2)
    inter[0::2] = s; inter[1::2] = s
    w.writeframes((inter * 32767).astype("<i2").tobytes())
    w.close()
    st = _load_wav(str(p), True, np)
    assert st.shape[1] == 2
    mono = _load_wav(str(p), False, np)
    assert _tonality(mono) > 0.9


# ---- loudness matching ---------------------------------------------------

def test_fit_level_matches_original_rms():
    rng = _MONO_RANGE
    # "stock": compressed voice — high RMS for its peak
    orig = np.round(np.sign(np.sin(np.linspace(0, 60, 44100)))
                    * rng * 0.9).astype(np.int64)
    # replacement: same shape but much quieter
    repl = (orig * 0.2).astype(np.int64)
    out = _fit_level(repl, orig, rng, np, headroom=0.97)
    orms = np.sqrt((orig.astype(float) ** 2).mean())
    rms = np.sqrt((out.astype(float) ** 2).mean())
    assert rms == pytest.approx(orms, rel=0.05)


def test_fit_level_respects_peak_ceiling():
    rng = _MONO_RANGE
    orig = np.round(np.sign(np.sin(np.linspace(0, 60, 44100)))
                    * rng * 0.9).astype(np.int64)          # square: RMS==peak
    repl = np.round(np.sin(np.linspace(0, 60, 44100))      # sine: RMS=peak/√2
                    * 1000).astype(np.int64)
    out = _fit_level(repl, orig, rng, np, headroom=0.97)
    assert int(np.abs(out).max()) <= int(rng * 0.97) + 1


def test_fit_level_falls_back_without_reference():
    rng = _MONO_RANGE
    repl = np.round(np.sin(np.linspace(0, 60, 4410)) * 1000).astype(np.int64)
    out = _fit_level(repl, None, rng, np, headroom=0.97)
    ref = _amplitude_fit(repl, rng, np, headroom=0.97)
    assert (out == ref).all()
    # a near-silent original is no reference either
    silent = np.zeros(4410, np.int64)
    out = _fit_level(repl, silent, rng, np, headroom=0.97)
    assert (out == ref).all()


def test_fit_level_kill_switch(monkeypatch):
    rng = _MONO_RANGE
    orig = np.round(np.sign(np.sin(np.linspace(0, 60, 4410)))
                    * rng * 0.9).astype(np.int64)
    repl = (orig * 0.2).astype(np.int64)
    from pinball_decryptor.plugins.stern import engine
    monkeypatch.setenv("PAD_STERN_MATCH_LOUDNESS", "0")
    assert not engine._match_loudness_enabled()
    monkeypatch.delenv("PAD_STERN_MATCH_LOUDNESS", raising=False)
    assert engine._match_loudness_enabled()


def test_fit_level_does_not_limit_when_it_did_not_boost_past_the_ceiling():
    """The soft limiter must engage only when the gain actually pushed peaks
    past the ceiling.  Running it unconditionally shaves the loudest 30% of
    audio that needed nothing, making the result quieter than doing nothing at
    all — the opposite of matching.  Here the match gain lands the peak under
    the ceiling, so the output is a pure scaling of the input."""
    rng = _MONO_RANGE
    t = np.linspace(0, 60, 44100)
    orig = np.round(np.sin(t) * rng * 0.7).astype(np.int64)
    repl = np.round(np.sin(t) * 3000).astype(np.int64)      # same shape, quiet
    out = _fit_level(repl, orig, rng, np, headroom=0.97)
    assert int(np.abs(out).max()) < int(rng * 0.97)         # never hit the knee
    gain = float(np.abs(out).max()) / float(np.abs(repl).max())
    assert np.allclose(out, np.round(repl * gain), atol=1)  # pure scaling


def test_fit_level_recovers_loudness_lost_to_a_transient_peak():
    """The case peak-normalizing cannot fix: one stray transient (a lip smack,
    a desk knock) holds the whole recording down, so normalizing to the peak
    leaves the speech far below stock.  Matching has to lift the body and
    limit the transient."""
    rng = _MONO_RANGE
    t = np.linspace(0, 400, 44100)
    orig = np.round(np.sin(t) * rng * 0.9).astype(np.int64)
    repl = np.round(np.sin(t) * rng * 0.15).astype(np.int64)
    repl[1000] = rng                       # the transient
    repl[1001] = -rng

    plain = _amplitude_fit(repl, rng, np, headroom=0.97)
    out = _fit_level(repl, orig, rng, np, headroom=0.97)

    body = slice(2000, None)               # past the transient
    rms = lambda v: float(np.sqrt((v[body].astype(float) ** 2).mean()))
    assert rms(out) > rms(plain) * 3       # ~+10 dB of body level recovered
    assert rms(out) == pytest.approx(rms(orig), rel=0.15)
    # and the ceiling still holds, so the codec range is never exceeded
    # (+1 for the rounding at the limiter's asymptote)
    assert int(np.abs(out).max()) <= int(rng * 0.97) + 1
    assert int(np.abs(out).max()) < rng


def test_fit_level_boost_is_bounded():
    """A near-dead source must not be lifted without limit — the cap keeps a
    whisper from being amplified into its own noise floor."""
    from pinball_decryptor.plugins.stern.engine import _MATCH_MAX_GAIN
    rng = _MONO_RANGE
    t = np.linspace(0, 400, 44100)
    orig = np.round(np.sin(t) * rng * 0.9).astype(np.int64)
    repl = np.round(np.sin(t) * 20).astype(np.int64)        # ~-60 dBFS
    out = _fit_level(repl, orig, rng, np, headroom=0.97)
    assert int(np.abs(out).max()) <= int(20 * _MATCH_MAX_GAIN) + 1


def test_fit_level_also_brings_a_too_loud_replacement_down():
    """Matching runs both ways: a hot, heavily-compressed source (a music clip
    dropped onto a quiet callout slot) is brought DOWN to the slot's own
    level, where peak-normalizing would have left it far louder than every
    sound around it."""
    rng = _MONO_RANGE
    t = np.linspace(0, 400, 44100)
    orig = np.round(np.sin(t) * rng * 0.15).astype(np.int64)     # quiet stock
    repl = np.round(np.sign(np.sin(t)) * rng * 0.9).astype(np.int64)  # hot
    out = _fit_level(repl, orig, rng, np, headroom=0.97)
    plain = _amplitude_fit(repl, rng, np, headroom=0.97)
    rms = lambda v: float(np.sqrt((v.astype(float) ** 2).mean()))
    assert rms(out) < rms(plain)
    assert rms(out) == pytest.approx(rms(orig), rel=0.15)


def test_soft_limit_is_monotonic_and_bounded():
    from pinball_decryptor.plugins.stern.engine import _soft_limit
    x = np.linspace(-30000, 30000, 4001)
    y = _soft_limit(x, 10000.0, np)
    assert np.all(np.diff(y) >= 0)          # monotonic: no fold-back
    assert np.abs(y).max() < 10000.0        # asymptotic to the ceiling
    small = np.abs(x) <= 0.7 * 10000.0      # under the knee: untouched
    assert np.allclose(y[small], x[small])


# ---- the user's own mix level, and the offset that restores it -----------
#
# PAD-90 (a tester, Godzilla music imports): "I mixed them loud but the edit
# didn't seem to make a big change, is PAD adjusting them on import?"  It is,
# and the match is scale-INVARIANT, so remixing louder is a literal no-op.
# These pin that (so it stays a documented behavior rather than a surprise)
# and the "Replacement loudness" offset that lets him sit above stock anyway.

def test_matching_ignores_the_level_the_user_mixed_at():
    """The reason a hotter re-export changes nothing: gain is orms/arms, so
    the same track exported at four different levels encodes identically."""
    rng = _MONO_RANGE
    t = np.linspace(0, 400, 44100)
    orig = np.round(np.sin(t) * rng * 0.35).astype(np.int64)
    base = np.sin(t) + 0.3 * np.sin(3 * t)
    outs = [_fit_level(np.round(base * rng * s).astype(np.int64), orig, rng,
                       np, headroom=0.97)
            for s in (0.2, 0.4, 0.7, 0.95)]
    for o in outs[1:]:
        assert np.abs(o - outs[0]).max() <= 2          # rounding only


def test_loudness_offset_lifts_the_match(monkeypatch):
    """+6 dB on top of the match really is ~2x the energy — the lever the
    scale-invariant match leaves the user."""
    from pinball_decryptor.plugins.stern import engine
    rng = _MONO_RANGE
    t = np.linspace(0, 400, 44100)
    orig = np.round(np.sin(t) * rng * 0.25).astype(np.int64)
    repl = np.round(np.sin(t) * rng * 0.9).astype(np.int64)
    flat = _fit_level(repl, orig, rng, np, headroom=0.97)
    monkeypatch.setenv("PAD_STERN_MATCH_GAIN_DB", "6")
    assert engine._match_gain_db() == pytest.approx(6.0)
    loud = _fit_level(repl, orig, rng, np, headroom=0.97)
    rms = lambda v: float(np.sqrt((v.astype(float) ** 2).mean()))
    assert rms(loud) == pytest.approx(rms(flat) * 2.0, rel=0.05)
    assert int(np.abs(loud).max()) <= int(rng * 0.97) + 1


def test_loudness_offset_cuts_and_is_clamped(monkeypatch):
    from pinball_decryptor.plugins.stern import engine
    rng = _MONO_RANGE
    t = np.linspace(0, 400, 44100)
    orig = np.round(np.sin(t) * rng * 0.25).astype(np.int64)
    repl = np.round(np.sin(t) * rng * 0.9).astype(np.int64)
    flat = _fit_level(repl, orig, rng, np, headroom=0.97)
    monkeypatch.setenv("PAD_STERN_MATCH_GAIN_DB", "-6")
    quiet = _fit_level(repl, orig, rng, np, headroom=0.97)
    rms = lambda v: float(np.sqrt((v.astype(float) ** 2).mean()))
    assert rms(quiet) == pytest.approx(rms(flat) / 2.0, rel=0.05)
    # clamped both ways, and junk is ignored
    monkeypatch.setenv("PAD_STERN_MATCH_GAIN_DB", "99")
    assert engine._match_gain_db() == engine._MATCH_GAIN_DB_MAX
    monkeypatch.setenv("PAD_STERN_MATCH_GAIN_DB", "-99")
    assert engine._match_gain_db() == -engine._MATCH_GAIN_DB_MAX
    monkeypatch.setenv("PAD_STERN_MATCH_GAIN_DB", "loud please")
    assert engine._match_gain_db() == 0.0


def test_loudness_offset_applies_without_a_reference_too(monkeypatch):
    """"Normalize to full scale" (no reference) also honours the offset, and a
    boost there limits instead of clipping — peak-normalizing already parked
    the peak on the cap."""
    rng = _MONO_RANGE
    t = np.linspace(0, 400, 44100)
    repl = np.round(np.sin(t) * 3000).astype(np.int64)
    monkeypatch.setenv("PAD_STERN_MATCH_GAIN_DB", "-6")
    out = _fit_level(repl, None, rng, np, headroom=0.97)
    plain = _amplitude_fit(repl, rng, np, headroom=0.97)
    rms = lambda v: float(np.sqrt((v.astype(float) ** 2).mean()))
    assert rms(out) == pytest.approx(rms(plain) / 2.0, rel=0.05)
    monkeypatch.setenv("PAD_STERN_MATCH_GAIN_DB", "6")
    up = _fit_level(repl, None, rng, np, headroom=0.97)
    assert rms(up) > rms(plain)
    assert int(np.abs(up).max()) <= int(rng * 0.97) + 1


def test_default_offset_leaves_the_shipped_behavior_alone():
    """No env var set = byte-identical to before the offset existed."""
    rng = _MONO_RANGE
    t = np.linspace(0, 400, 44100)
    orig = np.round(np.sin(t) * rng * 0.25).astype(np.int64)
    repl = np.round(np.sin(t) * rng * 0.9).astype(np.int64)
    out = _fit_level(repl, orig, rng, np, headroom=0.97)
    orms = float(np.sqrt((orig.astype(float) ** 2).mean()))
    assert float(np.sqrt((out.astype(float) ** 2).mean())) == pytest.approx(
        orms, rel=0.05)
    # and the no-reference path is still exactly _amplitude_fit
    assert (_fit_level(repl, None, rng, np, headroom=0.97)
            == _amplitude_fit(repl, rng, np, headroom=0.97)).all()


def test_loudness_log_phrase_names_the_setting(monkeypatch):
    """The build log has to say the user's own mix level was not carried over
    — a scale-invariant match is otherwise invisible."""
    from pinball_decryptor.plugins.stern import engine
    txt = engine._loudness_log_phrase()
    assert "matched to the level" in txt and "Replacement loudness" in txt
    monkeypatch.setenv("PAD_STERN_MATCH_GAIN_DB", "6")
    assert "+6.0 dB" in engine._loudness_log_phrase()
    monkeypatch.setenv("PAD_STERN_MATCH_LOUDNESS", "0")
    assert "full scale" in engine._loudness_log_phrase()
