"""Report a problem (PAD-780): core/problem_report.py, and the shellx
service's window against a stand-in for the Worker on localhost (the real
one is tools/donations_worker; its own tests run under node).
"""

import base64
import io
import json
import os
import threading
import urllib.error
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from pinball_decryptor.core import config
from pinball_decryptor.core import problem_report as R
from pinball_decryptor.core import session_log


# ---------------------------------------------------------- a fake Worker
class FakeWorker:
    """Answers /v1/report the way worker.js does.  ``refuse`` answers every
    report with that 4xx message; ``stop()`` takes the line down."""

    def __init__(self):
        self.posts = []
        self.refuse = None
        self._srv = None
        self.url = ""

    def start(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body):
                data = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                fake.posts.append((self.path, dict(self.headers), body))
                if self.path != "/v1/report":
                    return self._send(404, {"ok": False, "error": "Not found."})
                if self.headers.get("X-PAD-Key") != config.REPORTS_APP_KEY:
                    return self._send(403, {"ok": False,
                                            "error": "Not from the app."})
                if fake.refuse:
                    return self._send(400, {"ok": False, "error": fake.refuse})
                return self._send(201, {"ok": True,
                                        "id": "r-%d" % len(fake.posts)})

        self._srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self._srv.server_address[1]
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None


@pytest.fixture
def worker():
    w = FakeWorker().start()
    try:
        yield w
    finally:
        w.stop()


def _png(w=40, h=30):
    from PIL import Image
    im = Image.new("RGB", (w, h), (200, 30, 30))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _report(**kw):
    rep = {"app_version": "1.274.0", "platform": "win32",
           "facts": [["App", "v1.274.0"],
                     ["Card", r"D:\Pinball\images\godzilla_le.raw  print 8f3a"],
                     ["Project", "/home/david/projects/Heisei"]],
           "log": ["[12:00] Extracting C:\\Users\\david\\cards\\a.raw",
                   "[12:01] done"],
           "text": "Write stopped at 40% on the Godzilla card.",
           "name": "Joe", "email": "joe@example.com", "hide_paths": False,
           "picture": None, "at": 1700000000}
    rep.update(kw)
    return rep


# ------------------------------------------------------------ the record
def test_paths_and_the_account_name_are_redacted_on_request():
    out = R.redact(r"read C:\Users\david\cards\a.raw and \\nas\share\b.raw "
                   "then /home/david/x and /Users/david/y and /mnt/d/z",
                   user="david")
    assert out == ("read <path> and <path> then <path> and <path> and "
                   "<path>")
    assert R.redact("hello <user>", user="x") == "hello <user>"
    assert R.redact("", user="david") == ""


def test_the_record_reads_top_to_bottom_and_hides_paths_when_asked():
    text = R.as_text(_report())
    assert text.startswith("Pinball Asset Decryptor problem report\n")
    assert "App: v1.274.0" in text
    assert "Card: D:\\Pinball\\images\\godzilla_le.raw  print 8f3a" in text
    assert "From: Joe <joe@example.com>" in text
    assert "What happened\n-------------\nWrite stopped at 40%" in text
    assert "Log (last 2 lines)" in text and "[12:01] done" in text
    hidden = R.as_text(_report(hide_paths=True))
    assert "Card: <path>  print 8f3a" in hidden
    assert "Project: <path>" in hidden
    assert "Extracting <path>" in hidden
    assert "left out at the user's request" in hidden
    # the user's own words are never touched
    assert "Write stopped at 40% on the Godzilla card." in hidden


def test_validate_bounds_the_fields_and_says_what_is_missing():
    with pytest.raises(ValueError, match="Say what happened"):
        R.validate(_report(text="   short"))
    with pytest.raises(ValueError, match="email address"):
        R.validate(_report(email="not an address"))
    rep = R.validate(_report(text="x" * 5000, name="  Joe   Bloggs ",
                             email=" joe@example.com "))
    assert len(rep["text"]) == R.MAX_TEXT
    assert rep["name"] == "Joe Bloggs" and rep["email"] == "joe@example.com"
    assert R.title_of(_report(text="first line here\nsecond")) == \
        "first line here"
    assert R.title_of(_report(text="w" * 100)).endswith("…")


def test_the_log_tail_is_the_last_lines_of_the_session_log(tmp_path):
    old = session_log.LOG_DIR_OVERRIDE
    session_log.LOG_DIR_OVERRIDE = str(tmp_path / "logs")
    try:
        assert R.log_tail() == []
        os.makedirs(session_log.log_dir())
        with open(session_log.log_path(), "w", encoding="utf-8") as f:
            f.write("\n".join("line %d" % i for i in range(500)) + "\n")
            f.write("bad\x00line\n\n")
        tail = R.log_tail(10)
        assert len(tail) == 10 and tail[0] == "line 491"
        assert tail[-1] == "badline"
    finally:
        session_log.LOG_DIR_OVERRIDE = old


def test_a_picture_is_shrunk_to_a_small_jpeg():
    data, kind = R.shrink_picture(_png(3000, 2000))
    assert kind == "image/jpeg" and data[:3] == b"\xff\xd8\xff"
    assert len(data) <= R.MAX_PICTURE_BYTES
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    assert max(im.size) <= R.PICTURE_MAX_SIDE
    with pytest.raises(ValueError, match="not a picture"):
        R.shrink_picture(b"not a picture at all")


def test_the_payload_and_the_zip_carry_the_record_and_the_picture(tmp_path):
    pic = {"name": "shot.png", "type": "image/jpeg",
           "data": R.shrink_picture(_png())[0]}
    rep = _report(picture=pic)
    p = R.payload(rep)
    assert p["title"] == "Write stopped at 40% on the Godzilla card."
    assert p["body"] == R.as_text(rep)
    assert p["picture_type"] == "image/jpeg"
    assert base64.b64decode(p["picture_b64"]) == pic["data"]
    assert "Picture: shot.png (image/jpeg" in p["body"]
    path = R.save_zip(rep, str(tmp_path / R.default_zip_name(rep["at"])))
    with zipfile.ZipFile(path) as z:
        assert sorted(z.namelist()) == ["picture.jpg", "report.txt"]
        assert z.read("report.txt").decode("utf-8") == R.as_text(rep)
        assert z.read("picture.jpg") == pic["data"]


# -------------------------------------------------------------- the wire
def test_send_talks_to_the_worker_and_tells_a_refusal_from_a_dead_line(worker):
    out = R.send(worker.url, config.REPORTS_APP_KEY, _report())
    assert out["ok"] and out["id"] == "r-1"
    path, headers, body = worker.posts[0]
    assert path == "/v1/report"
    assert headers["User-Agent"] == R.USER_AGENT
    assert body["name"] == "Joe" and "What happened" in body["body"]
    with pytest.raises(R.ReportError, match="Not from the app"):
        R.send(worker.url, "wrong", _report())
    worker.refuse = "Too many reports in one hour."
    with pytest.raises(R.ReportError, match="Too many"):
        R.send(worker.url, config.REPORTS_APP_KEY, _report())
    worker.stop()
    with pytest.raises((urllib.error.URLError, OSError)):
        R.send(worker.url, config.REPORTS_APP_KEY, _report())
    with pytest.raises(R.ReportError, match="No report service"):
        R.send("", "k", _report())


# ------------------------------------------------------------ the window
def until(w, pred, timeout=8.0):
    import time
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


@pytest.fixture
def app_with_worker(tmp_path, worker, monkeypatch):
    from tests.webui_harness import web_app
    monkeypatch.setenv("PAD_REPORTS_URL", worker.url)
    monkeypatch.setattr(config, "REPORTS_URL", worker.url)
    with web_app(tmp_path) as w:
        yield w, worker


def test_the_window_opens_with_the_facts_and_sends_the_record(app_with_worker,
                                                              tmp_path):
    w, worker = app_with_worker
    gear = [it.get("id") for it in w.state("shell")["settings_items"]]
    assert "report_problem" in gear
    assert w.state("shellx")["report"]["available"] is True
    info = w.call("shellx.report_open", "Error: it broke")
    labels = [f[0] for f in info["facts"]]
    assert labels[:2] == ["App", "System"]
    assert info["prefill"] == "Error: it broke"
    assert info["hide_paths"] is True
    preview = w.call("shellx.report_preview", "Write stopped at 40% today",
                     "Joe", "joe@example.com", True)["text"]
    assert "Write stopped at 40% today" in preview
    assert "From: Joe <joe@example.com>" in preview
    with pytest.raises(Exception, match="Say what happened"):
        w.call("shellx.report_send", "short", "", "", True)
    assert w.call("shellx.report_send", "Write stopped at 40% today",
                  "Joe", "joe@example.com", True) == {"sent": True}
    assert until(w, lambda: (w.state("shellx")["report"]["last"] or {}
                             ).get("ok"))
    last = w.state("shellx")["report"]["last"]
    assert last == {"ok": True, "id": "r-1"}
    body = worker.posts[0][2]
    assert body["app_version"] == w.state("shell")["version"]
    assert "left out at the user's request" in body["body"]
    # the form is remembered in settings.json
    s = json.loads((tmp_path / "cfg" / "settings.json").read_text("utf-8"))
    assert s["report"] == {"name": "Joe", "email": "joe@example.com",
                           "hide_paths": True}


def test_a_dead_line_says_so_and_the_file_is_the_fallback(app_with_worker,
                                                          tmp_path):
    w, worker = app_with_worker
    worker.stop()
    w.call("shellx.report_send", "Write stopped at 40% today", "", "", False)
    assert until(w, lambda: w.state("shellx")["report"]["last"] is not None)
    last = w.state("shellx")["report"]["last"]
    assert last["ok"] is False and last["offline"] is True
    assert "can't be reached" in last["error"]
    out = tmp_path / "r.zip"
    w.answers.append(str(out))
    assert w.call("shellx.report_save", "Write stopped at 40% today",
                  "", "", False) == {"path": str(out)}
    with zipfile.ZipFile(out) as z:
        assert "report.txt" in z.namelist()
        assert "Write stopped at 40% today" in z.read("report.txt").decode()


def test_a_picked_picture_rides_along_and_can_be_removed(app_with_worker,
                                                         tmp_path):
    w, worker = app_with_worker
    shot = tmp_path / "shot.png"
    shot.write_bytes(_png(800, 600))
    w.answers.append(str(shot))
    out = w.call("shellx.report_picture", "pick")
    assert out["picture"]["name"] == "shot.png" and out["picture"]["kb"] >= 1
    assert w.state("shellx")["report"]["picture"]["name"] == "shot.png"
    w.call("shellx.report_send", "Write stopped at 40% today", "", "", True)
    assert until(w, lambda: (w.state("shellx")["report"]["last"] or {}
                             ).get("ok"))
    body = worker.posts[0][2]
    assert body["picture_type"] == "image/jpeg"
    assert base64.b64decode(body["picture_b64"])[:3] == b"\xff\xd8\xff"
    # sent: the picture is cleared for the next report
    assert w.state("shellx")["report"]["picture"] is None
    w.answers.append(str(tmp_path / "nope.txt"))
    (tmp_path / "nope.txt").write_text("x")
    with pytest.raises(Exception, match="not a picture"):
        w.call("shellx.report_picture", "pick")
    assert w.call("shellx.report_picture", "clear") == {"picture": None}


def test_no_service_configured_means_save_only(tmp_path, monkeypatch):
    from tests.webui_harness import web_app
    monkeypatch.setenv("PAD_REPORTS_URL", "")
    monkeypatch.setattr(config, "REPORTS_URL", "")
    with web_app(tmp_path) as w:
        assert w.state("shellx")["report"]["available"] is False
        with pytest.raises(Exception, match="No report service"):
            w.call("shellx.report_send", "Write stopped at 40% today",
                   "", "", True)
