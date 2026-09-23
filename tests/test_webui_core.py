"""The web UI's frame: loop, store, dialogs, the window contract.

The CONTRACT test is the one that guards against regressions in the cut
over: every window attribute the run logic (app.py) reads must be provided
by the web window or a tab service, for every manufacturer.
"""

import re
import threading
from pathlib import Path

import pytest

from tests.webui_harness import web_app

APP_PY = Path(__file__).resolve().parents[1] / "pinball_decryptor" / "app.py"


def _window_attrs_used_by_app():
    text = APP_PY.read_text(encoding="utf-8")
    names = set(re.findall(r"self\.window\.([A-Za-z_][A-Za-z0-9_]*)", text))
    names |= set(re.findall(r'getattr\(self\.window,\s*"([A-Za-z_]+)"', text))
    return sorted(names)


# ---------------------------------------------------------------- loop
def test_loop_after_and_call():
    from pinball_decryptor.webui.loop import UiLoop
    loop = UiLoop()
    loop.start()
    try:
        seen = []
        done = threading.Event()
        loop.after(30, lambda: (seen.append("b"), done.set()))
        loop.post(lambda: seen.append("a"))
        assert done.wait(2)
        assert seen == ["a", "b"]
        assert loop.call(lambda x: x * 2, 21) == 42
        tid = loop.after(20, lambda: seen.append("never"))
        loop.after_cancel(tid)
        loop.call(lambda: None)
        import time
        time.sleep(0.08)
        assert "never" not in seen
    finally:
        loop.stop()


def test_pump_until_keeps_the_loop_running():
    from pinball_decryptor.webui.loop import UiLoop
    loop = UiLoop()
    loop.start()
    try:
        ev = threading.Event()
        order = []

        def modal():
            loop.after(20, lambda: order.append("timer ran under the modal"))
            loop.after(60, ev.set)
            loop.pump_until(ev, timeout=2)
            order.append("modal returned")

        loop.call(modal, timeout=3)
        assert order == ["timer ran under the modal", "modal returned"]
    finally:
        loop.stop()


# --------------------------------------------------------------- store
def test_store_publishes_only_changes():
    from pinball_decryptor.webui.state import EventBus, Store
    bus = EventBus()
    store = Store(bus)
    store.set("x", a=1, b=[1, 2])
    n = bus.last_seq
    store.set("x", a=1)
    assert bus.last_seq == n
    store.set("x", a=2)
    assert bus.last_seq == n + 1
    store.set("x", rows=[{"k": 1}, {"k": 2}])
    assert store.patch_item("x", "rows", 1, k=3)
    assert store.get("x", "rows")[1] == {"k": 3}


# ---------------------------------------------------------- the contract
def _manufacturer_keys():
    from pinball_decryptor.core.registry import all_manufacturers, load_plugins
    load_plugins()
    return [m.key for m in all_manufacturers()]


@pytest.mark.parametrize("mfr", _manufacturer_keys())
def test_every_window_attribute_the_run_logic_reads_exists(tmp_path, mfr):
    with web_app(tmp_path, mfr=mfr) as w:
        win = w.window
        missing = []
        for name in _window_attrs_used_by_app():
            try:
                getattr(win, name)
            except AttributeError:
                missing.append(name)
        stand_ins = sorted((getattr(win, "missing_exports", None) or {}))
        assert not missing, "window lacks: %s" % ", ".join(missing)
        assert not stand_ins, "no tab provides: %s" % ", ".join(stand_ins)


def test_rail_follows_capabilities(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["extract"]["visible"]
        assert tabs["write"]["visible"]
        assert not tabs["emulate_jjp"]["visible"]
        w.call("ui.set_era", "whitestar")
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["extract"]["visible"]
        assert not tabs["write"]["visible"]


def test_messagebox_goes_to_the_page(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        from pinball_decryptor import app as app_module
        w.answers.append("yes")
        assert w.run(lambda: app_module.messagebox.askyesno("T", "Q?")) is True
        assert w.asked[-1]["title"] == "T"
        w.answers.append("no")
        assert w.run(lambda: app_module.messagebox.askyesno("T", "Q?")) is False


def test_hot_reload_watcher_tells_the_page_what_changed(tmp_path, monkeypatch):
    """A development checkout's watcher: a stylesheet save is swapped in
    place ("css"), a script save reloads the page ("full"), and a Python
    save only flags the header's restart chip."""
    import os
    import time
    from pinball_decryptor.webui import devreload
    from pinball_decryptor.webui.context import Context
    static = tmp_path / "pkg" / "webui" / "static"
    (static / "css").mkdir(parents=True)
    (static / "js").mkdir()
    css, js = static / "css" / "a.css", static / "js" / "a.js"
    py = tmp_path / "pkg" / "mod.py"
    for f in (css, js, py):
        f.write_text("x", encoding="utf-8")
    monkeypatch.setattr(devreload, "STATIC", str(static))
    monkeypatch.setattr(devreload, "PKG", str(tmp_path / "pkg"))
    monkeypatch.setattr(devreload, "POLL_S", 0.05)
    ctx = Context()
    ctx.loop.start()
    seen = []
    orig = ctx.bus.publish
    monkeypatch.setattr(ctx.bus, "publish",
                        lambda etype, **d: (seen.append((etype, d)),
                                            orig(etype, **d)))
    w = devreload.Watcher(ctx)
    w.start()
    try:
        def bump(p):
            st = os.stat(p)
            os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))

        def wait(pred):
            end = time.time() + 5
            while time.time() < end and not pred():
                time.sleep(0.05)
            return pred()
        time.sleep(0.2)
        bump(css)
        assert wait(lambda: ("dev_reload", {"kind": "css", "files": ["css/a.css"]}) in seen)
        bump(js)
        assert wait(lambda: any(e == "dev_reload" and d["kind"] == "full" for e, d in seen))
        bump(py)
        assert wait(lambda: (ctx.store.get("shell", "dev_py_changed") or []) == ["mod.py"])
    finally:
        w.stop()
        ctx.loop.stop()
        ctx.bus.close()


def test_hot_reload_is_off_in_a_frozen_build(monkeypatch):
    import sys
    from pinball_decryptor.webui import devreload
    monkeypatch.delenv("PAD_UI_HOT", raising=False)
    assert devreload.enabled()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert not devreload.enabled()
    monkeypatch.delattr(sys, "frozen")
    monkeypatch.setenv("PAD_UI_HOT", "0")
    assert not devreload.enabled()


def test_a_failing_ui_job_is_reported_in_the_log(tmp_path):
    """An exception escaping a button handler or an ``after`` callback lands
    in the log pane as one line (the traceback goes to the session log), as
    Tk's report_callback_exception did: never swallowed, never a dialog."""
    with web_app(tmp_path, mfr="stern") as w:
        def boom():
            raise ValueError("the rename half happened")
        w.ctx.loop.post(boom)
        w.drain()
        lines = [e["text"] for e in w.window._log["stern"]]
        hit = [t for t in lines if t.startswith("Internal error in ValueError")]
        assert hit and "the rename half happened" in hit[0], lines
