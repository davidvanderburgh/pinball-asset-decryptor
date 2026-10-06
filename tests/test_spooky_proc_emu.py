"""tools/spooky_emu/proc (PAD-269): the rig for Spooky's P-ROC titles (Rick
and Morty, Alice Cooper's Nightmare Castle) on tools/proc_emu's board.
The boot itself is proven in WSL (run_game.sh on the real .pkg files); this
pins what runs anywhere: the scripts, and prepare.py's unpacking of a build.
"""

import importlib.util
import os
import pathlib
import struct
import sys
import zipfile

import pytest

RIG = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spooky_emu" / "proc"
SCRIPTS = ("sppath.sh", "setup.sh", "run_game.sh", "netns.sh", "killgame.sh", "shot.sh",
           "sw.sh", "status.sh", "bootcheck.sh", "prepare.py", "spprun.py", "watch.sh",
           "sppctl.py", "sppswitches.py")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


prepare = _load("spooky_proc_prepare", RIG / "prepare.py")
sppctl = _load("spooky_proc_sppctl", RIG / "sppctl.py")
sppswitches = _load("spooky_proc_sppswitches", RIG / "sppswitches.py")


def test_rig_scripts_are_lf_and_complete():
    for name in SCRIPTS:
        data = (RIG / name).read_bytes()
        assert b"\r\n" not in data, name


def test_every_path_comes_from_sppath():
    # sppath.sh owns every path; the other scripts never hard-code the roots.
    for name in SCRIPTS:
        if name in ("sppath.sh", "prepare.py", "sppctl.py"):
            continue
        text = (RIG / name).read_text()
        assert "/var/tmp/pad_spkproc" not in text and "/var/tmp/pad_ap" not in text, name


def test_spprun_is_python2_source():
    # The games are Python 2.7; spprun.py runs inside them.  It must at least
    # parse (py2 and py3 share this syntax), and it never prints.
    src = (RIG / "spprun.py").read_text()
    compile(src, "spprun.py", "exec")
    assert "print" not in src


def test_every_title_has_a_profile():
    run = (RIG / "run_game.sh").read_text()
    for title in prepare.TITLES:
        assert "    %s) DIR=" % title in run, title
    assert run.count("BALLS=\"eject=") == len(prepare.TITLES)


def test_the_keys_are_the_apps_own():
    from pinball_decryptor.plugins.spooky import games
    keys = prepare.keys()
    assert keys["RM_AES_KEY"] == games.RM_AES_KEY and keys["AC_AES_KEY"] == games.AC_AES_KEY


def test_titles_by_file_name():
    assert prepare.title_of("/x/rm-gamecode-20220902.pkg") == "rm"
    assert prepare.title_of("/x/ac-gamecode.pkg") == "ac"
    for other in ("tna-gamecode.pkg", "code_H78.pkg", "v2025.12.01.09.scooby"):
        with pytest.raises(SystemExit) as e:
            prepare.title_of("/x/" + other)
        assert e.value.code == 4


def _fake_pkg(tmp_path, name, members):
    zpath = tmp_path / "inner.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for member, data in members.items():
            z.writestr(zipfile.ZipInfo(member), data)
    pkg = tmp_path / name
    pkg.write_bytes(struct.pack("<Q", zpath.stat().st_size) + b"\0" * 16)
    return pkg, zpath


def _run(monkeypatch, tmp_path, pkg, zpath):
    monkeypatch.setattr(prepare, "SPP_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(prepare, "decrypt",
                        lambda src, out, key: pathlib.Path(out).write_bytes(zpath.read_bytes()))
    monkeypatch.setattr(sys, "argv", ["prepare.py", str(pkg)])
    prepare.main()


def test_prepare_names_rick_and_morty_by_its_date(tmp_path, monkeypatch):
    pkg, zpath = _fake_pkg(tmp_path, "rm-gamecode-20220902.pkg", {
        "RMGame.pyc": b"\x03\xf3", "procgame/__init__.pyc": b"", "config/RM_PROTOTYPE1.yaml": ""})
    _run(monkeypatch, tmp_path, pkg, zpath)
    out = tmp_path / "cache" / "rm_20220902"
    assert (out / "title").read_text().strip() == "rm"
    assert (out / "RMGame.pyc").exists()
    assert sorted(os.listdir(tmp_path / "cache")) == ["rm_20220902"]     # no scratch, no zip


def test_prepare_names_alice_cooper_by_its_version(tmp_path, monkeypatch):
    pkg, zpath = _fake_pkg(tmp_path, "ac-gamecode.pkg", {
        "ACGame.py": "run", "WHATSNEW.txt": "File is in c:\\temp\n\nv1.1.0.5\n  fixes\nV1.1.0.4\n",
        "uptest/main.x86_64": b"\x7fELF"})
    _run(monkeypatch, tmp_path, pkg, zpath)
    out = tmp_path / "cache" / "ac_1.1.0.5"
    assert (out / "title").read_text().strip() == "ac"
    if os.name == "posix":
        assert os.access(out / "uptest" / "main.x86_64", os.X_OK)


def test_prepare_refuses_the_wrong_game_under_a_name(tmp_path, monkeypatch):
    pkg, zpath = _fake_pkg(tmp_path, "ac-gamecode.pkg", {"RMGame.pyc": b""})
    with pytest.raises(SystemExit) as e:
        _run(monkeypatch, tmp_path, pkg, zpath)
    assert e.value.code == 4                            # watch.sh: "not a game it runs"
    assert os.listdir(tmp_path / "cache") == []         # nothing left behind



# ------------------------------------------------------- PAD-319: the tab
def test_prepare_finds_its_build_again_by_the_file(tmp_path, monkeypatch, capsys):
    """The same .pkg again: its build, without decrypting it (Alice Cooper's
    version is only known from inside, so the name alone cannot find it)."""
    pkg, zpath = _fake_pkg(tmp_path, "ac-gamecode.pkg", {
        "ACGame.py": "", "WHATSNEW.txt": "v1.1.0.5 fixes\n"})
    _run(monkeypatch, tmp_path, pkg, zpath)
    out = tmp_path / "cache" / "ac_1.1.0.5"
    assert (out / "src").read_text().strip() == str(pkg.resolve())
    assert capsys.readouterr().out.splitlines()[-1] == "build=ac_1.1.0.5"

    def no(*a):
        raise AssertionError("decrypted again")
    monkeypatch.setattr(prepare, "decrypt", no)
    prepare.main()
    assert capsys.readouterr().out.splitlines()[-1] == "build=ac_1.1.0.5"


def test_prepare_wants_room_first(tmp_path, monkeypatch):
    pkg, zpath = _fake_pkg(tmp_path, "rm-gamecode-20220902.pkg", {"RMGame.pyc": b""})
    monkeypatch.setattr(prepare, "room_for", lambda p: False)
    with pytest.raises(SystemExit) as e:
        _run(monkeypatch, tmp_path, pkg, zpath)
    assert e.value.code == 3


def test_watch_hands_the_proc_games_here():
    """The tab runs tools/spooky_emu's scripts; they send a P-ROC game's file
    here and answer for its run (status, stop, cancel, cache, ctl)."""
    top = RIG.parent
    watch = (top / "watch.sh").read_text()
    assert 'spk_proc_file "$UPD"' in watch and 'bash "$SPK_PROC/watch.sh" "$UPD"' in watch
    assert 'spk_proc_alive && exec bash "$SPK_PROC/status.sh"' in (top / "status.sh").read_text()
    assert 'exec python3 "$SPK_PROC/sppctl.py"' in (top / "ctl.sh").read_text()
    for name in ("stop.sh", "cancel.sh"):
        assert 'bash "$SPK_PROC/killgame.sh"' in (top / name).read_text(), name
    assert "$SPK_PROC_ROOT" in (top / "cache.sh").read_text()
    own = (RIG / "watch.sh").read_text()
    assert 'bash "$SPP_TOOLS/setup.sh" || exit 7' in own
    assert 'bash "$SPP_TOOLS/../status.sh"' in own


def test_status_has_the_tabs_keys():
    """proc/status.sh says what the tab shows, under the Warden keys."""
    text = (RIG / "status.sh").read_text()
    for key in ("running", "title", "title_name", "build", "version", "attract", "pid",
                "rss_kb", "uptime_s", "display", "visible", "window", "switches",
                "switches_json"):
        assert 'echo "%s=' % key in text, key


RM_YAML = {
    "PRGame": {"machineType": "pdb", "numBalls": 5},
    "PRSwitches": {
        "coin1": {"number": "SD0", "label": "Left Coin Slot"},
        "sd1": {"number": "SD1", "label": "Unused"},
        "enter": {"number": "SD4", "label": "Service Enter"},
        "up": {"number": "SD5"}, "down": {"number": "SD6"}, "exit": {"number": "SD7"},
        "flipperLwR": {"number": "SD8"}, "antigravity": {"number": "SD9"},
        "flipperUpR": {"number": "SD10"}, "launchBall": {"number": "SD11"},
        "tilt": {"number": "SD13"}, "flipperLwL": {"number": "SD14"},
        "startButton": {"number": "SD15"},
        "subway": {"number": "SD16", "type": "NC", "label": "Subway"},
        "troughJam": {"number": "SD46", "type": "NC", "label": "Main Trough - Jam Opto"},
        "trough1": {"number": "SD47", "type": "NC"},
        "slingRight": {"number": "SD48", "label": "Right Sling"},
        "shooterLane": {"number": "SD51"},
        "trough2": {"number": "SD52"},
        "rightFlipperEOS": {"number": "SD57"},
        "SD80": {"number": "SD80"},
        "SD29": {"number": "SD29", "label": "TOP OF INNER ORBIT"},
    },
}


def _table():
    nums = {n: int(i["number"][2:]) for n, i in RM_YAML["PRSwitches"].items()}
    nc = {nums[n] for n, i in RM_YAML["PRSwitches"].items() if i.get("type") == "NC"}
    return sppswitches.table(RM_YAML, nums, nc, "Rick and Morty", "shooterLane")


def test_the_playfield_table_is_the_ap_windows():
    t = _table()
    by = {s["name"]: s for s in t["switches"]}
    # placeholders are not switches; a labelled SD<n> is
    assert "sd1" not in by and "SD80" not in by and by["SD29"]["label"] == "Top Of Inner Orbit"
    # appf finds the shooter, the trough and the coin door's buttons by name
    assert by["shooter"]["n"] == 51 and t["shooter"] == 51 and t["balls"] == 5
    assert [s["name"] for s in t["switches"] if s["group"] == "Trough"] == \
        ["troughJam", "trough1", "shooter", "trough2"]
    assert by["trough1"]["nc"] and by["trough1"]["type"] == "NC"
    for svc in ("exit", "down", "up", "enter"):
        assert by[svc]["group"] == "Cabinet"
    assert by["coin1"]["label"] == "Left Coin Slot" and by["flipperLwL"]["label"] == "Left Flipper"
    rows = {r["keys"]: r for r in t["rows"] if r["keys"]}
    assert rows["1"]["ns"] == [15] and rows["5"]["ns"] == [0] and rows["Space"]["ns"] == [11]
    assert rows["Down"]["ns"] == [9] and rows["T"]["ns"] == [13]
    assert rows["Left"]["ns"] == [14] and rows["Right"]["ns"] == [8, 10]
    assert rows["A"]["ns"] == [16] and rows["A"]["label"] == "Subway"
    # every switch reachable: the end-of-stroke one in the list, no key
    listed = {n for r in t["rows"] for n in r["ns"]}
    assert 57 in listed and 57 not in {n for r in rows.values() for n in r["ns"]}
    keys = {c: k for k in t["keymap"] for c in k["codes"]}
    assert keys["Escape"]["ns"] == [7] and keys["KeyF"]["action"] == "plunge"
    assert keys["F9"]["action"] == "pause"


def test_the_alice_cooper_launch_button_is_space():
    y = {"PRGame": {"numBalls": 4},
         "PRSwitches": {"launchBallButton": {"number": "SD11"}, "shooter": {"number": "SD50"}}}
    t = sppswitches.table(y, {"launchBallButton": 11, "shooter": 50}, set(), "AC", "shooter")
    assert [r["ns"] for r in t["rows"] if r["keys"] == "Space"] == [[11]]
    assert t["switches"][0]["label"] == "Launch Ball"


class FakeBoard:
    """prochw.py's ctl replies, for the adapter."""

    def __init__(self, shooter_made=False, in_play=0, trough=5):
        self.sent = []
        self.shooter_made, self.in_play, self.trough = shooter_made, in_play, trough

    def ask(self, line):
        import json
        self.sent.append(line)
        w = line.split()
        if w[0] == "state":
            return json.dumps({"host": True, "board": "P3-ROC", "balls": self.model()})
        if w[0] == "balls":
            return json.dumps(self.model())
        if w[0] == "switches":
            sw = {"trough%d" % i: {"number": n, "active": i <= self.trough}
                  for i, n in enumerate((47, 52, 53, 54, 55), 1)}
            sw["shooterLane"] = {"number": 51, "active": self.shooter_made}
            sw["startButton"] = {"number": 15, "active": False}
            return json.dumps(sw)
        if w[0] == "drain":
            if self.trough >= 5:
                return "err the trough is full"
            self.trough += 1
            self.in_play = max(0, self.in_play - 1)
            return "ok drained"
        if w[0] == "sw" and w[1] == "51":
            self.shooter_made = w[2] == "1"
        if w[0] == "plunge" and not self.shooter_made:
            return "err no ball in the shooter lane"
        return "ok"

    def model(self):
        return {"eject": 48, "shooter": 51, "launch": 49, "trough": self.trough,
                "in_play": self.in_play}


def test_the_adapter_answers_warden_state(tmp_path):
    ad = sppctl.Adapter(FakeBoard(shooter_made=True, in_play=1, trough=4), str(tmp_path))
    st = ad.command("state")
    assert st["up"] is True and st["paused"] is False and st["lights"] == {}
    assert st["switches"] == {"47": 1, "52": 1, "53": 1, "54": 1, "51": 1}
    assert st["balls"] == {"trough": 4, "shooter": 1, "in_play": 0}


def test_the_adapter_passes_switches_by_number(tmp_path):
    b = FakeBoard()
    ad = sppctl.Adapter(b, str(tmp_path))
    assert ad.command("sw 15 1") == {"ok": True}
    assert ad.command("tap 15") == {"ok": True}
    assert ad.command("plunge") == {"err": "no ball in the shooter lane"}
    assert ad.command("leds") == {}
    assert "err" in ad.command("fly 3")
    assert b.sent == ["sw 15 1", "tap 15 150", "plunge"]


def test_drain_takes_the_lanes_ball_when_none_is_in_play(tmp_path):
    b = FakeBoard(shooter_made=True, in_play=1, trough=4)
    ad = sppctl.Adapter(b, str(tmp_path))
    assert ad.command("drain") == {"ok": True}
    assert not b.shooter_made and b.trough == 5
    assert ad.command("drain") == {"err": "no ball in play"}


def test_reset_fills_the_trough(tmp_path):
    b = FakeBoard(shooter_made=True, in_play=3, trough=2)
    ad = sppctl.Adapter(b, str(tmp_path))
    assert ad.command("reset") == {"ok": True}
    assert b.trough == 5 and not b.shooter_made


def test_pause_without_a_game_says_so(tmp_path):
    ad = sppctl.Adapter(FakeBoard(), str(tmp_path))
    assert ad.command("pause 1") == {"paused": False}


def test_killgame_frees_a_paused_game():
    """A paused game stopped its runuser too (su's job control); Stop
    continues both, then sweeps what the game forked (SPK_MARK)."""
    text = (RIG / "killgame.sh").read_text()
    assert 'kill -CONT "$p"' in text and "spp_mark_pids" in text
    assert 'SPK_MARK="$SPP_RIG"' in (RIG / "netns.sh").read_text()


# --------------------------------------------------------------- PAD-405
# The Emulate tab's runs are visible and have sound, and every proof above
# was hidden and muted: on David's desktop Rick and Morty covered the whole
# screen and froze on its first attract page, played no sound, and a key in
# its window did nothing.

_FAKE_CONFIG = '''
values = {}

def load():
    global values           # what the machine's config.yaml says
    values = {"dmd_fullscreen": True, "dmd_window_border": False,
              "screen_position_x": 123, "keyboard_switch_map": {"1": "startButton"},
              "dmd_dots_w": 1280}
'''

_FAKE_LAUNCHER = '''
import json, os
import procgame.config
procgame.config.load()
with open(os.environ["OUT"], "w") as f:
    json.dump(procgame.config.values, f)
'''


def _run_spprun(tmp_path, visible):
    """spprun.py over a stand-in procgame whose load() reads the machine's
    config, as Rick and Morty's does, then a launcher that loads it."""
    import json
    import subprocess
    pg = tmp_path / "procgame"
    (pg / "game").mkdir(parents=True)
    (pg / "__init__.py").write_text("")
    (pg / "config.py").write_text(_FAKE_CONFIG)
    (pg / "game" / "__init__.py").write_text("")
    (pg / "game" / "mode.py").write_text(
        "class ModeQueue(object):\n    def add(self, m): pass\n    def remove(self, m): pass\n")
    (tmp_path / "__builtin__.py").write_text("from builtins import open\n")   # py2's name
    (tmp_path / "RMGame.py").write_text(_FAKE_LAUNCHER)
    out = tmp_path / "values.json"
    env = dict(os.environ, PYTHONPATH=str(tmp_path), OUT=str(out),
               SPP_VISIBLE="1" if visible else "0")
    env.pop("SPP_LOG", None)
    subprocess.run([sys.executable, str(RIG / "spprun.py"), "RMGame.py"], cwd=str(tmp_path),
                   env=env, check=True, timeout=60)
    return json.loads(out.read_text())


def test_the_game_draws_in_a_window_not_full_screen(tmp_path):
    values = _run_spprun(tmp_path, visible=True)
    assert values["dmd_fullscreen"] is False
    assert values["dmd_window_border"] is True          # on a desktop: movable
    assert values["screen_position_x"] == 0
    assert values["dmd_dots_w"] == 1280                 # the rest is the game's


def test_a_hidden_run_is_borderless_and_the_games_own_keys_are_off(tmp_path):
    values = _run_spprun(tmp_path, visible=False)
    assert values["dmd_fullscreen"] is False and values["dmd_window_border"] is False
    # its developers' map (A = the house, R = a flipper) would press a
    # second switch for every key the rig's listener also sends
    assert values["keyboard_switch_map"] == {}


def test_the_unity_screen_is_a_window_on_a_desktop():
    text = (RIG / "netns.sh").read_text()
    assert '-screen-fullscreen "$FULL"' in text
    assert '[ "${SPP_VISIBLE:-0}" = 1 ] && FULL=0' in text
    assert 'SPP_VISIBLE=$VISIBLE' in (RIG / "run_game.sh").read_text()


def test_sound_reaches_wslg_without_shared_memory():
    """The py27 env's libpulse wants WSLg's /dev/shm, which the distro cannot
    see, and then refused the whole connection: no sound on any run."""
    run = (RIG / "run_game.sh").read_text()
    assert "echo 'enable-shm = no' > \"$SPP_RIG/pulse-client.conf\"" in run
    assert "PULSE_CLIENTCONFIG=$SPP_RIG/pulse-client.conf" in run
    # netns.sh builds the game's environment from scratch (env -i)
    assert 'PULSE_CLIENTCONFIG="${PULSE_CLIENTCONFIG:-}"' in (RIG / "netns.sh").read_text()


def test_a_visible_run_listens_for_keys_in_the_game_window():
    run = (RIG / "run_game.sh").read_text()
    assert '"$SPP_TOOLS/sppctl.py" --serve "$SPP_RIG/ctl.sock"' in run
    assert '"$SPP_TOOLS/../../ap_emu/gamekeys.py"' in run
    assert '--sock "$SPP_RIG/ctl.sock"' in run and '--mark "SPK_MARK=$SPP_RIG"' in run
    assert '"${PAD_GAMEKEYS:-$VISIBLE}" = 1' in run
    kill = (RIG / "killgame.sh").read_text()
    assert '--serve $SPP_RIG/ctl.sock' in kill and 'gamekeys.py .*--sock $SPP_RIG/ctl.sock' in kill


@pytest.mark.skipif(sys.platform == "win32" or not hasattr(__import__("socket"), "AF_UNIX"),
                    reason="a unix socket and a POSIX game pid")
def test_serve_answers_the_key_listener_until_the_game_ends(tmp_path):
    import json
    import socket
    import subprocess
    import threading
    game = subprocess.Popen(["sleep", "60"])
    try:
        (tmp_path / "game.pid").write_text(str(game.pid))
        b = FakeBoard()
        sock = str(tmp_path / "ctl.sock")
        t = threading.Thread(target=sppctl.serve, args=(sppctl.Adapter(b, str(tmp_path)), sock),
                             daemon=True)
        t.start()
        for _ in range(50):
            if os.path.exists(sock):
                break
            threading.Event().wait(0.05)
        c = socket.socket(socket.AF_UNIX)
        c.connect(sock)
        f = c.makefile("r")
        c.sendall(b"sw 14 1\n")
        assert json.loads(f.readline()) == {"ok": True}
        c.sendall(b"pause 1\n")
        assert json.loads(f.readline()) == {"paused": True}
        c.sendall(b"pause 0\n")
        assert json.loads(f.readline()) == {"paused": False}
        c.close()
        assert b.sent == ["sw 14 1"]
    finally:
        game.kill()
        game.wait()
    t.join(5)
    assert not t.is_alive() and not os.path.exists(sock)


def test_the_table_maps_every_light_to_its_board_outputs():
    """Frank (PAD-405): the window showed the switches but no lights.  The
    yaml names each PD-LED light by board and outputs; one-output lights
    are white, and R&M's one G-twice typo reads the last as blue."""
    cfg = {"PRLEDs": {
        "garageLights1": {"number": "A0-R0-G1-B2"},
        "flasher": {"number": "A4-R81"},
        "typo": {"number": "A3-R10-G11-G12"},
        "nothing": {"number": ""},
        "lamp": {"number": "C-A4-B0-0:R-A4-B1-0"}}}
    assert sppswitches.leds(cfg) == {"garageLights1": [0, 0, 1, 2],
                                     "flasher": [4, 81, 81, 81],
                                     "typo": [3, 10, 11, 12]}
    t = sppswitches.table(cfg, {}, set(), "Rick and Morty", "shooterLane")
    assert t["leds"]["flasher"] == [4, 81, 81, 81]
    assert t["lights"] == []            # placed lights: there is no picture


class LedBoard(FakeBoard):
    def ask(self, line):
        import json
        if line.split()[0] == "leds":
            return json.dumps({"0:0": 255, "0:1": 128, "4:81": 40})
        return super().ask(line)


def test_state_carries_every_light_lit_or_dark(tmp_path):
    import json
    (tmp_path / "switches.json").write_text(json.dumps(
        {"leds": {"garageLights1": [0, 0, 1, 2], "flasher": [4, 81, 81, 81],
                  "giLeftOrbit1": [0, 12, 13, 14]}}))
    ad = sppctl.Adapter(LedBoard(), str(tmp_path))
    st = ad.command("state")
    # the window lays out its swatches from the first state, so the dark
    # one is there too
    assert st["lights"] == {"garageLights1": [255, 128, 0], "flasher": [40, 40, 40],
                            "giLeftOrbit1": [0, 0, 0]}
    assert ad.command("leds") == st["lights"]


def test_no_table_yet_means_no_lights_and_asks_again(tmp_path):
    import json
    ad = sppctl.Adapter(LedBoard(), str(tmp_path))
    assert ad.command("state")["lights"] == {}
    (tmp_path / "switches.json").write_text(json.dumps({"leds": {"flasher": [4, 81, 81, 81]}}))
    assert ad.command("state")["lights"] == {"flasher": [40, 40, 40]}
