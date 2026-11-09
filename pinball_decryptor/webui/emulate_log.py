"""PAD-1071: the Emulate tab's Sound and video log, in a window of its own.

Every sound and clip the game started during a run, in order, filterable, and each one opened from
its row: a sound plays in the window itself (its decoded WAV), and Open takes the row to the Audio
or Video tab, selected and playing there. The rows are read by
:class:`..plugins.stern.emulator_log.Log` from the files the playfield window writes beside the
volume file; they stay until the next Start, also across an app restart.

The window is a pywebview window on ``static/js/tabs/emulate_log.html`` beside the main one, so it
can sit next to the game and the playfield wherever the user puts it (the Spike 1 view windows'
way, :class:`.emulate_jjp_spike1view.ViewWindows`). Without a native main window (``--browser``,
``--serve``) the page opens it in a browser tab instead.
"""

import functools
import logging
import os
import sys
import threading
from urllib.parse import quote, urlsplit

from .rpc import rpc

log = logging.getLogger(__name__)

PAGE = "/static/js/tabs/emulate_log.html"
TITLE = "Sound and video log"
SIZE = (760, 640)
MIN_SIZE = (420, 260)


def to_front(win):
    """Bring pywebview window *win* in front of the others, as it is: a minimized window comes back,
    a maximized one stays maximized (round 3: Open went through ``restore()``, which on Windows
    un-maximizes - Jim-Beam's main window "shrinked" at every Open). On Windows the window is put
    topmost and back first, because SetForegroundWindow alone is refused while another program has
    the focus (emulate_ap.raise_window's recipe); elsewhere ``show()``."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            from .winbrand import _hwnd
            h = _hwnd(win)
            if h:
                u = ctypes.windll.user32
                u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_uint]
                if u.IsIconic(wintypes.HWND(h)):
                    u.ShowWindow(wintypes.HWND(h), 9)                     # SW_RESTORE: minimized only
                flags = 0x0001 | 0x0002 | 0x0040                         # NOSIZE | NOMOVE | SHOWWINDOW
                u.SetWindowPos(wintypes.HWND(h), wintypes.HWND(-1), 0, 0, 0, 0, flags)   # TOPMOST
                u.SetWindowPos(wintypes.HWND(h), wintypes.HWND(-2), 0, 0, 0, 0, flags)   # NOTOPMOST
                u.SetForegroundWindow(wintypes.HWND(h))
                return True
        except Exception:                                  # noqa: BLE001
            pass
    try:
        win.show()
        return True
    except Exception:                                      # noqa: BLE001
        return False


class LogWindow:
    """The one native window. Every pywebview call is made on this object's own thread, never on
    the UI loop (ViewWindows' rule: a window call from the loop hangs the quit)."""

    def __init__(self, ctx, log_line=None):
        self._ctx = ctx
        self._log_line = log_line or (lambda _m: None)
        self._cv = threading.Condition()
        self._want = False
        self._dirty = False
        self._shut = False
        self._thread = None
        self._win = None
        self._broken = False

    def _host(self):
        return getattr(self._ctx, "host", None)

    def _origin(self):
        win = getattr(self._host(), "window", None)
        url = getattr(win, "original_url", None) or ""
        try:
            parts = urlsplit(url)
        except ValueError:
            return ""
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return ""
        return "%s://%s" % (parts.scheme, parts.netloc)

    def available(self):
        """True when there is a native main window to open this one beside."""
        if self._shut or self._broken:
            return False
        host = self._host()
        if host is None or getattr(host, "mode", "") != "native" or getattr(host, "quitting", False):
            return False
        return bool(self._origin())

    def url(self):
        """The page's address with this session's token (the browser fallback opens it)."""
        return "%s?t=%s" % (PAGE, quote(getattr(self._ctx, "token", "") or ""))

    def show(self):
        """Open it, or bring it back on screen and to the front when it is open."""
        with self._cv:
            self._want = True
            self._dirty = True
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="pad-log-window", daemon=True)
                self._thread.start()
            self._cv.notify()

    def shutdown(self):
        """App quit: close it and open nothing more. Never waits."""
        self._shut = True
        with self._cv:
            self._want = False
            self._dirty = True
            self._cv.notify()

    def is_open(self):
        return self._win is not None

    def _run(self):
        while True:
            with self._cv:
                while not self._dirty:
                    self._cv.wait()
                self._dirty = False
                want = self._want and not self._shut
            try:
                if want:
                    self._open_or_raise()
                elif self._win is not None:
                    win, self._win = self._win, None
                    win.destroy()
            except Exception:                              # noqa: BLE001
                log.exception("the sound and video log window")
            if self._shut:
                return

    def _open_or_raise(self):
        win = self._win
        if win is not None:
            to_front(win)                 # where and as big as the user left it
            return
        import webview
        origin = self._origin()
        if not origin:
            return
        theme = self._ctx.store.get("shell", "theme")
        bg = "#f4f4f1" if theme == "light" else "#15171a"
        try:
            win = webview.create_window(TITLE, origin + self.url(), width=SIZE[0], height=SIZE[1],
                                        min_size=MIN_SIZE, background_color=bg)
        except Exception as exc:                           # noqa: BLE001
            self._broken = True
            self._log_line("[emulate] could not open the Sound and video log window (%s): it "
                           "opens in your browser instead." % exc)
            return
        if win is None:
            return
        # no taskbar group of its own: it is the app's window (the game's and the playfield's are not)
        win.events.closed += functools.partial(self._closed, win)
        self._win = win
        with self._cv:
            self._want = False

    def _closed(self, win):
        if self._win is win:
            self._win = None


class EmulateLogMixin:
    """The Emulate tab's half: the rows for the page, the window, Open. The tab calls
    :meth:`_elog_init` once and :meth:`_elog_new_run` at each Start."""

    def _elog_init(self):
        self._elog = None
        self._elog_lock = threading.Lock()
        self._elog_win = LogWindow(self.ctx, log_line=self._log)

    def _elog_dir_slot(self):
        from ..core import rigslot
        from .tabs.emulate import audio_ctl_file
        return os.path.dirname(audio_ctl_file()), rigslot.slot()

    def _elog_new_run(self, project):
        """At Start: the last run's sounds go (its clips went with the clip names), and the window
        lists this run's from the top."""
        from ..plugins.stern import emulator_log as EL
        d, n = self._elog_dir_slot()
        EL.clear_sounds(d, n)
        with self._elog_lock:
            self._elog = EL.Log(d, n, project)

    def _elog_stage_env(self, env, card):
        """The launch's ``PAD_SOUNDLOG_STAGE``: for a boot that has no runtime of its own (a stock
        card), the pinned runtime, the card's port and ``soundlog.only`` - the object then hooks the
        game's sound worker and nothing else (``tools/spike2_emu/modes/soundlog.sh``). A launch that
        brings a runtime (the override set's modes, Try it) needs none, and neither does a card
        with modes of its own (the rig asks the card first and uses this only when it has none).
        ``[]`` when this build has no port: the run then lists its clips and no sounds. Blocking:
        it reads the card (the Start worker calls it)."""
        import shutil
        import sys
        import tempfile
        from . import emulate_rig as rig
        from ..plugins.stern import mode_runtime as MR
        from ..plugins.stern import mode_tryit as MT
        if any(str(e).startswith("PAD_MODE_SO=") and str(e) != "PAD_MODE_SO=" for e in env):
            return []
        try:
            game_dir, version, _part = MT.card_title(card)
            port = MR.port_file(game_dir, version)
            obj = MR.prebuilt_object()
        except Exception as exc:                           # noqa: BLE001
            self._log("[emulate] the Sound and video log lists no sounds this run: the card's "
                      "game could not be read (%s)" % exc)
            return []
        if not port:
            self._log("[emulate] the Sound and video log lists no sounds this run: there is no "
                      "port for %s %s, so the game's sound requests cannot be read (its clips "
                      "are listed)" % (game_dir or "this card", version or ""))
            return []
        _d, n = self._elog_dir_slot()
        stage = os.path.join(tempfile.gettempdir(), "pad_soundlog_stage_%d" % n)
        try:
            if os.path.isdir(stage):
                shutil.rmtree(stage)
            os.makedirs(stage)
            shutil.copyfile(obj, os.path.join(stage, MT.OBJECT_NAME))
            shutil.copyfile(port, os.path.join(stage, MT.PORT_NAME))
            with open(os.path.join(stage, "soundlog.only"), "w", encoding="utf-8") as f:
                f.write("the Emulate tab's Sound and video log (PAD-1071)\n")
        except OSError as exc:
            self._log("[emulate] the Sound and video log lists no sounds this run: its folder %s "
                      "could not be made (%s)" % (stage, exc))
            return []
        return ["PAD_SOUNDLOG_STAGE=%s" % (rig.wsl_path(stage) if sys.platform == "win32" else stage)]

    def _elog_get(self):
        """The log, made on first use from the files the last run left (an app started after a run
        still lists it)."""
        from ..plugins.stern import emulator_log as EL
        with self._elog_lock:
            if self._elog is None:
                d, n = self._elog_dir_slot()
                self._elog = EL.Log(d, n, self._assets())
            return self._elog

    @rpc(loop=False)
    def log_rows(self, after=-1):
        """The page's poll: the rows past *after*, and what the page shows above them."""
        lg = self._elog_get()
        with self._elog_lock:
            try:
                lg.poll()
            except Exception:                              # noqa: BLE001
                log.exception("the sound and video log")
            out = lg.page(int(after) if isinstance(after, (int, float)) else -1)
            project = lg.names.project
        out["project"] = os.path.basename(project.rstrip("\\/")) if project else ""
        out["root"] = project or ""
        out["running"] = bool(getattr(self, "_last_up", False))
        return out

    @rpc
    def log_open(self):
        """Open (or bring back) the window. ``{"url": ...}`` when there is no native window to open
        and the page should open the address itself."""
        if self._elog_win.available():
            self._elog_win.show()
            return {"url": ""}
        return {"url": self._elog_win.url()}

    @rpc
    def log_show(self, kind, rel):
        """Open: the row on its tab, selected and playing (the Audio tab plays what the card will:
        its replacement with "Play replacements" ticked)."""
        ns = "audio" if kind == "sound" else "video"
        svc = getattr(self.window, "_by_ns", {}).get(ns)
        if svc is None or not rel:
            return False
        self.window.select_tab(ns)
        try:
            ok = svc.play_row(rel) if ns == "audio" else svc.play(rel)
        except Exception:                                  # noqa: BLE001
            log.exception("log_show %s %s", ns, rel)
            ok = False
        if not ok:
            self._log("[emulate] %s is not on the %s tab's list yet: it is still reading the "
                      "project, or the file is not in it." % (rel, svc.label))
        self._elog_raise_main()
        return bool(ok)

    def _elog_raise_main(self):
        win = getattr(getattr(self.ctx, "host", None), "window", None)
        if win is None:
            return

        threading.Thread(target=to_front, args=(win,), name="pad-log-front", daemon=True).start()
