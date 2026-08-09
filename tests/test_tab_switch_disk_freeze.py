"""Tab switches must never touch the disk on the UI thread.

The fault these reproduce reached David on 2026-08-09, right after a Windows
reboot: switching to the Emulate tab hung the whole window ("the logs haven't
even appeared yet") while WSL was already warm — so the stall was not wsl.exe.
It was `_refresh_stale_source_banner`, which ran on EVERY tab change and
statted the extract's SOURCE IMAGE inline: his card lives on OneDrive, and the
first touch of a cloud-synced path after a reboot can block for seconds while
the sync engine wakes.  The same class hid in `_scan_write_preview`, whose
folder checks ran on the main thread before its worker started — and that
scan fires at startup ("write destination changed").

Same treatment as the Emulate tab's WSL probes: the disk work moves to a
worker, the answer comes back through `after`, and a superseded probe's
answer is dropped.  Duck-typed stubs and no Tk window, the way
test_gui_batch26/28/29/30 do it — what is under test is the threading and the
plumbing, which exists without widgets.
"""

import os
import threading
import time

from pinball_decryptor.gui import main_window
from pinball_decryptor.gui.main_window import MainWindow

W = MainWindow


class _Var:
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


class _Banner:
    """The banner frame, remembering how it was packed."""

    def __init__(self, mapped=False):
        self.mapped = mapped
        self.pack_calls = []

    def winfo_ismapped(self):
        return self.mapped

    def pack(self, **kw):
        self.mapped = True
        self.pack_calls.append(kw)

    def pack_forget(self):
        self.mapped = False


class _Label:
    def __init__(self):
        self.text = None

    def configure(self, **kw):
        if "text" in kw:
            self.text = kw["text"]

    def cget(self, key):
        return self.text

    def place(self, **kw):
        pass


class _Root:
    """`after` runs the callback immediately — the marshalling is what is
    under test, not Tk's timer wheel."""

    def after(self, _delay, fn=None, *args):
        if fn is not None:
            fn(*args)


class _Win:
    """Just enough window for the banner halves, with the REAL methods bound
    by hand (the batch27 stub pattern: both halves have to be the real code
    or this stops testing the thing that was broken)."""

    def __init__(self, assets=""):
        self._stale_source_banner = _Banner()
        self._stale_source_banner_text = _Label()
        self._stale_source_dismissed = None
        self._top_bar = object()
        self.root = _Root()
        self.write_assets_var = _Var(assets)

    def _refresh_stale_source_banner(self, **kw):
        return W._refresh_stale_source_banner(self, **kw)

    def _apply_stale_source_banner(self, *a):
        return W._apply_stale_source_banner(self, *a)


def _wait_for(cond, timeout=5):
    deadline = time.time() + timeout
    while not cond() and time.time() < deadline:
        time.sleep(0.01)
    return cond()


def test_a_non_asset_tab_never_touches_the_disk(monkeypatch):
    """Entering Emulate/Extract/etc. must not stat the source image at all —
    the banner can never show there, so there is nothing to pay for.  This is
    the exact switch that hung: the probe raises if anything reaches it."""
    monkeypatch.setattr(
        main_window, "stale_source_message",
        lambda p: (_ for _ in ()).throw(AssertionError("disk touched")))
    win = _Win(assets="X:/extract")
    win._stale_source_banner.mapped = True
    win._refresh_stale_source_banner(on_asset_tab=False)
    assert not win._stale_source_banner.mapped      # hidden, and no disk I/O


def test_the_asset_tab_probe_stays_off_the_ui_thread(monkeypatch):
    """On Write/Replace tabs the staleness question is still asked — from a
    worker, with the answer marshalled back, so a cold OneDrive source costs
    patience instead of the UI."""
    seen = {}

    def probe(path):
        seen["thread"] = threading.current_thread()
        seen["path"] = path
        return "the source image has changed"

    monkeypatch.setattr(main_window, "stale_source_message", probe)
    monkeypatch.setattr(main_window, "stale_dismissed", lambda p: False)
    win = _Win(assets="X:/extract")
    win._refresh_stale_source_banner(on_asset_tab=True)
    assert _wait_for(lambda: win._stale_source_banner.mapped)
    assert seen["thread"] is not threading.main_thread(), \
        "the source image was statted on the UI thread"
    assert win._stale_source_banner_text.text == "the source image has changed"


def test_a_slow_probe_cannot_stamp_its_answer_over_a_newer_tab(monkeypatch):
    """Write spawns a probe, the user switches to Emulate before the cold
    disk answers — the late answer must be dropped, not shown on a tab the
    banner does not belong to."""
    gate = threading.Event()
    done = threading.Event()

    def slow_probe(path):
        gate.wait(5)
        return "stale"

    monkeypatch.setattr(main_window, "stale_source_message", slow_probe)
    monkeypatch.setattr(main_window, "stale_dismissed", lambda p: False)
    win = _Win(assets="X:/extract")

    apply_real = win._apply_stale_source_banner
    def apply_and_signal(*a):
        apply_real(*a)
        done.set()
    win._apply_stale_source_banner = apply_and_signal

    win._refresh_stale_source_banner(on_asset_tab=True)     # Write
    win._refresh_stale_source_banner(on_asset_tab=False)    # ... to Emulate
    gate.set()
    assert _wait_for(done.is_set)
    assert not win._stale_source_banner.mapped, \
        "a superseded probe stamped its answer over the new tab"


def test_the_write_scan_folder_checks_run_off_the_ui_thread(monkeypatch):
    """_scan_write_preview fires at startup ("write destination changed") and
    its folder checks used to stat the assets path — OneDrive, for the user
    who hit this — on the main thread before the worker existed."""
    seen = {}
    real_isdir = os.path.isdir

    def spying_isdir(path):
        if path == "X:/cold-extract":
            seen["thread"] = threading.current_thread()
            return False
        return real_isdir(path)

    monkeypatch.setattr(main_window.os.path, "isdir", spying_isdir)

    bailed = threading.Event()

    class _ScanWin:
        write_assets_var = _Var("X:/cold-extract")
        _write_preview_scan_id = 0
        _write_preview_empty = _Label()

        def _is_running(self):
            return False

        def _set_tab_scanning(self, key, active):
            if not active:
                bailed.set()

        def _add_pending_preview_rows(self, assets_path, scan_id):
            return 0

        def _tk_root(self):
            return _Root()

    win = _ScanWin()
    W._scan_write_preview(win)
    assert _wait_for(bailed.is_set)
    assert seen["thread"] is not threading.main_thread(), \
        "the assets folder was statted on the UI thread"
    assert "Select your modified assets folder" in win._write_preview_empty.text
