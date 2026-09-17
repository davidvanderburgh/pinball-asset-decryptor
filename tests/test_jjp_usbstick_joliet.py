"""The JJP stick maker refuses an ISO Windows would copy under shortened names.

Windows' Mount-DiskImage reads an ISO's Joliet tree for long names; without
one it shows the plain ISO 9660 names (SDA3_EXT4_PTCL_IMG_GZ.AA), and the GNR
multi-boot stick copied from that view could not install (item 119,
2026-09-13).  Pure: tiny synthetic volume descriptor sets."""
import pytest

from pinball_decryptor.plugins.jjp import usbstick

SECTOR = 2048


def _iso(path, joliet):
    b = bytearray(SECTOR * 19)

    def vd(i, kind, esc=b""):
        o = i * SECTOR
        b[o] = kind
        b[o + 1:o + 6] = b"CD001"
        b[o + 6] = 1
        if esc:
            b[o + 88:o + 91] = esc
    vd(16, 1)
    if joliet:
        vd(17, 2, b"%/E")
        vd(18, 255)
    else:
        vd(17, 255)
    path.write_bytes(bytes(b))
    return str(path)


def test_joliet_is_read_off_the_descriptors(tmp_path):
    assert usbstick.iso_has_joliet(_iso(tmp_path / "a.iso", True)) is True
    assert usbstick.iso_has_joliet(_iso(tmp_path / "b.iso", False)) is False


def test_not_an_iso_is_unknown(tmp_path):
    junk = tmp_path / "junk.iso"
    junk.write_bytes(b"\0" * SECTOR * 18)
    assert usbstick.iso_has_joliet(str(junk)) is None
    assert usbstick.iso_has_joliet(str(tmp_path / "missing.iso")) is None


def _run(tmp_path, monkeypatch, joliet):
    monkeypatch.setattr(usbstick.sys, "platform", "win32")
    monkeypatch.setattr(usbstick, "is_device_path", lambda p: True)
    formatted = []

    def fmt(self):
        formatted.append(1)
        raise usbstick.PipelineError(usbstick.PHASES[1], "stop after the check")
    monkeypatch.setattr(usbstick.UsbStickPreparePipeline, "_format_stick", fmt)
    done = {}
    p = usbstick.UsbStickPreparePipeline(
        _iso(tmp_path / "x.iso", joliet), r"\\.\PHYSICALDRIVE9",
        lambda m, lvl="info": None, lambda i: None, lambda *a: None,
        lambda ok, msg="": done.update(ok=ok, msg=msg))
    p.run()
    return done, formatted


def test_an_iso_without_joliet_is_refused_before_the_stick_is_touched(tmp_path, monkeypatch):
    done, formatted = _run(tmp_path, monkeypatch, joliet=False)
    assert done["ok"] is False
    assert "Joliet" in done["msg"]
    # The way out is building the ISO again — that phase now passes xorriso
    # '-joliet on' (test_jjp_iso_joliet_build).  It used to send the user to
    # Rufus, whose stick stopped in GRUB on "'/live/vmlinuz' not found".
    assert "build yours again" in done["msg"]
    assert "Rufus" not in done["msg"]
    assert formatted == []


def test_an_iso_with_joliet_goes_on_to_the_format(tmp_path, monkeypatch):
    done, formatted = _run(tmp_path, monkeypatch, joliet=True)
    assert formatted == [1]
    assert done["msg"] == "stop after the check"
