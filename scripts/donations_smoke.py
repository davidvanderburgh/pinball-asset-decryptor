r"""Prove the animal shelter donations service end to end (PAD-754).

    python scripts/donations_smoke.py https://pad-donations.<account>.workers.dev
    python scripts/donations_smoke.py http://127.0.0.1:8787          # wrangler dev --local
    python scripts/donations_smoke.py <url> --admin <ADMIN_KEY>      # also the review route

Runs the APP'S OWN client code (core/donations.py: the same calls the
window makes) against the service at <url>, with the app key from
core/config.py, and checks every answer:

  1. the summary answers;
  2. a $1 entry (shelter "smoke test") is added and shows in the summary;
  3. it is taken back with its token and is gone;
  4. an entry over the review threshold is HELD (not counted) and, with
     --admin, hidden again through the review route;
  5. the All donations page answers.

Nothing it adds is left behind.  Exit status 0 means every step held; the
first failing step prints what it saw and exits 1.  Run it once right after
`wrangler deploy` and once more after a release, from an installed app's
Python if you like (python -I is fine; it needs only the repo on sys.path).
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pinball_decryptor.core import config, donations  # noqa: E402
from pinball_decryptor.core.net import urlopen  # noqa: E402


def step(n, text):
    print("%d. %s" % (n, text), flush=True)


def fail(text):
    print("   FAILED: " + text)
    sys.exit(1)


def admin(url, method, path, key, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url.rstrip("/") + path, data=data, method=method,
                                 headers={"X-PAD-Admin": key, "Content-Type": "application/json",
                                          "Accept": "application/json",
                                          "User-Agent": donations.USER_AGENT})
    with urlopen(req, 15) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--key", default=config.DONATIONS_APP_KEY,
                    help="the app key (default: the one the app ships with)")
    ap.add_argument("--admin", default="", help="ADMIN_KEY: also prove the review route")
    a = ap.parse_args()
    url = a.url.rstrip("/")
    print("service:", url)
    print("app key:", a.key[:4] + "..." if a.key else "(none)")

    step(1, "the summary answers")
    try:
        s0 = donations.fetch_summary(url)
    except Exception as e:                                # noqa: BLE001
        fail("fetch_summary: %r" % (e,))
    print("   total $%s, %d donations, %d milestones, %d recent, %d places"
          % (s0["total_usd"], s0["count"], len(s0.get("milestones") or ()),
             len(s0.get("recent") or ()), len(s0.get("places") or ())))

    step(2, "a $1 entry is added and shows in the summary")
    entry = donations.validate_entry("1", "USD", "smoke test", "smoke", True,
                                     app_version="smoke", country="US", region="Ohio")
    try:
        s1 = donations.submit(url, a.key, entry)
    except donations.DonationsError as e:
        fail("the service refused it: %s (wrong app key? rate limit?)" % e)
    except Exception as e:                                # noqa: BLE001
        fail("submit: %r" % (e,))
    if not s1.get("id") or not s1.get("token"):
        fail("no id/token in the answer: %s" % json.dumps(s1)[:300])
    if s1.get("held"):
        fail("a $1 entry came back held")
    if s1["count"] != s0["count"] + 1:
        fail("count went %s -> %s, expected +1" % (s0["count"], s1["count"]))
    if abs(s1["total_usd"] - s0["total_usd"] - 1) > 0.011:
        fail("total went %s -> %s, expected +1" % (s0["total_usd"], s1["total_usd"]))
    top = (s1.get("recent") or [{}])[0]
    if top.get("shelter") != "smoke test" or top.get("name") != "smoke":
        fail("the newest recent row is not ours: %s" % json.dumps(top))
    print("   id %s, count %d, total $%s" % (s1["id"], s1["count"], s1["total_usd"]))
    s1b = donations.fetch_summary(url)
    if s1b["count"] != s1["count"]:
        fail("a fresh GET disagrees with the POST's answer (%s vs %s)" % (s1b["count"], s1["count"]))

    step(3, "it is taken back with its token and is gone")
    try:
        s2 = donations.remove(url, a.key, s1["id"], s1["token"])
    except Exception as e:                                # noqa: BLE001
        fail("remove: %r" % (e,))
    if s2["count"] != s0["count"] or abs(s2["total_usd"] - s0["total_usd"]) > 0.011:
        fail("after removal count/total are %s/%s, expected %s/%s"
             % (s2["count"], s2["total_usd"], s0["count"], s0["total_usd"]))
    try:
        donations.remove(url, a.key, s1["id"], s1["token"])
        fail("removing it twice should be refused")
    except donations.DonationsError:
        pass
    print("   gone")

    step(4, "an entry over $%d is held, not counted" % donations.HOLD_OVER_USD)
    big = donations.validate_entry(str(donations.HOLD_OVER_USD + 1), "USD", "smoke test big",
                                   "smoke", True, app_version="smoke")
    try:
        s3 = donations.submit(url, a.key, big)
    except Exception as e:                                # noqa: BLE001
        fail("submit (big): %r" % (e,))
    if not s3.get("held"):
        fail("a $%d entry was not held" % (donations.HOLD_OVER_USD + 1))
    if s3["count"] != s0["count"]:
        fail("a held entry changed the count (%s -> %s)" % (s0["count"], s3["count"]))
    print("   held, id %s" % s3["id"])
    if a.admin:
        try:
            rows = admin(url, "GET", "/v1/admin/list", a.admin)["rows"]
        except urllib.error.HTTPError as e:
            fail("admin list: HTTP %s (wrong ADMIN_KEY?)" % e.code)
        mine = [r for r in rows if r["id"] == s3["id"]]
        if not mine or mine[0]["held"] != 1:
            fail("the admin list does not show it held")
        out = admin(url, "POST", "/v1/admin/review/" + s3["id"], a.admin, {"approve": False})
        if not out.get("ok"):
            fail("review (hide) answered %s" % json.dumps(out))
        print("   seen held in the admin list and hidden through review")
    else:
        # no admin key: the app's own token takes it back instead
        donations.remove(url, a.key, s3["id"], s3["token"])
        print("   taken back with its token (pass --admin to prove the review route)")
    s4 = donations.fetch_summary(url)
    if s4["count"] != s0["count"]:
        fail("count is %s after clean-up, expected %s" % (s4["count"], s0["count"]))

    step(5, "the All donations page answers")
    try:
        page = donations.fetch_all(url, 0, 5)
    except Exception as e:                                # noqa: BLE001
        fail("fetch_all: %r" % (e,))
    if page.get("total") != s0["count"] or len(page.get("rows") or ()) > 5:
        fail("page: total %s (expected %s), %d rows" % (page.get("total"), s0["count"],
                                                        len(page.get("rows") or ())))
    print("   total %d, first page %d rows" % (page["total"], len(page["rows"])))
    print("ALL GOOD: the service at %s behaves, through the app's own client." % url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
