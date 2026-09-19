"""Tests for appending a record to a Spike 2 ``.sidx`` (plugins/stern/sidx_append).

``sidx.py`` can only REFRESH a record that already exists.  A file the card never had
needs a new one, and Stern's ``spk`` fails SD validation on an unindexed file - so
this is the foundation under a mode's own audio, screen and video.

The fixture here deliberately builds BOTH REAL SHAPES rather than one convenient one.
``tests/test_stern_sidx.py`` builds a fixed 0x48 header with ``STRS`` always at 0x48
and no size total, which is FI64's layout with its ``SZ64`` block left out; measuring
14 real cards showed the container is a SEQUENCE OF TAGGED BLOCKS whose order differs
by format:

  * FI64 - ``SZ64`` (u64 size total) at 0x38, then ``STRS`` at 0x48, ``0x34`` is
    0xffffffff.  Real totals run 4.5-7.8 GB, which is why the field is 64-bit.
  * FINF - ``STRS`` at 0x38, no ``SZ64`` at all, and ``0x34`` carries the size total
    as a u32.

Anything that indexes 0x38 or 0x48 is reading one title's accident, which is exactly
the bug these tests exist to prevent.
"""

import struct

import pytest

from pinball_decryptor.plugins.stern import sidx, sidx_append

_PAYLOAD = {"FI64": 80, "FINF": 60}


def _build(paths_and_sizes, fmt="FI64", pkg="game_pro"):
    """A .sidx in the shape real cards of *fmt* actually use."""
    tag = fmt.encode()
    plen = _PAYLOAD[fmt]
    strs = b"".join(p.encode() + b"\x00" for p, _ in paths_and_sizes)
    total = sum(s for _p, s in paths_and_sizes)

    hdr = bytearray(0x38)
    hdr[0:4] = b"SIDX"
    hdr[8:8 + len(pkg)] = pkg.encode()
    struct.pack_into("<I", hdr, 0x30, len(paths_and_sizes))

    body = b""
    if fmt == "FI64":
        struct.pack_into("<I", hdr, 0x34, 0xFFFFFFFF)
        body += b"SZ64" + struct.pack("<I", 8) + struct.pack("<Q", total)
    else:
        struct.pack_into("<I", hdr, 0x34, total)

    body += b"STRS" + struct.pack("<I", len(strs)) + strs
    pack, *size_offs = sidx._SIZE_FIELDS[fmt]
    for _p, size in paths_and_sizes:
        payload = bytearray(plen)
        for off in size_offs:
            struct.pack_into(pack, payload, off, size)
        body += tag + struct.pack("<I", plen) + bytes(payload)

    out = bytearray(bytes(hdr) + body + sidx_append.FEND)
    struct.pack_into("<I", out, 0x04, len(out) - 8)
    return bytes(out)


@pytest.mark.parametrize("fmt", ["FI64", "FINF"])
def test_fixture_matches_the_real_invariants(fmt):
    # If the fixture itself violated what 14 cards agree on, every test below
    # would be testing a manifest no card would accept.
    data = _build([("game/a.bin", 10), ("game/b.bin", 20)], fmt=fmt)
    assert sidx_append.verify(data) == []
    assert sidx_append.size_total(data) == 30


@pytest.mark.parametrize("fmt", ["FI64", "FINF"])
def test_append_adds_a_record_and_keeps_every_invariant(fmt):
    data = _build([("game/a.bin", 10), ("game/b.bin", 20)], fmt=fmt)
    hm, md = sidx.digests(b"payload")
    out = sidx_append.append_record(data, "game/ours.radium", 4096, hm, md)

    assert sidx_append.verify(out, expect_paths=["game/ours.radium"]) == []
    recs, _crc, got_fmt = sidx.parse_records(out)
    assert got_fmt == fmt
    assert set(recs) == {"game/a.bin", "game/b.bin", "game/ours.radium"}
    # the count, the payload length word and the size total all moved together
    assert struct.unpack_from("<I", out, 0x30)[0] == 3
    assert struct.unpack_from("<I", out, 0x04)[0] == len(out) - 8
    assert sidx_append.size_total(out) == 10 + 20 + 4096


@pytest.mark.parametrize("fmt", ["FI64", "FINF"])
def test_appended_record_carries_its_size_and_digests(fmt):
    data = _build([("game/a.bin", 10)], fmt=fmt)
    hm, md = sidx.digests(b"our own asset")
    out = sidx_append.append_record(data, "game/ours.bin", 1234, hm, md)
    recs, _crc, _f = sidx.parse_records(out)
    po = recs["game/ours.bin"]
    pack, size_off = sidx._SIZE_FIELDS[fmt][0], sidx._SIZE_FIELDS[fmt][1]
    h_off, m_off = sidx._FORMATS[fmt]
    assert struct.unpack_from(pack, out, po + size_off)[0] == 1234
    assert out[po + h_off:po + h_off + 20] == hm
    assert out[po + m_off:po + m_off + 16] == md


@pytest.mark.parametrize("fmt", ["FI64", "FINF"])
def test_existing_records_are_untouched(fmt):
    data = _build([("game/a.bin", 10), ("game/b.bin", 20)], fmt=fmt)
    before, _c, _f = sidx.parse_records(data)
    hm, md = sidx.digests(b"x")
    out = sidx_append.append_record(data, "game/ours.bin", 7, hm, md)
    after, _c2, _f2 = sidx.parse_records(out)
    plen = _PAYLOAD[fmt]
    for path, old_po in before.items():
        assert data[old_po:old_po + plen] == out[after[path]:after[path] + plen]


@pytest.mark.parametrize("fmt", ["FI64", "FINF"])
def test_the_new_path_and_record_go_last_and_in_step(fmt):
    # Record i belongs to path i, so a path appended anywhere but the end would
    # silently re-point every record after it.
    data = _build([("game/a.bin", 1), ("game/b.bin", 2)], fmt=fmt)
    hm, md = sidx.digests(b"x")
    out = sidx_append.append_record(data, "game/zzz.bin", 3, hm, md)
    si = out.find(b"STRS")
    sl = struct.unpack_from("<I", out, si + 4)[0]
    paths = [p.decode() for p in out[si + 8:si + 8 + sl].split(b"\x00") if p]
    assert paths == ["game/a.bin", "game/b.bin", "game/zzz.bin"]


def test_finf_refuses_rather_than_overflowing_its_u32_total():
    # FINF stores the size total in a 32-bit header word; real cards sit 1.2-3.2 GB
    # below the ceiling.  Wrapping would produce a manifest that disagrees with its
    # own records, so this must refuse.
    data = _build([("game/a.bin", 0xFFFFFF00)], fmt="FINF")
    hm, md = sidx.digests(b"x")
    with pytest.raises(sidx_append.SidxAppendError):
        sidx_append.append_record(data, "game/ours.bin", 0x1000, hm, md)


def test_fi64_has_the_headroom_finf_lacks():
    # The same addition on FI64 is fine: its total is a u64 (real cards 4.5-7.8 GB).
    data = _build([("game/a.bin", 0xFFFFFF00)], fmt="FI64")
    hm, md = sidx.digests(b"x")
    out = sidx_append.append_record(data, "game/ours.bin", 0x1000, hm, md)
    assert sidx_append.size_total(out) == 0xFFFFFF00 + 0x1000
    assert sidx_append.verify(out) == []


def test_refuses_a_duplicate_path():
    data = _build([("game/a.bin", 10)])
    hm, md = sidx.digests(b"x")
    with pytest.raises(sidx_append.SidxAppendError):
        sidx_append.append_record(data, "game/a.bin", 10, hm, md)


def test_refuses_a_path_with_a_nul():
    data = _build([("game/a.bin", 10)])
    hm, md = sidx.digests(b"x")
    with pytest.raises(sidx_append.SidxAppendError):
        sidx_append.append_record(data, "game/a\x00b.bin", 10, hm, md)


def test_refuses_something_that_is_not_a_manifest():
    hm, md = sidx.digests(b"x")
    with pytest.raises(sidx_append.SidxAppendError):
        sidx_append.append_record(b"not a sidx at all", "game/x", 1, hm, md)


@pytest.mark.parametrize("fmt", ["FI64", "FINF"])
def test_verify_catches_a_stale_count(fmt):
    data = bytearray(_build([("game/a.bin", 10)], fmt=fmt))
    struct.pack_into("<I", data, 0x30, 99)
    assert any("0x30" in b for b in sidx_append.verify(bytes(data)))


@pytest.mark.parametrize("fmt", ["FI64", "FINF"])
def test_verify_catches_a_stale_size_total(fmt):
    data = bytearray(_build([("game/a.bin", 10)], fmt=fmt))
    sz = data.find(b"SZ64")
    if sz >= 0:
        struct.pack_into("<Q", data, sz + 8, 12345)
    else:
        struct.pack_into("<I", data, 0x34, 12345)
    assert any("size total" in b for b in sidx_append.verify(bytes(data)))


@pytest.mark.parametrize("fmt", ["FI64", "FINF"])
def test_verify_catches_a_stale_payload_length_word(fmt):
    data = bytearray(_build([("game/a.bin", 10)], fmt=fmt))
    struct.pack_into("<I", data, 0x04, 1)
    assert any("0x04" in b for b in sidx_append.verify(bytes(data)))


@pytest.mark.parametrize("fmt", ["FI64", "FINF"])
def test_block_order_is_walked_not_assumed(fmt):
    # The point of the whole module: FI64 puts SZ64 at 0x38 and STRS at 0x48, FINF
    # puts STRS at 0x38.  Appending must work on both without indexing either.
    data = _build([("game/a.bin", 10)], fmt=fmt)
    si = data.find(b"STRS")
    assert si == (0x48 if fmt == "FI64" else 0x38)
    hm, md = sidx.digests(b"x")
    out = sidx_append.append_record(data, "game/ours.bin", 5, hm, md)
    assert out.find(b"STRS") == si          # the block did not move
    assert sidx_append.verify(out) == []
