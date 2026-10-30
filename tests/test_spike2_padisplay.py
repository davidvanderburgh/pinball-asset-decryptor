"""PAD-811: where the Spike 2 game window goes (tools/spike2_emu/padisplay.py),
and the Emulate tab's Game display control that sets it.

padisplay resolves the user's choice (a monitor, a mode, a rectangle on that
monitor) into the desktop pixels padglhost acts on.  Every path here is a temp
one: the real %USERPROFILE%\\.pad-rig\\display.conf moves a running game's
window, so no test may write it.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMU = os.path.join(ROOT, "tools", "spike2_emu")
if EMU not in sys.path:
    sys.path.insert(0, EMU)

pytestmark = pytest.mark.skipif(not os.path.isfile(os.path.join(EMU, "padisplay.py")),
                                reason="rig not present")

MONS = [{"n": 1, "x": 0, "y": 0, "w": 1920, "h": 1080, "primary": True},
        {"n": 2, "x": 1920, "y": 0, "w": 2560, "h": 1440, "primary": False},
        {"n": 3, "x": -1280, "y": 200, "w": 1280, "h": 1024, "primary": False}]


@pytest.fixture
def pd(monkeypatch, tmp_path):
    import padisplay
    monkeypatch.setattr(padisplay, "CONF", str(tmp_path / "display.conf"))
    monkeypatch.setattr(padisplay, "monitors", lambda: [dict(m) for m in MONS])
    return padisplay


def _kv(line):
    return dict(t.split("=", 1) for t in line.split()[1:])


def test_fullscreen_fills_the_named_monitor(pd):
    kv = _kv(pd.resolve({"mode": "fullscreen", "monitor": 2, "border": False}, MONS))
    assert (kv["x"], kv["y"], kv["w"], kv["h"], kv["fs"]) == ("1920", "0", "2560", "1440", "1")
    assert kv["monitor"] == "2" and kv["border"] == "0"


def test_a_window_is_offset_by_its_monitors_origin(pd):
    kv = _kv(pd.resolve({"mode": "window", "monitor": 3, "border": True,
                         "rx": 10, "ry": 20, "w": 1360, "h": 768}, MONS))
    assert (kv["x"], kv["y"], kv["w"], kv["h"], kv["fs"]) == ("-1270", "220", "1360", "768", "0")
    assert (kv["rx"], kv["ry"], kv["border"]) == ("10", "20", "1")


def test_a_missing_monitor_falls_back_to_the_main_one(pd):
    kv = _kv(pd.resolve({"mode": "fullscreen", "monitor": 7}, MONS))
    assert (kv["monitor"], kv["x"], kv["y"], kv["w"], kv["h"]) == ("1", "0", "0", "1920", "1080")
    assert "not connected" in pd.describe({"mode": "fullscreen", "monitor": 7}, MONS)


def test_free_writes_no_line(pd):
    assert pd.resolve({"mode": "free", "monitor": 2}, MONS) is None
    assert pd.save({"mode": "free"}, pd.CONF) is None
    assert not [ln for ln in open(pd.CONF, encoding="utf-8") if ln.startswith("game")]
    assert pd.load(pd.CONF)["mode"] == "free"


def test_load_round_trips_save(pd):
    win = {"mode": "window", "monitor": 2, "border": False, "rx": 100, "ry": 50, "w": 1360, "h": 768}
    pd.save(win, pd.CONF)
    assert pd.load(pd.CONF) == win
    full = {"mode": "fullscreen", "monitor": 3, "border": True}
    pd.save(full, pd.CONF)
    got = pd.load(pd.CONF)
    assert {k: got[k] for k in full} == full
    assert pd.load(os.path.join(os.path.dirname(pd.CONF), "none.conf"))["mode"] == "free"


# ------------------------------------------------- the Emulate tab's control
def _tab(tmp_path, monkeypatch, pd):
    from pinball_decryptor.webui import emulate_rig
    from pinball_decryptor.webui.tabs import emulate as E
    from tests.webui_harness import web_app
    monkeypatch.setattr(emulate_rig, "rig_available", lambda: True)
    monkeypatch.setattr(E, "padisplay_mod", lambda: pd)
    return web_app(tmp_path, mfr="stern")


def test_the_emulate_tab_lists_the_monitors_and_saves_each_change(tmp_path, monkeypatch, pd):
    with _tab(tmp_path, monkeypatch, pd) as w:
        svc = w.window.service("emulate")
        w.run(svc._display_paint)
        d = w.state("emulate")["gdisp"]
        assert d["mode"] == "free" and d["monitor"] == "1"
        assert [o["label"] for o in d["mons"]] == [
            "1 - 1920x1080 (main)", "2 - 2560x1440", "3 - 1280x1024"]
        # a new choice starts borderless
        assert w.call("emulate.display_set", "mode", "fullscreen") is True
        got = pd.load(pd.CONF)
        assert (got["mode"], got["monitor"], got["border"]) == ("fullscreen", 1, False)
        assert w.call("emulate.display_set", "monitor", "2") is True
        assert w.state("emulate")["gdisp"]["text"] == "full screen on monitor 2, borderless"
        # window mode starts at the Spike 2 screen's own size, at the corner
        assert w.call("emulate.display_set", "mode", "window") is True
        got = pd.load(pd.CONF)
        assert (got["rx"], got["ry"], got["w"], got["h"]) == (0, 0, 1360, 768)
        assert w.call("emulate.display_set", "rx", "40") is True
        assert w.call("emulate.display_set", "border", True) is True
        got = pd.load(pd.CONF)
        assert got["rx"] == 40 and got["border"] is True and got["monitor"] == 2
        # nonsense changes nothing
        assert w.call("emulate.display_set", "w", "wide") is False
        assert w.call("emulate.display_set", "mode", "huge") is False
        assert w.call("emulate.display_set", "colour", 1) is False
        assert pd.load(pd.CONF) == got
        assert w.call("emulate.display_set", "mode", "free") is True
        assert pd.load(pd.CONF)["mode"] == "free"


def test_the_emulate_tab_shows_an_unplugged_monitor(tmp_path, monkeypatch, pd):
    # saved while monitor 5 was there, then it was unplugged
    monkeypatch.setattr(pd, "monitors", lambda: MONS + [
        {"n": 5, "x": 5000, "y": 0, "w": 800, "h": 600, "primary": False}])
    pd.save({"mode": "fullscreen", "monitor": 5, "border": False}, pd.CONF)
    monkeypatch.setattr(pd, "monitors", lambda: [dict(m) for m in MONS])
    with _tab(tmp_path, monkeypatch, pd) as w:
        w.run(w.window.service("emulate")._display_paint)
        d = w.state("emulate")["gdisp"]
        assert d["monitor"] == "5" and d["mons"][-1]["label"] == "5 - not connected"


def test_no_rig_no_control(tmp_path, monkeypatch):
    from pinball_decryptor.webui.tabs import emulate as E
    from tests.webui_harness import web_app
    monkeypatch.setattr(E, "padisplay_mod", lambda: None)
    with web_app(tmp_path, mfr="stern") as w:
        assert w.state("emulate")["gdisp"] is None
        assert w.call("emulate.display_set", "mode", "fullscreen") is False
