r"""PAD-754 proof: the paw chip and the Animal shelters window, before/after.

    python scripts/shot_pad754.py --out <dir> --tag before|after

Serves THIS tree's app (webui_shot.start_server: scratch settings, hidden,
no update check) against a stand-in for the donations Worker on localhost,
seeded with a few entries, so the chip shows a total and the window has a
list and a Top places board.  Shoots the top bar, and when the tree has the
window ("after") the window itself, then adds a donation through the form
the way a user would and shoots the result.  Run from the main export for
"before" and from the ticket worktree for "after".
"""

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

NOW = int(time.time())
ROWS = [
    {"at": NOW - 86400 * 9, "amount": 100, "currency": "USD", "shelter": "Austin Pets Alive!",
     "country": "US", "region": "Texas", "name": "", "usd": 100},
    {"at": NOW - 86400 * 6, "amount": 40, "currency": "GBP", "shelter": "Dogs Trust Leeds",
     "country": "GB", "region": "", "name": "pinhead77", "usd": 50.8},
    {"at": NOW - 86400 * 3, "amount": 20, "currency": "USD", "shelter": "local shelter",
     "country": "", "region": "", "name": "", "usd": 20},
    {"at": NOW - 3600 * 5, "amount": 50, "currency": "USD", "shelter": "Humane Society of Tampa Bay",
     "country": "US", "region": "Florida", "name": "Mike R.", "usd": 50},
    {"at": NOW - 600, "amount": 75, "currency": "CAD", "shelter": "Toronto Humane Society",
     "country": "CA", "region": "Ontario", "name": "Dana", "usd": 54.75},
]
# older entries the list no longer shows, for the map and the board
OLDER = [("US", "California", 410), ("US", "Washington", 120), ("US", "Ohio", 260),
         ("US", "Illinois", 90), ("US", "Michigan", 150), ("US", "Pennsylvania", 70),
         ("US", "Colorado", 45), ("US", "Georgia", 30), ("US", "Arizona", 25),
         ("GB", "", 180), ("DE", "", 140), ("AU", "", 95), ("NL", "", 40),
         ("SE", "", 35), ("CA", "British Columbia", 60), ("XX", "", 20)]
BASE = 4320 - sum(r["usd"] for r in ROWS)     # older entries the list no longer shows


class Fake:
    def __init__(self):
        self.rows = list(ROWS)
        self.url = ""

    def summary(self):
        total = round(BASE + sum(r["usd"] for r in self.rows), 2)
        places = {}
        for r in self.rows:
            if not r["country"]:
                continue
            p = places.setdefault((r["country"], r["region"]),
                                  {"country": r["country"], "region": r["region"], "usd": 0, "count": 0})
            p["usd"] += r["usd"]
            p["count"] += 1
        for c, reg, usd in OLDER:
            p = places.setdefault((c, reg), {"country": c, "region": reg, "usd": 0, "count": 0})
            p["usd"] += usd
            p["count"] += 1 + usd // 60
        places = sorted(places.values(), key=lambda p: -p["usd"])
        tx = next(p for p in places if p["region"] == "Texas")
        tx["usd"] += 1800                               # Texas is winning
        places.sort(key=lambda p: -p["usd"])
        return {"ok": True, "total_usd": total, "count": 56 + len(self.rows),
                "milestones": [{"usd": 100, "at": NOW - 86400 * 260},
                               {"usd": 200, "at": NOW - 86400 * 240},
                               {"usd": 500, "at": NOW - 86400 * 200},
                               {"usd": 1000, "at": NOW - 86400 * 150},
                               {"usd": 2500, "at": NOW - 86400 * 53}],
                "rates": {"USD": 1, "GBP": 1.27, "CAD": 0.73, "EUR": 1.08},
                "recent": list(reversed(self.rows))[:12], "places": places,
                "updated": NOW}

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
                if self.path.startswith("/v1/all"):
                    rows = list(reversed(fake.rows))
                    self._send(200, {"ok": True, "rows": rows, "total": 56 + len(fake.rows),
                                     "offset": 0, "limit": 100})
                    return
                self._send(200, fake.summary())

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                held = body["amount"] > 299              # the Worker's HOLD_OVER_USD
                if not held:
                    fake.rows.append({"at": NOW, "amount": body["amount"], "currency": body["currency"],
                                      "shelter": body.get("shelter", ""), "country": body.get("country", ""),
                                      "region": body.get("region", ""),
                                      "name": body.get("name", "") if body.get("show_name") else "",
                                      "usd": body["amount"]})
                out = fake.summary()
                out["id"] = "%032x" % (NOW * 7919 + len(fake.rows))
                out["token"] = "f" * 32
                out["held"] = held
                self._send(201, out)

        srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % srv.server_port
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return self


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--url", default="",
                    help="drive the app against THIS donations service (the real "
                         "worker.js under `wrangler dev --local`, or production) "
                         "instead of the seeded stand-in")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    service = args.url.rstrip("/") if args.url else Fake().start().url
    scratch = tempfile.mkdtemp(prefix="pad754-")
    proc, url = webui_shot.start_server("", scratch,
                                        extra_env={"PAD_DONATIONS_URL": service})
    errors = []
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
            page.on("console", lambda m: errors.append("console.error: %s" % m.text)
                    if m.type == "error" else None)
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            keys = [m["key"] for m in webui_shot.state(url)["shell"]["mfrs"]]
            pick = [k for k in keys if "stern" in k.lower()] or keys
            webui_shot.api(url, "ui.pick_manufacturer", pick[0])
            has = False
            for _ in range(40):
                d = webui_shot.state(url).get("shellx", {}).get("donations")
                if d and d.get("known"):
                    has = True
                    break
                time.sleep(0.25)
            time.sleep(1.5)

            def shoot(name, **kw):
                path = os.path.join(args.out, "%s_%s.png" % (args.tag, name))
                page.screenshot(path=path, **kw)
                print("shot", path, flush=True)

            shoot("topbar", clip={"x": 0, "y": 0, "width": 1440, "height": 56})
            if not has:
                print("this tree has no donations state (before)")
            else:
                webui_shot.api(url, "ui.settings_action", "donations")
                page.wait_for_selector(".sx-don", timeout=15000)
                time.sleep(1.5)
                shoot("window")
                page.fill(".sx-don-form input[placeholder='25']", "30")
                page.fill(".sx-don-form input[placeholder='Shelter (optional)']", "Lollypop Farm")
                page.select_option(".sx-don-form .sx-don-country select", "US")
                page.fill(".sx-don-form input[placeholder='State or province (optional)']", "New York")
                page.fill(".sx-don-form input[placeholder='Your name (optional)']", "David")
                page.click(".sx-don-form button:has-text('Add to the tally')")
                page.wait_for_selector(".sx-don-confirm", timeout=15000)
                time.sleep(0.6)
                shoot("confirm")
                page.click(".sx-don-form button:has-text('Yes, add it')")
                for _ in range(40):
                    d = webui_shot.state(url)["shellx"]["donations"]
                    if d["recent"] and d["recent"][0]["name"] == "David":
                        break
                    time.sleep(0.25)
                time.sleep(0.5)                       # the paw prints mid-flight
                shoot("added")
                page.wait_for_selector(".sx-don-mine-row", timeout=15000)
                time.sleep(2.5)                       # the jackpot has settled
                shoot("yours")
                if page.query_selector(".sx-don-map-pick"):     # a real service may have no US places yet
                    page.click(".sx-don-map-pick button:has-text('United States')")
                    time.sleep(0.8)
                    shoot("map_us")
                    page.click(".sx-don-map-pick button:has-text('World')")
                page.click(".modal .ft button:has-text('All donations')")
                page.wait_for_selector(".sx-don-hist", timeout=15000)
                time.sleep(1.0)
                shoot("history")
                page.click(".modal .ft button:has-text('Back')")
                time.sleep(0.5)
                # a big one: the confirm step says it is checked by hand first
                page.fill(".sx-don-form input[placeholder='25']", "500")
                page.click(".sx-don-form button:has-text('Add to the tally')")
                page.wait_for_selector(".sx-don-confirm", timeout=15000)
                time.sleep(0.6)
                shoot("confirm_big")
                page.click(".sx-don-form button:has-text('Yes, add it')")
                for _ in range(40):
                    d = webui_shot.state(url)["shellx"]["donations"]
                    if d["mine"] and d["mine"][0]["held"]:
                        break
                    time.sleep(0.25)
                time.sleep(2.5)
                shoot("held")
                webui_shot.api(url, "ui.set_theme", "light")
                time.sleep(1.5)
                shoot("light")
                page.click(".modal .ft button:has-text('Close')")
                time.sleep(0.8)
                shoot("topbar_light", clip={"x": 0, "y": 0, "width": 1440, "height": 56})
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    for e in errors:
        print("ERROR", e)
    print("%d errors; server log %s" % (len(errors), os.path.join(scratch, "server.log")))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
