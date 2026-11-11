"""The Spike 1 rig behind PAD.Controller (PAD-943): tools/spike2_emu/vpx/s1bridge.

What is worth failing on, none of it needing a run:
  * THE TWO FILE LAYOUTS ARE THE RIG'S. s1bridge restates spike1_emulate's
    StateBlock / SwitchInput (so the controller never imports the app); a
    drift between them reads lamps off by a node or writes a bitmap the
    responder refuses.
  * THE NUMBERING: a Spike 1 switch is 1000 + node*64 + index, a coil the
    same, a lamp 1000 + node*100 + index; the got_le map says so.
  * THE BOARD RECORD: a Spike 1 run is taken only when it is the title's
    (case apart: the rig posts GOT_LE, the map says got_le), its work dir
    from the record's `root`.
  * THE PIPE: every change rewrites the whole bitmap; close lets go.
  * THE LAUNCH: a Spike 1 title's card is its .iso in a spike1 library beside
    the Spike 2 one; a run of another title on the one rig is refused.
"""
import json
import os
import struct
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VPX = os.path.join(ROOT, "tools", "spike2_emu", "vpx")
for p in (os.path.join(ROOT, "tools", "spike2_emu"), VPX):
    if p not in sys.path:
        sys.path.insert(0, p)
pytestmark = pytest.mark.skipif(not os.path.isdir(VPX), reason="rig not present")


@pytest.fixture(scope="module")
def s1():
    return pytest.importorskip("s1bridge")


def test_layouts_match_the_apps_state_model(s1):
    m = pytest.importorskip("pinball_decryptor.plugins.stern.spike1_emulate")
    assert (s1.MAX_NODES, s1.MAX_INDEX, s1.N_SLOTS) == (m.MAX_NODES, m.MAX_INDEX, m.N_SLOTS)
    assert s1.STATE_SIZE == m.StateBlock.SIZE
    assert s1.INPUT_SIZE == m.SwitchInput.SIZE
    st = m.HardwareState()
    st.set_switch(8, 2, True)
    st.set_lamp(9, 5, 0x58)
    st.set_coil(9, 2, True)
    data = m.StateBlock.pack(st, seq=7)
    assert s1.is_up(data)
    sw, lamps, coils, seq = s1.unpack(data)
    assert seq == 7 and sw[s1.slot(8, 2)] == 1 and coils[s1.slot(9, 2)] == 1
    assert s1.lamp_level(lamps, 9, 5) == 0x58 and s1.lamp_rgb(lamps, 9, 5) == (0x58, 0x58, 0x58)
    assert s1.lamp_level(lamps, 9, 6) == 0
    closed, seq2 = m.SwitchInput.unpack(s1.pack_input({75, 521}, 3))
    assert closed == {75, 521} and seq2 == 3


def test_not_a_state_block(s1):
    assert not s1.is_up(None) and not s1.is_up(b"\0" * 10)
    assert not s1.is_up(struct.pack("<4I", 0x12345678, 1, 0, 0) + bytes(s1.STATE_SIZE))
    assert s1.unpack(b"") is None


def test_numbering(s1):
    assert s1.slot(1, 11) == 75 and s1.sol_number(9, 2) == 1578 and s1.sol_number(8, 7) == 1519


def test_the_got_le_map_numbers_the_rigs_switches_and_the_elfs_coils(s1):
    m = json.load(open(os.path.join(VPX, "got_le.shadow.json"), encoding="utf-8"))
    names = json.load(open(os.path.join(ROOT, "tools", "spike1_emu", "switchmaps", "GOT_LE.json"), encoding="utf-8"))
    assert m["platform"] == "spike1" and m["listed"] is True and m["detect"]   # VPW's table is fitted
    by_name = {v: k for k, v in names.items() if not k.startswith("_")}
    for key, want in (("start", "START BUTTON"), ("left_flipper", "L. FLIPPER BUTTON"),
                      ("right_flipper", "R. FLIPPER BUTTON"), ("coin", "LEFT COIN SLOT")):
        node, idx = (int(x) for x in by_name[want].split(","))
        assert m["cabinet"][key] == 1000 + s1.slot(node, idx), key
    # the kit's trough: TROUGH #1 (R), nearest the up-kicker, first; the jam opto last
    trough = [s1.slot(*(int(x) for x in by_name["TROUGH #%d%s" % (n, s)].split(",")))
              for n, s in ((1, " (R)"), (2, ""), (3, ""), (4, " (L)"), (5, " (L)"), (6, " (L)"))]
    assert m["trough"]["switches"] == trough + [s1.slot(*(int(x) for x in by_name["TROUGH JAM"].split(",")))]
    assert m["solenoids"]["1"]["coil"] == [9, 2] and "TROUGH" in m["solenoids"]["1"]["name"]
    assert [tuple(c) for c in names["_trough_coils"]][:2] == [(1, 1), (1, 2)]   # the sweep's, kept as they were
    pc = pytest.importorskip("padcontroller")
    vm = pc.VpxMap("got_le")
    assert vm.platform == "spike1" and vm.game_on == (40, [(8, 7)])
    assert vm.solenoids[1] == (9, 2)
    # the table's li11 is LED 11 of the game's LED table: an RGB insert on node 8 at 20..22
    assert vm.lamp_groups[pc.lamp_number(8, 20)] == [(8, 20), (8, 21), (8, 22)]
    assert pc.lamp_number(8, 20) in vm.rgb_groups and pc.lamp_number(12, 2) in vm.lamp_groups   # fl235, a flasher on node 12


def test_board_record_is_the_titles_case_apart(s1, tmp_path):
    rec = {"emu": "spike1", "slot": 0, "game": "GOT_LE", "distro": "PAD-Runtime", "pid": 1,
           "root": "/mnt/wsl/paddata/spike1"}
    (tmp_path / "spike1-0.run").write_text(json.dumps(rec), encoding="utf-8")
    assert s1.board_record("got_le", board=str(tmp_path)) == rec
    assert s1.board_record("kiss_le", board=str(tmp_path)) is None
    assert s1.board_record(None, board=str(tmp_path)) == rec
    (tmp_path / "spike1-0.run").write_text(json.dumps(dict(rec, emu="spike2")), encoding="utf-8")
    assert s1.board_record("got_le", board=str(tmp_path)) is None


def test_rig_reads_its_files_from_the_records_work_dir(s1, monkeypatch):
    monkeypatch.setattr(s1.sys, "platform", "win32")
    rig = s1.Spike1Rig("got_le", record={"emu": "spike1", "game": "GOT_LE", "distro": "PAD-Runtime",
                                         "root": "/mnt/wsl/paddata/spike1"})
    assert rig.dump == r"\\wsl.localhost\PAD-Runtime\mnt\wsl\paddata\spike1"
    assert rig.led_path().endswith("s1hw.state") and rig.sw_path().endswith("s1sw.input")
    assert rig.ballfeed_off_path().endswith("s1ball.off")
    assert rig.how == "rig board spike1-0 (GOT_LE)"


def test_switch_ids_are_the_names_tables_slots(s1, tmp_path, monkeypatch):
    names = {"1,11": "START BUTTON", "8,2": "L. FLIPPER BUTTON", "_trough_coils": [[1, 1]]}
    (tmp_path / "s1switches.json").write_text(json.dumps(names), encoding="utf-8")
    rig = s1.Spike1Rig.__new__(s1.Spike1Rig)
    rig.dump = str(tmp_path)
    service = {(0, b): b for b in (8, 9, 10, 11)}
    assert rig.switch_ids() == {(1, 11): 75, (8, 2): 514, **service}
    rig.dump = str(tmp_path / "nowhere")
    assert rig.switch_ids() == service


@pytest.mark.parametrize("bit", [8, 9, 10, 11])
def test_cpu_service_inputs_are_active_low_and_not_node_switches(s1, tmp_path, bit):
    from types import SimpleNamespace
    cpu = tmp_path / "cpu.input"
    cpu.write_bytes(b"\xaa\xff\xfe")   # unrelated DIP / trough / door bits
    rig = SimpleNamespace(cpu_switch_path=lambda: str(cpu), sw_path=lambda: str(tmp_path / "sw.input"))
    pipe = s1.Spike1Pipe(rig)
    assert pipe.set(bit, 1)
    expected = bytearray(b"\xaa\xff\xfe")
    expected[1] &= ~(1 << (bit - 8))
    assert cpu.read_bytes() == expected and not (tmp_path / "sw.input").exists()
    assert pipe.set(75, 1)  # a later playfield write must not leak the CPU bit
    bits = (tmp_path / "sw.input").read_bytes()[s1.INPUT_HEADER.size:]
    assert bits[75 >> 3] & (1 << (75 & 7)) and not bits[1]
    assert pipe.set(bit, 0) and cpu.read_bytes() == b"\xaa\xff\xfe"
    assert pipe.set(bit, 1)
    pipe.close()
    assert cpu.read_bytes() == b"\xaa\xff\xfe"
    assert not any((tmp_path / "sw.input").read_bytes()[s1.INPUT_HEADER.size:])


def test_cpu_service_write_replaces_the_file_whole(s1, tmp_path, monkeypatch):
    """qemu pads a short read with zeros (= every active-low input pressed),
    so the file is swapped in whole, never truncated and rewritten."""
    from types import SimpleNamespace
    cpu = tmp_path / "cpu.input"
    cpu.write_bytes(b"\xff\xff\xfe")
    replaced = []
    real = s1.os.replace
    monkeypatch.setattr(s1.os, "replace", lambda a, b: (replaced.append((a, b)), real(a, b)))
    pipe = s1.Spike1Pipe(SimpleNamespace(cpu_switch_path=lambda: str(cpu)))
    assert pipe.set(9, 1)
    assert replaced == [(str(cpu) + ".tmp", str(cpu))]
    assert cpu.read_bytes() == b"\xff\xfd\xfe" and not (tmp_path / "cpu.input.tmp").exists()


def test_cpu_service_write_can_be_retried_after_resolution_failure(s1, tmp_path, monkeypatch):
    from types import SimpleNamespace
    attempts = []
    cpu = tmp_path / "cpu.input"
    def path():
        attempts.append(1)
        if len(attempts) == 1:
            raise s1.subprocess.TimeoutExpired("readlink", 10)
        return str(cpu)
    monkeypatch.setattr(s1, "_log", lambda s: None)
    pipe = s1.Spike1Pipe(SimpleNamespace(cpu_switch_path=path))
    assert not pipe.set(11, 1)
    assert pipe.set(11, 1) and len(attempts) == 2
    assert cpu.read_bytes() == b"\xff\xf7\xfe"


def test_cpu_input_path_resolves_the_wsl_symlink_once(s1, monkeypatch):
    from types import SimpleNamespace
    rig = s1.Spike1Rig.__new__(s1.Spike1Rig)
    rig.root, rig.distro = "/pad work/spike1", "TestRuntime"
    calls = []
    def run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(stdout="/pad work/cache/GB/rootfs\n", check_returncode=lambda: None)
    monkeypatch.setattr(s1.sys, "platform", "win32")
    monkeypatch.setattr(s1.subprocess, "run", run)
    want = os.path.join(r"\\wsl.localhost\TestRuntime\pad work\cache\GB\rootfs", "data", "s1cpusw.input")
    assert rig.cpu_switch_path() == rig.cpu_switch_path() == want
    assert calls == [["wsl.exe", "-d", "TestRuntime", "-u", "root", "--", "readlink", "-f", "/pad work/spike1/rootfs"]]


def test_pipe_rewrites_the_bitmap_and_lets_go_on_close(s1, tmp_path):
    rig = s1.Spike1Rig.__new__(s1.Spike1Rig)
    rig.dump = str(tmp_path)
    pipe = s1.Spike1Pipe(rig)
    assert pipe.set(75, 1) and pipe.set(521, 1)
    assert pipe.set(75, 1) is True                  # unchanged: nothing written again
    buf = (tmp_path / "s1sw.input").read_bytes()
    assert len(buf) == s1.INPUT_SIZE and struct.unpack_from("<I", buf, 0)[0] == s1.INPUT_MAGIC
    bits = buf[s1.INPUT_HEADER.size:]
    assert bits[75 >> 3] & (1 << (75 & 7)) and bits[521 >> 3] & (1 << (521 & 7))
    pipe.set(75, 0)
    bits = (tmp_path / "s1sw.input").read_bytes()[s1.INPUT_HEADER.size:]
    assert not bits[75 >> 3] & (1 << (75 & 7)) and bits[521 >> 3] & (1 << (521 & 7))
    pipe.close()
    assert not any((tmp_path / "s1sw.input").read_bytes()[s1.INPUT_HEADER.size:])
    assert pipe.held == {}
    assert pipe.pause() is False                    # no pause on this rig


def test_pipe_writes_in_place_when_its_tmp_cannot_be_made(s1, tmp_path):
    # PAD-977: GoT's first write at attach could not make s1sw.input.tmp over
    # \\wsl.localhost; the bitmap in place still reaches the responder
    rig = s1.Spike1Rig.__new__(s1.Spike1Rig)
    rig.dump = str(tmp_path)
    (tmp_path / "s1sw.input.tmp").mkdir()           # nothing can be opened at the .tmp path
    pipe = s1.Spike1Pipe(rig)
    assert pipe.set(75, 1) and pipe.set(521, 1)
    bits = (tmp_path / "s1sw.input").read_bytes()[s1.INPUT_HEADER.size:]
    assert bits[75 >> 3] & (1 << (75 & 7)) and bits[521 >> 3] & (1 << (521 & 7))
    assert pipe.set(75, 0)
    bits = (tmp_path / "s1sw.input").read_bytes()[s1.INPUT_HEADER.size:]
    assert not bits[75 >> 3] & (1 << (75 & 7)) and bits[521 >> 3] & (1 << (521 & 7))
    assert pipe._failed == 0


def test_the_got_le_maps_gi_bulbs_follow_the_games_gi_strings():
    # PAD-977: VPW's table turns its GI on only in its own game start, which
    # the shadow game never gets: every aGiLights bulb is the machine's now, on
    # the LEDs GOT LE 1.37's GI light lists name (LOWER / LEFT / UP RIGHT
    # PLAYFIELD GI = LED entries 0xdc, 0xdd, 0xde)
    m = json.load(open(os.path.join(VPX, "got_le.shadow.json"), encoding="utf-8"))
    gi = {k: v for k, v in m["lamps"].items() if k.startswith("gi")}
    strings = {(8, 4): "LOWER PLAYFIELD GI", (9, 0): "LEFT PLAYFIELD GI", (10, 0): "UP RIGHT PLAYFIELD GI"}
    assert len(gi) == 57
    for k, v in gi.items():
        (led,) = [tuple(x) for x in v["leds"]]
        assert strings[led] == v["name"], k
    # the three bulbs the baked GI lightmaps follow (LampTimer3: Lampz 80-82)
    assert [tuple(gi[k]["leds"][0]) for k in ("gi010", "gi026", "gi036")] == [(8, 4), (10, 0), (9, 0)]
    pc = pytest.importorskip("padcontroller")
    vm = pc.VpxMap("got_le")
    assert all(pc.lamp_number(*led) in vm.lamp_groups for led in strings)


@pytest.mark.parametrize("title,leds,n", [
    ("kiss_le", [(8, 4), (9, 4), (10, 4)], 55),       # white / red / blue playfield GI
    ("ghostbusters_le", [(9, 0), (9, 2)], 50)])       # playfield GI 3 / 2
def test_the_other_spike1_tributes_gi_is_the_machines_too(title, leds, n):
    # PAD-977: KISS's and Ghostbusters' tributes, like GoT's, turn their GI on
    # only in their own ResetForNewGame; their aGiLights bulbs are lit while
    # any of the game's playfield GI strings is (one group, not RGB)
    m = json.load(open(os.path.join(VPX, title + ".shadow.json"), encoding="utf-8"))
    gi = [v for v in m["lamps"].values() if isinstance(v, dict) and "GI" in v.get("name", "")]
    assert len(gi) == n and all([tuple(x) for x in v["leds"]] == leds and not v.get("rgb") for v in gi)
    assert any(k["since"].startswith("PAD-977") for k in m["repatch"])
    pc = pytest.importorskip("padcontroller")
    vm = pc.VpxMap(title)
    g = pc.lamp_number(*leds[0])
    assert vm.lamp_groups[g] == leds and g not in vm.rgb_groups


def test_bridge_takes_the_spike1_rig_for_a_spike1_map():
    pc = pytest.importorskip("padcontroller")
    b = pc.Bridge()
    b.set_game("got_le")
    assert b.spike1 and b.max_id == 1024 and b._sol_number(9, 2) == 1578
    assert b._rig_up(struct.pack("<4I", 0x53314857, 1, 0, 0) + bytes(5 * 1024))
    assert not b._rig_up(b"\0" * 32)
    b2 = pc.Bridge()
    b2.set_game("rush_le")
    assert not b2.spike1 and b2.max_id == 256 and b2._sol_number(8, 1) == 1129


def test_spike1_poll_reports_lamps_coils_and_held_flippers(tmp_path):
    pc = pytest.importorskip("padcontroller")
    s1 = pytest.importorskip("s1bridge")
    m = pytest.importorskip("pinball_decryptor.plugins.stern.spike1_emulate")
    b = pc.Bridge()
    b.set_game("got_le")
    rig = s1.Spike1Rig.__new__(s1.Spike1Rig)
    rig.dump = str(tmp_path)
    b.rig = rig
    b.pipe = s1.Spike1Pipe(rig)
    b.sw_ids = {(8, 3): 515, (1, 11): 75}
    b._button_coils = {(8, 7): 3}                  # RIGHT FLIPPER POWER from R. FLIPPER BUTTON
    st = m.HardwareState()
    st.set_lamp(8, 20, 255)                         # li11, an RGB insert, mapped
    st.set_lamp(9, 63, 200)                         # an unmapped channel
    st.set_coil(9, 2, True)                         # TROUGH UP-KICKER
    st.set_switch(1, 11, True)
    (tmp_path / "s1hw.state").write_bytes(m.StateBlock.pack(st, seq=1))
    b._poll_once()
    lamps = dict(b.changed_lamps() or [])
    assert lamps[pc.lamp_number(8, 20)] > 1 and lamps[pc.lamp_number(9, 63)] == 1   # the insert lit in its colour
    sols = dict(b.changed_solenoids() or [])
    assert sols[1] == 1                             # the map's number reaches core.vbs
    assert b.sol_state[1578] == 1                   # the 1000+ one is kept (Solenoid(n) reads it)
    assert sols[40] == 1                            # game_on: always armed here
    assert sols.get(46, 0) == 0 and b.get_switch(1075)
    b.pipe.set(515, 1)
    b._poll_once()
    sols = dict(b.changed_solenoids() or [])
    assert sols[46] == 1 and b.sol_state[1519] == 1  # the held button holds the coil
    assert b.polls == 2 and b.poll_fail == 0


def test_spike1_raw_lamp_aliases_keep_levels_and_report_zero(tmp_path):
    pc = pytest.importorskip("padcontroller")
    s1 = pytest.importorskip("s1bridge")
    m = pytest.importorskip("pinball_decryptor.plugins.stern.spike1_emulate")
    mapping = tmp_path / "raw.vpxmap.json"
    mapping.write_text(json.dumps({"platform": "spike1", "raw_lamp_rewrite": {
        "_": "legacy lamp number -> node and channel", "281": [15, 63], "94": [8, 11]}}), encoding="utf-8")
    b = pc.Bridge()
    b.map = pc.VpxMap()
    b.map.load(str(mapping))
    rig = s1.Spike1Rig.__new__(s1.Spike1Rig)
    rig.dump = str(tmp_path)
    b.rig, b.sw_ids = rig, {}
    st = m.HardwareState()
    for seq, position, brightness in ((1, 71, 128), (2, 130, 255), (3, 0, 0)):
        st.set_lamp(15, 63, position)
        st.set_lamp(8, 11, brightness)
        (tmp_path / "s1hw.state").write_bytes(m.StateBlock.pack(st, seq=seq))
        b._poll_once_s1()
        changes = dict(b.changed_lamps() or [])
        assert changes[281] == position and changes[94] == brightness
        assert b.lamp_state[281] == position
    b._poll_once_s1()
    assert not b.changed_lamps()    # an unchanged frame is not a new change


def test_spike1_raw_lamp_alias_level_reaches_controller_lamp(tmp_path):
    """Controller.Lamp(n), not only ChangedLamps, gives the table the raw
    level (a table polling its mech position reads Lamp); other lamps stay
    Boolean as VPinMAME's are."""
    pc = pytest.importorskip("padcontroller")
    s1 = pytest.importorskip("s1bridge")
    m = pytest.importorskip("pinball_decryptor.plugins.stern.spike1_emulate")
    mapping = tmp_path / "raw.vpxmap.json"
    mapping.write_text(json.dumps({"platform": "spike1", "raw_lamp_rewrite": {"281": [15, 63]}}),
                       encoding="utf-8")
    b = pc.Bridge()
    b.map = pc.VpxMap()
    b.map.load(str(mapping))
    rig = s1.Spike1Rig.__new__(s1.Spike1Rig)
    rig.dump = str(tmp_path)
    b.rig, b.sw_ids = rig, {}
    st = m.HardwareState()
    st.set_lamp(15, 63, 71)
    st.set_lamp(8, 11, 200)
    (tmp_path / "s1hw.state").write_bytes(m.StateBlock.pack(st, seq=1))
    b._poll_once_s1()
    assert b.lamp(281) == 71 and type(b.lamp(281)) is int
    assert b.lamp(pc.lamp_number(8, 11)) is True


def test_launch_finds_a_spike1_card_in_the_sister_library(tmp_path, monkeypatch):
    pl = pytest.importorskip("padlaunch")
    lib2 = tmp_path / "spike2"
    lib1 = tmp_path / "spike1"
    lib2.mkdir()
    lib1.mkdir()
    (lib1 / "GOT_LE-1_37.iso").write_bytes(b"x")
    (lib1 / "GOT_LE-1_36.iso").write_bytes(b"x")
    monkeypatch.delenv("PAD_VPX_LIBRARY", raising=False)
    monkeypatch.delenv("PAD_VPX_CARD", raising=False)
    monkeypatch.setattr(pl, "kit_load", lambda: {"library": str(lib2)})
    assert pl.libraries("spike1") == [str(lib2), str(lib1)]
    assert pl.card_for("got_le", "spike1") == str(lib1 / "GOT_LE-1_37.iso")
    assert pl.card_for("got_le") is None            # a Spike 2 look finds no .iso
    monkeypatch.setattr(pl, "kit_load", lambda: {"libraries": {"spike1": str(lib1)}})
    assert pl.card_for("got_le", "spike1") == str(lib1 / "GOT_LE-1_37.iso")
    assert isinstance(pl.launch_for("spike1", "got_le", "c.iso"), pl.Spike1Launch)
    assert isinstance(pl.launch_for("spike2", "rush_le", "c.raw"), pl.Launch)


@pytest.mark.parametrize("python", [r"C:\PAD App\python\python.exe", ""])
def test_spike1_launch_passes_the_native_audio_interpreter(monkeypatch, python):
    pl = pytest.importorskip("padlaunch")
    monkeypatch.setattr(pl, "win_python", lambda: python)
    monkeypatch.setattr(pl.padpath, "to_wsl", lambda p, d: "mapped:" + p)
    launch = pl.Spike1Launch("ghostbusters_le", "card.iso", dist="TestRuntime")
    launch.work = "/work/spike1"
    env, card = launch.env()
    expected = ["PAD_WINPYTHON=mapped:" + python] if python else []
    assert [s for s in env if s.startswith("PAD_WINPYTHON=")] == expected
    assert "PAD_AUDIO=1" in env and "S1_WORK=/work/spike1" in env
    assert card == "mapped:card.iso"


def test_spike1_launch_refuses_another_titles_run(tmp_path, monkeypatch):
    pl = pytest.importorskip("padlaunch")
    s1 = pytest.importorskip("s1bridge")
    monkeypatch.setattr(s1, "BOARD", str(tmp_path))
    (tmp_path / "spike1-0.run").write_text(json.dumps({"emu": "spike1", "game": "KISS_LE", "label": "PAD", "pid": 1}),
                                           encoding="utf-8")
    launch = pl.Spike1Launch("got_le", "c.iso", dist="PAD-Runtime")
    other = launch.other_run()
    assert other and other["game"] == "KISS_LE"
    monkeypatch.setattr(pl, "no_linux", lambda d: "")
    with pytest.raises(RuntimeError, match="running KISS_LE"):
        launch.start()
    (tmp_path / "spike1-0.run").write_text(json.dumps({"emu": "spike1", "game": "GOT_LE", "label": "PAD", "pid": 1}),
                                           encoding="utf-8")
    assert launch.other_run() is None
    assert launch.alive()                           # the board says the title's run is up


@pytest.mark.parametrize("command", [r"C:\DMD Tools\viewer.exe", [r"C:\PAD App\python.exe", "viewer.py"]])
def test_spike1_starts_only_the_configured_owned_dmd_viewer(monkeypatch, command):
    from unittest.mock import Mock
    pl = pytest.importorskip("padlaunch")
    monkeypatch.setattr(pl.sys, "platform", "win32")
    monkeypatch.setattr(pl, "BOARD", "test-board")
    monkeypatch.setattr(pl, "kit_load", lambda: {"spike1_dmd_viewers": {"ghostbusters_le": command}})
    monkeypatch.setattr(pl.os.path, "isfile", lambda p: True)
    said = []
    monkeypatch.setattr(pl, "log", said.append)
    spawn = Mock()
    spawn.return_value.pid = 4242
    monkeypatch.setattr(pl.subprocess, "Popen", spawn)
    launch = pl.Spike1Launch.__new__(pl.Spike1Launch)
    launch.title, launch.dmd_viewer = "ghostbusters_le", None
    output = object()
    launch._start_dmd_viewer(output)
    expected = [command] if isinstance(command, str) else command
    assert spawn.call_args.args[0] == expected + [os.path.join("test-board", "spike1-0.run"), "ghostbusters_le"]
    assert spawn.call_args.kwargs["stdout"] is output
    assert not spawn.call_args.kwargs.get("shell")
    assert launch.dmd_viewer is spawn.return_value
    assert len(said) == 1 and "pid 4242" in said[0] and "ghostbusters_le" in said[0]


@pytest.mark.parametrize("command", [None, [], [1], "missing.exe"])
def test_spike1_missing_or_invalid_viewer_does_not_stop_the_game(monkeypatch, command):
    from unittest.mock import Mock
    pl = pytest.importorskip("padlaunch")
    monkeypatch.setattr(pl.sys, "platform", "win32")
    monkeypatch.setattr(pl, "kit_load", lambda: {"spike1_dmd_viewers": {"ghostbusters_le": command}})
    monkeypatch.setattr(pl.os.path, "isfile", lambda p: False)
    said = []
    monkeypatch.setattr(pl, "log", said.append)
    spawn = Mock()
    monkeypatch.setattr(pl.subprocess, "Popen", spawn)
    launch = pl.Spike1Launch.__new__(pl.Spike1Launch)
    launch.title, launch.dmd_viewer = "ghostbusters_le", None
    launch._start_dmd_viewer(None)
    spawn.assert_not_called()
    assert launch.dmd_viewer is None
    if command:                     # a configured but unusable viewer says which and why
        assert len(said) == 1 and "ghostbusters_le" in said[0] and repr(command) in said[0]
    else:                           # an unconfigured one is silent
        assert said == []


def test_spike1_viewer_stop_reaps_only_its_owned_child(monkeypatch):
    from unittest.mock import Mock
    pl = pytest.importorskip("padlaunch")
    launch = pl.Spike1Launch.__new__(pl.Spike1Launch)
    viewer = Mock()
    viewer.poll.return_value = None
    viewer.wait.side_effect = [pl.subprocess.TimeoutExpired("viewer", 3), 0]
    launch.dmd_viewer = viewer
    launch._stop_dmd_viewer()
    viewer.terminate.assert_called_once()
    viewer.kill.assert_called_once()
    assert viewer.wait.call_count == 2 and launch.dmd_viewer is None
    launch._stop_dmd_viewer()   # repeated cleanup cannot stop another process
    assert viewer.terminate.call_count == 1


def test_padvpx_knows_a_maps_platform():
    pv = pytest.importorskip("padvpx")
    assert pv.platform_of("got_le") == "spike1"
    assert pv.platform_of("rush_le") == "spike2"
    assert pv.maps()["got_le"]["platform"] == "spike1" and pv.maps()["got_le"]["listed"] is True


def test_spike1_launch_passes_only_the_selected_maps_encoder_wiring(tmp_path, monkeypatch):
    pl = pytest.importorskip("padlaunch")
    maps = tmp_path / "maps"
    maps.mkdir()
    (maps / "ghostbusters_le_replica.vpxmap.json").write_text(json.dumps({
        "encoder_lamps": {"8,0": [15, 63]}}), encoding="utf-8")
    monkeypatch.setattr(pl, "USER_MAPS", str(maps))
    monkeypatch.setattr(pl, "win_python", lambda: "")
    monkeypatch.setattr(pl.padpath, "to_wsl", lambda p, d: p)
    for title, expected in (("ghostbusters_le_replica", ["S1_ENCODER_LAMPS=8,0:15,63"]), ("got_le", [])):
        launch = pl.Spike1Launch(title, "card.iso", dist="TestRuntime")
        launch.work = "/test/spike1"
        env, _ = launch.env()
        assert [s for s in env if s.startswith("S1_ENCODER_LAMPS=")] == expected
    with pytest.raises(ValueError, match="encoder_lamps"):
        pl.encoder_lamp_env({"8,0": [15, 64]})
