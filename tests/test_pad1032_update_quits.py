"""PAD-1032: Restart to update closed the app down and the app never went.

David: "Trying to restart my pad app after update locally and it never
does".  In the web UI App._on_close is what the window's close runs; it does
not close the window.  The installer route never noticed (its setup exe
force-closes the app), but the swap helper only waits for the process to
exit, so the old version sat there with its window up and the helper's log
stopped at "waiting for the app (pid ...) to close".
"""

import threading
import types

from pinball_decryptor import app as app_mod
from pinball_decryptor.webui import host as host_mod


class _Host:
    def __init__(self, order):
        self.order = order

    def quit_for_update(self):
        self.order.append("quit")


class _App:
    _close_for_update = app_mod.App._close_for_update

    def __init__(self, host=None):
        self.order = []
        self.ctx = types.SimpleNamespace(host=host)

    def _on_close(self):
        self.order.append("close")


def test_an_update_quit_ends_the_process_after_closing_down():
    app = _App()
    app.ctx.host = _Host(app.order)
    app._close_for_update()
    assert app.order == ["close", "quit"]


def test_with_no_host_it_only_closes_down():
    """Tests and the stand-ins have no desktop host: nothing to end."""
    app = _App()
    app._close_for_update()
    assert app.order == ["close"]


def test_the_close_down_runs_once():
    """The update's own call, then the window's close calling it again: the
    second must not stop the emulators through wsl.exe after WSL was shut
    down for the update (it would boot the VM again)."""
    calls = []

    class _Once:
        _on_close = app_mod.App._on_close

        def _save_session_state(self):
            calls.append("save")

        window = types.SimpleNamespace(
            stop_all_preview_playback=lambda: calls.append("preview"),
            emulate_shutdown=lambda: calls.append("emulators"),
            close=lambda: calls.append("window"))
        ctx = types.SimpleNamespace(dialogs=types.SimpleNamespace(
            cancel_all=lambda: calls.append("cancel")))

    app = _Once()
    app._on_close()
    app._on_close()
    assert calls == ["save", "preview", "emulators", "window", "cancel"]


def test_the_host_quits_off_the_loop_and_ends_a_process_that_hangs(
        monkeypatch):
    """The window's close calls back into the UI loop, which is the caller,
    so the quit runs on its own thread; and a process still up past
    UPDATE_EXIT_S is ended outright, because the update waits for it."""
    host = host_mod.Host(types.SimpleNamespace(), "serve")
    ended = threading.Event()
    quit_threads = []
    monkeypatch.setattr(host_mod.os, "_exit", lambda code: ended.set())
    monkeypatch.setattr(host_mod.Host, "UPDATE_EXIT_S", 0.05)
    real_quit = host.quit

    def _quit():
        quit_threads.append(threading.current_thread())
        real_quit()
    host.quit = _quit
    host.quit_for_update()
    assert ended.wait(5)
    assert host.quitting
    assert quit_threads and quit_threads[0] is not threading.current_thread()


def test_every_update_route_ends_the_process():
    """The swap, the installer, the macOS swap and the AppImage hand-over all
    wait for this process (or leave its window up) - none may call the bare
    close-down."""
    import inspect
    for name in ("_swap_in_staged", "_launch_downloaded_installer",
                 "_finish_macos_update", "_finish_appimage_update"):
        src = inspect.getsource(getattr(app_mod.App, name))
        assert "self._close_for_update()" in src, name
        assert "self._on_close()" not in src, name
