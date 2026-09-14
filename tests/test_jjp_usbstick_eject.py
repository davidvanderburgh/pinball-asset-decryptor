"""The JJP stick maker's eject on Windows (plugins/jjp/usbstick.py).

Shell.Application's Eject verb is asynchronous, and the PowerShell that asked
for it used to exit at once - the GNR multi-boot stick stayed mounted after
the pipeline logged that it was ejecting (item 119, 2026-09-13).  The script
now waits for the drive letter to go and reports which way it went."""
from pinball_decryptor.plugins.jjp import usbstick


def test_the_eject_flushes_asks_and_waits_for_the_drive_to_go():
    s = usbstick._win_eject_script("F")
    assert "Write-VolumeCache -DriveLetter F" in s
    assert "InvokeVerb('Eject')" in s
    assert s.index("InvokeVerb") < s.index("Test-Path 'F:\\'")
    assert "EJECTED=1" in s and "EJECTED=0" in s


def test_a_stick_that_stays_mounted_is_said(monkeypatch):
    logs = []
    monkeypatch.setattr(usbstick, "_ps", lambda script, timeout=180: (0, "EJECTED=0"))
    usbstick.eject_stick_windows("F:\\", r"\\.\PHYSICALDRIVE5",
                                 lambda msg, level="info": logs.append(msg))
    assert len(logs) == 1
    assert "still mounted as F:" in logs[0] and "Safely Remove Hardware" in logs[0]


def test_an_ejected_stick_says_nothing(monkeypatch):
    logs = []
    monkeypatch.setattr(usbstick, "_ps", lambda script, timeout=180: (0, "EJECTED=1"))
    usbstick.eject_stick_windows("F:\\", r"\\.\PHYSICALDRIVE5",
                                 lambda msg, level="info": logs.append(msg))
    assert logs == []
