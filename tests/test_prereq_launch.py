"""Install Missing on Windows: the elevated installer is started directly and
a window that never starts the script is reported (PAD-327)."""

import os
import queue
import sys
import types

import pytest

from pinball_decryptor import app as app_module
from pinball_decryptor.core import prereq_launch
from pinball_decryptor.core.messages import LogMsg, UiCallMsg


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_installer_args_pass_the_marker():
    args = prereq_launch.installer_args(r"C:\x y\install_prerequisites.ps1",
                                        r"C:\t\m.txt")
    assert args == ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    r"C:\x y\install_prerequisites.ps1",
                    "-StartedMarker", r"C:\t\m.txt"]
    assert "-StartedMarker" not in prereq_launch.installer_args("s.ps1", "")


def test_watch_reports_a_window_that_never_starts(tmp_path):
    clock = _Clock()
    assert prereq_launch.watch_started(
        str(tmp_path / "m"), lambda: True, grace_s=45,
        clock=clock, sleep=clock.sleep) is True
    assert clock.t >= 45


def test_watch_quiet_once_the_script_started(tmp_path):
    marker = tmp_path / "m"
    clock = _Clock()

    def sleep(s):
        clock.sleep(s)
        if clock.t >= 3:
            marker.write_text("123")

    assert prereq_launch.watch_started(
        str(marker), lambda: True, grace_s=45,
        clock=clock, sleep=sleep) is False
    assert clock.t < 45


def test_watch_quiet_when_the_window_is_closed(tmp_path):
    clock = _Clock()
    assert prereq_launch.watch_started(
        str(tmp_path / "m"), lambda: clock.t < 5, grace_s=45,
        clock=clock, sleep=clock.sleep) is False


def test_new_marker_path_does_not_exist_yet():
    import os
    path = prereq_launch.new_marker_path()
    assert not os.path.exists(path)


class _FakeConsole:
    def __init__(self, error=0, declined=False):
        self.error = error
        self.declined = declined
        self.closed = False
        self.args = None

    def running(self):
        return True

    def close(self):
        self.closed = True


# The install folder, spelled with this OS's separator: the app takes its
# dirname, and a backslash is no separator off Windows.
PAD_DIR = os.path.join("C:" + os.sep, "Program Files", "PAD")


def _run(monkeypatch, console, stuck):
    fake = types.SimpleNamespace(msg_queue=queue.Queue())
    made = {}

    def make(args, cwd=None):
        if isinstance(console, Exception):
            raise console
        console.args = args
        made["cwd"] = cwd
        return console

    popen = []
    monkeypatch.setattr(prereq_launch, "ElevatedConsole", make)
    monkeypatch.setattr(prereq_launch, "watch_started",
                        lambda marker, running: stuck)
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda argv: popen.append(argv))
    app_module.App._run_install_prereqs_win(
        fake, os.path.join(PAD_DIR, "install_prerequisites.ps1"))
    msgs = []
    while not fake.msg_queue.empty():
        msgs.append(fake.msg_queue.get_nowait())
    return msgs, popen, made


def test_stuck_window_gets_a_box(monkeypatch):
    console = _FakeConsole()
    msgs, popen, made = _run(monkeypatch, console, stuck=True)
    assert not popen
    assert console.closed
    assert "-StartedMarker" in console.args
    assert made["cwd"] == PAD_DIR
    assert any(isinstance(m, LogMsg) for m in msgs)
    assert any(isinstance(m, UiCallMsg) for m in msgs)


def test_started_installer_says_nothing(monkeypatch):
    msgs, popen, _ = _run(monkeypatch, _FakeConsole(), stuck=False)
    assert msgs == [] and popen == []


def test_declined_uac_says_nothing(monkeypatch):
    msgs, popen, _ = _run(monkeypatch, _FakeConsole(1223, declined=True),
                          stuck=True)
    assert msgs == [] and popen == []


@pytest.mark.parametrize("console", [_FakeConsole(error=2),
                                     OSError("no shell32")])
def test_shellexecute_failure_falls_back_to_the_old_launch(monkeypatch,
                                                           console):
    msgs, popen, _ = _run(monkeypatch, console, stuck=True)
    assert msgs == []
    assert len(popen) == 1
    assert "Start-Process powershell -Verb RunAs" in popen[0][-1]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows installer")
def test_script_writes_the_marker_before_the_admin_check(tmp_path):
    """Non-elevated, the script stops at its admin check - after the marker."""
    import ctypes
    import subprocess
    if ctypes.windll.shell32.IsUserAnAdmin():
        pytest.skip("elevated (CI runners are): the script would go on "
                    "to its menu")
    from pathlib import Path
    from pinball_decryptor.core.elevated_flash import _winq
    script = (Path(__file__).resolve().parents[1]
              / "installer" / "install_prerequisites.ps1")
    marker = tmp_path / "started.txt"
    line = "powershell.exe " + " ".join(
        _winq(a) for a in prereq_launch.installer_args(str(script),
                                                       str(marker)))
    subprocess.run(line, stdin=subprocess.DEVNULL, capture_output=True,
                   timeout=120)
    assert marker.is_file()
