"""pfweb.py - the rig windows' web host (the virtual playfield since the Tk
cut-over, 2026-09-23).

What is pinned here is the part every platform shares and none of them can
show on screen: the loopback server's token gate and path containment, the
numbered event stream a page replays from, the images and files the page
fetches, and the queue that keeps a window asked for before the window system
is up (the villain vision can stamp in the first frames) from being dropped.
The windows themselves are proven by the CI captures (webui-builds.yml).
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
if RIG not in sys.path:
    sys.path.insert(0, RIG)


class App:
    def __init__(self, tmp):
        self.calls = []
        self.art = os.path.join(tmp, "art.png")
        with open(self.art, "wb") as f:
            f.write(b"\x89PNG fake")

    def state(self, page):
        return {"page": page, "n": 1}

    def api(self, m, a):
        self.calls.append((m, a))
        if m == "boom":
            raise ValueError("no such call: boom")
        return {"m": m, "a": a}

    def blob(self, key):
        return (b"PNGDATA", "image/png") if key == "b1" else None

    def file(self, name):
        return self.art if name == "art" else None


@pytest.fixture()
def host(tmp_path):
    import pfweb
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>page</html>", encoding="utf8")
    (static / "pf.js").write_text("// js", encoding="utf8")
    (tmp_path / "secret.txt").write_text("no", encoding="utf8")
    h = pfweb.WebHost(str(static), App(str(tmp_path)), title="t")
    h.start()
    yield h
    h.stop()


def _get(h, path, token=True):
    sep = "&" if "?" in path else "?"
    url = "http://127.0.0.1:%d%s" % (h.port, path)
    if token:
        url += sep + "t=" + h.token
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read(), r.headers.get("Content-Type")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type")


def _post(h, body, token=True):
    url = "http://127.0.0.1:%d/api" % h.port + ("?t=" + h.token if token else "")
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None


def test_the_page_and_its_files_need_no_token_but_everything_live_does(host):
    assert _get(host, "/", token=False)[0] == 200
    assert _get(host, "/static/pf.js", token=False)[2] == "text/javascript"
    assert _get(host, "/state", token=False)[0] == 403
    assert _get(host, "/blob/b1", token=False)[0] == 403
    assert _get(host, "/file/art", token=False)[0] == 403
    assert _post(host, {"m": "x"}, token=False)[0] == 403


def test_state_carries_the_event_number_the_page_resumes_from(host):
    host.publish("frame", {"a": 1})
    host.publish("frame", {"a": 2})
    code, body, _ = _get(host, "/state?page=lcd")
    st = json.loads(body)
    assert code == 200 and st["page"] == "lcd" and st["_seq"] == 2


def test_api_calls_reach_the_app_and_errors_come_back_as_errors(host):
    code, r = _post(host, {"m": "hold", "a": [42]})
    assert code == 200 and r == {"ok": True, "r": {"m": "hold", "a": [42]}}
    code, r = _post(host, {"m": "boom", "a": []})
    assert code == 200 and r["ok"] is False and "boom" in r["error"]


def test_a_static_path_cannot_climb_out_of_the_page_folder(host):
    assert _get(host, "/static/../secret.txt", token=False)[0] == 404
    assert _get(host, "/static/..%2Fsecret.txt", token=False)[0] == 404


def test_blobs_files_and_the_favicon(host):
    code, body, ctype = _get(host, "/blob/b1")
    assert (code, body, ctype) == (200, b"PNGDATA", "image/png")
    assert _get(host, "/blob/nope")[0] == 404
    code, body, _ = _get(host, "/file/art")
    assert code == 200 and body == b"\x89PNG fake"
    assert _get(host, "/file/other")[0] == 404
    # the browser asks for it without the token: answered, never a 403 in
    # the page's console
    assert _get(host, "/favicon.ico", token=False)[0] in (200, 204)


def test_the_fonts_are_the_apps_own(host):
    if not host.fonts_dir:
        pytest.skip("no app fonts beside this rig")
    code, body, _ = _get(host, "/fonts/ibm-plex-mono-latin-400-normal.woff2",
                         token=False)
    assert code == 200 and body[:4] == b"wOF2"


def test_long_polling_returns_what_happened_since_a_number(host):
    host.publish("frame", {"x": 1})
    host.publish("lcd", {"y": 2})
    code, body, _ = _get(host, "/events?poll=1&wait=0.2&since=1")
    j = json.loads(body)
    assert j["seq"] == 2
    assert [(e["seq"], e["e"]["type"]) for e in j["events"]] == [(2, "lcd")]


def test_the_event_stream_delivers_numbered_events(host):
    url = "http://127.0.0.1:%d/events?t=%s&since=0" % (host.port, host.token)
    got = []

    def read():
        with urllib.request.urlopen(url, timeout=10) as r:
            for raw in r:
                line = raw.decode().strip()
                if line.startswith("data: "):
                    got.append(json.loads(line[6:]))
                    return
    t = threading.Thread(target=read, daemon=True)
    t.start()
    time.sleep(0.3)
    host.publish("frame", {"fx": {"3": 0}})
    t.join(5)
    assert got == [{"type": "frame", "data": {"fx": {"3": 0}}}]


def test_a_window_asked_for_before_the_window_system_is_up_is_not_lost(host):
    opened = []

    class Backend:
        def open(self, name, spec, on_close=None):
            opened.append(name)
    host.open_window("lcd", {"page": "lcd"})     # no backend yet
    assert opened == []
    host.backend = Backend()
    host.open_window("lcd2", {"page": "lcd"})    # backend, not yet ready
    assert opened == []
    host._flush()
    assert opened == ["lcd", "lcd2"]
    host.open_window("lcd3", {"page": "lcd"})    # ready: straight through
    assert opened == ["lcd", "lcd2", "lcd3"]


def test_the_window_rung_can_be_forced(host, monkeypatch):
    import pfweb
    monkeypatch.setenv("PAD_PF_WINDOW", "browser")
    assert isinstance(pfweb.pick_backend(host), pfweb.BrowserBackend)
    monkeypatch.setenv("PAD_PF_WINDOW", "nonsense")
    assert pfweb.pick_backend(host) is not None


def test_a_browser_tab_window_ends_once_its_page_has_gone_quiet(host,
                                                                monkeypatch):
    import pfweb
    monkeypatch.setattr(pfweb.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(pfweb.BrowserBackend, "GONE_S", 0.3)
    closed = []
    b = pfweb.BrowserBackend(host)
    host.clients = 1                    # a page is listening...
    t = threading.Thread(target=b.run, args=({"page": "main"},
                                             lambda: closed.append(1)))
    t.start()
    time.sleep(1.2)
    assert not closed
    host.clients = 0                    # ...and leaves
    host._touch()
    t.join(5)
    assert closed == [1]


def test_the_host_needs_nothing_but_the_standard_library():
    """It runs on PAD's bundled Python, a Linux desktop's python3 and the
    macOS container's: none of them may be asked to install anything."""
    import ast
    src = open(os.path.join(RIG, "pfweb.py"), encoding="utf8").read()
    top = set()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Import):
            top.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top.add(node.module.split(".")[0])
    assert top <= set(sys.stdlib_module_names), top - set(sys.stdlib_module_names)
