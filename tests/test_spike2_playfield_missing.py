"""PAD-629: "missing playfield" - a run with no playfield window and a log
that never said why.

Two halves. playfield.py's one-window guard raised ANY window carrying its
title instead of opening a new one, so a title copied by another program (or
left by a dead or hung run) meant no playfield at all; it now counts only a
visible, answering window owned by a Python process. And watch.sh asked
whether the window was up about a second after the launch, before a Windows
process started through interop had run its first line, so a window that quit
moments later passed the check; a watcher now waits for pfweb's "window up"
line or the process's end, and says which.
"""
import os
import re
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(HERE, "tools", "spike2_emu")
pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
if RIG not in sys.path:
    sys.path.insert(0, RIG)

win_only = pytest.mark.skipif(sys.platform != "win32", reason="Win32 windows")
needs_bash = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"),
                                reason="needs a POSIX bash")


@pytest.fixture()
def titled_window(monkeypatch):
    """A plain Win32 window of THIS (Python) process with the playfield's
    title, hidden; the test shows it when it wants a live one."""
    import ctypes
    from ctypes import wintypes
    import playfield
    title = "PAD-629 test - virtual playfield %d" % os.getpid()
    monkeypatch.setattr(playfield, "WINDOW_TITLE", title)
    u = ctypes.windll.user32
    u.CreateWindowExW.restype = wintypes.HWND
    u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR,
                                  wintypes.LPCWSTR, wintypes.DWORD,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                  wintypes.HINSTANCE, wintypes.LPVOID]
    u.DestroyWindow.argtypes = [wintypes.HWND]
    # WS_OVERLAPPEDWINDOW, far off every monitor
    h = u.CreateWindowExW(0, "STATIC", title, 0x00CF0000, -6000, 40, 200, 120,
                          None, None, None, None)
    assert h
    yield playfield, h
    u.DestroyWindow(h)


@win_only
def test_a_hidden_window_with_the_title_does_not_stop_the_playfield(titled_window):
    playfield, _h = titled_window
    assert playfield.raise_existing() is False


@win_only
def test_a_live_playfield_window_is_raised_and_brought_onto_a_screen(titled_window):
    import ctypes
    from ctypes import wintypes
    playfield, h = titled_window
    u = ctypes.windll.user32
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.ShowWindow(h, 4)                              # SW_SHOWNOACTIVATE
    # Answer like a live window: a thread that has not pumped its queue for
    # 5 s is "hung" to IsHungAppWindow, and pytest's thread never pumps, so
    # a slow (cold) run failed this test now and then (PAD-692).
    msg = wintypes.MSG()
    while u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):   # PM_REMOVE
        u.DispatchMessageW(ctypes.byref(msg))
    assert playfield._our_live_window(h)
    assert playfield.raise_existing() is True
    u.MonitorFromWindow.restype = wintypes.HANDLE
    u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    assert u.MonitorFromWindow(h, 0), "left off every monitor"


def _watcher():
    """watch.sh's after-launch playfield check, as it stands in the script."""
    with open(os.path.join(RIG, "watch.sh"), encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"^pf_said_why\(\) \{.*?^        PFWATCHPID=\$!\n    fi\nfi\n",
                  src, re.S | re.M)
    assert m, "the playfield watcher moved"
    return m.group(0)


def test_the_watcher_waits_for_the_window_up_line():
    w = _watcher()
    assert "pfweb: window up" in w
    with open(os.path.join(RIG, "pfweb.py"), encoding="utf-8") as f:
        assert 'print("pfweb: window up' in f.read()
    with open(os.path.join(RIG, "watch.sh"), encoding="utf-8") as f:
        assert 'kill "$PFWATCHPID"' in f.read()


def _run(tmp_path, scenario):
    """alive = the window process; scenario writes the log / ends it."""
    alive, log = tmp_path / "alive", tmp_path / "pf.log"
    alive.write_text("")
    log.write_text("")
    script = (
        'ALIVE=$1; PFLOG=$2; GUEST=$3; PF_PY=pythonw.exe; GAME=godzilla_le\n'
        'PF_LAUNCHED=1; PAD_PF_WAIT=4\n'
        'pf_up() { [ -e "$ALIVE" ]; }\n'
        'pad_guest_up() { [ "$GUEST" = 1 ]; }\n'
        + _watcher() + scenario + "\nwait\n")
    r = subprocess.run(["bash", "-c", script, "x", str(alive), str(log),
                        "0" if "GUEST=0" in scenario else "1"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


@needs_bash
def test_a_window_that_quits_after_the_first_check_is_reported(tmp_path):
    out = _run(tmp_path, 'sleep 1; echo "Traceback: no WebView2" >> "$PFLOG";'
                         ' rm -f "$ALIVE"')
    assert "started and stopped" in out
    assert "Traceback: no WebView2" in out


@needs_bash
def test_a_window_that_comes_up_says_nothing(tmp_path):
    out = _run(tmp_path, 'sleep 1; echo "pfweb: window up (WebviewBackend)"'
                         ' >> "$PFLOG"')
    assert out == ""


@needs_bash
def test_a_window_that_never_comes_up_is_named(tmp_path):
    out = _run(tmp_path, ":")
    assert "has not come up after 4 s" in out


@needs_bash
def test_the_run_ending_closes_it_quietly(tmp_path):
    out = _run(tmp_path, ': GUEST=0; sleep 1; rm -f "$ALIVE"')
    assert out == ""
