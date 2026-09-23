"""Build the web UI's run logic and window in-process for tests: no HTTP
server, no browser, a scratch settings folder.  Tab tests use it like

    from tests.webui_harness import web_app

    def test_something(tmp_path):
        with web_app(tmp_path, mfr="stern") as w:
            w.call("extract.set_source", "file")        # an @rpc method
            assert w.state("extract")["input"] == ""
            assert w.window.extract_input_var.get() == ""

``w.call`` runs a registered call exactly as the page would (on the UI
loop); ``w.state(ns)`` reads the store; ``w.run(fn)`` runs any function on
the loop.  Modal questions are answered by ``w.answers`` (a list consumed
in order; each item is the reply value, e.g. "yes"), and recorded in
``w.asked``.
"""

import contextlib
import gc
import json
import os
import threading

import pinball_decryptor.core.config as config


class WebHarness:
    def __init__(self, ctx):
        self.ctx = ctx
        self.answers = []
        self.asked = []

    @property
    def app(self):
        return self.ctx.app

    @property
    def window(self):
        return self.ctx.window

    def call(self, method, *args, **kwargs):
        return self.ctx.registry.call(method, list(args), kwargs)

    def state(self, ns):
        return self.ctx.store.namespace(ns)

    def run(self, fn, *args):
        return self.ctx.loop.call(fn, *args)

    def drain(self, timeout=5.0):
        """Wait until the UI loop has run everything queued so far."""
        self.ctx.loop.call(lambda: None, timeout=timeout)


@contextlib.contextmanager
def web_app(tmp_path, mfr=None, era=None, settings=None):
    from pinball_decryptor.core import session_log
    from pinball_decryptor.webui import compat
    from pinball_decryptor.webui.context import Context

    cfg = tmp_path / "cfg"
    cfg.mkdir(parents=True, exist_ok=True)
    settings_file = cfg / "settings.json"
    data = {"disclaimer_accepted": True}
    data.update(settings or {})
    settings_file.write_text(json.dumps(data), encoding="utf-8")

    old_settings = config.SETTINGS_FILE
    import pinball_decryptor.app as app_module
    old_app_settings = app_module.SETTINGS_FILE
    config.SETTINGS_FILE = str(settings_file)
    app_module.SETTINGS_FILE = str(settings_file)
    old_log_dir = session_log.LOG_DIR_OVERRIDE
    session_log.LOG_DIR_OVERRIDE = str(tmp_path / "logs")
    # a per-project log mirror left on by an earlier test must not leak in
    old_project_dir = session_log._project_dir
    session_log._project_dir = None
    # The app writes encoder options into os.environ (PAD_STERN_AUDIO_RAW,
    # the Advanced audio knobs, PAD_STERN_TEXT_GROW ...) because spawned
    # workers inherit it.  Put the whole environment back on the way out, or
    # a later test in this worker builds with this app's options.
    env_snapshot = dict(os.environ)
    old_env = {k: os.environ.get(k) for k in (
        "PAD_UI_NO_UPDATE_CHECK", "PAD_UI_NO_PREREQS", "PAD_UI_NO_RIG",
        "PINBALL_SKIP_DISCLAIMER")}
    for k in old_env:
        os.environ[k] = "1"
    old_messagebox = app_module.messagebox
    old_filedialog = app_module.filedialog

    # Tk tests in the same process leave destroyed Tk interpreters in
    # garbage cycles.  If the collector finds them on the UI loop's thread,
    # Tcl aborts that thread ("Tcl_AsyncDelete: async handler deleted by the
    # wrong thread") and the test hangs.  Collect them here, on the thread
    # that made them.  (The app itself never creates a Tk object.)
    gc.collect()
    ctx = Context()
    harness = WebHarness(ctx)
    compat.install(ctx)
    ctx.loop.start()

    # answer modals from harness.answers (tests never block on a question)
    orig_ask = ctx.dialogs.ask

    def _ask(spec):
        harness.asked.append(spec)
        if harness.answers:
            return harness.answers.pop(0)
        if spec.get("kind") == "file":
            return "" if not spec.get("multiple") else []
        buttons = spec.get("buttons") or [{"id": "ok"}]
        return buttons[-1]["id"] if len(buttons) > 1 else buttons[0]["id"]

    ctx.dialogs.ask = _ask
    try:
        from pinball_decryptor.app import App
        ctx.loop.call(lambda: App(ctx), timeout=120)
        if mfr:
            harness.call("ui.pick_manufacturer", mfr)
            if era:
                harness.call("ui.set_era", era)
        harness.drain()
        yield harness
    finally:
        try:
            ctx.loop.call(lambda: ctx.window.close(), timeout=30)
        except Exception:                               # noqa: BLE001
            pass
        ctx.dialogs.ask = orig_ask
        ctx.loop.stop()
        ctx.bus.close()
        config.SETTINGS_FILE = old_settings
        app_module.SETTINGS_FILE = old_app_settings
        compat.uninstall()
        app_module.messagebox = old_messagebox
        app_module.filedialog = old_filedialog
        session_log.LOG_DIR_OVERRIDE = old_log_dir
        session_log._project_dir = old_project_dir
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for k in [k for k in os.environ if k not in env_snapshot]:
            os.environ.pop(k, None)
        for k, v in env_snapshot.items():
            if os.environ.get(k) != v:
                os.environ[k] = v
