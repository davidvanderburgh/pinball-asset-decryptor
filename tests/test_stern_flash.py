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
card + a backup).
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


# ---- read-back verify ------------------------------------------------------

def test_flash_verifies_readback_and_catches_a_bad_write(tmp_path, monkeypatch):
    """A silently-corrupt flash (card doesn't match the image) must raise so it
    never reaches the machine -- the gap that let a bad CGC flash SHELL ERROR
    on the hardware.  Simulate it by having the read-back return wrong bytes."""
    img_bytes = _pattern(6000)
    img = tmp_path / "src.img"
    img.write_bytes(img_bytes)
    card = tmp_path / "card.dev"
    card.write_bytes(b"\x00" * 16384)

    # After the (faithful) write, corrupt one byte of what the read-back sees.
    real_read = RawDeviceFile._aligned_read

    def _corrupting_read(self, start, length):
        buf = bytearray(real_read(self, start, length))
        if start <= 3000 < start + len(buf):
            buf[3000 - start] ^= 0xFF
        return bytes(buf)
    monkeypatch.setattr(RawDeviceFile, "_aligned_read", _corrupting_read)

    with pytest.raises(FlashError, match="does not match the image"):
        rd.flash_image_to_device(str(img), str(card))


def test_flash_verify_passes_on_faithful_write(tmp_path):
    """A good write reads back byte-identical and completes without raising."""
    img_bytes = _pattern(6000)
    img = tmp_path / "src.img"
    img.write_bytes(img_bytes)
    card = tmp_path / "card.dev"
    card.write_bytes(b"\x00" * 16384)
    written = rd.flash_image_to_device(str(img), str(card))   # verify=True
    assert written == 6000
    assert card.read_bytes()[:6000] == img_bytes


def test_flash_verify_can_be_disabled(tmp_path, monkeypatch):
    """verify=False skips the read-back (kept for callers that verify
    separately) -- a corrupting read-back is then NOT caught."""
    img = tmp_path / "src.img"
    img.write_bytes(_pattern(6000))
    card = tmp_path / "card.dev"
    card.write_bytes(b"\x00" * 16384)
    monkeypatch.setattr(
        RawDeviceFile, "_aligned_read",
        lambda self, s, n: b"\x00" * n)   # would fail verify if it ran
    written = rd.flash_image_to_device(str(img), str(card), verify=False)
    assert written == 6000


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


# ---- macOS raw-disk handling ------------------------------------------------
# (Platform-gated code paths exercised by patching rd.sys.platform; the pure
# helpers run as-is.  Real /dev nodes are never touched.)

def test_rdisk_path_translation():
    assert rd._rdisk_path("/dev/disk9") == "/dev/rdisk9"
    assert rd._rdisk_path("/dev/disk9s1") == "/dev/rdisk9s1"
    assert rd._rdisk_path("/dev/rdisk9") == "/dev/rdisk9"    # already raw
    assert rd._rdisk_path("/dev/sdb") == "/dev/sdb"          # Linux untouched
    assert rd._rdisk_path("") == ""
    assert rd._rdisk_path(None) == ""


def test_fda_guidance_names_path_and_fix():
    msg = rd._fda_guidance("/dev/rdisk9")
    assert "/dev/rdisk9" in msg
    assert "Full Disk Access" in msg
    assert "Pinball Asset Decryptor" in msg
    assert "Cmd+Q" in msg                     # the quit-and-reopen step


def test_parse_diskutil_total_size():
    plist = (b'<?xml version="1.0" encoding="UTF-8"?>\n'
             b'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
             b'"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
             b'<plist version="1.0"><dict>'
             b'<key>DeviceIdentifier</key><string>disk9</string>'
             b'<key>TotalSize</key><integer>15931539456</integer>'
             b'</dict></plist>')
    assert rd._parse_diskutil_total_size(plist) == 15931539456
    assert rd._parse_diskutil_total_size(b"not a plist") is None
    assert rd._parse_diskutil_total_size(b"") is None
    # A plist without a size key (diskutil against a nonsense arg).
    empty = plist.replace(b"TotalSize", b"SomethingElse")
    assert rd._parse_diskutil_total_size(empty) is None


def test_open_backend_uses_rdisk_on_macos(monkeypatch):
    seen = {}

    class _FakeIO:
        def __init__(self, path, writable):
            seen["path"] = path
    monkeypatch.setattr(rd.sys, "platform", "darwin")
    monkeypatch.setattr(rd, "_FdIO", _FakeIO)
    rd._open_backend("/dev/disk9", True)
    assert seen["path"] == "/dev/rdisk9"
    # File paths (tests, card images) must not be rewritten.
    rd._open_backend("/tmp/card.img", True)
    assert seen["path"] == "/tmp/card.img"


def test_fdio_root_eperm_enriched_with_fda_guidance(monkeypatch):
    """A root EPERM on a mac disk node (TCC denial) must try authopen, then
    fail with the Full Disk Access recipe — not the bare 'Operation not
    permitted' flippermeister got."""
    real_open = rd.os.open

    def _deny(path, flags, *a, **k):
        if str(path).startswith("/dev/"):
            raise PermissionError(1, "Operation not permitted", path)
        return real_open(path, flags, *a, **k)
    monkeypatch.setattr(rd.sys, "platform", "darwin")
    monkeypatch.setattr(rd.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(rd.os, "open", _deny)
    authopen_calls = []

    def _no_authopen(path, flags):
        authopen_calls.append(path)
        return None
    monkeypatch.setattr(rd, "_authopen_fd", _no_authopen)
    with pytest.raises(PermissionError, match="Full Disk Access"):
        rd._FdIO("/dev/rdisk9", writable=True)
    assert authopen_calls == ["/dev/rdisk9"]


def test_fdio_adopts_authopen_fd(monkeypatch, tmp_path):
    """When authopen hands back an fd, _FdIO must use it transparently."""
    import os as _os
    backing = tmp_path / "disk"
    backing.write_bytes(b"\xEE" * 1024)
    real_open = rd.os.open

    def _deny(path, flags, *a, **k):
        if str(path).startswith("/dev/"):
            raise PermissionError(1, "Operation not permitted", path)
        return real_open(path, flags, *a, **k)
    monkeypatch.setattr(rd.sys, "platform", "darwin")
    monkeypatch.setattr(rd.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(rd.os, "open", _deny)
    monkeypatch.setattr(
        rd, "_authopen_fd",
        lambda p, f: real_open(str(backing), _os.O_RDONLY | rd._O_BINARY))
    io = rd._FdIO("/dev/rdisk9", writable=False)
    try:
        assert io.read(4) == b"\xEE" * 4
    finally:
        io.close()


def test_fdio_nonroot_eperm_stays_plain(monkeypatch):
    """Unprivileged EPERM means 'needs elevation', not TCC — no authopen, no
    FDA message (the GUI preflight must not pop password prompts)."""
    real_open = rd.os.open

    def _deny(path, flags, *a, **k):
        if str(path).startswith("/dev/"):
            raise PermissionError(1, "Operation not permitted", path)
        return real_open(path, flags, *a, **k)
    monkeypatch.setattr(rd.sys, "platform", "darwin")
    monkeypatch.setattr(rd.os, "geteuid", lambda: 501, raising=False)
    monkeypatch.setattr(rd.os, "open", _deny)

    def _boom(*a, **k):
        raise AssertionError("authopen must not run unprivileged")
    monkeypatch.setattr(rd, "_authopen_fd", _boom)
    with pytest.raises(PermissionError) as exc:
        rd._FdIO("/dev/rdisk9", writable=False)
    assert "Full Disk Access" not in str(exc.value)


def test_disk_offline_unmounts_on_macos(monkeypatch):
    calls = []

    class _R:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, **kw):
        calls.append(cmd)
        return _R()
    monkeypatch.setattr(rd.sys, "platform", "darwin")
    monkeypatch.setattr(rd.subprocess, "run", _fake_run)
    logs = []
    with rd._disk_offline_for_write(
            "/dev/disk9", log=lambda m, l="info": logs.append(m)):
        pass
    assert calls == [["diskutil", "unmountDisk", "/dev/disk9"]]
    assert any("Unmounting" in m for m in logs)
    # File paths must not shell out even on darwin.
    calls.clear()
    with rd._disk_offline_for_write("/tmp/card.img"):
        pass
    assert calls == []


def test_device_size_macos_falls_back_to_diskutil(monkeypatch):
    """With the raw open denied (unprivileged preflight / TCC), the capacity
    check must still work via diskutil info -plist."""
    real_open = rd.os.open

    def _deny(path, flags, *a, **k):
        if str(path).startswith("/dev/"):
            raise PermissionError(1, "Operation not permitted", path)
        return real_open(path, flags, *a, **k)
    monkeypatch.setattr(rd.sys, "platform", "darwin")
    monkeypatch.setattr(rd.os, "open", _deny)
    monkeypatch.setattr(rd, "_diskutil_total_size",
                        lambda p: 15931539456 if p == "/dev/disk9" else None)
    assert rd.device_size("/dev/disk9") == 15931539456


def test_flash_permission_error_becomes_flash_error(tmp_path, monkeypatch):
    """flash_image_to_device must convert a denied device open into a
    FlashError (clean dialog message), not leak a PermissionError that the
    helper renders as a traceback."""
    img = tmp_path / "i.img"
    img.write_bytes(_pattern(1024))

    def _deny(path, writable):
        raise PermissionError(1, "Operation not permitted", path)
    monkeypatch.setattr(rd, "_open_backend", _deny)
    with pytest.raises(FlashError, match="Operation not permitted"):
        rd.flash_image_to_device(str(img), str(tmp_path / "card.dev"))


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
    assert phases == [0, 1, 2, 3]             # Check / Write / Verify / Flush
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
    assert mfr.flash_phases == ("Check card", "Write image", "Verify card",
                                "Flush")
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
