"""A worker thread that outlives its window must not crash.

Background render/scan threads finish by hopping back to the Tk main
thread via ``MainWindow._post_ui``.  When the window is already gone —
the user closed it mid-run, or (the case that mattered) a pytest-xdist
worker tore the App down while the daemon thread was still finishing —
touching Tk raises ``RuntimeError: main thread is not in main loop`` or
``tkinter.TclError`` *inside the worker thread*.  Unhandled, that stray
exception crashed the whole Windows CI worker.  ``_post_ui`` must swallow
it and drop the update; these tests pin that down without a real display,
so they run in the normal parallel pool (no ``@tk`` marker).
"""
import tkinter as tk

from pinball_decryptor.gui.main_window import MainWindow


class _Root:
    """Stand-in for the Tk root's ``.after`` scheduler."""

    def __init__(self, raises=None):
        self._raises = raises
        self.calls = []

    def after(self, delay, fn, *args):
        if self._raises is not None:
            raise self._raises
        self.calls.append((delay, fn, args))


class _Stub:
    """Minimal object exposing just what ``_post_ui`` reaches for."""

    def __init__(self, root):
        self._root = root

    def _tk_root(self):
        return self._root


def _post(stub, fn, *args, **kw):
    # Call the real method against the stub, unbound.
    return MainWindow._post_ui(stub, fn, *args, **kw)


def test_a_live_window_schedules_the_callback():
    root = _Root()
    stub = _Stub(root)
    marker = object()

    def cb(*a):
        pass

    _post(stub, cb, marker, 7)

    assert root.calls == [(0, cb, (marker, 7))]


def test_a_torn_down_root_raising_runtimeerror_is_swallowed():
    # This is the exact CI failure: the daemon thread reaches into Tk after
    # the loop is gone.  No exception must escape _post_ui.
    stub = _Stub(_Root(raises=RuntimeError("main thread is not in main loop")))
    _post(stub, lambda: None, 1, 2, 3)  # must not raise


def test_a_torn_down_root_raising_tclerror_is_swallowed():
    stub = _Stub(_Root(raises=tk.TclError("application has been destroyed")))
    _post(stub, lambda: None)  # must not raise


def test_a_delay_is_forwarded():
    root = _Root()
    stub = _Stub(root)

    def cb():
        pass

    _post(stub, cb, delay=90)

    assert root.calls == [(90, cb, ())]
