"""PAD-1191 (Ben): a video plays full screen, as on YouTube.

The page fills the window with the player; the app's window goes full screen
with it through ``shell.fullscreen`` -> Host.set_fullscreen, since pywebview
ignores a page asking for full screen.  Full screen must never be kept as the
window's size or maximized state, and leaving it puts a maximized window back
maximized (pywebview's toggle restores it to Normal)."""

import os
import types

from pinball_decryptor.webui import host as host_mod
from pinball_decryptor.webui.host import Host

HERE = os.path.dirname(os.path.abspath(__file__))
VIDEO_JS = os.path.join(HERE, "..", "pinball_decryptor", "webui", "static", "js", "tabs", "video.js")


class _Win:
    """pywebview's Window as far as full screen goes: toggle_fullscreen
    maximizes (WinForms) and its way back restores, firing the events."""

    def __init__(self, on_max=None, on_restore=None):
        self.calls = []
        self.on_max, self.on_restore = on_max, on_restore
        self.fs = False

    def toggle_fullscreen(self):
        self.fs = not self.fs
        self.calls.append("toggle")
        hook = self.on_max if self.fs else self.on_restore
        if hook:
            hook()

    def maximize(self):
        self.calls.append("maximize")


def _host(maximized=False):
    host = Host(types.SimpleNamespace(), "native")
    host._maximized = maximized
    return host


def test_full_screen_toggles_the_window_once_each_way():
    host = _host()
    win = host.window = _Win()
    assert host.set_fullscreen(True) is True
    assert host.fullscreen
    assert host.set_fullscreen(True) is True          # already: nothing more
    assert host.set_fullscreen(False) is True
    assert not host.fullscreen
    assert host.set_fullscreen(False) is True
    assert win.calls == ["toggle", "toggle"]


def test_a_maximized_window_comes_back_maximized():
    host = _host(maximized=True)
    win = host.window = _Win()
    host.set_fullscreen(True)
    assert host.is_maximized()                        # what the app saves meanwhile
    host.set_fullscreen(False)
    assert win.calls == ["toggle", "toggle", "maximize"]
    assert host.is_maximized()


def test_a_normal_window_is_not_maximized_by_full_screen():
    host = _host(maximized=False)
    win = host.window = _Win()
    host.set_fullscreen(True)
    assert not host.is_maximized()
    host.set_fullscreen(False)
    assert win.calls == ["toggle", "toggle"]
    assert not host.is_maximized()


def test_no_window_leaves_it_to_the_browser():
    """In a browser (or serve mode) there is no app window: False tells the
    page to ask the browser for its own full screen."""
    assert _host().set_fullscreen(True) is False
    browser = Host(types.SimpleNamespace(), "browser")
    browser.window = _Win()
    assert browser.set_fullscreen(True) is False
    assert browser.window.calls == []


def test_a_window_that_cannot_go_full_screen_says_so():
    host = _host()

    class _Broken(_Win):
        def toggle_fullscreen(self):
            raise RuntimeError("no")
    host.window = _Broken()
    assert host.set_fullscreen(True) is False
    assert not host.fullscreen


def test_full_screen_size_is_never_remembered():
    saved = {}
    app = types.SimpleNamespace(_settings=saved, _last_normal_geometry=None)
    host = _host()
    host.window = types.SimpleNamespace(x=0, y=0, toggle_fullscreen=lambda: None)
    ctx = types.SimpleNamespace(app=app)
    host._fullscreen = True
    host_mod._remember_geometry(ctx, host, 1920, 1080)
    assert saved == {}
    host._fullscreen = False
    host_mod._remember_geometry(ctx, host, 1200, 800)
    assert saved["window_geometry"] == "1200x800+0+0"


def test_both_video_players_offer_full_screen():
    """The Video tab's Original / Replacement players and each Compare tile."""
    with open(VIDEO_JS, encoding="utf-8") as f:
        js = f.read()
    assert js.count("<${FullButton} fv=${fv} />") == 2
    assert js.count("const fv = useFullView(playing);") == 2
    assert 'call("shell.fullscreen", on)' in js
    with open(os.path.join(os.path.dirname(host_mod.__file__), "host.py"), encoding="utf-8") as f:
        assert '"shell.fullscreen"' in f.read()
