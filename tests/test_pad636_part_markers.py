"""PAD-636: descriptors whose op11 marker carries a parameter byte (``0b 00 xx 00``), and the
resolver's window running on into the next descriptor.

The descriptors here are Led Zeppelin Pro 1.22's own, de-whitened as the resolver hands them
back: sid 191 plays its record behind ``0b 00 01 00``; sid 470 plays one behind ``0b 00 00 00``
and ends at byte 28, where sid 471's descriptor starts, which plays its record behind
``0b 00 04 00``. A longer replacement of 191's or 471's record used to be trimmed (no
descriptor named it), and growing 471's moved sid 470's declared duration too."""

import struct

import pytest

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import clip_sounds as CS
from pinball_decryptor.plugins.stern.spike2 import emulator as EMU
from pinball_decryptor.plugins.stern.spike2 import sfx_names as SN

D191 = bytes.fromhex(
    "051c01d81d00000200110b00010009fb5ee8f537abb2110100afce15060f1154886083e419624dc04cf7ab"
    "2c7e50bb4c7a7c41f70d508f664a7aac196c5f5a07724ffd0b4a5653284594d548899197f7")
D470 = bytes.fromhex(
    "052001c85100000100050200110b000000c398f544e6e8167a110100052001474300000100050200110b0004"
    "00394f884642b8fb1d110100c12fac9f6c3c3a52fdfac4e9306b0816b787e44f22243526")
D471 = bytes.fromhex(
    "052001474300000100050200110b000400394f884642b8fb1d110100c12fac9f6c3c3a52fdfac4e9306b08"
    "16b787e44f222435262d0114771ee23a9196db1abd981628628e794d99f739b4ab8b0062be")
P191, P470, P471 = D191[14:22], D470[17:25], D471[17:25]
#: the key mask Led Zeppelin Pro 1.22's play tables measure (names 549 of its 549 records)
LZ_MASK = 0xFC0003FF
#: where each descriptor starts in the bank: 471's is 28 bytes past 470's
AT = {191: 0x4000, 470: 0x1000, 471: 0x101c}


def test_the_lz_windows_are_what_the_tests_say():
    assert D470[28:] == D471[:52]
    assert (D191[10:14], D470[13:17], D471[13:17]) == (
        b"\x0b\x00\x01\x00", b"\x0b\x00\x00\x00", b"\x0b\x00\x04\x00")


def test_op11_payloads_reads_the_marker_whatever_its_parameter_byte():
    assert E._op11_payloads(D191) == [(14, P191)]
    assert E._op11_payloads(D471) == [(17, P471)]
    # the window: sid 470's own payload, then sid 471's
    assert E._op11_payloads(D470) == [(17, P470), (45, P471)]
    # 0b 01 .. is not a marker, and nothing is found inside a payload
    desc = (b"\x05" + b"\x00" * 8 + b"\x0b\x01\x00\x00" + b"A" * 8
            + b"\x0b\x00\x02\x00" + b"\x0b\x00\x00\x00" + b"B" * 4 + b"\x00" * 8)
    assert E._op11_payloads(desc) == [(25, b"\x0b\x00\x00\x00BBBB")]


@pytest.fixture
def lz_resolver(monkeypatch):
    """The game's resolver stubbed to hand back the three Led Zeppelin windows."""
    class _Emu:
        def __init__(self, *a):
            pass

        def boot(self):
            pass

        def close(self):
            pass

    win = {191: D191, 470: D470, 471: D471}
    monkeypatch.setattr(EMU, "Spike2Emu", _Emu)
    monkeypatch.setattr(SN, "_find_resolver", lambda emu, fw=None: (0x1000, 0x2000))
    monkeypatch.setattr(SN, "sid_ceiling", lambda img, default=4096: 500)
    monkeypatch.setattr(
        SN, "resolve_descriptor",
        lambda emu, addr, out, sid: (AT[sid], bytes(0x50), win[sid]) if sid in win else None)


def test_a_descriptor_site_is_only_its_own_payloads(lz_resolver):
    sites = E._descriptor_sites("g", "i")
    assert sorted((s.sid, s.off, s.payload) for s in sites) == [
        (191, AT[191] + 14, P191),
        (470, AT[470] + 17, P470),
        (471, AT[471] + 17, P471)]
    assert {s.sid: s.duration for s in sites} == {191: 0x1dd8, 470: 0x51c8, 471: 0x4347}


def test_growing_a_record_behind_0b_00_04_00_repoints_its_own_sid_only(lz_resolver):
    """The plan names 471's record, moves 471's declared duration and leaves 470's alone."""
    sites = E._descriptor_sites("g", "i")
    stock = E._play_key(P471, 471, LZ_MASK)
    new = struct.pack("<II", 0x12345678, 0x000002bc)
    params = [{"idx": 7, "grown": True, "stock_findkey": stock, "findkey": new,
               "length": 44100 * 3, "stock_length": 44100}]
    writes, expect = E._plan_descriptor_repoint(params, sites, LZ_MASK, family=True)
    assert set(expect) == {471}
    assert set(writes) == {AT[471] + 17, AT[471] + 3}
    assert E._play_key(writes[AT[471] + 17], 471, LZ_MASK) == new        # (a zero keystream)


def test_a_grown_record_behind_0b_00_01_00_is_kept_for_the_repoint(lz_resolver):
    sites = E._descriptor_sites("g", "i")
    k0 = struct.unpack_from("<I", P191)[0]
    msgs = []
    kept = E._grows_named_by_a_descriptor({3: (10, 20)}, {3: {"idx": 3, "key0": k0}}, sites,
                                          lambda m, lvl="info": msgs.append(m))
    assert kept == {3: (10, 20)} and not msgs


def test_sound_test_primary_is_the_first_marker_whatever_its_parameter_byte():
    """Sid 508's first marker is 0b 00 04 00: read as none, the name went to the NEXT
    descriptor's record."""
    key0 = {struct.unpack_from("<I", P470)[0]: 1, struct.unpack_from("<I", P471)[0]: 2,
            struct.unpack_from("<I", P191)[0]: 3}
    assert SN._primary_idx(D471, key0) == 2
    assert SN._primary_idx(D191, key0) == 3
    assert SN._primary_idx(D470, key0) == 1


def test_request_parts_stop_where_the_next_descriptor_starts(lz_resolver):
    key0 = {struct.unpack_from("<I", P470)[0]: 1, struct.unpack_from("<I", P471)[0]: 2,
            struct.unpack_from("<I", P191)[0]: 3}
    params = [{"idx": i, "key0": k} for k, i in key0.items()]
    also = {}
    assert CS.resolve_requests(None, params, [[470], [471], [191]], also=also,
                               ceiling=500) == {0: [1], 1: [2], 2: [3]}
    assert also == {}
    # without the ceiling the window is read whole: 471's record counted as 470's later part
    also = {}
    CS.resolve_requests(None, params, [[470]], also=also)
    assert also == {0: [2]}
    assert SN._part_idxs(D470, key0) == [1, 2]
    assert SN._part_idxs(D470, key0, 28) == [1]


def test_a_sound_whose_codec_cannot_re_encode_is_not_lengthened(monkeypatch):
    """A sound that fails the re-encode self-test is not grown: the play table would be re-pointed
    at an appended record the encode then skipped. It trims, and says why. Led Zeppelin Pro 1.22's
    ten sounds behind 0b 00 01 00 / 0b 00 04 00 are its multi-band records (stride 12 / 24), which
    re-encode since PAD-637 but are never lengthened (idx 390 here)."""
    from pinball_decryptor.plugins.stern.spike2 import codec as CODEC

    class _Emu:
        def __init__(self, *a):
            pass

        def boot(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(EMU, "Spike2Emu", _Emu)
    monkeypatch.setattr(CODEC, "GenRecover", lambda emu: "gen")
    monkeypatch.setattr(CODEC, "StereoRecover", lambda emu: "st")
    monkeypatch.setattr(E, "_recovery_valid", lambda emu, gr, sr, p, np: p["stride"] in (1, 2))
    byidx = {390: {"idx": 390, "chan": 1, "stride": 12}, 0: {"idx": 0, "chan": 1, "stride": 1},
             269: {"idx": 269, "chan": 2, "stride": 2}}
    msgs = []
    kept = E._grows_reencodable("g", "i", {390: (1, 2), 0: (3, 4), 269: (5, 6), 7: (8, 9)}, byidx,
                                lambda m, lvl="info": msgs.append(m))
    assert kept == {0: (3, 4), 269: (5, 6)}
    assert [m.split(":")[0] for m in msgs] == ["idx 390", "idx 7"]
    assert all("trimmed to fit" in m for m in msgs)
    assert E._grows_reencodable("g", "i", {}, byidx, None) == {}
