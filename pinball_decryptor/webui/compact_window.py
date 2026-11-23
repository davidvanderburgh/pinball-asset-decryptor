"""Right-click a card image in Explorer > Compact with PAD (PAD-1522).

    pythonw "Pinball Asset Decryptor.pyw" --compact <card.raw> [more...]

Stores the card compact WHERE IT IS (core.sparse_card.compact_file: the same
file, the same bytes, only its data takes disk space) in a small window of
its own: the card's name, a progress bar, and what it came to.  The app
itself is not started, and nothing here needs Administrator, so the launcher
skips its prompt for this one (installer/launcher.vbs).

Explorer starts one of these per selected file.  The first is the window;
each later one hands its card to it (:func:`hand_over`, a note in
:func:`spool_dir` the window picks up) and ends, so five cards selected are
one window working down a list, not five reading the same drive at once.

The work and the wording are :class:`Jobs` and :func:`view` (no window,
tested as they are); the window, a Windows task dialog (the shipped Python
has no Tk), only draws them.
"""

import json
import logging
import os
import queue
import sys
import threading
import time

from ..core import sparse_card

log = logging.getLogger(__name__)

FLAG = "--compact"
TITLE = "Compact card image"
NOTE = ("A compact card is the same file with the same bytes: only the "
        "card's data takes disk space. PAD builds, emulates, extracts and "
        "writes it as it is.")
#: how long a later launch waits for the window to take its card
HAND_OVER_WAIT = 4.0
MUTEX = "Local\\PinballAssetDecryptor.CompactWindow"

WAITING, WORKING, DONE, FAILED, STOPPED = (
    "waiting", "working", "done", "failed", "stopped")

# The compact badge on a card's icon is drawn by Explorer, which learns of
# it only when it starts (webui/shell_icon.py, PAD-1526).  Until it has
# restarted since PAD listed the badge, the finished window offers to restart
# it: nobody should have to know to sign out first.
NO_OFFER, OFFER, RESTARTING, RESTARTED, NOT_RESTARTED = (
    "", "offer", "restarting", "restarted", "failed")
OFFER_BUTTON = "Restart Explorer"
OFFER_TEXT = {
    OFFER: ("To show the green compact badge on the card's icon, Windows "
            "Explorer has to restart once. Your open folders come back."),
    RESTARTING: "Restarting Explorer...",
    RESTARTED: "Explorer restarted. The card's icon now shows the green "
               "compact badge.",
    NOT_RESTARTED: "Explorer could not be restarted. Sign out and back in "
                   "to see the green compact badge.",
}


def fmt(n):
    """Binary sizes, as the app's Manage disk space shows them."""
    if n >= 1024 ** 3:
        return "%.2f GiB" % (n / 1024 ** 3)
    if n >= 1024 ** 2:
        return "%.1f MiB" % (n / 1024 ** 2)
    if n >= 1024:
        return "%.0f KiB" % (n / 1024)
    return "%d B" % n


def paths_arg(argv):
    """The card images on a ``--compact`` command line, in order."""
    out = []
    for a in argv or ():
        if not a or a.startswith("-"):
            continue
        p = os.path.abspath(a.strip('"'))
        if p not in out:
            out.append(p)
    return out


def result_text(res):
    """One line on what compacting came to, from a CompactResult."""
    if not res.sparse_ok and res.after >= res.size:
        return ("Left as it was: this drive cannot hold compact files "
                "(exFAT or FAT32, like most USB sticks).")
    if res.saved >= sparse_card.MIN_HOLE:
        return ("Compact: %s on disk for a %s card, %s freed."
                % (fmt(res.after), fmt(res.size), fmt(res.saved)))
    if res.after + sparse_card.MIN_HOLE <= res.size:
        return ("Already compact: %s on disk for a %s card."
                % (fmt(res.after), fmt(res.size)))
    return ("Nothing to free: this %s card is full of data."
            % fmt(res.size))


def error_text(err):
    if isinstance(err, PermissionError):
        return ("Could not open it: another program is using this card, or "
                "it is read-only. Close that program and try again.")
    if isinstance(err, FileNotFoundError):
        return "This file is no longer there."
    if isinstance(err, OSError) and err.strerror:
        return "Could not compact it: %s." % err.strerror.rstrip(".")
    return "Could not compact it: %s." % err


class Stopped(Exception):
    """The window was closed while a card was being read."""


class Job:
    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        self.state = WAITING
        self.pct = None
        self.text = "Waiting…"
        self.saved = 0


class Jobs:
    """The list of cards and the one worker that compacts them in turn.

    Everything the worker finds goes on :attr:`events` as ``(job, what)``;
    whoever shows it (the window's timer, a test) drains that on its own
    thread and reads the job's fields."""

    def __init__(self, compact=None):
        self.jobs = []
        self.events = queue.Queue()
        self._compact = compact or sparse_card.compact_file
        self._lock = threading.Lock()
        self._worker = None
        self._stop = False

    def add(self, path):
        """Queue *path*; False when it is already listed and not finished
        (the same card picked twice)."""
        path = os.path.abspath(path)
        with self._lock:
            for j in self.jobs:
                if os.path.normcase(j.path) == os.path.normcase(path) and \
                        j.state in (WAITING, WORKING):
                    return False
            job = Job(path)
            self.jobs.append(job)
            start = self._worker is None
            if start:
                self._worker = threading.Thread(
                    target=self._run, name="pad-compact", daemon=True)
        self.events.put((job, "added"))
        if start:
            self._worker.start()
        return True

    @property
    def busy(self):
        with self._lock:
            return any(j.state in (WAITING, WORKING) for j in self.jobs)

    def stop(self):
        """Stop after the block being read; the card in hand is left as it
        was (nothing is changed until its whole scan is done)."""
        self._stop = True

    def wait(self, timeout=None):
        w = self._worker
        if w is not None:
            w.join(timeout)

    def summary(self):
        """The line under the list once nothing is left to do."""
        with self._lock:
            jobs = list(self.jobs)
        done = [j for j in jobs if j.state == DONE]
        failed = [j for j in jobs if j.state == FAILED]
        if len(jobs) <= 1:
            return ""
        text = "%d of %d card images done, %s freed." % (
            len(done), len(jobs), fmt(sum(j.saved for j in done)))
        if failed:
            text += " %d could not be compacted." % len(failed)
        return text

    # ------------------------------------------------------------------
    def _next(self):
        with self._lock:
            for j in self.jobs:
                if j.state == WAITING:
                    j.state = WORKING
                    return j
            # decided under the lock add() takes: a card added now starts a
            # new worker, never lands on one that has just given up
            self._worker = None
            return None

    def _run(self):
        while True:
            job = self._next()
            if job is None:
                return
            if self._stop:
                job.state, job.text = STOPPED, "Stopped."
                self.events.put((job, "end"))
                continue
            self._one(job)

    def _one(self, job):
        job.pct, job.text = 0, "Reading the card…"
        self.events.put((job, "start"))
        last = [-1]

        def progress(done, total):
            if self._stop:
                raise Stopped()
            pct = int(done * 100 // total) if total else 100
            if pct != last[0]:
                last[0] = pct
                job.pct = pct
                job.text = "Reading the card… %d%%" % pct
                self.events.put((job, "progress"))

        try:
            if not os.path.isfile(job.path):
                raise FileNotFoundError(job.path)
            res = self._compact(job.path, progress=progress)
        except Stopped:
            job.state, job.pct = STOPPED, None
            job.text = "Stopped: this card is as it was."
        except Exception as e:                          # noqa: BLE001
            log.warning("compact %s", job.path, exc_info=True)
            job.state, job.pct, job.text = FAILED, None, error_text(e)
        else:
            job.state, job.pct = DONE, 100
            job.saved = res.saved
            job.text = result_text(res)
            if not res.sparse_ok and res.after >= res.size:
                job.state = FAILED
        self.events.put((job, "end"))


# ----------------------------------------------------------------------
# one window for every card picked: later launches hand theirs over
# ----------------------------------------------------------------------
def spool_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "pinball_decryptor", "compact_queue")


def claim():
    """Become THE compact window; a handle to keep while it is open, or
    None when another one already is.  Only Windows has several launches
    (Explorer's one per file); elsewhere every run is its own window."""
    if sys.platform != "win32":
        return object()
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                     ctypes.c_wchar_p]
        h = k32.CreateMutexW(None, False, MUTEX)
        if h and ctypes.get_last_error() == 183:        # ALREADY_EXISTS
            k32.CloseHandle(ctypes.c_void_p(h))
            return None
        return h or object()
    except Exception:                                   # noqa: BLE001
        return object()


def release(handle):
    if sys.platform == "win32" and isinstance(handle, int):
        try:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
        except Exception:                               # noqa: BLE001
            pass


def hand_over(paths, folder=None, wait=HAND_OVER_WAIT):
    """Give *paths* to the window that is already open.  True when it took
    them; False when it did not within *wait* (it was closing), and then
    nothing is left behind for a later window to find."""
    folder = folder or spool_dir()
    try:
        os.makedirs(folder, exist_ok=True)
        note = os.path.join(folder, "%d-%d.json" % (time.time_ns(),
                                                    os.getpid()))
        tmp = note + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"paths": list(paths)}, f)
        os.replace(tmp, note)
    except OSError:
        return False
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if not os.path.exists(note):
            return True
        time.sleep(0.05)
    try:
        os.remove(note)
    except FileNotFoundError:
        return True                 # taken at the last moment
    except OSError:
        pass
    return False


def take_handed(folder=None):
    """The cards later launches left for the window, oldest first; each note
    is removed as it is read (that is how its sender knows)."""
    folder = folder or spool_dir()
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith(".json"))
    except OSError:
        return []
    out = []
    for name in names:
        note = os.path.join(folder, name)
        try:
            with open(note, encoding="utf-8") as f:
                body = json.load(f)
            os.remove(note)
        except (OSError, ValueError):
            continue
        for p in body.get("paths") or ():
            if isinstance(p, str) and p:
                out.append(p)
    return out


# ----------------------------------------------------------------------
# what the window says
# ----------------------------------------------------------------------
MARK = {WAITING: "•", WORKING: "▸", DONE: "✓",
        FAILED: "✕", STOPPED: "•"}


def view(jobs, offer=NO_OFFER):
    """What the window shows now: ``{"busy", "instruction", "content",
    "pct", "warn", "offer"}``.  One card reads as a sentence about that
    card; several as a list, a mark and a line each.  *offer* (OFFER,
    RESTARTED, NOT_RESTARTED) adds the line about Explorer's restart once
    the work is done."""
    with jobs._lock:
        cards = list(jobs.jobs)
    busy = any(j.state in (WAITING, WORKING) for j in cards)
    now = next((j for j in cards if j.state == WORKING), None)
    warn = any(j.state == FAILED for j in cards)
    pct = (now.pct or 0) if now is not None else (0 if busy else 100)
    if len(cards) == 1:
        j = cards[0]
        if j.state in (WAITING, WORKING):
            head = "Compacting %s" % j.name
        elif j.state == FAILED:
            head = "%s was not compacted" % j.name
        elif j.state == STOPPED:
            head = "Stopped"
        elif j.text.startswith("Nothing to free"):
            head = "%s stays as it is" % j.name
        else:
            head = "%s is stored compact" % j.name
        body = "%s\n\n%s" % (os.path.dirname(j.path), j.text)
    else:
        if busy:
            at = (cards.index(now) + 1) if now is not None else \
                sum(1 for j in cards if j.state not in (WAITING,)) + 1
            head = "Compacting card image %d of %d" % (min(at, len(cards)),
                                                       len(cards))
        else:
            head = jobs.summary()
        body = "\n".join("%s  %s\n      %s" % (MARK[j.state], j.name, j.text)
                         for j in cards)
    if busy:
        offer = NO_OFFER
    if offer:
        body = "%s\n\n%s" % (body, OFFER_TEXT[offer])
    return {"busy": busy, "instruction": head, "content": body, "pct": pct,
            "warn": warn and not busy, "offer": offer}


# ----------------------------------------------------------------------
# the window: a Windows task dialog (the shipped Python has no Tk)
# ----------------------------------------------------------------------
def _dpi_aware():
    try:
        import ctypes
        try:
            # per monitor v2: the dialog is sharp on every screen
            if ctypes.windll.user32.SetProcessDpiAwarenessContext(
                    ctypes.c_void_p(-4)):
                return
        except Exception:                               # noqa: BLE001
            pass
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:                                   # noqa: BLE001
        pass


def _icon_path():
    pkg = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("card_image_compact.ico", "icon.ico"):
        p = os.path.join(pkg, name)
        if os.path.isfile(p):
            return p
    return None


_WM_USER = 0x0400
_TDM_NAVIGATE_PAGE = _WM_USER + 101
_TDM_CLICK_BUTTON = _WM_USER + 102
_TDM_SET_PROGRESS_BAR_POS = _WM_USER + 106
_TDM_SET_ELEMENT_TEXT = _WM_USER + 108
_TDE_CONTENT, _TDE_MAIN_INSTRUCTION = 0, 3
_TDN_CREATED, _TDN_NAVIGATED, _TDN_BUTTON_CLICKED, _TDN_TIMER = 0, 1, 2, 4
_TDF_USE_HICON_MAIN = 0x0002
_TDF_ALLOW_DIALOG_CANCELLATION = 0x0008
_TDF_SHOW_PROGRESS_BAR = 0x0200
_TDF_CALLBACK_TIMER = 0x0800
_TDF_CAN_BE_MINIMIZED = 0x8000
_TD_WARNING_ICON = 0xFFFF           # MAKEINTRESOURCE(-1)
_BUTTON = 100                       # Stop while working, Close after
_OFFER_BUTTON = 101                 # Restart Explorer, on the finished page
_S_OK, _S_FALSE = 0, 1


def _structs():
    import ctypes
    from ctypes import wintypes

    class Button(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("id", ctypes.c_int), ("text", wintypes.LPCWSTR)]

    callback = ctypes.WINFUNCTYPE(
        ctypes.c_long, wintypes.HWND, ctypes.c_uint, ctypes.c_size_t,
        ctypes.c_ssize_t, ctypes.c_ssize_t)

    class Config(ctypes.Structure):     # TASKDIALOGCONFIG (commctrl.h)
        _pack_ = 1
        _fields_ = [
            ("cbSize", ctypes.c_uint), ("hwndParent", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE), ("dwFlags", ctypes.c_int),
            ("dwCommonButtons", ctypes.c_int),
            ("pszWindowTitle", wintypes.LPCWSTR),
            ("mainIcon", ctypes.c_void_p),
            ("pszMainInstruction", wintypes.LPCWSTR),
            ("pszContent", wintypes.LPCWSTR), ("cButtons", ctypes.c_uint),
            ("pButtons", ctypes.POINTER(Button)),
            ("nDefaultButton", ctypes.c_int),
            ("cRadioButtons", ctypes.c_uint),
            ("pRadioButtons", ctypes.c_void_p),
            ("nDefaultRadioButton", ctypes.c_int),
            ("pszVerificationText", wintypes.LPCWSTR),
            ("pszExpandedInformation", wintypes.LPCWSTR),
            ("pszExpandedControlText", wintypes.LPCWSTR),
            ("pszCollapsedControlText", wintypes.LPCWSTR),
            ("footerIcon", ctypes.c_void_p),
            ("pszFooter", wintypes.LPCWSTR), ("pfCallback", callback),
            ("lpCallbackData", ctypes.c_ssize_t), ("cxWidth", ctypes.c_uint)]

    return Button, Config, callback


class TaskWindow:
    """The dialog: the card's own compact icon, a headline, the card (or the
    list of cards), a progress bar while one is read, the note, and one
    button - Stop while it works, Close once it is done.

    Windows calls :meth:`_event` on a timer; everything is drawn from
    :func:`view` there, on the dialog's own thread.  A card handed over by a
    later launch (:func:`take_handed`) joins the list and the dialog comes
    forward."""

    WIDTH = 300                     # dialog units

    def __init__(self, jobs, spool=None, poll_spool=True, on_created=None,
                 on_page=None, badge_waits=None, restart=None):
        from . import shell_icon
        # asked once, when the work is done; tests pass their own
        self.badge_waits = badge_waits or shell_icon.badge_waits_for_explorer
        self.restart = restart or shell_icon.restart_explorer
        self.offer = None               # None: not asked yet
        self.jobs = jobs
        self.spool = spool
        self.poll_spool = poll_spool
        self.on_created = on_created    # (hwnd): tests and proof shots
        self.on_page = on_page          # (hwnd, view) after each page change
        self.hwnd = None
        self._shown = None              # the view last drawn
        self._keep = []                 # ctypes objects a live page points at
        self._icon = None

    # -- pages ---------------------------------------------------------
    def _config(self, v):
        import ctypes
        Button, Config, _cb = self._types
        label = "Stop" if v["busy"] else "Close"
        if v["offer"] == OFFER:
            buttons = (Button * 2)(Button(_OFFER_BUTTON, OFFER_BUTTON),
                                   Button(_BUTTON, label))
        else:
            buttons = (Button * 1)(Button(_BUTTON, label))
        cfg = Config()
        cfg.cbSize = ctypes.sizeof(Config)
        cfg.dwFlags = (_TDF_ALLOW_DIALOG_CANCELLATION | _TDF_CALLBACK_TIMER
                       | _TDF_CAN_BE_MINIMIZED)
        if v["busy"]:
            cfg.dwFlags |= _TDF_SHOW_PROGRESS_BAR
        if v["warn"] or not self._icon:
            cfg.mainIcon = _TD_WARNING_ICON if v["warn"] else None
        else:
            cfg.dwFlags |= _TDF_USE_HICON_MAIN
            cfg.mainIcon = self._icon
        cfg.pszWindowTitle = TITLE
        cfg.pszMainInstruction = v["instruction"]
        cfg.pszContent = v["content"]
        cfg.cButtons = len(buttons)
        cfg.pButtons = buttons
        cfg.nDefaultButton = _BUTTON
        cfg.pszFooter = NOTE
        cfg.pfCallback = self._callback
        cfg.cxWidth = self.WIDTH
        self._keep = [buttons, cfg]
        return cfg

    def _send(self, msg, wparam=0, lparam=0):
        import ctypes
        fn = ctypes.windll.user32.SendMessageW
        fn.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t,
                       ctypes.c_void_p]
        fn.restype = ctypes.c_ssize_t
        return fn(self.hwnd, msg, wparam, lparam)

    def _draw(self, v):
        import ctypes
        old = self._shown
        if old is None or old["busy"] != v["busy"] or \
                old["warn"] != v["warn"] or old["offer"] != v["offer"]:
            # another kind of page (working <> done, a button more or
            # less): build it anew
            cfg = self._config(v)
            self._shown = v
            self._send(_TDM_NAVIGATE_PAGE, 0, ctypes.addressof(cfg))
            return
        for key, element in (("instruction", _TDE_MAIN_INSTRUCTION),
                             ("content", _TDE_CONTENT)):
            if old[key] != v[key]:
                text = ctypes.create_unicode_buffer(v[key])
                self._send(_TDM_SET_ELEMENT_TEXT, element,
                           ctypes.addressof(text))
        if v["busy"] and old["pct"] != v["pct"]:
            self._send(_TDM_SET_PROGRESS_BAR_POS, int(v["pct"]), 0)
        self._shown = v

    # -- Windows calls this ---------------------------------------------
    def _event(self, hwnd, msg, wparam, _lparam, _data):
        try:
            self.hwnd = hwnd
            if msg == _TDN_CREATED:
                self._window_icon()
                if self.on_created:
                    self.on_created(hwnd)
            elif msg == _TDN_NAVIGATED:
                self._send(_TDM_SET_PROGRESS_BAR_POS,
                           int(self._shown["pct"]), 0)
                if self.on_page:
                    self.on_page(hwnd, self._shown)
            elif msg == _TDN_TIMER:
                self._tick()
            elif msg == _TDN_BUTTON_CLICKED and wparam == _OFFER_BUTTON:
                # off this thread: Windows may take a while to close
                # Explorer, and the window must stay alive meanwhile (the
                # timer draws what came of it)
                if self.offer == OFFER:
                    self.offer = RESTARTING
                    threading.Thread(target=self._restart, daemon=True,
                                     name="pad-restart-explorer").start()
                    self._draw(self._view())
                return _S_FALSE                 # the window stays
            elif msg == _TDN_BUTTON_CLICKED:
                # Stop, Close, Esc and the X all end here
                if self.jobs.busy:
                    self.jobs.stop()
                    self.jobs.wait(15)
                return _S_OK
        except Exception:                               # noqa: BLE001
            log.exception("compact window")
        return _S_OK if msg != _TDN_TIMER else _S_FALSE

    def _tick(self):
        if self.poll_spool:
            new = False
            for p in take_handed(self.spool):
                new = self.jobs.add(p) or new
            if new:
                self.come_forward()
        while True:
            try:
                self.jobs.events.get_nowait()
            except queue.Empty:
                break
        self._draw(self._view())

    def _restart(self):
        try:
            ok = self.restart()
        except Exception:                               # noqa: BLE001
            log.exception("restart Explorer")
            ok = False
        self.offer = RESTARTED if ok else NOT_RESTARTED

    def _view(self):
        """:func:`view`, with the offer to restart Explorer once the work is
        done and a card came out compact."""
        if self.jobs.busy:
            # more cards were handed over: ask again when they are done
            if self.offer == OFFER:
                self.offer = None
        elif self.offer is None:
            done = any(j.state == DONE for j in self.jobs.jobs)
            try:
                waits = done and self.badge_waits()
            except Exception:                           # noqa: BLE001
                waits = False
            self.offer = OFFER if waits else NO_OFFER
        return view(self.jobs, self.offer or NO_OFFER)

    def _window_icon(self):
        if not self._icon:
            return
        import ctypes
        fn = ctypes.windll.user32.SendMessageW
        fn.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t,
                       ctypes.c_void_p]
        for which in (0, 1):                            # ICON_SMALL, ICON_BIG
            fn(self.hwnd, 0x0080, which, self._icon)    # WM_SETICON

    def come_forward(self):
        try:
            import ctypes
            u32 = ctypes.windll.user32
            if u32.IsIconic(ctypes.c_void_p(self.hwnd)):
                u32.ShowWindow(ctypes.c_void_p(self.hwnd), 9)   # SW_RESTORE
            u32.SetForegroundWindow(ctypes.c_void_p(self.hwnd))
        except Exception:                               # noqa: BLE001
            pass

    def close(self):
        """Press the dialog's button (tests, proof shots)."""
        self._send(_TDM_CLICK_BUTTON, _BUTTON, 0)

    def run(self):
        """Show the dialog until it is closed.  False when this Windows has
        no task dialog to show (then nothing was shown at all)."""
        import ctypes
        try:
            self._types = _structs()
            fn = ctypes.windll.comctl32.TaskDialogIndirect
        except (AttributeError, OSError):
            return False
        Button, Config, callback = self._types
        self._callback = callback(self._event)
        icon = _icon_path()
        if icon:
            load = ctypes.windll.user32.LoadImageW
            load.restype = ctypes.c_void_p
            load.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                             ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            # IMAGE_ICON, LR_LOADFROMFILE | LR_DEFAULTSIZE
            self._icon = load(None, icon, 1, 0, 0, 0x10 | 0x40)
        v = self._view()
        cfg = self._config(v)
        self._shown = v
        fn.argtypes = [ctypes.POINTER(Config), ctypes.POINTER(ctypes.c_int),
                       ctypes.POINTER(ctypes.c_int),
                       ctypes.POINTER(ctypes.c_int)]
        fn.restype = ctypes.c_long
        hr = fn(ctypes.byref(cfg), None, None, None)
        if hr != 0:
            log.warning("TaskDialogIndirect 0x%08x", hr & 0xffffffff)
            return False
        return True


def _message(text, warn=False):
    """The fallback's one box, for a Windows with no task dialog."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, text, TITLE, 0x30 if warn else 0x40)
    except Exception:                                   # noqa: BLE001
        pass


def run_plain(jobs, out=None):
    """No window (Linux, a Mac, a terminal): work through the cards and
    print what each came to."""
    out = out or sys.stdout
    jobs.wait()
    for j in jobs.jobs:
        print("%s: %s" % (j.name, j.text), file=out)
    return 0 if all(j.state == DONE for j in jobs.jobs) else 1


def main(argv=None):
    """The ``--compact`` launch.  Returns the process's exit code."""
    argv = sys.argv[1:] if argv is None else argv
    paths = paths_arg(argv)
    if not paths:
        return 2
    if sys.platform != "win32":
        jobs = Jobs()
        for p in paths:
            jobs.add(p)
        return run_plain(jobs)
    handle = claim()
    if handle is None:
        if hand_over(paths):
            return 0
        # the window that was open is on its way out: be the next one
        handle = claim() or object()
    try:
        _dpi_aware()
        jobs = Jobs()
        for p in paths:
            jobs.add(p)
        if not TaskWindow(jobs).run():
            jobs.wait()
            v = view(jobs)
            _message("%s\n\n%s" % (v["instruction"], v["content"]),
                     v["warn"])
    finally:
        release(handle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
