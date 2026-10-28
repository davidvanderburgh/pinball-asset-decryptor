"""The Visual Pinball tab (PAD-802): the kit in the app, behind a preview code.

What is worth failing on:

  * THE GATE. The tab shows only with a preview code for "vpx", only on
    Windows, and only for a manufacturer the Spike 2 emulator runs; without a
    code nobody sees it.
  * THE KIT STAYS OUT OF PROCESS. The tab runs the kit's own scripts and reads
    the LAST JSON line they print; anything else (a traceback, nothing) is an
    error the page can show, never a crash.
  * PATCH WRITES INTO VISUAL PINBALL'S TABLES FOLDER, from the person's own
    download, and says so when the table is not one the kit knows.
"""
import os
import sys
import time
import types

import pytest

from pinball_decryptor.core import preview
from pinball_decryptor.webui.tabs import vpx as V


class _Store:
    def __init__(self):
        self.d = {}

    def set(self, ns, **kw):
        self.d.setdefault(ns, {}).update(kw)

    def get(self, ns, k, default=None):
        return self.d.get(ns, {}).get(k, default)


class _Loop:
    def post(self, fn, *a):
        fn(*a)


class _Win:
    def __init__(self, pick=""):
        self.ctx = types.SimpleNamespace(store=_Store(), loop=_Loop())
        self.lines = []
        self.pick = pick

    def bind_var(self, *a):
        pass

    def append_log(self, text, level="info"):
        self.lines.append((level, text))

    def ask_open(self, *a, **k):
        return self.pick

    def ask_folder(self, *a, **k):
        return self.pick


def _wait(tab):
    deadline = time.time() + 10
    while tab._busy and time.time() < deadline:
        time.sleep(0.02)
    assert not tab._busy


@pytest.fixture
def tab(monkeypatch):
    monkeypatch.setattr(V.sys, "platform", "win32")
    monkeypatch.setattr(V.os.path, "isfile", lambda p, _f=os.path.isfile: True if p.endswith("vpxsetup.py") else _f(p))
    calls = []
    state = {"registered": True, "vpx": r"C:\VP", "tables_dir": r"C:\VP\tables", "library": "",
             "cards": {}, "tables": [], "patched": [], "presets": [], "layout": ""}

    def kit(self, script, args, timeout=0, on_line=None):
        calls.append((script, list(args)))
        if args and args[0] == "state":
            return dict(state)
        return self.answers.get((script, args[0]), {"result": "ok", "_text": ""})
    monkeypatch.setattr(V.VpxTab, "_kit", kit)
    from pinball_decryptor.core import runtime
    monkeypatch.setattr(runtime, "status", lambda **k: ("ready", "Runtime 6."))
    V.VpxTab.answers = {}
    t = V.VpxTab(_Win())
    t.calls = calls
    return t


def test_the_preview_names_the_tab():
    assert preview.FEATURES.get("vpx") == "Visual Pinball"
    assert V.PREVIEW_FEATURE == "vpx"
    keys = [m[2] for m in __import__("pinball_decryptor.webui.tabs", fromlist=["TABS"]).TABS]
    assert "Visual Pinball" in keys


def test_the_tab_shows_only_with_a_code_on_windows(monkeypatch):
    from pinball_decryptor.webui import window as W
    caps = types.SimpleNamespace(emulate=True)
    mfr = types.SimpleNamespace(capabilities=caps)
    win = W.WebWindow.__new__(W.WebWindow) if hasattr(W, "WebWindow") else None
    if win is None:
        pytest.skip("no WebWindow class")
    monkeypatch.setattr(type(win), "modes_preview_on", lambda self, m=None: False)
    monkeypatch.setattr(W.sys, "platform", "win32")
    monkeypatch.setattr(preview, "_active", frozenset())
    assert win._gate(mfr)["Visual Pinball"] is False
    monkeypatch.setattr(preview, "_active", frozenset({"vpx"}))
    assert win._gate(mfr)["Visual Pinball"] is True
    # not for a manufacturer the Spike 2 emulator does not run
    assert win._gate(types.SimpleNamespace(capabilities=types.SimpleNamespace()))["Visual Pinball"] is False
    # Visual Pinball and the controller are Windows only
    monkeypatch.setattr(W.sys, "platform", "linux")
    assert win._gate(mfr)["Visual Pinball"] is False


def test_the_last_json_line_is_the_answer():
    assert V.last_json('say downloading\nprogress 0.5\n{"result": "ok"}\n') == {"result": "ok"}
    assert V.last_json("Traceback (most recent call last):\n  boom") is None
    assert V.last_json("") is None
    assert V.last_json("{not json") is None


def test_a_kit_that_prints_no_json_is_an_error_not_a_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(V, "kit_python", lambda: sys.executable)
    monkeypatch.setattr(V, "kit_dir", lambda: str(tmp_path))
    (tmp_path / "broken.py").write_text("import sys\nprint('half a line')\nsys.exit(3)\n", encoding="utf-8")
    t = V.VpxTab.__new__(V.VpxTab)
    got = t._kit("broken.py", [])
    assert "exit 3" in got["error"] and "half a line" in got["error"]
    (tmp_path / "good.py").write_text("print('progress 0.1')\nprint('{\"result\": \"ok\"}')\n", encoding="utf-8")
    seen = []
    got = t._kit("good.py", [], on_line=seen.append)
    assert got["result"] == "ok" and seen == ["progress 0.1", '{"result": "ok"}']
    monkeypatch.setattr(V, "kit_python", lambda: None)
    assert "No Windows Python" in t._kit("good.py", [])["error"]


def test_showing_the_tab_reads_the_kit(tab):
    tab.on_show()
    _wait(tab)
    st = tab.window.ctx.store.d["vpx"]
    assert st["loaded"] and st["vpx"] == r"C:\VP" and st["registered"]
    assert ("vpxsetup.py", ["state"]) in tab.calls


def test_patch_writes_into_visual_pinballs_tables_folder(tab):
    tab.on_show()
    _wait(tab)
    tab.window.pick = r"D:\Downloads\Rush LE 2.0.2.vpx"
    tab.answers[("padvpx.py", "patch")] = {
        "_text": 'recognised rush_le: Rush LE ver DrHotWing\nopen "C:\\VP\\tables\\Rush LE 2.0.2 (PAD).vpx" in Visual Pinball'}
    assert tab.patch()
    _wait(tab)
    script, args = [c for c in tab.calls if c[0] == "padvpx.py"][-1]
    assert args == ["patch", os.path.normpath(r"D:\Downloads\Rush LE 2.0.2.vpx"), "--out", r"C:\VP\tables"]
    assert not [ln for ln in tab.window.lines if ln[0] == "error"]


def test_patch_says_when_the_table_is_not_one_the_kit_knows(tab):
    tab.on_show()
    _wait(tab)
    tab.window.pick = r"D:\Downloads\Some Other Table.vpx"
    tab.answers[("padvpx.py", "patch")] = {"_text": "this table is not one the kit knows; it can patch: rush_le"}
    assert tab.patch()
    _wait(tab)
    assert any("not one the app can patch" in t for _, t in tab.window.lines)


def test_nothing_runs_when_a_dialog_is_cancelled(tab):
    tab.window.pick = ""
    assert tab.patch() is False and tab.choose_vpx() is False and tab.choose_library() is False
    assert tab.download_vpx() is False
    assert not [c for c in tab.calls if c[1] and c[1][0] != "state"]


def test_one_job_at_a_time(tab):
    tab._busy = True
    assert tab.refresh() is False and tab.play("x (PAD).vpx") is False
    tab._busy = False


def test_a_layout_is_saved_from_the_presets_the_kit_offered(tab):
    tab.set(presets=[{"key": "side", "words": "Side", "player": [0, 0, 720, 1080], "lcd": [720, 0, 1200, 675]}])
    assert tab.layout("nope") is False
    assert tab.layout("side")
    _wait(tab)
    script, args = [c for c in tab.calls if c[1] and c[1][0] == "layout"][-1]
    assert args == ["layout", "side", "[0, 0, 720, 1080]", "[720, 0, 1200, 675]"]
