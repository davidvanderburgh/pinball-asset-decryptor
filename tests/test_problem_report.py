"""Report a problem (PAD-780): core/problem_report.py, and the shellx
service's window against a stand-in for the Worker on localhost (the real
one is tools/donations_worker; its own tests run under node).
"""

import base64
import io
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from pinball_decryptor.core import config
from pinball_decryptor.core import problem_report as R
from pinball_decryptor.core import session_log


# ---------------------------------------------------------- a fake Worker
class FakeWorker:
    """Answers /v1/report and /v1/report/status the way worker.js does.
    ``refuse`` answers every report with that 4xx message; ``states`` is
    what the status call says per id; ``stop()`` takes the line down."""

    def __init__(self):
        self.posts = []
        self.asked = []
        self.refuse = None
        self.states = {}
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

            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                if u.path != "/v1/report/status":
                    return self._send(404, {"ok": False, "error": "Not found."})
                if self.headers.get("X-PAD-Key") != config.REPORTS_APP_KEY:
                    return self._send(403, {"ok": False,
                                            "error": "Not from the app."})
                ids = urllib.parse.parse_qs(u.query).get("ids", [""])[0]
                ids = [i for i in ids.split(",") if i]
                fake.asked.append(ids)
                rows = []
                for i in ids:
                    st = fake.states.get(i) or {"state": "received"}
                    rows.append(dict({"id": i, "version": "", "message": "",
                                      "answered_at": 0}, **st))
                return self._send(200, {"ok": True, "rows": rows})

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
           "name": "Joe", "hide_paths": False,
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


def test_a_known_path_with_spaces_goes_whole():
    """PAD-929: the regex stops at the first space, so 'C:\\...\\HEISEI
    v1.99D + mods' left '<path> v1.99D + mods' behind.  The card's and the
    project's own paths go whole, with whatever runs on from them."""
    project = r"C:\Users\david\OneDrive\Desktop\HEISEI v1.99D + daveyvandy modes"
    card = project + r"\build\Godzilla Premium 1.16 Heisei.raw"
    known = [card, project]
    assert R.redact(card + "  print 8f3a", user="david",
                    known=known) == "<path>  print 8f3a"
    assert R.redact(project, user="david", known=known) == "<path>"
    assert R.redact("wrote %s\\images\\a.png fine" % project, user="david",
                    known=known) == "wrote <path> fine"
    # forward slashes and another case are the same folder
    assert R.redact(project.replace("\\", "/").upper() + "/x", user="david",
                    known=known) == "<path>"
    # without them the old leak is what the regex alone can do
    assert R.redact(project, user="david").startswith("<path> v1.99D")
    hidden = R.as_text(_report(hide_paths=True, paths=known,
                               facts=[["Card", card], ["Project", project]],
                               log=["saved to " + project]))
    assert "HEISEI" not in hidden and "Godzilla Premium" not in hidden
    assert "Card: <path>\n" in hidden and "Project: <path>\n" in hidden


def test_the_record_reads_top_to_bottom_and_hides_paths_when_asked():
    text = R.as_text(_report())
    assert text.startswith("Pinball Asset Decryptor problem report\n")
    assert "App: v1.274.0" in text
    assert "Card: D:\\Pinball\\images\\godzilla_le.raw  print 8f3a" in text
    assert "From: Joe\n" in text
    assert "What happened\n-------------\nWrite stopped at 40%" in text
    assert "Log (last 2 lines)" in text and "[12:01] done" in text
    hidden = R.as_text(_report(hide_paths=True, name=""))
    assert "Card: <path>  print 8f3a" in hidden
    assert "Project: <path>" in hidden
    assert "Extracting <path>" in hidden
    assert "left out at the user's request" in hidden
    assert "From:" not in hidden
    # the user's own words are never touched
    assert "Write stopped at 40% on the Godzilla card." in hidden


def test_validate_bounds_the_fields_and_says_what_is_missing():
    with pytest.raises(ValueError, match="Say what happened"):
        R.validate(_report(text="   short"))
    rep = R.validate(_report(text="x" * 5000, name="  Joe   Bloggs "))
    assert len(rep["text"]) == R.MAX_TEXT
    assert rep["name"] == "Joe Bloggs"
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


def test_a_visual_pinball_report_carries_the_controller_log(tmp_path, monkeypatch):
    """PAD-902: a table's run and its DOF are logged by the controller, not
    the app, so a Visual Pinball report said nothing about DOF at all."""
    monkeypatch.setenv("TEMP", str(tmp_path))
    assert R.vpx_log_tail("Visual Pinball") == []
    log = tmp_path / "padcontroller.log"
    log.write_text("\n".join(
        ["15:36:44 game metallica_spike: map C:\\x\\metallica_spike.vpxmap.json"]
        + ["15:36:45 sol %d -> 1" % i for i in range(400)]
        + ["15:36:45 sw 1065 -> id 65 = 1",
           "15:36:45 DOF for mtl_180h: up", "",
           "15:40:02 DOF for mtl_180h finished after 0 events"]) + "\n",
        encoding="utf-8")
    tail = R.vpx_log_tail("Visual Pinball")
    assert tail == ["15:36:44 game metallica_spike: map C:\\x\\metallica_spike.vpxmap.json",
                    "15:36:45 DOF for mtl_180h: up",
                    "15:40:02 DOF for mtl_180h finished after 0 events"]
    assert len(R.vpx_log_tail("Visual Pinball", max_lines=2)) == 2
    # another tab: only while a table ran lately
    assert R.vpx_log_tail("Stern Pinball") == tail
    later = os.path.getmtime(str(log)) + R.VPX_RECENT_S + 1
    assert R.vpx_log_tail("Stern Pinball", now=later) == []
    assert R.vpx_log_tail("Visual Pinball", now=later) == tail
    text = R.as_text(_report(vpx_log=tail, hide_paths=True))
    assert "Visual Pinball controller log (last 3 lines)" in text
    assert "15:36:44 game metallica_spike: map <path>" in text
    assert text.index("Log (last") < text.index("Visual Pinball controller log")
    assert "controller log" not in R.as_text(_report())


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
    assert "email" not in p
    assert p["picture_type"] == "image/jpeg"
    assert base64.b64decode(p["picture_b64"]) == pic["data"]
    assert "Picture: shot.png (image/jpeg" in p["body"]
    path = R.save_zip(rep, str(tmp_path / R.default_zip_name(rep["at"])))
    with zipfile.ZipFile(path) as z:
        assert sorted(z.namelist()) == ["picture.jpg", "report.txt"]
        assert z.read("report.txt").decode("utf-8") == R.as_text(rep)
        assert z.read("picture.jpg") == pic["data"]


# ------------------------------------------------------------ the answer
def test_the_cache_remembers_sent_reports_and_folds_in_the_answers(tmp_path):
    path = R.cache_path(str(tmp_path / "settings.json"))
    cache = R.load_cache(path)
    assert cache == {"mine": [], "checked_at": 0.0, "install": ""}
    for i in range(25):
        R.remember(cache, _report(text="report number %d of many" % i),
                   {"id": "id-%d" % i})
    assert len(cache["mine"]) == R.KEEP_MINE
    assert cache["mine"][-1]["id"] == "id-24"
    assert cache["mine"][-1]["title"] == "report number 24 of many"
    assert cache["mine"][-1]["state"] == "received"
    assert cache["mine"][-1]["seen"] is True
    R.save_cache(path, cache)
    again = R.load_cache(path)
    assert [m["id"] for m in again["mine"]] == [m["id"] for m in cache["mine"]]
    news = R.apply_status(again, {
        "id-24": {"state": "released", "version": "1.275.0",
                  "message": "Fixed.", "answered_at": 5},
        "id-23": {"state": "filed", "version": "", "message": "",
                  "answered_at": 0},
        "id-22": {"state": "closed", "version": "", "message": "",
                  "answered_at": 6}})
    assert [n["id"] for n in news] == ["id-22", "id-24"]
    assert news[1]["seen"] is False and news[1]["version"] == "1.275.0"
    by = {m["id"]: m for m in again["mine"]}
    assert by["id-23"]["state"] == "filed" and by["id-23"]["seen"] is True
    assert R.state_words(by["id-24"]) == "Addressed in v1.275.0"
    assert R.state_words(by["id-23"]) == "Being looked at"
    assert R.state_words(by["id-22"]) == "Looked at and closed"
    assert R.state_words({"state": "unknown"}) == "No longer on record"
    assert R.answered(by["id-24"]) and not R.answered(by["id-23"])
    # the same answer again is not news twice
    assert R.apply_status(again, {"id-24": {
        "state": "released", "version": "1.275.0", "message": "Fixed.",
        "answered_at": 5}}) == []
    # junk on disk is an empty cache
    (tmp_path / "reports_cache.json").write_text("[1, 2", encoding="utf-8")
    assert R.load_cache(path)["mine"] == []


# -------------------------------------------------------------- the wire
def test_send_and_status_talk_to_the_worker_and_tell_a_refusal_from_a_dead_line(worker):
    out = R.send(worker.url, config.REPORTS_APP_KEY, _report())
    assert out["ok"] and out["id"] == "r-1"
    path, headers, body = worker.posts[0]
    assert path == "/v1/report"
    assert headers["User-Agent"] == R.USER_AGENT
    assert body["name"] == "Joe" and "What happened" in body["body"]
    worker.states["r-1"] = {"state": "released", "version": "1.275.0",
                            "message": "Fixed.", "answered_at": 9}
    rows = R.fetch_status(worker.url, config.REPORTS_APP_KEY, ["r-1", "zz"])
    assert rows["r-1"] == {"state": "released", "version": "1.275.0",
                           "message": "Fixed.", "answered_at": 9,
                           "stage": "", "ticket": "", "progress": -1}
    assert rows["zz"]["state"] == "received"
    assert R.fetch_status(worker.url, config.REPORTS_APP_KEY, []) == {}
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


def _banner(w, bid):
    return next((b for b in (w.state("shell").get("banners") or [])
                 if b.get("id") == bid), None)


def test_the_facts_table_follows_the_leave_paths_out_box(app_with_worker,
                                                        tmp_path):
    """PAD-929: ticked, the table under the form showed the card's and the
    project's full paths although the record leaves them out.  The window
    gets the facts both ways and shows the redacted ones when ticked."""
    w, _worker = app_with_worker
    user = os.path.basename(os.path.expanduser("~").rstrip("\\/"))
    project = tmp_path / "HEISEI v1.99D + daveyvandy modes"
    project.mkdir()
    card = project / "Godzilla Premium.raw"
    card.write_bytes(b"\0" * 512)
    w.run(lambda: w.window.extract_input_var.set(str(card)))
    w.run(lambda: w.window.write_assets_var.set(str(project)))
    info = w.call("shellx.report_open", "")
    shown = dict(info["facts"])
    hidden = dict(info["facts_hidden"])
    assert [f[0] for f in info["facts_hidden"]] == [f[0] for f in info["facts"]]
    assert shown["Project"] == str(project)
    assert str(card) in shown["Card"]
    assert hidden["Project"] == "<path>"
    assert hidden["Card"].startswith("<path>")
    for label in ("Card", "Project"):
        assert "HEISEI" not in hidden[label]
        assert "Godzilla" not in hidden[label]
        assert str(tmp_path) not in hidden[label]
        if len(user) > 1:
            assert user.lower() not in hidden[label].lower()
    assert hidden["App"] == shown["App"]
    # what the table shows ticked is what the record carries
    preview = w.call("shellx.report_preview", "Write stopped at 40% today",
                     "", True)["text"]
    assert "Project: %s" % hidden["Project"] in preview
    assert "Card: %s" % hidden["Card"] in preview


def test_the_window_opens_with_the_facts_and_sends_the_record(app_with_worker,
                                                              tmp_path):
    w, worker = app_with_worker
    gear = [it.get("id") for it in w.state("shell")["settings_items"]]
    assert "report_problem" in gear
    assert w.state("shellx")["report"]["available"] is True
    assert w.state("shellx")["report"]["mine"] == []
    info = w.call("shellx.report_open", "Error: it broke")
    labels = [f[0] for f in info["facts"]]
    assert labels[:2] == ["App", "System"]
    assert info["prefill"] == "Error: it broke"
    assert info["hide_paths"] is True
    assert "email" not in info
    preview = w.call("shellx.report_preview", "Write stopped at 40% today",
                     "Joe", True)["text"]
    assert "Write stopped at 40% today" in preview
    assert "From: Joe" in preview
    with pytest.raises(Exception, match="Say what happened"):
        w.call("shellx.report_send", "short", "", True)
    assert w.call("shellx.report_send", "Write stopped at 40% today",
                  "Joe", True) == {"sent": True}
    assert until(w, lambda: (w.state("shellx")["report"]["last"] or {}
                             ).get("ok"))
    rep = w.state("shellx")["report"]
    assert rep["last"] == {"ok": True, "id": "r-1"}
    body = worker.posts[0][2]
    assert body["app_version"] == w.state("shell")["version"]
    assert "email" not in body
    assert "left out at the user's request" in body["body"]
    # the report is remembered as this app's own, received so far
    assert [(m["id"], m["state"], m["words"]) for m in rep["mine"]] == [
        ("r-1", "received", "Received, not looked at yet")]
    cache = R.load_cache(R.cache_path(str(tmp_path / "cfg" / "settings.json")))
    assert cache["mine"][0]["id"] == "r-1"
    # the form is remembered in settings.json, and no address anywhere
    s = json.loads((tmp_path / "cfg" / "settings.json").read_text("utf-8"))
    assert s["report"] == {"name": "Joe", "hide_paths": True}


def test_a_release_that_addresses_a_report_is_a_notice_in_the_app(
        tmp_path, worker, monkeypatch):
    from tests.webui_harness import web_app
    monkeypatch.setenv("PAD_REPORTS_URL", worker.url)
    monkeypatch.setattr(config, "REPORTS_URL", worker.url)
    # two reports this install sent earlier, one of them just shipped
    cfg = tmp_path / "cfg"
    cfg.mkdir(parents=True, exist_ok=True)
    cache = {"mine": [
        {"id": "r-a", "title": "Write stopped at 40%", "at": 1700000000,
         "state": "filed", "version": "", "message": "", "answered_at": 0,
         "seen": True},
        {"id": "r-b", "title": "No sound in attract", "at": 1700001000,
         "state": "received", "version": "", "message": "",
         "answered_at": 0, "seen": True}], "checked_at": 0}
    R.save_cache(R.cache_path(str(cfg / "settings.json")), cache)
    worker.states["r-a"] = {"state": "released", "version": "1.275.0",
                            "message": "Fixed: the write no longer stops.",
                            "answered_at": 9}
    worker.states["r-b"] = {"state": "filed"}
    with web_app(tmp_path) as w:
        # the ask at startup covers the reports with no last word yet
        assert until(w, lambda: worker.asked)
        assert worker.asked[0] == ["r-a", "r-b"]
        assert until(w, lambda: _banner(w, "report_answer") is not None)
        b = _banner(w, "report_answer")
        assert b["kind"] == "info"
        assert b["text"] == ('Your report "Write stopped at 40%" is '
                             'addressed in v1.275.0. Fixed: the write no '
                             'longer stops.')
        assert [a["id"] for a in b["actions"]] == ["view"]
        mine = {m["id"]: m for m in w.state("shellx")["report"]["mine"]}
        assert mine["r-a"]["words"] == "Addressed in v1.275.0"
        assert mine["r-a"]["seen"] is False
        assert mine["r-b"]["words"] == "Being looked at"
        assert mine["r-b"]["seen"] is True
        # the user looks: the notice goes, the news is seen, and stays so
        assert w.call("ui.banner_action", "report_answer", "dismiss")
        w.drain()
        assert _banner(w, "report_answer") is None
        assert all(m["seen"] for m in w.state("shellx")["report"]["mine"])
        saved = R.load_cache(R.cache_path(str(cfg / "settings.json")))
        assert saved["mine"][0]["state"] == "released"
        assert saved["mine"][0]["seen"] is True
        assert saved["checked_at"] > 0
        # opening the window soon after asks nothing again (the ask is fresh)
        w.call("shellx.report_open", "")
        w.drain()
        assert len(worker.asked) == 1
        # an answered report is never asked after again
        assert w.call("shellx.report_refresh") is True
        assert until(w, lambda: len(worker.asked) == 2)
        assert worker.asked[1] == ["r-b"]


def test_a_dead_line_says_so_and_the_file_is_the_fallback(app_with_worker,
                                                          tmp_path):
    w, worker = app_with_worker
    worker.stop()
    w.call("shellx.report_send", "Write stopped at 40% today", "", False)
    assert until(w, lambda: w.state("shellx")["report"]["last"] is not None)
    last = w.state("shellx")["report"]["last"]
    assert last["ok"] is False and last["offline"] is True
    assert "can't be reached" in last["error"]
    assert w.state("shellx")["report"]["mine"] == []
    out = tmp_path / "r.zip"
    w.answers.append(str(out))
    assert w.call("shellx.report_save", "Write stopped at 40% today",
                  "", False) == {"path": str(out)}
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
    w.call("shellx.report_send", "Write stopped at 40% today", "", True)
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
                   "", True)


# ------------------------------------------------------- the board (PAD-914)
def test_the_board_column_comes_from_the_tracker_or_from_the_state():
    # a service from before the board has only the state
    assert R.stage_of({"state": "received"}) == "received"
    assert R.stage_of({"state": "filed"}) == "queued"
    assert R.stage_of({"state": "released", "stage": "working"}) == "done"
    assert R.stage_of({"state": "closed"}) == "done"
    assert R.stage_of({"state": "unknown"}) == "done"
    # the tracker's stage wins while the report has no last word
    assert R.stage_of({"state": "filed", "stage": "working"}) == "working"
    assert R.stage_of({"state": "filed", "stage": "ready"}) == "ready"
    assert R.stage_of({"state": "filed", "stage": "done"}) == "queued"
    assert R.stage_of({"state": "filed", "stage": "nonsense"}) == "queued"
    e = R.board_entry({"id": "r-1", "title": "Write stopped", "at": 5,
                       "state": "filed", "stage": "working",
                       "ticket": "PAD-914", "progress": 45, "seen": False})
    assert e == {"id": "r-1", "title": "Write stopped", "at": 5,
                 "stage": "working", "state": "filed", "ticket": "PAD-914",
                 "progress": 45, "version": "", "message": "", "new": True}
    assert R.board_entry({"progress": 250})["progress"] == -1
    assert R.board_entry({"progress": None})["progress"] == -1


def test_the_install_id_is_anonymous_kept_and_named_in_the_record(tmp_path):
    path = R.cache_path(str(tmp_path / "settings.json"))
    cache = R.load_cache(path)
    i = R.install_id(cache)
    assert len(i) == 16 and int(i, 16) >= 0
    assert R.install_id(cache) == i
    R.save_cache(path, cache)
    assert R.load_cache(path)["install"] == i
    # junk on disk is not an id
    (tmp_path / "reports_cache.json").write_text(
        json.dumps({"mine": [], "install": "C:/Users/joe"}), encoding="utf-8")
    assert R.load_cache(path)["install"] == ""
    rep = _report(install=i)
    assert ("App id: %s" % i) in R.as_text(rep)
    assert R.payload(rep)["install"] == i
    assert "install" not in R.payload(_report())


def test_status_carries_the_board_and_folds_into_the_cache(worker):
    worker.states["r-1"] = {"state": "filed", "stage": "working",
                            "ticket": "PAD-914", "progress": 45}
    worker.states["r-2"] = {"state": "filed", "stage": "ready",
                            "ticket": "PAD-915", "progress": "lots"}
    rows = R.fetch_status(worker.url, config.REPORTS_APP_KEY, ["r-1", "r-2"])
    assert (rows["r-1"]["stage"], rows["r-1"]["ticket"],
            rows["r-1"]["progress"]) == ("working", "PAD-914", 45)
    assert rows["r-2"]["progress"] == -1
    cache = {"mine": [{"id": "r-1", "title": "a", "state": "filed",
                       "seen": True},
                      {"id": "r-2", "title": "b", "state": "filed",
                       "seen": True}]}
    assert R.apply_status(cache, rows) == []        # a move is not news
    by = {m["id"]: R.board_entry(m) for m in cache["mine"]}
    assert (by["r-1"]["stage"], by["r-1"]["progress"]) == ("working", 45)
    assert (by["r-2"]["stage"], by["r-2"]["ticket"]) == ("ready", "PAD-915")


def test_your_reports_board_asks_when_stale_and_shows_each_column(
        tmp_path, worker, monkeypatch):
    from tests.webui_harness import web_app
    monkeypatch.setenv("PAD_REPORTS_URL", worker.url)
    monkeypatch.setattr(config, "REPORTS_URL", worker.url)
    cfg = tmp_path / "cfg"
    cfg.mkdir(parents=True, exist_ok=True)
    R.save_cache(R.cache_path(str(cfg / "settings.json")), {"mine": [
        {"id": "r-a", "title": "Write stopped at 40%", "at": 1700000000,
         "state": "filed", "seen": True},
        {"id": "r-b", "title": "No sound in attract", "at": 1700001000,
         "state": "received", "seen": True}], "checked_at": 0})
    worker.states["r-a"] = {"state": "filed", "stage": "working",
                            "ticket": "PAD-914", "progress": 60}
    worker.states["r-b"] = {"state": "filed", "stage": "queued",
                            "ticket": ""}
    with web_app(tmp_path) as w:
        assert until(w, lambda: worker.asked)
        assert until(w, lambda: w.state("shellx")["report"]["checked_at"] > 0)
        rep = w.state("shellx")["report"]
        assert rep["checking"] is False
        board = {m["id"]: m["board"] for m in rep["mine"]}
        assert (board["r-a"]["stage"], board["r-a"]["ticket"],
                board["r-a"]["progress"]) == ("working", "PAD-914", 60)
        assert board["r-b"]["stage"] == "queued"
        # opening the board right after the ask asks nothing ...
        assert w.call("shellx.report_board_open") is True
        w.drain()
        assert len(worker.asked) == 1
        # ... and once the last ask is older than a few minutes, it asks
        svc = w.ctx.registry._methods["shellx.report_board_open"][0].__self__
        svc._rep_cache["checked_at"] = time.time() - R.BOARD_STATUS_AFTER - 5
        worker.states["r-a"] = {"state": "filed", "stage": "ready",
                                "ticket": "PAD-914"}
        assert w.call("shellx.report_board_open") is True
        assert until(w, lambda: len(worker.asked) == 2)
        assert until(w, lambda: {m["id"]: m["board"]["stage"] for m in
                                 w.state("shellx")["report"]["mine"]}["r-a"]
                     == "ready")
        # the notice's Your reports opens the board window
        opened = []
        svc._open_dialog = lambda name, **kw: opened.append(name) or True
        svc._report_banner_action("view")
        assert opened == ["reports"]


def test_a_sent_report_carries_this_apps_id(app_with_worker, tmp_path):
    w, worker = app_with_worker
    assert w.call("shellx.report_send", "Write stopped at 40% today",
                  "", True) == {"sent": True}
    assert until(w, lambda: (w.state("shellx")["report"]["last"] or {}
                             ).get("ok"))
    body = worker.posts[0][2]
    cache = R.load_cache(R.cache_path(str(tmp_path / "cfg" / "settings.json")))
    assert cache["install"] and body["install"] == cache["install"]
    assert ("App id: %s" % cache["install"]) in body["body"]
    board = w.state("shellx")["report"]["mine"][0]["board"]
    assert (board["stage"], board["ticket"], board["progress"]) == (
        "received", "", -1)


def test_the_board_script_draws_five_columns_and_escapes_the_words(tmp_path):
    """report_board.js is the one script the app and the tracker draw the
    board with: run it under node as the tracker loads it (no module)."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("no node")
    js = os.path.join(os.path.dirname(__file__), "..", "pinball_decryptor",
                      "webui", "static", "js", "report_board.js")
    entries = [
        {"id": "a", "title": "<b>Write</b> stopped", "at": 1700000000,
         "stage": "working", "state": "filed", "ticket": "PAD-914",
         "progress": 45, "version": "", "message": "", "new": False},
        {"id": "b", "title": "No sound", "at": 1700001000, "stage": "done",
         "state": "released", "ticket": "PAD-915", "progress": -1,
         "version": "1.300.0", "message": "Sound is back.", "new": True}]
    drive = tmp_path / "drive.js"
    drive.write_text(
        "globalThis.window = globalThis;\n"
        "require(%s);\n"
        "const e = %s;\n"
        "process.stdout.write(JSON.stringify({\n"
        "  board: window.PADReportBoard.html(e, {current: 'a'}),\n"
        "  empty: window.PADReportBoard.html([], {empty: 'none yet'}),\n"
        "  stages: window.PADReportBoard.STAGES.map((s) => s.key)}));\n"
        % (json.dumps(os.path.abspath(js)), json.dumps(entries)),
        encoding="utf-8")
    out = json.loads(subprocess.run([node, str(drive)], capture_output=True,
                                    text=True, check=True).stdout)
    assert out["stages"] == list(R.STAGES)
    b = out["board"]
    for label in ("Received", "In the queue", "Being worked on",
                  "Fix ready", "Done"):
        assert label in b
    assert "&lt;b&gt;Write&lt;/b&gt; stopped" in b and "<b>Write" not in b
    assert "PAD-914" in b and "45% through the work" in b
    assert "This ticket" in b
    assert "Fixed in v1.300.0" in b and "Sound is back." in b
    assert 'class="prb-card prb-new"' in b
    assert "none yet" in out["empty"]
