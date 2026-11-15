"""PAD-1305: Barrels of Fun in the Visual Pinball kit.

  * bofhw.py's plugin hook: an observer next to the Emulator sees every
    switch, DL:/TL: line, LED frame and BICS command, sets switches and can
    turn PAD's ball model off - the supported way for another program to
    follow the boards, so a VPX link never replaces PAD's files again;
  * bofvpx.py, PAD's own plugin on that hook: the state block / switch
    bitmap the kit's PAD.Controller reads (bofbridge.py), with the rule
    plane, and the line stream (P H A R L M F W V) for other links;
  * the kit's `bof` platform: bofbridge restates bofvpx's layout (pinned
    together here), padlaunch finds a title's .fun and starts watch.sh.
"""

import importlib.util
import json
import pathlib
import socket
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RIG = ROOT / "tools" / "bof_emu"
VPX = ROOT / "tools" / "spike2_emu" / "vpx"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bofhw = _load("bofhw", RIG / "bofhw.py")


class _Log:
    def __init__(self):
        self.lines = []

    def write(self, s):
        self.lines.append(s)

    def flush(self):
        pass

    def text(self):
        return "".join(self.lines)


class _FakePort:
    def __init__(self, role):
        self.role, self.rx, self.tx = role, b"", b""


def profile(title):
    return json.loads((RIG / "profiles" / ("%s.json" % title)).read_text())


def emu(title="dune", root="/nonexistent"):
    prof = profile(title)
    e = bofhw.Emulator(str(root), prof, _Log())
    for spec in prof.get("ports", bofhw.DEFAULT_PORTS):
        e.ports[spec["role"]] = _FakePort(spec["role"])
    return e


class Recorder:
    """Every event, as (name, args)."""

    def __init__(self):
        self.events = []

    def __getattr__(self, name):
        if not name.startswith("on_"):
            raise AttributeError(name)

        def rec(*args):
            self.events.append((name, args))
        return rec

    def of(self, name):
        return [a for n, a in self.events if n == name]


# ----------------------------------------------------------------- the hook
def test_observer_sees_switches_drivers_leds_and_bics():
    e = emu("dune")
    r = Recorder()
    e.add_observer("rec", r)
    e.set_switch(8, 1, "mylink")
    assert r.of("on_switch") == [(8, 1, "mylink")]
    e.on_net_line("DL:0F,81,08,10,1E,FF,00,00,00")
    assert r.of("on_driver_config") == [(0x0F, ["81", "08", "10", "1E", "FF", "00", "00", "00"])]
    e.on_net_line("TL:27,01")
    assert r.of("on_driver") == [(0x27, ["01"])]
    assert ("on_net_line", ("TL:27,01",)) in r.events
    p = e.ports["exp"]
    p.rx = b"RD@48:" + bytes([2]) + bytes([5, 255, 0, 0, 6, 0, 0, 9])
    e.pump_exp(p)
    assert r.of("on_leds") == [("48", [(5, 255, 0, 0), (6, 0, 0, 9)], "RD")]
    e.on_exp_line("RA@48:102030")
    assert r.of("on_leds")[-1] == ("48", [(5, 16, 32, 48), (6, 16, 32, 48)], "RA")
    e.on_bics_line("MOVE:STEPPER WORM,UP")
    assert r.of("on_bics") == [("MOVE:STEPPER WORM,UP", "MOVE:STEPPER WORM,UP,ACK")]


def test_watchdog_is_not_an_event():
    e = emu("dune")
    r = Recorder()
    e.add_observer("rec", r)
    e.on_net_line("WD:1F4")
    assert r.events == []


def test_a_plugin_that_raises_never_stops_the_boards():
    e = emu("dune")

    class Bad:
        def on_switch(self, *a):
            raise RuntimeError("boom")

    r = Recorder()
    e.add_observer("bad", Bad())
    e.add_observer("rec", r)
    for i in range(5):
        e.set_switch(20, i % 2 == 0)
    assert len(r.of("on_switch")) == 5           # the next observer still hears
    assert e.logf.text().count("ERROR in plugin bad on_switch") == 3   # said, not spammed
    assert e.switches[20] == 1


def test_ball_model_off_leaves_the_balls_to_the_switches_owner():
    e = emu("dune")
    e.ball_model = False
    before = e.in_trough
    e.on_net_line("TL:%02X,01" % e.profile["trough_eject_driver"])
    assert e.in_trough == before and not e.timers   # no eject, no shooter lane ball
    assert e.plunge() is False and e.drain() is False
    assert e.state()["ball_model"] is False
    assert "ball model off" in e.logf.text()


def test_ctl_turns_the_ball_model_off_and_on():
    e = emu("dune")

    class Conn:
        def __init__(self):
            self.out = b""

        def sendall(self, b):
            self.out += b

    c = Conn()
    e.on_ctl(c, "balls off")
    assert c.out == b"ok\n" and e.ball_model is False
    e.on_ctl(c, "plunge")
    assert c.out.endswith(b"err no ball in the shooter lane\n")
    e.on_ctl(c, "balls on")
    assert e.ball_model is True


def test_plugins_load_from_a_file_once_and_a_broken_one_is_logged(tmp_path):
    good = tmp_path / "mylink.py"
    good.write_text("class O:\n    def __init__(self, emu):\n        self.emu = emu\n"
                    "        emu.ball_model = False\n"
                    "def attach(emu):\n    return O(emu)\n")
    bad = tmp_path / "broken.py"
    bad.write_text("raise ImportError('nope')\n")
    e = emu("dune")
    bofhw.load_plugins(e, [str(good), str(good), str(bad), ""])
    assert [n for n, _ in e.observers] == ["mylink"]
    assert e.ball_model is False
    assert "ERROR plugin %s not loaded" % bad in e.logf.text()
    assert e.state()["plugins"] == ["mylink"]


def test_plugin_fds_are_watched_by_the_loop():
    e = emu("dune")
    a, b = socket.socketpair()

    class Srv:
        got = []

        def fds(self):
            return [a]

        def on_readable(self, fd):
            self.got.append(fd.recv(10))

    e.add_observer("srv", Srv())
    assert e.plugin_fds() == {a: ("srv", e.observers[0][1])}
    a.close()
    b.close()


def test_run_game_loads_pads_bridge_the_env_and_the_dropin_folder():
    src = (RIG / "run_game.sh").read_text()
    assert '--plugin "$BOF_TOOLS/bofvpx.py"' in src
    assert "BOFHW_PLUGINS" in src and '"$BOF_ROOT"/plugins/*.py' in src
    assert '"${PLUGINS[@]}"' in src
    assert "RIGBOARD_ROOT=$BOF_RIG/hw rigboard_post bof" in src


def test_bofhw_doc_names_every_observer_event():
    doc = bofhw.__doc__
    for ev in ("on_switch", "on_driver_config", "on_driver", "on_leds", "on_exp_line",
               "on_bics", "on_net_line", "on_audio", "tick", "fds", "on_readable", "on_stop"):
        assert ev in doc
    src = (RIG / "bofhw.py").read_text()
    for ev in ("on_switch", "on_driver_config", "on_driver", "on_leds", "on_exp_line",
               "on_bics", "on_net_line", "on_audio", "tick", "on_stop"):
        assert 'notify("%s"' % ev in src, ev


# ------------------------------------------------------------ bofvpx.py
sys.path.insert(0, str(RIG))
bofvpx = _load("bofvpx", RIG / "bofvpx.py")


@pytest.fixture
def vpx(tmp_path, monkeypatch):
    """A Dune Emulator with PAD's bridge attached, no TCP port, and a
    socketpair standing in for a connected link: (emu, bridge, read)."""
    monkeypatch.setenv("BOF_VPX_PORT", "0")
    e = emu("dune", tmp_path)
    br = bofvpx.attach(e)
    e.add_observer("bofvpx", br)
    a, b = socket.socketpair()
    br.clients[a] = {"buf": b"", "balls_off": False}

    def read():
        b.setblocking(False)
        got = []
        try:
            while True:
                chunk = b.recv(65536)
                if not chunk:
                    break
                got.append(chunk)
        except (BlockingIOError, OSError):
            pass
        return b"".join(got).decode().splitlines()
    yield e, br, read
    a.close()
    b.close()


def run_timers(e):
    import heapq
    while e.timers:
        _, _, fn, args = heapq.heappop(e.timers)
        fn(*args)


COILS = 16 + 1024 * 4
RULES = 16 + 1024 * 5


def test_a_flipper_rule_is_armed_by_tl0_and_disarmed_by_tl02(vpx):
    e, br, read = vpx
    # Dune FLIPPER_MAIN_LL (coils.gd): DL:16,81,<button 08>,56,<EOS>,1E,92,32,0A
    e.on_net_line("DL:16,81,08,56,0B,1E,92,32,0A")
    e.on_net_line("DL:17,81,08,5d,5,FF,FF")
    assert read() == []                          # configured, not armed (trigger 81)
    e.on_net_line("TL:16,0")
    e.on_net_line("TL:17,0")
    assert read() == ["A 22 8 1 56", "A 23 8 1 5d"]
    blk = br.block(0.0)
    assert blk[RULES + 0x16] == 8 + 1 and blk[RULES + 0x17] == 8 + 1
    assert blk[COILS + 0x16] == 0                # button up: coil off
    e.set_switch(8, 1, "vpx")
    blk = br.block(0.0)
    assert blk[COILS + 0x16] == 1 and blk[COILS + 0x17] == 1
    assert read() == []                          # the rule's own firing is the table's
    e.on_net_line("TL:16,02")
    assert read() == ["A 22 8 0 56"]
    assert br.block(0.0)[RULES + 0x16] == 0


def test_a_placebo_rule_is_not_a_rule_and_trigger_01_is_live(vpx):
    e, br, read = vpx
    e.on_net_line("DL:28,81,13,10,28,FF,00,00,00")   # flipper test mode: PLACEBO
    e.on_net_line("TL:28,0")
    assert read() == []
    e.on_net_line("DL:15,01,3A,30,02,0F,0,00,32")    # pain box kicker, active
    assert read() == ["A 21 58 1 30"]
    e.on_net_line("DL:15,81,3A,30,02,0F,0,00,32")    # and back
    assert read() == ["A 21 58 0 30"]


def test_pulses_and_holds_stream_and_light_the_block(vpx):
    e, br, read = vpx
    e.on_net_line("DL:07,81,13,10,0F,FF,0,00,20")    # KNOCKER, 15 ms
    e.on_net_line("TL:7,01")
    e.on_net_line("DL:02,81,13,18,0,AA,AA,0")       # SHAKER
    e.on_net_line("TL:2,03")
    assert br.block(0.0)[COILS + 2] == 1
    e.on_net_line("TL:2,02")
    assert read() == ["P 7 15", "H 2 1", "H 2 0"]
    import time as _t
    assert br.block(_t.monotonic())[COILS + 7] == 1      # the pulse reads on a while


def test_leds_stream_by_name_aliases_expand_and_fill_their_slots(vpx):
    e, br, read = vpx
    e.on_exp_line("LM@840:88,10,11")                   # an alias on 84, breakout 0
    p = e.ports["exp"]
    p.rx = b"RD@b4:" + bytes([1, 0, 255, 0, 0]) + b"RD@840:" + bytes([1, 0x88, 0, 0, 200])
    e.pump_exp(p)
    lines = read()
    assert lines[0] == "L DOT_ORBIT_LEFT8 ff0000"
    assert lines[1:] == ["L %s 0000c8" % br.led_name("84", 0x10),
                         "L %s 0000c8" % br.led_name("84", 0x11)]
    assert br.led_name("84", 0x10) != "84:16"         # a named LED
    assert ("84", 0x88) not in e.leds and e.leds[("84", 0x10)] == (0, 0, 200)
    blk = br.block(0.0)
    o = 16 + 1024
    s = br.boards.index("84") * 128 + 0x10
    assert blk[o + s * 3:o + s * 3 + 3] == bytes((0, 0, 200))
    s = br.boards.index("b4") * 128
    assert blk[o + s * 3:o + s * 3 + 3] == bytes((255, 0, 0))
    p.rx = b"RD@b4:" + bytes([1, 0, 255, 0, 0])
    e.pump_exp(p)
    assert read() == []                                # unchanged: not said again


def test_bics_magnet_rule_magnets_flashers_and_steppers(vpx):
    e, br, read = vpx
    e.on_bics_line("SET:MAGNET B,FIRE,TIME,700")
    e.on_bics_line("SET:MAGNET B,HOLD,TIME,300")
    e.on_bics_line("ARM:MAGNET A,2,R,0,-1")           # bics.gd arm_magnet: worm, switch 2
    e.on_bics_line("FIRE:MAGNET B")
    e.on_bics_line("SET:FLASHER 2,250,12.0,50.0")
    e.on_bics_line("FIRE:FLASHER 2")
    e.on_bics_line("FIRE:FLASHER 3")                  # FLASHER_FAKE: the game's watchdog
    e.on_bics_line("MOVE:STEPPER WORM,UP")
    assert read() == ["R MAGNET_WORM 51 1 R 0 -1", "M MAGNET_ORBIT_LEFT 1",
                      "F FLASHER_ORBIT 250", "W WORM 87.0"]
    when = e.timers[0][0] - time_now()
    assert 0.9 < when <= 1.0                          # FIRE 700 + HOLD 300 ms
    run_timers(e)
    assert read() == ["M MAGNET_ORBIT_LEFT 0"]
    e.set_switch(51, 1, "vpx")                        # the rule fires on the board: not sent
    assert read() == []
    e.on_bics_line("ARM:MAGNET A,2,R,0,0")
    assert read() == ["R MAGNET_WORM 51 0 R 0 0"]


def time_now():
    import time as _t
    return _t.monotonic()


def test_a_counted_magnet_rule_runs_out(vpx):
    e, br, read = vpx
    e.on_bics_line("ARM:MAGNET A,2,R,0,1")
    e.set_switch(51, 1, "vpx")
    assert read() == ["R MAGNET_WORM 51 1 R 0 1", "R MAGNET_WORM 51 0 R 0 0"]


def test_servos_stream_by_name(vpx):
    e, br, read = vpx
    e.on_exp_line("mp@b4:1,5dc,0bb8")
    e.on_exp_line("mp@b4:1,5dc,0bb8")
    assert read() == ["V HARVESTER 1500"]


def test_winchester_names_its_coils_and_its_hall_stepper(tmp_path, monkeypatch):
    monkeypatch.setenv("BOF_VPX_PORT", "0")
    e = emu("winchester", tmp_path)
    br = bofvpx.attach(e)
    e.add_observer("bofvpx", br)
    seen = []
    br.emit = seen.append
    e.on_bics_line("ARM:COIL 1,0,R,0,-1")              # mechs.gd: MAGNET_STAIRS on switch 0
    e.on_bics_line("MOVE:STEPPER 45")                  # set_hall_angle: no motor named
    assert seen == ["R MAGNET_STAIRS 98 1 R 0 -1", "W HALL 45"]


def test_the_stream_sets_switches_and_hands_the_balls_over(vpx):
    e, br, read = vpx
    c = next(iter(br.clients))
    br.on_stream_line(c, "S 8 1")
    assert e.switches[8] == 1
    br.on_stream_line(c, "B 0")
    assert e.ball_model is False
    br.on_stream_line(c, "bogus")
    assert read()[-1] == "E unknown: bogus"
    br.drop(c)                                         # the link went: PAD has the balls again
    assert e.ball_model is True


def test_the_stream_greets_with_the_state_so_far(vpx):
    e, br, read = vpx
    e.on_net_line("DL:16,81,08,56,0B,1E,92,32,0A")
    e.on_net_line("TL:16,0")
    snap = br.snapshot()
    assert snap[0] == "# PAD bofvpx 1 Dune slot 0"
    assert "A 22 8 1 56" in snap and "W WORM 5.0" in snap


def test_attached_the_table_owns_the_balls_and_its_switches(vpx, tmp_path):
    e, br, read = vpx
    bb = pytest.importorskip("bofbridge")
    br.tick(0.0)
    assert bb.is_up((tmp_path / bofvpx.STATE_FILE).read_bytes())
    assert e.ball_model is True and br.poll_s == bofvpx.IDLE_POLL_S
    (tmp_path / bofvpx.ATTACHED_FILE).write_text("PAD.Controller\n")
    # the table: two balls in the trough (72, 73), the left flipper button
    closed = {bb.switch_slot(72), bb.switch_slot(73), bb.switch_slot(8)}
    (tmp_path / bofvpx.INPUT_FILE).write_bytes(bb.pack_input(closed, 1))
    br.tick(1.0)
    assert e.ball_model is False and br.poll_s == bofvpx.POLL_S
    on = {n for n, v in e.switches.items() if v}
    assert {72, 73, 8} <= on and not on & {74, 75, 76, 77}
    sw, lamps, coils, seq = bb.unpack((tmp_path / bofvpx.STATE_FILE).read_bytes())
    assert sw[bb.switch_slot(8)] == 1 and sw[bb.switch_slot(74)] == 0
    (tmp_path / bofvpx.ATTACHED_FILE).unlink()
    br.tick(2.0)
    assert e.ball_model is True


# ------------------------------------------------------ the kit's side
for _p in (ROOT / "tools" / "spike2_emu", VPX):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_the_bridge_restates_the_plugins_layout(monkeypatch):
    bb = pytest.importorskip("bofbridge")
    for k in ("STATE_MAGIC", "INPUT_MAGIC", "STATE_FILE", "INPUT_FILE", "ATTACHED_FILE",
              "SWITCH_BASE", "LEDS_PER_BOARD"):
        assert getattr(bb, k) == getattr(bofvpx, k), k
    assert bb.N_SLOTS == bofvpx.SLOTS
    monkeypatch.setenv("BOF_VPX_PORT", "0")
    blk = bofvpx.Bridge(emu("dune")).block(0.0)
    assert len(blk) == bb.STATE_SIZE and bb.is_up(blk) and bb.rules(blk) == {}


def test_the_run_is_found_on_the_board_by_its_title_or_slot(tmp_path, monkeypatch):
    bb = pytest.importorskip("bofbridge")
    monkeypatch.setattr(bb, "BOARD", str(tmp_path))
    rec = {"emu": "bof", "slot": 6, "game": "dune", "title": "", "label": "PAD-VPX",
           "distro": "PAD-Runtime", "pid": 1, "root": "/var/tmp/pad_bof/rig6/hw"}
    (tmp_path / "bof-6.run").write_text(json.dumps(rec), encoding="utf-8")
    (tmp_path / "spooky-7.run").write_text(json.dumps({"emu": "spooky", "game": "dune"}),
                                           encoding="utf-8")
    assert bb.board_record("dune")["slot"] == 6
    assert bb.board_record("winchester") is None and bb.board_record(slot=7) is None
    rig = bb.BofRig("dune")
    assert rig.slot == 6 and rig.led_path().endswith("vpxhw.state") and rig.switch_ids() == {}
    if sys.platform == "win32":
        assert rig.dump == r"\\wsl.localhost\PAD-Runtime\var\tmp\pad_bof\rig6\hw"


def test_the_controller_fires_a_flipper_only_while_its_rule_is_armed(tmp_path, monkeypatch):
    pc = pytest.importorskip("padcontroller")
    bb = pytest.importorskip("bofbridge")
    maps = tmp_path / "maps"
    maps.mkdir()
    (maps / "dune.vpxmap.json").write_text(json.dumps({
        "platform": "bof", "title": "dune",
        "cabinet": {"left_flipper": 1000 + bb.switch_slot(8)},
        "solenoids": {"48": {"coil": [0, 0x16], "name": "FLIPPER_MAIN_LL"}},
        "game_on": {"number": 40, "coils": [[0, 0x16]]},
        "lamps": {"L1": {"leds": [[2, 0]], "rgb": True}}}), encoding="utf-8")
    monkeypatch.setattr(pc, "USER_MAPS", str(maps))
    b = pc.Bridge()
    b.set_game("dune")
    assert b.rigmod is bb and b.slots and b.max_id == 1024
    monkeypatch.setenv("BOF_VPX_PORT", "0")
    e = emu("dune", tmp_path)
    br = bofvpx.Bridge(e)
    e.add_observer("bofvpx", br)
    e.on_net_line("DL:16,81,08,56,0B,1E,92,32,0A")
    p = e.ports["exp"]
    p.rx = b"RD@b4:" + bytes([1, 0, 10, 20, 30])       # b4 is led_boards[1]: slot 128 = [2, 0]
    e.pump_exp(p)
    monkeypatch.setattr(pc, "read_block", lambda path, n: br.block(0.0))

    class R:
        def led_path(self):
            return "x"

        def sw_path(self):
            return str(tmp_path / "in")
    b.rig = R()
    b.pipe = bb.BofPipe(R())
    b._poll_once()
    assert b._rule_coils == {} and b.sol_state.get(40) == 0      # not armed: flippers off
    assert b.lamp_state[pc.lamp_number(2, 0)] == pc.rgb_value(10, 20, 30)
    e.on_net_line("TL:16,0")
    b._poll_once()
    assert b.sol_state.get(40) == 1
    b.set_switch(1000 + bb.switch_slot(8), 1)                     # the table's button
    assert b.sol_state.get(48) == 1                               # fired at once, no poll
    b.set_switch(1000 + bb.switch_slot(8), 0)
    assert b.sol_state.get(48) == 0
    e.on_net_line("TL:16,02")
    b._poll_once()
    b.set_switch(1000 + bb.switch_slot(8), 1)
    assert not b.sol_state.get(48) and b.sol_state.get(40) == 0


def test_a_bof_title_boots_its_fun_from_the_makers_folder(tmp_path, monkeypatch):
    pl = pytest.importorskip("padlaunch")
    lib2 = tmp_path / "Stern" / "spike2"
    bof = tmp_path / "BoF"
    lib2.mkdir(parents=True)
    bof.mkdir()
    for n in ("dune.fun", "winchester.fun", "lab.fun", "bon-jovi_2026.10.01.fun"):
        (bof / n).write_bytes(b"x")
    monkeypatch.delenv("PAD_VPX_LIBRARY", raising=False)
    monkeypatch.delenv("PAD_VPX_CARD", raising=False)
    monkeypatch.setattr(pl, "kit_load", lambda: {"library": str(lib2)})
    assert str(bof) in pl.libraries("bof")
    assert pl.card_for("dune", "bof") == str(bof / "dune.fun")
    assert pl.card_for("labyrinth", "bof") == str(bof / "lab.fun")
    assert pl.card_for("winchester", "bof") == str(bof / "winchester.fun")
    assert pl.PLATFORM_NAMES["bof"] == "Barrels of Fun"
    assert isinstance(pl.launch_for("bof", "dune", "d.fun"), pl.BofLaunch)


def test_the_bof_launch_takes_a_free_slot_and_the_apps_keys(tmp_path, monkeypatch):
    pl = pytest.importorskip("padlaunch")
    bb = pytest.importorskip("bofbridge")
    monkeypatch.setattr(bb, "BOARD", str(tmp_path))
    (tmp_path / "bof-7.run").write_text(json.dumps({"emu": "bof", "slot": 7, "game": "winchester",
                                                    "label": "PAD-VPX"}), encoding="utf-8")
    launch = pl.BofLaunch("dune", r"D:\Pinball\images\BoF\dune.fun", dist="PAD-Runtime")
    assert launch.take_slot() == 6 and launch.other_run() is None
    assert launch.rig_wsl.endswith("/bof_emu")
    env, _ = launch.env()
    assert "PAD_SLOT=6" in env and "BOF_TITLE=dune" in env
    keys = [x for x in env if x.startswith("BOF_KEYS=")]
    assert keys and "dune:" in keys[0] and "winchester:" in keys[0] and "bonjovi" not in keys[0]
    (tmp_path / "bof-0.run").write_text(json.dumps({"emu": "bof", "slot": 0, "game": "dune",
                                                    "label": "PAD-319"}), encoding="utf-8")
    assert launch.other_run()["slot"] == 0                # the app's own Dune is up


# ------------------------------------------------- the profiles' names
gen = _load("gen_profile", RIG / "gen_profile.py")


def test_names_come_from_the_titles_own_tables(tmp_path):
    a = tmp_path / "autoloads"
    a.mkdir()
    (a / "leds.gd").write_text(
        'func set_up_leds() -> void :\n'
        '\titems[DOT_A] = {"display_name": "A", \n'
        '\t\t"board": "b4", "hex": "00", "dec": 0, "tags": ["playfield"], "commands": {}}\n'
        '\titems[GI_X] = {"display_name": "X", "board": "841", "hex": "05", "dec": 5}\n'
        '\titems[ALIAS_GI] = {"display_name": "G", "board": "840", "hex": "88", "dec": 136}\n'
        '\titems[PLACEBO] = {"display_name": "P", "board": "861", "hex": "40", "dec": 65}\n')
    (a / "servos.gd").write_text('\titems[PAINBOX] = {"hex": "0", "dec": 0, \n\t"board": "b4", }\n')
    (a / "coils.gd").write_text(
        '\titems[MAGNET_WORM] = {"display_name": "W", \n\t\t"driver_id": "A", \n'
        '\t\t"param_1": 500, \n\t\t"tags": ["bics", "bics_magnet", "burn_in"]}\n'
        '\titems[FLASHER_ORBIT] = {"display_name": "F", \n\t\t"driver_id": "left_orbit", \n'
        '\t\t"param_1": 2, \n\t\t"tags": ["bics", "bics_flasher"]}\n')
    n = gen.vpx_names(str(tmp_path))
    assert n["leds"] == {"b4:0": "DOT_A", "841:5": "GI_X"}
    assert n["led_boards"] == ["b4", "841"]
    assert n["servos"] == {"b4:0": "PAINBOX"}
    assert n["bics_outputs"] == {"A": "MAGNET_WORM"} and n["bics_flashers"] == {"2": "FLASHER_ORBIT"}


@pytest.mark.parametrize("title,count", [("dune", 465), ("winchester", 459), ("labyrinth", 210)])
def test_every_profile_names_its_leds_within_the_block(title, count):
    p = profile(title)
    assert len(p["leds"]) == count
    assert len(p["led_boards"]) * bofvpx.LEDS_PER_BOARD <= bofvpx.SLOTS
    for key in p["leds"]:
        board, idx = key.split(":")
        assert board in p["led_boards"] and int(idx) < bofvpx.LEDS_PER_BOARD


def test_winchester_motorless_stepper_moves_its_one_motor():
    e = emu("winchester")
    e.on_bics_line("MOVE:STEPPER 45")
    assert e.bics["pos"]["HALL"] == "45"


@pytest.mark.parametrize("bridge,pipe", [("spkbridge", "SpookyPipe"), ("bofbridge", "BofPipe")])
def test_switches_8_to_11_reach_the_board_not_a_spike1_cpu(tmp_path, bridge, pipe):
    # Alice Cooper's right flipper is 1010, its upper right 1009, launch 1011
    mod = pytest.importorskip(bridge)

    class R:
        def sw_path(self):
            return str(tmp_path / mod.INPUT_FILE)
    p = getattr(mod, pipe)(R())
    for sid in (8, 9, 10, 11):
        assert p.set(sid, 1)
    bits = (tmp_path / mod.INPUT_FILE).read_bytes()[12:]
    assert all(bits[s >> 3] >> (s & 7) & 1 for s in (8, 9, 10, 11))
