"""The desktop host's start-up (PAD-610): the window opens without waiting
behind the App's start-up jobs, and a title set before it shows is kept."""

import threading
import types

from pinball_decryptor.webui import host as host_mod
from pinball_decryptor.webui.host import Host


class _Win:
    def __init__(self):
        self.titles = []

    def set_title(self, text):
        self.titles.append(text)


def test_a_title_set_before_the_window_shows_waits_for_it():
    """pywebview's set_title blocks its caller until the window shows; the
    app sets titles on its UI loop, so before that the host only keeps it."""
    host = Host(types.SimpleNamespace(), "native")
    host.set_title("before any window")
    win = _Win()
    host.window = win
    host.set_title("Godzilla Premium 1.16")
    assert win.titles == []
    host._on_shown()
    assert win.titles == ["Godzilla Premium 1.16"]
    host.set_title("later")
    assert win.titles == ["Godzilla Premium 1.16", "later"]


def test_nothing_waits_when_no_title_was_set_before_showing():
    host = Host(types.SimpleNamespace(), "native")
    host.window = _Win()
    host._on_shown()
    assert host.window.titles == []


def test_build_runs_the_hosts_work_while_the_app_is_made(monkeypatch):
    """build(meanwhile=...) makes the App on the UI loop while the calling
    thread loads the window toolkit, and keeps the saved window place read
    as the App was made (asked for afterwards it waited behind every job
    the App queued)."""
    from pinball_decryptor.webui.context import Context
    made_on, seen = [], []

    class _App:
        def __init__(self, ctx):
            made_on.append(threading.current_thread())
            ctx.app = self
            ctx.loop.post(lambda: seen.append("start-up job"))

        def saved_geometry(self):
            seen.append("geometry")
            return (1000, 700, 10, 20, False)

        accept_disclaimer = _on_ui_zoom_change = lambda *a: None

    import pinball_decryptor.app as app_mod
    monkeypatch.setattr(app_mod, "App", _App)
    monkeypatch.setattr(host_mod.compat, "install", lambda ctx: None)
    ctx = Context()
    ran = []
    ctx, server = host_mod.build(
        ctx, meanwhile=lambda: ran.append(threading.current_thread()))
    try:
        assert ran == [threading.current_thread()]
        assert made_on and made_on[0] is not threading.current_thread()
        assert ctx.start_geometry == (1000, 700, 10, 20, False)
        assert seen[0] == "geometry"
    finally:
        ctx.loop.stop()
        server.stop()


def test_a_failing_meanwhile_never_stops_the_start(monkeypatch):
    from pinball_decryptor.webui.context import Context

    class _App:
        def __init__(self, ctx):
            ctx.app = self

        def saved_geometry(self):
            return None

        accept_disclaimer = _on_ui_zoom_change = lambda *a: None

    import pinball_decryptor.app as app_mod
    monkeypatch.setattr(app_mod, "App", _App)
    monkeypatch.setattr(host_mod.compat, "install", lambda ctx: None)

    def _boom():
        raise RuntimeError("no web view here")
    ctx, server = host_mod.build(Context(), meanwhile=_boom)
    try:
        assert isinstance(ctx.app, _App) and ctx.start_geometry is None
    finally:
        ctx.loop.stop()
        server.stop()
