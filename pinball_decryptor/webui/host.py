"""Start the app with the web UI: the run logic on its loop, the local
server, and a native window (pywebview) showing the page.

    python -m pinball_decryptor            the native window
    python -m pinball_decryptor --browser  the page in the system browser
    python -m pinball_decryptor --serve    the server only (tests, captures)

The native window is Edge WebView2 on Windows, WKWebView on macOS and Qt
WebEngine on Linux (all shipped with the app).  If it cannot start, the app
opens the page in the system browser instead and says why in the log, so a
missing web view never leaves the app unusable.
"""

import argparse
import logging
import os
import sys
import threading
import time

from . import compat
from .context import Context
from .dialogs import list_dir, list_roots
from .server import WebServer

log = logging.getLogger(__name__)

APP_TITLE = "Pinball Asset Decryptor"
MIN_SIZE = (900, 620)


def _filetypes_for_pywebview(filetypes):
    out = []
    for desc, patterns in filetypes or ():
        pats = [p for p in str(patterns).split() if p]
        if not pats:
            continue
        out.append("%s (%s)" % (str(desc).replace("(", "[").replace(")", "]"),
                                ";".join(pats)))
    return tuple(out)


class Host:
    """The desktop side: window chrome and native pickers."""

    def __init__(self, ctx, mode):
        self.ctx = ctx
        self.mode = mode                    # "native" | "browser" | "serve"
        self.window = None
        self._quit = threading.Event()
        self._maximized = False

    # -- called by the app ------------------------------------------------
    def set_title(self, text):
        win = self.window
        if win is not None:
            try:
                win.set_title(text or APP_TITLE)
            except Exception:                           # noqa: BLE001
                pass

    def is_maximized(self):
        return self._maximized

    def maximize(self):
        win = self.window
        if win is not None:
            try:
                win.maximize()
            except Exception:                           # noqa: BLE001
                pass

    def quit(self):
        self._quit.set()
        win = self.window
        if win is not None:
            try:
                win.destroy()
            except Exception:                           # noqa: BLE001
                pass

    @property
    def quitting(self):
        return self._quit.is_set()

    def wait(self):
        self._quit.wait()

    # -- native pickers ---------------------------------------------------
    def native_file_dialog(self, spec):
        import webview
        win = self.window
        if win is None:
            return NotImplemented
        mode = spec["mode"]
        kind = {"open": webview.FileDialog.OPEN,
                "save": webview.FileDialog.SAVE,
                "folder": webview.FileDialog.FOLDER}[mode]
        kwargs = {"directory": spec.get("initialdir") or "",
                  "allow_multiple": bool(spec.get("multiple"))}
        if mode == "save" and spec.get("initialfile"):
            kwargs["save_filename"] = spec["initialfile"]
        types = _filetypes_for_pywebview(spec.get("filetypes"))
        if types and mode != "folder":
            kwargs["file_types"] = types
        try:
            result = win.create_file_dialog(kind, **kwargs)
        except Exception:                               # noqa: BLE001
            # a malformed filter on one platform: try once without it
            kwargs.pop("file_types", None)
            result = win.create_file_dialog(kind, **kwargs)
        if result is None:
            return ""
        if isinstance(result, str):
            return result
        result = list(result)
        if spec.get("multiple"):
            return result
        return result[0] if result else ""


def build(ctx=None):
    """Context + server + app, ready for a host.  Returns (ctx, server)."""
    ctx = ctx or Context()
    compat.install(ctx)
    ctx.loop.start()
    server = WebServer(ctx)
    server.start()

    from ..app import App
    app = ctx.loop.call(lambda: App(ctx))
    reg = ctx.registry
    reg.register("shell.accept_disclaimer", app.accept_disclaimer)
    reg.register("fs.list", list_dir, on_loop=False)
    reg.register("fs.roots", list_roots, on_loop=False)
    reg.register("shell.zoom", app._on_ui_zoom_change)
    reg.register("shell.quit", lambda: ctx.host.quit() if ctx.host else None,
                 on_loop=False)
    # hot reload while developing (never in a frozen build): see devreload
    from . import devreload
    if devreload.enabled() and ctx.host is not None:
        ctx.dev_watcher = devreload.Watcher(ctx)
        ctx.dev_watcher.start()
        reg.register("shell.dev_restart", lambda: devreload.restart(ctx),
                     on_loop=False)
    return ctx, server


def url_for(ctx, server, query=""):
    base = "http://127.0.0.1:%d/?t=%s" % (server.port, ctx.token)
    return base + ("&" + query if query else "")


def _close_app(ctx):
    try:
        ctx.loop.call(ctx.app._on_close, timeout=60)
    except Exception:                                   # noqa: BLE001
        log.exception("closing the app")


def run_native(ctx, server, host):
    import webview
    geo = None
    try:
        geo = ctx.loop.call(ctx.app.saved_geometry)
    except Exception:                                   # noqa: BLE001
        geo = None
    width, height, x, y, maximized = geo or (1280, 860, None, None, False)
    width = max(MIN_SIZE[0], width)
    height = max(MIN_SIZE[1], height)
    win = webview.create_window(
        APP_TITLE, url_for(ctx, server), width=width, height=height,
        x=x, y=y, min_size=MIN_SIZE, background_color="#15171A",
        text_select=True, maximized=bool(maximized))
    host.window = win
    ctx.dialogs.native_file_dialog = host.native_file_dialog
    closing_done = threading.Event()

    def _on_closing():
        if not closing_done.is_set():
            _close_app(ctx)
            closing_done.set()
        return True

    def _on_maximized():
        host._maximized = True

    def _on_restored():
        host._maximized = False

    def _on_resized(w, h):
        try:
            ctx.loop.post(_remember_geometry, ctx, host, w, h)
        except Exception:                               # noqa: BLE001
            pass

    def _on_loaded():
        # A Python-side drop handler makes pywebview give every dropped File
        # a pywebviewFullPath, which the page's drop zones read (a browser
        # never exposes a dropped file's path).  preventDefault stops the
        # web view from navigating to a file dropped outside a drop zone.
        try:
            from webview.dom import DOMEventHandler
            win.dom.document.events.drop += DOMEventHandler(
                lambda _e: None, True, False)
        except Exception:                               # noqa: BLE001
            log.warning("drag and drop of files is not available",
                        exc_info=True)

    win.events.loaded += _on_loaded
    win.events.closing += _on_closing
    win.events.maximized += _on_maximized
    win.events.restored += _on_restored
    win.events.resized += _on_resized
    storage = os.path.join(os.path.dirname(
        __import__("pinball_decryptor.core.config", fromlist=["x"])
        .SETTINGS_FILE), "webview")
    debug = bool(os.environ.get("PAD_UI_DEBUG"))
    gui = os.environ.get("PAD_UI_GUI") or None
    if gui is None and sys.platform.startswith("linux"):
        gui = "qt"
        # Qt WebEngine's renderer sandbox needs unprivileged user namespaces,
        # which current Ubuntu blocks for an AppImage; the page is the app's
        # own local files only, so run without it (PAD_UI_SANDBOX=1 keeps it).
        if not os.environ.get("PAD_UI_SANDBOX"):
            os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    # the app's icon on the window, as Tk set it (Windows takes the .ico,
    # the Qt and GTK backends a picture)
    icon = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))),
        "icon.ico" if sys.platform == "win32" else "icon.png")
    webview.start(gui=gui, debug=debug, private_mode=False,
                  storage_path=storage,
                  icon=icon if os.path.isfile(icon) else None)
    if not closing_done.is_set():
        _close_app(ctx)
    host._quit.set()


def _remember_geometry(ctx, host, w, h):
    app = ctx.app
    win = host.window
    if app is None or win is None or host._maximized:
        return
    try:
        x, y = win.x, win.y
    except Exception:                                   # noqa: BLE001
        x = y = None
    geo = "%dx%d" % (w, h)
    if x is not None and y is not None:
        geo += "+%d+%d" % (x, y)
    app._last_normal_geometry = geo
    app._settings["window_geometry"] = geo
    app._settings["window_maximized"] = False


def run_browser(ctx, server, host, open_browser=True):
    import webbrowser
    url = url_for(ctx, server)
    if open_browser:
        webbrowser.open(url)
    print(url, flush=True)
    seen = {"any": False, "last_zero": None}

    def _clients(n):
        if n > 0:
            seen["any"] = True
            seen["last_zero"] = None
        else:
            seen["last_zero"] = time.monotonic()

    ctx.on_clients_changed = _clients
    try:
        while not host.quitting:
            time.sleep(0.5)
            if (open_browser and seen["any"] and seen["last_zero"]
                    and time.monotonic() - seen["last_zero"] > 90):
                break
    except KeyboardInterrupt:
        pass
    _close_app(ctx)


def _relaunch_with_checkout_venv(argv):
    """Development only: a checkout started by an interpreter without
    pywebview (the tree selector relaunches with the SAME interpreter it was
    started with) re-runs itself with the checkout's own .venv, which has
    the pinned requirements.  Never in an installed copy (no .venv there,
    and frozen builds are skipped).  Returns True when it relaunched."""
    import subprocess
    if getattr(sys, "frozen", False) or os.environ.get("PAD_UI_VENV_RELAUNCHED"):
        return False
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    venv = os.path.join(root, ".venv")
    exe = (os.path.join(venv, "Scripts", "pythonw.exe")
           if sys.platform == "win32" else os.path.join(venv, "bin", "python"))
    if not os.path.isfile(exe):
        return False
    if os.path.normcase(os.path.abspath(sys.prefix)) == os.path.normcase(venv):
        return False
    env = dict(os.environ)
    env["PAD_UI_VENV_RELAUNCHED"] = "1"
    try:
        from ..worktree_picker import ENV_PICKED
        env[ENV_PICKED] = "1"
    except Exception:                                   # noqa: BLE001
        pass
    subprocess.Popen([exe, "-m", "pinball_decryptor"] + list(argv or []),
                     cwd=root, env=env)
    return True


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if "--serve" not in argv and "--browser" not in argv:
        try:
            import webview  # noqa: F401
        except Exception:                               # noqa: BLE001
            if _relaunch_with_checkout_venv(argv):
                return 0
    parser = argparse.ArgumentParser(prog="pinball_decryptor")
    parser.add_argument("--browser", action="store_true",
                        help="show the app in the system browser")
    parser.add_argument("--serve", action="store_true",
                        help="run the server only and print its URL")
    args, _rest = parser.parse_known_args(argv)

    logging.basicConfig(level=logging.WARNING)
    mode = "serve" if args.serve else "browser" if args.browser else "native"
    ctx = Context()
    host = Host(ctx, mode)
    ctx.host = host
    ctx, server = build(ctx)
    try:
        if mode == "native":
            try:
                import webview  # noqa: F401
            except Exception as e:                      # noqa: BLE001
                ctx.loop.post(ctx.window.append_log,
                              "The app window could not start (%s); showing "
                              "the app in your browser instead." % e,
                              "warning")
                mode = "browser"
        if mode == "native":
            try:
                run_native(ctx, server, host)
            except Exception as e:                      # noqa: BLE001
                log.exception("native window failed")
                if host.quitting:
                    return 0
                ctx.loop.post(ctx.window.append_log,
                              "The app window could not start (%s); showing "
                              "the app in your browser instead." % e,
                              "warning")
                run_browser(ctx, server, host)
        else:
            run_browser(ctx, server, host, open_browser=(mode == "browser"))
    finally:
        watcher = getattr(ctx, "dev_watcher", None)
        if watcher is not None:
            watcher.stop()
        ctx.bus.close()
        ctx.loop.stop()
        server.stop()
    if getattr(ctx, "dev_relaunch", False):
        from . import devreload
        devreload.relaunch()
    return 0


if __name__ == "__main__":                           # pragma: no cover
    sys.exit(main())
