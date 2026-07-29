"""JJP USB install-stick prep — the format-and-copy "flash" surface.

A JJP machine can't read a raw-imaged (Etcher/dd) stick: it mounts the
stick's FAT volume at power-on and runs the installer from the files it
finds there (Alex's Sonic report — "Failed to mount USB stick").  These
tests drive ``UsbStickPreparePipeline``'s Check/Copy/Verify core on plain
folders (a directory device_path/iso_path short-circuits the privileged
format/mount steps by design) plus the manufacturer/dialog wiring.  No
devices are touched and nothing is formatted.
"""

import os
import sys
import types

import pytest

from pinball_decryptor.plugins.jjp import usbstick
from pinball_decryptor.plugins.jjp.manufacturer import JJPManufacturer
from pinball_decryptor.plugins.jjp.usbstick import (PHASES,
                                                    UsbStickPreparePipeline)


class _Calls:
    def __init__(self):
        self.logs = []
        self.phases = []
        self.progress = []
        self.done = None

    def cbs(self):
        return (lambda text, level="info": self.logs.append((text, level)),
                lambda idx: self.phases.append(idx),
                lambda cur, total, desc="": self.progress.append(
                    (cur, total, desc)),
                lambda ok, summary: self._set_done(ok, summary))

    def _set_done(self, ok, summary):
        self.done = (ok, summary)


def _make_iso_tree(root):
    """A miniature Clonezilla-ish ISO content tree."""
    files = {
        "syslinux/syslinux.cfg": b"DEFAULT clonezilla\n",
        "home/partimag/sonic/sda3.ext4-ptcl-img.gz.aa": b"\x1f\x8b" * 600,
        "home/partimag/sonic/sda3.ext4-ptcl-img.gz.ab": b"\x1f\x8b" * 300,
        "Clonezilla-Live-Version": b"3.1\n",
    }
    for rel, data in files.items():
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    return files


def _run(iso, dev):
    calls = _Calls()
    p = UsbStickPreparePipeline(str(iso), str(dev), *calls.cbs())
    p.run()
    return p, calls


# ---------------------------------------------------------------------------
# Pipeline core (folder-mode: no devices, no privileges)
# ---------------------------------------------------------------------------

def test_prepare_happy_path_copies_and_verifies(tmp_path):
    iso = tmp_path / "iso"
    dev = tmp_path / "stick"
    iso.mkdir(), dev.mkdir()
    files = _make_iso_tree(str(iso))

    _p, calls = _run(iso, dev)

    assert calls.done is not None and calls.done[0] is True
    # Every source file landed, byte-identical size, tree shape preserved.
    for rel, data in files.items():
        dst = os.path.join(str(dev), *rel.split("/"))
        assert os.path.isfile(dst), rel
        assert os.path.getsize(dst) == len(data), rel
    # All five phases ran, in order.
    assert calls.phases == list(range(len(PHASES)))
    # The summary tells the user the working install procedure.
    assert "installer starts by itself" in calls.done[1]
    # Folder mode says (in the log) that format/eject were skipped.
    joined = "\n".join(t for t, _lvl in calls.logs)
    assert "skipping the format" in joined
    assert "skipping the eject" in joined


def test_prepare_refuses_non_device_target(tmp_path):
    iso = tmp_path / "iso"
    iso.mkdir()
    _make_iso_tree(str(iso))

    _p, calls = _run(iso, tmp_path / "not-a-real-target.bin")

    assert calls.done is not None and calls.done[0] is False
    assert "physical drive" in calls.done[1]


def test_prepare_refuses_missing_iso(tmp_path):
    dev = tmp_path / "stick"
    dev.mkdir()

    _p, calls = _run(tmp_path / "nope.iso", dev)

    assert calls.done is not None and calls.done[0] is False
    assert "not found" in calls.done[1]


def test_prepare_refuses_stick_too_small(tmp_path, monkeypatch):
    iso = tmp_path / "iso"
    dev = tmp_path / "stick"
    iso.mkdir(), dev.mkdir()
    _make_iso_tree(str(iso))

    usage = types.SimpleNamespace(total=100, used=90, free=10)
    monkeypatch.setattr(usbstick.shutil, "disk_usage", lambda _p: usage)

    _p, calls = _run(iso, dev)

    assert calls.done is not None and calls.done[0] is False
    assert "too small" in calls.done[1]


def test_prepare_windows_fat32_cap_points_at_rufus(tmp_path, monkeypatch):
    iso = tmp_path / "iso"
    dev = tmp_path / "stick"
    iso.mkdir(), dev.mkdir()
    _make_iso_tree(str(iso))

    # Pretend the platform is Windows and the FAT32 ceiling is tiny, so the
    # miniature tree "exceeds" it — the refusal must name Rufus (which can
    # format large FAT32 where Windows itself can't).
    monkeypatch.setattr(usbstick, "sys",
                        types.SimpleNamespace(platform="win32"))
    monkeypatch.setattr(usbstick, "_WIN_FAT32_USABLE", 16)

    _p, calls = _run(iso, dev)

    assert calls.done is not None and calls.done[0] is False
    assert "Rufus" in calls.done[1]


def test_prepare_cancel_mid_copy_fails_loud(tmp_path):
    iso = tmp_path / "iso"
    dev = tmp_path / "stick"
    iso.mkdir(), dev.mkdir()
    _make_iso_tree(str(iso))

    calls = _Calls()
    log_cb, phase_cb, progress_cb, done_cb = calls.cbs()
    p = UsbStickPreparePipeline(str(iso), str(dev), log_cb, phase_cb,
                                lambda *a: (progress_cb(*a), p.cancel()),
                                done_cb)
    p.run()

    assert calls.done is not None and calls.done[0] is False
    assert "cancel" in calls.done[1].lower()


def test_prepare_verify_catches_corrupt_copy(tmp_path):
    iso = tmp_path / "iso"
    dev = tmp_path / "stick"
    iso.mkdir(), dev.mkdir()
    _make_iso_tree(str(iso))

    class _Corrupting(UsbStickPreparePipeline):
        def _set_phase(self, index):
            super()._set_phase(index)
            if PHASES[index] == "Verify":
                victim = os.path.join(
                    str(dev), "home", "partimag", "sonic",
                    "sda3.ext4-ptcl-img.gz.aa")
                with open(victim, "wb") as f:
                    f.write(b"short")

    calls = _Calls()
    p = _Corrupting(str(iso), str(dev), *calls.cbs())
    p.run()

    assert calls.done is not None and calls.done[0] is False
    assert "did not verify" in calls.done[1]
    assert "size mismatch" in calls.done[1]


# ---------------------------------------------------------------------------
# Manufacturer + dialog wiring
# ---------------------------------------------------------------------------

def test_jjp_manufacturer_wires_the_stick_pipeline():
    mfr = JJPManufacturer()
    assert mfr.capabilities.flash_image is True
    assert mfr.flash_phases == PHASES
    p = mfr.make_flash_pipeline(
        "x.iso", r"\\.\PHYSICALDRIVE9",
        lambda *a: None, lambda *a: None, lambda *a: None, lambda *a: None)
    assert isinstance(p, UsbStickPreparePipeline)
    # The Build path pins .iso so the dialog's Build-to box can't produce
    # an extensionless or mis-suffixed file.
    assert mfr.write_output_ext() == ".iso"
    assert mfr.force_write_ext("mymod").endswith(".iso")


def test_flash_words_jjp_vs_default():
    """JJP relabels the shared flash surface; Stern/CGC keep the dd text."""
    from pinball_decryptor.gui.flash_dialog import _flash_words

    jjp = _flash_words(JJPManufacturer())
    assert jjp["noun"] == "USB stick"
    assert jjp["target_kind"] == "sd_card"
    assert "*.iso" in jjp["filetypes"][0][1]
    assert "format" in jjp["confirm_verb"]

    class _DdPlugin:  # a Stern/CGC-shaped plugin: no flash_* overrides
        direct_medium_noun = "SD card"
        direct_target_kind = "sd_card"

    dd = _flash_words(_DdPlugin())
    assert dd["noun"] == "SD card"
    assert dd["section"] == "Write an image onto the SD card"
    assert dd["action"] == "flash"
    assert dd["confirm_verb"] == "write the image onto it"
    assert "*.img" in dd["filetypes"][0][1]


def test_linux_partition_node_naming():
    assert usbstick._linux_partition_node("/dev/sdb") == "/dev/sdb1"
    assert usbstick._linux_partition_node("/dev/nvme0n1") == "/dev/nvme0n1p1"
    assert usbstick._linux_partition_node("/dev/mmcblk0") == "/dev/mmcblk0p1"


def test_disk_number_parsing():
    assert usbstick._disk_number(r"\\.\PHYSICALDRIVE3") == 3
    with pytest.raises(Exception):
        usbstick._disk_number("/dev/sdb")
