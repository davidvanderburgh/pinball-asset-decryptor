"""Tests for the Williams (WPC-era) plugin.

The plugin uses a real WPC DMD decoder (port of permartinson/wpcedit.js),
so the tests below focus on:

  - detect() picks up our known games from a MAME-style zip
  - the WPC ROM wrapper rejects non-WPC sizes
  - the 6809 signature scan finds plausible table addresses on
    real ROMs when present, and returns None on noise
  - decode_00 produces byte-for-byte the source bytes (the simplest
    encoding; if this breaks the layout is wrong)
  - the full Extract pipeline runs end-to-end against a synthetic
    zip (gated on ffmpeg, which renders the browse MP4)
"""

import os
import shutil
import zipfile

import pytest

from tests import synthetic
from tests._runner import run_pipeline_sync


HAS_FFMPEG = shutil.which("ffmpeg") is not None


# ---------------------------------------------------------------------------
# detect()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("game_key",
                         ["fish_tales", "white_water", "no_fear"])
def test_williams_detect_zip(manufacturers_by_key, tmp_path, game_key):
    w = manufacturers_by_key["williams"]
    z = synthetic.make_williams_rom_zip(
        tmp_path / f"{game_key}.zip", game_key=game_key)
    game = w.detect(str(z))
    assert game is not None, f"Williams.detect failed for {game_key}"
    assert game.key == game_key
    assert game.manufacturer_key == "williams"


def test_williams_detect_rejects_unrelated(manufacturers_by_key, tmp_path):
    w = manufacturers_by_key["williams"]
    unrelated = tmp_path / "random.zip"
    with zipfile.ZipFile(unrelated, "w") as zf:
        zf.writestr("unrelated.bin", b"\x00" * 64)
    assert w.detect(str(unrelated)) is None


def test_williams_detect_rejects_non_zip(manufacturers_by_key, tmp_path):
    w = manufacturers_by_key["williams"]
    not_zip = tmp_path / "not_a_zip.bin"
    not_zip.write_bytes(b"\x00" * 64)
    assert w.detect(str(not_zip)) is None


# ---------------------------------------------------------------------------
# WPC ROM wrapper
# ---------------------------------------------------------------------------

def test_wpc_rom_rejects_wrong_size():
    from pinball_decryptor.plugins.williams import wpc_decode
    with pytest.raises(ValueError):
        wpc_decode.WpcRom(b"\x00" * 12345)


@pytest.mark.parametrize("size", [0x40000, 0x80000, 0x100000])
def test_wpc_rom_accepts_valid_sizes(size):
    from pinball_decryptor.plugins.williams import wpc_decode
    rom = wpc_decode.WpcRom(b"\x00" * size)
    assert rom.size == size
    # Each WPC ROM has at least one paged page plus 2 non-paged pages.
    assert rom.total_pages >= 3


# ---------------------------------------------------------------------------
# Signature scan
# ---------------------------------------------------------------------------

def test_find_table_addresses_returns_none_on_noise():
    """Random bytes should not match the 6809 instruction signature."""
    import random
    from pinball_decryptor.plugins.williams import wpc_decode
    rng = random.Random(42)
    data = bytes(rng.randrange(256) for _ in range(0x40000))
    rom = wpc_decode.WpcRom(data)
    tables = wpc_decode.find_table_addresses(rom)
    assert tables.font_ptr_rom is None


# ---------------------------------------------------------------------------
# decode_00 byte-for-byte roundtrip
# ---------------------------------------------------------------------------

def test_decode_00_copies_raw_bytes():
    """Encoding 0x00 is just a 512-byte copy — easy to verify."""
    from pinball_decryptor.plugins.williams import wpc_decode
    # Build a 256 KB ROM with a recognisable 512-byte frame at offset 0x4001
    # (right after a 0x00 encoding byte at 0x4000).
    rom_bytes = bytearray(0x40000)
    rom_bytes[0x4000] = 0x00   # encoding type byte
    frame = bytes((i * 7 + 3) & 0xFF for i in range(512))
    rom_bytes[0x4001:0x4001 + 512] = frame
    rom = wpc_decode.WpcRom(bytes(rom_bytes))
    plane = wpc_decode.DmdPlane()
    plane = wpc_decode.decode_full_frame_image(rom, 0x4000, plane)
    assert plane.status == wpc_decode.PLANE_VALID
    assert plane.encoding == 0x00
    assert plane.data == frame


# ---------------------------------------------------------------------------
# Address conversion (port of getROMAddressFromWPCAddrAndPage)
# ---------------------------------------------------------------------------

def test_rom_addr_from_wpc_nonpaged():
    """Non-paged WPC addresses sit in the last 32 KB of ROM."""
    from pinball_decryptor.plugins.williams import wpc_decode
    rom = wpc_decode.WpcRom(b"\x00" * 0x80000)  # 512 KB, 32 pages
    # 0x8000 in non-paged ROM => start of the last two pages
    off = wpc_decode.rom_addr_from_wpc(rom, 0x8000, 0xFF)
    assert off == 0x78000
    # 0xFFFE => end of ROM minus 2 bytes
    off = wpc_decode.rom_addr_from_wpc(rom, 0xFFFE, 0xFF)
    assert off == 0x7FFFE


def test_rom_addr_from_wpc_paged():
    """Paged addresses map (page - basePage) * 16 KB + (addr - 0x4000)."""
    from pinball_decryptor.plugins.williams import wpc_decode
    data = bytearray(0x80000)
    data[0] = 0x20  # basePageIndex marker
    rom = wpc_decode.WpcRom(bytes(data))
    assert rom.base_page_index == 0x20
    # Page 0x20 / addr 0x4000 => ROM offset 0
    assert wpc_decode.rom_addr_from_wpc(rom, 0x4000, 0x20) == 0
    # Page 0x21 / addr 0x5000 => ROM offset 16 KB + 0x1000
    assert (wpc_decode.rom_addr_from_wpc(rom, 0x5000, 0x21)
            == 0x4000 + 0x1000)


# ---------------------------------------------------------------------------
# End-to-end pipeline (ffmpeg-gated)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not on PATH")
def test_williams_extract_synthetic_zip(manufacturers_by_key, tmp_path):
    """The pipeline should run cleanly on a synthetic zip and fail with
    a useful error (font table not found) rather than crash.

    The synthetic fixture doesn't include the real WPC 6809 instruction
    signature, so detection of the master tables will fail — but the
    pipeline should report that as a clean ``PipelineError`` rather
    than raising.
    """
    w = manufacturers_by_key["williams"]
    z = synthetic.make_williams_rom_zip(
        tmp_path / "fish_tales.zip", game_key="fish_tales")
    out_dir = tmp_path / "extracted"
    out_dir.mkdir()
    pipeline = w.make_extract_pipeline(
        str(z), str(out_dir),
        log_cb=lambda *a, **k: None,
        phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None,
        done_cb=lambda *a, **k: None)
    result = run_pipeline_sync(pipeline)
    # Synthetic ROM bytes are all zero — no 6809 signature — so the
    # pipeline should fail at the "Find tables" phase with a user-
    # friendly error rather than crash.  ``success`` is False, but
    # the summary explains why.
    assert result.success is False
    assert ("font-table" in result.summary.lower()
            or "table" in result.summary.lower()), \
        f"Unexpected failure summary: {result.summary}"
