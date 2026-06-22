"""Tests for the Stern Spike 2 Direct-SD path (raw-device read/write wiring).

These cover the deterministic, hardware-free pieces:

  * the byte-level MBR helpers that recognise a Spike 2 card + locate its ext
    partitions from a raw device's first 512 bytes;
  * :class:`RawDeviceFile` — sector-aligned reads return the same bytes as a
    plain file read, and sector-aligned read-modify-write lands the same bytes a
    plain ``seek``/``write`` would (validated against forced 512- and 4096-byte
    sectors over a backing file);
  * the equivalence that matters for Direct-SD: applying the engine's flat patch
    list through a writable ``RawDeviceFile`` produces a result byte-identical to
    applying it to an image copy — the offline analog of the on-hardware
    "read-from-card == read-from-image / round-trip write-back" check;
  * :func:`engine.device_partitions` verify/override/error behaviour.

The full extract/write-from-a-real-card path still needs the hardware test
(Administrator + the user's actual card) — see the GUI/feature handoff.
"""

import struct

import pytest

from pinball_decryptor.plugins.stern import engine, formats
from pinball_decryptor.plugins.stern.rawdevice import (RawDeviceFile,
                                                       is_device_path, read_mbr)


# ---- synthetic MBRs --------------------------------------------------------

def _spike_mbr(linux_sectors=4096000):
    """A Stern Spike 2 MBR: 8 MB FAT boot @LBA 8192 + ext @LBA 24576."""
    mbr = bytearray(512)
    struct.pack_into("<B", mbr, 446 + 4, 0x0c)              # p0 type: FAT
    struct.pack_into("<II", mbr, 446 + 8, 8192, 16384)      # p0 lba, sectors
    struct.pack_into("<B", mbr, 446 + 16 + 4, 0x83)         # p1 type: Linux
    struct.pack_into("<II", mbr, 446 + 16 + 8, 24576, linux_sectors)
    mbr[510:512] = b"\x55\xaa"
    return bytes(mbr)


def _generic_mbr():
    """A non-Spike 2-partition MBR (wrong boot geometry)."""
    mbr = bytearray(512)
    struct.pack_into("<B", mbr, 446 + 4, 0x0c)
    struct.pack_into("<II", mbr, 446 + 8, 2048, 1024000)    # not LBA 8192
    struct.pack_into("<B", mbr, 446 + 16 + 4, 0x83)
    struct.pack_into("<II", mbr, 446 + 16 + 8, 1026048, 4096000)
    mbr[510:512] = b"\x55\xaa"
    return bytes(mbr)


# ---- formats byte-level helpers -------------------------------------------

def test_parse_mbr_partitions_bytes_reads_both_entries():
    parts = formats.parse_mbr_partitions_bytes(_spike_mbr())
    assert len(parts) == 2
    assert parts[0] == (0, 0x0c, 8192, 16384)
    assert parts[1] == (1, 0x83, 24576, 4096000)


def test_parse_mbr_partitions_bytes_rejects_no_signature():
    assert formats.parse_mbr_partitions_bytes(b"\x00" * 512) == []
    assert formats.parse_mbr_partitions_bytes(b"\x00" * 100) == []


def test_is_spike_card_parts():
    assert formats.is_spike_card_parts(
        formats.parse_mbr_partitions_bytes(_spike_mbr())) is True
    assert formats.is_spike_card_parts(
        formats.parse_mbr_partitions_bytes(_generic_mbr())) is False
    assert formats.is_spike_card_parts([]) is False


def test_linux_partitions_from_parts_offsets_are_bytes_largest_first():
    parts = formats.parse_mbr_partitions_bytes(_spike_mbr())
    lp = formats.linux_partitions_from_parts(parts)
    # Only the Linux (0x83) partition, expressed in bytes.
    assert lp == [(24576 * 512, 4096000 * 512)]


# ---- is_device_path --------------------------------------------------------

def test_is_device_path_current_platform():
    import sys
    if sys.platform == "win32":
        assert is_device_path(r"\\.\PHYSICALDRIVE2") is True
        assert is_device_path(r"\\.\physicaldrive0") is True
        assert is_device_path(r"C:\cards\game.img") is False
    else:
        assert is_device_path("/dev/sdb") is True
        assert is_device_path("/home/user/game.img") is False
    assert is_device_path("") is False
    assert is_device_path(None) is False


# ---- RawDeviceFile reads (vs a plain file) ---------------------------------

def _pattern(n):
    return bytes((i * 13 + 5) & 0xff for i in range(n))


@pytest.mark.parametrize("sector", [512, 4096])
def test_rawdevice_read_matches_plain_file(tmp_path, sector):
    base = _pattern(70000)
    p = tmp_path / "img.bin"
    p.write_bytes(base)
    with RawDeviceFile(str(p), sector=sector) as f:
        assert f.sector == sector
        # aligned, unaligned-offset, unaligned-length, cross-sector, tail reads
        for off, n in [(0, 16), (1024, 1024), (1000, 37), (4093, 10),
                       (65000, 5000), (69990, 10), (0, 0)]:
            f.seek(off)
            assert f.read(n) == base[off:off + n], (off, n)
        # read-to-EOF
        f.seek(50000)
        assert f.read(-1) == base[50000:]


# ---- RawDeviceFile writes (RMW) vs a plain file ----------------------------

# Arbitrary-offset, arbitrary-length, overlapping, and tail patches.
_PATCHES = [
    (1000, b"\xAA" * 37),       # unaligned offset + length
    (4096, b"hello"),           # aligned offset
    (4093, b"X" * 10),          # spans a sector boundary, overlaps prev
    (8192, b"\x00" * 512),      # exactly one sector
    (199990, b"Z" * 10),        # ends exactly at EOF
]


@pytest.mark.parametrize("sector", [512, 4096])
def test_apply_writes_via_rawdevice_matches_image_copy(tmp_path, sector):
    base = _pattern(200000)

    # Reference: apply the patches to an image copy the proven (file) way.
    ref = tmp_path / "ref.img"
    ref.write_bytes(base)
    with open(ref, "r+b") as out:
        engine._apply_writes(out, _PATCHES)

    # Direct-SD: apply the SAME flat patch list through a writable
    # RawDeviceFile (sector-aligned read-modify-write).
    dev = tmp_path / "dev.img"
    dev.write_bytes(base)
    with RawDeviceFile(str(dev), writable=True, sector=sector) as out:
        engine._apply_writes(out, _PATCHES)
        out.flush()

    assert dev.read_bytes() == ref.read_bytes()


def test_rawdevice_read_only_rejects_write(tmp_path):
    p = tmp_path / "ro.bin"
    p.write_bytes(_pattern(4096))
    with RawDeviceFile(str(p), writable=False, sector=512) as f:
        with pytest.raises(OSError):
            f.write(b"nope")


# ---- read_mbr integration --------------------------------------------------

def test_read_mbr_returns_first_512_bytes(tmp_path):
    mbr = _spike_mbr()
    p = tmp_path / "card.img"
    p.write_bytes(mbr + _pattern(100000))
    assert read_mbr(str(p)) == mbr
    # And it round-trips through the byte helpers to a Spike verdict.
    assert formats.is_spike_card_parts(
        formats.parse_mbr_partitions_bytes(read_mbr(str(p)))) is True


def test_read_mbr_bad_path_returns_empty():
    assert read_mbr("\\\\.\\PHYSICALDRIVE_does_not_exist_999") == b""


# ---- engine.device_partitions ---------------------------------------------

def test_device_partitions_accepts_spike_card(monkeypatch):
    import pinball_decryptor.plugins.stern.rawdevice as rawdevice
    monkeypatch.setattr(rawdevice, "read_mbr", lambda _p: _spike_mbr())
    parts = engine.device_partitions(r"\\.\PHYSICALDRIVE9")
    assert parts == [(24576 * 512, 4096000 * 512)]


def test_device_partitions_rejects_non_spike(monkeypatch):
    import pinball_decryptor.plugins.stern.rawdevice as rawdevice
    monkeypatch.setattr(rawdevice, "read_mbr", lambda _p: _generic_mbr())
    with pytest.raises(RuntimeError, match="isn't a Stern Spike 2 SD card"):
        engine.device_partitions(r"\\.\PHYSICALDRIVE9")


def test_device_partitions_unreadable_device_mentions_admin(monkeypatch):
    import pinball_decryptor.plugins.stern.rawdevice as rawdevice
    monkeypatch.setattr(rawdevice, "read_mbr", lambda _p: b"")
    with pytest.raises(RuntimeError, match="Administrator"):
        engine.device_partitions(r"\\.\PHYSICALDRIVE9")


def test_device_partitions_honours_partition_override(monkeypatch):
    import pinball_decryptor.plugins.stern.rawdevice as rawdevice
    monkeypatch.setattr(rawdevice, "read_mbr", lambda _p: _spike_mbr())
    # Force partition #1 (the FAT boot) — 1-based; returns just that entry.
    parts = engine.device_partitions(r"\\.\PHYSICALDRIVE9", partition_override=1)
    assert parts == [(8192 * 512, 16384 * 512)]


# ---- pipeline / capability wiring ------------------------------------------

def test_direct_ssd_pipelines_are_wired_not_pending():
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    mfr = SternManufacturer()
    noop = lambda *a, **k: None
    ex = mfr.make_direct_ssd_extract_pipeline(
        r"\\.\PHYSICALDRIVE9", "out", noop, noop, noop, noop)
    wr = mfr.make_direct_ssd_write_pipeline(
        r"\\.\PHYSICALDRIVE9", "assets", noop, noop, noop, noop)
    assert ex.device_path == r"\\.\PHYSICALDRIVE9"
    assert wr.assets_dir == "assets"
    # Direct-extract phase indices must line up with what engine.extract_all
    # drives (it calls phase(2..5)); the tuple needs >= 6 entries ending in
    # Checksums.
    assert len(mfr.direct_ssd_extract_phases) == 6
    assert mfr.direct_ssd_extract_phases[-1] == "Checksums"
    assert mfr.direct_ssd_write_phases == ("Scan", "Re-encode audio",
                                           "Write to SD card")


# ---- live decode-progress formatting --------------------------------------

def test_dur_str_formats_minutes_seconds():
    # 271 s = 4:31, stereo / mono prefix.
    assert engine._dur_str(44100 * 271, 2) == "(stereo 4:31)"
    assert engine._dur_str(44100 * 5, 1) == "(mono 0:05)"


def test_bar_fills_proportionally():
    assert engine._bar(0.0, 10) == "[..........]"
    assert engine._bar(1.0, 10) == "[##########]"
    assert engine._bar(0.5, 10) == "[#####.....]"
    # Out-of-range fracs are clamped, never overflow the width.
    assert engine._bar(2.0, 8) == "[########]"
    assert engine._bar(-1.0, 8) == "[........]"


def test_decode_line_renders_start_prog_done():
    # One key per sound so the GUI rewrites a single line in place.
    k, t, lvl = engine._decode_line(("start", 453, 44100 * 271, 2))
    assert k == "dec453" and "0%" in t and "(stereo 4:31)" in t and lvl == "info"
    k, t, lvl = engine._decode_line(("prog", 453, 0.42, 44100 * 271, 2))
    assert k == "dec453" and "42%" in t and "idx0453" in t and lvl == "info"
    k, t, lvl = engine._decode_line(("done", 453, 44100 * 271, 2))
    assert k == "dec453" and "decoded" in t and lvl == "success"


def test_emit_decode_inplace_vs_append_fallback():
    # With a log_line cb: every event forwarded keyed (in-place).
    keyed = []
    engine._emit_decode(("start", 7, 44100, 1), None,
                        lambda k, t, l: keyed.append((k, t, l)))
    engine._emit_decode(("done", 7, 44100, 1), None,
                        lambda k, t, l: keyed.append((k, t, l)))
    assert [k for k, _, _ in keyed] == ["dec7", "dec7"]      # same line key
    # Without a cb (non-GUI): only 'done' appends, 'start'/'prog' are silent.
    appended = []
    log = lambda t, level="info": appended.append((level, t))
    engine._emit_decode(("start", 7, 44100, 1), log, None)
    engine._emit_decode(("prog", 7, 0.5, 44100, 1), log, None)
    engine._emit_decode(("done", 7, 44100, 1), log, None)
    assert len(appended) == 1 and "decoded" in appended[0][1]


def test_direct_extract_rejects_a_file_path():
    from pinball_decryptor.core.pipeline_base import PipelineError
    from pinball_decryptor.plugins.stern.pipeline import (
        SternDirectSsdExtractPipeline)
    errs = []
    pipe = SternDirectSsdExtractPipeline(
        "C:/cards/game.img", "out",
        log_cb=lambda *a, **k: None, phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None,
        done_cb=lambda ok, msg: errs.append((ok, msg)))
    pipe.run()
    assert errs and errs[0][0] is False
    assert "physical drive" in errs[0][1].lower()
