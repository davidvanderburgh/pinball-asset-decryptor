"""A native window that cannot show the page (PAD-748): a Windows PC whose
Edge WebView2 runtime is missing or does not start got an empty window and
nothing in the log.  The app now spots it, says why, and shows itself in
the browser instead."""

import logging
import sys
import threading
import types

import pytest

from pinball_decryptor.webui import host as host_mod
from pinball_decryptor.webui.context import Context
from pinball_decryptor.webui.host import Host, WindowUnusable


class _Hook(list):
    def __iadd__(self, fn):
        self.append(fn)
        return self

    def fire(self, *a):
        for fn in list(self):
            fn(*a)


class _Window:
    def __init__(self):
        self.events = types.SimpleNamespace(
            loaded=_Hook(), shown=_Hook(), closing=_Hook(), maximized=_Hook(),
            restored=_Hook(), resized=_Hook())
        self.closed = threading.Event()

    def destroy(self):
        self.events.closing.fire()
        self.closed.set()


class _Webview(types.ModuleType):
    """pywebview as far as run_native uses it; start() runs ``during``
    with the window, then blocks until the window is closed."""

    def __init__(self, renderer="edgechromium", during=None):
        super().__init__("webview")
        self.renderer = renderer
        self.screens = []
        self.during = during
        self.window = None

    def create_window(self, *a, **k):
        self.window = _Window()
        return self.window

    def start(self, **k):
        if self.during:
            self.during(self.window)
        assert self.window.closed.wait(10), "the window was never closed"


class _Loop:
    def post(self, fn, *a):
        fn(*a)

    def call(self, fn, *a, **k):
        return fn(*a)


class _LogWindow:
    def __init__(self):
        self.lines = []

    def append_log(self, text, tag=None):
        self.lines.append((text, tag))

    def log_history(self):
        return []


def _ctx():
    ctx = Context()
    ctx.loop = _Loop()
    ctx.window = _LogWindow()
    ctx.app = types.SimpleNamespace(root=types.SimpleNamespace(
        title=lambda: "Pinball Asset Decryptor"))
    return ctx


@pytest.fixture
def run(monkeypatch):
    """run_native against a fake pywebview; returns (ctx, closed_app)."""
    closed = []
    monkeypatch.setattr(host_mod, "_close_app", lambda ctx: closed.append(1))
    monkeypatch.delenv("PAD_UI_GUI", raising=False)

    def _run(webview, ctx=None):
        ctx = ctx or _ctx()
        monkeypatch.setitem(sys.modules, "webview", webview)
        host = Host(ctx, "native")
        ctx.host = host
        server = types.SimpleNamespace(port=1)
        try:
            host_mod.run_native(ctx, server, host)
            return ctx, closed, None
        except WindowUnusable as e:
            return ctx, closed, e
    return _run


def test_a_page_that_loads_keeps_the_window(run):
    def during(win):
        ctx.state_snapshot()            # the page asks for its state
        win.destroy()                   # then the user closes the window
    ctx = _ctx()
    ctx, closed, err = run(_Webview(during=during), ctx)
    assert err is None
    assert closed == [1]                # closing the window closes the app


def test_the_engine_failing_to_start_hands_over_to_the_browser(run):
    def during(win):
        logging.getLogger("pywebview").error(
            "WebView2 initialization failed with exception:\n Couldn't find "
            "a compatible Webview2 Runtime installation to host WebViews. "
            "---> System.IO.FileNotFoundException: The system cannot find "
            "the file specified.\n\n   --- End of inner exception stack "
            "trace ---\n   at Microsoft.Web.WebView2.Core.Create()")
    ctx, closed, err = run(_Webview(during=during))
    assert isinstance(err, WindowUnusable)
    assert "WebView2" in str(err)
    assert closed == []                 # the app stays open for the browser
    # the engine's own words reach the app's log, without the stack trace
    text = " ".join(t for t, _tag in ctx.window.lines)
    assert "Couldn't find a compatible Webview2 Runtime" in text
    assert "End of inner exception" not in text
    assert ctx.dialogs.native_file_dialog is None
    assert ctx.host.window is None


def test_a_page_that_never_arrives_hands_over_to_the_browser(run, monkeypatch):
    monkeypatch.setattr(host_mod, "PAGE_WAIT", 0.3)
    ctx, closed, err = run(_Webview())
    assert isinstance(err, WindowUnusable)
    assert "did not load" in str(err)
    assert closed == []


def test_closing_the_window_before_the_wait_is_up_just_closes(run,
                                                             monkeypatch):
    monkeypatch.setattr(host_mod, "PAGE_WAIT", 0.3)
    ctx, closed, err = run(_Webview(during=lambda win: win.destroy()))
    assert err is None
    assert closed == [1]


def test_internet_explorers_engine_is_never_shown(run, monkeypatch):
    """No WebView2 runtime: pywebview would quietly use MSHTML, which cannot
    run the page.  Refused before any window opens."""
    monkeypatch.setattr(host_mod.sys, "platform", "win32")
    wv = _Webview(renderer="mshtml")
    ctx, closed, err = run(wv)
    assert isinstance(err, WindowUnusable)
    assert "WebView2" in str(err)
    assert wv.window is None
    assert closed == []


def test_engine_problem(monkeypatch):
    monkeypatch.delenv("PAD_UI_GUI", raising=False)
    monkeypatch.setattr(host_mod.sys, "platform", "win32")
    assert host_mod.engine_problem(_Webview("edgechromium")) is None
    assert host_mod.engine_problem(_Webview("mshtml"))
    # not known yet: asking for the screens loads the backend
    class _Unloaded:
        renderer = None

        @property
        def screens(self):
            self.renderer = "mshtml"
            return []
    assert host_mod.engine_problem(_Unloaded())
    monkeypatch.setenv("PAD_UI_GUI", "mshtml")      # picked on purpose
    assert host_mod.engine_problem(_Webview("mshtml")) is None
    monkeypatch.delenv("PAD_UI_GUI")
    monkeypatch.setattr(host_mod.sys, "platform", "darwin")
    assert host_mod.engine_problem(_Webview("cocoa")) is None


def test_main_shows_the_browser_and_says_how_to_get_the_window(monkeypatch):
    ctx = _ctx()
    ctx.loop.start = ctx.loop.stop = lambda: None
    server = types.SimpleNamespace(stop=lambda: None)
    browser = []
    monkeypatch.setattr(host_mod, "Context", lambda: ctx)
    monkeypatch.setattr(host_mod, "build",
                        lambda ctx, meanwhile=None: (ctx, server))

    def _native(ctx, server, host):
        raise WindowUnusable("its web engine (Edge WebView2) did not start")
    monkeypatch.setattr(host_mod, "run_native", _native)
    monkeypatch.setattr(host_mod, "run_browser",
                        lambda ctx, server, host: browser.append(1))
    monkeypatch.setattr(host_mod.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "webview", _Webview())
    assert host_mod.main([]) == 0
    assert browser == [1]
    (text, tag), = ctx.window.lines
    assert tag == "warning"
    assert "showing the app in your browser instead" in text
    assert "Microsoft Edge WebView2 Runtime" in text


def test_the_state_request_marks_the_page_seen():
    ctx = Context()
    assert not ctx.page_seen.is_set()
    ctx.state_snapshot()
    assert ctx.page_seen.is_set()
