"""PAD-1227 (BEN, JJP GNR): Choose... pressed again while a file picker was up
opened another picker over it, each on a new thread, stacking with every
click until the app froze.  Now one picker is open at a time, and on Windows
the OS picker is shown on the window's own GUI thread."""
import sys
import threading
import types

import pytest

from pinball_decryptor.webui import compat, host as host_mod
from pinball_decryptor.webui.context import Context


@pytest.fixture
def ctx():
    c = Context()
    compat.install(c)
    c.loop.start()
    yield c
    c.dialogs.cancel_all()
    c.loop.stop()
    c.bus.close()
    compat.uninstall()


def test_a_second_pick_while_a_picker_is_open_opens_nothing(ctx):
    d = ctx.dialogs
    opened, release = [], threading.Event()

    def native(spec):
        opened.append(spec["title"])
        release.wait(10)
        return "C:/clips/new.mp4"
    d.native_file_dialog = native
    first = {}
    threading.Thread(target=lambda: first.update(
        r=ctx.loop.call(lambda: d.file("open", title="one")))).start()
    for _ in range(200):
        if opened:
            break
        threading.Event().wait(0.01)
    assert opened == ["one"]
    # the loop keeps turning under the open picker: further clicks run, and
    # each is a cancelled pick at once, not a second picker
    assert ctx.loop.call(lambda: d.file("open", title="two"), timeout=5) == ""
    assert ctx.loop.call(lambda: d.file("open", title="three", multiple=True),
                         timeout=5) == ()
    assert opened == ["one"]
    release.set()
    for _ in range(200):
        if "r" in first:
            break
        threading.Event().wait(0.01)
    assert first["r"].replace("\\", "/") == "C:/clips/new.mp4"
    # closed: the next click opens a picker again
    assert ctx.loop.call(lambda: d.file("open", title="four"), timeout=5)
    assert opened == ["one", "four"]


def test_a_picker_that_fails_frees_the_next_one(ctx):
    d = ctx.dialogs

    def broken(spec):
        raise RuntimeError("no dialog")
    d.native_file_dialog = broken
    d.ask = lambda spec: ""          # the page's own picker, cancelled
    assert ctx.loop.call(lambda: d.file("open", title="x"), timeout=5) == ""
    d.native_file_dialog = lambda spec: "C:/a.mp4"
    assert ctx.loop.call(lambda: d.file("open", title="y"), timeout=5)


class _Form:
    """A WinForms form stand-in: Invoke runs the delegate on its own thread."""
    InvokeRequired = True

    def __init__(self):
        self.threads = []

    def Invoke(self, action):                       # noqa: N802
        def run():
            self.threads.append(threading.current_thread().name)
            action()
        t = threading.Thread(target=run, name="gui")
        t.start()
        t.join()


def _system(monkeypatch):
    monkeypatch.setitem(sys.modules, "System",
                        types.SimpleNamespace(Action=lambda fn: fn))


def test_windows_shows_the_picker_on_the_windows_gui_thread(monkeypatch):
    monkeypatch.setattr(host_mod.sys, "platform", "win32")
    _system(monkeypatch)
    form = _Form()
    win = types.SimpleNamespace(native=form)
    ran = []
    assert host_mod._on_gui_thread(
        win, lambda: ran.append(threading.current_thread().name) or "p") == "p"
    assert ran == ["gui"] and form.threads == ["gui"]


def test_an_error_on_the_gui_thread_comes_back_to_the_caller(monkeypatch):
    monkeypatch.setattr(host_mod.sys, "platform", "win32")
    _system(monkeypatch)
    win = types.SimpleNamespace(native=_Form())

    def boom():
        raise ValueError("bad filter")
    with pytest.raises(ValueError, match="bad filter"):
        host_mod._on_gui_thread(win, boom)


def test_already_on_the_gui_thread_or_not_windows_runs_as_is(monkeypatch):
    form = _Form()
    form.InvokeRequired = False
    monkeypatch.setattr(host_mod.sys, "platform", "win32")
    me = threading.current_thread().name
    assert host_mod._on_gui_thread(types.SimpleNamespace(native=form),
                                   lambda: threading.current_thread().name) == me
    monkeypatch.setattr(host_mod.sys, "platform", "darwin")
    assert host_mod._on_gui_thread(types.SimpleNamespace(native=_Form()),
                                   lambda: threading.current_thread().name) == me
    assert form.threads == []


def test_native_file_dialog_goes_through_the_gui_thread(monkeypatch):
    monkeypatch.setattr(host_mod.sys, "platform", "win32")
    _system(monkeypatch)
    form = _Form()
    seen = []

    class _Win:
        native = form

        def create_file_dialog(self, kind, **kw):
            seen.append((threading.current_thread().name, kind))
            return ("C:/clips/new.mp4",)
    fake_webview = types.SimpleNamespace(FileDialog=types.SimpleNamespace(
        OPEN="open", SAVE="save", FOLDER="folder"))
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    h = host_mod.Host.__new__(host_mod.Host)
    h.window = _Win()
    out = h.native_file_dialog({"mode": "open", "initialdir": "", "multiple": False,
                                "filetypes": []})
    assert out == "C:/clips/new.mp4"
    assert seen == [("gui", "open")]
