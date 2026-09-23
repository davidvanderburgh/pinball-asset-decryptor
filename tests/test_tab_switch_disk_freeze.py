"""Tab switches must never touch the disk on the UI thread.

The fault these reproduce reached David on 2026-08-09, right after a Windows
reboot: switching to the Emulate tab hung the whole window ("the logs haven't
even appeared yet") while WSL was already warm — so the stall was not wsl.exe.
It was `_refresh_stale_source_banner`, which ran on EVERY tab change and
statted the extract's SOURCE IMAGE inline: his card lives on OneDrive, and the
first touch of a cloud-synced path after a reboot can block for seconds while
the sync engine wakes.

Same treatment as the Emulate tab's WSL probes: the disk work moves to a
worker, the answer comes back through the UI loop, and a superseded probe's
answer is dropped.  The banner halves are the web shell's
(``webui/tabs/shell_extras.py``, the port of the Tk window's), driven on a
duck-typed stand-in with the REAL methods bound by hand: what is under test is
the threading and the plumbing, which exists without a page.
"""

import threading
import time

from pinball_decryptor.core import extract_source
from pinball_decryptor.webui.tabs.shell_extras import ShellExtras

S = ShellExtras


class _Var:
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


class _Loop:
    """`post` runs the callback immediately — the marshalling is what is
    under test, not the loop's queue."""

    def post(self, fn, *args):
        fn(*args)


class _Window:
    """The banner the page shows, remembering what it was last given."""

    def __init__(self):
        self.banners = {}

    def set_banner(self, key, spec):
        self.banners[key] = spec


class _Shell:
    """Just enough shell for the banner halves, with the REAL methods bound
    by hand (both halves have to be the real code or this stops testing the
    thing that was broken)."""

    def __init__(self, assets=""):
        self._stale_token = 0
        self._stale_dismissed = None
        self._stale_shown = None
        self.window = _Window()
        self.ctx = type("Ctx", (), {"loop": _Loop()})()
        self.write_assets_var = _Var(assets)

    def _var_or_none(self, name):
        return getattr(self, name, None)

    def _refresh_stale_source_banner(self, **kw):
        return S._refresh_stale_source_banner(self, **kw)

    def _apply_stale_source_banner(self, *a):
        return S._apply_stale_source_banner(self, *a)

    @property
    def shown(self):
        return bool(self.window.banners.get("stale_source"))


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
        extract_source, "stale_source_message",
        lambda p: (_ for _ in ()).throw(AssertionError("disk touched")))
    shell = _Shell(assets="X:/extract")
    shell._stale_shown = ("X:/extract", "stale")
    shell.window.banners["stale_source"] = {"text": "stale"}
    shell._refresh_stale_source_banner(on_asset_tab=False)
    assert not shell.shown                          # hidden, and no disk I/O


def test_the_asset_tab_probe_stays_off_the_ui_thread(monkeypatch):
    """On Write/Replace tabs the staleness question is still asked — from a
    worker, with the answer marshalled back, so a cold OneDrive source costs
    patience instead of the UI."""
    seen = {}

    def probe(path):
        seen["thread"] = threading.current_thread()
        seen["path"] = path
        return "the source image has changed"

    monkeypatch.setattr(extract_source, "stale_source_message", probe)
    monkeypatch.setattr(extract_source, "stale_dismissed", lambda p: False)
    shell = _Shell(assets="X:/extract")
    shell._refresh_stale_source_banner(on_asset_tab=True)
    assert _wait_for(lambda: shell.shown)
    assert seen["thread"] is not threading.main_thread(), \
        "the source image was statted on the UI thread"
    assert shell.window.banners["stale_source"]["text"] == \
        "the source image has changed"


def test_a_slow_probe_cannot_stamp_its_answer_over_a_newer_tab(monkeypatch):
    """Write spawns a probe, the user switches to Emulate before the cold
    disk answers — the late answer must be dropped, not shown on a tab the
    banner does not belong to."""
    gate = threading.Event()
    done = threading.Event()

    def slow_probe(path):
        gate.wait(5)
        return "stale"

    monkeypatch.setattr(extract_source, "stale_source_message", slow_probe)
    monkeypatch.setattr(extract_source, "stale_dismissed", lambda p: False)
    shell = _Shell(assets="X:/extract")

    apply_real = shell._apply_stale_source_banner

    def apply_and_signal(*a):
        apply_real(*a)
        done.set()
    shell._apply_stale_source_banner = apply_and_signal

    shell._refresh_stale_source_banner(on_asset_tab=True)     # Write
    shell._refresh_stale_source_banner(on_asset_tab=False)    # ... to Emulate
    gate.set()
    assert _wait_for(done.is_set)
    assert not shell.shown, \
        "a superseded probe stamped its answer over the new tab"
