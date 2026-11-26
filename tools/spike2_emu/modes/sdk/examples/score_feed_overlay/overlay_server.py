#!/usr/bin/env python3
"""The score feed's sample overlay server (PAD-1575): takes what the machine posts and shows it live.

The machine's Score feed (the app's Network tab) posts each game's final report, and with "Also during the game"
ticked one small JSON object per event while a game is played (game_start, ball_start, score, mode_start, ...: every
one carries all the scores, the player up and their ball). This server takes those posts on any path and serves:

    /            overlay.html: the overlay page (OBS: add a Browser source with this address)
    /state       the game as it stands, as JSON (what the page reads, four times a second)

Run it on the computer whose IP address the Score feed posts to:

    python overlay_server.py                 listens on port 8080 (the app's example address)
    python overlay_server.py --port 9000     another port (the address's :port)
    python overlay_server.py --log feed.jsonl   also keep every post, one JSON object a line

Python 3.8 or later, nothing to install. Stop it with Ctrl+C.
"""
import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
RECENT = 12                                     # the last events the page lists


class Board:
    """The game as the posts so far tell it."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"game": "", "game_number": 0, "in_game": False, "players": 0, "player": 0, "ball": 0,
                      "scores": [], "modes": [], "recent": [], "last_game": None, "seq": 0, "dropped": 0,
                      "updated": 0.0}

    def take(self, doc):
        with self.lock:
            st = self.state
            st["updated"] = time.time()
            ev = doc.get("event")
            if ev is None:                      # a game's report (the end-of-game post)
                st["last_game"] = {k: doc.get(k) for k in ("game_number", "players", "scores", "insider",
                                                           "game_type", "challenge", "time")}
                st["game"] = doc.get("game") or st["game"]
                return
            seq = doc.get("seq")
            if isinstance(seq, int):
                if st["seq"] and seq > st["seq"] + 1:
                    st["dropped"] += seq - st["seq"] - 1
                st["seq"] = max(st["seq"], seq)
            for k in ("game", "game_number", "players", "player", "ball", "scores"):
                if k in doc:
                    st[k] = doc[k]
            if ev == "game_start":
                st["in_game"], st["modes"] = True, []
            elif ev == "game_end":
                st["in_game"], st["modes"], st["player"], st["ball"] = False, [], 0, 0
            elif ev == "mode_start" and doc.get("mode"):
                st["modes"].append({"name": doc["mode"], "kind": doc.get("kind", "")})
            elif ev == "mode_end" and doc.get("mode"):
                for i, m in enumerate(st["modes"]):
                    if m["name"] == doc["mode"] and m["kind"] == doc.get("kind", ""):
                        del st["modes"][i]
                        break
            if ev != "score":
                what = ev + (": " + doc["mode"] if doc.get("mode") else "")
                st["recent"] = ([{"seq": seq, "what": what, "player": doc.get("player", 0)}] + st["recent"])[:RECENT]

    def json(self):
        with self.lock:
            return json.dumps(self.state).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    board = None
    log = None
    quiet = False

    def do_POST(self):                          # noqa: N802 - http.server's name
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if 0 < n < 65536 else b""
        try:
            doc = json.loads(raw.decode("utf-8"))
            if not isinstance(doc, dict):
                raise ValueError("not an object")
        except ValueError:
            self.send_response(400)
            self.end_headers()
            return
        self.board.take(doc)
        if self.log:
            with open(self.log, "a", encoding="utf-8") as f:
                f.write(json.dumps(doc, separators=(",", ":")) + "\n")
        if not self.quiet:
            ev = doc.get("event") or "report"
            print("%s  %-13s seq %-5s player %s ball %s scores %s%s" % (
                time.strftime("%H:%M:%S"), ev, doc.get("seq", "-"), doc.get("player", "-"), doc.get("ball", "-"),
                doc.get("scores"), "  " + doc["mode"] if doc.get("mode") else ""), flush=True)
        self.send_response(204)
        self.end_headers()

    def do_GET(self):                           # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/state":
            body, kind = self.board.json(), "application/json"
        elif path in ("/", "/overlay.html"):
            with open(os.path.join(HERE, "overlay.html"), "rb") as f:
                body, kind = f.read(), "text/html; charset=utf-8"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):               # the posts are printed above, one line each
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="The score feed's sample overlay server")
    ap.add_argument("--port", type=int, default=8080, help="the port the Score feed's address names (8080)")
    ap.add_argument("--host", default="0.0.0.0", help="the address to listen on (every one of this computer's)")
    ap.add_argument("--log", default="", help="also append every post to this file, one JSON object a line")
    ap.add_argument("--quiet", action="store_true", help="print nothing per post")
    a = ap.parse_args(argv)
    Handler.board, Handler.log, Handler.quiet = Board(), a.log or None, a.quiet
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print("Score feed overlay: posts taken on port %d; open http://localhost:%d/ (OBS: a Browser source)"
          % (a.port, a.port), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
