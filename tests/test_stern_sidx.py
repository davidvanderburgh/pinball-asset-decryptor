"""Tests for Stern Spike 2 .sidx manifest regeneration (core/sidx).

The global HMAC-SHA1 key was recovered by reverse-engineering the validator and
verified to reproduce real card digests; these guard the key constant, the FI64
record parser, and the field offsets so a refactor can't silently break it.
"""

import struct

from pinball_decryptor.plugins.stern import sidx


def test_key_is_pinned():
    # The global SIDX key is a fixed constant; a change here would break every
    # regenerated manifest. Pin it via a known digest of a fixed input.
    assert sidx.SIDX_KEY.hex() == "8e1f5543c2f54a11673a282a2f87c006"
    hm, md = sidx.digests(b"spike2")
    assert hm.hex() == "374be47bb39540406acb8db0f847deac53970731"
    assert md.hex() == "ae4541bcc15bd0a22405fb0abdc9f23a"


def _build_sidx(paths_and_sizes):
    """Hand-build a minimal FI64 .sidx: SIDX header + STRS + FI64 records."""
    strs = b"".join(p.encode() + b"\x00" for p, _ in paths_and_sizes)
    body = b"STRS" + struct.pack("<I", len(strs)) + strs
    for _p, size in paths_and_sizes:
        payload = bytearray(80)
        struct.pack_into("<I", payload, 8, size)       # size field
        body += b"FI64" + struct.pack("<I", 80) + bytes(payload)
    # header: SIDX magic, payloadsize@4, name@8, count@0x30, crc@0x34
    hdr = bytearray(0x48)
    hdr[0:4] = b"SIDX"
    struct.pack_into("<I", hdr, 0x30, len(paths_and_sizes))
    struct.pack_into("<I", hdr, 0x34, 0xffffffff)       # header CRC disabled
    return bytes(hdr) + body


def test_parse_records_maps_paths_to_payload_offsets():
    data = _build_sidx([("game/image.bin", 1000),
                        ("game/coil.hex", 200),
                        ("game/scene.radium", 50)])
    recs, hdr_crc = sidx.parse_records(data)
    assert hdr_crc == 0xffffffff
    assert set(recs) == {"game/image.bin", "game/coil.hex", "game/scene.radium"}
    # payload offset points at the size field we wrote (size readable there)
    po = recs["game/coil.hex"]
    assert struct.unpack_from("<I", data, po + 8)[0] == 200


def test_record_field_writes_offsets():
    writes = sidx.record_field_writes(1000, b"H" * 20, b"M" * 16)
    assert writes == [(1000 + 37, b"H" * 20), (1000 + 57, b"M" * 16)]


def test_parse_rejects_non_fi64():
    recs, hdr_crc = sidx.parse_records(b"not a sidx at all")
    assert recs == {} and hdr_crc is None


def test_digests_roundtrip_into_a_record():
    # Simulate refreshing a record: write the digests into the payload and read
    # them back at the documented offsets.
    data = bytearray(_build_sidx([("game/image.bin", 4)]))
    recs, _ = sidx.parse_records(bytes(data))
    po = recs["game/image.bin"]
    hm, md = sidx.digests(b"\x01\x02\x03\x04")
    for off, b in sidx.record_field_writes(po, hm, md):
        data[off:off + len(b)] = b
    assert bytes(data[po + 37:po + 57]) == hm
    assert bytes(data[po + 57:po + 73]) == md
