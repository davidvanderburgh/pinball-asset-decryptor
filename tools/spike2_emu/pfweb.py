"""pfweb.py - the rig windows' web host: a local page in a native window.

The virtual playfield (playfield.py) and its villain-vision screen used to be
Tk windows. They are web pages now, drawn in the app's own design, and this
module is everything between their Python models and the page: a loopback
HTTP server, a numbered event stream, and the window the page is shown in.

STDLIB ONLY, ON PURPOSE. It runs wherever the rig's windows run - PAD's own
bundled Python on Windows (reached through interop), a Linux desktop's
python3, and the macOS container's python3 - and none of those may be asked
to install anything (project rule: no user ever resolves a dependency).

THE WINDOW, best first, and each rung is a property of the machine:

  1. pywebview, when it imports. PAD's bundled Python on Windows carries it
     (requirements-ui.txt, the same library the app's own window uses), so
     the normal Windows playfield is a native Edge WebView2 window.
  2. GTK WebKit (gi + WebKit2), when it imports: the macOS container
     (docker/Dockerfile installs gir1.2-webkit2-4.1 for exactly this) and most
     Linux desktops. A real X window with a title bar, like the Tk one was.
  3. A Chromium-family browser in APP mode (Edge, Chrome, Chromium, Brave):
     a window with no tabs or address bar, in its own throwaway profile so it
     is a process of its own that closes with this one.
  4. The system browser, as a tab. The window still works; it just looks
     like a web page.

PAD_PF_WINDOW=webview|gtk|app|browser forces one rung (for testing a rung on
a machine that would pick a higher one).

The page talks back over the same server: GET /state for a full snapshot,
/events for the change stream (Server-Sent Events, numbered, with a long-poll
fallback for an engine whose EventSource never opens), POST /api for actions.
Every request carries a session token; the server binds 127.0.0.1 only.
"""

import collections
import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------
class Bus:
    """Numbered events, the newest KEEP of them replayable by number."""

    KEEP = 600

    def __init__(self):
        self._cv = threading.Condition()
        self._ev = collections.deque(maxlen=self.KEEP)
        self.seq = 0
        self.closed = False

    def publish(self, etype, data=None):
        text = json.dumps({"type": etype, "data": data}, separators=(",", ":"))
        with self._cv:
            self.seq += 1
            self._ev.append((self.seq, text))
            self._cv.notify_all()

    def since(self, n):
        with self._cv:
            return [(s, t) for s, t in self._ev if s > n]

    def wait(self, n, timeout):
        with self._cv:
            if self.seq > n or self.closed:
                return True
            self._cv.wait(timeout)
            return self.seq > n

    def close(self):
        with self._cv:
            self.closed = True
            self._cv.notify_all()


# ---------------------------------------------------------------------------
# the server
# ---------------------------------------------------------------------------
def find_fonts():
    """IBM Plex, the app's type, when this rig sits inside a PAD checkout or
    install (tools/spike2_emu -> pinball_decryptor/webui/static/fonts). The
    container mounts only the rig; there the page falls back to the system's
    IBM Plex (fonts-ibm-plex) or its sans."""
    here = os.path.dirname(os.path.abspath(__file__))
    for up in (2, 3):
        base = here
        for _ in range(up):
            base = os.path.dirname(base)
        cand = os.path.join(base, "pinball_decryptor", "webui", "static",
                            "fonts")
        if os.path.isdir(cand):
            return cand
    return None


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self):
        # no reverse lookup of our own name (HTTPServer.server_bind does one,
        # and on a Mac that can raise a local-network permission prompt)
        import socketserver
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = host, port

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError,
                            BrokenPipeError)):
            return                      # a page closed mid-write: normal
        super().handle_error(request, client_address)


class WebHost:
    """The server, the event stream and the windows for one app.

    `app` answers four calls: ``state(page)`` -> a JSON-able snapshot,
    ``api(method, args)`` -> a JSON-able result, ``blob(key)`` -> (bytes,
    mime) or None, and ``file(name)`` -> a path or None (the artwork).
    """

    def __init__(self, static_dir, app, title="PAD"):
        self.static_dir = static_dir
        self.fonts_dir = find_fonts()
        self.app = app
        self.title = title
        self.token = secrets.token_urlsafe(18)
        self.bus = Bus()
        self.clients = 0
        self._last_client = time.monotonic()
        self._srv = None
        self.port = None
        self.backend = None
        self._pending = []              # windows asked for before run()
        self._ready = False
        self._plock = threading.Lock()

    # ---- lifecycle -------------------------------------------------------
    def start(self):
        host = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json",
                      cache=False):
                if isinstance(body, str):
                    body = body.encode("utf8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control",
                                 "max-age=3600" if cache else "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _ok_token(self, q):
                return (q.get("t") or [""])[0] == host.token

            def do_GET(self):                           # noqa: N802
                u = urlparse(self.path)
                q = parse_qs(u.query)
                path = u.path
                if path in ("/", "/index.html"):
                    return host._file(self, os.path.join(host.static_dir,
                                                         "index.html"))
                if path.startswith("/static/"):
                    return host._file(self, os.path.join(
                        host.static_dir, unquote(path[len("/static/"):])))
                if path.startswith("/fonts/"):
                    if not host.fonts_dir:
                        return self._send(404, "{}")
                    return host._file(self, os.path.join(
                        host.fonts_dir, unquote(path[len("/fonts/"):])),
                        cache=True)
                if path == "/favicon.ico":
                    icon = _find_icon(png=True)
                    if icon:
                        return host._file(self, icon, cache=True)
                    return self._send(204, b"")
                if not self._ok_token(q):
                    return self._send(403, '{"error":"token"}')
                if path == "/state":
                    page = (q.get("page") or ["main"])[0]
                    try:
                        st = host.app.state(page)
                    except Exception as e:              # noqa: BLE001
                        return self._send(500, json.dumps({"error": str(e)}))
                    st = dict(st or {})
                    st["_seq"] = host.bus.seq
                    return self._send(200, json.dumps(st))
                if path == "/events":
                    return host._events(self, q)
                if path.startswith("/blob/"):
                    got = host.app.blob(unquote(path[len("/blob/"):]))
                    if not got:
                        return self._send(404, "{}")
                    data, mime = got
                    return self._send(200, data, mime, cache=True)
                if path.startswith("/file/"):
                    p = host.app.file(unquote(path[len("/file/"):]))
                    if not p:
                        return self._send(404, "{}")
                    return host._file(self, p, cache=True)
                return self._send(404, "{}")

            def do_POST(self):                          # noqa: N802
                u = urlparse(self.path)
                q = parse_qs(u.query)
                if u.path != "/api" or not self._ok_token(q):
                    return self._send(403, "{}")
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    req = json.loads(self.rfile.read(n) or b"{}")
                    r = host.app.api(req.get("m"), req.get("a") or [])
                    return self._send(200, json.dumps({"ok": True, "r": r}))
                except Exception as e:                  # noqa: BLE001
                    return self._send(200, json.dumps({"ok": False,
                                                       "error": str(e)}))

        self._srv = _Server(("127.0.0.1", 0), H)
        self.port = self._srv.server_address[1]
        threading.Thread(target=self._srv.serve_forever, name="pfweb-http",
                         daemon=True).start()

    def stop(self):
        self.bus.close()
        if self._srv is not None:
            try:
                self._srv.shutdown()
            except Exception:                           # noqa: BLE001
                pass

    def url(self, page="main"):
        return "http://127.0.0.1:%d/?t=%s&page=%s" % (self.port, self.token,
                                                      quote(page))

    def publish(self, etype, data=None):
        self.bus.publish(etype, data)

    # ---- request helpers ---------------------------------------------------
    def _file(self, h, path, cache=False):
        real = os.path.realpath(path)
        roots = [os.path.realpath(self.static_dir)]
        if self.fonts_dir:
            roots.append(os.path.realpath(self.fonts_dir))
        # a static or font path must stay inside its root; an app-named file
        # (/file/...) is whatever the app answered, so it is trusted as is
        if h.path.startswith(("/static/", "/fonts/", "/?", "/index")):
            if not any(real == r or real.startswith(r + os.sep)
                       for r in roots):
                return h._send(404, "{}")
        try:
            with open(real, "rb") as f:
                data = f.read()
        except OSError:
            return h._send(404, "{}")
        mime = mimetypes.guess_type(real)[0] or "application/octet-stream"
        if real.endswith(".js"):
            mime = "text/javascript"
        return h._send(200, data, mime, cache=cache)

    def _events(self, h, q):
        since = int((q.get("since") or ["0"])[0] or 0)
        if (q.get("poll") or [""])[0]:
            wait = min(25.0, float((q.get("wait") or ["20"])[0] or 20))
            self.bus.wait(since, wait)
            evs = self.bus.since(since)
            body = '{"seq":%d,"events":[%s]}' % (
                self.bus.seq, ",".join('{"seq":%d,"e":%s}' % (s, t)
                                       for s, t in evs))
            self._touch()
            return h._send(200, body)
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
        self.clients += 1
        try:
            h.wfile.write(b": hello\n\n")
            h.wfile.flush()
            while not self.bus.closed:
                for seq, text in self.bus.since(since):
                    h.wfile.write(("id: %d\ndata: %s\n\n" % (seq, text))
                                  .encode("utf8"))
                    since = seq
                h.wfile.flush()
                self._touch()
                if not self.bus.wait(since, 10.0):
                    h.wfile.write(b": ping\n\n")
                    h.wfile.flush()
        except OSError:
            pass
        finally:
            self.clients -= 1
            self._touch()

    def _touch(self):
        self._last_client = time.monotonic()

    def idle_for(self):
        """Seconds since a page last talked to us (0 while one listens)."""
        if self.clients > 0:
            return 0.0
        return time.monotonic() - self._last_client

    # ---- windows -----------------------------------------------------------
    def run(self, main, on_close):
        """Show the main window and block until it closes (or until quit()).

        `main` is a dict: page, title, width, height, x, y. `on_close` runs
        on the way out, whatever closed the window - the user, quit(), or the
        window's process dying."""
        self.backend = pick_backend(self)
        self.backend.run(main, on_close, self._flush)

    def _flush(self):
        """The window system is up: open whatever was asked for before it
        was (the villain vision screen can stamp during the first frames)."""
        with self._plock:
            self._ready = True
            pending, self._pending = self._pending, []
        for name, spec, on_close in pending:
            self.backend.open(name, spec, on_close)

    def open_window(self, name, spec, on_close=None):
        """A second window (the villain vision screen). A no-op when the
        backend is gone; `on_close` runs when the USER closes it."""
        with self._plock:
            if self.backend is None or not self._ready:
                self._pending.append((name, spec, on_close))
                return
        self.backend.open(name, spec, on_close)

    def show_window(self, name, visible):
        if self.backend is not None:
            self.backend.show(name, visible)

    def geometry(self, name):
        """(x, y) of a window when the backend can say, else None."""
        if self.backend is not None:
            return self.backend.position(name)
        return None

    def quit(self):
        if self.backend is not None:
            self.backend.quit()


def screen_size():
    """(width, height) of the primary screen's work area, best effort."""
    if sys.platform == "win32":
        try:
            import ctypes
            import ctypes.wintypes as wt
            r = wt.RECT()
            # SPI_GETWORKAREA: the screen less the taskbar
            if ctypes.windll.user32.SystemParametersInfoW(0x30, 0,
                                                          ctypes.byref(r), 0):
                return r.right - r.left, r.bottom - r.top
        except Exception:                               # noqa: BLE001
            pass
    try:
        out = subprocess.run(["xdpyinfo"], capture_output=True, timeout=5,
                             text=True).stdout
        for ln in out.splitlines():
            if "dimensions:" in ln:
                w, h = ln.split()[1].split("x")
                return int(w), int(h)
    except Exception:                                   # noqa: BLE001
        pass
    return 1920, 1080


# ---------------------------------------------------------------------------
# window backends
# ---------------------------------------------------------------------------
def pick_backend(host):
    want = (os.environ.get("PAD_PF_WINDOW") or "").strip().lower()
    order = ([want] if want else []) + ["webview", "gtk", "app", "browser"]
    for name in order:
        cls = BACKENDS.get(name)
        if cls is not None and cls.available():
            return cls(host)
    return BrowserBackend(host)


class _Base:
    def __init__(self, host):
        self.host = host
        self._on_close = None
        self._closed = threading.Event()

    def _finish(self):
        if self._closed.is_set():
            return
        self._closed.set()
        cb, self._on_close = self._on_close, None
        if cb is not None:
            try:
                cb()
            except Exception:                           # noqa: BLE001
                pass

    def show(self, name, visible):
        pass

    def position(self, name):
        return None


class WebviewBackend(_Base):
    """pywebview: Edge WebView2 on Windows (PAD's bundled Python has it)."""

    @staticmethod
    def available():
        try:
            import webview  # noqa: F401
            return True
        except Exception:                               # noqa: BLE001
            return False

    def __init__(self, host):
        super().__init__(host)
        self.wins = {}
        self._quitting = False

    def _create(self, spec):
        import webview
        kw = dict(width=int(spec.get("width") or 900),
                  height=int(spec.get("height") or 700),
                  background_color="#15171A", text_select=False,
                  min_size=tuple(spec.get("min_size") or (320, 240)))
        if spec.get("x") is not None and spec.get("y") is not None:
            kw.update(x=int(spec["x"]), y=int(spec["y"]))
        if spec.get("fixed"):
            kw["resizable"] = False
        return webview.create_window(spec.get("title") or self.host.title,
                                     self.host.url(spec.get("page", "main")),
                                     **kw)

    def run(self, main, on_close, ready=None):
        import webview
        self._on_close = on_close
        win = self._create(main)
        self.wins["main"] = win

        def _main_closed():
            # the playfield closing ends the process: its second windows
            # (the villain vision) go with it, or start() would wait on them
            self._quitting = True
            self._finish()
            for name, w in list(self.wins.items()):
                if name != "main":
                    try:
                        w.destroy()
                    except Exception:                   # noqa: BLE001
                        pass
        win.events.closed += _main_closed
        # the rig's own icon when the app's is beside it
        icon = _find_icon()
        kw = {"icon": icon} if icon else {}
        if ready is not None:
            kw["func"] = ready
        try:
            webview.start(private_mode=True, **kw)
        except TypeError:
            kw.pop("icon", None)
            webview.start(private_mode=True, **kw)
        self._finish()

    def open(self, name, spec, on_close=None):
        if name in self.wins:
            self.show(name, True)
            return
        win = self._create(spec)
        self.wins[name] = win
        if on_close is not None:
            def _closing():
                if self._quitting:
                    return True         # the process is going: let it close
                # a second display's close box HIDES it for the run (the
                # item-44 contract the Tk window kept); the process decides
                threading.Thread(target=on_close, daemon=True).start()
                try:
                    win.hide()
                except Exception:                       # noqa: BLE001
                    pass
                return False
            win.events.closing += _closing

    def show(self, name, visible):
        win = self.wins.get(name)
        if win is None:
            return
        try:
            win.show() if visible else win.hide()
        except Exception:                               # noqa: BLE001
            pass

    def position(self, name):
        win = self.wins.get(name)
        try:
            return (int(win.x), int(win.y)) if win is not None else None
        except Exception:                               # noqa: BLE001
            return None

    def quit(self):
        self._quitting = True
        for name, win in list(self.wins.items()):
            if name == "main":
                continue
            try:
                win.destroy()
            except Exception:                           # noqa: BLE001
                pass
        win = self.wins.get("main")
        if win is not None:
            try:
                win.destroy()
            except Exception:                           # noqa: BLE001
                pass


class GtkBackend(_Base):
    """GTK + WebKit2: the macOS container and Linux desktops."""

    @staticmethod
    def available():
        if sys.platform == "win32" or not os.environ.get("DISPLAY") and \
                not os.environ.get("WAYLAND_DISPLAY"):
            return False
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            try:
                gi.require_version("WebKit2", "4.1")
            except ValueError:
                gi.require_version("WebKit2", "4.0")
            from gi.repository import Gtk, WebKit2  # noqa: F401
            return True
        except Exception:                               # noqa: BLE001
            return False

    def __init__(self, host):
        super().__init__(host)
        self.wins = {}

    def _create(self, spec, on_delete):
        from gi.repository import Gtk, WebKit2
        w = Gtk.Window(title=spec.get("title") or self.host.title)
        w.set_default_size(int(spec.get("width") or 900),
                           int(spec.get("height") or 700))
        if spec.get("x") is not None and spec.get("y") is not None:
            w.move(int(spec["x"]), int(spec["y"]))
        if spec.get("fixed"):
            w.set_resizable(False)
        view = WebKit2.WebView()
        view.load_uri(self.host.url(spec.get("page", "main")))
        w.add(view)
        w.connect("delete-event", on_delete)
        w.show_all()
        return w

    def run(self, main, on_close, ready=None):
        # SOFTWARE RENDERING, AND IT HAS TO BE ASKED FOR: the macOS container
        # is Xvfb with llvmpipe, where WebKitGTK's DMA-BUF renderer and its
        # accelerated compositing draw a blank window. Set before the first
        # web view spawns its web process; harmless on a real desktop.
        os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")
        os.environ.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "1")
        from gi.repository import GLib, Gtk
        self._on_close = on_close

        def _del(*_a):
            Gtk.main_quit()
            return False
        self.wins["main"] = self._create(main, _del)
        if ready is not None:
            GLib.idle_add(lambda: (ready(), False)[1])
        Gtk.main()
        self._finish()

    def open(self, name, spec, on_close=None):
        from gi.repository import GLib

        def _go():
            if name in self.wins:
                self.wins[name].show_all()
                return False

            def _del(win, *_a):
                if on_close is not None:
                    threading.Thread(target=on_close, daemon=True).start()
                win.hide()
                return True             # hide, do not destroy
            self.wins[name] = self._create(spec, _del)
            return False
        GLib.idle_add(_go)

    def show(self, name, visible):
        from gi.repository import GLib

        def _go():
            w = self.wins.get(name)
            if w is not None:
                w.show_all() if visible else w.hide()
            return False
        GLib.idle_add(_go)

    def position(self, name):
        w = self.wins.get(name)
        try:
            x, y = w.get_position()
            return int(x), int(y)
        except Exception:                               # noqa: BLE001
            return None

    def quit(self):
        from gi.repository import GLib, Gtk
        GLib.idle_add(lambda: (Gtk.main_quit(), False)[1])


def _chromium():
    """A Chromium-family browser that can open an app window, or None."""
    names = ["msedge", "chrome", "chromium", "chromium-browser",
             "google-chrome", "google-chrome-stable", "brave-browser",
             "microsoft-edge"]
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles(x86)"),
                     os.environ.get("ProgramFiles"),
                     os.environ.get("LOCALAPPDATA")):
            if not base:
                continue
            for rel in (r"Microsoft\Edge\Application\msedge.exe",
                        r"Google\Chrome\Application\chrome.exe",
                        r"BraveSoftware\Brave-Browser\Application\brave.exe"):
                p = os.path.join(base, rel)
                if os.path.isfile(p):
                    return p
    if sys.platform == "darwin":
        for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"):
            if os.path.isfile(p):
                return p
    return None


class AppBackend(_Base):
    """A Chromium-family browser's --app window, one process per window, each
    in its own throwaway profile (a shared profile would hand the window to
    an already-running browser and our process would lose track of it)."""

    @staticmethod
    def available():
        return _chromium() is not None

    def __init__(self, host):
        super().__init__(host)
        self.procs = {}
        self.dirs = []
        self._quit = threading.Event()

    def _spawn(self, spec):
        exe = _chromium()
        prof = tempfile.mkdtemp(prefix="padpf-")
        self.dirs.append(prof)
        args = [exe, "--app=" + self.host.url(spec.get("page", "main")),
                "--user-data-dir=" + prof, "--no-first-run",
                "--no-default-browser-check", "--disable-extensions",
                "--window-size=%d,%d" % (int(spec.get("width") or 900),
                                         int(spec.get("height") or 700))]
        if spec.get("x") is not None and spec.get("y") is not None:
            args.append("--window-position=%d,%d" % (int(spec["x"]),
                                                     int(spec["y"])))
        if sys.platform.startswith("linux") and os.geteuid() == 0:
            args.append("--no-sandbox")         # chromium refuses root without
        return subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                creationflags=_CREATE_NO_WINDOW)

    def run(self, main, on_close, ready=None):
        self._on_close = on_close
        self.procs["main"] = self._spawn(main)
        if ready is not None:
            ready()
        while not self._quit.is_set():
            if self.procs["main"].poll() is not None:
                break
            self._quit.wait(0.5)
        self.quit()
        self._finish()
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)

    def open(self, name, spec, on_close=None):
        p = self.procs.get(name)
        if p is not None and p.poll() is None:
            return
        self.procs[name] = self._spawn(spec)

    def show(self, name, visible):
        if visible:
            return
        p = self.procs.pop(name, None)
        if p is not None:
            try:
                p.terminate()
            except Exception:                           # noqa: BLE001
                pass

    def quit(self):
        self._quit.set()
        for p in self.procs.values():
            try:
                if p.poll() is None:
                    p.terminate()
            except Exception:                           # noqa: BLE001
                pass


class BrowserBackend(_Base):
    """The last rung: the system browser, as a tab. Closing is judged by the
    page going quiet: it holds an event stream open while it is shown."""

    GONE_S = 30.0

    @staticmethod
    def available():
        return True

    def __init__(self, host):
        super().__init__(host)
        self._quit = threading.Event()

    def run(self, main, on_close, ready=None):
        self._on_close = on_close
        webbrowser.open(self.host.url(main.get("page", "main")))
        if ready is not None:
            ready()
        seen = False
        while not self._quit.is_set():
            if self.host.clients > 0:
                seen = True
            elif seen and self.host.idle_for() > self.GONE_S:
                break
            self._quit.wait(1.0)
        self._finish()

    def open(self, name, spec, on_close=None):
        webbrowser.open(self.host.url(spec.get("page", "main")))

    def quit(self):
        self._quit.set()


BACKENDS = {"webview": WebviewBackend, "gtk": GtkBackend, "app": AppBackend,
            "browser": BrowserBackend}


def _find_icon(png=False):
    here = os.path.dirname(os.path.abspath(__file__))
    base = os.path.dirname(os.path.dirname(here))
    name = "icon.ico" if sys.platform == "win32" and not png else "icon.png"
    p = os.path.join(base, "pinball_decryptor", name)
    return p if os.path.isfile(p) else None
