"""Animal shelter donations (PAD-754): core/donations.py, and the shellx
service's window and paw chip against a stand-in for the Worker on
localhost (the real one is tools/donations_worker; its own tests run under
node).
"""

import json
import os
import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from pinball_decryptor.core import config
from pinball_decryptor.core import donations as D


# ---------------------------------------------------------- a fake Worker
class FakeWorker:
    """Answers /v1/summary and /v1/donate the way worker.js does, from a
    list in memory.  ``down`` refuses connections (the server is stopped);
    ``refuse`` answers every donate with that 4xx message."""

    def __init__(self):
        self.rows = []
        self.posts = []
        self.gets = []
        self.deletes = []
        self.refuse = None
        self.key = None
        self._srv = None
        self.url = ""

    def summary(self):
        total = round(sum(r["usd"] for r in self.rows), 2)
        return {"ok": True, "total_usd": total, "count": len(self.rows),
                "milestones": [{"usd": 500, "at": 1700000000}] if total >= 500 else [],
                "recent": list(reversed(self.rows))[:12],
                "places": [{"country": "US", "region": "Texas",
                            "usd": total, "count": len(self.rows)}]
                if self.rows else [],
                "updated": int(time.time())}

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
                fake.gets.append((self.path,
                                  {k.lower(): v for k, v in self.headers.items()}))
                if self.path == "/v1/summary":
                    self._send(200, fake.summary())
                elif self.path.startswith("/v1/all"):
                    from urllib.parse import parse_qs, urlsplit
                    q = parse_qs(urlsplit(self.path).query)
                    off = int(q.get("offset", ["0"])[0])
                    lim = int(q.get("limit", ["100"])[0])
                    rows = list(reversed(fake.rows))
                    self._send(200, {"ok": True, "rows": rows[off:off + lim],
                                     "total": len(rows), "offset": off, "limit": lim})
                else:
                    self._send(404, {"ok": False, "error": "Not found."})

            def do_DELETE(self):
                fake.deletes.append((self.path,
                                     {k.lower(): v for k, v in self.headers.items()}))
                rid = self.path.rsplit("/", 1)[-1]
                row = next((r for r in fake.rows if r.get("id") == rid), None)
                if row is None or self.headers.get("X-PAD-Edit") != row["token"]:
                    self._send(404, {"ok": False, "error": "No such donation."})
                    return
                fake.rows.remove(row)
                out = fake.summary()
                out["id"] = rid
                self._send(200, out)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                fake.posts.append(({k.lower(): v for k, v in self.headers.items()},
                                   body))
                if fake.key and self.headers.get("X-PAD-Key") != fake.key:
                    self._send(403, {"ok": False, "error": "Not from the app."})
                    return
                if fake.refuse:
                    self._send(429, {"ok": False, "error": fake.refuse})
                    return
                usd = body["amount"] * {"USD": 1, "GBP": 1.27}.get(body["currency"], 1)
                rid = "x%d" % (len(fake.posts))
                fake.rows.append({"id": rid, "token": "t" * 31 + rid[-1],
                                  "at": int(time.time()), "amount": body["amount"],
                                  "currency": body["currency"],
                                  "shelter": body.get("shelter", ""),
                                  "country": body.get("country", ""),
                                  "region": body.get("region", ""),
                                  "name": body.get("name", "") if body.get("show_name") else "",
                                  "usd": usd})
                out = fake.summary()
                out["id"] = rid
                out["token"] = fake.rows[-1]["token"]
                self._send(201, out)

        self._srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self._srv.server_port
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
    yield w
    w.stop()


# ------------------------------------------------------------------ entry
def test_the_entry_is_cleaned_and_bounded():
    e = D.validate_entry("$25", "usd", "  Humane   Society ", " Mike  R ", True,
                         app_version="1.265.0", country="us", region=" Texas ")
    assert e == {"amount": 25.0, "currency": "USD", "shelter": "Humane Society",
                 "country": "US", "region": "Texas", "name": "Mike R",
                 "show_name": True, "app_version": "1.265.0"}
    assert D.validate_entry("1,000.50", "GBP")["amount"] == 1000.5
    assert D.validate_entry("€12", "EUR")["amount"] == 12.0
    assert D.validate_entry("5", country="ZZ", region="Mars")["country"] == ""
    assert D.validate_entry("5", country="ZZ", region="Mars")["region"] == ""
    assert len(D.validate_entry("5", name="x" * 99)["name"]) == D.MAX_NAME


@pytest.mark.parametrize("amount,currency,words", [
    ("", "USD", "Enter the amount"),
    ("0", "USD", "Enter the amount"),
    ("-5", "USD", "Enter the amount"),
    ("lots", "USD", "Enter the amount"),
    ("10001", "USD", "more than one entry"),
    ("5", "XXX", "Unknown currency"),
])
def test_a_bad_entry_says_why(amount, currency, words):
    with pytest.raises(ValueError, match=words):
        D.validate_entry(amount, currency)


# ---------------------------------------------------------------- figures
def test_the_ladder_and_the_money_words():
    assert D.next_milestone(0) == 100
    assert D.next_milestone(100) == 200
    assert D.next_milestone(500) == 1000
    assert D.next_milestone(4320) == 5000
    assert D.next_milestone(2_000_000) is None
    assert D.last_milestone(4320) == 2500
    assert D.last_milestone(12) == 0
    assert D.fmt_usd(4320.4) == "$4,320"
    assert D.fmt_usd(None) == "$0"
    assert D.fmt_amount(40, "GBP") == "£40"
    assert D.fmt_amount(12.5, "EUR") == "€12.50"
    assert D.fmt_amount(25, "CAD") == "CA$25"
    assert D.fmt_amount(3, "QQQ") == "QQQ 3"
    assert D.fmt_place("US", "Texas") == "Texas, US"
    assert D.fmt_place("gb") == "United Kingdom"
    assert D.fmt_place("CA", "Ontario") == "Ontario, Canada"
    assert D.fmt_place("", "Texas") == ""
    assert D.fmt_place("ZZ", "x") == ""
    assert D.fmt_date(0)                         # some day, never raises
    assert D.fmt_date("junk") == ""


def test_states_are_matched_by_code_or_name():
    assert D.state_code("Texas") == "TX"
    assert D.state_code(" tx. ") == "TX"
    assert D.state_code("new york") == "NY"
    assert D.state_code("Washington, D.C.") == "DC"
    assert D.state_code("Ontario") == ""
    assert D.state_code("") == ""
    assert len(D.US_STATES) == 51


def test_the_map_lights_countries_states_and_elsewhere():
    places = [{"country": "US", "region": "Texas", "usd": 1200, "count": 9},
              {"country": "US", "region": "tx", "usd": 100, "count": 1},
              {"country": "US", "region": "", "usd": 50, "count": 2},
              {"country": "US", "region": "Mars", "usd": 5, "count": 1},
              {"country": "GB", "region": "", "usd": 51, "count": 1},
              {"country": "XX", "region": "Orbit", "usd": 9, "count": 1},
              {"country": "ZZ", "region": "", "usd": 999, "count": 1},
              "junk"]
    m = D.map_data(places)
    assert [(w["code"], w["usd"], w["count"], w["amount"]) for w in m["world"]] == [
        ("US", 1355, 13, "$1,355"), ("GB", 51, 1, "$51")]
    assert m["world"][0]["label"] == "United States"
    assert [(s["code"], s["label"], s["usd"], s["count"]) for s in m["us"]] == [
        ("TX", "Texas", 1300, 10)]
    assert m["elsewhere"] == {"usd": 9, "count": 1, "amount": "$9"}
    assert D.map_data([])["elsewhere"] is None
    assert D.view(None)["map"] == {"world": [], "us": [], "elsewhere": None}


def test_history_rows_read_like_the_list():
    rows = D.history_rows([
        {"at": 1725000000, "amount": 40, "currency": "GBP", "shelter": "Dogs Trust",
         "country": "GB", "region": "", "name": "pinhead77"},
        {"at": "junk", "amount": 5, "currency": "USD", "name": ""},
        "junk"])
    assert rows[0]["date"] == D.fmt_date_full(1725000000)
    assert rows[0]["date"].endswith(", 2024")
    assert (rows[0]["name"], rows[0]["where"], rows[0]["amount"]) == ("pinhead77", "United Kingdom", "£40")
    assert (rows[1]["date"], rows[1]["name"], rows[1]["where"]) == ("", "Anonymous", "")
    assert len(rows) == 2


def test_the_view_before_any_total():
    v = D.view(None)
    assert v["known"] is False
    assert v["chip"] == "Animal shelters"
    assert v["total_text"] == "—"
    assert v["pct"] == 0 and v["next_text"] == "$100"
    assert v["recent"] == [] and v["places"] == [] and v["reached_text"] is None
    assert v["currency"] == "USD" and v["country"] == ""
    assert v["countries"][0] == {"value": "", "label": "Country (optional)"}


def test_the_view_of_a_total():
    summary = {
        "total_usd": 4320, "count": 61,
        "milestones": [{"usd": 500, "at": 1700000000}, {"usd": 2500, "at": 1725000000}],
        "recent": [
            {"amount": 50, "currency": "USD", "shelter": "Humane Society of Tampa Bay",
             "name": "Mike R.", "country": "US", "region": "Florida"},
            {"amount": 40, "currency": "GBP", "shelter": "", "name": "", "country": "GB"},
            "junk",
        ],
        "places": [{"country": "US", "region": "Texas", "usd": 1200.5, "count": 9},
                   {"country": "", "region": "x", "usd": 5, "count": 1}],
        "rates": {"USD": 1, "GBP": 1.27, "XX": "junk"},
    }
    v = D.view(summary, pending=[{"amount": 20, "currency": "USD"}],
               currency="GBP", name="pinhead77", country="US", region="Texas")
    assert v["known"] and v["total_text"] == "$4,320" and v["count"] == 61
    assert v["count_text"] == "61 donations"
    assert v["pct"] == 73                        # (4320-2500)/(5000-2500)
    assert v["next_text"] == "$5,000"
    assert v["total_usd"] == 4320 and v["last_text"] == "$2.5k"
    assert [(c["text"], c["state"]) for c in v["ladder"]] == [
        ("$1k", "reached"), ("$2.5k", "reached"), ("$5k", "next"),
        ("$10k", "ahead"), ("$25k", "ahead")]
    assert v["ladder"][1]["date"] == D.fmt_date(1725000000)
    assert v["ladder"][0]["date"] == ""          # fell, but the service didn't say when
    assert v["ladder"][2]["date"] == ""
    assert D.fmt_short(500) == "$500" and D.fmt_short(2500) == "$2.5k"
    assert D.fmt_short(100000) == "$100k" and D.fmt_short(1000000) == "$1M"
    assert [(c["text"], c["state"]) for c in D.view(None)["ladder"]] == [("$100", "next"), ("$200", "ahead"), ("$500", "ahead")]
    assert D.view(None)["hold_over"] == 299 and D.view(None)["rates"] == {}
    assert [c["text"] for c in D.view({"total_usd": 5_000_000, "count": 1})["ladder"]] == ["$500k", "$1M"]
    assert v["reached_text"].startswith("$2,500 reached ")
    assert v["recent"] == [
        {"name": "Mike R.", "shelter": "Humane Society of Tampa Bay",
         "where": "Florida, US", "amount": "$50"},
        {"name": "Anonymous", "shelter": "", "where": "United Kingdom", "amount": "£40"},
    ]
    assert v["places"] == [{"where": "Texas, US", "usd": 1200.5, "count": 9,
                            "amount": "$1,200"}]
    assert v["pending"] == 1 and v["pending_usd"] == 20
    assert v["rates"] == {"USD": 1, "GBP": 1.27}
    assert v["chip"] == "$4,320 to shelters"
    assert "61 donations" in v["tip"]
    assert (v["currency"], v["name"], v["country"], v["region"]) == \
        ("GBP", "pinhead77", "US", "Texas")
    assert D.view({"total_usd": 1, "count": 1})["count_text"] == "1 donation"
    assert D.view({"total_usd": 5_000_000, "count": 1})["pct"] == 100
    assert D.view({"total_usd": 5_000_000, "count": 1})["next_text"] == ""


# ------------------------------------------------------------------ cache
def test_the_cache_round_trips_and_shrugs_at_junk(tmp_path):
    path = D.cache_path(str(tmp_path / "cfg" / "settings.json"))
    assert path == str(tmp_path / "cfg" / "donations_cache.json")
    assert D.load_cache(path) == {"summary": None, "fetched_at": 0.0, "pending": [],
                                  "mine": []}
    cache = {"summary": {"total_usd": 5, "count": 1}, "fetched_at": 12.5,
             "pending": [{"amount": 1, "currency": "USD"}, "junk"]}
    D.save_cache(path, cache)
    back = D.load_cache(path)
    assert back["summary"] == {"total_usd": 5, "count": 1}
    assert back["fetched_at"] == 12.5
    assert back["pending"] == [{"amount": 1, "currency": "USD"}]
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert D.load_cache(path)["summary"] is None
    with open(path, "w", encoding="utf-8") as f:
        f.write("[1, 2]")
    assert D.load_cache(path)["pending"] == []


# ------------------------------------------------------------------- wire
def test_fetch_and_submit_talk_to_the_worker(worker):
    assert D.fetch_summary(worker.url)["total_usd"] == 0
    entry = D.validate_entry("40", "GBP", "Dogs Trust", "pinhead77", True,
                             country="GB")
    out = D.submit(worker.url, "k", entry)
    assert out["ok"] and out["count"] == 1 and out["total_usd"] == 50.8
    headers, body = worker.posts[0]
    assert headers["x-pad-key"] == "k"
    assert body == entry
    assert D.fetch_summary(worker.url)["recent"][0]["name"] == "pinhead77"


def test_an_entry_can_be_taken_back_with_its_token(worker):
    out = D.submit(worker.url, "k", D.validate_entry("300", shelter="typo"))
    assert out["id"] and out["token"]
    with pytest.raises(D.DonationsError, match="No such donation"):
        D.remove(worker.url, "k", out["id"], "wrong")
    back = D.remove(worker.url, "k", out["id"], out["token"])
    assert back["ok"] and back["count"] == 0 and back["id"] == out["id"]
    assert worker.deletes[-1][1]["x-pad-edit"] == out["token"]
    assert worker.deletes[-1][1]["x-pad-key"] == "k"
    with pytest.raises(D.DonationsError):
        D.remove(worker.url, "k", out["id"], out["token"])      # already gone


def test_own_entries_are_listed_newest_first_with_the_pending_ones_on_top():
    sent = [{"id": "a", "token": "ta", "entry": D.validate_entry("5", country="US", region="Ohio")},
            {"id": "b", "token": "tb", "entry": D.validate_entry("7", "GBP", "Dogs Trust", "Pat")}]
    pend = [D.validate_entry("9", shelter="later")]
    rows = D.view({"total_usd": 0, "count": 0}, pending=pend, mine=sent)["mine"]
    assert [(r["key"], r["pending"], r["amount"]) for r in rows] == [
        ("pending:0", True, "$9"), ("b", False, "£7"), ("a", False, "$5")]
    assert rows[2]["where"] == "Ohio, US" and rows[1]["name"] == "Pat"
    assert rows[0]["entry"]["shelter"] == "later"
    assert set(rows[1]["entry"]) == {"amount", "currency", "shelter", "country",
                                      "region", "name", "show_name"}


def test_every_donation_can_be_paged(worker):
    for i in range(5):
        D.submit(worker.url, "k", D.validate_entry(str(10 + i), name="n%d" % i))
    page = D.fetch_all(worker.url, 0, 2)
    assert page["total"] == 5 and [r["amount"] for r in page["rows"]] == [14, 13]
    page = D.fetch_all(worker.url, 4, 2)
    assert [r["amount"] for r in page["rows"]] == [10]
    with pytest.raises(D.DonationsError, match="configured"):
        D.fetch_all("")


def test_the_wire_tells_a_refusal_from_a_dead_line(worker):
    worker.refuse = "Too many in one hour. Try again later."
    with pytest.raises(D.DonationsError, match="Too many in one hour"):
        D.submit(worker.url, "k", D.validate_entry("5"))
    worker.refuse = None
    worker.key = "right"
    with pytest.raises(D.DonationsError, match="Not from the app"):
        D.submit(worker.url, "wrong", D.validate_entry("5"))
    url = worker.url
    worker.stop()
    with pytest.raises(urllib.error.URLError):
        D.submit(url, "k", D.validate_entry("5"), timeout=2)
    with pytest.raises(urllib.error.URLError):
        D.fetch_summary(url, timeout=2)
    with pytest.raises(D.DonationsError, match="configured"):
        D.fetch_summary("")


def test_flush_drops_a_refused_entry_and_keeps_the_rest_when_the_line_dies(worker):
    good = D.validate_entry("5")
    worker.refuse = "No."
    remaining, summary = D.flush_pending(worker.url, "k", [good, good])
    assert remaining == [] and summary is None
    worker.refuse = None
    remaining, summary = D.flush_pending(worker.url, "k", [good, good])
    assert remaining == [] and summary["count"] == 2
    url = worker.url
    worker.stop()
    remaining, summary = D.flush_pending(url, "k", [good, good], timeout=2)
    assert remaining == [good, good] and summary is None


# ---------------------------------------------------------------- service
def until(w, pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.05)
    return False


def settings_of(tmp_path):
    return json.loads((tmp_path / "cfg" / "settings.json").read_text(
        encoding="utf-8"))


@pytest.fixture
def app_with_worker(tmp_path, worker, monkeypatch):
    from tests.webui_harness import web_app
    monkeypatch.setenv("PAD_DONATIONS_URL", worker.url)
    monkeypatch.setattr(config, "DONATIONS_URL", worker.url)
    with web_app(tmp_path) as w:
        yield w, worker


def test_the_chip_fills_from_the_worker_at_startup(app_with_worker, tmp_path):
    w, worker = app_with_worker
    assert until(w, lambda: w.state("shellx")["donations"]["known"])
    d = w.state("shellx")["donations"]
    assert d["chip"] == "$0 to shelters" and d["offline"] is False
    cache = D.load_cache(D.cache_path(str(tmp_path / "cfg" / "settings.json")))
    assert cache["summary"]["ok"] is True
    gear = [it.get("id") for it in w.state("shell")["settings_items"]]
    assert "donations" in gear
    assert w.call("ui.settings_action", "donations")


def test_a_donation_goes_up_and_the_form_is_remembered(app_with_worker, tmp_path):
    w, worker = app_with_worker
    assert until(w, lambda: w.state("shellx")["donations"]["known"])
    from pinball_decryptor.webui.rpc import RpcError
    with pytest.raises(RpcError, match="Enter the amount"):
        w.call("shellx.donations_submit", "", "USD")
    assert worker.posts == []
    r = w.call("shellx.donations_submit", "50", "usd", "Humane Society",
               "Mike", True, "US", "Florida")
    assert r == {"sent": True}
    assert until(w, lambda: w.state("shellx")["donations"]["count"] == 1)
    d = w.state("shellx")["donations"]
    assert d["total_text"] == "$50" and d["chip"] == "$50 to shelters"
    assert d["recent"][0] == {"name": "Mike", "shelter": "Humane Society",
                              "where": "Florida, US", "amount": "$50"}
    assert d["places"][0]["where"] == "Texas, US"       # the fake's board
    assert worker.posts[0][1]["app_version"]
    assert (d["currency"], d["name"], d["country"], d["region"]) == \
        ("USD", "Mike", "US", "Florida")
    s = settings_of(tmp_path)["donations"]
    assert (s["currency"], s["name"], s["country"]) == ("USD", "Mike", "US")


def test_an_unreachable_total_keeps_the_entry_and_sends_it_later(app_with_worker, tmp_path):
    w, worker = app_with_worker
    assert until(w, lambda: w.state("shellx")["donations"]["known"])
    worker.stop()
    assert w.call("shellx.donations_submit", "20", "USD") == {"sent": True}
    assert until(w, lambda: w.state("shellx")["donations"]["pending"] == 1)
    assert w.state("shellx")["donations"]["offline"] is True
    path = D.cache_path(str(tmp_path / "cfg" / "settings.json"))
    assert D.load_cache(path)["pending"][0]["amount"] == 20
    # back up: Refresh flushes it
    worker.start()
    monkey_url = worker.url
    config.DONATIONS_URL = monkey_url
    assert w.call("shellx.donations_refresh")
    assert until(w, lambda: w.state("shellx")["donations"]["pending"] == 0)
    assert len(worker.posts) == 1 and worker.posts[0][1]["amount"] == 20
    assert w.state("shellx")["donations"]["count"] == 1
    assert D.load_cache(path)["pending"] == []


def test_a_sent_entry_is_yours_and_can_be_taken_back(app_with_worker, tmp_path):
    w, worker = app_with_worker
    assert until(w, lambda: w.state("shellx")["donations"]["known"])
    w.call("shellx.donations_submit", "300", "USD", "Lollypop Farm", "David", True,
           "US", "New York")
    assert until(w, lambda: w.state("shellx")["donations"]["mine"])
    mine = w.state("shellx")["donations"]["mine"]
    assert len(mine) == 1 and mine[0]["amount"] == "$300" and not mine[0]["pending"]
    path = D.cache_path(str(tmp_path / "cfg" / "settings.json"))
    cached = D.load_cache(path)["mine"]
    assert cached[0]["id"] == mine[0]["key"] and cached[0]["token"]
    from pinball_decryptor.webui.rpc import RpcError
    with pytest.raises(RpcError, match="already gone"):
        w.call("shellx.donations_remove", "nope")
    entry = w.call("shellx.donations_remove", mine[0]["key"])
    assert entry["amount"] == 300 and entry["shelter"] == "Lollypop Farm"
    assert until(w, lambda: not w.state("shellx")["donations"]["mine"])
    assert w.state("shellx")["donations"]["count"] == 0
    assert worker.deletes and D.load_cache(path)["mine"] == []
    # a pending one is dropped here, with its fields handed back the same way
    worker.stop()
    w.call("shellx.donations_submit", "20", "USD", "later")
    assert until(w, lambda: w.state("shellx")["donations"]["pending"] == 1)
    assert w.state("shellx")["donations"]["mine"][0]["key"] == "pending:0"
    assert w.call("shellx.donations_remove", "pending:0")["shelter"] == "later"
    w.drain()
    assert w.state("shellx")["donations"]["pending"] == 0
    assert D.load_cache(path)["pending"] == []


def test_the_window_pages_through_every_donation(app_with_worker):
    w, worker = app_with_worker
    assert until(w, lambda: w.state("shellx")["donations"]["known"])
    for i in range(3):
        D.submit(worker.url, "k", D.validate_entry(str(10 + i), name="n%d" % i,
                                                   country="US", region="Ohio"))
    page = w.call("shellx.donations_history", 0)
    assert page["total"] == 3 and page["next"] is None
    assert [r["amount"] for r in page["rows"]] == ["$12", "$11", "$10"]
    assert page["rows"][0]["where"] == "Ohio, US" and page["rows"][0]["date"]
    url = worker.url
    worker.stop()
    from pinball_decryptor.webui.rpc import RpcError
    with pytest.raises(RpcError, match="Couldn't reach the list"):
        w.call("shellx.donations_history", 0)


def test_a_refused_entry_is_not_kept(app_with_worker):
    w, worker = app_with_worker
    assert until(w, lambda: w.state("shellx")["donations"]["known"])
    worker.refuse = "Too many in one hour. Try again later."
    assert w.call("shellx.donations_submit", "20", "USD") == {"sent": True}
    assert until(w, lambda: len(worker.posts) == 1)
    w.drain()
    time.sleep(0.2)
    w.drain()
    assert w.state("shellx")["donations"]["pending"] == 0


def test_the_window_opens_once_after_the_first_card_write(app_with_worker, tmp_path):
    w, worker = app_with_worker
    assert w.run(w.window.note_card_written) is True
    assert settings_of(tmp_path)["donations"]["prompted"] is True
    assert w.run(w.window.note_card_written) is False


def test_no_service_configured_means_no_network_and_a_kept_entry(tmp_path, monkeypatch):
    from tests.webui_harness import web_app
    monkeypatch.delenv("PAD_DONATIONS_URL", raising=False)
    monkeypatch.setattr(config, "DONATIONS_URL", "")
    with web_app(tmp_path) as w:
        d = w.state("shellx")["donations"]
        assert d["known"] is False and d["chip"] == "Animal shelters"
        assert w.call("shellx.donations_submit", "5", "USD") == {"sent": False}
        w.drain()
        assert w.state("shellx")["donations"]["pending"] == 1
        assert w.call("shellx.donations_refresh") is False


def test_every_request_names_the_app_not_python(worker):
    """Cloudflare's browser integrity check answers Python's default agent
    with 403 (error 1010); the deployed Worker proved it on 2026-10-27."""
    url = worker.url
    D.fetch_summary(url)
    D.fetch_all(url, 0, 5)
    out = D.submit(url, "k", D.validate_entry("3"))
    D.remove(url, "k", out["id"], out["token"])
    seen = [h for _, h in worker.gets] + [h for h, _ in worker.posts]         + [h for _, h in worker.deletes]
    assert len(seen) >= 4
    for h in seen:
        assert h.get("user-agent") == D.USER_AGENT, h.get("user-agent")
