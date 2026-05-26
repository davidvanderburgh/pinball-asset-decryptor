"""Unit tests for the BOF source-format converter.

Builds tiny synthetic versions of each Godot resource container the
converter knows about, runs decode + verifies the output is a valid
file in the expected format.
"""

import os
import struct

import pytest

from pinball_decryptor.plugins.bof import source_converter as sc


def test_parse_imported_name():
    name = "harkonnen_loop.png-63eb1af321a4002399a2ee837da9de44.ctex"
    base, hash6 = sc._parse_imported_name(name)
    assert base == "harkonnen_loop.png"
    assert hash6 == "63eb1a"


def test_parse_imported_name_rejects_non_imported():
    assert sc._parse_imported_name("regular.gdc") == (None, None)


# ----------------------------------------------------------------------
# .ctex decoders
# ----------------------------------------------------------------------

def _fake_ctex_with_webp(webp_size=512):
    """A minimal GST2 .ctex carrying a fake WebP payload."""
    webp_payload = b"RIFF" + struct.pack("<I", webp_size + 4) + b"WEBP" + b"\xAA" * webp_size
    # GST2 header is ~64 bytes — pad zeros then attach the WebP RIFF chunk
    header = b"GST2" + b"\x01" + b"\x00" * 59
    return header + webp_payload, webp_payload


def test_decode_ctex_webp():
    ctex, expected_webp = _fake_ctex_with_webp()
    ext, payload = sc._decode_ctex(ctex)
    assert ext == ".webp"
    # Allow small over-read tolerance (we slice up to riff_size+8)
    assert payload.startswith(b"RIFF")
    assert b"WEBP" in payload[:12]


def test_decode_ctex_ogg_video():
    ogg_bytes = b"OggS\x00\x02" + b"\x00" * 500
    ext, payload = sc._decode_ctex(ogg_bytes)
    assert ext == ".ogv"
    assert payload == ogg_bytes


def test_decode_ctex_unrecognised():
    ext, payload = sc._decode_ctex(b"\x00" * 100)
    assert ext is None and payload is None


# ----------------------------------------------------------------------
# .sample decoder — three encodings: PCM, QOA, OGG
# ----------------------------------------------------------------------

def _build_audio_sample(payload_bytes, payload_class=b"AudioStreamWAV"):
    """Synthesize a Godot AudioStreamWAV .sample with the given audio
    payload.  Mimics the structural layout the converter parses: two
    occurrences of the class name (resource header + internal-resource
    type), the internal-resource property list (num_props=5, first prop
    is the PBA), then a trailer holding format/rate/stereo values."""
    # File starts with RSRC magic + some header garbage + first class name
    cls = struct.pack("<I", len(payload_class) + 1) + payload_class + b"\x00"
    pre = b"RSRC" + b"\x00" * 16 + cls + b"\x00" * 64  # resource header copy
    # Internal resource: class name + property list
    int_res = cls
    int_res += struct.pack("<I", 5)  # num_props
    # Prop 0: (str_idx=2, VTYPE_PBA, pba_len, payload)
    int_res += struct.pack("<II", 2, sc._VTYPE_PBA)
    int_res += struct.pack("<I", len(payload_bytes))
    int_res += payload_bytes
    int_res += b"\x00" * ((4 - len(payload_bytes) % 4) % 4)
    # Trailer (format=1 (16-bit), rate=44100, stereo=0)
    trailer = (struct.pack("<III", 3, 3, 1) +
               struct.pack("<III", 7, 3, 44100) +
               struct.pack("<III", 8, 2, 0) +
               b"\x00" * 12 +
               b"RSRC")
    return pre + int_res + trailer


def test_decode_sample_raw_pcm_wraps_in_wav():
    # 100 samples of 16-bit PCM
    pcm = struct.pack("<100h", *(i * 100 for i in range(100)))
    sample = _build_audio_sample(pcm)
    ext, wav = sc._decode_sample(sample)
    assert ext == ".wav"
    assert wav.startswith(b"RIFF")
    assert wav[8:12] == b"WAVE"
    # Verify the PCM data round-trips
    assert wav.endswith(pcm)


def test_decode_sample_qoa_decoded_to_wav():
    # Build a tiny but VALID QOA payload (silence) so the decoder can
    # actually decompress it rather than falling through to .qoa
    # preserve.
    from pinball_decryptor.plugins.bof.qoa_codec import encode as qoa_encode
    pcm = b"\x00\x00" * 100  # 100 mono samples of silence
    qoa = qoa_encode(pcm, 1, 22050)
    sample = _build_audio_sample(qoa)
    ext, payload = sc._decode_sample(sample)
    assert ext == ".wav"
    assert payload.startswith(b"RIFF")
    assert payload[8:12] == b"WAVE"


def test_decode_sample_ogg_preserved():
    ogg = b"OggS\x00\x02" + b"\xAB" * 300
    sample = _build_audio_sample(ogg)
    ext, payload = sc._decode_sample(sample)
    assert ext == ".ogg"
    assert payload == ogg


def test_decode_sample_rejects_non_rsrc():
    assert sc._decode_sample(b"\x00" * 500) == (None, None)


# ----------------------------------------------------------------------
# Whole-tree converter — integration smoke
# ----------------------------------------------------------------------

def test_convert_imported_tree(tmp_path):
    # Build a mini pck/ tree with one .ctex (OGV), one .sample (QOA), one ignored .gdc
    imported = tmp_path / ".godot" / "imported"
    imported.mkdir(parents=True)

    (imported / "loop.png-abcdef0123456789abcdef0123456789.ctex").write_bytes(
        b"OggS\x00\x02" + b"V" * 500)
    qoa = b"qoaf" + struct.pack(">I", 100) + b"\xCC" * 100
    (imported / "song.wav-fedcba9876543210fedcba9876543210.sample").write_bytes(
        _build_audio_sample(qoa))
    (imported / "ignored.gdc").write_bytes(b"GDSC" + b"\x00" * 50)

    src = tmp_path / "source"
    stats = sc.convert_imported_tree(str(imported.parent.parent), str(src))
    assert stats["success"] == 2
    assert stats["by_ext"] == {".ogv": 1, ".qoa": 1}

    # Output names use original basename (no extension) + short hash
    names = sorted(p.name for p in src.iterdir())
    assert any(n.startswith("loop-abcdef") and n.endswith(".ogv") for n in names)
    assert any(n.startswith("song-fedcba") and n.endswith(".qoa") for n in names)
