"""tools/cgc_emu (PAD-273): the parts of the Chicago Gaming rig that can be
checked without WSL or a card - the WPC ROM name tables (cgcroms.py), the
ball model each title gets (cgctitles.py), the frame buffer picture
(cgcshot.py) and sw.py's switch names and commands."""

import importlib.util
import json
import pathlib
import struct
import zlib

import pytest

RIG = pathlib.Path(__file__).resolve().parents[1] / "tools" / "cgc_emu"


def _load(name):
    spec = importlib.util.spec_from_file_location("cgc_" + name, RIG / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cgcroms = _load("cgcroms")
cgctitles = _load("cgctitles")
cgcshot = _load("cgcshot")
sw = _load("sw")

MM_SWITCHES = (["LEFT COIN SLOT", "CENTER COIN SLOT", "RIGHT COIN SLOT", "4TH COIN OPTION",
                "ESCAPE", "DOWN", "UP", "ENTER"]
               + ["LAUNCH BUTTON", "CATAPULT TARGET", "START BUTTON", "PLUMB BOB TILT",
                  "L. TROLL TARGET", "LEFT OUTLANE", "RIGHT RETURN", "SHOOTER LANE"]
               + ["SLAM TILT", "COIN DOOR CLOSED", "NOT USED", "ALWAYS CLOSED",
                  "R. TROLL TARGET", "LEFT RETURN", "RIGHT OUTLANE", "RIGHT EJECT"]
               + ["TROUGH EJECT", "TROUGH BALL 1", "TROUGH BALL 2", "TROUGH BALL 3",
                  "TROUGH BALL 4", "LEFT POPPER", "CASTLE GATE", "CATAPULT"]
               + ["MOAT ENTER", "NOT USED", "NOT USED", "CASTLE LOCK", "L. TROLL",
                  "R. TROLL", "LEFT TOP LANE", "RIGHT TOP LANE"]
               + ["LEFT SLINGSHOT", "RIGHT SLINGSHOT", "LEFT JET", "BOTTOM JET",
                  "RIGHT JET", "DRAWBRIDGE UP", "DRAWBRIDGE DOWN", "TOWER EXIT"]
               + ["NOT USED"] * 16)
MM_FLIPPERS = ["R. FLIPPER E.O.S.", "R. FLIPPER BUTTON", "L. FLIPPER E.O.S.",
               "L. FLIPPER BUTTON", "U.R. FLIPPER E.O.S.", "U.R. FLIPPER BUT.",
               "U.L. FLIPPER E.O.S.", "U.L. FLIPPER BUT."]
MM_COILS = ["AUTO PLUNGER", "TROUGH EJECT", "LEFT POPPER", "CASTLE", "CASTLE GATE PWR.",
            "CASTLE GATE HOLD", "KNOCKER", "CATAPULT", "RIGHT EJECT", "LEFT SLINGSHOT",
            "RIGHT SLINGSHOT", "LEFT JET", "BOTTOM JET", "RIGHT JET", "TWR. DIVERT. POWER",
            "TWR. DIVERT. HOLD", "TOWER LOCK POST", "RIGHT GATE", "LEFT GATE",
            "L. TROLL POWER", "L. TROLL HOLD", "R. TROLL POWER", "R. TROLL HOLD",
            "DRAWBRIDGE MOTOR"]


def _page(tables, glued=()):
    """A 16 KiB ROM page laid out as a WPC ROM's: each table a run of BE
    pointers (CPU address 0x4000 + offset), entry 0 the "invalid" text, the
    names after the tables, NUL-ended.  A name in `glued` follows a printable
    byte instead of a NUL (Cactus Canyon's flipper table's entry 0)."""
    page = bytearray(0x4000)
    names_at = 0x1000
    ptr_at = 0x100
    for bad, names in tables:
        for n in [bad] + names:
            if n in glued:
                page[names_at] = ord("z")
                names_at += 1
            page[ptr_at:ptr_at + 2] = struct.pack(">H", 0x4000 + names_at)
            ptr_at += 2
            b = n.encode() + b"\0"
            page[names_at:names_at + len(b)] = b
            names_at += len(b)
        ptr_at += 16                       # data between tables
    return bytes(page)


@pytest.fixture
def mm_rom():
    english = _page([("Null", MM_COILS), ("INVALID SW. NUMBER", MM_SWITCHES),
                     ("INVALID FL. SW. NUM.", MM_FLIPPERS)])
    # another language's set comes first in the ROM, as on the real one
    spanish = _page([("INVALID SW. NUMBER", MM_SWITCHES[:4] + ['BOTON "ESCAPE"', 'BOTON "-"',
                                                               'BOTON "+"', 'BOTON "ENTER"']
                      + MM_SWITCHES[8:])])
    return spanish + english + bytes(0x4000 * 2)


def test_rom_tables_are_the_english_set(mm_rom):
    n = cgcroms.named(mm_rom)
    assert n["switches"]["D1"] == "LEFT COIN SLOT"
    assert n["switches"]["D8"] == "ENTER"
    assert n["switches"]["13"] == "START BUTTON"
    assert n["switches"]["32"] == "TROUGH BALL 1"
    assert "23" not in n["switches"]            # NOT USED is left out
    assert n["flippers"]["F2"] == "R. FLIPPER BUTTON"
    # coil 1 is the table's second entry: entry 0 is its "Null"
    assert n["coils"]["1"] == "AUTO PLUNGER"
    assert n["coils"]["2"] == "TROUGH EJECT"
    assert n["coils"]["24"] == "DRAWBRIDGE MOTOR"


def test_rom_without_tables():
    assert cgcroms.named(bytes(0x10000))["switches"] == {}


def test_mm_ball_model_from_rom_names(mm_rom):
    balls = cgctitles.balls("mm", cgcroms.named(mm_rom))
    kv = dict(p.split("=") for p in balls.split(";"))
    # the configuration proven on the rig: serve on coil 2, launch on coil 1
    assert kv["trough"] == "32,33,34,35"
    assert kv["eject"] == "2"
    assert kv["launch"] == "1"
    assert kv["shooter"] == "18"
    assert kv["optos"] == "31,32,33,34,35,36,41"
    assert set(kv["holes"].split(",")) == {"36:3", "28:9", "38:8"}
    assert kv["mechs"] == "24:56:57"


def test_detect_titles(tmp_path):
    mm = tmp_path / "mm" / "appdata" / "rom"
    mm.mkdir(parents=True)
    (mm / "mm_10.rom").write_bytes(b"")
    assert cgctitles.detect(str(tmp_path / "mm")) == "mm"
    afm = tmp_path / "afm" / "afmdata" / "rom"
    afm.mkdir(parents=True)
    (afm / "mars1_1.rom").write_bytes(b"")     # not named after the title
    assert cgctitles.detect(str(tmp_path / "afm")) == "afm"
    (tmp_path / "cc").mkdir()
    (tmp_path / "cc" / "pin").write_bytes(b"")
    assert cgctitles.detect(str(tmp_path / "cc")) == "cc"
    empty = tmp_path / "empty"
    empty.mkdir()
    assert cgctitles.detect(str(empty)) is None


def test_shot_reads_the_front_buffer(tmp_path):
    w, h = 8, 4
    pitch = w * 2
    hdr = bytearray(4096)
    hdr[0:4] = b"CGCF"
    bufsize = 4096
    struct.pack_into("<8I", hdr, 4, w, h, pitch, 16, 1, 7, 2, bufsize)
    struct.pack_into("<2I", hdr, 36, 4096, 4096 + bufsize)
    back = struct.pack("<H", 0xF800) * (w * h)       # red: not on screen
    front = struct.pack("<H", 0x07E0) * (w * h)      # green: buffer 1, shown
    fb = tmp_path / "fb"
    fb.write_bytes(bytes(hdr) + back.ljust(bufsize, b"\0") + front.ljust(bufsize, b"\0"))
    out = tmp_path / "shot.png"
    assert cgcshot.main(["cgcshot.py", str(fb), str(out)]) == 0
    png = out.read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", png[16:24]) == (w, h)
    i = png.index(b"IDAT")
    ln = struct.unpack(">I", png[i - 4:i])[0]
    raw = zlib.decompress(png[i + 4:i + 4 + ln])
    assert raw[1:4] == b"\x00\xff\x00"


def test_shot_refuses_an_unready_file(tmp_path):
    fb = tmp_path / "fb"
    fb.write_bytes(bytes(8192))
    with pytest.raises(SystemExit):
        cgcshot.main(["cgcshot.py", str(fb), str(tmp_path / "x.png")])


def test_sw_names_and_commands(tmp_path, monkeypatch, mm_rom):
    rig = tmp_path / "rig0"
    rig.mkdir()
    (rig / "names.json").write_text(json.dumps(cgcroms.named(mm_rom)))
    monkeypatch.setenv("CGC_ROOT", str(tmp_path))
    monkeypatch.setenv("PAD_SLOT", "0")
    assert sw.resolve("start") == "13"
    assert sw.resolve("START BUTTON") == "13"
    assert sw.resolve("enter") == "D8"
    assert sw.resolve("l. flipper button") == "F4"
    assert sw.resolve("32") == "32"
    with pytest.raises(SystemExit):
        sw.resolve("trough")                  # four of them
    # the shim's commands: coin door is bank 0, flippers bank 1
    assert sw.line("D1", 1) == "sys 0 0 1"
    assert sw.line("D8", 0) == "sys 0 7 0"
    assert sw.line("F4", 1) == "sys 1 3 1"
    assert sw.line("13", 1) == "sw 13 1"


def test_sw_state_parses_the_shim_file(tmp_path, monkeypatch):
    rig = tmp_path / "rig0"
    rig.mkdir()
    (rig / "state").write_text(
        "sw 800a2f0120000000\nsys 0000\nlamps 0100000000000080\nsols 00000003\n"
        "frames 1805\nballs trough=3 shooter=1 play=0 held=36\nidle 1\n")
    monkeypatch.setenv("CGC_ROOT", str(tmp_path))
    monkeypatch.setenv("PAD_SLOT", "0")
    s = sw.state()
    assert 18 in s["switches_raw"] and 22 in s["switches_raw"]
    assert s["lamps_on"] == [11, 88]
    assert s["coils_on"] == [1, 2]
    assert s["balls"] == {"trough": 3, "shooter": True, "in_play": 0, "held": [36]}


# Cactus Canyon (PAD-1170): optos marked "*", coils named "##1 (L) DROP TGT.",
# unused entries "UNUSED ##n", and a flipper table whose "invalid" entry
# follows a printable byte, so the table is found from entry 1
CC_SWITCHES = (["LEFT COIN SLOT", "CENTER COIN SLOT", "RIGHT COIN SLOT", "4TH COIN OPTION",
                "ESCAPE", "DOWN", "UP", "ENTER"]
               + ["UNUSED ##9", "UNUSED ##10", "START BUTTON", "PLUMB BOB TILT",
                  "MINE ENTRANCE", "LEFT OUTLANE", "R. RETURN", "SHOOTER LANE"]
               + ["SLAM TILT", "COIN DOOR CLOSED", "UNUSED ##19", "ALWAYS CLOSED",
                  "UNUSED ##21", "L. RETURN", "RIGHT OUTLANE", "R STANDUP (BOT)"]
               + ["*TROUGH EJECT", "*TROUGH BALL 1", "*TROUGH BALL 2", "*TROUGH BALL 3",
                  "*TROUGH BALL 4", "*L. LOOP BOTTOM", "*RT. LOOP BOTTOM", "UNUSED ##32"]
               + ["*MINE POPPER", "*SALOON POPPER", "*UNUSED ##35", "R STANDUP (TOP)",
                  "UNUSED ##37", "BEER MUG SWITCH", "L. BONUS X LANE", "JET EXIT"]
               + ["L. SLINGSHOT", "R. SLINGSHOT", "LEFT JET", "RIGHT JET", "BOTTOM JET",
                  "RIGHT LOOP TOP", "R. BONUS X LANE", "LEFT LOOP TOP"]
               + ["UNUSED ##%d" % n for n in range(49, 65)])
CC_COILS = ["AUTOPLUNGER", "##1 (L) DROP TGT.", "##2 (LC) DROP TGT.", "##3 (RC) DROP TGT.",
            "##4 (R) DROP TGT.", "MINE POPPER", "KNOCKER-NOT USED", "SALOON POPPER",
            "TROUGH EJECT", "L. SLINGSHOT", "R. SLINGSHOT", "LEFT JET", "RIGHT JET",
            "L. GUNFIGHT POST", "R. GUNFIGHT POST", "BOTTOM JET", "MINE MOTOR", "UNUSED ##23"]


@pytest.fixture
def cc_rom():
    return _page([("NULL", CC_COILS), ("INVALID SW. NUMBER", CC_SWITCHES),
                  ("INVALID FL. SW. NUM.", MM_FLIPPERS)],
                 glued={"INVALID FL. SW. NUM."}) + bytes(0x4000)


def test_cc_rom_names(cc_rom):
    n = cgcroms.named(cc_rom)
    assert n["switches"]["31"] == "TROUGH EJECT"         # the '*' opto mark dropped
    assert n["switches"]["32"] == "TROUGH BALL 1"
    assert n["switches"]["41"] == "MINE POPPER"
    assert "11" not in n["switches"] and "43" not in n["switches"]   # UNUSED ##n
    # the flipper table read from entry 1 is not shifted by one
    assert n["flippers"]["F1"] == "R. FLIPPER E.O.S."
    assert n["flippers"]["F4"] == "L. FLIPPER BUTTON"
    # coil numbers as the machine's: 6 mine popper, 8 saloon popper, 9 eject
    assert n["coils"]["1"] == "AUTOPLUNGER"
    assert n["coils"]["2"] == "##1 (L) DROP TGT."
    assert n["coils"]["6"] == "MINE POPPER"
    assert n["coils"]["8"] == "SALOON POPPER"
    assert n["coils"]["9"] == "TROUGH EJECT"
    assert "18" not in n["coils"]


def test_mm_names_unchanged_by_the_cc_rules(mm_rom):
    n = cgcroms.named(mm_rom)
    assert n["flippers"]["F1"] == "R. FLIPPER E.O.S."
    assert n["coils"]["1"] == "AUTO PLUNGER"
    assert n["switches"]["31"] == "TROUGH EJECT"


def test_cc_ball_model(cc_rom):
    kv = dict(p.split("=") for p in cgctitles.balls("cc", cgcroms.named(cc_rom)).split(";"))
    # the rig run (PAD-1170): trough 32-35 with 31 clear, serve on coil 9,
    # autoplunger 1, poppers 41/42 kicked by coils 6/8, coin door closed
    assert kv["trough"] == "32,33,34,35"
    assert kv["eject"] == "9"
    assert kv["launch"] == "1"
    assert kv["shooter"] == "18"
    assert set(kv["holes"].split(",")) == {"41:6", "42:8"}
    assert kv["closed"] == "22,24"
    assert "closed" not in cgctitles.balls("mm", {"switches": {"22": "COIN DOOR CLOSED"}})


def test_find_rom_takes_the_game_rom(tmp_path):
    rom = tmp_path / "ccdata" / "rom"
    rom.mkdir(parents=True)
    for f in ("s2.rom", "s3.rom", "cc_g11.1_3"):
        (rom / f).write_bytes(b"")
    assert cgctitles.find_rom(str(tmp_path)).endswith("cc_g11.1_3")
    mm = tmp_path / "mm"
    mm.mkdir()
    (mm / "mm_10.rom").write_bytes(b"")
    assert cgctitles.find_rom(str(mm)).endswith("mm_10.rom")


def test_sw_state_stacked_shooter(tmp_path, monkeypatch):
    rig = tmp_path / "rig0"
    rig.mkdir()
    (rig / "state").write_text("sw 0000000000000000\nballs trough=2 shooter=2 play=0 held=\n")
    monkeypatch.setenv("CGC_ROOT", str(tmp_path))
    monkeypatch.setenv("PAD_SLOT", "0")
    assert sw.state()["balls"]["shooter"] is True


# Monster Bash (PAD-1174): its coil-name table runs 1, 2, 3, 5 ... (solenoid 4
# unused, left out), so entry n from LEFT GATE on is coil n + 1 - the ROM's
# own solenoid test shows "09 TROUGH EJECT".  Names as cgcroms reads them:
MB_COILS = ["AUTO PLUNGER", "BRIDE POST", "MUMMY COFFIN", "LEFT GATE", "RIGHT GATE",
            "KNOCKER", "RAMP LOCK POST", "TROUGH EJECT", "LEFT SLINGSHOT",
            "RIGHT SLINGSHOT", "LEFT JET", "RIGHT JET", "BOTTOM JET", "LEFT EJECT",
            "RIGHT POPPER", "FRANK. MOTOR", "UP/DN BANK MOTOR", "FRANK. RAMP POWER",
            "FRANK. RAMP HOLD", "DRAC. MTR. FORWD.", "DRAC. MTR. BCKWD.",
            "L. FLIP PROX.", "R. FLIP PROX.", "COIN METER"]
MB_SWITCHES = {"13": "START BUTTON", "18": "SHOOTER LANE", "28": "LEFT EJECT",
               "31": "TROUGH EJECT", "32": "TROUGH BALL 1", "33": "TROUGH BALL 2",
               "34": "TROUGH BALL 3", "35": "TROUGH BALL 4", "36": "RIGHT POPPER",
               "74": "DRAC. POSITION 5", "75": "DRAC. POSITION 4",
               "76": "DRAC. POSITION 3", "77": "DRAC. POSITION 2",
               "78": "DRAC. POSITION 1", "81": "UP/DN BANK UP", "82": "UP/DN BANK DOWN",
               "83": "FRANK. TABLE DOWN", "84": "FRANK. TABLE UP"}


def _mb_names():
    return {"switches": dict(MB_SWITCHES), "flippers": {},
            "coils": {str(i + 1): n for i, n in enumerate(MB_COILS)}}


def test_mb_coils_skip_solenoid_4():
    coils = cgctitles.rig_names("mb", _mb_names())["coils"]
    assert coils["1"] == "AUTO PLUNGER"
    assert coils["3"] == "MUMMY COFFIN"
    assert "4" not in coils
    assert coils["5"] == "LEFT GATE"
    assert coils["9"] == "TROUGH EJECT"
    assert coils["16"] == "RIGHT POPPER"
    assert coils["17"] == "FRANK. MOTOR"
    assert coils["25"] == "COIN METER"
    # titles without a gap keep the table's numbers
    names = {"coils": {"2": "TROUGH EJECT"}}
    assert cgctitles.rig_names("mm", names) is names


def test_mb_ball_model():
    kv = dict(p.split("=") for p in cgctitles.balls("mb", _mb_names()).split(";"))
    # the rig run (PAD-1174): serve on 9, launch on 1, the right popper an
    # opto read empty, both kickouts on their own coils, Dracula's track
    # (forward 21, backward 22) from position 1 (78) to 5 (74)
    assert kv["eject"] == "9"
    assert kv["launch"] == "1"
    assert kv["optos"] == "31,32,33,34,35,36"
    assert set(kv["holes"].split(",")) == {"36:16", "28:15"}
    assert "closed" not in kv
    assert kv["tracks"] == "21:22:78/77/76/75/74"
    assert kv["mechs"] == "18:81:82,17:83:84"


def test_ready_frames_only_where_the_rom_waits():
    assert cgctitles.TITLES["mb"]["ready_frames"] == 1800
    for key in ("mm", "afm", "cc"):
        assert "ready_frames" not in cgctitles.TITLES[key]
