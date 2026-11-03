"""Alice Cooper's Nightmare Castle behind a Visual Pinball table (PAD-954):
the P-ROC board's bridge (tools/proc_emu/prochw.py --bridge), the controller
finding the P-ROC rig's runs (spkbridge.py), the map on Helshaks' table
(gen_alice_map.py -> ac.shadow.json), and the authors' card reading the
game's machine yaml.

What is worth failing on, none of it needing a run:
  * THE BOARD'S FILES are the Warden board's (spkbridge reads both): switches
    by number, LEDs and coils by their places in the yaml, a pulse seen for
    BRIDGE_PULSE_S, a timed patter (a sling's kick) ending by itself.
  * ATTACHED, the table owns the balls: the first input sets the trough and
    the lane whole, and the ball model no longer moves a ball.
  * THE RUN: a `spooky-proc` record is a Spooky run, its rig folder the
    P-ROC rig's.
  * THE MAP: every switch a switch of the game, every coil one of its coils,
    every light one of its LEDs; the flippers on the coils the game drives.
  * THE PATCHER renames every definition of a sub (the table defines some
    twice, and the last one runs).
"""
import importlib.util
import json
import os
import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
VPX = ROOT / "tools" / "spike2_emu" / "vpx"
PROC = ROOT / "tools" / "proc_emu"
for p in (ROOT / "tools" / "spike2_emu", VPX):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
pytestmark = pytest.mark.skipif(not VPX.is_dir(), reason="rig not present")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


if "pinproc" not in sys.modules:
    _load("pinproc", PROC / "pystub" / "pinproc.py")
prochw = _load("pad954_prochw", PROC / "prochw.py")

#: config/alice.yaml of ac-gamecode 1.1.0.5, the parts the map names
#: (PRSwitches name -> SD number; PRCoils and PRLEDs counts)
AC_SWITCHES = {
    "coin1": 0, "enter": 4, "up": 5, "down": 6, "exit": 7, "flipperUpR": 9, "flipperLwR": 10,
    "launchBallButton": 11, "tilt": 13, "flipperLwL": 14, "startButton": 15, "balcony": 18,
    "upperRightExit": 19, "upperLeftExit": 20, "target2": 21, "target3": 22, "target1": 23,
    "leftRampOpto": 24, "outsideLeftOrbit": 25, "leftCastleLock": 26, "rightCastleLock": 27,
    "leftMagnet": 28, "chopOpto": 30, "righMagnet": 31, "dropOpto": 33, "rightRampOpto": 34,
    "rightSubway": 35, "backDropTarget": 36, "frontDropTarget": 37, "rightOuterOrbit": 38,
    "increaseMultiplier": 39, "hellTarget1": 44, "hellTarget2": 45, "hellTarget3": 46, "slingr": 47,
    "inlaneRight": 48, "outlaneRight": 49, "shooter": 50, "troughJam": 51, "trough1": 52,
    "trough2": 53, "trough3": 54, "trough4": 55, "leftSubway": 56, "innerLeftOrbit": 57,
    "spinner": 58, "hurryup": 59, "leftScoop": 60, "slingl": 61, "inlaneLeft": 62, "outlaneLeft": 63}
AC_LEDS = 84

MINI_YAML = """PRGame:
    machineType: pdb
    numBalls: 2
PRSwitches:
    trough1:
        number: SD52
        type: 'NC'
    trough2:
        number: SD53
    troughJam:
        number: SD51
        type: 'NC'
    shooter:
        number: SD50
    slingl:
        number: SD61
        label: SLING LEFT
    SD29:
        number: SD29
        label: TOP OF INNER ORBIT
    SD40:
        number: SD40
PRCoils:
    trough:
        number: A5-B1-0
        pulseTime: 30
    slingl:
        number: A6-B1-5
    flipperLwLMain:
        number: A6-B1-0
PRLEDs:
    arrowLeftRamp:
        number: A1-R0-G1-B2
        tags: pf
        label: LEFT RAMP ARROW
    GIbackLeft1:
        number: A2-R3-G4-B5
        tags: gi
"""


@pytest.fixture
def mini(tmp_path):
    p = tmp_path / "alice.yaml"
    p.write_text(MINI_YAML, encoding="utf-8")
    return p


@pytest.fixture
def fpga(mini):
    pytest.importorskip("yaml")
    m = prochw.Machine(str(mini))
    clock = [100.0]
    f = prochw.Fpga("p3roc", m, m.initial_closed(), clock=lambda: clock[0])
    f.coil_drivers.update({"trough": 64, "slingl": 53, "flipperLwLMain": 48})
    f.tick_to = lambda t: (clock.__setitem__(0, t), f.tick())
    f.now = clock
    return f


def _block(f):
    data = f.bridge_block(1)
    n = prochw.BRIDGE_SLOTS
    magic, ver, seq, flags = struct.unpack_from("<4I", data, 0)
    o = 16
    return magic, flags, data[o:o + n], data[o + n:o + n * 4], data[o + n * 4:o + n * 5]


# --- the board -----------------------------------------------------------

def test_the_board_reads_leds_and_coils_in_the_yamls_order(mini):
    pytest.importorskip("yaml")
    m = prochw.Machine(str(mini))
    assert m.coil_names == ["trough", "slingl", "flipperLwLMain"]
    assert m.leds == [(1, 0, 1, 2), (2, 3, 4, 5)]
    assert m.decode_led("A3-R81-G82-B83") == (3, 81, 82, 83) and m.decode_led("C-A4-B0-0") is None


def test_the_block_is_the_warden_boards(fpga):
    spk = pytest.importorskip("spkbridge")
    assert (prochw.BRIDGE_STATE_MAGIC, prochw.BRIDGE_INPUT_MAGIC) == (spk.STATE_MAGIC, spk.INPUT_MAGIC)
    assert (prochw.BRIDGE_STATE, prochw.BRIDGE_INPUT, prochw.BRIDGE_ATTACHED) == (
        spk.STATE_FILE, spk.INPUT_FILE, spk.ATTACHED_FILE)
    assert prochw.BRIDGE_SLOTS == spk.N_SLOTS
    data = fpga.bridge_block(3)
    assert len(data) == spk.STATE_SIZE and spk.is_up(data)
    fpga.leds["1:0"], fpga.leds["1:1"], fpga.leds["1:2"] = 255, 128, 0
    sw, lamps, coils, _ = spk.unpack(fpga.bridge_block(4))
    assert spk.lamp_rgb(lamps, 0, 0) == (255, 128, 0)        # LED 0: the yaml's first
    assert sw[52] == 1 and sw[53] == 1 and sw[50] == 0        # the trough's two balls, active


def test_a_pulse_reads_on_for_the_bridges_window(fpga):
    fpga.set_driver(64, 1 << 9 | 21, 0, "host")              # trough: pulse 21 ms
    assert _block(fpga)[4][0] == 1                            # coil 0 = PRCoils' first
    fpga.tick_to(100.05)
    assert not fpga.drivers[64]["active"] and _block(fpga)[4][0] == 1
    fpga.tick_to(100.2)
    assert _block(fpga)[4][0] == 0


def test_a_timed_patter_ends_by_itself(fpga):
    # a sling's "patter 2/2 for 15 ms" read as on for ever: its coil never let go
    w2 = (1 << 30) | (2 << 16) | (2 << 23)
    fpga.set_driver(53, 15, w2, "rule sw61 closed")
    assert prochw.describe_driver(fpga.drivers[53]) == "patter 2/2 for 15ms"
    assert _block(fpga)[4][1] == 1
    fpga.tick_to(100.5)
    assert not fpga.drivers[53]["active"] and _block(fpga)[4][1] == 0
    # a flipper's "patter after 40 ms" holds until the rule lets it go
    fpga.set_driver(48, (1 << 9) | 40, (1 << 30) | (2 << 16) | (12 << 23), "rule sw14 closed")
    fpga.tick_to(101.5)
    assert fpga.drivers[48]["active"] and _block(fpga)[4][2] == 1


def test_attached_the_table_owns_the_balls(fpga):
    fpga.ball_model = {"eject": 64, "shooter": 50}
    fpga.set_bridged(True)
    bits = bytearray(128)
    bits[51 >> 3] |= 1 << (51 & 7)                            # the table: a ball on the jam opto
    bits[52 >> 3] |= 1 << (52 & 7)                            # and one on trough1
    fpga.bridge_input(struct.pack("<3I", prochw.BRIDGE_INPUT_MAGIC, 1, 1) + bytes(bits))
    assert fpga.active(52) and not fpga.active(53) and fpga.active(51)   # the trough set whole
    fpga.set_driver(64, 1 << 9 | 21, 0, "host")
    fpga.tick_to(101.0)
    assert fpga.active(52) and not fpga.active(50)            # no ball moved by the board
    assert fpga.plunge() is False and fpga.drain() is False
    bits[61 >> 3] |= 1 << (61 & 7)
    fpga.bridge_input(struct.pack("<3I", prochw.BRIDGE_INPUT_MAGIC, 1, 2) + bytes(bits))
    assert fpga.active(61)
    assert _block(fpga)[1] == 1                               # flags: bridged


def test_the_daemon_attaches_on_the_tables_file(fpga, tmp_path):
    d = prochw.Daemon(str(tmp_path), fpga, open(os.devnull, "w"), bridge=str(tmp_path))
    d.bridge_tick()
    assert (tmp_path / prochw.BRIDGE_STATE).is_file() and not fpga.bridged
    (tmp_path / prochw.BRIDGE_ATTACHED).write_text("PAD.Controller\n")
    bits = bytearray(128)
    bits[50 >> 3] |= 1 << (50 & 7)
    (tmp_path / prochw.BRIDGE_INPUT).write_bytes(struct.pack("<3I", prochw.BRIDGE_INPUT_MAGIC, 1, 1) + bytes(bits))
    d.bridge_tick()
    assert fpga.bridged and fpga.active(50) and not fpga.active(52)
    assert d.on_ctl("coils trough=64") == "ok 3 coils"
    assert json.loads(d.on_ctl("coils"))["trough"] == 64


# --- the run -------------------------------------------------------------

def test_a_p_roc_run_is_a_spooky_run(tmp_path, monkeypatch):
    spk = pytest.importorskip("spkbridge")
    monkeypatch.setattr(spk, "BOARD", str(tmp_path))
    rec = {"emu": "spooky-proc", "slot": 6, "game": "ac_1.1.0.5", "label": "PAD-VPX", "distro": "PAD-Runtime",
           "pid": 1, "root": "/var/tmp/pad_spkproc/rig6"}
    (tmp_path / "spooky-proc-6.run").write_text(json.dumps(rec), encoding="utf-8")
    assert spk.board_record("ac")["slot"] == 6 and spk.board_record(slot=6)["game"] == "ac_1.1.0.5"
    assert spk.board_record("h78") is None
    rig = spk.SpookyRig("ac")
    assert rig.root == "/var/tmp/pad_spkproc/rig6"
    rec.pop("root")
    assert spk.SpookyRig(record=rec).root == "/var/tmp/pad_spkproc/rig6"


def test_alice_coopers_package_is_its_card(tmp_path, monkeypatch):
    pl = pytest.importorskip("padlaunch")
    lib2 = tmp_path / "Stern" / "spike2"
    spooky = tmp_path / "Spooky"
    lib2.mkdir(parents=True)
    spooky.mkdir()
    (spooky / "ac-gamecode.pkg").write_bytes(b"x")
    (spooky / "tna-gamecode.pkg").write_bytes(b"x")
    monkeypatch.delenv("PAD_VPX_LIBRARY", raising=False)
    monkeypatch.delenv("PAD_VPX_CARD", raising=False)
    monkeypatch.setattr(pl, "kit_load", lambda: {"library": str(lib2)})
    assert pl.card_for("ac", "spooky") == str(spooky / "ac-gamecode.pkg")
    assert isinstance(pl.launch_for("spooky", "ac", "c.pkg"), pl.SpookyLaunch)


# --- the map -------------------------------------------------------------

def test_the_map_is_what_its_generator_writes():
    gen = _load("pad954_gen", VPX / "gen_alice_map.py")
    m = json.load(open(VPX / "ac.shadow.json", encoding="utf-8"))
    assert m == json.loads(json.dumps(gen.build()))


def test_the_map_numbers_the_games_own_parts():
    gen = _load("pad954_gen2", VPX / "gen_alice_map.py")
    m = json.load(open(VPX / "ac.shadow.json", encoding="utf-8"))
    assert m["platform"] == "spooky" and m["title"] == "ac" and m["listed"]
    assert len(gen.COILS) == 27
    for obj, s in m["switches"].items():
        if obj != "_":
            assert AC_SWITCHES.get(s["name"]) == s["id"], obj
    for num, c in m["solenoids"].items():
        if num != "_":
            assert c["coil"][0] == 0 and gen.COILS[c["coil"][1]] == c["name"], num
    # the game flips on the main coils (pulse, then patter); the holds are never driven
    for n in ("46", "48", "34"):
        assert m["solenoids"][n]["name"].endswith("Main")
    for light, v in m["lamps"].items():
        if light != "_":
            node, idx = v["leds"][0]
            assert 0 <= node * 64 + idx < AC_LEDS and v["rgb"], light
    t = m["trough"]
    assert t["switches"] == [AC_SWITCHES[k] for k in ("trough1", "trough2", "trough3", "trough4", "troughJam")]
    assert t["balls"] == 4 and m["plunger"]["lane_switch"] == AC_SWITCHES["shooter"]
    cab = m["cabinet"]
    assert (cab["start"], cab["coin"], cab["left_flipper"], cab["right_flipper"], cab["up_right_flipper"],
            cab["launch"]) == tuple(1000 + AC_SWITCHES[k] for k in (
                "startButton", "coin1", "flipperLwL", "flipperLwR", "flipperUpR", "launchBallButton"))
    assert m["saucers"]["Kicker2"]["switch"] == AC_SWITCHES["leftScoop"]


def test_the_catalogue_row_names_the_map():
    cat = json.load(open(VPX / "catalog.json", encoding="utf-8"))
    row = next(t for t in cat["tables"] if t.get("game") == "Alice Cooper's Nightmare Castle")
    assert row["title"] == "ac" and row["map"] and not row.get("no_game")


# --- the patcher ---------------------------------------------------------

def test_every_definition_of_a_sub_is_renamed():
    vs = pytest.importorskip("vpxshadow")
    lines = ["Sub sw9_Hit : A : End Sub", "Sub Other_Hit : End Sub", "Sub sw9_Hit ' again", "End Sub"]
    rep = []
    assert vs.rename_sub(lines, "sw9_Hit", rep)
    assert lines[0].startswith("Sub sw9_Hit_orig") and lines[2].startswith("Sub sw9_Hit_orig")
    assert rep == ["renamed Sub sw9_Hit -> sw9_Hit_orig (2 definitions)"]
    rep = []
    assert vs.rename_sub(lines, "Other_Hit", rep) and rep == ["renamed Sub Other_Hit -> Other_Hit_orig"]
    assert not vs.rename_sub(lines, "Nothing_Hit", [])


# --- the authors' card ---------------------------------------------------

def test_the_machine_yaml_is_read_without_a_yaml_library(mini):
    va = pytest.importorskip("vpxauthor")
    cfg = va.read_machine_yaml(str(mini))
    assert list(cfg["PRSwitches"]) == ["trough1", "trough2", "troughJam", "shooter", "slingl", "SD29", "SD40"]
    assert cfg["PRSwitches"]["trough1"] == {"number": "SD52", "type": "NC"}
    assert cfg["PRLEDs"]["arrowLeftRamp"]["label"] == "LEFT RAMP ARROW"
    yaml = pytest.importorskip("yaml")
    ref = yaml.safe_load(MINI_YAML)
    for sec in ("PRSwitches", "PRCoils", "PRLEDs"):
        assert {k: {f: str(x) for f, x in (v or {}).items()} for k, v in ref[sec].items()} == cfg[sec]


def test_the_authors_card_reads_alice_coopers_machine(mini):
    va = pytest.importorskip("vpxauthor")
    m = va.read_machine_spooky_proc("ac", str(mini))
    ids = {s["id"]: s for s in m["switches"]}
    assert 29 in ids and ids[29]["name"] == "TOP OF INNER ORBIT"      # a labelled SD input is wired
    assert 40 not in ids                                                # a spare one is not
    assert ids[61]["name"] == "SLING LEFT"
    assert [c["index"] for c in m["coils"]] == [0, 1, 2] and m["coils"][0]["name"] == "trough"
    assert [i["where"] for i in m["inserts"]] == ["playfield", "cabinet"]   # GI is not an insert
    assert m["inserts"][1]["leds"] == [(0, 1)] and m["platform"] == "spooky"
