"""Unit tests for BOF's RSCC container decoder.

RSCC is the custom Zstd-compressed container BOF introduced in May 2026
for font resources in their Godot PCK.  Synthesized RSCC blobs let us
test header parsing + decompression without needing a real BOF .fun
fixture; the decoder is byte-equivalent regardless of payload type.
"""

import math
import struct

import pytest

zstandard = pytest.importorskip("zstandard")

from pinball_decryptor.plugins.bof.rscc_decoder import (
    RSCC_MAGIC, RSCC_VERSION, RSCC_BLOCK_SIZE,
    RsccError, decompress, is_rscc_at, parse_header, scan,
)


def _build_rscc(payload):
    """Synthesize a valid RSCC container from arbitrary payload bytes."""
    blk_size = RSCC_BLOCK_SIZE
    n = math.ceil(len(payload) / blk_size) if payload else 0
    cctx = zstandard.ZstdCompressor()
    frames = []
    for i in range(n):
        chunk = payload[i * blk_size:(i + 1) * blk_size]
        frames.append(cctx.compress(chunk))
    block_sizes = [len(f) for f in frames]

    out = bytearray()
    out += RSCC_MAGIC
    out += struct.pack("<III", RSCC_VERSION, blk_size, len(payload))
    out += struct.pack(f"<{n}I", *block_sizes)
    for f in frames:
        out += f
    return bytes(out)


def test_is_rscc_at_filters_spurious_matches():
    # Random bytes that happen to contain "RSCC" but aren't a real container
    spurious = b"\x00" * 10 + RSCC_MAGIC + b"\xff\xff\xff\xff" * 10
    assert not is_rscc_at(spurious, 10)


def test_is_rscc_at_recognises_real_container():
    blob = _build_rscc(b"hello world" * 100)
    assert is_rscc_at(blob, 0)


def test_parse_header_round_trip():
    payload = b"X" * (RSCC_BLOCK_SIZE * 3 + 17)  # 3 full blocks + 17 bytes
    blob = _build_rscc(payload)

    hdr = parse_header(blob, 0)
    assert hdr["version"] == RSCC_VERSION
    assert hdr["block_size"] == RSCC_BLOCK_SIZE
    assert hdr["total_uncompressed"] == len(payload)
    assert hdr["num_blocks"] == 4
    assert hdr["container_size"] == len(blob)


def test_decompress_recovers_payload():
    payload = b"Lorem ipsum dolor sit amet, " * 1000  # ~28 KB
    blob = _build_rscc(payload)

    recovered, consumed = decompress(blob, 0)
    assert recovered == payload
    assert consumed == len(blob)


def test_decompress_at_nonzero_offset():
    """The decoder must operate at any offset, not assume container starts
    at byte 0 — real PCKs have RSCC blobs at gigabyte offsets."""
    payload = b"font data goes here" * 200
    blob = _build_rscc(payload)
    wrapped = b"PREFIX_BYTES_TO_OFFSET" + blob + b"TRAILING"

    recovered, consumed = decompress(wrapped, len(b"PREFIX_BYTES_TO_OFFSET"))
    assert recovered == payload
    assert consumed == len(blob)


def test_decompress_raises_on_no_container():
    with pytest.raises(RsccError, match="No valid RSCC"):
        decompress(b"\x00" * 100, 0)


def test_decompress_raises_on_truncated_frame():
    payload = b"X" * (RSCC_BLOCK_SIZE * 2)
    blob = _build_rscc(payload)
    truncated = blob[:-50]
    with pytest.raises(RsccError):
        decompress(truncated, 0)


def test_scan_finds_all_real_containers_and_skips_spurious():
    blob_a = _build_rscc(b"alpha payload" * 50)
    blob_b = _build_rscc(b"beta payload" * 75)
    blob_c = _build_rscc(b"gamma payload" * 100)

    # Spurious "RSCC" bytes between real blobs (e.g. inside other data)
    junk = b"\xff" * 30 + RSCC_MAGIC + b"\x00\x00\x00\x00" * 5
    combined = blob_a + junk + blob_b + b"\x55" * 20 + blob_c

    found = list(scan(combined))
    assert len(found) == 3

    offsets = [off for off, _ in found]
    assert offsets == [
        0,
        len(blob_a) + len(junk),
        len(blob_a) + len(junk) + len(blob_b) + 20,
    ]


def test_empty_payload_container():
    blob = _build_rscc(b"")
    recovered, consumed = decompress(blob, 0)
    assert recovered == b""
    assert consumed == len(blob)
