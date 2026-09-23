"""The local HTTP server the web UI runs on.

Bound to 127.0.0.1 on a free port.  Everything but the static files needs
the session token the host puts in the page's URL, so no other program on
the machine can drive the app or read files through it.

Routes
  GET  /                      the page (static/index.html)
  GET  /static/<path>         the page's css, js, fonts, images
  POST /api                   one call: {"m": "ns.method", "a": [...], "k": {...}}
  POST /api/reply             a modal's answer: {"id": ..., "v": ...}
  GET  /api/state             the whole UI state and the event number it is at
  GET  /events?since=N        Server-Sent Events after N (or ?poll=1: JSON)
  GET  /media?p=<path>        a local file (audio, video, picture) with Range
"""

import json
import mimetypes
import os
import re
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "static")

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("audio/wav", ".wav")
mimetypes.add_type("audio/ogg", ".ogg")
mimetypes.add_type("audio/flac", ".flac")
mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/webm", ".webm")

_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


class _Handler(BaseHTTPRequestHandler):
    server_version = "PAD"
    protocol_version = "HTTP/1.1"

    # quiet: the app's own log says what matters
    def log_message(self, fmt, *args):          # noqa: D401
        return

    @property
    def app(self):
        return self.server.pad

    # ------------------------------------------------------------------
    def _authorised(self, query):
        token = self.headers.get("X-PAD-Token") or \
            (query.get("t") or [""])[0]
        return token == self.app.token

    def _send(self, status, body=b"", ctype="application/json",
              headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, status=HTTPStatus.OK):
        self._send(status, json.dumps(obj, separators=(",", ":")))

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return None

    # ------------------------------------------------------------------
    def do_GET(self):                               # noqa: N802
        url = urlparse(self.path)
        query = parse_qs(url.query)
        path = url.path
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(unquote(path[len("/static/"):]))
        if path == "/favicon.ico":
            icon = os.path.join(os.path.dirname(STATIC_DIR), "..", "icon.png")
            icon = os.path.normpath(icon)
            if os.path.isfile(icon):
                with open(icon, "rb") as f:
                    return self._send(HTTPStatus.OK, f.read(), "image/png")
            return self._send(HTTPStatus.NO_CONTENT, b"", "image/png")
        if not self._authorised(query):
            return self._send(HTTPStatus.FORBIDDEN, b'{"error":"token"}')
        if path == "/api/state":
            return self._json(self.app.state_snapshot())
        if path == "/events":
            if (query.get("poll") or [""])[0]:
                return self._poll_events(query)
            return self._sse(query)
        if path == "/media":
            return self._media((query.get("p") or [""])[0])
        return self._send(HTTPStatus.NOT_FOUND, b'{"error":"not found"}')

    do_HEAD = do_GET

    def do_POST(self):                              # noqa: N802
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if not self._authorised(query):
            return self._send(HTTPStatus.FORBIDDEN, b'{"error":"token"}')
        payload = self._read_json()
        if payload is None:
            return self._json({"ok": False, "error": "bad json"},
                              HTTPStatus.BAD_REQUEST)
        if url.path == "/api":
            return self._json(self.app.registry.dispatch(payload))
        if url.path == "/api/reply":
            ok = self.app.dialogs.reply(payload.get("id"), payload.get("v"))
            return self._json({"ok": ok})
        return self._send(HTTPStatus.NOT_FOUND, b'{"error":"not found"}')

    # ------------------------------------------------------------------
    def _static(self, rel):
        rel = rel.replace("\\", "/").lstrip("/")
        full = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            return self._send(HTTPStatus.NOT_FOUND, b"not found",
                              "text/plain")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            body = f.read()
        self._send(HTTPStatus.OK, body, ctype)

    def _poll_events(self, query):
        since = int((query.get("since") or ["0"])[0] or 0)
        wait = float((query.get("wait") or ["0"])[0] or 0)
        if wait > 0:
            self.app.bus.wait(since, min(wait, 25.0))
        events, gap = self.app.bus.since(since)
        body = '{"gap":%s,"last":%d,"events":[%s]}' % (
            "true" if gap else "false", self.app.bus.last_seq,
            ",".join('{"seq":%d,"e":%s}' % (s, t) for s, t in events))
        self._send(HTTPStatus.OK, body)

    def _sse(self, query):
        since = int((query.get("since") or ["0"])[0] or 0)
        last_id = self.headers.get("Last-Event-ID")
        if last_id and last_id.isdigit():
            since = max(since, int(last_id))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.app.client_connected()
        try:
            events, gap = self.app.bus.since(since)
            if gap:
                self.wfile.write(b"event: gap\ndata: {}\n\n")
            for seq, text in events:
                self.wfile.write(("id: %d\ndata: %s\n\n" % (seq, text))
                                 .encode("utf-8"))
                since = seq
            self.wfile.flush()
            last_ping = time.monotonic()
            while not self.app.bus.closed:
                if self.app.bus.wait(since, 10.0):
                    events, gap = self.app.bus.since(since)
                    if gap:
                        self.wfile.write(b"event: gap\ndata: {}\n\n")
                    chunk = []
                    for seq, text in events:
                        chunk.append("id: %d\ndata: %s\n\n" % (seq, text))
                        since = seq
                    if chunk:
                        self.wfile.write("".join(chunk).encode("utf-8"))
                        self.wfile.flush()
                if time.monotonic() - last_ping > 10:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_ping = time.monotonic()
        except (BrokenPipeError, ConnectionResetError,
                ConnectionAbortedError, OSError):
            pass
        finally:
            self.app.client_disconnected()

    def _media(self, raw_path):
        path = os.path.normpath(unquote(raw_path or ""))
        if not path or not os.path.isfile(path):
            return self._send(HTTPStatus.NOT_FOUND, b"not found",
                              "text/plain")
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        start, end = 0, size - 1
        status = HTTPStatus.OK
        rng = self.headers.get("Range")
        if rng:
            m = _RANGE.match(rng.strip())
            if m:
                if m.group(1):
                    start = int(m.group(1))
                    if m.group(2):
                        end = min(int(m.group(2)), size - 1)
                elif m.group(2):
                    start = max(0, size - int(m.group(2)))
                if start > end or start >= size:
                    return self._send(
                        HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, b"",
                        "text/plain",
                        {"Content-Range": "bytes */%d" % size})
                status = HTTPStatus.PARTIAL_CONTENT
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range",
                             "bytes %d-%d/%d" % (start, end, size))
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(65536, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError,
                ConnectionAbortedError, OSError):
            pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self):
        # HTTPServer.server_bind looks the host name up (socket.getfqdn),
        # which on macOS can reach for mDNS and raise the "find devices on
        # local networks" permission prompt.  The name is never used here.
        import socketserver
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port

    def handle_error(self, request, client_address):
        # a page that reloads or closes drops its event stream mid-write:
        # that is normal, not an error worth a traceback on the console
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError,
                            BrokenPipeError)):
            return
        super().handle_error(request, client_address)


class WebServer:
    """Owns the HTTP server thread.  ``pad`` is the host context the handler
    reads: token, registry, dialogs, bus, state_snapshot(), client hooks."""

    def __init__(self, pad, host="127.0.0.1", port=0):
        self._httpd = _Server((host, port), _Handler)
        self._httpd.pad = pad
        self._thread = None

    @property
    def port(self):
        return self._httpd.server_address[1]

    def start(self):
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name="pad-http", daemon=True)
        self._thread.start()

    def stop(self):
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception:                           # noqa: BLE001
            pass
