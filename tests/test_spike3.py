"""Spike 3 support: partition map, decrypting reader, key source, title map.

Pure + offline: no real card, no secrets.  The reader round-trip builds its own
ciphertext with luks_otp's XTS, so it proves the seek/decrypt/cache path with a
throwaway key.
"""

import io
import json
import os
import struct

import pytest

from pinball_decryptor.plugins.stern import spike3
from pinball_decryptor.plugins.stern import spike3_games as s3g
from pinball_decryptor.plugins.stern import spike3_keys as s3k


# --------------------------------------------------------------------------
# Partition map (MBR primaries + EBR logical chain)
# --------------------------------------------------------------------------
_LUKS2 = b"LUKS\xba\xbe\x00\x02"


def _mbr_entry(ptype, lba, sectors):
    return b"\x00\x00\x00\x00" + bytes([ptype]) + b"\x00\x00\x00" \
        + struct.pack("<II", lba, sectors)


def _build_spike3_disk():
    """A minimal Spike 3-shaped disk image in a BytesIO:

        p1 FAT(0x0c)@1 (64MB)  p2 LUKS@131073  p3 LUKS@1359873
        p4 extended(0x0f)@1409025  -> p5 LUKS, p6 LUKS (biggest)
    """
    SS = 512
    ext_base = 1409025
    p5_rel, p5_sectors = 1, 2048
    # second EBR sits a little past the first
    ebr2_rel = 4096
    p6_rel, p6_sectors = 1, 1_000_000

    size_sectors = 2_000_000
    buf = bytearray(SS * 64)          # we only need the low sectors + markers
    buf.extend(b"\x00" * (SS * 10))

    def put(lba, data):
        end = (lba * SS) + len(data)
        if end > len(buf):
            buf.extend(b"\x00" * (end - len(buf)))
        buf[lba * SS:lba * SS + len(data)] = data

    # --- primary MBR ---
    mbr = bytearray(SS)
    mbr[446:462] = _mbr_entry(0x0c, 1, 131072)
    mbr[462:478] = _mbr_entry(0x83, 131073, 1228800)
    mbr[478:494] = _mbr_entry(0x83, 1359873, 49152)
    mbr[494:510] = _mbr_entry(0x0f, ext_base, size_sectors - ext_base)
    mbr[510:512] = b"\x55\xaa"
    put(0, bytes(mbr))
    # LUKS magic at p2/p3 starts
    put(131073, _LUKS2)
    put(1359873, _LUKS2)

    # --- first EBR (p5) ---
    ebr1 = bytearray(SS)
    ebr1[446:462] = _mbr_entry(0x83, p5_rel, p5_sectors)       # p5 (relative)
    ebr1[462:478] = _mbr_entry(0x0f, ebr2_rel, 8192)           # -> next EBR
    ebr1[510:512] = b"\x55\xaa"
    put(ext_base, bytes(ebr1))
    put(ext_base + p5_rel, _LUKS2)

    # --- second EBR (p6) ---
    ebr2 = bytearray(SS)
    ebr2[446:462] = _mbr_entry(0x83, p6_rel, p6_sectors)       # p6 (relative)
    ebr2[510:512] = b"\x55\xaa"
    put(ext_base + ebr2_rel, bytes(ebr2))
    put(ext_base + ebr2_rel + p6_rel, _LUKS2)

    return io.BytesIO(bytes(buf))


def test_parse_partitions_primaries_and_logicals():
    f = _build_spike3_disk()
    parts = spike3.parse_partitions(f)
    by_idx = {p["index"]: p for p in parts}
    assert set(by_idx) == {1, 2, 3, 4, 5, 6}
    assert by_idx[1]["ptype"] == 0x0c and not by_idx[1]["luks"]
    assert by_idx[2]["luks"] and by_idx[2]["start_lba"] == 131073
    assert by_idx[3]["luks"]
    assert by_idx[5]["logical"] and by_idx[5]["luks"]
    assert by_idx[6]["logical"] and by_idx[6]["luks"]


def test_is_spike3_card_parts():
    f = _build_spike3_disk()
    parts = spike3.parse_partitions(f)
    assert spike3.is_spike3_card_parts(parts)
    # A plain non-LUKS disk is not a Spike 3 card.
    assert not spike3.is_spike3_card_parts(parts[:1])


def test_partition_for_role_games_is_largest_luks():
    f = _build_spike3_disk()
    parts = spike3.parse_partitions(f)
    games = spike3.partition_for_role(parts, "games")
    assert games["index"] == 6                      # biggest LUKS
    assert spike3.partition_for_role(parts, "rootfs")["index"] == 2


def test_non_mbr_returns_empty():
    assert spike3.parse_partitions(io.BytesIO(b"\x00" * 1024)) == []


# --------------------------------------------------------------------------
# DecryptingSegmentReader round-trip (its own XTS, throwaway key)
# --------------------------------------------------------------------------
class _FakeHeader:
    def __init__(self, sector_size=512, offset=0):
        self._seg = {"encryption": "aes-xts-plain64",
                     "sector_size": sector_size, "offset": str(offset)}

    def segment(self, idx="0"):
        return self._seg


def test_decrypting_reader_roundtrip():
    otp = spike3._luks_otp()
    key = bytes(range(64))                           # 64-byte XTS key
    sector = 512
    nsec = 20
    part_base_lba = 3
    seg_off = 0
    plain = os.urandom(sector * nsec)
    # encrypt per the segment's XTS (tweak == sector index from seg start)
    ct = otp.aes_xts_encrypt(key, plain, 0, sector)
    SS = 512
    buf = bytearray(part_base_lba * SS + seg_off + len(ct))
    buf[part_base_lba * SS + seg_off:] = ct
    f = io.BytesIO(bytes(buf))

    hdr = _FakeHeader(sector_size=sector, offset=seg_off)
    hdr._pad_part_sectors = (seg_off + len(ct)) // SS
    r = spike3.DecryptingSegmentReader(f, part_base_lba, hdr, key)

    assert r.size == len(plain)
    # whole-read, straddling reads, and a seek-back all return plaintext
    assert r.read() == plain
    r.seek(1000)
    assert r.read(2000) == plain[1000:3000]
    r.seek(sector * 5 - 7)                           # straddle a sector boundary
    assert r.read(30) == plain[sector * 5 - 7:sector * 5 + 23]


# --------------------------------------------------------------------------
# Title table / filename mapping
# --------------------------------------------------------------------------
def test_spike3_key_for_path():
    f = "star_wars_2025_pro-0_84_0.Release.64G.sdcard-secure.raw"
    assert s3g.spike3_key_for_path(f) == "star_wars_2025_pro"
    assert s3g.spike3_key_for_path("walking_dead_remastered_le-0_92_0.x.raw") \
        == "walking_dead_remastered_le"
    assert s3g.spike3_key_for_path("mystery_title-1_0_0.raw") \
        == s3g.SPIKE3_GENERIC_KEY


def test_spike3_display():
    assert "Star Wars 2025 PRO" in s3g.spike3_display("star_wars_2025_pro")
    assert s3g.spike3_display(s3g.SPIKE3_GENERIC_KEY,
                             "night_rider-1_0.raw") == "Night Rider (Spike 3)"


def test_only_one_supported_title():
    supported = [k for k, v in s3g.SPIKE3_DB.items() if v.get("supported")]
    assert supported == ["star_wars_2025_pro"]


# --------------------------------------------------------------------------
# Key source (no secrets; just loading/resolution)
# --------------------------------------------------------------------------
def test_as_32_bytes_hex_and_file(tmp_path):
    hexkey = "aa" * 32
    assert s3k._as_32_bytes(hexkey, "k") == bytes([0xaa]) * 32
    p = tmp_path / "k.bin"
    p.write_bytes(bytes(range(32)))
    assert s3k._as_32_bytes(str(p), "k") == bytes(range(32))
    with pytest.raises(s3k.Spike3KeyError):
        s3k._as_32_bytes("bb" * 10, "k")            # wrong length


def test_keysource_master_key_precedence():
    ks = s3k.Spike3KeySource(
        master_keys={"games": "11" * 32,
                     "img:games": "22" * 32},
        image_id="img")
    # image:role beats bare role
    assert ks.master_key(None, role="games") == bytes([0x22]) * 32
    ks2 = s3k.Spike3KeySource(master_keys={"games": "11" * 32})
    assert ks2.master_key(None, role="games") == bytes([0x11]) * 32


def test_keysource_from_keyfile_and_discover(tmp_path, monkeypatch):
    doc = {"master_keys": {"games": "33" * 32}}
    kf = tmp_path / "card.raw.padkeys.json"
    kf.write_text(json.dumps(doc))
    img = tmp_path / "card.raw"
    img.write_bytes(b"x")
    ks = s3k.Spike3KeySource.discover(image_path=str(img))
    assert ks is not None and ks.has_any()
    assert ks.master_key(None, role="games") == bytes([0x33]) * 32
    # env var wins
    envkf = tmp_path / "env.json"
    envkf.write_text(json.dumps({"master_keys": {"games": "44" * 32}}))
    monkeypatch.setenv("PAD_SPIKE3_KEYFILE", str(envkf))
    ks2 = s3k.Spike3KeySource.discover(image_path=str(img))
    assert ks2.master_key(None, role="games") == bytes([0x44]) * 32


def test_keysource_no_key_raises():
    ks = s3k.Spike3KeySource()
    assert not ks.has_any()
    with pytest.raises(s3k.Spike3KeyError):
        ks.master_key(None, role="games")


# --------------------------------------------------------------------------
# Preview gating of the Spike 3 era
# --------------------------------------------------------------------------
def test_spike3_era_is_preview_gated(monkeypatch):
    from pinball_decryptor.core import preview
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    m = SternManufacturer()
    monkeypatch.setattr(preview, "_active", set())
    assert "spike3" not in [e[0] for e in m.eras]
    monkeypatch.setattr(preview, "_active", {"spike3"})
    assert "spike3" in [e[0] for e in m.eras]


# --------------------------------------------------------------------------
# SPKS archive parser (synthetic round-trip, both FINF and FI64)
# --------------------------------------------------------------------------
def _build_spks(files, use_64):
    import struct as _s
    # STRS table
    strs = b""
    offs = []
    for name, _data in files:
        offs.append(len(strs))
        strs += name.encode() + b"\x00"
    # records + data
    recs = b""
    data = b""
    for (name, blob), noff in zip(files, offs):
        doff = len(data)
        if use_64:
            rec = _s.pack("<I", noff) + b"\x00\x00\x00\x00" \
                + _s.pack("<QQQ", len(blob), doff, len(blob)) \
                + _s.pack("<I", 0o100644) + b"\x00" * 44
            recs += b"FI64" + _s.pack("<I", 80) + rec
        else:
            rec = _s.pack("<IIIII", noff, len(blob), doff, len(blob), 0o100644) \
                + b"\x00" * 40
            recs += b"FINF" + _s.pack("<I", 60) + rec
        data += blob
    section = b"SPK0" + b"\xff\xff\xff\xff" + b"\x00" * 8
    section += b"SIDX" + _s.pack("<I", 8) + b"spike\x00\x00\x00"
    section += b"STRS" + _s.pack("<I", len(strs)) + strs
    section += recs
    section += b"FEND" + b"\x00\x00\x00\x00" + b"SDAT" + b"\x00\x00\x00\x00"
    section += data
    header = b"SPKS" + b"\xff\xff\xff\xff" + struct.pack("<III", 0x6A6F4697, 2, 1)
    return header + section


@pytest.mark.parametrize("use_64", [False, True])
def test_spks_roundtrip(use_64):
    from pinball_decryptor.plugins.stern import spks
    files = [("mfs/sd/0001.wav", b"RIFFxxxxWAVEfmt "),
             ("assets/lcd/GameLogo.png", b"\x89PNG\r\n\x1a\n" + b"IDATend"),
             ("image.bin", b"\x70\x04" + b"A" * 500)]
    blob = _build_spks(files, use_64)

    def read(off, n):
        return blob[off:off + n]

    arc = spks.SpksArchive(read, len(blob))
    assert len(arc.files) == 3
    png = arc.get("assets/lcd/GameLogo.png")
    assert png is not None and png.size == len(files[1][1])
    got = b"".join(arc.read_file(png))
    assert got == files[1][1]
    wav = arc.get("mfs/sd/0001.wav")
    assert b"".join(arc.read_file(wav)) == files[0][1]
