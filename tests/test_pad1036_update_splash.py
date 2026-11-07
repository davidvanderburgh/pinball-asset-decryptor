"""PAD-1036: a window to watch while Restart to update swaps versions.

David: "We should have a splash screen with a cool pinball animation on it
for the user to watch while they wait for the app to restart.  Otherwise,
they may think it's broken.  We need to show this after they press
'restart' and until the new app instance comes up."

The splash is a PowerShell/WPF window started from the temp folder
(core/update_splash): the Restart click opens it before the app closes
down, on both Windows routes (the staged swap and the installer), and the
new version closes it when its first page is up.
"""

import os
import subprocess
import sys
import time

import pytest

from pinball_decryptor.core import update_splash as sp
from pinball_decryptor.webui.context import Context
from tests.test_pad1024_background_update import (  # noqa: F401
    _banner, _installer, _until, slots, staged)   # slots needs staged
from tests.webui_harness import web_app


# ------------------------------------------------------------ the script
def test_the_script_carries_the_words_and_the_waits():
    text = sp.splash_script("9.9.9", center=(640, 400), hint_after=7,
                            give_up_after=8, close_after=9)
    assert "'Pinball Asset Decryptor - updating'" in text
    assert "Updating to v9.9.9…" in text
    assert "the new version opens by itself" in text
    assert "start it from its shortcut" in text
    assert "$S.cx = 640; $S.cy = 400; $S.placed = $true" in text
    assert "$S.hintAfter = 7; $S.giveUpAfter = 8; $S.closeAfter = 9" in text
    assert "Add_KeyDown" in text and "Escape" in text      # never traps
    assert "Remove-Item -LiteralPath $PSCommandPath" in text


def test_no_centre_means_the_main_screen():
    text = sp.splash_script("9.9.9")
    assert "$S.placed = $false" in text
    assert 'WindowStartupLocation="CenterScreen"' in text


def test_the_words_follow_the_app_language():
    tr = {"Updating to v9.9.9…": "Aktualisierung auf v9.9.9…",
          "Close": "Schließen"}
    text = sp.splash_script("9.9.9", tr=lambda t: tr.get(t, t))
    assert "Aktualisierung auf v9.9.9…" in text
    assert "'Schließen'" in text
    assert "'Pinball Asset Decryptor'" in text          # the name stays


def test_the_catalogs_have_the_words():
    from pinball_decryptor.webui.i18n import catalog
    for code in ("de", "es", "fr"):
        cat = catalog(code)
        for key in ("Updating to v9.9.9…",
                    "Still updating… the new version opens by itself "
                    "when it is ready.",
                    "This is taking longer than usual. If the app has not "
                    "opened, start it from its shortcut.", "Close"):
            assert cat.tr(key) != key, (code, key)
        assert "9.9.9" in cat.tr("Updating to v9.9.9…")


# ------------------------------------------------------------ the launch
def test_started_from_temp_with_a_console_nobody_sees(tmp_path, monkeypatch):
    """Like the swap helper (PAD-1029): never DETACHED_PROCESS, and never
    from inside the app's folder, which is about to be renamed."""
    monkeypatch.setattr(sp, "find_window", lambda title=None: 0)
    seen = {}

    def _popen(args, **kw):
        seen.update(kw, args=args)
        return "proc"
    ok, info = sp.start_splash("9.9.9", popen=_popen, platform="win32")
    assert ok and info == "proc"
    args = seen["args"]
    assert args[0] == "powershell.exe" and "-STA" in args
    script = args[-1]
    assert os.path.dirname(script) == seen["cwd"]
    assert os.path.basename(script).startswith("pad-splash-")
    assert not seen["creationflags"] & 0x00000008       # DETACHED_PROCESS
    if sys.platform == "win32":
        assert seen["creationflags"] & subprocess.CREATE_NO_WINDOW
    with open(script, encoding="utf-8-sig") as f:
        assert "Updating to v9.9.9" in f.read()
    os.unlink(script)


def test_only_on_windows_and_only_one(monkeypatch):
    ok, why = sp.start_splash("9.9.9", platform="linux")
    assert not ok and "Windows" in why
    monkeypatch.setattr(sp, "find_window", lambda title=None: 42)
    ok, why = sp.start_splash("9.9.9", platform="win32",
                              popen=lambda *a, **k: pytest.fail("started"))
    assert not ok and why == "already showing"


def test_a_launch_that_fails_says_so_and_leaves_no_script(monkeypatch):
    monkeypatch.setattr(sp, "find_window", lambda title=None: 0)
    scripts = []

    def _popen(args, **kw):
        scripts.append(args[-1])
        raise OSError("no powershell")
    ok, why = sp.start_splash("9.9.9", popen=_popen, platform="win32")
    assert not ok and "no powershell" in why
    assert not os.path.exists(scripts[0])


# ------------------------------------------------------------ the app
def _record_splash(shown, result=(True, None), order=None):
    """A stand-in start_splash that records.  Inside the ``with web_app``,
    and set directly, not through monkeypatch: the harness stubs the real
    one on enter and puts it back on exit, and a monkeypatch undone after
    that would put the harness's stub back for the rest of the worker."""
    def _start(version, **kw):
        if order is not None:
            order.append("splash")
        shown.append((version, kw))
        return result
    sp.start_splash = _start


def test_restart_to_update_opens_the_splash_before_closing(tmp_path, slots,
                                                            monkeypatch):
    """The staged swap route: the splash is up before _on_close runs (the
    emulator and WSL shutdowns are the first part of the wait)."""
    from pinball_decryptor import app as app_mod
    order, shown = [], []
    real_close = app_mod.App._on_close
    monkeypatch.setattr(app_mod.App, "_on_close",
                        lambda self: order.append("close") or real_close(self))
    with web_app(tmp_path, mfr="stern") as w:
        _record_splash(shown, order=order)
        w.run(w.app._offer_update, "9.9.9", "u", _installer())
        assert _until(w, lambda: "is ready" in (_banner(w) or {}).get(
            "text", ""))
        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: slots["closed"])
        assert order[:2] == ["splash", "close"]
        assert [v for v, _ in shown] == ["9.9.9"]
        assert slots["swaps"]


def test_the_installer_route_opens_it_too(tmp_path, slots, monkeypatch):
    slots["stage_ok"] = False
    shown = []
    with web_app(tmp_path, mfr="stern") as w:
        _record_splash(shown)
        w.run(w.app._offer_update, "9.9.9", "u", _installer())
        assert _until(w, lambda: "is ready" in (_banner(w) or {}).get(
            "text", ""))
        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: slots["closed"])
        assert slots["launched"] and not slots["swaps"]
        assert [v for v, _ in shown] == ["9.9.9"]


def test_a_second_restart_click_opens_no_second_one(tmp_path, slots,
                                                     monkeypatch):
    """PAD-1034's second click goes straight to the close: no new splash."""
    shown = []
    with web_app(tmp_path, mfr="stern") as w:
        _record_splash(shown)
        w.run(w.app._offer_update, "9.9.9", "u", _installer())
        assert _until(w, lambda: "is ready" in (_banner(w) or {}).get(
            "text", ""))
        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: slots["closed"])
        w.run(w.app._swap_in_staged, w.app._bg_update)
        time.sleep(0.3)
        assert len(shown) == 1


def test_a_failed_splash_never_stops_the_restart(tmp_path, slots,
                                                 monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        _record_splash([], result=(False, "no powershell"))
        w.run(w.app._offer_update, "9.9.9", "u", _installer())
        assert _until(w, lambda: "is ready" in (_banner(w) or {}).get(
            "text", ""))
        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: slots["closed"])
        assert slots["swaps"]


def test_the_first_page_of_a_run_dismisses_it(monkeypatch):
    calls = []
    monkeypatch.setattr(sp, "dismiss", lambda title=None: calls.append(1))
    ctx = Context()
    try:
        ctx.state_snapshot()
        ctx.state_snapshot()
        ctx.state_snapshot()
    finally:
        ctx.loop.stop()
    assert calls == [1]                     # once: the page's first ask


def test_dismiss_without_a_splash_is_nothing():
    assert sp.dismiss("PAD-1036 no such window") is False


# ------------------------------------------------------------ for real
@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell/WPF")
def test_the_real_splash_shows_and_closes_on_dismiss():
    """The real script through the real launch, off every screen: its
    window is up within seconds, dismiss() (what the new version does)
    closes it, and the process ends and takes its script with it."""
    title = "PAD-1036 test splash %d" % os.getpid()
    ok, proc = sp.start_splash("9.9.9", title=title, offscreen=True)
    assert ok, proc
    script = proc.args[-1]
    try:
        end = time.time() + 30
        while time.time() < end and not sp.find_window(title):
            assert proc.poll() is None, "the splash exited (%s)" % proc.returncode
            time.sleep(0.1)
        assert sp.find_window(title), "no splash window after 30 s"
        time.sleep(1.0)                                   # a few frames
        assert proc.poll() is None                        # still running
        assert sp.dismiss(title)
        proc.wait(20)
        assert proc.returncode == 0
        assert not sp.find_window(title)
        assert not os.path.exists(script)
    finally:
        if proc.poll() is None:
            proc.kill()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell/WPF")
def test_the_real_splash_gives_up_in_time():
    """The waits, shortened to seconds: it closes itself at CLOSE_AFTER."""
    title = "PAD-1036 test closes %d" % os.getpid()
    ok, proc = sp.start_splash("9.9.9", title=title, offscreen=True,
                               hint_after=1, give_up_after=2, close_after=4)
    assert ok, proc
    try:
        proc.wait(45)
        assert proc.returncode == 0
    finally:
        if proc.poll() is None:
            proc.kill()
