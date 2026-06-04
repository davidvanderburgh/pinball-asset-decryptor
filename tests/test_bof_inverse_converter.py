"""Unit tests for the BOF inverse converter (write-back path).

Verifies that user-edited .wav / .webp files in ``pck/editable/``
are correctly re-encoded into the matching imported binaries in
``pck/.godot/imported/`` ready for the may_packer to ship.
"""

import os
import struct

import pytest

from pinball_decryptor.plugins.bof import inverse_converter as ic
from pinball_decryptor.plugins.bof.source_converter import (
    _VTYPE_PBA,
)


# ----------------------------------------------------------------------
# Filename parsing + matching
# ----------------------------------------------------------------------

def test_parse_source_name():
    stem, hash6, ext = ic.parse_source_name("voice_clip-abc123.wav")
    assert stem == "voice_clip"
    assert hash6 == "abc123"
    assert ext == "wav"


def test_parse_source_name_rejects_unknown_ext():
    assert ic.parse_source_name("foo-abc123.txt") == (None, None, None)


def test_parse_source_name_rejects_no_hash():
    assert ic.parse_source_name("regular.wav") == (None, None, None)


def test_find_matching_imported(tmp_path):
    imp = tmp_path / ".godot" / "imported"
    imp.mkdir(parents=True)
    (imp / "harkonnen.png-1c4a29c1874032b7a7a4d19647d0c93e.ctex").write_bytes(b"x")
    (imp / "other.wav-fedcba9876543210fedcba9876543210.sample").write_bytes(b"x")

    found = ic.find_matching_imported(str(tmp_path), "harkonnen", "1c4a29")
    assert found is not None
    assert "harkonnen.png-1c4a29c1" in found

    assert ic.find_matching_imported(str(tmp_path), "no_match", "abcdef") is None


# ----------------------------------------------------------------------
# .wav → .sample (PCM round-trip)
# ----------------------------------------------------------------------

def _build_pcm_sample(pcm_bytes):
    """Tiny AudioStreamWAV RSRC blob carrying raw PCM in the data PBA."""
    cls = struct.pack("<I", len(b"AudioStreamWAV") + 1) + b"AudioStreamWAV\x00"
    pre = b"RSRC" + b"\x00" * 16 + cls + b"\x00" * 64
    int_res = cls + struct.pack("<I", 1)  # num_props=1
    int_res += struct.pack("<II", 2, _VTYPE_PBA)  # str_idx=2, VTYPE_PBA
    int_res += struct.pack("<I", len(pcm_bytes))
    int_res += pcm_bytes
    int_res += b"\x00" * ((4 - len(pcm_bytes) % 4) % 4)
    return pre + int_res + b"RSRC"  # trailer just needs RSRC sentinel here


def _write_wav(path, pcm_bytes, channels, rate, width):
    """Write a minimal RIFF/WAVE PCM file."""
    riff = bytearray()
    riff += b"RIFF"
    riff += struct.pack("<I", 36 + len(pcm_bytes))
    riff += b"WAVE"
    riff += b"fmt "
    bps = width * 8
    block_align = channels * width
    byte_rate = rate * block_align
    riff += struct.pack("<IHHIIHH", 16, 1, channels, rate, byte_rate, block_align, bps)
    riff += b"data"
    riff += struct.pack("<I", len(pcm_bytes))
    riff += pcm_bytes
    with open(path, "wb") as f:
        f.write(bytes(riff))


def test_encode_wav_to_sample_swaps_pcm_payload(tmp_path):
    # Original .sample with old PCM bytes
    orig_pcm = b"\xAA\x00" * 50
    orig_sample = tmp_path / "voice.sample"
    orig_sample.write_bytes(_build_pcm_sample(orig_pcm))

    # User's new WAV with different PCM bytes (same length — a larger
    # clip would be auto-trimmed to fit the original's footprint).
    new_pcm = b"\x55\x00" * 50
    new_wav = tmp_path / "voice.wav"
    _write_wav(str(new_wav), new_pcm, channels=1, rate=22050, width=2)

    new_sample_bytes = ic.encode_wav_to_sample(str(new_wav), str(orig_sample))

    # The new PCM should appear in the rebuilt sample bytes
    assert new_pcm in new_sample_bytes
    assert orig_pcm not in new_sample_bytes
    # Header + trailer should still be intact
    assert new_sample_bytes.startswith(b"RSRC")
    assert new_sample_bytes.endswith(b"RSRC")


def test_encode_wav_rejects_non_audiostreamwav(tmp_path):
    bogus = tmp_path / "bogus.sample"
    bogus.write_bytes(b"RSRC" + b"\x00" * 200)  # no AudioStreamWAV class
    wav = tmp_path / "x.wav"
    _write_wav(str(wav), b"\x00\x00" * 10, channels=1, rate=22050, width=2)

    with pytest.raises(ValueError, match="not an AudioStreamWAV"):
        ic.encode_wav_to_sample(str(wav), str(bogus))


def test_encode_wav_conforms_to_original_channels_and_rate(tmp_path):
    """A mono / 44.1 kHz user file replacing a stereo / 48 kHz QOA callout
    must be conformed to stereo / 48 kHz.  We splice into the original
    resource and keep its mix_rate / stereo properties verbatim, so the
    new audio's channel count + rate MUST match — a channel mismatch makes
    Godot read the QOA buffer with the wrong stride and crashes (black
    screen at boot)."""
    import math
    from pinball_decryptor.plugins.bof import qoa_codec

    # Original: stereo 48 kHz QOA payload inside an AudioStreamWAV blob.
    stereo_pcm = b"".join(
        struct.pack("<hh", int(3000 * math.sin(i * 0.05)),
                    int(-3000 * math.sin(i * 0.05)))
        for i in range(3000))
    qoa = qoa_codec.encode(stereo_pcm, 2, 48000)
    assert qoa[8] == 2 and int.from_bytes(qoa[9:12], "big") == 48000
    orig_sample = tmp_path / "callout.sample"
    orig_sample.write_bytes(_build_pcm_sample(qoa))

    # User supplies MONO / 44.1 kHz — the worst-case mismatch.
    mono_pcm = b"".join(
        struct.pack("<h", int(2000 * math.sin(i * 0.07))) for i in range(2205))
    user_wav = tmp_path / "callout.wav"
    _write_wav(str(user_wav), mono_pcm, channels=1, rate=44100, width=2)

    new_sample = ic.encode_wav_to_sample(str(user_wav), str(orig_sample))

    new_qoa = new_sample[new_sample.find(b"qoaf"):]
    assert new_qoa[:4] == b"qoaf"
    assert new_qoa[8] == 2, "channel count not conformed to original (stereo)"
    assert int.from_bytes(new_qoa[9:12], "big") == 48000, "rate not conformed"
    pcm2, ch2, rate2 = qoa_codec.decode(new_qoa)
    assert ch2 == 2 and rate2 == 48000


def test_encode_wav_keeps_full_length_replacement(tmp_path):
    """A LONGER replacement is kept at full length (NOT trimmed) — the
    directory-aware repacker handles any size.  The new QOA payload simply
    grows and still conforms to the original's channels + rate."""
    import math
    from pinball_decryptor.plugins.bof import qoa_codec
    from pinball_decryptor.plugins.bof.source_converter import _find_data_pba

    # Original: a SHORT stereo/48k QOA callout (1 second).
    short_pcm = b"".join(
        struct.pack("<hh", int(2000 * math.sin(i * 0.05)),
                    int(2000 * math.sin(i * 0.05)))
        for i in range(48000))
    orig_sample = tmp_path / "loop.sample"
    orig_sample.write_bytes(_build_pcm_sample(qoa_codec.encode(short_pcm, 2, 48000)))

    # User supplies a much LONGER clip (5 seconds, stereo 48k).
    long_pcm = b"".join(
        struct.pack("<hh", int(2000 * math.sin(i * 0.05)),
                    int(2000 * math.sin(i * 0.05)))
        for i in range(48000 * 5))
    user_wav = tmp_path / "loop.wav"
    _write_wav(str(user_wav), long_pcm, channels=2, rate=48000, width=2)

    new_sample = ic.encode_wav_to_sample(str(user_wav), str(orig_sample))

    # Bigger than the original, full 5 seconds preserved, format conformed.
    assert len(new_sample) > len(orig_sample.read_bytes())
    new_payload, _off, _end = _find_data_pba(new_sample, b"AudioStreamWAV")
    assert new_payload[:4] == b"qoaf"
    pcm2, ch2, rate2 = qoa_codec.decode(new_payload)
    assert ch2 == 2 and rate2 == 48000
    assert len(pcm2) // (2 * 2) == 48000 * 5         # full length kept


# ----------------------------------------------------------------------
# .webp → .ctex
# ----------------------------------------------------------------------

def test_encode_image_to_ctex_replaces_payload(tmp_path):
    # Original .ctex: 64-byte GST2 header + 4-byte size + small WebP RIFF
    old_webp = b"RIFF" + struct.pack("<I", 4 + 4) + b"WEBPxxxx"
    header = b"GST2" + b"\x00" * 56 + struct.pack("<I", len(old_webp))
    orig_ctex = tmp_path / "tex.ctex"
    orig_ctex.write_bytes(header + old_webp)

    # User's new WebP — bigger, different content
    new_webp = b"RIFF" + struct.pack("<I", 24) + b"WEBPyyyyyyyyyyyyyyyy"
    new_img = tmp_path / "tex.webp"
    new_img.write_bytes(new_webp)

    rebuilt = ic.encode_image_to_ctex(str(new_img), str(orig_ctex))
    # New WebP should be embedded
    assert new_webp in rebuilt
    # Old WebP gone
    assert old_webp not in rebuilt
    # GST2 header still at the start
    assert rebuilt.startswith(b"GST2")
    # Size field updated to match new payload length
    size_field_off = rebuilt.find(b"RIFF") - 4
    embedded_size = struct.unpack("<I", rebuilt[size_field_off:size_field_off + 4])[0]
    assert embedded_size == len(new_webp)


def test_encode_image_rejects_non_gst2(tmp_path):
    orig = tmp_path / "vid.ctex"
    orig.write_bytes(b"OggS" + b"\x00" * 100)  # OGG video, not GST2
    img = tmp_path / "img.webp"
    img.write_bytes(b"RIFF" + b"\x00" * 100)

    with pytest.raises(ValueError, match="isn't GST2"):
        ic.encode_image_to_ctex(str(img), str(orig))


# ----------------------------------------------------------------------
# apply_source_edits — top-level write-back
# ----------------------------------------------------------------------

def test_apply_source_edits_picks_up_changed_wav(tmp_path):
    # Build a minimal pck/ tree: editable/ folder + .godot/imported/
    pck = tmp_path / "pck"
    editable = pck / "_EDITABLE ASSETS"
    imported = pck / ".godot" / "imported"
    editable.mkdir(parents=True)
    imported.mkdir(parents=True)

    orig_pcm = b"\xAA\x00" * 50
    full_hash = "1c4a29c1874032b7a7a4d19647d0c93e"
    imp_path = imported / f"voice.wav-{full_hash}.sample"
    imp_path.write_bytes(_build_pcm_sample(orig_pcm))

    # User drops in a new .wav (newer mtime)
    import time
    baseline = time.time()
    time.sleep(0.05)  # ensure mtime > baseline
    new_pcm = b"\x55\x00" * 50
    user_wav = editable / "voice-1c4a29.wav"
    _write_wav(str(user_wav), new_pcm, channels=1, rate=22050, width=2)

    stats = ic.apply_source_edits(str(pck), baseline)
    assert len(stats["updated"]) == 1
    assert stats["updated"][0][0] == "voice-1c4a29.wav"

    # The imported binary should now contain the new PCM
    rebuilt = imp_path.read_bytes()
    assert new_pcm in rebuilt
    assert orig_pcm not in rebuilt


def test_apply_source_edits_skips_unmatched_filename(tmp_path):
    pck = tmp_path / "pck"
    (pck / "_EDITABLE ASSETS").mkdir(parents=True)
    (pck / ".godot" / "imported").mkdir(parents=True)

    import time
    baseline = time.time()
    time.sleep(0.05)
    # Filename without the -hash6 suffix won't match
    bad = pck / "_EDITABLE ASSETS" / "just_a_file.wav"
    bad.write_bytes(b"RIFF" + b"\x00" * 100)

    stats = ic.apply_source_edits(str(pck), baseline)
    assert stats["updated"] == []
    assert len(stats["skipped"]) == 1


def test_apply_source_edits_no_editable_folder_is_clean_noop(tmp_path):
    pck = tmp_path / "pck"
    pck.mkdir()
    stats = ic.apply_source_edits(str(pck), 0)
    assert stats == {"updated": [], "skipped": []}
