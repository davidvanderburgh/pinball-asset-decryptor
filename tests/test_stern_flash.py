"""Tests for the Stern Spike 2 flash-image path (dd-style whole-card write).

Hardware-free coverage of the flasher core + pipeline wiring:

  * ``flash_image_to_device`` raw-copies an image onto a device byte-for-byte
    (validated against a backing file at forced 512- and 4096-byte sectors),
    preserving any bytes past the image's end in the final partial sector;
  * the size guard refuses an image larger than the target card;
  * an unknown card size proceeds with a logged warning (not a block);
  * ``copy_image_onto`` honours ``cancel`` mid-stream (partial write + raise);
  * ``flash_preflight`` / ``device_size`` / ``format_size`` helpers;
  * the :class:`SternFlashImagePipeline` rejects bad inputs and, fed a writable
    backing file, drives Check/Write/Flush to a successful done;
  * capability + factory wiring (era-aware ``flash_image``, ``flash_phases``).

The actual on-card flash still needs the hardware test (Administrator + a real
card + a backup) — see docs/STERN_SPIKE2_TODO.md.
"""

import pytest

from pinball_decryptor.core.pipeline_base import PipelineError
from pinball_decryptor.core import rawdevice as rd
from pinball_decryptor.plugins.stern.pipeline import SternFlashImagePipeline
from pinball_decryptor.core.rawdevice import (FlashCancelled,
                                             FlashError, RawDeviceFile)


def _pattern(n):
    return bytes((i * 13 + 5) & 0xff for i in range(n))


# ---- flash_image_to_device byte-equivalence --------------------------------

@pytest.mark.parametrize("sector", [512, 4096])
def test_flash_writes_image_bytes_and_preserves_tail(tmp_path, sector):
    # Image is deliberately NOT a sector multiple, so the final (partial) sector
    # exercises the read-modify-write tail path.
    img_bytes = _pattern(5000)
    img = tmp_path / "src.img"
    img.write_bytes(img_bytes)
    # Card pre-filled with 0xAA so we can see the tail of the last sector is
    # preserved (only the image's footprint should change).
    card = tmp_path / "card.dev"
    card.write_bytes(b"\xAA" * 16384)

    written = rd.flash_image_to_device(
        str(img), str(card),
        # force the sector via a pre-opened device? flash opens its own
        # RawDeviceFile; a plain file probes to 512.  Re-run the body manually
        # at the requested sector for the 4096 case.
    ) if sector == 512 else _flash_at_sector(str(img), str(card), sector)

    out = card.read_bytes()
    assert written == 5000
    assert out[:5000] == img_bytes                       # image landed verbatim
    # The remainder of the final sector that held image bytes stays 0xAA (RMW).
    last_sec_start = (5000 // sector) * sector
    assert out[5000:last_sec_start + sector].count(0xAA) == (
        last_sec_start + sector - 5000)
    # Everything past that sector is untouched.
    assert out[last_sec_start + sector:] == b"\xAA" * (
        16384 - (last_sec_start + sector))


def _flash_at_sector(img_path, dev_path, sector):
    """flash_image_to_device equivalent with a forced sector (for the 4096 case
    a regular backing file would otherwise probe to 512)."""
    import os
    img_size = os.path.getsize(img_path)
    with RawDeviceFile(dev_path, writable=True, sector=sector) as dev:
        with open(img_path, "rb") as src:
            written = dev.copy_image_onto(src, img_size)
        dev.flush()
    return written


def test_flash_full_sector_multiple_uses_fast_path(tmp_path):
    img_bytes = _pattern(8192)            # exact multiple of 512
    img = tmp_path / "a.img"
    img.write_bytes(img_bytes)
    card = tmp_path / "b.dev"
    card.write_bytes(b"\x00" * 20000)
    written = rd.flash_image_to_device(str(img), str(card))
    assert written == 8192
    assert card.read_bytes()[:8192] == img_bytes


# ---- size guard ------------------------------------------------------------

def test_flash_refuses_image_larger_than_card(tmp_path):
    img = tmp_path / "big.img"
    img.write_bytes(b"\x01" * 20000)
    card = tmp_path / "small.dev"
    card.write_bytes(b"\x00" * 8192)
    with pytest.raises(FlashError, match="larger than the card"):
        rd.flash_image_to_device(str(img), str(card))
    # The card must be left untouched when the write is refused.
    assert card.read_bytes() == b"\x00" * 8192


def test_flash_unknown_card_size_warns_but_proceeds(tmp_path, monkeypatch):
    img_bytes = _pattern(4096)
    img = tmp_path / "x.img"
    img.write_bytes(img_bytes)
    card = tmp_path / "y.dev"
    card.write_bytes(b"\x00" * 8192)
    # Force "unknown size" by stubbing the probe to None.
    monkeypatch.setattr(RawDeviceFile, "size", property(lambda self: None))
    logs = []
    written = rd.flash_image_to_device(
        str(img), str(card), log=lambda m, l="info": logs.append((l, m)))
    assert written == 4096
    assert card.read_bytes()[:4096] == img_bytes
    assert any(lvl == "warning" and "capacity check" in msg
               for lvl, msg in logs)


# ---- cancel ----------------------------------------------------------------

def test_copy_image_onto_cancels_mid_stream(tmp_path):
    img = tmp_path / "c.img"
    img.write_bytes(_pattern(4096))
    card = tmp_path / "d.dev"
    card.write_bytes(b"\x00" * 8192)
    # A cancel that fires only AFTER the first chunk has landed, plus a small
    # chunk, so some bytes are written before the cancel raises.
    state = {"calls": 0}

    def _cancel():
        state["calls"] += 1
        return state["calls"] > 1      # False on the first poll, True after

    import os
    with RawDeviceFile(str(card), writable=True, sector=512) as dev:
        with open(img, "rb") as src:
            with pytest.raises(FlashCancelled):
                dev.copy_image_onto(src, os.path.getsize(img),
                                    cancel=_cancel, chunk=512)
    # The first 512-byte chunk landed before the cancel.
    assert card.read_bytes()[:512] == _pattern(4096)[:512]


def test_flash_cancel_immediately_writes_nothing(tmp_path):
    img = tmp_path / "e.img"
    img.write_bytes(_pattern(4096))
    card = tmp_path / "f.dev"
    card.write_bytes(b"\x00" * 8192)
    with pytest.raises(FlashCancelled):
        rd.flash_image_to_device(str(img), str(card), cancel=lambda: True)
    assert card.read_bytes() == b"\x00" * 8192


# ---- helpers ---------------------------------------------------------------

def test_flash_preflight_and_device_size(tmp_path):
    img = tmp_path / "g.img"
    img.write_bytes(b"\x02" * 12345)
    card = tmp_path / "h.dev"
    card.write_bytes(b"\x00" * 65536)
    img_size, dev_size = rd.flash_preflight(str(img), str(card))
    assert img_size == 12345
    assert dev_size == 65536
    assert rd.device_size(str(card)) == 65536


def test_device_size_bad_path_is_none():
    assert rd.device_size("\\\\.\\PHYSICALDRIVE_nope_999") is None


def test_format_size():
    assert rd.format_size(None) == "unknown"
    assert rd.format_size(0) == "0 bytes"
    assert rd.format_size(16_000_000_000) == "16.00 GB"
    assert rd.format_size(5_000_000) == "5.0 MB"
    assert rd.format_size(2048) == "2 KB"


# ---- Windows disk-offline wrapper ------------------------------------------

def test_physicaldrive_number_parsing():
    assert rd._physicaldrive_number(r"\\.\PHYSICALDRIVE3") == 3
    assert rd._physicaldrive_number(r"\\.\physicaldrive12") == 12
    assert rd._physicaldrive_number("/dev/sdb") is None
    assert rd._physicaldrive_number("C:/cards/game.img") is None
    assert rd._physicaldrive_number("") is None
    assert rd._physicaldrive_number(None) is None


def test_disk_offline_is_noop_for_file_paths(monkeypatch):
    # A backing-file "device" (tests) must NOT shell out to Set-Disk — guard
    # against a regression that would run PowerShell against a file path.
    def _boom(*a, **k):
        raise AssertionError("Set-Disk should not run for a file path")
    monkeypatch.setattr(rd.subprocess, "run", _boom)
    with rd._disk_offline_for_write("C:/cards/game.img"):
        pass            # context body — must complete without invoking _boom


def test_locked_volumes_is_noop_for_file_paths():
    # For a file path (not \\.\PHYSICALDRIVEn) the volume lock/dismount must do
    # nothing and just yield — it must never touch any real volume.
    ran = []
    with rd._locked_volumes("C:/cards/game.img"):
        ran.append(True)
    assert ran == [True]


# ---- pipeline --------------------------------------------------------------

def test_flash_pipeline_rejects_file_path():
    errs = []
    pipe = SternFlashImagePipeline(
        "C:/images/game.img", "C:/images/game.img",
        log_cb=lambda *a, **k: None, phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None,
        done_cb=lambda ok, msg: errs.append((ok, msg)))
    pipe.run()
    assert errs and errs[0][0] is False
    assert "physical drive" in errs[0][1].lower()


def test_flash_pipeline_rejects_missing_image(monkeypatch):
    import pinball_decryptor.plugins.stern.pipeline as pl
    monkeypatch.setattr(pl, "is_device_path", lambda _p: True)
    errs = []
    pipe = SternFlashImagePipeline(
        "C:/does/not/exist.img", "\\\\.\\PHYSICALDRIVE9",
        log_cb=lambda *a, **k: None, phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None,
        done_cb=lambda ok, msg: errs.append((ok, msg)))
    pipe.run()
    assert errs and errs[0][0] is False
    assert "not found" in errs[0][1].lower()


def test_flash_pipeline_success_against_backing_file(tmp_path, monkeypatch):
    """End-to-end: treat a writable file as the 'device' and confirm the
    pipeline drives Check/Write/Flush to a successful done with the image
    bytes landed."""
    import pinball_decryptor.plugins.stern.pipeline as pl
    # Let the pipeline accept our regular file as a device path.
    monkeypatch.setattr(pl, "is_device_path", lambda _p: True)

    img_bytes = _pattern(6000)
    img = tmp_path / "ok.img"
    img.write_bytes(img_bytes)
    card = tmp_path / "card.dev"
    card.write_bytes(b"\xFF" * 32768)

    phases, results = [], []
    pipe = SternFlashImagePipeline(
        str(img), str(card),
        log_cb=lambda *a, **k: None,
        phase_cb=lambda i: phases.append(i),
        progress_cb=lambda *a, **k: None,
        done_cb=lambda ok, msg: results.append((ok, msg)))
    pipe.run()

    assert results and results[0][0] is True
    assert "Flashed" in results[0][1]
    assert phases == [0, 1, 2]                       # Check / Write / Flush
    assert card.read_bytes()[:6000] == img_bytes


def test_flash_pipeline_size_guard_surfaces_as_pipeline_error(tmp_path,
                                                              monkeypatch):
    import pinball_decryptor.plugins.stern.pipeline as pl
    monkeypatch.setattr(pl, "is_device_path", lambda _p: True)
    img = tmp_path / "big.img"
    img.write_bytes(b"\x01" * 40000)
    card = tmp_path / "small.dev"
    card.write_bytes(b"\x00" * 8192)
    errs = []
    pipe = SternFlashImagePipeline(
        str(img), str(card),
        log_cb=lambda *a, **k: None, phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None,
        done_cb=lambda ok, msg: errs.append((ok, msg)))
    pipe.run()
    assert errs and errs[0][0] is False
    assert "larger than the card" in errs[0][1]


# ---- capability / factory wiring -------------------------------------------

def test_flash_capability_and_factory_wired():
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    mfr = SternManufacturer()
    assert mfr.capabilities.flash_image is True
    assert mfr.flash_phases == ("Check card", "Write image", "Flush")
    noop = lambda *a, **k: None
    pipe = mfr.make_flash_pipeline(
        "game.img", "\\\\.\\PHYSICALDRIVE9", noop, noop, noop, noop)
    assert isinstance(pipe, SternFlashImagePipeline)
    assert pipe.image_path == "game.img"
    assert pipe.device_path == "\\\\.\\PHYSICALDRIVE9"


def test_flash_capability_off_for_whitestar_era():
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    mfr = SternManufacturer()
    mfr.set_era("whitestar")
    assert mfr.capabilities.flash_image is False
    mfr.set_era("spike2")
    assert mfr.capabilities.flash_image is True
