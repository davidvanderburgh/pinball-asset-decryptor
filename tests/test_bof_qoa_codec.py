"""Unit tests for the pure-Python QOA codec.

QOA is BOF's chosen audio compression for ~70% of Dune's .sample
files.  These tests build small synthetic PCM streams, round-trip
through encode + decode, and verify the reconstructed audio is
close enough to the original to be acoustically clean.
"""

import struct

import pytest

from pinball_decryptor.plugins.bof.qoa_codec import (
    decode, encode, _DEQUANT, _SF_TAB,
)


def _make_silence_pcm(samples, channels=1):
    """Interleaved 16-bit LE silence."""
    return b"\x00\x00" * (samples * channels)


def _make_sine_pcm(samples, channels=1, freq=440, rate=44100, amp=0.5):
    """Interleaved 16-bit LE sine wave."""
    import math
    out = bytearray()
    for i in range(samples):
        v = int(amp * 32767 * math.sin(2 * math.pi * freq * i / rate))
        for _ in range(channels):
            out += struct.pack("<h", v)
    return bytes(out)


def _avg_per_sample_error(pcm_a, pcm_b):
    """Mean absolute sample difference between two 16-bit LE PCM buffers."""
    n = min(len(pcm_a), len(pcm_b)) // 2
    if n == 0:
        return 0
    err_sum = 0
    for i in range(n):
        a = struct.unpack_from("<h", pcm_a, i * 2)[0]
        b = struct.unpack_from("<h", pcm_b, i * 2)[0]
        err_sum += abs(a - b)
    return err_sum / n


# ----------------------------------------------------------------------
# Format-level sanity
# ----------------------------------------------------------------------

def test_dequant_table_size():
    assert len(_DEQUANT) == 16
    for row in _DEQUANT:
        assert len(row) == 8


def test_scalefactor_table_size():
    assert len(_SF_TAB) == 16
    # Monotonic increasing — the dynamic range scales up with SF index
    assert _SF_TAB == sorted(_SF_TAB)


def test_encoded_file_starts_with_qoaf():
    pcm = _make_silence_pcm(100, 1)
    blob = encode(pcm, channels=1, samplerate=22050)
    assert blob[:4] == b"qoaf"


def test_encoded_file_records_total_samples():
    pcm = _make_silence_pcm(2000, 1)
    blob = encode(pcm, channels=1, samplerate=22050)
    total = struct.unpack(">I", blob[4:8])[0]
    assert total == 2000


# ----------------------------------------------------------------------
# Decode round-trip
# ----------------------------------------------------------------------

def test_decode_recovers_metadata():
    pcm = _make_silence_pcm(500, 2)
    blob = encode(pcm, channels=2, samplerate=48000)
    out_pcm, channels, rate = decode(blob)
    assert channels == 2
    assert rate == 48000
    assert len(out_pcm) == len(pcm)


def test_decode_silence_stays_silent():
    pcm = _make_silence_pcm(2000, 1)
    blob = encode(pcm, channels=1, samplerate=22050)
    out_pcm, _, _ = decode(blob)
    # Silence might gain ±a few LSBs from LMS warmup; tolerate up to 3.
    assert _avg_per_sample_error(pcm, out_pcm) < 3


def test_round_trip_sine_acoustically_clean():
    """A sine round-trip should average <100 LSB error across all
    samples (out of a 65536 range — that's ~-56 dBFS, acoustically
    inaudible)."""
    pcm = _make_sine_pcm(samples=4000, channels=1, freq=440, rate=22050)
    blob = encode(pcm, channels=1, samplerate=22050)
    out_pcm, _, _ = decode(blob)
    assert _avg_per_sample_error(pcm, out_pcm) < 100


def test_round_trip_stereo_preserves_channel_count():
    pcm = _make_sine_pcm(samples=2000, channels=2, freq=440, rate=44100)
    blob = encode(pcm, channels=2, samplerate=44100)
    out_pcm, ch, _ = decode(blob)
    assert ch == 2
    assert len(out_pcm) == len(pcm)


# ----------------------------------------------------------------------
# Error paths
# ----------------------------------------------------------------------

def test_decode_rejects_bad_magic():
    with pytest.raises(ValueError, match="not a QOA"):
        decode(b"NOTQ" + b"\x00" * 100)


def test_encode_rejects_misaligned_pcm():
    with pytest.raises(ValueError, match="not divisible"):
        encode(b"\x00" * 5, channels=2, samplerate=22050)


def test_encode_rejects_invalid_channel_count():
    with pytest.raises(ValueError, match="unsupported channel"):
        encode(b"\x00" * 100, channels=0, samplerate=22050)
