"""A BoF game's one window on a cabinet's screens (PAD-1308):
tools/spike2_emu/vpx/padsplit.py, tools/bof_emu/bofplace.py and run_game.sh's
split, the Emulate BoF tab's Cabinet screens card, and the Visual Pinball
kit's hook. What is worth failing on, none of it needing Windows or a run:

  * EACH TITLE'S PARTS are where the live windows drew them (read off runs,
    2026-11-14): Dune and Labyrinth 1280x1110, the main display over the
    1280x390 strip; Winchester 3286x768, the 1366x768 main display beside
    the 1920x720 reflected one. A wrong rectangle shows half of one display
    and half of the other.
  * THE GAME'S WINDOW HIDES UNDER A PART WINDOW: WSLg never lets it off the
    desktop and Windows can't hide it (msrdc refused every call), so where it
    goes is picked to show nothing on a monitor no part window covers.
  * WSLg's margin: the split's unfocusable window has none, an ordinary one
    32 px all round; the window is found by its size either way.
  * The status protocol is padloading.py's, so the controller drives either.
"""
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMU = os.path.join(ROOT, "tools", "spike2_emu")
VPX = os.path.join(EMU, "vpx")
for p in (VPX, EMU):
    if p not in sys.path:
        sys.path.insert(0, p)

import padsplit    # noqa: E402

#: a cabinet: the playfield monitor (Visual Pinball's) main, the backbox
#: above it, the strip below
PLAYFIELD = {"n": 1, "x": 0, "y": 0, "w": 1920, "h": 1080, "primary": True}
BACKBOX = {"n": 2, "x": 0, "y": -1080, "w": 1920, "h": 1080, "primary": False}
STRIP = {"n": 3, "x": 0, "y": 1080, "w": 1280, "h": 390, "primary": False}
CABINET = [PLAYFIELD, BACKBOX, STRIP]
SPLIT = {"on": True, "main": 2, "second": 3, "fit": "keep"}


# ------------------------------------------------------------------ layouts
def test_the_measured_layouts():
    size, parts = padsplit.layout("dune")
    assert size == (1280, 1110)
    assert parts == [("main", (0, 0, 1280, 720)), ("second", (0, 720, 1280, 390))]
    assert padsplit.layout("labyrinth") == (size, parts)
    size, parts = padsplit.layout("winchester")
    assert size == (3286, 768)
    assert parts == [("main", (0, 0, 1366, 768)), ("second", (1366, 0, 1920, 720))]


def test_a_title_the_launch_could_not_name_is_known_by_its_size():
    assert padsplit.layout("", (3286, 768)) == padsplit.layout("winchester")
    assert padsplit.layout("", (1280, 1110)) == padsplit.layout("dune")


def test_an_unmeasured_size_is_cut_strip_at_the_bottom():
    size, parts = padsplit.layout("bonjovi", (1920, 1470))
    assert parts == [("main", (0, 0, 1920, 1080)), ("second", (0, 1080, 1280, 390))]
    assert padsplit.layout("x", (800, 300))[1] == [("main", (0, 0, 800, 300))]
    assert padsplit.layout("x") == (None, [])


def test_the_second_display_is_named_for_the_title():
    assert padsplit.part_name("main", "dune") == "Main display"
    assert padsplit.part_name("second", "dune") == "Playfield display"
    assert padsplit.part_name("second", "winchester") == "Reflected display"


# ------------------------------------------------------------------ the plan
def test_fit_keeps_the_shape_centred_or_fills():
    mon = {"x": 100, "y": 50, "w": 1920, "h": 1080}
    assert padsplit.fit_rect((1280, 720), mon) == (100, 50, 1920, 1080)
    assert padsplit.fit_rect((1280, 390), mon) == (100, 50 + (1080 - 585) // 2, 1920, 585)
    assert padsplit.fit_rect((1280, 390), mon, "fill") == (100, 50, 1920, 1080)


def test_each_part_fills_its_monitor():
    plans = {p["part"]: p for p in padsplit.plan(SPLIT, "dune", CABINET)}
    assert plans["main"]["window"] == (0, -1080, 1920, 1080)
    assert plans["main"]["dest"] == (0, 0, 1920, 1080)
    assert plans["main"]["src"] == (0, 0, 1280, 720)
    assert plans["second"]["window"] == (0, 1080, 1280, 390)
    assert plans["second"]["dest"] == (0, 0, 1280, 390)


def test_a_part_with_no_monitor_or_a_missing_one_is_not_shown():
    assert [p["part"] for p in padsplit.plan(dict(SPLIT, second=0), "dune", CABINET)] == ["main"]
    assert [p["part"] for p in padsplit.plan(dict(SPLIT, main=7), "dune", CABINET)] == ["second"]


def test_a_test_spot_overrides_the_monitor():
    plans = padsplit.plan(SPLIT, "dune", CABINET, fixed={"second": (-9000, 0, 640, 195)})
    second = [p for p in plans if p["part"] == "second"][0]
    assert second["window"] == (-9000, 0, 640, 195) and second["dest"] == (0, 0, 640, 195)


# ------------------------------------------------------------------ hiding
def test_the_game_window_hides_where_nothing_of_it_shows():
    """Under the backbox's top-left it would hang 30 px into the playfield
    monitor below (Visual Pinball's); flush with the backbox's bottom it
    overhangs above, off every monitor."""
    plans = padsplit.plan(SPLIT, "dune", CABINET)
    assert padsplit.exposed((0, -1080, 1280, 1110), plans, CABINET) == 1280 * 30
    assert padsplit.cover_spot(plans, (1280, 1110), CABINET) == (0, -1110)
    assert padsplit.exposed((0, -1110, 1280, 1110), plans, CABINET) == 0


def test_one_screen_the_window_goes_under_it():
    mons = [dict(PLAYFIELD, w=1024, h=768)]
    plans = padsplit.plan({"on": True, "main": 1, "second": 0}, "dune", mons)
    assert padsplit.cover_spot(plans, (1280, 1110), mons) == (0, 0)


def test_no_part_on_a_monitor_leaves_the_window_be():
    plans = padsplit.plan(SPLIT, "dune", CABINET, fixed={"main": (-9000, 0, 10, 10),
                                                          "second": (-9000, 20, 10, 10)})
    assert padsplit.cover_spot(plans, (1280, 1110), CABINET) is None


def test_place_env():
    assert padsplit.place_env(dict(SPLIT, on=False), CABINET) == []
    assert padsplit.place_env({"on": True, "main": 0, "second": 0}, CABINET) == []
    env = padsplit.place_env(SPLIT, CABINET)
    assert env[0] == "PAD_BOF_SPLIT=1"
    spots = dict(kv.split(":") for kv in env[1].split("=", 1)[1].split(";"))
    assert spots["dune"] == spots["labyrinth"] == spots["*"] == "0,-1110"
    # Winchester's 3286 px are wider than any monitor: some of it hangs
    # off the backbox's side, never onto the playfield monitor
    x, y = (int(v) for v in spots["winchester"].split(","))
    plans = padsplit.plan(SPLIT, "winchester", CABINET)
    assert padsplit.exposed((x, y, 3286, 768), plans, CABINET) == 0


# ------------------------------------------------------------------ the window
def test_the_window_is_found_by_its_size_with_or_without_the_margin():
    assert padsplit.is_game_size((1280, 1110), "dune")
    assert padsplit.is_game_size((1344, 1174), "dune")
    assert not padsplit.is_game_size((1344, 1174), "winchester")
    assert padsplit.is_game_size((3286, 768), "")
    assert not padsplit.is_game_size((376, 297), "")          # some other WSLg window
    assert padsplit.game_size((1344, 1174)) == (1280, 1110)
    assert padsplit.game_size((1280, 1110)) == (1280, 1110)
    assert padsplit.margins((1344, 1174), (1280, 1110)) == (32, 32)
    assert padsplit.margins((1280, 1110), (1280, 1110)) == (0, 0)


# ------------------------------------------------------------------ status, setting
def test_the_status_protocol(tmp_path):
    f = tmp_path / "st.txt"
    assert padsplit.read_status(str(f)) == ("", None, "")
    f.write_text("boot 30 Decrypting the game\n")
    assert padsplit.read_status(str(f)) == ("boot", 30, "Decrypting the game")
    f.write_text("boot 30 x\nup\n")
    assert padsplit.read_status(str(f))[0] == "up"
    f.write_text("failed The game did not start.")
    assert padsplit.read_status(str(f)) == ("failed", None, "The game did not start.")
    f.write_text("stop")
    assert padsplit.read_status(str(f))[0] == "stop"
    assert padsplit.loading_lines("winchester", "second", "boot", "Starting the boards")[:2] \
        == ["Winchester Mystery House", "is starting"]


def test_the_setting_file(tmp_path):
    conf = str(tmp_path / "split.json")
    assert padsplit.load(conf) == padsplit.DEFAULT
    padsplit.save({"on": True, "main": 2}, conf)
    padsplit.save({"second": "3", "fit": "fill", "junk": 1}, conf)
    assert padsplit.load(conf) == {"on": True, "main": 2, "second": 3, "fit": "fill"}
    with open(conf, "w") as f:
        f.write(json.dumps({"on": 1, "main": -4, "second": "x", "fit": "huge"}))
    assert padsplit.load(conf) == {"on": True, "main": 0, "second": 0, "fit": "keep"}
    assert not padsplit.active({"on": True, "main": 0, "second": 0})
    assert padsplit.active({"on": True, "main": 0, "second": 3})


# ------------------------------------------------------------------ run_game.sh
def _run_game():
    with open(os.path.join(ROOT, "tools", "bof_emu", "run_game.sh"), encoding="utf-8") as f:
        return f.read()


@pytest.mark.skipif(shutil.which("bash") is None, reason="no bash")
def test_run_game_picks_its_titles_spot():
    src = _run_game()
    fn = src[src.index("bof_place_at() {"):]
    fn = fn[:fn.index("\n}\n") + 3]
    script = fn + "\n".join(
        'printf "[%%s]\\n" "$(bof_place_at %s %s)"' % (a, t) for a, t in (
            ("'dune:1,2;winchester:5,6;*:7,8'", "dune"),
            ("'dune:1,2;*:7,8'", "labyrinth"),
            ("'*:7,8;dune:1,2'", "dune"),
            ("'3,4'", "dune"),
            ("''", "dune"),
            ("'winchester:5,6'", "dune"))) + "\n"
    # on stdin: on Windows `bash` may be WSL's, which cannot read a Windows path
    out = subprocess.run(["bash"], input=script.encode(), stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, timeout=60).stdout.decode().split()
    assert out == ["[1,2]", "[7,8]", "[1,2]", "[3,4]", "[]", "[]"]


def test_the_split_window_is_the_shipped_slab_and_unfocusable():
    src = _run_game()
    block = src[src.index('"${PAD_BOF_SPLIT:-0}" = 1 ]; then'):src.index("elif [ $VISIBLE = 1 ]")]
    for want in ("window/size/borderless=true", "window/size/resizable=false",
                 "window/size/no_focus=true"):
        assert want in block
    assert "stretch" not in block                 # every part at the game's own pixels
    assert "bofplace.py" in src and '--at "$PLACE_AT"' in src


def test_a_hidden_run_has_room_for_winchester():
    assert "3840x1440x24" in _run_game()
    with open(os.path.join(ROOT, "tools", "bof_emu", "shot.sh"), encoding="utf-8") as f:
        assert "SIZE=3840x1440" in f.read()


# ------------------------------------------------------------------ the kit
def test_the_kit_splits_bof_runs_only(monkeypatch):
    import padlaunch

    class Bof:
        rig_wsl = "/mnt/c/PAD/tools/bof_emu"

    class Spooky:
        rig_wsl = "/mnt/c/PAD/tools/spooky_emu"
    assert padlaunch.is_bof(Bof()) and not padlaunch.is_bof(Spooky()) \
        and not padlaunch.is_bof(object())
    monkeypatch.setattr(padsplit, "load", lambda path=None: dict(SPLIT))
    monkeypatch.setattr(padsplit.padisplay, "monitors", lambda: CABINET)
    assert padlaunch.split_env()[0] == "PAD_BOF_SPLIT=1"
    monkeypatch.setattr(padsplit, "load", lambda path=None: dict(SPLIT, on=False))
    assert padlaunch.split_env() == []


def test_the_controller_keeps_the_split_past_up_and_stops_it(tmp_path, monkeypatch):
    import padcontroller
    b = padcontroller.Bridge.__new__(padcontroller.Bridge)
    b.title = "dune"
    b._loading_file = str(tmp_path / "status.txt")
    killed = []
    monkeypatch.setattr(padcontroller.Bridge, "_loading_kill", staticmethod(killed.append))

    class Proc:
        def poll(self):
            return None
    proc = Proc()
    b._loading, b._loading_split = proc, True
    b._loading_end("up")
    time.sleep(0.2)
    assert killed == [] and b._split is proc
    assert open(b._loading_file).read() == "up"
    b._split_end()
    assert open(b._loading_file).read() == "stop"
    time.sleep(2.3)
    assert killed == [proc]
    # a plain loading window still goes at once on up
    b._loading, b._loading_split, b._split = proc, False, None
    b._loading_end("up")
    time.sleep(0.2)
    assert killed == [proc, proc]


# ------------------------------------------------------------------ the tab
class _FakeSplit:
    """padsplit as the tab loads it, its setting in memory."""
    PARTS = padsplit.PARTS

    def __init__(self):
        self.s = dict(padsplit.DEFAULT)

        class _D:
            @staticmethod
            def monitors():
                return CABINET
        self.padisplay = _D()

    def load(self, path=None):
        return dict(self.s)

    def save(self, change, path=None):
        self.s.update(change)
        return dict(self.s)

    active = staticmethod(padsplit.active)

    def place_env(self, setting=None, mons=None):
        return padsplit.place_env(setting or self.s, CABINET)


@pytest.fixture
def tab_split(monkeypatch):
    from pinball_decryptor.webui.tabs import emulate_bof
    from pinball_decryptor.webui import emulate_bof_core as core
    fake = _FakeSplit()
    monkeypatch.setattr(emulate_bof, "padsplit_mod", lambda: fake)
    monkeypatch.setattr(emulate_bof, "_on_windows", lambda: True)
    monkeypatch.setattr(emulate_bof, "physical", lambda fn, *a: fn(*a))
    monkeypatch.setattr(core, "rig_available", lambda: True)
    monkeypatch.setattr(core, "platform_ok", lambda: True)
    return fake


def test_the_tab_shows_and_saves_the_cabinet_screens(tab_split, tmp_path):
    from tests.webui_harness import web_app
    with web_app(tmp_path, mfr="bof") as w:
        sp = w.state("emulate_bof")["split"]
        assert sp["on"] is False and sp["main"] == "0" and sp["fit"] == "keep"
        assert [o["value"] for o in sp["mons"]] == ["0", "1", "2", "3"]
        assert sp["mons"][1]["label"] == "Monitor 1 - 1920x1080 (main)"
        assert w.call("emulate_bof.split_set", "on", True)
        assert w.call("emulate_bof.split_set", "main", "2")
        assert w.call("emulate_bof.split_set", "fit", "fill")
        assert not w.call("emulate_bof.split_set", "fit", "huge")
        assert not w.call("emulate_bof.split_set", "nonsense", 1)
        assert tab_split.s == {"on": True, "main": 2, "second": 0, "fit": "fill"}
        sp = w.state("emulate_bof")["split"]
        assert sp["on"] and sp["main"] == "2" and sp["fit"] == "fill"
        tab_split.s["second"] = 9                          # unplugged since
        w.window.service("emulate_bof")._split_paint()
        assert w.state("emulate_bof")["split"]["mons"][-1] == {
            "value": "9", "label": "Monitor 9 - not connected"}


def test_a_start_opens_the_split_and_tells_it_how_the_run_goes(tab_split, tmp_path, monkeypatch):
    from tests.webui_harness import web_app
    from pinball_decryptor.webui.tabs import emulate_bof
    started = []

    class Proc:
        def __init__(self, cmd, **kw):
            started.append(cmd)

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            pass
    from pinball_decryptor.webui import theme
    monkeypatch.setattr(emulate_bof.subprocess, "Popen", Proc)
    # on macOS the window asks `defaults read -g AppleInterfaceStyle` for its theme through that same Popen
    monkeypatch.setattr(theme, "detect_system_theme", lambda: "light")
    monkeypatch.setattr(emulate_bof, "windows_python", lambda *a, **k: "pythonw.exe")
    monkeypatch.setattr(emulate_bof.rigslot, "hidden", lambda: False)
    monkeypatch.setattr(emulate_bof.tempfile, "gettempdir", lambda: str(tmp_path))
    with web_app(tmp_path, mfr="bof") as w:
        svc = w.window.service("emulate_bof")
        assert svc._split_begin(str(tmp_path / "dune.fun")) == []      # off: nothing
        assert started == []
        tab_split.s.update(on=True, main=2, second=3)
        env = svc._split_begin(str(tmp_path / "dune.fun"))
        assert env[0] == "PAD_BOF_SPLIT=1" and env[1].startswith("PAD_BOF_PLACE=dune:0,-1110;")
        cmd = started[-1]
        assert cmd[0] == "pythonw.exe" and cmd[1].endswith(os.path.join("vpx", "padsplit.py"))
        assert cmd[cmd.index("--title") + 1] == "dune"
        status = cmd[cmd.index("--status") + 1]
        svc._footer = lambda *a, **k: None
        for line in ("== Decrypt ==", "progress 50", "== Boards =="):
            svc._footer_line(line)
        lines = open(status, encoding="utf-8").read().splitlines()
        assert lines[0] == "boot 0 Getting ready"
        assert padsplit.read_status(status)[:2] == ("boot", 65)
        assert "boot 32 Decrypting the game… 50%" in lines
        svc._split_end()
        assert padsplit.read_status(status)[0] == "stop"
        assert svc._split_proc is None and svc._split_status is None


def test_a_hidden_app_never_splits(tab_split, tmp_path, monkeypatch):
    from tests.webui_harness import web_app
    from pinball_decryptor.webui.tabs import emulate_bof
    monkeypatch.setattr(emulate_bof.rigslot, "hidden", lambda: True)
    tab_split.s.update(on=True, main=2)
    with web_app(tmp_path, mfr="bof") as w:
        assert w.window.service("emulate_bof")._split_begin("dune.fun") == []
