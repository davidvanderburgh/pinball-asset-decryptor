"""PAD-1029: Restart to update closed the app and nothing reopened it.

David: "Pressing restart to update is not restarting the app".  The swap
helper (core/update_slots.start_swap) was started with DETACHED_PROCESS, and
Windows PowerShell with no console at all exits 0 at once without running a
line of its script: no log, no swap, no relaunch.  The app closed as it
should and its installed folder stayed the old version.

And, asked for on the same ticket: "while it's installing in the background,
I want to see a progress circle / bar".  The background install now reports
how much of the new folder is written, and the update banner draws a bar.
"""

import os
import subprocess
import sys
import threading
import time

import pytest

from pinball_decryptor.core import update_slots as us
from tests.test_pad1024_background_update import (  # noqa: F401
    _banner, _installer, _tree, _until, staged)
from tests.webui_harness import web_app


# ------------------------------------------------------------ the swap
def test_the_swap_helper_is_never_detached(tmp_path):
    seen = {}

    def _popen(args, **kw):
        seen.update(kw, args=args)
    ok, _log = us.start_swap(str(tmp_path / "PAD"), "9.9.9", "", pid=1,
                             popen=_popen, log_path=str(tmp_path / "l"))
    assert ok and seen["args"][0] == "powershell.exe"
    assert not seen["creationflags"] & 0x00000008       # DETACHED_PROCESS
    if sys.platform == "win32":
        assert seen["creationflags"] & subprocess.CREATE_NO_WINDOW


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell")
def test_the_swap_helper_really_swaps_once_the_app_is_gone(tmp_path):
    """The real helper, through the real launch: it waits for the app's
    process, then swaps the folders.  Main's launch ran nothing here."""
    app = tmp_path / "PAD"
    app.mkdir()
    (app / "which.txt").write_text("old", encoding="utf-8")
    nxt = tmp_path / "PAD.next"
    nxt.mkdir()
    (nxt / "which.txt").write_text("new", encoding="utf-8")
    (nxt / us.MARKER).write_text('{"version": "9.9.9"}', encoding="utf-8")
    log = tmp_path / "swap.log"
    stand_in = subprocess.Popen([sys.executable, "-c",
                                 "import time; time.sleep(2)"])
    ok, _ = us.start_swap(str(app), "9.9.9", "", pid=stand_in.pid,
                          launch=False, register=False, log_path=str(log))
    assert ok
    stand_in.wait(30)
    end = time.time() + 60
    while time.time() < end and not (
            log.exists() and "swapped in v9.9.9" in log.read_text()):
        time.sleep(0.2)
    text = log.read_text() if log.exists() else ""
    assert "waiting for the app (pid %d)" % stand_in.pid in text
    assert "swapped in v9.9.9" in text
    assert (app / "which.txt").read_text(encoding="utf-8") == "new"
    assert not (app / us.MARKER).exists()


# ------------------------------------------------------------ progress
def test_the_background_install_reports_how_far_it_is(tmp_path, monkeypatch):
    monkeypatch.setattr(us, "WATCH_EVERY", 0.05)
    app = _tree(tmp_path / "PAD", "1.0.0")
    (app / "big.bin").write_bytes(b"x" * 400_000)
    target = tmp_path / "PAD.next"
    seen = []

    def _run(cmd, **kw):
        if isinstance(cmd, str) and "/STAGED=1" in cmd:
            # the setup exe fills the new folder over a second or so
            _tree(target, "9.9.9")
            for i in range(10):
                (target / ("part%d.bin" % i)).write_bytes(b"x" * 40_000)
                time.sleep(0.1)
        return type("R", (), {"returncode": 0})()
    ok, _ = us.stage_install("s.exe", str(app), "9.9.9", run=_run,
                             progress_cb=seen.append)
    assert ok
    assert seen[0] == 0 and seen[-1] == 100
    assert seen == sorted(seen)                  # never goes backwards
    copying = [p for p in seen if 0 < p < us.COPY_SHARE]
    assert len(copying) >= 3, seen               # moved while it copied
    assert us.COPY_SHARE in seen


def test_folder_bytes(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f").write_bytes(b"12345")
    (tmp_path / "g").write_bytes(b"12")
    assert us.folder_bytes(str(tmp_path)) == 7
    assert us.folder_bytes(str(tmp_path / "nope")) == 0


def test_the_installing_banner_has_a_bar(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        w.window.cb["on_install_update"] = lambda v, inst: None
        w.run(lambda: w.window.show_update_banner(
            "9.9.9", "u", installer=_installer(), stage="installing"))
        assert _banner(w)["progress"] == -1      # a spinner until the first
        w.run(lambda: w.window.show_update_banner(
            "9.9.9", "u", installer=_installer(), stage="installing",
            pct=45))
        b = _banner(w)
        assert b["progress"] == 45
        assert "installing in the background (45%)" in b["text"]
        assert w.state("shell")["update"]["label"] == "Installing v9.9.9… 45%"
        w.run(lambda: w.window.show_update_banner(
            "9.9.9", "u", installer=_installer(), stage="downloading",
            pct=20))
        assert _banner(w)["progress"] == 20
        w.run(lambda: w.window.show_update_banner(
            "9.9.9", "u", installer=_installer(), stage="ready"))
        assert "progress" not in _banner(w)


def test_the_install_progress_reaches_the_banner(tmp_path, staged,
                                                 monkeypatch):
    staged["gate"].set()
    hold = threading.Event()
    monkeypatch.setattr(us, "installed_app_dir",
                        lambda *a, **k: str(tmp_path / "PAD"))
    monkeypatch.setattr(us, "staged_install_ok", lambda app, v: False)

    def _stage(setup, app, version, run=None, cancel_cb=None,
               progress_cb=None):
        progress_cb(0)
        progress_cb(37)
        hold.wait(10)
        return False, "stand-in"
    monkeypatch.setattr(us, "stage_install", _stage)
    with web_app(tmp_path, mfr="stern") as w:
        w.run(w.app._offer_update, "9.9.9", "u", _installer())
        try:
            assert _until(w, lambda: (_banner(w) or {}).get("progress") == 37)
            assert "(37%)" in _banner(w)["text"]
        finally:
            hold.set()
        assert _until(w, lambda: "is ready" in (_banner(w) or {}).get(
            "text", ""))
        assert "progress" not in _banner(w)
