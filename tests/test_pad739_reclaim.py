"""Reclaim space to Windows no longer loses its disk to the app's own WSL calls (PAD-739).

A user who had deleted 150 GB of cached cards ran Reclaim as Administrator and got diskpart's "The process cannot
access the file because it is being used by another process". Reclaim ran `wsl --shutdown` and went straight to
diskpart; meanwhile the open app's own wsl.exe calls (the Emulate tab's status, the rig pills, the clean-up's
checks) booted WSL again and the VM took the .vhdx back. Now WSL is held off for the whole compact, the disk file is
waited for until WSL has let go of it, and a compact that still finds it in use shuts WSL down and tries again
before saying what else to close.
"""
import os
import subprocess
import threading

import pytest

from pinball_decryptor.core import wsl_disk


class _FakePopen:
    """Stands in for subprocess.Popen: records what would have started."""
    started = []

    def __init__(self, args, *a, **kw):
        _FakePopen.started.append(list(args) if not isinstance(args, str) else [args])


@pytest.fixture
def fake_popen(monkeypatch):
    _FakePopen.started = []
    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    return _FakePopen


def _from_thread(fn):
    out = {}

    def run():
        try:
            out["value"] = fn()
        except Exception as e:                              # noqa: BLE001
            out["error"] = e
    t = threading.Thread(target=run)
    t.start()
    t.join(10)
    return out


def test_wsl_is_held_off_for_everyone_but_the_working_thread(fake_popen):
    assert not wsl_disk.wsl_is_paused()
    with wsl_disk.wsl_paused():
        assert wsl_disk.wsl_is_paused()
        # another thread - a status poll - may not start WSL again
        r = _from_thread(lambda: subprocess.Popen(["wsl.exe", "-d", "Ubuntu", "--", "true"]))
        assert isinstance(r.get("error"), OSError)
        r = _from_thread(lambda: subprocess.run(["C:\\Windows\\System32\\wsl.exe", "-l"]))
        assert isinstance(r.get("error"), OSError)
        # anything that is not wsl.exe still runs
        r = _from_thread(lambda: subprocess.Popen(["diskpart", "/s", "x.txt"]))
        assert "error" not in r
        # the working thread itself shuts WSL down
        subprocess.Popen(["wsl", "--shutdown"])
    assert fake_popen.started == [["diskpart", "/s", "x.txt"], ["wsl", "--shutdown"]]
    # afterwards everyone runs WSL again, and Popen is what it was
    assert subprocess.Popen is _FakePopen and not wsl_disk.wsl_is_paused()
    r = _from_thread(lambda: subprocess.Popen(["wsl.exe", "-l"]))
    assert "error" not in r and fake_popen.started[-1] == ["wsl.exe", "-l"]


def test_waits_for_wsl_to_let_go_and_asks_again(monkeypatch):
    shutdowns, t = [], [0.0]
    monkeypatch.setattr(wsl_disk, "_shutdown", lambda: shutdowns.append(t[0]))
    locked = iter([True] * 20 + [False])
    monkeypatch.setattr(wsl_disk, "_file_locked", lambda p: next(locked))
    said = []
    wsl_disk._shutdown_until_free("x.vhdx", said.append,
                                  sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0])
    assert shutdowns == [0.0, 15.0]                      # asked again after 15 s still held
    assert said[0] == "Shutting down WSL…" and "still holding" in said[1]


def test_a_disk_that_stays_held_says_what_to_close(monkeypatch):
    t = [0.0]
    monkeypatch.setattr(wsl_disk, "_shutdown", lambda: None)
    monkeypatch.setattr(wsl_disk, "_file_locked", lambda p: True)
    with pytest.raises(wsl_disk.WslDiskError) as e:
        wsl_disk._shutdown_until_free("x.vhdx", None, sleep=lambda s: t.__setitem__(0, t[0] + s),
                                      clock=lambda: t[0])
    assert "Docker Desktop" in str(e.value) and t[0] >= wsl_disk.RELEASE_WAIT_S


def _reclaim_rig(monkeypatch, tmp_path, diskpart_answers):
    vhdx = tmp_path / "ext4.vhdx"
    vhdx.write_bytes(b"x" * 1000)
    from pinball_decryptor.core import admin
    monkeypatch.setattr(wsl_disk, "is_supported", lambda: True)
    monkeypatch.setattr(admin, "is_admin", lambda: True)
    monkeypatch.setattr(wsl_disk, "_default_distro_vhdx", lambda: ("Ubuntu", str(vhdx)))
    monkeypatch.setattr(wsl_disk, "_trim", lambda: None)
    monkeypatch.setattr(wsl_disk, "_file_locked", lambda p: False)
    calls, polls = [], []
    answers = iter(diskpart_answers)

    def run(argv, **kw):
        calls.append(list(argv))
        if argv[:2] == ["wsl", "--shutdown"]:
            # the app's status poll fires right after the shutdown - and is held off
            polls.append(_from_thread(lambda: subprocess.Popen(["wsl.exe", "-e", "true"])))
            return subprocess.CompletedProcess(argv, 0, "", "")
        script = open(argv[2], encoding="ascii").read()
        if "compact vdisk" not in script:
            return subprocess.CompletedProcess(argv, 0, "", "")      # the detach between tries
        rc, out = next(answers)
        if rc == 0:
            vhdx.write_bytes(b"x" * 100)
        return subprocess.CompletedProcess(argv, rc, out, "")
    monkeypatch.setattr(subprocess, "run", run)
    return calls, polls


IN_USE = ("DiskPart successfully selected the virtual disk file.\n\nDiskPart has encountered an error: The process "
          "cannot access the file because it is being used by another process.")


def test_reclaim_retries_a_disk_wsl_took_back(monkeypatch, tmp_path):
    calls, polls = _reclaim_rig(monkeypatch, tmp_path, [(1, IN_USE), (0, "compacted")])
    said = []
    assert wsl_disk.reclaim(progress=said.append) == 900
    shut = [c for c in calls if c[:2] == ["wsl", "--shutdown"]]
    parts = [c for c in calls if c[0] == "diskpart"]
    assert len(shut) == 2 and len(parts) == 3             # compact, detach, compact again
    assert polls and all(isinstance(p.get("error"), OSError) for p in polls)
    assert said[0] == "Trimming the Linux filesystem…"
    assert not wsl_disk.wsl_is_paused()


def test_reclaim_gives_up_with_what_to_close(monkeypatch, tmp_path):
    _reclaim_rig(monkeypatch, tmp_path, [(1, IN_USE)] * 3)
    with pytest.raises(wsl_disk.WslDiskError) as e:
        wsl_disk.reclaim()
    msg = str(e.value)
    assert msg.startswith("WSL kept its virtual disk open") and "used by another process" in msg
    assert not wsl_disk.wsl_is_paused()


def test_reclaim_reports_any_other_diskpart_error_at_once(monkeypatch, tmp_path):
    calls, _ = _reclaim_rig(monkeypatch, tmp_path, [(1, "Virtual Disk Service error: access denied")])
    with pytest.raises(wsl_disk.WslDiskError) as e:
        wsl_disk.reclaim()
    assert str(e.value) == "diskpart could not compact the disk:\nVirtual Disk Service error: access denied"
    assert len([c for c in calls if c[0] == "diskpart"]) == 1


@pytest.mark.skipif(os.name != "nt", reason="the lock probe is Windows'")
def test_lock_probe_reads_a_free_file_as_free(tmp_path):
    f = tmp_path / "free.bin"
    f.write_bytes(b"1")
    assert wsl_disk._file_locked(str(f)) is False
    with open(f, "rb"):
        # Python opens with sharing allowed, but an exclusive open is still refused while it is open
        assert wsl_disk._file_locked(str(f)) is True
