"""The update banner's Download button must never be a dead button.

aly, Ubuntu AppImage: clicking Download did nothing -- the browser
handoff failed inside the bundle's environment and the GUI had no way to
know.  ``MainWindow.open_link`` now goes through core.desktop (which
reports failure honestly) and surfaces the URL when it can't be opened.
These run unbound with a stub ``self`` -- no Tk needed.
"""

import threading

from pinball_decryptor.gui import main_window as mw


class _FakeRoot:
    def __init__(self):
        self.clipboard = []
        self.done = threading.Event()

    def after(self, _ms, fn):
        fn()
        self.done.set()

    def clipboard_clear(self):
        self.clipboard = []

    def clipboard_append(self, text):
        self.clipboard.append(text)


class _Win:
    # The two real methods under test; everything else they touch is a stub.
    open_link = mw.MainWindow.open_link
    _open_update_url = mw.MainWindow._open_update_url
    _link_opened = mw.MainWindow._link_opened

    def __init__(self):
        self.root = _FakeRoot()
        self._update_banner_url = "https://example.invalid/releases/v9"


def _run(monkeypatch, result, url="https://example.invalid/releases/v9"):
    warnings = []
    monkeypatch.setattr(mw.messagebox, "showwarning",
                        lambda t, m, **k: warnings.append((t, m)))
    monkeypatch.setattr(mw.session_log, "append",
                        lambda *a, **k: None)
    monkeypatch.setattr(mw.desktop, "open_url", lambda u: result)
    win = _Win()
    mw.MainWindow.open_link(win, url, what="the release page")
    assert win.root.done.wait(5), "open_link never reported back"
    return win, warnings


def test_download_goes_through_desktop_opener(monkeypatch):
    seen = []
    monkeypatch.setattr(mw.desktop, "open_url",
                        lambda u: (seen.append(u), (True, ""))[1])
    win = _Win()
    mw.MainWindow._open_update_url(win)
    assert win.root.done.wait(5)
    assert seen == ["https://example.invalid/releases/v9"]


def test_success_is_quiet(monkeypatch):
    win, warnings = _run(monkeypatch, (True, ""))
    assert warnings == []
    assert win.root.clipboard == []


def test_failure_shows_the_url_and_copies_it(monkeypatch):
    win, warnings = _run(monkeypatch, (False, "no desktop opener found"))
    assert len(warnings) == 1
    body = warnings[0][1]
    assert "https://example.invalid/releases/v9" in body
    assert "no desktop opener found" in body
    assert win.root.clipboard == ["https://example.invalid/releases/v9"]


def test_no_url_does_nothing(monkeypatch):
    monkeypatch.setattr(mw.desktop, "open_url",
                        lambda u: (_ for _ in ()).throw(
                            AssertionError("launched with no URL")))
    mw.MainWindow.open_link(_Win(), "")
