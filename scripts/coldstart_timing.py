"""Timed start of the app with a hidden window: nothing saved, hard exit.

python scripts/coldstart_timing.py OUT.json WEBVIEW_DIR [LINGER_S] [APP_DIR]
then: python scripts/coldstart_report.py OUT.json

Run it with a Python that has pywebview (the installed copy's, or the
checkout's .venv).  APP_DIR is the tree to time (default: this checkout;
an installed copy's folder times that).  The window is created hidden,
the instance and agent links and the settings are not written, and the
process ends itself LINGER_S after the page has its state.  It does add
a session to the session log.  WEBVIEW_DIR is a scratch folder for the
web engine's profile (an elevated app and this run cannot share one)."""
import json
import os
import sys
import threading
import time

T0 = time.perf_counter()
APP = (sys.argv[4] if len(sys.argv) > 4 else
       os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = sys.argv[1]
STORE = sys.argv[2]
LINGER = float(sys.argv[3]) if len(sys.argv) > 3 else 12.0
marks = []


def mark(name):
    marks.append((name, round(time.perf_counter() - T0, 3)))


sys.path.insert(0, APP)
os.chdir(APP)

# ---- sampler: what the UI loop and the main thread are inside, every 15 ms
samples = []            # (t, thread name, [app frames outermost..innermost])
stop_sampling = threading.Event()


def _sampler():
    names = {}
    me = threading.get_ident()
    while not stop_sampling.is_set():
        t = time.perf_counter() - T0
        for th in threading.enumerate():
            names[th.ident] = th.name
        for ident, frame in sys._current_frames().items():
            if ident == me:
                continue
            name = names.get(ident, "?")
            if name not in ("pad-ui", "MainThread"):
                continue
            chain = []
            f = frame
            while f is not None:
                fn = f.f_code.co_filename.replace("\\", "/")
                short = fn.rsplit("/", 1)[-1]
                if "/pinball_decryptor/" in fn:
                    short = fn.split("/pinball_decryptor/", 1)[1]
                elif "site-packages/" in fn:
                    short = fn.split("site-packages/", 1)[1]
                chain.append("%s:%s" % (short, f.f_code.co_name))
                f = f.f_back
            chain.reverse()
            samples.append((t, name, chain))
        time.sleep(0.015)


threading.Thread(target=_sampler, name="sampler", daemon=True).start()

from pinball_decryptor.webui import host as H            # noqa: E402
mark("imported webui.host")
from pinball_decryptor.webui import agent_link, open_image  # noqa: E402
open_image.write_link = lambda *a, **k: None
open_image.register_association = lambda *a, **k: None
agent_link.set_enabled = lambda *a, **k: None
import pinball_decryptor.app as A                         # noqa: E402
mark("imported app")
A.App._save_settings = lambda self, *a, **k: None

_init = A.App.__init__


def _timed_init(self, ctx):
    mark("App() begin")
    try:
        _init(self, ctx)
    finally:
        mark("App() end")


A.App.__init__ = _timed_init

_session = A.App._start_session


def _timed_session(self):
    mark("last project: opening")
    try:
        _session(self)
    finally:
        mark("last project: open")


A.App._start_session = _timed_session

from pinball_decryptor.webui.context import Context      # noqa: E402
_snapshot = Context.state_snapshot


def _timed_snapshot(self):
    mark("page asks for its state")
    try:
        return _snapshot(self)
    finally:
        mark("page has its state (it draws now)")


Context.state_snapshot = _timed_snapshot

_preload = H.Host.preload_window


def _timed_preload(self):
    mark("webview import begin")
    _preload(self)
    mark("webview import + screens end")


H.Host.preload_window = _timed_preload

_build = H.build


def _timed_build(ctx=None, meanwhile=None):
    mark("build begin")
    r = _build(ctx, meanwhile=meanwhile)
    mark("build end (window may now be created)")
    return r


H.build = _timed_build

_run_native = H.run_native
result = {}


def _timed_run_native(ctx, server, host):
    import webview
    mark("run_native begin")
    _create = webview.create_window
    _start = webview.start

    def create(*a, **k):
        k["hidden"] = True
        win = _create(*a, **k)
        mark("create_window returned")
        win.show = lambda: None
        win.events.shown += lambda: mark("window shown event")
        win.events.loaded += lambda: mark("page loaded event")
        result["win"] = win
        return win

    def start(*a, **k):
        k["storage_path"] = STORE
        mark("webview.start (WebView2 begins)")
        return _start(*a, **k)

    webview.create_window = create
    webview.start = start

    def _after_page():
        ctx.page_seen.wait(60)
        building = getattr(ctx, "building", None)
        if building is not None:
            building.wait(60)

        # what the page is showing as the start goes on
        def _look():
            for _ in range(12):
                try:
                    text = result["win"].evaluate_js(
                        "(document.getElementById('app').innerText || '')"
                        ".replace(/\\s+/g, ' ').slice(0, 160)")
                except Exception as e:                  # noqa: BLE001
                    text = "(%r)" % e
                mark("page shows: %s" % (text or "(nothing: the spinner)"))
                time.sleep(0.2)
        threading.Thread(target=_look, daemon=True).start()
        # loop latency: how long a click that needs the UI loop would wait
        lat = []
        end = time.perf_counter() + LINGER
        while time.perf_counter() < end:
            t = time.perf_counter()
            ev = threading.Event()
            ctx.loop.post(ev.set)
            ev.wait(30)
            lat.append((round(t - T0, 3),
                        round((time.perf_counter() - t) * 1000)))
            time.sleep(0.05)
        result["latency"] = lat
        try:
            js = result["win"].evaluate_js(
                "JSON.stringify({nav: performance.getEntriesByType("
                "'navigation')[0], paint: performance.getEntriesByType("
                "'paint'), res: performance.getEntriesByType('resource')"
                ".map(r => [r.name.replace(/^https?:\\/\\/[^\\/]+/, '')"
                ".split('?')[0], Math.round(r.startTime), "
                "Math.round(r.duration), r.transferSize])})")
            result["perf"] = json.loads(js) if js else None
        except Exception as e:                          # noqa: BLE001
            result["perf_error"] = repr(e)
        _finish()

    threading.Thread(target=_after_page, daemon=True).start()
    return _run_native(ctx, server, host)


H.run_native = _timed_run_native


def _finish():
    stop_sampling.set()
    time.sleep(0.05)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"marks": marks, "samples": samples,
                   "latency": result.get("latency"),
                   "perf": result.get("perf"),
                   "perf_error": result.get("perf_error")}, fh)
    os._exit(0)


def _deadline():
    time.sleep(90)
    mark("DEADLINE: gave up")
    _finish()


threading.Thread(target=_deadline, daemon=True).start()
mark("calling main")
H.main([])
mark("main returned")
_finish()
