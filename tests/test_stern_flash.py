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

import json
import os
import struct

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


# ---- auto-eject after a verified flash (flippermeister feedback) ------------

def test_eject_is_noop_on_file_path(tmp_path, monkeypatch):
    # A backing file isn't a device -> no eject subprocess is spawned, no crash.
    ran = []
    monkeypatch.setattr(rd.subprocess, "run",
                        lambda *a, **k: ran.append(a))
    rd._eject_device(str(tmp_path / "card.dev"))
    assert ran == []


def test_eject_best_effort_never_raises(monkeypatch):
    # On a real device path a failing eject is logged, not raised (the flash has
    # already completed + verified, so the card is safe regardless).
    monkeypatch.setattr(rd, "is_device_path", lambda p: True)
    monkeypatch.setattr(rd, "_physicaldrive_number", lambda p: 9)

    def _boom(*a, **k):
        raise OSError("no eject here")
    monkeypatch.setattr(rd.subprocess, "run", _boom)
    logs = []
    rd._eject_device("/dev/disk9", log=lambda t, l="info": logs.append((l, t)))
    assert logs and any("eject" in t.lower() for _, t in logs)


def test_flash_auto_ejects_by_default(tmp_path, monkeypatch):
    img = tmp_path / "src.img"; img.write_bytes(_pattern(3000))
    card = tmp_path / "card.dev"; card.write_bytes(b"\x00" * 8192)
    ejected = []
    monkeypatch.setattr(rd, "_eject_device",
                        lambda dp, log=None: ejected.append(dp))
    rd.flash_image_to_device(str(img), str(card))          # eject defaults True
    assert ejected == [str(card)]                          # ejected after verify


def test_flash_eject_can_be_disabled(tmp_path, monkeypatch):
    img = tmp_path / "src.img"; img.write_bytes(_pattern(3000))
    card = tmp_path / "card.dev"; card.write_bytes(b"\x00" * 8192)
    ejected = []
    monkeypatch.setattr(rd, "_eject_device",
                        lambda dp, log=None: ejected.append(dp))
    rd.flash_image_to_device(str(img), str(card), eject=False)
    assert ejected == []


# ---- what a flash tells you while it runs -------------------------------------------
def test_the_flash_says_how_fast_it_is_going_and_how_long_is_left():
    """A flash is an elapsed clock and a crawling bar without this, and
    finding out at minute forty that the CARD is the bottleneck is finding
    out too late (David, on a 14.72 GB card image: "writing to my sd card is
    pretty slow... is there anything we can do in software to speed it up?
    or do i just need to get a faster sd card?" - it was 6 MB/s)."""
    total = 14_723_055_616
    hist = []
    # one sample is not a rate
    assert rd._rate_note(hist, 0, total, now=0.0) == ""
    assert rd._rate_note(hist, 60_000_000, total, now=10.0) == \
        " - 6.0 MB/s, about 41 minutes left"
    # THE RECENT RATE, not the average since the start: a card that takes its
    # first gigabyte at SLC speed and then falls off must not go on quoting
    # the number nobody will live with
    fast = [(0.0, 0), (10.0, 900_000_000)]
    assert rd._rate_note(fast, 960_000_000, total, now=11.0) == \
        " - 87.3 MB/s, about 3 minutes left"
    slow = fast + [(41.0, 1_000_000_000)]
    note = rd._rate_note(slow, 1_006_000_000, total, now=42.0)
    assert note.startswith(" - 6.0 MB/s")          # the old samples aged out
    assert "about" in note


def test_the_time_left_is_coarse_or_silent():
    assert rd._time_left(None) == "" and rd._time_left(-1) == ""
    assert rd._time_left(10 ** 6) == ""            # not an estimate any more
    assert rd._time_left(30) == "less than a minute left"
    assert rd._time_left(60) == "about 1 minute left"
    assert rd._time_left(90) == "about 2 minutes left"
    assert rd._time_left(3600) == "about 1 hour left"
    assert rd._time_left(2 * 3600 + 300) == "about 2h 5m left"


def test_the_write_and_the_read_back_both_carry_the_rate(tmp_path):
    """Both halves of a flash are long, and the verify is the half nobody
    expects - so it says the same thing."""
    img = tmp_path / "card.img"
    img.write_bytes(b"\xa5" * (1 << 20))
    dev = tmp_path / "dev.img"
    dev.write_bytes(b"\x00" * (1 << 20))
    seen = []
    rd.flash_image_to_device(
        str(img), str(dev), progress=lambda d, t, desc: seen.append(desc),
        verify=True)
    assert dev.read_bytes() == img.read_bytes()
    said = " ".join(seen)
    assert "Writing image to SD card" in said
    assert "Verifying flashed card" in said


# ---- the menu-only write ------------------------------------------------------------
_SEC = 512


def _entry(ptype, lba, count):
    return (b"\x00" + b"\x00\x00\x00" + bytes([ptype]) + b"\x00\x00\x00"
            + struct.pack("<II", lba, count))


def _ext_sb(marker):
    """A minimal ext4 superblock whose IDENTITY comes from *marker*, plus
    mutable fields set to something.  1024 bytes, to be laid at offset 1024
    of a partition - where a real one lives."""
    sb = bytearray(1024)
    struct.pack_into("<I", sb, 0x00, 419328)            # s_inodes_count
    struct.pack_into("<I", sb, 0x04, 1675263)           # s_blocks_count_lo
    struct.pack_into("<I", sb, 0x0C, 532955)            # s_free_blocks (moves)
    struct.pack_into("<I", sb, 0x14, 0)                 # s_first_data_block
    struct.pack_into("<I", sb, 0x18, 2)                 # s_log_block_size
    struct.pack_into("<I", sb, 0x2C, 1788276185)        # s_mtime (moves)
    struct.pack_into("<I", sb, 0x30, 1788276216)        # s_wtime (moves)
    struct.pack_into("<H", sb, 0x34, 2)                 # s_mnt_count (moves)
    sb[0x38:0x3A] = b"\x53\xef"                         # s_magic
    struct.pack_into("<H", sb, 0x3A, 1)                 # s_state (moves)
    struct.pack_into("<I", sb, 0x40, 1662358379)        # s_lastcheck (moves)
    sb[0x68:0x78] = (marker * 16)[:16]                  # s_uuid - the identity
    sb[0x78:0x88] = (marker * 16)[:16]                  # s_volume_name
    return bytes(sb)


def _fill(marker, size):
    """*marker*, repeated, EXACTLY *size* bytes long.  Slice-assigning a
    shorter bytes into a bytearray resizes it, which silently shifts every
    partition after it - the whole image comes out wrong and the failure
    looks like a bug in the code under test."""
    reps = size // len(marker) + 1
    return (marker * reps)[:size]


def _spike_image(path, disk_id, games=b"GAMES", extra=b"EXTRA", menu=b"MENU"):
    """A miniature Spike 2 card: p1 boot, p2 rootfs, p3 games, and an
    extended container holding p5 /data, p6 /dump and p7 the extra games
    tree - the shape every real card has, at 384 KB instead of 8 GB.

    Each partition is filled with its own marker so a test can see exactly
    which ones a write touched.
    """
    total = 768
    img = bytearray(total * _SEC)
    parts = [(0x0C, 64, 64, b"BOOT"), (0x83, 128, 128, menu),
             (0x83, 256, 128, games)]
    mbr = bytearray(_SEC)
    mbr[440:444] = struct.pack("<I", disk_id)
    for i, (ptype, lba, count, fill) in enumerate(parts):
        mbr[446 + i * 16:446 + (i + 1) * 16] = _entry(ptype, lba, count)
        img[lba * _SEC:(lba + count) * _SEC] = _fill(fill, count * _SEC)
        if ptype == 0x83:               # ...with a superblock where one lives
            img[lba * _SEC + 1024:lba * _SEC + 2048] = _ext_sb(fill)
    ext_lba, ext_count = 384, 384
    mbr[446 + 3 * 16:446 + 4 * 16] = _entry(0x0F, ext_lba, ext_count)
    mbr[510:512] = b"\x55\xaa"
    img[0:_SEC] = mbr
    logical = [(386, 100, b"DATA"), (514, 100, b"DUMP"), (642, 100, extra)]
    for n, (lba, count, fill) in enumerate(logical):
        ebr_lba = ext_lba + n * 128
        sb_at = lba
        ebr = bytearray(_SEC)
        ebr[446:462] = _entry(0x83, lba - ebr_lba, count)
        if n + 1 < len(logical):
            nxt = ext_lba + (n + 1) * 128
            ebr[462:478] = _entry(0x05, nxt - ext_lba, 128)
        ebr[510:512] = b"\x55\xaa"
        img[ebr_lba * _SEC:(ebr_lba + 1) * _SEC] = ebr
        img[lba * _SEC:(lba + count) * _SEC] = _fill(fill, count * _SEC)
        img[sb_at * _SEC + 1024:sb_at * _SEC + 2048] = _ext_sb(fill)
    with open(str(path), "wb") as f:
        f.write(img)
    return str(path)


def _at(path, lba, n=16):
    with open(path, "rb") as f:
        f.seek(lba * _SEC)
        return f.read(n)


def test_the_menu_plan_is_p2_and_a_proof_of_everything_else(tmp_path):
    img = _spike_image(tmp_path / "card.img", 0xA1B2C3D4)
    plan = rd.menu_write_plan(img)
    # ONE partition is written: the rootfs, where the selector and its media
    # and images.conf live
    assert plan["write"] == [(128 * _SEC, 128 * _SEC,
                              "the menu partition (p2)")]
    what = [w for _o, _l, w, _k in plan["prove"]]
    # a filesystem is proved by its IDENTITY, a table by its bytes
    assert dict((w, k) for _o, _l, w, k in plan["prove"])["the games on p3"] \
        == "ext"
    assert dict((w, k) for _o, _l, w, k in
                plan["prove"])["the card's partition table"] == "bytes"
    assert what[0] == "the card's partition table"
    # every games tree is identified, and so is the boot partition...
    # named for what they are to a person, not for a partition number
    assert "the games on p3" in what and "the games on p7" in what
    # ...the logical chain is walked...
    assert ["the card's p%d table entry" % n for n in (5, 6, 7)] == \
        [w for w in what if "table entry" in w]
    # ...and /data and /dump are DELIBERATELY not compared: the machine
    # writes them, so they differ on any card that has ever booted
    assert "the games on p5" not in what
    assert "the games on p6" not in what
    # ...and NOT p1, which is the trap: it is FAT, and FAT is rewritten by
    # being MOUNTED (the dirty flag, the FSInfo block), so it stops matching
    # the image the moment the machine reads the kernel out of it.  It
    # refused a card that WAS the right card.
    assert not [w for w in what if "p1" in w]
    # nothing outside the image is read
    assert all(o + l <= os.path.getsize(img)
               for o, l, _w, *_k in
               [p[:3] + ("",) for p in plan["prove"]] + plan["write"])


def test_a_menu_write_replaces_the_menu_and_nothing_else(tmp_path):
    img = _spike_image(tmp_path / "img.raw", 0xA1B2C3D4)
    card = tmp_path / "card.raw"
    card.write_bytes((tmp_path / "img.raw").read_bytes())
    # the machine has been playing: /data and /dump are its own now
    raw = bytearray(card.read_bytes())
    raw[386 * _SEC:386 * _SEC + 64] = b"HIGH SCORES AND SETTINGS".ljust(64)
    raw[514 * _SEC:514 * _SEC + 64] = b"LOGS".ljust(64)
    card.write_bytes(bytes(raw))
    # ...and the menu has been edited in the image
    raw = bytearray((tmp_path / "img.raw").read_bytes())
    raw[128 * _SEC:128 * _SEC + 64] = b"A DIFFERENT MENU".ljust(64)
    (tmp_path / "img.raw").write_bytes(bytes(raw))

    said = []
    n = rd.flash_menu_to_device(img, str(card),
                                log=lambda m, k="info": said.append(m))
    assert n == 128 * _SEC                      # p2 and only p2
    assert _at(str(card), 128, 16) == b"A DIFFERENT MENU"
    # the games are untouched, and so is the machine's own data
    assert _at(str(card), 256, 5) == b"GAMES"
    assert _at(str(card), 642, 5) == b"EXTRA"
    assert _at(str(card), 386, 24) == b"HIGH SCORES AND SETTINGS"
    assert _at(str(card), 514, 4) == b"LOGS"
    assert "verified" in " ".join(said).lower()


def test_a_menu_write_refuses_a_card_it_was_not_flashed_onto(tmp_path):
    img = _spike_image(tmp_path / "img.raw", 0xA1B2C3D4)
    # same shape, different games
    other = _spike_image(tmp_path / "other.raw", 0xA1B2C3D4, games=b"OTHER")
    before = open(other, "rb").read()
    with pytest.raises(rd.FlashError) as e:
        rd.flash_menu_to_device(img, other)
    assert "does not hold the images in" in str(e.value)
    assert "the games on p3" in str(e.value)
    assert "Nothing was written" in str(e.value)
    assert "Untick" in str(e.value)
    assert open(other, "rb").read() == before, "it refused BEFORE writing"
    # a different EXTRA image is caught too, and so is a different table
    other2 = _spike_image(tmp_path / "o2.raw", 0xA1B2C3D4, extra=b"OTHER")
    with pytest.raises(rd.FlashError) as e:
        rd.flash_menu_to_device(img, other2)
    assert "the games on p7" in str(e.value)
    other3 = _spike_image(tmp_path / "o3.raw", 0x99999999)
    with pytest.raises(rd.FlashError) as e:
        rd.flash_menu_to_device(img, other3)
    assert "the card's partition table" in str(e.value)


def test_a_menu_write_refuses_an_image_that_is_not_a_card(tmp_path):
    plain = tmp_path / "plain.raw"
    plain.write_bytes(b"\x00" * (64 * _SEC))
    with pytest.raises(rd.FlashError) as e:
        rd.menu_write_plan(str(plain))
    assert "partition table" in str(e.value)
    # ...and one whose second partition is not a Linux rootfs
    img = bytearray(_spike_image(tmp_path / "x.raw", 1) and
                    (tmp_path / "x.raw").read_bytes())
    img[446 + 16 + 4] = 0x0C                    # p2 as FAT
    (tmp_path / "x.raw").write_bytes(bytes(img))
    with pytest.raises(rd.FlashError) as e:
        rd.menu_write_plan(str(tmp_path / "x.raw"))
    assert "Linux rootfs" in str(e.value)


def test_the_pipeline_carries_menu_only_through(tmp_path, monkeypatch):
    import pinball_decryptor.plugins.stern.pipeline as pl
    monkeypatch.setattr(pl, "is_device_path", lambda _p: True)
    img = _spike_image(tmp_path / "img.raw", 0xA1B2C3D4)
    card = tmp_path / "card.raw"
    card.write_bytes((tmp_path / "img.raw").read_bytes())
    done = {}
    p = SternFlashImagePipeline(
        img, str(card), lambda *a: None, lambda *a: None, lambda *a: None,
        lambda ok, summary: done.update(ok=ok, summary=summary),
        menu_only=True)
    p.run()
    assert done["ok"] is True
    assert "boot menu" in done["summary"]
    assert "settings and scores were left alone" in done["summary"]
    # ...and without it the whole image goes
    p2 = SternFlashImagePipeline(
        img, str(card), lambda *a: None, lambda *a: None, lambda *a: None,
        lambda ok, summary: done.update(ok=ok, summary=summary))
    p2.run()
    assert done["ok"] is True and "Flashed" in done["summary"]


# ---- telling someone their card is the problem, while it still helps -----------------
def test_a_slow_card_is_named_with_numbers_and_what_to_buy():
    """"Your card is slow" is not an instruction.  The advice quotes what the
    wait IS and what it WOULD BE, and names cards and markings (David: "if
    their speed is <10MB/s for example, propose that they update to a better
    card with actual suggestions")."""
    note = rd.slow_card_advice(6.0e6, 14_723_055_616)
    assert "6.0 MB/s" in note
    assert "about 41 minutes for this write" in note   # what it costs now
    assert "against about 4 minutes" in note           # ...and what it need not
    # the marking to look for, and cards that carry it
    assert "A2" in note and "V30" in note
    for card in ("SanDisk Extreme", "Samsung PRO Plus", "Kingston Canvas Go",
                 "Lexar Professional"):
        assert card in note
    # the two things that are not the card
    assert "READER" in note and "CABLE" in note
    assert "fake cards" in note                        # the 6 MB/s classic
    # ...and the software answer, only where it applies
    assert "Only the boot menu" not in note
    assert "Only the boot menu" in rd.slow_card_advice(
        6.0e6, 14_723_055_616, menu_only=True)


def test_a_card_that_is_fast_enough_is_not_lectured():
    assert rd.slow_card_advice(rd.SLOW_CARD_MB_S * 1e6, 1 << 30) == ""
    assert rd.slow_card_advice(90e6, 1 << 30) == ""
    assert rd.slow_card_advice(0, 1 << 30) == ""
    assert rd.slow_card_advice(None, 1 << 30) == ""


def test_the_slow_card_note_waits_for_the_slc_burst_and_is_said_once():
    """A cheap card takes its first gigabyte at cache speed, so judging it
    inside that burst calls a good card slow - and judging it at the end is
    no use to anyone."""
    said = []
    clock = [1000.0]
    real = rd.time.monotonic
    rd.time.monotonic = lambda: clock[0]
    try:
        seen = []
        wrapped = rd._slow_card_watch(lambda t, k="info": said.append(t),
                                      lambda d, t, desc="": seen.append(d))
        total = 14_723_055_616
        wrapped(0, total)                       # the first sample only starts it
        assert said == []
        clock[0] += 10.0
        wrapped(60_000_000, total)              # 6 MB/s, but only 10 s in
        assert said == []
        clock[0] += 15.0
        wrapped(150_000_000, total)             # 25 s, but under 256 MB
        assert said == []
        clock[0] += 30.0
        wrapped(330_000_000, total)             # past both: now it says so
        assert len(said) == 1 and "MB/s" in said[0]
        clock[0] += 30.0
        wrapped(500_000_000, total)             # ...and only once
        assert len(said) == 1
        # the wrapped progress callback still did its own job throughout
        assert seen == [0, 60_000_000, 150_000_000, 330_000_000, 500_000_000]
    finally:
        rd.time.monotonic = real


def test_a_slow_flash_says_so_in_the_log(tmp_path, monkeypatch):
    """End to end: the note reaches the log the flash writes to."""
    monkeypatch.setattr(rd, "_FLASH_CHUNK", 64 << 10)
    monkeypatch.setattr(rd, "_SLOW_AFTER_BYTES", 4096)
    monkeypatch.setattr(rd, "_SLOW_AFTER_S", 0.0)
    monkeypatch.setattr(rd, "slow_card_advice",
                        lambda rate, total, menu_only=False:
                        "SLOW %.1f %s" % (rate / 1e6, menu_only))
    # A clock that MOVES between callbacks: a CI runner copies this whole
    # image inside one 15 ms Windows clock tick, and a zero-length span is
    # no rate (the watch waits for the next tick), so real time never let
    # the note fire there - the v0.184.1 tripwire.
    clock = [1000.0]

    def moving():
        clock[0] += 0.05
        return clock[0]
    monkeypatch.setattr(rd.time, "monotonic", moving)
    img = _spike_image(tmp_path / "img.raw", 0xA1B2C3D4)
    dev = tmp_path / "dev.raw"
    dev.write_bytes(b"\x00" * os.path.getsize(img))
    said = []
    rd.flash_image_to_device(img, str(dev), verify=False,
                             log=lambda t, k="info": said.append((k, t)))
    notes = [t for k, t in said if t.startswith("SLOW")]
    assert len(notes) == 1
    # ...and it knows this image has a menu partition, so it offers that too
    assert notes[0].endswith("True")


def test_the_check_ignores_everything_the_machine_writes(tmp_path):
    """A card that has BOOTED is still the card, and everything it did to
    itself on the way is not evidence about which games are on it.

    Each of these refused the right card in turn (David, twice: "why is the
    write failing? this is the exact raw image that I wrote onto the
    attached sd card", and then "still failed"):

      * p1 is FAT, and FAT is rewritten by being MOUNTED;
      * /data and /dump are what the machine writes for a living;
      * and the games partitions get e2fsck'd at EVERY boot - the fstab
        gives them ``pass 2`` - which rewrites the superblock's check time,
        state and mount count even though the mount itself is read-only.
    """
    img = _spike_image(tmp_path / "img.raw", 0xA1B2C3D4)
    card = tmp_path / "card.raw"
    card.write_bytes((tmp_path / "img.raw").read_bytes())
    raw = bytearray(card.read_bytes())
    # the machine mounted /mnt/boot: FAT's dirty flag and FSInfo moved
    raw[64 * _SEC + 0x25] = 0x01
    raw[65 * _SEC:65 * _SEC + 8] = b"FSINFOxx"
    # ...it has been played
    raw[386 * _SEC:386 * _SEC + 8] = b"SCORES!!"
    raw[514 * _SEC:514 * _SEC + 8] = b"LOGLINES"
    # ...and e2fsck has been over both games trees at boot: check time, state,
    # mount count and the free counts all move, the UUID does not
    for lba in (256, 642):
        sb = lba * _SEC + 1024
        struct.pack_into("<I", raw, sb + 0x40, 1799999999)   # s_lastcheck
        struct.pack_into("<H", raw, sb + 0x3A, 2)            # s_state
        struct.pack_into("<H", raw, sb + 0x34, 47)           # s_mnt_count
        struct.pack_into("<I", raw, sb + 0x2C, 1799999000)   # s_mtime
        struct.pack_into("<I", raw, sb + 0x30, 1799999001)   # s_wtime
        struct.pack_into("<I", raw, sb + 0x0C, 1)            # s_free_blocks
    card.write_bytes(bytes(raw))
    # ...and the menu still goes on, because none of that is a game
    n = rd.flash_menu_to_device(img, str(card), verify=True)
    assert n == 128 * _SEC
    assert _at(str(card), 386, 8) == b"SCORES!!", "and they are still there"
    assert _at(str(card), 514, 8) == b"LOGLINES"
    # ...and e2fsck's marks are still on the card: nothing put them back
    import struct as _s
    assert _s.unpack_from("<I", card.read_bytes(),
                          256 * _SEC + 1024 + 0x40)[0] == 1799999999
    # THE GAMES ARE STILL CHECKED, by the one thing that does not move: a
    # filesystem's UUID is set once, at mkfs, so two builds never share one
    other = _spike_image(tmp_path / "other.raw", 0xA1B2C3D4, games=b"OTHER")
    with pytest.raises(rd.FlashError) as e:
        rd.flash_menu_to_device(img, other)
    assert "the games on p3" in str(e.value)


def test_a_filesystem_is_identified_by_what_it_is_born_with(tmp_path):
    """The fields a filesystem never changes, against the ones it does."""
    born = rd._ext_identity(b"\x00" * 1024 + _ext_sb(b"A"))
    assert born is not None
    same = bytearray(b"\x00" * 1024 + _ext_sb(b"A"))
    for off, fmt, val in ((0x40, "<I", 1799999999),   # s_lastcheck
                          (0x3A, "<H", 2),            # s_state
                          (0x34, "<H", 47),           # s_mnt_count
                          (0x2C, "<I", 1799999000),   # s_mtime
                          (0x30, "<I", 1799999001),   # s_wtime
                          (0x0C, "<I", 1)):           # s_free_blocks_count
        struct.pack_into(fmt, same, 1024 + off, val)
    assert rd._ext_identity(bytes(same)) == born, "these all move on a card"
    # ...and the ones that do not
    other = b"\x00" * 1024 + _ext_sb(b"B")
    assert rd._ext_identity(other) != born
    # anything that is not a filesystem is not identified at all
    assert rd._ext_identity(b"\x00" * 2048) is None
    assert rd._ext_identity(b"short") is None


# ---- item 99: the menu's ranges off a card, into a sparse image, and back ---------------
def test_the_menu_read_takes_the_menu_ranges_and_nothing_else(tmp_path):
    """read_device_menu_to_image: the table, p1 and p2 whole, every EBR sector and the
    identity bytes of the games partitions - and NOT the games, /data or /dump; the image
    is the card's full size (sparse), and menu_write_plan proves it against the card."""
    card = _spike_image(tmp_path / "card.raw", 0x0BADCAFE)
    img = str(tmp_path / "menu.raw")
    got = []
    n = rd.read_device_menu_to_image(card, img, progress=lambda d, t, m: got.append((d, t)))
    assert os.path.getsize(img) == os.path.getsize(card)
    assert got and got[-1][0] == got[-1][1] == n
    # p1 + p2 whole (their ranges end where p2 ends), the MBR too
    assert _at(img, 0, 512) == _at(card, 0, 512)
    assert _at(img, 64, 512) == b"BOOT" * 128 and _at(img, 200, 512) == _at(card, 200, 512)
    # the games partitions: identity bytes only
    assert _at(img, 256, rd._IDENT_BYTES) == _at(card, 256, rd._IDENT_BYTES)
    assert _at(img, 256 + 16, 512) == bytes(512)
    assert _at(img, 642, rd._IDENT_BYTES) == _at(card, 642, rd._IDENT_BYTES)
    assert _at(img, 700, 512) == bytes(512)
    # /data and /dump not at all; every EBR sector yes
    assert _at(img, 386, 512) == bytes(512) and _at(img, 514, 512) == bytes(512)
    for ebr in (384, 512, 640):
        assert _at(img, ebr, 512) == _at(card, ebr, 512)
    assert n < os.path.getsize(card) // 2
    # ...and a menu-only write of the image is provable against the card it came off
    plan = rd.menu_write_plan(img)
    with rd.RawDeviceFile(card, writable=False) as dev, open(img, "rb") as src:
        ok, what = rd._ranges_match(dev, src, plan["prove"])
    assert ok, what


def test_the_menu_read_refuses_a_card_without_a_table(tmp_path):
    blank = tmp_path / "blank.raw"
    blank.write_bytes(bytes(1 << 20))
    with pytest.raises(rd.FlashError):
        rd.read_device_menu_to_image(str(blank), str(tmp_path / "out.raw"))
    assert not (tmp_path / "out.raw").exists() and not (tmp_path / "out.raw.part").exists()


def test_the_elevated_helper_reads_a_menu(tmp_path):
    """The helper's ``read_menu`` job mode, on plain files (no elevation needed)."""
    from pinball_decryptor.core import elevated_flash as ef
    card = _spike_image(tmp_path / "card.raw", 0x11223344)
    img = str(tmp_path / "menu.raw")
    ipc = tmp_path / "ipc"
    ipc.mkdir()
    (ipc / "job.json").write_text(json.dumps({"mode": "read_menu", "image": img, "device": card}))
    assert ef.run_helper_main(["--flash-helper", str(ipc)]) == 0
    result = json.loads((ipc / "result.json").read_text())
    assert result["ok"] is True and result["written"] > 0
    assert os.path.getsize(img) == os.path.getsize(card)
    # the unelevated entry point on a plain file runs in-process
    n = ef.read_device_menu_with_privileges(card, str(tmp_path / "menu2.raw"))
    assert n == result["written"]


def test_the_ipc_dir_is_granted_to_the_user_on_windows(tmp_path, monkeypatch):
    """The relay fix: the elevated child's files inherit an ACE for the user (they were
    Administrators-only, so nothing came back to an unelevated parent)."""
    from pinball_decryptor.core import elevated_flash as ef
    calls = []
    monkeypatch.setattr(ef.subprocess, "run", lambda argv, **kw: calls.append(argv))
    monkeypatch.setattr(ef.sys, "platform", "win32")
    monkeypatch.setenv("USERNAME", "david")
    monkeypatch.setenv("USERDOMAIN", "EAGLE")
    monkeypatch.setattr(ef.tempfile, "gettempdir", lambda: str(tmp_path))
    d = ef._ipc_dir("pad_test_")
    assert os.path.isdir(d) and d.startswith(str(tmp_path))
    assert calls and calls[0][:3] == ["icacls", d, "/grant"]
    assert calls[0][3] == "EAGLE\\david:(OI)(CI)F"
    monkeypatch.setattr(ef.sys, "platform", "linux")
    calls.clear()
    ef._ipc_dir("pad_test_")
    assert calls == []
