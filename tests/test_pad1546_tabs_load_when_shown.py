"""PAD-1546: opening the last project at start no longer reads what only a tab
behind the one on screen shows (the Modes tab's ports, the Color profiles, Play
options, the service menu, the Network tab's Score feed and online co-op): each
reads it when it is next shown.  The lines the restore logs are written in one
piece, and the page no longer misses a change that lands between its first
render and its subscription (it stayed on "Starting..." until a later one)."""

import os
import shutil
import subprocess

import pytest

from pinball_decryptor.core import session_log
from tests.webui_harness import web_app

_JS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                   "webui", "static", "js")


def _counter(monkeypatch, obj, name):
    calls = []
    monkeypatch.setattr(obj, name, lambda *a, **k: calls.append(a))
    return calls


def test_the_colour_profiles_wait_for_a_tab_that_shows_them(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.select_tab", "card")
        w.drain()
        svc = w.window.service("color")
        seen = []
        monkeypatch.setattr(svc, "_load", lambda: seen.append(w.ctx.store.get("shell", "tab")))
        w.run(svc.on_manufacturer, w.window.current_mfr)
        w.run(svc.on_project, str(tmp_path))
        assert seen == [] and svc._unread
        w.call("ui.select_tab", "extract")
        assert seen == []
        # the Colors bar on Images reads them as it is shown, once
        w.call("ui.select_tab", "images")
        assert seen == ["images"] and not svc._unread
        w.call("ui.select_tab", "video")
        assert seen == ["images"]
        # on a tab that shows them a change is read at once
        w.run(svc.on_project, str(tmp_path))
        assert seen == ["images", "video"]


def test_the_colour_tab_itself_reads_them_once_when_shown(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.select_tab", "card")
        w.drain()
        svc = w.window.service("color")
        seen = _counter(monkeypatch, svc, "_load")
        w.run(svc.on_manufacturer, w.window.current_mfr)
        assert seen == []
        w.call("ui.select_tab", "color")
        assert len(seen) == 1 and not svc._unread


def test_the_modes_tab_reads_its_ports_when_it_is_shown(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        svc = w.window.service("modes")
        assert getattr(svc, "_visible", False)     # on the rail for a Spike 2 card
        w.call("ui.select_tab", "card")
        w.drain()
        reads = _counter(monkeypatch, svc, "_refresh_all")
        _counter(monkeypatch, svc, "_refresh_list")
        _counter(monkeypatch, svc, "refresh_stock_modes")
        w.run(svc.on_manufacturer, w.window.current_mfr)
        w.run(svc._on_project_changed)
        w.drain()
        assert reads == [] and svc._unread
        w.call("ui.select_tab", "modes")
        assert len(reads) == 1 and not svc._unread
        # back again with nothing changed: the light re-read, not the whole one
        w.call("ui.select_tab", "card")
        w.call("ui.select_tab", "modes")
        assert len(reads) == 1
        # while it is on screen a manufacturer change reads it at once
        w.run(svc.on_manufacturer, w.window.current_mfr)
        assert len(reads) == 2


@pytest.mark.parametrize("ns", ["playopts", "svcmenu"])
def test_play_options_and_the_service_menu_publish_only_when_shown(tmp_path, monkeypatch, ns):
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.select_tab", "card")
        w.drain()
        svc = w.window.service(ns)
        rail = getattr(svc, "_visible", False)
        published = _counter(monkeypatch, svc, "publish")
        w.run(svc.on_manufacturer, w.window.current_mfr)
        w.run(svc.on_project, str(tmp_path))
        assert published == []
        w.call("ui.select_tab", ns)
        assert len(published) == 1
        w.run(svc.on_project, str(tmp_path))
        assert len(published) == 2
        # the window's rail flag is the window's: showing and leaving the tab leave it be
        w.call("ui.select_tab", "card")
        assert getattr(svc, "_visible", False) == rail


def test_leaving_a_tab_tells_it(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        net = w.window.service("network")
        hidden = _counter(monkeypatch, net, "on_hide")
        w.call("ui.select_tab", "network")
        w.call("ui.select_tab", "network")          # the same tab again: not left
        assert hidden == []
        w.call("ui.select_tab", "card")
        assert len(hidden) == 1


def test_network_publishes_its_cheap_part_behind_another_tab(tmp_path, monkeypatch):
    """Build reads the Network tab's error, so its publish still runs at every change;
    only the boxes that read the project's port files wait for the tab."""
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.select_tab", "card")
        w.drain()
        net = w.window.service("network")
        feed = _counter(monkeypatch, net, "_publish_feed")
        online = _counter(monkeypatch, net, "_publish_online")
        inspect = []
        real = net._inspect
        monkeypatch.setattr(net, "_inspect", lambda: inspect.append(1) or real())
        w.run(net.on_manufacturer, w.window.current_mfr)
        assert inspect and feed == [] and online == []
        w.call("ui.select_tab", "network")
        assert len(feed) == 1 and len(online) == 1


def test_a_batch_holds_the_project_banners_with_its_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(session_log, "LOG_DIR_OVERRIDE", str(tmp_path / "logs"))
    monkeypatch.setattr(session_log, "_project_dir", None)
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    writes = []
    real = session_log._append_raw
    monkeypatch.setattr(session_log, "_append_raw", lambda text: (writes.append(text), real(text)))
    with session_log.batched():
        session_log.append("before any project")
        assert session_log.set_project(str(one), version="9.9")
        session_log.append("in one")
        assert session_log.set_project(str(two), version="9.9")
        session_log.append("in two")
        assert writes == []
        assert not os.path.exists(session_log.project_log_path(str(one)))
    assert len(writes) == 1                          # the session log opened once
    log = open(session_log.log_path(), encoding="utf-8").read()
    order = [log.index(s) for s in ("before any project", "----- Project: one", "in one",
                                    "----- Project: two", "in two")]
    assert order == sorted(order)
    first = open(session_log.project_log_path(str(one)), encoding="utf-8").read()
    second = open(session_log.project_log_path(str(two)), encoding="utf-8").read()
    assert "one opened" in first and "in one" in first
    assert "before any project" not in first and "in two" not in first
    assert first.index("one opened") < first.index("in one")
    assert "two opened" in second and "in two" in second and "in one" not in second
    # outside a batch every line is written as it comes, as before
    session_log.append("unbatched")
    assert len(writes) == 2
    assert "unbatched" in open(session_log.project_log_path(str(two)), encoding="utf-8").read()


def test_the_page_store_parses_and_subscribes_in_the_render_task(tmp_path):
    src = open(os.path.join(_JS, "core", "store.js"), encoding="utf-8").read()
    # a plain effect subscribes a frame after the render (a hidden window's, a
    # second): a change in between was lost and the shell stayed on Starting
    body = src[src.index("export function useNs"):src.index("export function onEvent")]
    assert "useLayoutEffect" in body and "useEffect(" not in body
    assert "nsVersion.get(ns)" in body and "logVersion" in body
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on this PC")
    mod = tmp_path / "store.mjs"
    mod.write_text(src, encoding="utf-8")
    got = subprocess.run([node, "--check", str(mod)], capture_output=True, text=True, timeout=60)
    assert got.returncode == 0, got.stderr
