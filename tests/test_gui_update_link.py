"""The update banner's Download button must never be a dead button.

A tester, Ubuntu AppImage: clicking Download did nothing -- the browser
handoff failed inside the bundle's environment and the UI had no way to
know.  Opening a link now goes through core.desktop (which reports failure
honestly) and surfaces the URL when it can't be opened.  Driven through the
web UI's ``shellx`` service (webui/tabs/shell_extras.py).
"""

import threading
import time

from pinball_decryptor.core import desktop
from tests.webui_harness import web_app

URL = "https://example.invalid/releases/v9"


def _svc(w):
    return w.window.service("shellx")


def _clipboard(w, monkeypatch):
    seen = []
    real = w.ctx.bus.publish

    def _publish(event, **data):
        if event == "clipboard":
            seen.append(data.get("text"))
        return real(event, **data)
    monkeypatch.setattr(w.ctx.bus, "publish", _publish)
    return seen


def _run(w, monkeypatch, result, url=URL):
    """Open *url* with the opener answering *result*; wait for the worker
    and whatever it hands back to the UI loop."""
    done = threading.Event()

    def _open(u):
        try:
            return result
        finally:
            done.set()
    monkeypatch.setattr(desktop, "open_url", _open)
    clip = _clipboard(w, monkeypatch)
    n = len(w.asked)
    w.run(_svc(w).open_link_checked, url, "the release page")
    assert done.wait(5), "the link was never handed to the opener"
    time.sleep(0.1)
    w.drain()
    return w.asked[n:], clip


def test_download_goes_through_desktop_opener(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        seen = []
        done = threading.Event()

        def _open(u):
            seen.append(u)
            done.set()
            return True, ""
        monkeypatch.setattr(desktop, "open_url", _open)
        svc = _svc(w)

        def _banner():
            svc._update_banner_url = URL
        w.run(_banner)
        w.run(svc._open_update_url)
        assert done.wait(5)
        assert seen == [URL]


def test_success_is_quiet(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        warnings, clip = _run(w, monkeypatch, (True, ""))
        assert warnings == []
        assert clip == []


def test_failure_shows_the_url_and_copies_it(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        warnings, clip = _run(w, monkeypatch,
                              (False, "no desktop opener found"))
        assert len(warnings) == 1
        body = warnings[0]["message"]
        assert URL in body
        assert "no desktop opener found" in body
        assert clip == [URL]


def test_no_url_does_nothing(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        launched = []
        monkeypatch.setattr(desktop, "open_url",
                            lambda u: (launched.append(u), (True, ""))[1])
        w.run(_svc(w).open_link_checked, "")
        assert w.call("shellx.open_link", "") is False
        time.sleep(0.1)
        w.drain()
        assert launched == [], "launched with no URL"
