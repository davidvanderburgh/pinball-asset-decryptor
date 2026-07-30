"""JJP USB install-stick prep — the format-and-copy "flash" surface.

A JJP machine can't read a raw-imaged (Etcher/dd) stick: it mounts the
stick's FAT volume at power-on and runs the installer from the files it
finds there (a tester's Sonic report — "Failed to mount USB stick").  These
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


def test_windows_format_script_survives_stale_disk_view():
    """New-Partition right after Clear-Disk sees the cmdlets' stale cached
    view of the disk and fails with "Not enough available capacity" (a tester's
    Sonic stick) — the script must re-sync and retry, and must surface the
    first real error alone instead of a null-parameter cascade."""
    script = usbstick._win_format_script(3)
    assert script.splitlines()[0] == "$ErrorActionPreference = 'Stop'"
    assert "Update-Disk" in script
    assert "Start-Sleep" in script
    # Initialize-Disk failures must be visible, not silenced.
    assert "SilentlyContinue" not in script
    # The boot/system-disk guard and the drive-letter handshake stay.
    assert "IsBoot" in script
    assert "'LETTER=' + $part.DriveLetter" in script
    # A partition that came up letterless still gets one assigned.
    assert "Add-PartitionAccessPath -AssignDriveLetter" in script
    assert "-DiskNumber 3" in script


def test_windows_diskpart_fallback_script():
    """When the storage cmdlets fail, the format is redone with diskpart —
    a different service (VDS) that does not share the Storage-WMI cache
    that kept saying "Not enough available capacity" through all six
    retries on a tester's stick.  Everything the wedged provider could lie
    about must come from elsewhere: size from Win32_DiskDrive, the drive
    letter from DriveInfo, assigned explicitly."""
    script = usbstick._win_diskpart_script(3)
    assert script.splitlines()[0] == "$ErrorActionPreference = 'Stop'"
    # The boot/system-disk safety net is re-checked, never bypassed.
    assert "IsBoot" in script
    assert usbstick._BOOT_DISK_REFUSAL in script
    assert "diskpart.exe /s" in script
    assert "select disk 3" in script
    assert "clean" in script
    assert "convert mbr noerr" in script
    assert "format fs=fat32 quick label=JJPUSB" in script
    assert "Win32_DiskDrive" in script
    assert "Index=3" in script
    assert "GetDrives" in script
    assert "assign letter=" in script
    assert "'LETTER=' + $letter" in script


def test_format_stick_windows_falls_back_to_diskpart(monkeypatch):
    """Cmdlet script fails -> the diskpart script runs and its LETTER=
    handshake is honoured; the log names both the error and diskpart."""
    calls = []

    def fake_ps_admin(script, timeout=300, log=None):
        calls.append(script)
        if len(calls) == 1:
            return 1, "New-Partition : Not enough available capacity"
        return 0, "LETTER=Z"

    monkeypatch.setattr(usbstick, "_ps_admin", fake_ps_admin)
    real_isdir = os.path.isdir
    monkeypatch.setattr(usbstick.os.path, "isdir",
                        lambda p: True if p == "Z:\\" else real_isdir(p))

    logs = []
    root = usbstick.format_stick_windows(
        r"\\.\PHYSICALDRIVE3", lambda text, level="info": logs.append(text))

    assert root == "Z:\\"
    assert len(calls) == 2
    assert "diskpart.exe" in calls[1]
    joined = "\n".join(logs)
    assert "Not enough available capacity" in joined
    assert "diskpart" in joined


@pytest.mark.parametrize("fatal", [
    "Refusing to format the boot/system disk.",
    "Administrator access was not granted.",
])
def test_format_stick_windows_fatal_errors_skip_diskpart(monkeypatch, fatal):
    """The safety refusal must stay fatal (a fallback must never bypass
    it) and a declined UAC prompt must not immediately prompt again."""
    calls = []

    def fake_ps_admin(script, timeout=300, log=None):
        calls.append(script)
        return 1, fatal

    monkeypatch.setattr(usbstick, "_ps_admin", fake_ps_admin)

    with pytest.raises(Exception) as exc:
        usbstick.format_stick_windows(r"\\.\PHYSICALDRIVE3", lambda *a: None)

    assert len(calls) == 1
    assert fatal in str(exc.value)


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
    assert jjp["target_kind"] == "usb_stick"
    assert "*.iso" in jjp["filetypes"][0][1]
    assert "format" in jjp["confirm_verb"]
    # "Target USB stick:" clips in the dialog's 12-char label column.
    assert jjp["target_label"] == "Target USB:"
    assert len(jjp["target_label"]) <= 12

    class _DdPlugin:  # a Stern/CGC-shaped plugin: no flash_* overrides
        direct_medium_noun = "SD card"
        direct_target_kind = "sd_card"

    dd = _flash_words(_DdPlugin())
    assert dd["noun"] == "SD card"
    assert dd["section"] == "Write an image onto the SD card"
    assert dd["action"] == "flash"
    assert dd["confirm_verb"] == "write the image onto it"
    assert "*.img" in dd["filetypes"][0][1]


# ---------------------------------------------------------------------------
# Drive picking — the format target must never default to an SSD/HDD
# ---------------------------------------------------------------------------

def _drive(model, gb, bus="USB", path=None):
    from pinball_decryptor.core.drives import PhysicalDrive
    return PhysicalDrive(
        device_path=path or r"\\.\PHYSICALDRIVE9",
        model=model, size_bytes=int(gb * 1e9), bus_type=bus)


def test_usb_stick_pick_prefers_stick_over_ssd():
    from pinball_decryptor.core.drives import pick_best_game_ssd

    stick = _drive("SanDisk Ultra USB Device", 32, path=r"\\.\PHYSICALDRIVE4")
    ssd = _drive("Samsung SSD 870 EVO 500GB", 500, path=r"\\.\PHYSICALDRIVE5")
    best, confidence, _reason = pick_best_game_ssd(
        [ssd, stick], prefer="usb_stick")
    assert best is stick
    assert confidence == "high"


def test_usb_stick_pick_refuses_obvious_disks():
    """Only SSDs/HDDs connected -> nothing is auto-selected, ever."""
    from pinball_decryptor.core.drives import pick_best_game_ssd

    game_ssd = _drive("WDC WDS240G2G0A SSD", 240,
                      path=r"\\.\PHYSICALDRIVE3")
    backup = _drive("Seagate Solid State Drive", 2000,
                    path=r"\\.\PHYSICALDRIVE6")
    nvme = _drive("Fast Thing 990", 1000, bus="NVMe",
                  path=r"\\.\PHYSICALDRIVE7")
    best, _confidence, reason = pick_best_game_ssd(
        [game_ssd, backup, nvme], prefer="usb_stick")
    assert best is None
    assert "nothing was auto-selected" in reason


def test_usb_stick_pick_never_guesses_a_big_external():
    """A big external with no SSD hint (backup HDD) is still not guessed —
    stick candidates must be stick-SIZED."""
    from pinball_decryptor.core.drives import pick_best_game_ssd

    big = _drive("Seagate Backup Plus", 4000, path=r"\\.\PHYSICALDRIVE8")
    best, _confidence, _reason = pick_best_game_ssd([big],
                                                    prefer="usb_stick")
    assert best is None


def test_usb_stick_visible_drives_hides_disks_but_never_empties():
    from pinball_decryptor.core.drives import visible_drives

    stick = _drive("SanDisk Ultra USB Device", 32,
                   path=r"\\.\PHYSICALDRIVE4")
    ssd = _drive("Samsung SSD 870 EVO 500GB", 500,
                 path=r"\\.\PHYSICALDRIVE5")
    assert visible_drives([stick, ssd], prefer="usb_stick") == [stick]
    # keep= wins over the filter (the auto-picked best must stay listed).
    assert ssd in visible_drives([stick, ssd], prefer="usb_stick",
                                 keep=[ssd])
    # Filtering must never leave the dropdown empty — a manual pick of an
    # unrecognised stick stays possible.
    assert visible_drives([ssd], prefer="usb_stick") == [ssd]


def test_linux_partition_node_naming():
    assert usbstick._linux_partition_node("/dev/sdb") == "/dev/sdb1"
    assert usbstick._linux_partition_node("/dev/nvme0n1") == "/dev/nvme0n1p1"
    assert usbstick._linux_partition_node("/dev/mmcblk0") == "/dev/mmcblk0p1"


def test_disk_number_parsing():
    assert usbstick._disk_number(r"\\.\PHYSICALDRIVE3") == 3
    with pytest.raises(Exception):
        usbstick._disk_number("/dev/sdb")
