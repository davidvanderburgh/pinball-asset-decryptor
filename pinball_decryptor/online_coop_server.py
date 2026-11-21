"""The online co-op server: every machine's games added up per team, the campaign's map drawn, Discord told (PAD-1479;
docs/plans/pad1479-online-coop.md, plugins/stern/online_coop.py).

Each PAD-built card in an online co-op campaign posts its game's report here at the end of every game (the score
feed's JSON, PAD-1204, with the campaign, team, machine, join key and the game's online counts). This server checks
the report is for its campaign, counts the game toward the machine's team and hands out the campaign's regions:

* teams race for ONE region at a time, the regions in the design's order. Each counted game adds its points to its
  team's progress on the open region; the first team whose progress reaches the region's target takes it, and every
  team then starts again from nothing on the next one (the taker's points past the target carry over). With one team
  (the vanilla campaign) that is a row of goals of rising size, one after the other.
* a game's points: the design's goal ``score`` counts the game's score - once for a co-op game (every player shows the
  same team score), every player's for any other (they all played on this machine's team); goal ``count`` counts the
  report's online count of that name.
* a report sent again (the machine heard no answer and tried again) is counted once.

It answers ``POST /`` (any path) with 200 when it counted the game, 202 when it took a report it does not count (no
points), 400 for one it cannot read, 403 for another campaign's or a wrong join key. ``GET /`` is a status page,
``GET /map.png`` the map, ``GET /state.json`` the totals. With ``--webhook`` (a Discord channel's webhook address) it
posts the map there as a region is taken, when the campaign is won, and every ``--post-every`` games.

    python -m pinball_decryptor.online_coop_server --campaign campaign.json --port 8090 [--state state.json]
        [--webhook https://discord.com/api/webhooks/...] [--post-every 25]

The machines post plain http:// to an IPv4 address and look no names up: run it on a computer with a fixed public
IPv4 address (a small cloud server), or on a home computer with the port forwarded from the router. Python 3.9+;
Pillow draws the map (without it the status page and Discord's words still work)."""
import argparse
import io
import json
import math
import os
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SOURCE = "PAD score feed"
#: a report's largest body, and a game's largest score or count the server believes
BODY_MAX = 16384
POINTS_MAX = 10 ** 13
#: reports kept per machine to tell a resend from a new game
SEEN_MAX = 64
LOG_MAX = 200


class CampaignError(ValueError):
    """A campaign file this server cannot run."""


def load_campaign(path):
    """The campaign file (online_coop.campaign_file), checked."""
    from .plugins.stern import online_coop as OC
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError) as e:
        raise CampaignError("cannot read the campaign file %s: %s" % (path, e)) from None
    why = OC.design_problems(c) + [OC.word_problem("campaign", c.get("campaign"))]
    why = [w for w in why if w]
    if why:
        raise CampaignError("the campaign file %s: %s" % (path, " ".join(why)))
    return c


def fresh_state(campaign):
    """The state of a campaign no game has been played in."""
    return {"campaign": campaign["campaign"], "games": 0, "started": int(time.time()), "won_by": None,
            "teams": {t["name"]: {"total": 0, "progress": 0, "games": 0, "regions": 0, "counts": {}}
                      for t in campaign["teams"]},
            "regions": [{"name": r["name"], "target": r["target"], "owner": None, "taken": None}
                        for r in campaign["regions"]],
            "machines": {}, "log": []}


def fit_state(state, campaign):
    """*state* (read back from its file) fitted to *campaign*: a team or region the design gained starts from nothing,
    one it lost is dropped."""
    s = fresh_state(campaign)
    if not isinstance(state, dict):
        return s
    for k in ("games", "started", "won_by", "machines", "log"):
        if k in state:
            s[k] = state[k]
    for name, t in (state.get("teams") or {}).items():
        if name in s["teams"] and isinstance(t, dict):
            s["teams"][name].update({k: t[k] for k in ("total", "progress", "games", "regions", "counts") if k in t})
    old = {r.get("name"): r for r in state.get("regions") or [] if isinstance(r, dict)}
    for r in s["regions"]:
        o = old.get(r["name"])
        if o and o.get("owner") in s["teams"]:
            r["owner"], r["taken"] = o["owner"], o.get("taken")
    return s


def game_points(report, goal):
    """What *report* adds for the campaign's *goal*: the score (once in a co-op game, every player's otherwise), or the
    online count the goal names. 0 for a report with nothing to count."""
    if goal.get("kind") == "count":
        n = (report.get("counts") or {}).get(goal.get("count"))
        return n if isinstance(n, int) and not isinstance(n, bool) and 0 < n <= POINTS_MAX else 0
    scores = [s for s in report.get("scores") or [] if isinstance(s, int) and not isinstance(s, bool) and s >= 0]
    if not scores:
        return 0
    pts = max(scores) if report.get("game_type") == "cooperation" else sum(scores)
    return pts if pts <= POINTS_MAX else 0


def report_counts(report):
    """The report's online counts the server believes: {name: n} (whole numbers, 0 < n <= POINTS_MAX)."""
    raw = report.get("counts") if isinstance(report.get("counts"), dict) else {}
    return {str(k)[:23]: v for k, v in list(raw.items())[:8]
            if isinstance(v, int) and not isinstance(v, bool) and 0 < v <= POINTS_MAX}


def open_region(state):
    """The index of the region being raced for, or None when every one is taken."""
    for i, r in enumerate(state["regions"]):
        if r["owner"] is None:
            return i
    return None


class Campaign:
    """A campaign's state and the rules that move it, safe to call from the server's threads."""

    def __init__(self, campaign, state_path=None, clock=time.time):
        self.c = campaign
        self.path = state_path
        self.clock = clock
        self.lock = threading.Lock()
        state = None
        if state_path and os.path.exists(state_path):
            try:
                with open(state_path, encoding="utf-8") as f:
                    state = json.load(f)
            except (OSError, ValueError):
                state = None
        self.s = fit_state(state, campaign)

    # ---- a report -----------------------------------------------------------------------------------------------
    def check(self, report):
        """``(status, why)`` for a report this campaign does not take (400 / 403), else ``(0, "")``."""
        if not isinstance(report, dict) or report.get("source") != SOURCE:
            return 400, "not a PAD score feed report"
        camp = report.get("campaign")
        if not isinstance(camp, str) or not camp:
            return 403, "the machine plays in no online co-op campaign"
        if camp.strip().lower() != self.c["campaign"].strip().lower():
            return 403, "the machine plays in campaign %r, not %r" % (camp, self.c["campaign"])
        if (self.c.get("key") or "") and report.get("key") != self.c["key"]:
            return 403, "the campaign's join key is wrong"
        if report.get("team") not in self.s["teams"]:
            return 403, "%r is not one of the campaign's teams" % report.get("team")
        if not isinstance(report.get("machine"), str) or not report["machine"].strip():
            return 400, "the machine has no name"
        return 0, ""

    def take(self, report):
        """Count *report*: ``(status, words, news)`` - news a list of what changed worth telling (a region taken, the
        campaign won)."""
        status, why = self.check(report)
        if status:
            return status, why, []
        machine, team = report["machine"].strip()[:31], report["team"]
        sig = "%s|%s|%s|%s" % (report.get("game_number"), report.get("time"), report.get("scores"),
                               sorted((report.get("counts") or {}).items()))
        with self.lock:
            m = self.s["machines"].setdefault(machine, {"team": team, "games": 0, "points": 0, "last": None,
                                                        "game": report.get("game"), "seen": [], "counts": {}})
            if sig in m["seen"]:
                return 202, "game already counted (a resend)", []
            m["seen"] = (m["seen"] + [sig])[-SEEN_MAX:]
            pts = game_points(report, self.c["goal"])
            m.update(team=team, game=report.get("game"), last=int(self.clock()))
            m["games"] += 1
            m["points"] += pts
            self.s["games"] += 1
            t = self.s["teams"][team]
            t["games"] += 1
            t["total"] += pts
            counts = report_counts(report)                  # every count, whatever the goal: the designers see them
            for k, v in counts.items():
                t.setdefault("counts", {})[k] = t.get("counts", {}).get(k, 0) + v
                m.setdefault("counts", {})[k] = m.get("counts", {}).get(k, 0) + v
            news = []
            i = open_region(self.s)
            if pts and i is not None:
                t["progress"] += pts
                r = self.s["regions"][i]
                if t["progress"] >= r["target"]:
                    left = t["progress"] - r["target"]
                    r["owner"], r["taken"] = team, int(self.clock())
                    t["regions"] += 1
                    for other in self.s["teams"].values():
                        other["progress"] = 0
                    nxt = open_region(self.s)
                    t["progress"] = left if nxt is not None else 0
                    news.append("%s took %s (%s from %s)" % (team, r["name"], _n(r["target"]), machine))
                    if nxt is None:
                        best = max(self.s["teams"].items(), key=lambda kv: (kv[1]["regions"], kv[1]["total"]))
                        self.s["won_by"] = best[0]
                        news.append("The campaign is over: %s holds %d of %d" % (
                            best[0], best[1]["regions"], len(self.s["regions"])))
            self.s["log"] = (self.s["log"] + [{"t": int(self.clock()), "machine": machine, "team": team,
                                               "points": pts, "news": news}])[-LOG_MAX:]
            self._save()
        return 200, "counted %s for %s%s" % (_n(pts), team, "; counts %s" % ", ".join(
            "%s %s" % (k, _n(v)) for k, v in sorted(counts.items())) if counts else ""), news

    def _save(self):
        if not self.path:
            return
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.s, f, indent=1)
        os.replace(tmp, self.path)

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.s))

    # ---- words --------------------------------------------------------------------------------------------------
    def summary(self):
        """A few lines on where the campaign stands (Discord's message, the page's head)."""
        s = self.snapshot()
        unit = "points" if self.c["goal"]["kind"] == "score" else self.c["goal"]["count"].replace("_", " ")
        out = ["**%s** - %d game(s) played" % (self.c.get("title") or self.c["campaign"], s["games"])]
        i = open_region(s)
        if i is None:
            out.append("Every region is taken%s." % (": %s wins" % s["won_by"] if s["won_by"] else ""))
        else:
            r = s["regions"][i]
            out.append("Now racing for %s (%s %s):" % (r["name"], _n(r["target"]), unit))
        for name, t in s["teams"].items():
            out.append("%s: %d region(s)%s, %s %s in all" % (
                name, t["regions"], ", %s toward the next" % _n(t["progress"]) if i is not None else "",
                _n(t["total"]), unit))
        return out


def _n(v):
    """A number as people read it: 1,234,567."""
    return "{:,}".format(int(v))


# ---- the map ---------------------------------------------------------------------------------------------------------
def draw_map(campaign, state, width=1200):
    """The campaign's map as PNG bytes: each region a tile in its owner's colour (the one being raced for shows each
    team's progress), the teams' standings beneath. None without Pillow."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    colours = {t["name"]: t["colour"] for t in campaign["teams"]}
    regions = state["regions"]
    n = len(regions)
    cols = min(6, max(1, math.ceil(math.sqrt(n * 1.6))))
    rows = math.ceil(n / cols)
    pad, head, tile_h = 24, 84, 150
    tile_w = (width - pad * (cols + 1)) // cols
    legend_h = 40 + 34 * len(colours)
    height = head + rows * (tile_h + pad) + pad + legend_h
    img = Image.new("RGB", (width, height), "#14161a")
    d = ImageDraw.Draw(img)

    def font(size):
        for f in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf", "LiberationSans-Bold.ttf"):
            try:
                return ImageFont.truetype(f, size)
            except OSError:
                continue
        return ImageFont.load_default()

    big, mid, small = font(34), font(22), font(17)
    d.text((pad, 22), campaign.get("title") or campaign["campaign"], fill="#f2f2f2", font=big)
    d.text((width - pad, 34), "%s games" % _n(state["games"]), fill="#9aa0a6", font=mid, anchor="ra")
    now = open_region(state)
    unit = "pts" if campaign["goal"]["kind"] == "score" else campaign["goal"]["count"].replace("_", " ")
    for i, r in enumerate(regions):
        x = pad + (i % cols) * (tile_w + pad)
        y = head + (i // cols) * (tile_h + pad)
        owner = r["owner"]
        fill = colours.get(owner, "#2a2e35") if owner else ("#343a43" if i == now else "#22262c")
        d.rounded_rectangle((x, y, x + tile_w, y + tile_h), 14, fill=fill,
                            outline="#f2f2f2" if i == now else None, width=3 if i == now else 0)
        d.text((x + 14, y + 12), r["name"], fill="#ffffff", font=mid)
        if owner:
            d.text((x + 14, y + tile_h - 34), owner, fill="#ffffff", font=small)
        elif i == now:
            yy = y + 52
            for name, t in state["teams"].items():
                frac = max(0.0, min(1.0, t["progress"] / float(r["target"])))
                d.rounded_rectangle((x + 14, yy, x + tile_w - 14, yy + 12), 6, fill="#1b1e23")
                if frac > 0:
                    d.rounded_rectangle((x + 14, yy, x + 14 + max(12, int((tile_w - 28) * frac)), yy + 12), 6,
                                        fill=colours.get(name, "#888888"))
                yy += 22
                if yy > y + tile_h - 30:
                    break
            d.text((x + 14, y + tile_h - 30), "%s %s" % (_n(r["target"]), unit), fill="#c9ccd1", font=small)
        else:
            d.text((x + 14, y + tile_h - 30), "%s %s" % (_n(r["target"]), unit), fill="#7d838b", font=small)
    y = head + rows * (tile_h + pad) + 8
    for name, t in state["teams"].items():
        d.rounded_rectangle((pad, y + 4, pad + 22, y + 26), 5, fill=colours.get(name, "#888888"))
        d.text((pad + 34, y + 2), "%s  -  %d region(s), %s %s, %d game(s)%s" % (
            name, t["regions"], _n(t["total"]), unit, t["games"], "  WINNER" if state.get("won_by") == name else ""),
            fill="#e8eaed", font=mid)
        y += 34
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


# ---- Discord -------------------------------------------------------------------------------------------------------
def discord_post(webhook, text, png, opener=None):
    """Post *text* and the map to a Discord webhook; ``(ok, why)``."""
    boundary = uuid.uuid4().hex
    parts = [("--%s\r\nContent-Disposition: form-data; name=\"payload_json\"\r\nContent-Type: application/json\r\n\r\n"
              % boundary).encode() + json.dumps({"content": text[:1900]}).encode() + b"\r\n"]
    if png:
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"map.png\"\r\n"
                      "Content-Type: image/png\r\n\r\n" % boundary).encode() + png + b"\r\n")
    body = b"".join(parts) + ("--%s--\r\n" % boundary).encode()
    req = urllib.request.Request(webhook, data=body, method="POST", headers={
        "Content-Type": "multipart/form-data; boundary=%s" % boundary, "User-Agent": "PAD-online-coop"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=15) as r:
            return 200 <= r.status < 300, "HTTP %d" % r.status
    except Exception as e:                                # noqa: BLE001 - Discord down: the next post tries again
        return False, str(e)


# ---- the HTTP server ----------------------------------------------------------------------------------------------
_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta http-equiv="refresh" content="30"><title>%(title)s</title><style>body{background:#14161a;color:#e8eaed;
font:16px system-ui,sans-serif;margin:16px}img{max-width:100%%;border-radius:8px}li{margin:4px 0}</style></head>
<body><h1>%(title)s</h1><ul>%(lines)s</ul><img src="map.png" alt="the campaign map"><h2>Machines</h2><ul>%(machines)s
</ul></body></html>"""


def make_handler(camp, notify):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PAD-online-coop"

        def log_message(self, fmt, *args):            # the server's own lines, not one per request
            pass

        def _send(self, status, body=b"", ctype="text/plain; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if not 0 < n <= BODY_MAX:
                return self._send(400, b"a report has a body of up to 16 KB\n")
            try:
                report = json.loads(self.rfile.read(n).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return self._send(400, b"not JSON\n")
            status, words, news = camp.take(report)
            print("%s %s %s: %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), self.client_address[0],
                                    (report.get("machine") if isinstance(report, dict) else None) or "?", words),
                  flush=True)
            self._send(status, (words + "\n").encode("utf-8"))
            if status == 200:
                notify(news)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/map.png":
                png = draw_map(camp.c, camp.snapshot())
                return self._send(200, png, "image/png") if png else self._send(503, b"Pillow is not installed\n")
            if path == "/state.json":
                s = camp.snapshot()
                for m in s["machines"].values():
                    m.pop("seen", None)
                return self._send(200, json.dumps(s, indent=1).encode(), "application/json")
            if path in ("/", "/index.html"):
                import html as _h
                s = camp.snapshot()
                lines = "".join("<li>%s</li>" % _h.escape(l.replace("**", "")) for l in camp.summary()[1:])
                machines = "".join("<li>%s (%s): %d game(s), %s</li>" % (_h.escape(k), _h.escape(v["team"]),
                                                                         v["games"], _n(v["points"]))
                                   for k, v in sorted(s["machines"].items())) or "<li>none yet</li>"
                page = _PAGE % {"title": _h.escape(camp.c.get("title") or camp.c["campaign"]), "lines": lines,
                                "machines": machines}
                return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            return self._send(404, b"not here\n")
    return Handler


class Notifier:
    """Tells Discord (when a webhook is given) about news and every *every* games, off the request's thread."""

    def __init__(self, camp, webhook=None, every=0, post=discord_post):
        self.camp, self.webhook, self.every, self.post = camp, webhook, every, post
        self.last_games = camp.snapshot()["games"]

    def __call__(self, news):
        games = self.camp.snapshot()["games"]
        due = bool(news) or (self.every and games - self.last_games >= self.every)
        if not self.webhook or not due:
            return None
        self.last_games = games
        text = "\n".join(list(news) + [""] + self.camp.summary())
        t = threading.Thread(target=self._send, args=(text,), daemon=True)
        t.start()
        return t

    def _send(self, text):
        ok, why = self.post(self.webhook, text, draw_map(self.camp.c, self.camp.snapshot()))
        print("discord: %s" % ("posted" if ok else "not posted - %s" % why), flush=True)


def serve(campaign_path, port=8090, state_path=None, webhook=None, every=0, host="0.0.0.0"):
    camp = Campaign(load_campaign(campaign_path), state_path)
    notifier = Notifier(camp, webhook, every)
    httpd = ThreadingHTTPServer((host, port), make_handler(camp, notifier))
    print("online co-op: campaign %r (%d team(s), %d region(s)), listening on %s:%d%s" % (
        camp.c["campaign"], len(camp.c["teams"]), len(camp.c["regions"]), host, port,
        ", posting to Discord" if webhook else ""), flush=True)
    return httpd, camp


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m pinball_decryptor.online_coop_server",
                                 description="The online co-op server: machines' games per team, the map, Discord.")
    ap.add_argument("--campaign", required=True, help="the campaign file (the app's Network tab, Save campaign file)")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--host", default="0.0.0.0", help="the address to listen on (every one by default)")
    ap.add_argument("--state", help="where the totals are kept between runs (default: beside the campaign file)")
    ap.add_argument("--webhook", help="a Discord channel's webhook address, to post the map there")
    ap.add_argument("--post-every", type=int, default=0, help="also post the map every N games (0: only on news)")
    a = ap.parse_args(argv)
    state = a.state or os.path.splitext(a.campaign)[0] + ".state.json"
    try:
        httpd, _camp = serve(a.campaign, a.port, state, a.webhook, a.post_every, a.host)
    except CampaignError as e:
        ap.exit(2, "online co-op: %s\n" % e)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
