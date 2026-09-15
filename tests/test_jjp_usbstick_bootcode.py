"""The JJP install stick's legacy-BIOS boot code (plugins/jjp/usbstick.py).

A JJP machine boots the stick.  A FAT copy of the ISO's files starts only in
UEFI mode; the GNR multi-boot stick stopped on "Reboot and Select proper Boot
device" on a machine that boots USB in legacy mode (item 119, 2026-09-13).  The
stick maker now runs the ISO's own utils/win64/syslinux64.exe, as Clonezilla's
makeboot64.bat does, and checks the loader and the active flag afterwards."""
import os

import pytest

from pinball_decryptor.core.pipeline_base import PipelineError
from pinball_decryptor.plugins.jjp import usbstick


def _stick(tmp_path, tool=True, loader=True):
    root = tmp_path / "stick"
    (root / "UTILS" / "WIN64").mkdir(parents=True)
    (root / "syslinux").mkdir()
    if tool:
        (root / "UTILS" / "WIN64" / "SYSLINUX64.EXE").write_bytes(b"MZ")
    if loader:
        (root / "syslinux" / "ldlinux.sys").write_bytes(b"\0" * 16)
    return str(root)


def test_the_command_is_clonezillas_own():
    s = usbstick._win_syslinux_script(r"F:\UTILS\WIN64\SYSLINUX64.EXE", "F")
    assert r"-FilePath 'F:\UTILS\WIN64\SYSLINUX64.EXE'" in s
    assert "-ArgumentList '-d','syslinux','-mafi','F:'" in s
    assert "SYSLINUX_RC=" in s


def test_the_tool_is_found_whatever_the_case(tmp_path):
    root = _stick(tmp_path)
    got = usbstick._stick_path(root, "utils", "win64", "syslinux64.exe")
    assert got is not None and got.endswith("SYSLINUX64.EXE")


def test_boot_code_installed_and_checked(tmp_path, monkeypatch):
    root = _stick(tmp_path)
    asked, logs = [], []
    monkeypatch.setattr(usbstick, "_ps_admin",
                        lambda script, timeout=300, log=None, why="":
                        (asked.append((script, why)), (0, "SYSLINUX_RC=0"))[1])
    monkeypatch.setattr(usbstick, "_ps", lambda script, timeout=180: (0, "True"))
    # a mount root with its trailing separator, as Windows hands it over (E:\)
    assert usbstick.make_bootable_windows(root + os.sep, r"\\.\PHYSICALDRIVE5",
                                          lambda m, lvl="info": logs.append(m)) is True
    assert len(asked) == 1 and "boot code" in asked[0][1]
    assert any("Boot code installed" in m for m in logs)


def test_no_tool_on_the_iso_says_uefi_only_and_asks_nothing(tmp_path, monkeypatch):
    root = _stick(tmp_path, tool=False)
    monkeypatch.setattr(usbstick, "_ps_admin",
                        lambda *a, **k: pytest.fail("no admin step without the tool"))
    logs = []
    assert usbstick.make_bootable_windows(root, r"\\.\PHYSICALDRIVE5",
                                          lambda m, lvl="info": logs.append(m)) is False
    assert "legacy BIOS" in logs[0] and "Rufus" in logs[0]


@pytest.mark.parametrize("admin, active, loader", [
    ((0, "SYSLINUX_RC=1"), "True", True),        # the tool failed
    ((0, "SYSLINUX_RC=0"), "False", True),       # partition not active
    ((0, "SYSLINUX_RC=0"), "True", False),       # no loader written
    ((1, "Administrator access was not granted."), "False", False),
])
def test_a_stick_without_its_boot_code_is_an_error(tmp_path, monkeypatch, admin, active, loader):
    root = _stick(tmp_path, loader=loader)
    monkeypatch.setattr(usbstick, "_ps_admin", lambda *a, **k: admin)
    monkeypatch.setattr(usbstick, "_ps", lambda script, timeout=180: (0, active))
    with pytest.raises(PipelineError) as e:
        usbstick.make_bootable_windows(root, r"\\.\PHYSICALDRIVE5", lambda m, lvl="info": None)
    assert "Reboot and Select proper Boot device" in e.value.message


def test_a_folder_target_skips_the_boot_code(tmp_path, monkeypatch):
    """Test mode (a directory device) never reaches the boot-code step."""
    iso = tmp_path / "iso"
    (iso / "live").mkdir(parents=True)
    (iso / "live" / "vmlinuz").write_bytes(b"k" * 100)
    dev = tmp_path / "dev"
    dev.mkdir()
    monkeypatch.setattr(usbstick.UsbStickPreparePipeline, "_make_bootable",
                        lambda self, root: pytest.fail("boot code in test mode"))
    logs, done = [], {}
    p = usbstick.UsbStickPreparePipeline(
        str(iso), str(dev), lambda m, lvl="info": logs.append(m),
        lambda i: None, lambda *a: None, lambda ok, msg="": done.update(ok=ok, msg=msg))
    p.run()
    assert done.get("ok") is True, done
    assert any("skipping the boot code" in m for m in logs)
    assert os.path.isfile(dev / "live" / "vmlinuz")
