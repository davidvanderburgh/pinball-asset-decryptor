"""Right-click a card image in Explorer > Compact with PAD (PAD-1522),
> Move with PAD (PAD-1535) or > Copy with PAD (PAD-1539).

    pythonw "Pinball Asset Decryptor.pyw" --compact <card.raw> [more...]
    pythonw "Pinball Asset Decryptor.pyw" --move <card.raw> [more...] [--to DIR]
    pythonw "Pinball Asset Decryptor.pyw" --copy <card.raw> [more...] [--to DIR]

COPY: Explorer's copy writes a compact card's holes back out too, on the
same drive as much as on another.  Copy with PAD is Move with PAD that
leaves the original where it is (:class:`CopyJobs`,
core.sparse_card.copy_card).  A folder that cannot keep a card compact
(Google Drive, a cloud folder, an exFAT stick: sparse_card.zip_reason) gets
the card as a .zip the size of its data, from a copy and from a move.

MOVE: Explorer's move to another drive is a copy that writes a compact
card's holes back out as zeros, so the card arrived full size and took as
long as a full one to write.  Move with PAD asks for the folder (the
standard Windows folder picker), then moves each card with
core.sparse_card.move_card: a rename on the same drive, only the card's
data copied to another one.  The same window shows it (:class:`MoveJobs`
carries the words), with a queue and a mutex of its own, so a move and a
compact never land in one window.

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

MOVE_FLAG = "--move"
MOVE_TITLE = "Move card image"
MOVE_NOTE = ("PAD copies only the card's data, so a compact card stays "
             "compact on its new drive and is written in a fraction of the "
             "time. Explorer's own move to another drive writes the card's "
             "whole size.")
MOVE_MUTEX = "Local\\PinballAssetDecryptor.MoveWindow"
MOVE_QUEUE = "move_queue"
#: a later launch waits this long for the window to take its card: the
#: first one may still be showing the folder picker (its own thread takes
#: cards meanwhile, so this is only a guard)
MOVE_HAND_OVER_WAIT = 10.0

COPY_FLAG = "--copy"
COPY_TITLE = "Copy card image"
COPY_NOTE = ("PAD copies only the card's data, so the copy of a compact "
             "card is compact too and is written in a fraction of the time. "
             "Explorer's own copy writes the card's whole size.")
COPY_MUTEX = "Local\\PinballAssetDecryptor.CopyWindow"
COPY_QUEUE = "copy_queue"
#: what the window adds under a card that went in as a .zip
ZIP_NOTE = ("%s cannot keep a card compact, so it is a zip there: the same "
            "card, byte for byte, once unzipped or added to PAD's card "
            "library.")

WAITING, WORKING, DONE, FAILED, STOPPED = (
    "waiting", "working", "done", "failed", "stopped")


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
    """The card images on a ``--compact`` / ``--move`` command line, in
    order (a ``--to DIR`` is not one)."""
    out = []
    skip = False
    for a in argv or ():
        if skip:
            skip = False
            continue
        if a == "--to":
            skip = True
            continue
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

    The window's words are the list's (:attr:`title`, :attr:`note`,
    :meth:`headline`): :class:`MoveJobs` is the same window moving cards.

    Everything the worker finds goes on :attr:`events` as ``(job, what)``;
    whoever shows it (the window's timer, a test) drains that on its own
    thread and reads the job's fields."""

    title = TITLE
    note = NOTE

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

    def headline(self, j):
        """The headline when *j* is the only card."""
        if j.state in (WAITING, WORKING):
            return "Compacting %s" % j.name
        if j.state == FAILED:
            return "%s was not compacted" % j.name
        if j.state == STOPPED:
            return "Stopped"
        if j.text.startswith("Nothing to free"):
            return "%s stays as it is" % j.name
        return "%s is stored compact" % j.name

    def busy_headline(self, at, n):
        return "Compacting card image %d of %d" % (at, n)

    def where(self, j):
        """The line under a lone card's headline: where it is."""
        return os.path.dirname(j.path)

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
def spool_dir(name="compact_queue"):
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "pinball_decryptor", name)


def claim(mutex=MUTEX):
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
        h = k32.CreateMutexW(None, False, mutex)
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


def view(jobs):
    """What the window shows now: ``{"busy", "instruction", "content",
    "pct", "warn"}``.  One card reads as a sentence about that card; several
    as a list, a mark and a line each."""
    with jobs._lock:
        cards = list(jobs.jobs)
    busy = any(j.state in (WAITING, WORKING) for j in cards)
    now = next((j for j in cards if j.state == WORKING), None)
    warn = any(j.state == FAILED for j in cards)
    pct = (now.pct or 0) if now is not None else (0 if busy else 100)
    if len(cards) == 1:
        j = cards[0]
        head = jobs.headline(j)
        body = "%s\n\n%s" % (jobs.where(j), j.text)
    else:
        if busy:
            at = (cards.index(now) + 1) if now is not None else \
                sum(1 for j in cards if j.state not in (WAITING,)) + 1
            head = jobs.busy_headline(min(at, len(cards)), len(cards))
        else:
            head = jobs.summary()
        body = "\n".join("%s  %s\n      %s" % (MARK[j.state], j.name, j.text)
                         for j in cards)
    return {"busy": busy, "instruction": head, "content": body, "pct": pct,
            "warn": warn and not busy}


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
                 on_page=None):
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
        cfg.pszWindowTitle = self.jobs.title
        cfg.pszMainInstruction = v["instruction"]
        cfg.pszContent = v["content"]
        cfg.cButtons = 1
        cfg.pButtons = buttons
        cfg.nDefaultButton = _BUTTON
        cfg.pszFooter = self.jobs.note
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
                old["warn"] != v["warn"]:
            # another kind of page (working <> done): build it anew
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
            elif msg == _TDN_BUTTON_CLICKED:
                # Stop, Close, Esc and the X all end here
                if self.jobs.busy:
                    self.jobs.stop()
                    self.jobs.wait(15)
                return _S_OK
        except Exception:                               # noqa: BLE001
            log.exception("card window")
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
        self._draw(view(self.jobs))

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
        v = view(self.jobs)
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


def _message(text, warn=False, title=TITLE):
    """The fallback's one box, for a Windows with no task dialog."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, text, title, 0x30 if warn else 0x40)
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



# ----------------------------------------------------------------------
# Move with PAD (PAD-1535)
# ----------------------------------------------------------------------
def to_arg(argv):
    """The folder a ``--to DIR`` names, or None."""
    argv = list(argv or ())
    if "--to" in argv:
        i = argv.index("--to")
        if i + 1 < len(argv):
            return os.path.abspath(argv[i + 1].strip('"'))
    return None


def _place(folder):
    """A folder as the window names it: ``D:\\Pinball\\cards``."""
    return folder.rstrip("\\/") if len(folder) > 3 else folder


def move_text(res, copied=False):
    """One line on what moving (or, *copied*, copying) came to, from a
    sparse_card.MoveResult."""
    size, after = fmt(res.size), fmt(res.after)
    did = "Copied" if copied else "Moved"
    if res.zipped:
        why = res.zipped[0].upper() + res.zipped[1:]
        text = "%s as a zip: %s for a %s card. %s" % (
            did, after, size, ZIP_NOTE % why)
    elif res.renamed:
        text = ("Moved. On the same drive it is the very same file, "
                "%s on disk." % after)
    elif not res.sparse_ok:
        text = ("%s, but full size: this drive cannot hold compact "
                "files (exFAT or FAT32, like most USB sticks)." % did)
    elif res.after + sparse_card.MIN_HOLE > res.size:
        text = "%s. This %s card is full of data." % (did, size)
    elif res.before + sparse_card.MIN_HOLE > res.size:
        text = ("%s and %s compact: %s on disk for a %s card."
                % (did, "the copy is" if copied else "now", after, size))
    elif copied:
        text = "Copied, and the copy is compact too: %s on disk for a %s " \
               "card." % (after, size)
    else:
        text = "Moved and still compact: %s on disk for a %s card." % (
            after, size)
    if res.kept and not copied:
        text += (" The original could not be removed (another program has "
                 "it open), so it is still in %s too."
                 % _place(os.path.dirname(res.src)))
    return text


def move_error_text(err, dest="", copied=False):
    did = "copied" if copied else "moved"
    do = "copy" if copied else "move"
    if isinstance(err, sparse_card.SameFolder):
        return "It is already in that folder."
    if isinstance(err, FileExistsError):
        return ("%s already has a file of that name. Nothing was %s."
                % (_place(dest), did))
    if isinstance(err, sparse_card.NoRoom):
        return "Not %s: %s." % (did, str(err).rstrip("."))
    if isinstance(err, PermissionError):
        return ("Could not %s it: another program is using this card, or "
                "it is read-only. Close that program and try again." % do)
    if isinstance(err, FileNotFoundError):
        return "This file is no longer there."
    if isinstance(err, OSError) and err.strerror:
        return "Could not %s it: %s." % (do, err.strerror.rstrip("."))
    return "Could not %s it: %s." % (do, err)


class MoveJobs(Jobs):
    """:class:`Jobs` moving every card into :attr:`dest`."""

    title = MOVE_TITLE
    note = MOVE_NOTE
    copied = False
    #: the window's words: Moving / moved / "is in its new folder"
    doing, did, there = "Moving", "moved", "is in its new folder"

    def __init__(self, dest, move=None):
        super().__init__()
        self.dest = os.path.abspath(dest)
        self._move = move or self._engine()

    def _engine(self):
        return sparse_card.move_card

    def headline(self, j):
        if j.state in (WAITING, WORKING):
            return "%s %s" % (self.doing, j.name)
        if j.state == FAILED:
            return "%s was not %s" % (j.name, self.did)
        if j.state == STOPPED:
            return "Stopped"
        return "%s %s" % (j.name, self.there)

    def busy_headline(self, at, n):
        return "%s card image %d of %d" % (self.doing, at, n)

    def where(self, j):
        came = getattr(j, "came_from", None) or j.path
        return "From %s\nTo %s" % (_place(os.path.dirname(came)),
                                    _place(self.dest))

    def summary(self):
        with self._lock:
            jobs = list(self.jobs)
        if len(jobs) <= 1:
            return ""
        done = sum(1 for j in jobs if j.state == DONE)
        text = "%d of %d card images %s to %s." % (
            done, len(jobs), self.did, _place(self.dest))
        failed = sum(1 for j in jobs if j.state == FAILED)
        if failed:
            text += " %d could not be %s." % (failed, self.did)
        return text

    def _one(self, job):
        job.pct, job.text = 0, "%s the card…" % self.doing
        self.events.put((job, "start"))
        last = [-1]

        def progress(done, total):
            pct = int(done * 100 // total) if total else 100
            if pct != last[0]:
                last[0] = pct
                job.pct = pct
                job.text = "Copying the card's data… %d%%" % pct
                self.events.put((job, "progress"))

        def cancel():
            if self._stop:
                raise Stopped()

        try:
            res = self._move(job.path, self.dest, progress=progress,
                             cancel=cancel)
        except Stopped:
            job.state, job.pct = STOPPED, None
            job.text = ("Stopped: nothing was copied." if self.copied
                        else "Stopped: the card is where it was.")
        except Exception as e:                          # noqa: BLE001
            log.warning("%s %s to %s", self.doing, job.path, self.dest,
                        exc_info=True)
            job.state, job.pct = FAILED, None
            job.text = move_error_text(e, self.dest, self.copied)
        else:
            job.state, job.pct = DONE, 100
            job.text = move_text(res, self.copied)
            job.came_from = job.path
            if self.copied:
                job.copy = res.dst
            else:
                job.path = res.dst
            if not res.sparse_ok:
                job.state = FAILED
        self.events.put((job, "end"))


class CopyJobs(MoveJobs):
    """:class:`MoveJobs` that leaves every card where it is (PAD-1539)."""

    title = COPY_TITLE
    note = COPY_NOTE
    copied = True
    doing, did, there = "Copying", "copied", "has its copy"

    def _engine(self):
        return sparse_card.copy_card


_FOS_NOCHANGEDIR, _FOS_PICKFOLDERS, _FOS_FORCEFILESYSTEM = 0x8, 0x20, 0x40
_FOS_PATHMUSTEXIST = 0x800
_SIGDN_FILESYSPATH = 0x80058000


def pick_folder(start=None, title="Move with PAD: choose the folder",
                ok="Move here"):
    """The standard Windows folder picker (IFileOpenDialog, as Explorer's
    own "Move to" > "Choose location" shows); the folder picked, or None
    when it was cancelled or cannot be shown."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort),
                    ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]

    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32

    def guid(text):
        g = GUID()
        ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
        return g

    def method(ptr, index, *argtypes):
        vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(
            ctypes.c_void_p))).contents
        proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
        fn = proto(vtbl[index])
        return lambda *a: fn(ptr, *a)

    def release(ptr):
        if ptr:
            method(ptr, 2)()

    ole32.CoInitializeEx(None, 0x2)             # apartment threaded
    dlg = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(
        ctypes.byref(guid("{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}")), None,
        1, ctypes.byref(guid("{D57C7288-D4AD-4768-BE02-9D969532D960}")),
        ctypes.byref(dlg))
    if hr != 0 or not dlg:
        return None
    item = ctypes.c_void_p()
    try:
        opts = ctypes.c_uint(0)
        method(dlg, 10, ctypes.POINTER(ctypes.c_uint))(ctypes.byref(opts))
        method(dlg, 9, ctypes.c_uint)(
            opts.value | _FOS_PICKFOLDERS | _FOS_FORCEFILESYSTEM
            | _FOS_PATHMUSTEXIST | _FOS_NOCHANGEDIR)
        method(dlg, 17, ctypes.c_wchar_p)(title)
        method(dlg, 18, ctypes.c_wchar_p)(ok)
        if start and os.path.isdir(start):
            there = ctypes.c_void_p()
            fn = shell32.SHCreateItemFromParsingName
            fn.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p,
                           ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
            fn.restype = ctypes.c_long
            if fn(start, None, ctypes.byref(guid(
                    "{43826D1E-E718-42EE-BC55-A1E261C37BFE}")),
                    ctypes.byref(there)) == 0:
                method(dlg, 12, ctypes.c_void_p)(there)
                release(there)
        if method(dlg, 3, wintypes.HWND)(None) != 0:
            return None                         # cancelled
        if method(dlg, 20, ctypes.POINTER(ctypes.c_void_p))(
                ctypes.byref(item)) != 0 or not item:
            return None
        name = ctypes.c_void_p()
        if method(item, 5, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(
                _SIGDN_FILESYSPATH, ctypes.byref(name)) != 0:
            return None
        try:
            return ctypes.wstring_at(name.value)
        finally:
            ole32.CoTaskMemFree(name)
    finally:
        release(item)
        release(dlg)


class _Gatherer:
    """Takes the cards later launches hand over while the folder picker is
    open (Explorer starts one launch per selected card), so they wait for
    nothing and all go to the one folder."""

    def __init__(self, spool):
        self.spool = spool
        self.paths = []
        self._done = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True,
                                   name="pad-move-gather")
        self._t.start()

    def _run(self):
        while not self._done.wait(0.05):
            self.paths += take_handed(self.spool)

    def stop(self):
        self._done.set()
        self._t.join(2)
        self.paths += take_handed(self.spool)
        return self.paths


def main_move(argv=None, pick=None, copy=False):
    """The ``--move`` launch (*copy*: the ``--copy`` one).  Returns the
    process's exit code."""
    argv = sys.argv[1:] if argv is None else argv
    paths = paths_arg(argv)
    dest = to_arg(argv)
    if not paths:
        return 2
    make = CopyJobs if copy else MoveJobs
    if sys.platform != "win32":
        if not dest:
            print("--%s needs --to DIR here" % ("copy" if copy else "move"),
                  file=sys.stderr)
            return 2
        jobs = make(dest)
        for p in paths:
            jobs.add(p)
        return run_plain(jobs)
    mutex = COPY_MUTEX if copy else MOVE_MUTEX
    spool = spool_dir(COPY_QUEUE if copy else MOVE_QUEUE)
    handle = claim(mutex)
    if handle is None:
        if hand_over(paths, spool, wait=MOVE_HAND_OVER_WAIT):
            return 0
        handle = claim(mutex) or object()
    try:
        _dpi_aware()
        if not dest:
            gather = _Gatherer(spool)
            try:
                picker = pick or pick_folder
                if copy:
                    dest = picker(os.path.dirname(paths[0]),
                                  "Copy with PAD: choose the folder",
                                  "Copy here")
                else:
                    dest = picker(os.path.dirname(paths[0]))
            finally:
                for p in gather.stop():
                    p = os.path.abspath(p)
                    if p not in paths:
                        paths.append(p)
            if not dest:
                return 0                        # cancelled: nothing moved
        jobs = make(dest)
        for p in paths:
            jobs.add(p)
        if not TaskWindow(jobs, spool=spool).run():
            jobs.wait()
            v = view(jobs)
            _message("%s\n\n%s" % (v["instruction"], v["content"]),
                     v["warn"], jobs.title)
    finally:
        release(handle)
    return 0


def main_copy(argv=None, pick=None):
    """The ``--copy`` launch (PAD-1539).  Returns the process's exit code."""
    return main_move(argv, pick, copy=True)


if __name__ == "__main__":
    sys.exit(main())
