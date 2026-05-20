"""Round-trip tests for the JPS sound-bank extractor / repacker.

Builds a synthetic .bnk in memory (no real PF .img required) that
matches the JPS file structure -- header + per-buffer header table +
command chunks + zlib-wrapped JPS-magic+PCM streams.  Then exercises:

  * `extract_bnk` -> verify WAVs match the synthetic PCM
  * `repack_bnk` with no edits -> byte-identical output
  * `repack_bnk` with an edit -> re-extract + verify edit persisted

If repack ever regresses, this test catches it without needing a 14 GB
real `.img` and a half-hour smoke run.
"""

import os
import struct
import wave
import zlib

import pytest

from pinball_decryptor.plugins.cgc import jps_bnk


# ---------------------------------------------------------------------------
# Synthetic bnk builder
# ---------------------------------------------------------------------------

def _make_jps_buffer(pcm_bytes: bytes, hash1: int = 0xDEADBEEF,
                     hash2: int = 0xCAFEBABE) -> bytes:
    """Build a single zlib-wrapped JPS buffer: 44-byte magic + PCM."""
    header = struct.pack(
        "<11I",
        0x0E6F07BB, hash1, 0x1385CA6D, 0xDB8E52BF, 0xCBA86BDF,
        0x3C4B88A6, 0x31933080, 0x3855CD0A, 0x9AC705CB, 0xD16487E2,
        hash2,
    )
    return zlib.compress(header + pcm_bytes, 6)


def _build_synthetic_bnk(name: str, buffer_pcms: list) -> bytes:
    """Compose a minimal but JPS-shape-correct .bnk.

    Layout:
      filename header (32 bytes, null-padded)
      per-buffer header table (68 bytes * N) starting at 0x2A0
      command region: one SETV + one PLAY per buffer (96 bytes each)
      zlib-wrapped buffers (each separated by a 4-byte gap matching
      the real format)

    Not bit-accurate to a real CGC compiler output (no MSVC garbage,
    no extra opcodes), but uses the same chunk sizes / offsets / magic
    that the loader keys off of.
    """
    n = len(buffer_pcms)
    out = bytearray()

    # Filename header at offset 0, null-padded to 0x2A0
    out += name.encode("latin-1") + b"\x00"
    out += b"\x00" * (0x2A0 - len(out))

    # Per-buffer header table: 68 bytes per entry, sample-rate marker
    # at offset 0 of each entry.
    for _ in range(n):
        entry = bytearray(68)
        struct.pack_into("<I", entry, 0, jps_bnk.SAMPLE_RATE)
        struct.pack_into("<I", entry, 4, jps_bnk.CHANNELS)
        out += entry

    # Command region: alternating SETV + PLAY (96 bytes each).
    # PLAY's +0x20 field encodes buffer_index * 68.
    for i in range(n):
        setv = bytearray(96)
        setv[0:6] = b"SETVOL"
        out += setv
        play = bytearray(96)
        play[0:4] = b"PLAY"
        struct.pack_into(
            "<I", play, jps_bnk.PLAY_BUFFER_INDEX_FIELD_OFFSET,
            i * jps_bnk.PLAY_BUFFER_INDEX_STRIDE)
        out += play

    # zlib-compressed buffers + 4-byte gap before each subsequent one.
    for i, pcm in enumerate(buffer_pcms):
        if i > 0:
            out += b"\xab\xcd\xef\x01"  # placeholder 4-byte gap
        out += _make_jps_buffer(pcm, hash1=0x10000 + i,
                                hash2=0x20000 + i)

    return bytes(out)


def _sine_pcm(duration_ms: int, freq_hz: int = 440) -> bytes:
    """Generate stereo s16le PCM at 48 kHz."""
    import math
    n_samples = int(jps_bnk.SAMPLE_RATE * duration_ms / 1000)
    out = bytearray()
    for i in range(n_samples):
        s = int(16000 * math.sin(2 * math.pi * freq_hz * i / jps_bnk.SAMPLE_RATE))
        out += struct.pack("<hh", s, s)
    return bytes(out)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_bnk_path(tmp_path):
    """Write a 3-buffer synthetic bnk and return its path."""
    pcms = [
        _sine_pcm(100, 440),
        _sine_pcm(200, 880),
        _sine_pcm(50, 220),
    ]
    bnk_path = tmp_path / "test.bnk"
    bnk_path.write_bytes(_build_synthetic_bnk("test.txt", pcms))
    return bnk_path, pcms


def test_extract_synthetic_bnk_returns_correct_pcm(synthetic_bnk_path,
                                                    tmp_path):
    bnk_path, expected_pcms = synthetic_bnk_path
    out_dir = tmp_path / "extract"
    contents = jps_bnk.extract_bnk(str(bnk_path), str(out_dir))

    assert len(contents.buffers) == 3
    assert len(contents.events) == 3
    # Each event references its corresponding buffer in order.
    for i, e in enumerate(contents.events):
        assert e.buffer_index == i

    for i, expected_pcm in enumerate(expected_pcms):
        wav_path = out_dir / f"test_sound_{i:03d}.wav"
        assert wav_path.exists(), f"sound_{i:03d}.wav was not extracted"
        with wave.open(str(wav_path), "rb") as w:
            assert w.getnchannels() == jps_bnk.CHANNELS
            assert w.getframerate() == jps_bnk.SAMPLE_RATE
            got_pcm = w.readframes(w.getnframes())
        assert got_pcm == expected_pcm, (
            f"buffer {i} PCM mismatch after extract "
            f"({len(got_pcm)} vs {len(expected_pcm)} bytes)")


def test_repack_no_changes_is_byte_identical(synthetic_bnk_path,
                                              tmp_path):
    """A repack that touches nothing should re-emit the original
    file byte-for-byte (PCM-diff path keeps the original compressed
    payload instead of re-zlib-compressing)."""
    bnk_path, _ = synthetic_bnk_path
    out_dir = tmp_path / "extract"
    jps_bnk.extract_bnk(str(bnk_path), str(out_dir))

    repacked = tmp_path / "repacked.bnk"
    summary = jps_bnk.repack_bnk(str(bnk_path), str(out_dir),
                                  str(repacked))

    assert summary["modified_count"] == 0
    assert bnk_path.read_bytes() == repacked.read_bytes()


def test_repack_with_edit_preserves_modification(synthetic_bnk_path,
                                                  tmp_path):
    bnk_path, _ = synthetic_bnk_path
    out_dir = tmp_path / "extract"
    jps_bnk.extract_bnk(str(bnk_path), str(out_dir))

    # Replace sound 1's WAV with a completely different sine wave.
    new_pcm = _sine_pcm(150, 1320)
    target = out_dir / "test_sound_001.wav"
    with wave.open(str(target), "wb") as w:
        w.setnchannels(jps_bnk.CHANNELS)
        w.setsampwidth(jps_bnk.SAMPLE_WIDTH_BYTES)
        w.setframerate(jps_bnk.SAMPLE_RATE)
        w.writeframes(new_pcm)

    repacked = tmp_path / "repacked.bnk"
    summary = jps_bnk.repack_bnk(str(bnk_path), str(out_dir),
                                  str(repacked))
    assert summary["modified_count"] == 1
    assert summary["buffers"][1]["modified"] is True
    assert summary["buffers"][0]["modified"] is False
    assert summary["buffers"][2]["modified"] is False

    # Re-extract from the repacked bnk and verify our edit survived.
    re_dir = tmp_path / "re_extract"
    contents = jps_bnk.extract_bnk(str(repacked), str(re_dir))
    assert len(contents.buffers) == 3
    re_target = re_dir / "repacked_sound_001.wav"
    with wave.open(str(re_target), "rb") as w:
        round_tripped_pcm = w.readframes(w.getnframes())
    assert round_tripped_pcm == new_pcm

    # And the unmodified neighbors should still match their original PCM.
    for i in (0, 2):
        orig_wav = out_dir / f"test_sound_{i:03d}.wav"
        re_wav = re_dir / f"repacked_sound_{i:03d}.wav"
        with wave.open(str(orig_wav), "rb") as w:
            orig_pcm = w.readframes(w.getnframes())
        with wave.open(str(re_wav), "rb") as w:
            re_pcm = w.readframes(w.getnframes())
        assert orig_pcm == re_pcm, f"untouched buffer {i} got mangled"


def test_repack_rejects_mismatched_audio_format(synthetic_bnk_path,
                                                 tmp_path):
    """Different sample rate / channels should raise rather than
    silently corrupt the bnk (the JPS runtime is mono-format)."""
    bnk_path, _ = synthetic_bnk_path
    out_dir = tmp_path / "extract"
    jps_bnk.extract_bnk(str(bnk_path), str(out_dir))

    target = out_dir / "test_sound_000.wav"
    with wave.open(str(target), "wb") as w:
        w.setnchannels(1)             # wrong: mono
        w.setsampwidth(2)
        w.setframerate(22050)          # wrong: half sample rate
        w.writeframes(b"\x00\x00" * 1000)

    with pytest.raises(ValueError, match="expects"):
        jps_bnk.repack_bnk(str(bnk_path), str(out_dir),
                            str(tmp_path / "repacked.bnk"))
