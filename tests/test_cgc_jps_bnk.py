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


def _riff_wav(pcm: bytes) -> bytes:
    """A minimal 48 kHz stereo s16le RIFF/WAVE around *pcm* (music-bank
    storage form)."""
    fmt = struct.pack("<HHIIHH", 1, jps_bnk.CHANNELS, jps_bnk.SAMPLE_RATE,
                      jps_bnk.SAMPLE_RATE * jps_bnk.CHANNELS * 2,
                      jps_bnk.CHANNELS * 2, 16)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt \
        + b"data" + struct.pack("<I", len(pcm)) + pcm
    return b"RIFF" + struct.pack("<I", len(body)) + body


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_scan_large_riff_with_false_zlib_headers_is_fast_and_correct():
    """A music-style RIFF buffer whose PCM is full of ``0x78 0x9C`` byte
    pairs (valid-looking zlib headers) must be parsed as exactly one RIFF
    buffer, quickly.

    ``0x78 0x9C`` is a real zlib header, so the scanner probes it -- and the
    naive probe decompressed the entire multi-hundred-MB tail from every such
    hit, making a 233 MB pfmusic.bnk take ~140 s (RTS's "first 3 minutes crush
    my processor").  The probe is now bounded, so this stays sub-second; the
    generous 10 s bound only trips on a catastrophic regression.
    """
    import time
    # 20 MB of PCM peppered with false zlib headers.
    pcm = (b"\x78\x9c\x00\x11\x22\x33\x44\x55") * (20_000_000 // 8)
    bnk = b"\x00" * 0x2A0 + _riff_wav(pcm)

    t0 = time.time()
    buffers = jps_bnk._scan_buffers(bnk)
    elapsed = time.time() - t0

    assert len(buffers) == 1, f"expected 1 RIFF buffer, got {len(buffers)}"
    assert buffers[0].storage == "riff"
    assert buffers[0].bnk_offset == 0x2A0
    assert elapsed < 10.0, f"scan took {elapsed:.1f}s -- perf regression"



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
    # Same length as the stock slot -- JPS slots are fixed-length, so a
    # size-neutral swap round-trips exactly (length changes are covered
    # by the dedicated clamp tests below).
    new_pcm = _sine_pcm(200, 1320)
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


def _write_wav(path, pcm, rate=None, channels=None):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels or jps_bnk.CHANNELS)
        w.setsampwidth(jps_bnk.SAMPLE_WIDTH_BYTES)
        w.setframerate(rate or jps_bnk.SAMPLE_RATE)
        w.writeframes(pcm)


def test_repack_matches_transcribe_renamed_wav(synthetic_bnk_path, tmp_path):
    """Extract's auto-transcribe renames WAVs to ``<stem> - <text>.wav``
    and Replace Audio stages the user's track over the *renamed* file.
    The repacker must still map it back to its buffer -- before the
    rename-aware fallback existed, every buffer was preserved verbatim
    (modified_count == 0) and the Write build degenerated to a silent
    byte-for-byte copy ("No modified files found")."""
    bnk_path, _ = synthetic_bnk_path
    out_dir = tmp_path / "extract"
    jps_bnk.extract_bnk(str(bnk_path), str(out_dir))

    renamed = out_dir / "test_sound_001 - Bring out the gimp.wav"
    os.rename(out_dir / "test_sound_001.wav", renamed)
    new_pcm = _sine_pcm(200, 1320)  # same length as the stock slot
    _write_wav(renamed, new_pcm)

    repacked = tmp_path / "repacked.bnk"
    summary = jps_bnk.repack_bnk(str(bnk_path), str(out_dir),
                                  str(repacked))
    assert summary["modified_count"] == 1
    assert summary["buffers"][1]["modified"] is True
    assert summary["buffers"][1]["wav"] == str(renamed)

    re_dir = tmp_path / "re_extract"
    jps_bnk.extract_bnk(str(repacked), str(re_dir))
    with wave.open(str(re_dir / "repacked_sound_001.wav"), "rb") as w:
        assert w.readframes(w.getnframes()) == new_pcm


def _riff_wav_with_list(pcm: bytes) -> bytes:
    """A 48 kHz stereo s16le RIFF/WAVE with a LIST/INFO metadata chunk
    between ``fmt `` and ``data`` -- exactly what ffmpeg's WAV muxer
    emits (and what silenced the real Pulp Fiction music slot)."""
    fmt = struct.pack("<HHIIHH", 1, jps_bnk.CHANNELS, jps_bnk.SAMPLE_RATE,
                      jps_bnk.SAMPLE_RATE * jps_bnk.CHANNELS * 2,
                      jps_bnk.CHANNELS * 2, 16)
    info = b"INFOISFT" + struct.pack("<I", 6) + b"Lavf\x00\x00"
    lst = b"LIST" + struct.pack("<I", len(info)) + info
    body = (b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
            + lst + b"data" + struct.pack("<I", len(pcm)) + pcm)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _build_contiguous_riff_bnk(name: str, pcms: list,
                               overshoot: int = 96) -> bytes:
    """Compose a music-style bnk exactly like the real pfmusic.bnk: RIFF
    streams packed CONTIGUOUSLY (zero gap), each with an outer RIFF ``size``
    field INFLATED so it overshoots into the next stream by *overshoot* bytes.

    This is the shape that made the shipping scanner skip every other stream
    (advancing by ``8 + riff_size`` overshoots past the next stream's header),
    so a correct scanner must walk by the data-chunk end instead.  The last
    stream's inflated size deliberately runs past EOF (like the real stream
    48), exercising the bounds check.
    """
    out = bytearray(b"\x00" * 0x2A0)
    for pcm in pcms:
        wav = bytearray(_riff_wav(pcm))          # canonical: size = 36+len(pcm)
        struct.pack_into("<I", wav, 4, (36 + len(pcm)) + overshoot)  # inflate
        out += wav                                # NO gap -- contiguous
    return bytes(out)


def test_scan_finds_all_contiguous_overshoot_streams():
    """Regression lock for the 24->49 scanner fix: contiguous RIFF streams
    whose outer size field overshoots must ALL be found.  The old scanner
    (``i += 8 + riff_size``) skipped every other one and dropped the last."""
    pcms = [_sine_pcm(100, 440), _sine_pcm(60, 880),
            _sine_pcm(80, 220), _sine_pcm(40, 1320), _sine_pcm(70, 990)]
    bnk = _build_contiguous_riff_bnk("music.txt", pcms)
    bufs = jps_bnk._scan_buffers(bnk)
    assert len(bufs) == len(pcms), (
        f"scanner found {len(bufs)} of {len(pcms)} streams -- overshoot skip")
    off = 0x2A0
    for i, pcm in enumerate(pcms):
        assert bufs[i].bnk_offset == off, f"stream {i} offset wrong"
        assert bufs[i].pcm_size == len(pcm)
        assert bufs[i].compressed_size == 44 + len(pcm)   # exact, no overshoot
        off += 44 + len(pcm)


def test_repack_riff_edit_middle_stream_is_size_neutral(tmp_path):
    """THE Pulp Fiction silent-music fix on the real bank shape: editing one
    stream (here a formerly-hidden middle one) with a longer LIST-carrying
    ffmpeg WAV must splice size-neutrally -- stock header kept, LIST dropped,
    PCM clamped, and every other stream byte-identical."""
    pcms = [_sine_pcm(100, 440), _sine_pcm(60, 880), _sine_pcm(80, 220)]
    bnk = _build_contiguous_riff_bnk("music.txt", pcms)
    bnk_path = tmp_path / "music.bnk"
    bnk_path.write_bytes(bnk)

    out_dir = tmp_path / "extract"
    contents = jps_bnk.extract_bnk(str(bnk_path), str(out_dir))
    assert len(contents.buffers) == 3

    # Edit the MIDDLE stream (index 1) with a longer LIST-chunk ffmpeg WAV.
    longer = _sine_pcm(110, 1500)
    (out_dir / "music_sound_001.wav").write_bytes(_riff_wav_with_list(longer))

    repacked = tmp_path / "repacked.bnk"
    summary = jps_bnk.repack_bnk(str(bnk_path), str(out_dir), str(repacked))
    out = repacked.read_bytes()

    assert len(out) == len(bnk)                       # size-neutral
    assert summary["modified_count"] == 1
    assert summary["buffers"][1]["modified"] is True
    assert summary["buffers"][0]["modified"] is False
    assert summary["buffers"][2]["modified"] is False
    assert any("truncated" in n for n in summary.get("clamp_notes", []))

    # Only stream 1's PCM changed; everything else byte-identical.
    b1 = contents.buffers[1]
    off, plen = jps_bnk._riff_data_span(
        bnk[b1.bnk_offset:b1.bnk_offset + b1.compressed_size])
    pcm_start, pcm_end = b1.bnk_offset + off, b1.bnk_offset + off + plen
    assert out[:pcm_start] == bnk[:pcm_start]
    assert out[pcm_end:] == bnk[pcm_end:]
    assert b"LIST" not in out[b1.bnk_offset:pcm_start]   # LIST dropped

    re_dir = tmp_path / "re"
    jps_bnk.extract_bnk(str(repacked), str(re_dir))
    with wave.open(str(re_dir / "repacked_sound_001.wav"), "rb") as w:
        assert w.readframes(w.getnframes()) == longer[:plen]
    with wave.open(str(re_dir / "repacked_sound_000.wav"), "rb") as w:
        assert w.readframes(w.getnframes()) == pcms[0]


def test_repack_riff_pads_short_replacement(tmp_path):
    """A replacement shorter than the stock slot is zero-padded to the
    slot length (still size-neutral) and reported as padded."""
    bnk = _build_contiguous_riff_bnk("music.txt", [_sine_pcm(100, 440),
                                                    _sine_pcm(50, 880)])
    bnk_path = tmp_path / "music.bnk"
    bnk_path.write_bytes(bnk)
    out_dir = tmp_path / "extract"
    jps_bnk.extract_bnk(str(bnk_path), str(out_dir))

    shorter = _sine_pcm(40, 1500)
    (out_dir / "music_sound_000.wav").write_bytes(_riff_wav(shorter))
    repacked = tmp_path / "repacked.bnk"
    summary = jps_bnk.repack_bnk(str(bnk_path), str(out_dir), str(repacked))

    assert len(repacked.read_bytes()) == len(bnk)
    assert any("padded" in n for n in summary.get("clamp_notes", []))
    re_dir = tmp_path / "re"
    jps_bnk.extract_bnk(str(repacked), str(re_dir))
    with wave.open(str(re_dir / "repacked_sound_000.wav"), "rb") as w:
        got = w.readframes(w.getnframes())
    assert got[:len(shorter)] == shorter
    assert got[len(shorter):] == b"\x00" * (len(got) - len(shorter))


def test_repack_riff_no_op_is_byte_identical(tmp_path):
    """Extract + repack with no edits reproduces a contiguous-overshoot bank
    byte-for-byte (extract now emits clean WAVs, but repack preserves the
    stock bank bytes)."""
    bnk = _build_contiguous_riff_bnk(
        "music.txt", [_sine_pcm(90, 440), _sine_pcm(120, 660),
                      _sine_pcm(30, 880)])
    bnk_path = tmp_path / "music.bnk"
    bnk_path.write_bytes(bnk)
    out_dir = tmp_path / "extract"
    jps_bnk.extract_bnk(str(bnk_path), str(out_dir))
    repacked = tmp_path / "repacked.bnk"
    summary = jps_bnk.repack_bnk(str(bnk_path), str(out_dir), str(repacked))
    assert summary["modified_count"] == 0
    assert repacked.read_bytes() == bnk


def test_repack_zlib_edit_is_size_neutral(tmp_path):
    """zlib (SFX/speech) banks are fixed-length too: the engine's
    compressed path validates the decompressed length against the stock
    record, so a longer/shorter edit must be clamped, not shipped at its
    own size."""
    pcms = [_sine_pcm(100, 440), _sine_pcm(200, 880)]
    bnk_path = tmp_path / "sfx.bnk"
    bnk_path.write_bytes(_build_synthetic_bnk("sfx.txt", pcms))
    out_dir = tmp_path / "extract"
    jps_bnk.extract_bnk(str(bnk_path), str(out_dir))

    with wave.open(str(out_dir / "sfx_sound_000.wav"), "rb") as w:
        stock_len = len(w.readframes(w.getnframes()))
    _write_wav(out_dir / "sfx_sound_000.wav", _sine_pcm(300, 1500))  # longer

    repacked = tmp_path / "repacked.bnk"
    summary = jps_bnk.repack_bnk(str(bnk_path), str(out_dir), str(repacked))
    assert any("truncated" in n for n in summary.get("clamp_notes", []))
    re_dir = tmp_path / "re"
    contents = jps_bnk.extract_bnk(str(repacked), str(re_dir))
    # Slot 0's decoded PCM stayed the stock length (clamped), so the
    # engine's length check would still pass.
    assert contents.buffers[0].pcm_size == stock_len


def test_repack_refuses_ambiguous_renamed_wavs(synthetic_bnk_path,
                                                tmp_path):
    """Two ``<stem> - *.wav`` siblings for the same slot are ambiguous --
    the resolver must not guess (the pipeline-level consumed-check turns
    the unmatched edit into a loud abort)."""
    bnk_path, _ = synthetic_bnk_path
    out_dir = tmp_path / "extract"
    jps_bnk.extract_bnk(str(bnk_path), str(out_dir))

    orig = out_dir / "test_sound_001.wav"
    stock_bytes = orig.read_bytes()
    os.rename(orig, out_dir / "test_sound_001 - take one.wav")
    (out_dir / "test_sound_001 - take two.wav").write_bytes(stock_bytes)
    _write_wav(out_dir / "test_sound_001 - take one.wav",
               _sine_pcm(150, 1320))

    repacked = tmp_path / "repacked.bnk"
    summary = jps_bnk.repack_bnk(str(bnk_path), str(out_dir),
                                  str(repacked))
    assert summary["modified_count"] == 0
    assert summary["buffers"][1]["wav"] is None
    assert bnk_path.read_bytes() == repacked.read_bytes()


# ---------------------------------------------------------------------------
# Write-pipeline pre-step: renamed edits must be detected, and edits the
# repacker can't place must abort loudly (never a silent no-op build).
# ---------------------------------------------------------------------------

def _make_bank_assets(tmp_path):
    """An assets dir shaped like a PF extract: data/pf.bnk + decoded
    data/pf/ subdir.  Returns (assets_root, bnk_path, subdir_path)."""
    assets = tmp_path / "assets"
    (assets / "data").mkdir(parents=True)
    bnk = assets / "data" / "pf.bnk"
    bnk.write_bytes(_build_synthetic_bnk(
        "pf.txt", [_sine_pcm(100, 440), _sine_pcm(200, 880)]))
    jps_bnk.extract_bnk(str(bnk), str(assets / "data" / "pf"))
    return assets, bnk, assets / "data" / "pf"


def test_diff_detects_edit_on_transcribe_renamed_wav(tmp_path):
    """End-to-end shape of the real failure: transcribed extract (all
    WAVs renamed, baseline re-pointed), one renamed WAV edited ->
    _diff_assets must repack the bank and report the .bnk as changed."""
    from pinball_decryptor.core.checksums import md5_file
    from pinball_decryptor.plugins.cgc import pipeline as cgc_pipeline

    assets, bnk, sub = _make_bank_assets(tmp_path)
    baseline = {"data/pf.bnk": md5_file(str(bnk))}
    for i, label in enumerate(["music", "Zed's dead baby"]):
        renamed = sub / f"pf_sound_{i:03d} - {label}.wav"
        os.rename(sub / f"pf_sound_{i:03d}.wav", renamed)
        baseline[f"data/pf/{renamed.name}"] = md5_file(str(renamed))

    new_pcm = _sine_pcm(100, 1320)  # slot 0 is 100ms; keep it size-neutral
    _write_wav(sub / "pf_sound_000 - music.wav", new_pcm)

    changed, missing = cgc_pipeline._diff_assets(str(assets), baseline)
    assert "data/pf.bnk" in changed
    assert not missing
    assert not any(k.endswith(".wav") for k in changed)

    re_dir = tmp_path / "re_extract"
    jps_bnk.extract_bnk(str(bnk), str(re_dir))
    with wave.open(str(re_dir / "pf_sound_000.wav"), "rb") as w:
        assert w.readframes(w.getnframes()) == new_pcm


def test_diff_aborts_loudly_on_unmatchable_edited_wav(tmp_path):
    """An edited WAV the repacker can't map to a slot (rename that broke
    the naming convention) must abort the build, not ship an unmodified
    image that reports success."""
    from pinball_decryptor.core.checksums import md5_file
    from pinball_decryptor.plugins.cgc import pipeline as cgc_pipeline

    assets, bnk, sub = _make_bank_assets(tmp_path)
    baseline = {"data/pf.bnk": md5_file(str(bnk))}
    for fn in os.listdir(sub):
        if fn.endswith(".wav"):
            baseline[f"data/pf/{fn}"] = md5_file(str(sub / fn))

    broken = sub / "royale with cheese.wav"
    os.rename(sub / "pf_sound_001.wav", broken)
    _write_wav(broken, _sine_pcm(150, 1320))

    with pytest.raises(cgc_pipeline.PipelineError,
                       match="could not be matched"):
        cgc_pipeline._diff_assets(str(assets), baseline)


def test_diff_aborts_loudly_when_repack_fails(tmp_path):
    """A repack failure on a bank the user edited (e.g. wrong WAV format)
    must abort the build instead of silently shipping the stock .bnk."""
    from pinball_decryptor.core.checksums import md5_file
    from pinball_decryptor.plugins.cgc import pipeline as cgc_pipeline

    assets, bnk, sub = _make_bank_assets(tmp_path)
    baseline = {"data/pf.bnk": md5_file(str(bnk))}
    for fn in os.listdir(sub):
        if fn.endswith(".wav"):
            baseline[f"data/pf/{fn}"] = md5_file(str(sub / fn))

    # Wrong sample rate + mono -> repack_bnk raises ValueError inside.
    _write_wav(sub / "pf_sound_000.wav", b"\x00\x00" * 1000,
               rate=22050, channels=1)

    with pytest.raises(cgc_pipeline.PipelineError, match="failed"):
        cgc_pipeline._diff_assets(str(assets), baseline)


def test_diff_aborts_on_stale_v1_extract_when_edited(tmp_path):
    """A decoded subdir made before the RIFF scanner was corrected (manifest
    format != jps_bnk_v2) has a different slot->stream mapping, so building
    an EDIT from it would scramble the bank.  It must abort with a re-extract
    message -- never silently ship scrambled audio."""
    import json
    from pinball_decryptor.core.checksums import md5_file
    from pinball_decryptor.plugins.cgc import pipeline as cgc_pipeline

    assets, bnk, sub = _make_bank_assets(tmp_path)
    baseline = {"data/pf.bnk": md5_file(str(bnk))}
    for fn in os.listdir(sub):
        if fn.endswith(".wav"):
            baseline[f"data/pf/{fn}"] = md5_file(str(sub / fn))

    # Simulate an OLD extract: downgrade the manifest format tag.
    man = sub / "pf.manifest.json"
    m = json.loads(man.read_text())
    m["format"] = "jps_bnk_v1"
    man.write_text(json.dumps(m))

    # Edit a WAV.
    _write_wav(sub / "pf_sound_000.wav", _sine_pcm(100, 1320))

    with pytest.raises(cgc_pipeline.PipelineError, match="older version"):
        cgc_pipeline._diff_assets(str(assets), baseline)


def test_diff_allows_v2_extract_edit(tmp_path):
    """The stale-extract guard must NOT fire for a current (v2) extract."""
    from pinball_decryptor.core.checksums import md5_file
    from pinball_decryptor.plugins.cgc import pipeline as cgc_pipeline

    assets, bnk, sub = _make_bank_assets(tmp_path)   # extract writes v2
    baseline = {"data/pf.bnk": md5_file(str(bnk))}
    for fn in os.listdir(sub):
        if fn.endswith(".wav"):
            baseline[f"data/pf/{fn}"] = md5_file(str(sub / fn))
    _write_wav(sub / "pf_sound_000.wav", _sine_pcm(100, 1320))  # size-neutral

    changed, missing = cgc_pipeline._diff_assets(str(assets), baseline)
    assert "data/pf.bnk" in changed  # built, not aborted


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
