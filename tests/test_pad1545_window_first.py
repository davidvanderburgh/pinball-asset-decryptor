"""PAD-1545: the window goes up while the App is made, and the last project
is opened as the App's first job on the loop, not inside its constructor."""

import threading
import time

import pytest

from pinball_decryptor.webui import host as host_mod
from pinball_decryptor.webui.context import Context
from tests.webui_harness import web_app


class _App:
    accept_disclaimer = _on_ui_zoom_change = open_image = lambda *a: None
    _settings = {}

    def __init__(self, ctx):
        ctx.app = self

    def saved_geometry(self):
        return None


def _slow_app(gate, entered=None, error=None):
    class _Slow(_App):
        def __init__(self, ctx):
            if entered is not None:
                entered.set()
            gate.wait(10)
            if error is not None:
                raise error
            super().__init__(ctx)
    return _Slow


@pytest.fixture
def no_install(monkeypatch):
    monkeypatch.setattr(host_mod.compat, "install", lambda ctx: None)


def _stop(pending):
    pending.ctx.loop.stop()
    pending.server.stop()


def test_begin_build_returns_while_the_app_is_still_being_made(
        monkeypatch, no_install):
    import pinball_decryptor.app as app_mod
    gate, entered = threading.Event(), threading.Event()
    monkeypatch.setattr(app_mod, "App", _slow_app(gate, entered))
    pending = host_mod.begin_build(Context())
    try:
        assert entered.wait(10)
        # the server answers already; the App does not exist yet
        assert pending.server.port and pending.ctx.app is None
        assert not pending.finished
        gate.set()
        ctx, server = pending.finish()
        assert isinstance(ctx.app, _App) and pending.finished
        assert pending.result() == (ctx, server)
    finally:
        gate.set()
        _stop(pending)


def test_the_pages_first_state_waits_for_the_app(monkeypatch, no_install):
    """The window's page asks for its state before the App is there: the
    ask counts as the page having arrived (the blank-window watch), and it
    is answered once the App is made."""
    import pinball_decryptor.app as app_mod
    from pinball_decryptor.core import update_splash
    monkeypatch.setattr(update_splash, "dismiss", lambda *a, **k: None)
    gate = threading.Event()
    monkeypatch.setattr(app_mod, "App", _slow_app(gate))
    pending = host_mod.begin_build(Context())
    ctx = pending.ctx
    got = []
    asker = threading.Thread(
        target=lambda: got.append(ctx.state_snapshot()), daemon=True)
    try:
        asker.start()
        assert ctx.page_seen.wait(10)
        time.sleep(0.1)
        assert not got and asker.is_alive()
        gate.set()
        pending.finish()
        asker.join(10)
        assert got and "state" in got[0]
    finally:
        gate.set()
        _stop(pending)


def test_a_context_nobody_is_building_answers_at_once(monkeypatch):
    from pinball_decryptor.core import update_splash
    monkeypatch.setattr(update_splash, "dismiss", lambda *a, **k: None)
    ctx = Context()
    assert ctx.building is None
    assert "state" in ctx.state_snapshot()


def test_an_app_that_cannot_be_made_raises_from_finish_and_result(
        monkeypatch, no_install):
    import pinball_decryptor.app as app_mod
    gate = threading.Event()
    gate.set()
    monkeypatch.setattr(app_mod, "App",
                        _slow_app(gate, error=RuntimeError("no plugins")))
    pending = host_mod.begin_build(Context())
    try:
        with pytest.raises(RuntimeError, match="no plugins"):
            pending.finish()
        with pytest.raises(RuntimeError, match="no plugins"):
            pending.result()
        # a page that was waiting is let go
        assert pending.ctx.building.is_set()
    finally:
        _stop(pending)


def test_closing_before_the_app_is_made_saves_nothing():
    ctx = Context()
    assert ctx.app is None
    host_mod._close_app(ctx)            # no error, nothing to call


def test_main_puts_the_window_up_before_the_app_is_made(
        monkeypatch, no_install):
    """main() starts the window while the App is still in its constructor,
    asks the App to open the last project afterwards, and opens the window
    at the place saved in the settings."""
    import pinball_decryptor.app as app_mod
    gate, entered = threading.Event(), threading.Event()
    monkeypatch.setattr(app_mod, "App", _slow_app(gate, entered))
    monkeypatch.setattr(app_mod, "saved_window_geometry",
                        lambda: (1000, 700, 10, 20, False))
    monkeypatch.setattr(host_mod, "_startup_watch", lambda: None)
    monkeypatch.setattr(host_mod.Host, "preload_window", lambda self: None)
    seen = {}

    def _native(ctx, server, host):
        assert entered.wait(10)
        seen["app_when_window_started"] = ctx.app
        seen["defer"] = ctx.defer_session
        seen["geometry"] = ctx.start_geometry
        gate.set()
        ctx.building.wait(10)
        seen["app_later"] = ctx.app
    monkeypatch.setattr(host_mod, "run_native", _native)
    import sys
    import types
    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace())
    try:
        assert host_mod.main([]) == 0
    finally:
        gate.set()
    assert seen["app_when_window_started"] is None
    assert seen["defer"] is True
    assert seen["geometry"] == (1000, 700, 10, 20, False)
    assert isinstance(seen["app_later"], _App)


def test_geometry_from_settings():
    from pinball_decryptor.app import geometry_from_settings as g
    assert g({"window_geometry": "1200x800+30+-40",
              "window_maximized": True}) == (1200, 800, 30, -40, True)
    assert g({"window_geometry": "1200x800"}) == (1200, 800, None, None,
                                                  False)
    assert g({}) is None and g({"window_geometry": "big"}) is None


def test_the_saved_window_place_is_read_without_an_app(tmp_path, monkeypatch):
    import pinball_decryptor.app as app_mod
    f = tmp_path / "settings.json"
    monkeypatch.setattr(app_mod, "SETTINGS_FILE", str(f))
    assert app_mod.saved_window_geometry() is None          # no file
    f.write_text("not json", encoding="utf-8")
    assert app_mod.saved_window_geometry() is None
    f.write_text('{"window_geometry": "900x700+5+6"}', encoding="utf-8")
    assert app_mod.saved_window_geometry() == (900, 700, 5, 6, False)


def test_a_deferred_app_opens_the_last_project_as_its_first_job(
        tmp_path, monkeypatch):
    """With the host's defer_session the constructor returns with the page
    on its Starting line; the manufacturer view follows as the next job."""
    import pinball_decryptor.app as app_mod
    import pinball_decryptor.webui.context as context_mod

    class _Deferring(context_mod.Context):
        def __init__(self):
            super().__init__()
            self.defer_session = True
    monkeypatch.setattr(context_mod, "Context", _Deferring)
    at_return = {}
    real = app_mod.App._start_session_deferred

    def _spy(self):
        at_return.update(self.ctx.store.snapshot().get("shell") or {})
        at_return["mfr"] = self._current_mfr
        real(self)
    monkeypatch.setattr(app_mod.App, "_start_session_deferred", _spy)
    with web_app(tmp_path, settings={"last_manufacturer": "stern"}) as w:
        assert at_return["opening"] is True
        assert at_return["mfr"] is None
        shell = w.state("shell")
        assert shell["opening"] is False and shell["view"] == "mfr"
        assert w.app._current_mfr.key == "stern"


def test_an_app_nobody_defers_opens_the_last_project_in_its_constructor(
        tmp_path):
    with web_app(tmp_path, settings={"last_manufacturer": "stern"}) as w:
        shell = w.state("shell")
        assert shell["view"] == "mfr" and not shell.get("opening")
