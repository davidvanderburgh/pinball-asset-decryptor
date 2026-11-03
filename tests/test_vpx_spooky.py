"""The Spooky rig behind PAD.Controller (PAD-952): tools/spike2_emu/vpx/
spkbridge.py, the board side in tools/spooky_emu/spkwarden.py, the Halloween
and Ultraman maps on marty02's Halloween MM Edition, and the tab's Spooky rows.

What is worth failing on, none of it needing a run:
  * THE TWO FILES ARE THE BOARD'S: spkbridge restates spkwarden's block and
    input (magics, sizes, the servo coils) so the controller never imports
    the rig; a drift reads lamps off by a slot or writes a bitmap the board
    refuses.
  * THE BOARD: its block carries switches, LEDs, held / pulsed coils, a held
    flipper's coils and a raised servo; once a table attached, its trough
    gives way to the table's and its coils stop making switches.
  * THE RUN: a Spooky run is taken by its build's title (h78_v118 -> h78) or
    its slot, from the record's `root`; the launch takes a free kit slot.
  * THE MAPS: Halloween and Ultraman fit the one table, every switch is a
    switch of the game, every coil one of its coils or lifter servos.
  * THE PATCHER'S NEW PIECES: a drop target's switch made while it stands,
    a bank reset that stands them again, and other holes feeding one lane.
  * THE TAB: Spooky updates count as its cards, downloads are read from the
    folders in the tables folder, AMH says why nothing can play
    behind it and opens as it is; TNA is complete on its own, so it is
    not listed (PAD-956).
"""
import importlib.util
import json
import os
import pathlib
import struct
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
VPX = ROOT / "tools" / "spike2_emu" / "vpx"
SPK = ROOT / "tools" / "spooky_emu"
for p in (ROOT / "tools" / "spike2_emu", VPX):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
pytestmark = pytest.mark.skipif(not VPX.is_dir(), reason="rig not present")


def _load(name, path):
    spec = importlib.util.spec_from_file_location("pad952_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(SPK))
warden = _load("warden", SPK / "spkwarden.py")
pinotaur = _load("pinotaur", SPK / "spkpinotaur.py")


@pytest.fixture(scope="module")
def spk():
    return pytest.importorskip("spkbridge")


@pytest.fixture
def pino(tmp_path, monkeypatch):
    b = pinotaur.Pinotaur(str(tmp_path), pty=False, title="h78")
    b.sent = []
    monkeypatch.setattr(b, "send", lambda data: b.sent.append(bytes(data)))
    monkeypatch.setattr(b, "later", lambda secs, fn, *a: fn(*a))
    yield b
    b.log.close()


# --- the two files -------------------------------------------------------

def test_the_layout_is_the_boards(spk):
    assert (spk.STATE_MAGIC, spk.INPUT_MAGIC) == (warden.BRIDGE_STATE_MAGIC, warden.BRIDGE_INPUT_MAGIC)
    assert spk.N_SLOTS == warden.BRIDGE_SLOTS and spk.SERVO_COIL == warden.SERVO_COIL
    assert (spk.STATE_FILE, spk.INPUT_FILE, spk.ATTACHED_FILE) == (
        warden.BRIDGE_STATE, warden.BRIDGE_INPUT, warden.BRIDGE_ATTACHED)


def test_a_block_from_the_board_reads_back(spk, pino):
    pino.state[51] = 1                                  # LEFT SLING made
    pino.leds[107] = (10, 200, 30)                      # left_spinner
    pino.coil_held.add(17)                              # crossover dump held
    pino.pulsed_at[18] = time.monotonic()               # the trough just fired
    pino.pulsed_at[5] = time.monotonic() - 5            # long ago: off
    pino.servos[0] = 150                                # the left lifter up
    pino.servos[1] = 10                                 # the right one down
    pino.flippers = {81: (19, 20, 49)}                  # the left button's coils
    pino.power["flippers"] = 1
    pino.state[81] = 1
    data = pino.bridge_block(7)
    assert spk.is_up(data) and not __import__("s1bridge").is_up(data)
    sw, lamps, coils, seq = spk.unpack(data)
    assert seq == 7 and sw[51] == 1 and sw[65] == 1     # the board's full trough
    assert spk.lamp_rgb(lamps, 107 // 64, 107 % 64) == (10, 200, 30)
    assert coils[17] and coils[18] and not coils[5]
    assert coils[spk.SERVO_COIL] and not coils[spk.SERVO_COIL + 1]
    assert coils[19] and coils[20] and not coils[255]   # a held flipper; 255 is no coil


def test_the_input_is_what_the_table_holds(spk, pino):
    pino.bridged = True
    pino._bridge_first = True
    full = {65, 22, 21, 20, 16, 19, 18}
    pino.bridge_input(spk.pack_input({65, 22, 21}, 1))      # the table holds three balls
    assert {k for k in full if pino.state.get(k)} == {65, 22, 21}
    assert pino.state.get(27) == 0                          # a rest switch the table did not hold
    pino.bridge_input(spk.pack_input({65, 22, 21, 51}, 2))
    assert pino.state[51] == 1
    pino.bridge_input(spk.pack_input({65, 22}, 3))          # 51 let go, a ball out
    assert pino.state[51] == 0 and pino.state[21] == 0
    pino.bridge_input(b"\0" * 140)                           # not an input: ignored
    assert pino.state[65] == 1


def test_attached_the_board_leaves_the_balls_to_the_table(pino):
    pino.bridged = True
    lane = pino.shooter
    pino.fire(18, "pulse")                               # the trough coil
    assert pino.balls == pino.total and not pino.state.get(lane)
    pino.fire(11, "pulse")                               # the bank reset makes no switches
    assert pino.coil_fired[11] == 1 and 11 in pino.pulsed_at
    pino.bridged = False
    pino.fire(18, "pulse")
    assert pino.balls == pino.total - 1                  # unattached it serves as before


def test_the_bridge_loop_publishes_and_takes_input(spk, pino, tmp_path, monkeypatch):
    calls = {"n": 0}

    def sleep(_):
        calls["n"] += 1
        if calls["n"] == 1:
            (tmp_path / spk.ATTACHED_FILE).write_text("PAD.Controller\n")
            (tmp_path / spk.INPUT_FILE).write_bytes(spk.pack_input({65, 51}, 1))
        if calls["n"] >= 3:
            raise KeyboardInterrupt
    monkeypatch.setattr(warden.time, "sleep", sleep)
    with pytest.raises(KeyboardInterrupt):
        pino.bridge_loop()
    data = (tmp_path / spk.STATE_FILE).read_bytes()
    assert spk.is_up(data) and pino.bridged and pino.state[51] == 1 and pino.state[22] == 0


# --- the run --------------------------------------------------------------

def test_the_run_is_found_by_its_builds_title_or_slot(spk, tmp_path, monkeypatch):
    monkeypatch.setattr(spk, "BOARD", str(tmp_path))
    rec = {"emu": "spooky", "slot": 7, "game": "h78_v118", "title": "Halloween", "label": "PAD-VPX",
           "distro": "PAD-Runtime", "pid": 1, "root": "/var/tmp/pad_spooky/rig7"}
    (tmp_path / "spooky-7.run").write_text(json.dumps(rec), encoding="utf-8")
    (tmp_path / "spike1-0.run").write_text(json.dumps({"emu": "spike1", "game": "h78"}), encoding="utf-8")
    assert spk.board_record("h78")["slot"] == 7
    assert spk.board_record("um") is None and spk.board_record(slot=6) is None
    assert spk.board_record(slot=7)["game"] == "h78_v118"
    rig = spk.SpookyRig("h78")
    assert rig.slot == 7 and rig.led_path().endswith(spk.STATE_FILE) and rig.switch_ids() == {}
    if sys.platform == "win32":
        assert rig.dump == r"\\wsl.localhost\PAD-Runtime\var\tmp\pad_spooky\rig7"


def test_the_pipe_writes_the_whole_bitmap(spk, tmp_path):
    class R:
        def sw_path(self):
            return str(tmp_path / spk.INPUT_FILE)
    pipe = spk.SpookyPipe(R())
    pipe.set(65, 1)
    pipe.set(23, 1)
    data = (tmp_path / spk.INPUT_FILE).read_bytes()
    assert struct.unpack_from("<I", data, 0)[0] == spk.INPUT_MAGIC
    bits = data[12:]
    assert bits[65 >> 3] >> (65 & 7) & 1 and bits[23 >> 3] >> (23 & 7) & 1
    assert pipe.pause() is False
    pipe.close()
    assert not any((tmp_path / spk.INPUT_FILE).read_bytes()[12:])


def test_a_spooky_title_boots_its_update_from_the_makers_folder(tmp_path, monkeypatch):
    pl = pytest.importorskip("padlaunch")
    lib2 = tmp_path / "Stern" / "spike2"
    spooky = tmp_path / "Spooky"
    lib2.mkdir(parents=True)
    spooky.mkdir()
    (spooky / "code_H78.pkg").write_bytes(b"x")
    (spooky / "code_UM.pkg").write_bytes(b"x")
    monkeypatch.delenv("PAD_VPX_LIBRARY", raising=False)
    monkeypatch.delenv("PAD_VPX_CARD", raising=False)
    monkeypatch.setattr(pl, "kit_load", lambda: {"library": str(lib2)})
    assert str(spooky) in pl.libraries("spooky")
    assert pl.card_for("h78", "spooky") == str(spooky / "code_H78.pkg")
    assert pl.card_for("um", "spooky") == str(spooky / "code_UM.pkg")
    assert pl.card_for("h78") is None
    assert isinstance(pl.launch_for("spooky", "h78", "c.pkg"), pl.SpookyLaunch)


def test_the_launch_takes_a_free_kit_slot(tmp_path, monkeypatch):
    pl = pytest.importorskip("padlaunch")
    spk = pytest.importorskip("spkbridge")
    monkeypatch.setattr(spk, "BOARD", str(tmp_path))
    (tmp_path / "spooky-7.run").write_text(json.dumps({"emu": "spooky", "slot": 7, "game": "bj_v1",
                                                       "label": "PAD-VPX"}), encoding="utf-8")
    launch = pl.SpookyLaunch("h78", r"D:\Spooky\code_H78.pkg", dist="PAD-Runtime")
    assert launch.take_slot() == 6 and launch.other_run() is None
    env, _ = launch.env()
    assert "PAD_SLOT=6" in env and "PAD_LABEL=PAD-VPX" in env
    (tmp_path / "spooky-5.run").write_text(json.dumps({"emu": "spooky", "slot": 5, "game": "h78_v118",
                                                       "label": "PAD-319"}), encoding="utf-8")
    assert launch.other_run()["slot"] == 5               # the app's own Halloween is up


# --- the maps --------------------------------------------------------------

@pytest.mark.parametrize("title", ["h78", "um"])
def test_the_maps_number_the_games_own_parts(title):
    titles = warden.spktitles.TITLES[title]
    m = json.load(open(VPX / ("%s.shadow.json" % title), encoding="utf-8"))
    assert m["platform"] == "spooky" and m["title"] == title and m["listed"]
    for obj, s in m["switches"].items():
        if obj != "_":
            assert s["id"] in titles["switches"], obj
            assert s["name"] == titles["switches"][s["id"]].upper() or s["name"], obj
    assert m["trough"]["switches"] == list(titles["trough"]) + [titles["jam"]]
    assert m["plunger"]["lane_switch"] == titles["shooter"]
    al = warden.spktitles.aliases(title)
    cab = m["cabinet"]
    assert (cab["start"], cab["coin"], cab["left_flipper"], cab["right_flipper"]) == (
        1000 + al["start"], 1000 + al["coin"], 1000 + al["lflip"], 1000 + al["rflip"])
    assert (cab["service_select"], cab["service_back"]) == (1000 + al["enter"], 1000 + al["back"])
    known = set(titles["coils"]) | {32 + s for s in titles["servos"]}
    for num, c in m["solenoids"].items():
        if num != "_":
            assert c["coil"][0] == 0 and c["coil"][1] in known, num
    assert m["solenoids"]["1"]["coil"] == [0, titles["eject"][0]]
    for k, s in m["saucers"].items():
        if k != "_":
            assert s["switch"] in titles["switches"] and s.get("enter", s["switch"]) in titles["switches"]


def test_one_table_fits_both_titles_halloween_first():
    padvpx = pytest.importorskip("padvpx")
    maps = padvpx.maps()
    assert maps["h78"]["platform"] == maps["um"]["platform"] == "spooky"
    assert maps["h78"]["detect"] == maps["um"]["detect"] and maps["h78"]["output"] == maps["um"]["output"]
    assert list(maps).index("h78") < list(maps).index("um")


def test_the_controller_takes_the_spooky_rig_for_a_spooky_map(spk):
    pc = pytest.importorskip("padcontroller")
    b = pc.Bridge()
    b.set_game("h78")
    assert b.rigmod is spk and b.slots and not b.spike1 and b.max_id == 1024
    assert b._sol_number(0, 18) == 1018
    assert b.switch_id(9008) == 60 and b.switch_id(9011) == 63      # the coin door: MENU ENTER / BACK
    assert b.switch_id(1087) == 87
    vm = pc.VpxMap("h78")
    assert vm.lamp_number if hasattr(vm, "lamp_number") else True
    n = pc.lamp_number(0, 25)
    assert n in vm.lamp_groups and n in vm.rgb_groups          # one LED that is red, green and blue


def test_a_spooky_led_lights_its_table_light_in_its_colour(spk, monkeypatch):
    pc = pytest.importorskip("padcontroller")
    b = pc.Bridge()
    b.set_game("h78")
    block = bytearray(spk.STATE_SIZE)
    struct.pack_into("<4I", block, 0, spk.STATE_MAGIC, 1, 1, 1)
    o = spk.STATE_HEADER.size + spk.N_SLOTS
    block[o + 25 * 3:o + 25 * 3 + 3] = bytes((255, 128, 0))     # save_light orange
    block[o + spk.N_SLOTS * 3 + 18] = 1                         # the trough coil
    monkeypatch.setattr(pc, "read_block", lambda path, n: bytes(block))

    class R:
        def led_path(self):
            return "x"
    b.rig = R()
    b._poll_once()
    assert b.lamp_state[pc.lamp_number(0, 25)] == pc.rgb_value(255, 128, 0)
    assert b.sol_state.get(1) == 1


# --- the patcher's new pieces ------------------------------------------------

MINI = """Option Explicit
Sub Table1_Init : End Sub
Sub Table1_KeyDown(ByVal keycode) : End Sub
Sub Table1_KeyUp(ByVal keycode) : End Sub
Sub Drain_Hit : End Sub
Sub Target1_Hit : AddScore 10 : End Sub
Sub K1_Hit : K1.DestroyBall : Out1.CreateBall : Out1.Kick 180, 10 : End Sub
Sub K2_Hit : K2.DestroyBall : Out1.CreateBall : Out1.Kick 180, 10 : End Sub
"""


def test_drops_standing_made_banks_and_feeders():
    vs = pytest.importorskip("vpxshadow")
    m = {"title": "h78", "platform": "spooky",
         "cabinet": {"start": 1087, "left_flipper": 1081, "right_flipper": 1080, "coin": 1056},
         "switches": {"Target1": {"id": 29, "event": "drop", "up_closed": True}},
         "drop_resets": {"PadBankUp": ["Target1"]},
         "trough": {"release": "BallRelease", "drain": "Drain", "switches": [65, 22], "balls": 2, "kick": [90, 4]},
         "saucers": {"K1": {"switch": 66, "stack": [73], "kick_from": "Out1", "dir": 180, "power": 10,
                            "enter": 76, "feeders": {"K2": {"enter": 79}}}},
         "solenoids": {"1": {"coil": [0, 18], "name": "trough", "callback": "bsTrough.SolOut"},
                       "4": {"coil": [0, 32], "name": "lifter", "callback": "bsK1.SolOut"},
                       "7": {"coil": [0, 11], "name": "reset", "callback": "PadBankUp"}}}
    out, rep = vs.patch(MINI, m)
    assert "Controller.Switch(1029) = True   ' Target1 stands" in out
    assert "Sub Target1_Hit : Controller.Switch(1029) = False : Target1_Hit_orig : End Sub" in out
    assert "Sub PadBankUp(e) : If e Then Controller.Switch(1029) = True : End If : End Sub" in out
    assert "renamed Sub K2_Hit -> K2_Hit_orig" in rep
    k2 = out[out.index("Sub K2_Hit\n"):]
    assert "vpmTimer.PulseSw 1079" in k2.split("End Sub")[0]
    assert "vpmCreateBall Out1 : Out1.Kick 180, 10" in k2.split("End Sub")[0]    # full: out where the lane lets out
    assert "bsK1.AddBall Me" in k2.split("End Sub")[0]
    assert "vpmTimer.PulseSwitch 1056, 600, 0" in out                           # the long coin press


# --- the tab ------------------------------------------------------------------

def test_spooky_updates_are_its_cards(tmp_path, monkeypatch):
    setup = pytest.importorskip("vpxsetup")
    lib2 = tmp_path / "Stern" / "spike2"
    spooky = tmp_path / "Spooky"
    lib2.mkdir(parents=True)
    spooky.mkdir()
    (spooky / "code_H78.pkg").write_bytes(b"x")
    (spooky / "rm-gamecode-20220902.pkg").write_bytes(b"x")
    monkeypatch.delenv("PAD_VPX_LIBRARY", raising=False)
    assert setup.cards_in(str(spooky), "spooky") == {"h78": ["code_H78.pkg"]}
    cards = setup.all_cards(str(lib2), {"library": str(lib2)})
    assert cards.get("h78") == ["code_H78.pkg"] and "rm" not in cards


def test_downloads_are_read_from_the_folders_in_the_tables_folder(tmp_path):
    setup = pytest.importorskip("vpxsetup")
    (tmp_path / "Top 1.0.vpx").write_bytes(b"x")
    (tmp_path / "Top 1.0 (PAD).vpx").write_bytes(b"x")
    orig = tmp_path / "originals"
    orig.mkdir()
    (orig / "halloween_MM_Edition.vpx").write_bytes(b"x")
    (orig / "notes.txt").write_bytes(b"x")
    (orig / "deeper").mkdir()
    (orig / "deeper" / "Two levels.vpx").write_bytes(b"x")
    got = setup.downloads_in(str(tmp_path), cache={})
    assert [d["file"] for d in got] == ["Top 1.0.vpx", "halloween_MM_Edition.vpx"]
    assert got[1]["path"] == str(orig / "halloween_MM_Edition.vpx")


def test_amh_says_why_no_game_plays_behind_it():
    setup = pytest.importorskip("vpxsetup")
    c = setup.catalog_match("America's Most Haunted (Spooky Pinball 2014) LW.vpx")
    assert c and c["platform"] == "spooky" and c["game"] == "America's Most Haunted" and c["no_game"]
    assert not c["complete"]
    cat = setup.load_catalog()
    assert cat["platforms"]["spooky"]["bridge"] == "pad"
    hw = [t for t in cat["tables"] if t.get("game") == "Halloween"][0]
    assert hw["title"] == "h78" and not hw.get("no_game")


def test_tna_is_complete_on_its_own_so_neither_list_has_it(tmp_path):
    """PAD-956: TNA's table is whole without PAD: its download is not on the
    Tables list (read or not) and its catalogue row is marked to be left out."""
    setup = pytest.importorskip("vpxsetup")
    c = setup.catalog_match("Total Nuclear Annihilation (Spooky 2017) VPW v2.3.vpx")
    assert c and c["game"] == "Total Nuclear Annihilation" and c["complete"] and not c["no_game"]
    assert [t for t in setup.load_catalog()["tables"] if t.get("complete")] == [
        t for t in setup.load_catalog()["tables"] if t.get("game") == "Total Nuclear Annihilation"]
    orig = tmp_path / "originals"
    orig.mkdir()
    for f in ("Total Nuclear Annihilation (Spooky 2017) VPW v2.3.vpx",
              "America's Most Haunted (Spooky Pinball 2014) LW.vpx"):
        (orig / f).write_bytes(b"x")
    got = setup.downloads_in(str(tmp_path), cache={})
    assert [d["file"] for d in got] == ["America's Most Haunted (Spooky Pinball 2014) LW.vpx"]


def test_the_catalogue_card_leaves_out_a_complete_table():
    js = open(os.path.join(os.path.dirname(__file__), "..", "pinball_decryptor", "webui", "static",
                           "js", "tabs", "vpx.js"), encoding="utf-8").read()
    assert "filter((t) => !t.complete && " in js


def test_a_download_opens_as_it_is_only_from_the_folder(tmp_path, monkeypatch):
    setup = pytest.importorskip("vpxsetup")
    (tmp_path / "originals").mkdir()
    tna = tmp_path / "originals" / "AMH.vpx"
    tna.write_bytes(b"x")
    vpx = tmp_path / "vp"
    vpx.mkdir()
    monkeypatch.setattr(setup, "find_vpx", lambda: str(vpx))
    monkeypatch.setattr(setup, "vpx_tables_dir", lambda: str(tmp_path))
    monkeypatch.setattr(setup, "missing_directx", lambda v: "")
    opened = []
    monkeypatch.setattr(setup.subprocess, "Popen", lambda args, cwd=None: opened.append(args))
    assert "not one of the downloads" in setup.open_download(str(tmp_path / "elsewhere.vpx"))
    assert setup.open_download(str(tna)) == "ok"
    assert opened == [[os.path.join(str(vpx), "VPinballX64.exe"), "-play", str(tna)]]
    assert tna.read_bytes() == b"x"                     # the download is never changed


def test_the_authors_card_reads_a_spooky_machine(tmp_path):
    author = pytest.importorskip("vpxauthor")
    lights = tmp_path / "lightconfig.json"
    lights.write_text(json.dumps({"save_light": {"num": 25, "label": "save_light"},
                                  "light_70": {"num": 70, "label": "upper_light_strip_1"}}), encoding="utf-8")
    mach = author.read_machine_spooky("h78", lights=str(lights))
    assert mach["platform"] == "spooky"
    ids = {s["id"]: s for s in mach["switches"]}
    assert ids[87]["where"] == "cabinet" and ids[50]["where"] == "unplaced"
    coils = {c["index"]: c for c in mach["coils"]}
    assert coils[18]["name"] == "TROUGH" and coils[32]["name"] == "LEFT SUBWAY LIFTER"
    ins = {i["name"]: i for i in mach["inserts"]}
    assert ins["save_light"]["leds"] == [(0, 25)] and ins["save_light"]["where"] == "playfield"
    assert ins["upper_light_strip_1"]["where"] == "cabinet"
    m = json.load(open(VPX / "h78.shadow.json", encoding="utf-8"))
    cov = author.coverage(m)
    assert 87 in cov["switches"] and (0, 32) in cov["coils"] and (0, 25) in cov["leds"]
