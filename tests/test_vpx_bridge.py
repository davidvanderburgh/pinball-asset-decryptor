"""The Visual Pinball bridge (PAD-775): tools/spike2_emu/vpx.

What is worth failing on, none of it needing Windows, VPX or a run:

  * THE .vpx DIGEST RULE. vpxfile reproduces VPX's MD2 MAC (proven bit-for-bit
    on marty02's table on 2026-10-27); the rule it encodes is pinned here on a
    synthetic BIFF stream: the record SIZE is never hashed, the TAG is, CODE's
    payload is hashed WITHOUT its length word, ENDB ends the object. A change
    to any of these ships a table VPX refuses to load.
  * CODE IS NOT A PLAIN RECORD: [4]["CODE"][len][text]. biff_records must
    yield the script whole and biff_record must write it back the same way,
    or script() returns "" and the patcher silently patches nothing (it did).
  * A CLONED ITEM MOVES WHOLE: every VCEN in the stream (centre and drag
    points) shifts by the same delta, and NAME is replaced.
  * padled VERSION 7 (the coil rule plane) sits where padled.h says it does,
    after every older plane, and coilmap.rule() reads it.
  * THE MAP IS CONSISTENT: every number the controller derives is unique,
    every switch id is one godzilla_le has, every coil index fits a board.
  * THE PATCHER'S REWRITES on a miniature of marty02's script: the Sega
    numbers become Spike 2 ids + 1000, dropped ones become 0, the per-object
    overrides win, the solenoid block appears once, UpdateLamps is regenerated.
"""
import json
import os
import re
import struct
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMU = os.path.join(ROOT, "tools", "spike2_emu")
VPX = os.path.join(EMU, "vpx")
for p in (EMU, VPX):
    if p not in sys.path:
        sys.path.insert(0, p)

pytestmark = pytest.mark.skipif(not os.path.isdir(VPX), reason="rig not present")


@pytest.fixture(scope="module")
def vpxfile():
    return pytest.importorskip("vpxfile")


# ---------------------------------------------------------------- BIFF -----

def _code(text):
    b = text.encode("utf-8")
    return struct.pack("<I", 4) + b"CODE" + struct.pack("<I", len(b)) + b


def _rec(tag, payload):
    return struct.pack("<I", 4 + len(payload)) + tag.encode() + payload


def test_code_record_parses_whole(vpxfile):
    gd = _rec("LEFT", struct.pack("<f", 0)) + _code("Option Explicit\nDim x") + \
        _rec("SEDT", struct.pack("<i", 7)) + _rec("ENDB", b"")
    tags = [(t, p) for t, p, _ in vpxfile.biff_records(gd)]
    assert [t for t, _ in tags] == ["LEFT", "CODE", "SEDT", "ENDB"]
    code = dict(tags)["CODE"]
    assert code[4:] == b"Option Explicit\nDim x"
    assert vpxfile.biff_record("CODE", code) == _code("Option Explicit\nDim x")


def test_digest_rule_hashes_tag_payload_not_size(vpxfile):
    md2 = pytest.importorskip("Crypto.Hash.MD2")
    gd = _rec("LEFT", b"\x01\x02") + _code("abc") + _rec("ENDB", b"") + b"TRAILING JUNK"
    h = md2.new()
    vpxfile.biff_hash_update(h, gd)
    want = md2.new()
    want.update(b"LEFT" + b"\x01\x02" + b"CODE" + b"abc" + b"ENDB")
    assert h.digest() == want.digest()


def test_replace_script_keeps_other_records(vpxfile):
    gd = _rec("LEFT", b"\x01") + _code("old") + _rec("SEDT", struct.pack("<i", 3)) + _rec("ENDB", b"")
    gd2 = vpxfile.with_script(gd, "new script")
    gd3 = vpxfile.with_item_count(gd2, 40)
    tags = {t: p for t, p, _ in vpxfile.biff_records(gd3)}
    assert tags["CODE"][4:] == b"new script"
    assert struct.unpack("<i", tags["SEDT"])[0] == 40
    assert tags["LEFT"] == b"\x01"


def test_clone_item_shifts_every_vcen_and_renames(vpxfile):
    # a light with TWO drag points, each its own nested object with its own
    # ENDB, then the light's ENDB - exactly the shape that truncated the
    # first clones (VPX never finished loading them)
    item = struct.pack("<i", 7) + _rec("VCEN", struct.pack("<ff", 100, 200)) + \
        _rec("NAME", vpxfile.wide("L21")) + \
        _rec("DPNT", b"") + _rec("VCEN", struct.pack("<ff", 110, 205)) + _rec("ENDB", b"") + \
        _rec("DPNT", b"") + _rec("VCEN", struct.pack("<ff", 90, 195)) + _rec("ENDB", b"") + \
        _rec("ENDB", b"")
    out = vpxfile.clone_item(item, "PL_NEW", 300, 400)
    assert struct.unpack_from("<i", out, 0)[0] == 7
    recs = [(t, p) for t, p, _ in vpxfile.item_records(out, 4)]
    vcens = [struct.unpack("<ff", p) for t, p in recs if t == "VCEN"]
    assert vcens == [(300.0, 400.0), (310.0, 405.0), (290.0, 395.0)]
    assert [t for t, _ in recs].count("ENDB") == 3, "both points and the item close"
    assert len(out) == len(item) + (len(vpxfile.wide("PL_NEW")) - len(vpxfile.wide("L21")))
    assert vpxfile.unwide([p for t, p in recs if t == "NAME"][0]) == "PL_NEW"


# ---------------------------------------------------------------- padled v7 -

def test_rule_plane_offsets_match_padled_h():
    import coilmap
    hdr = open(os.path.join(EMU, "padled.h"), encoding="utf-8").read()
    m = re.search(r"rule_pwr (\d+), rule_in (\d+),\s*\*?\s*rule_sets (\d+)", hdr)
    assert m, "padled.h names the version-7 offsets"
    assert (coilmap.RULE_PWR_OFF, coilmap.RULE_IN_OFF, coilmap.RULE_SETS_OFF) == \
        tuple(int(x) for x in m.groups())
    assert coilmap.RULE_READ <= int(re.search(r"#define PADLED_BYTES (\d+)", hdr).group(1))
    assert coilmap.RULE_PWR_OFF >= coilmap.PAINT_READ            # after every older plane
    assert "#define PADLED_VERSION 7" in hdr


def test_rule_reads_power_and_input():
    import coilmap
    data = bytearray(coilmap.RULE_READ)
    struct.pack_into("<I", data, 0, coilmap.PADLED_MAGIC)
    struct.pack_into("<I", data, 4, 7)
    o = 8 * coilmap.COIL_N + 5                                   # node 8 coil 5
    data[coilmap.RULE_PWR_OFF + o] = 0xff
    data[coilmap.RULE_IN_OFF + o] = 0x40 | 25                    # input 25
    assert coilmap.rule(bytes(data), 8, 5) == {"power": 255, "input": 25}
    assert coilmap.rule(bytes(data), 8, 0) == {"power": 0, "input": None}
    struct.pack_into("<I", data, 4, 6)
    assert coilmap.rule(bytes(data), 8, 5) is None               # a v6 block has no plane


# ---------------------------------------------------------------- the map ---

@pytest.fixture(scope="module")
def gzmap():
    return json.load(open(os.path.join(VPX, "godzilla_le.vpxmap.json"), encoding="utf-8"))


def test_map_numbers_are_unique_and_in_range(gzmap):
    lamp_nums = []
    for sect in (gzmap["lamps"], gzmap["retrofit_lights"]["lights"]):
        for name, v in sect.items():
            if name == "_":
                continue
            node, idx = v["leds"][0]
            assert 0 <= node < 16 and 0 <= idx < 480, name
            lamp_nums.append(1000 + node * 100 + idx)
    assert len(lamp_nums) == len(set(lamp_nums)), "two lights on one LED number"
    coils = []
    for num, s in gzmap["solenoids"].items():
        if num == "_":
            continue
        node, idx = s["coil"]
        assert 1 <= int(num) <= gzmap["solenoid_max"] <= 68, "core.vbs's SolCallback(68)"
        assert 0 <= idx < 16
        coils.append((node, idx))
    assert len(coils) == len(set(coils)), "one small number per coil"
    assert {"46", "48", "36"} <= set(gzmap["solenoids"]), "core.vbs's flipper Consts"
    assert 1 <= gzmap["game_on"]["number"] <= gzmap["solenoid_max"]
    ids = {int(v) for k, v in gzmap["switch_rewrite"].items() if k != "_"}
    ids |= {int(v) for k, v in gzmap["switch_by_object"].items() if k != "_"}
    ids |= set(gzmap["switch_holds"]["trough"])
    assert all(0 <= i <= 97 for i in ids), "godzilla_le has switch ids 1..97"


def test_patcher_rewrites_a_miniature(gzmap):
    patch = pytest.importorskip("patch_godzilla")
    mini = "\n".join([
        'On Error Resume Next',
        'ExecuteGlobal GetTextFile("controller.vbs")',
        'If Err Then MsgBox "You need the controller.vbs in order to run this table"',
        'Const cGameName="godzilla",UseSolenoids=1,UseLamps=0,UseGI=0, SCoin="coin"',
        'LoadVPM "01000000","SEGA.VBS",3.10',
        ' SolCallBack(1) = "SolRelease"',
        'SolCallback(3) = "solTopMagnet"',
        '',
        'SolCallback(sLRFlipper) = "SolRFlipper"',
        'Sub SolRelease(Enabled)',
        '\tbsTrough.ExitSol_On',
        '\tvpmTimer.PulseSw 15',
        'End Sub',
        'Sub sw17_hit:vpmTimer.pulseSw 17 : playsound"targethaut" : End Sub',
        'Sub sw41_Hit : Controller.Switch(41)=1 : End Sub',
        'Sub sw62_Spin:vpmTimer.PulseSw 62 : End Sub',
        'Sub RightSlingShot_Slingshot',
        '\tvpmTimer.PulseSw 62',
        'End Sub',
        'Sub Bumper2_Hit : vpmTimer.PulseSw(50) : End Sub',
        'Sub K9_hit()',
        'k9.destroyball',
        'end Sub',
        'sub timer009_timer',
        '\tTimer009.enabled=0',
        'end Sub',
        'Dim LampState(200), FadingLevel(200)',
        'Dim FlashSpeedUp(200), FlashSpeedDown(200), FlashMin(200), FlashMax(200), FlashLevel(200)',
        'Sub UpdateLamps',
        ' NFadeL 1, l1',
        'End Sub',
        '\t\tbsTrough.InitSw 0,14,13,12,11,0,0,0',
        '\t\tbsTrough.Balls = 4',
        '\t\tbsTrough.InitExitSnd SoundFX("ballrelease",DOFContactors), SoundFX("Solenoid",DOFContactors)',
        '\t\tmTopMagnet.Solenoid = 3',
        'Set mMagnaSave2 = New cvpmMagnet : With mMagnaSave2',
        '\t.InitMagnet Magna2, 15',
        'End With',
        'Sub Table1_KeyDown(ByVal KeyCode)',
        '\tIf KeyCode=PlungerKey Then Controller.Switch(53)=1',
        'End Sub',
    ])
    out, rep = patch.patch_script(mini, gzmap)
    assert 'GetTextFile("PADSPIKE2.vbs")' in out and "SEGA.VBS" not in out
    assert 'cGameName="godzilla_le",UseSolenoids=2' in out
    assert out.count("PAD: Spike 2 coils") == 1
    assert 'SolCallback(1) = "SolRelease"' in out and "solTopMagnet" not in out
    assert 'SolCallback(sLLFlipper) = "SolLFlipper"' in out
    assert "PulseSw 15" not in out                       # the trough switches say it
    assert "pulseSw 1078" in out                         # sw17 -> PWRLINE LEFT TGT
    assert "Controller.Switch(0)=1" in out               # sw41: no Stern switch
    assert "Sub sw62_Spin:vpmTimer.PulseSw 1085" in out  # by object: TOP SPINNER
    assert "\tvpmTimer.PulseSw 1063\n" in out            # right slingshot, not 62
    assert "PulseSw(1049)" in out                        # the pop bumper
    assert "Controller.Switch(1034)=1" in out            # launch = Action Button
    assert "bsScoop.AddBall Me" in out and "k9.destroyball" not in out
    assert "timer009" not in out.lower().replace("timer009.enabled", "")
    assert "InitSw 0,1071,1070,1069,1068,1067,1066,1072" in out
    assert "bsTrough.Balls = 6" in out
    assert "mTopMagnet.Solenoid = 0" in out
    assert "NFadeL 1939, L1    ' TANKS" in out and " NFadeL 1, l1" not in out
    assert "Dim LampState(3000), FadingLevel(3000)" in out
    assert "FlashSpeedUp(3000), FlashSpeedDown(3000), FlashMin(3000), FlashMax(3000), FlashLevel(3000)" in out
    assert "(200)" not in out
    assert "mMechaMagnet.Solenoid = 6" in out and ".Solenoid = 5   ' GODZILLA MAGNET" in out
    assert out.count("End Sub") + out.count("end Sub") == \
        len(re.findall(r"(?im)^\s*(?:public |private )?sub\s", out)), "every Sub closes once"


# ----------------------------------------------- the shadow patcher -----
#
# A scripted tribute (Rush, Foo Fighters) keeps its whole script as a shadow
# game; vpxshadow.py renames its event subs, generates the bridge, neuters its
# ball creation and makes PinUP Player optional. What matters is pinned on a
# miniature of such a script.

MINI_TRIBUTE = """Option Explicit
Dim PuPlayer, bBallInPlungerLane
Sub Table1_Init
    Set PuPlayer = CreateObject("PinUpPlayer.PinDisplay")
    PuPlayer.B2SInit "", "rush"
    PuPlayer.LabelSet 1, "Title", "x", 1, ""
    BallRelease.CreateBall
    BallRelease.Kick 90, 4
End Sub
Sub Table1_KeyDown(ByVal keycode)
    If keycode = LeftFlipperKey And bGameInPlay Then SolLFlipper 1
End Sub
Sub Table1_KeyUp(ByVal keycode) : End Sub
Sub SolLFlipper(Enabled) : LeftFlipper.RotateToEnd : End Sub
Sub SolRFlipper(Enabled) : RightFlipper.RotateToEnd : End Sub
Sub Drain_Hit : PlungerIM.AutoFire : End Sub
Sub Trigger1_Hit : bBallInPlungerLane = True : End Sub
Sub sw001_Hit : AddScore 100 : End Sub
Sub LeftSlingShot_Slingshot : AddScore 10 : End Sub
Sub Kicker1_Hit : AddScore 500 : End Sub
"""

MINI_SHADOW = {
    "title": "rush_le",
    "cabinet": {"start": 1036, "launch": 1034, "launch_key": "LockBarKey",
                "left_flipper": 1065, "right_flipper": 1064, "up_right_flipper": 1066, "coin": 1039},
    "keys_skip_orig": ["StartGameKey", "AddCreditKey", "LockBarKey"],
    "switches": {"sw001": {"id": 53, "event": "hit"},
                 "LeftSlingShot": {"id": 69, "event": "slingshot"},
                 "Spinner": {"id": 83, "event": "spin"},
                 "Opto1": {"id": 85, "event": "hold"}},
    "plunger": {"lane_trigger": "Trigger1", "lane_switch": 67, "autoplunge": "plungerIM"},
    "trough": {"release": "BallRelease", "drain": "Drain",
               "switches": [76, 75, 74, 73, 72, 71, 77], "balls": 6, "kick": [90, 4]},
    "saucers": {"Kicker1": {"switch": 78, "dir": 190, "power": 15, "kickz": 1.4}},
    "solenoids": {"1": {"coil": [8, 1], "name": "TROUGH", "callback": "bsTrough.SolOut"},
                  "2": {"coil": [8, 4], "name": "AUTO PLUNGER", "callback": "PadAutoPlunge"},
                  "3": {"coil": [9, 1], "name": "SIDE SCOOP", "callback": "bsKicker1.SolOut"},
                  "7": {"coil": [8, 6], "name": "UP POST", "callback": None}},
    "pup_stub": True,
    "neuter": ["BallRelease.CreateBall", "BallRelease.Kick", "PlungerIM.AutoFire"],
}


@pytest.fixture(scope="module")
def shadow():
    vs = pytest.importorskip("vpxshadow")
    text, rep = vs.patch(MINI_TRIBUTE, json.loads(json.dumps(MINI_SHADOW)))
    return text, rep


def test_shadow_keeps_the_original_subs_behind_the_bridge(shadow):
    out, rep = shadow
    assert "Sub Table1_Init_orig" in out and "\tTable1_Init_orig" in out
    assert "Sub sw001_Hit_orig" in out
    assert "Sub sw001_Hit : vpmTimer.PulseSw 1053 : sw001_Hit_orig : End Sub" in out
    assert "Sub LeftSlingShot_Slingshot : vpmTimer.PulseSw 1069 : LeftSlingShot_Slingshot_orig : End Sub" in out
    assert "Sub Spinner_Spin : vpmTimer.PulseSw 1083 : End Sub" in out      # no original to call
    assert "Sub Opto1_Hit : Controller.Switch(1085) = True : End Sub" in out
    assert "Sub Opto1_UnHit : Controller.Switch(1085) = False : End Sub" in out
    assert out.count("End Sub") == len(re.findall(r"(?im)^\s*(?:public |private )?sub\s", out)), \
        "every Sub closes once"


def test_shadow_neuters_the_tributes_own_balls(shadow):
    out, rep = shadow
    assert "'PAD neutered: BallRelease.CreateBall" in out
    assert "'PAD neutered: BallRelease.Kick 90, 4" in out
    assert "Sub Drain_Hit_orig : If False Then PlungerIM.AutoFire : End Sub" in out   # one-liner kept whole
    assert "Sub PadAutoPlunge(e) : If e Then plungerIM.AutoFire : End If : End Sub" in out
    assert "neutered 3 line(s)" in " ".join(rep)
    assert "Sub Drain_Hit\n\tbsTrough.AddBall Me" in out
    assert "bsTrough.InitSw 0,1076,1075,1074,1073,1072,1071,1077" in out
    assert "bsTrough.InitKick BallRelease, 90, 4" in out
    assert "bsKicker1.InitSaucer Kicker1, 1078, 190, 15" in out and "bsKicker1.KickZ = 1.4" in out
    assert "Sub Kicker1_Hit : bsKicker1.AddBall Me" in out and "Sub Kicker1_Hit_orig" in out
    assert "Sub Trigger1_Hit : Controller.Switch(1067) = True : Trigger1_Hit_orig : End Sub" in out
    assert "Sub Trigger1_UnHit : Controller.Switch(1067) = False : End Sub" in out


def test_shadow_flippers_are_the_machines_coils(shadow):
    # JP's and drhotwing's tables flip from the keyboard only while THEIR game
    # is in play, which it never is: the machine's flipper coils call the
    # table's own flipper subs, and the keys stop reaching the shadow game.
    out, rep = shadow
    assert 'SolCallback(sLLFlipper) = "SolLFlipper"' in out
    assert 'SolCallback(sLRFlipper) = "SolRFlipper"' in out
    assert "sURFlipper" not in out                          # the table has no such sub
    assert "Case StartGameKey, AddCreditKey, LockBarKey, LeftFlipperKey, RightFlipperKey" in out
    assert "If KeyCode = RightFlipperKey Then Controller.Switch(1064) = True" in out
    assert "If KeyCode = RightFlipperKey Then Controller.Switch(1066) = True" in out
    assert "If KeyCode = LockBarKey Then Controller.Switch(1034) = True" in out
    assert "If KeyCode = LockBarKey Then Controller.Switch(1034) = False" in out
    assert "If KeyCode = AddCreditKey Then vpmTimer.PulseSw 1039" in out
    assert "Sub Table1_Init_orig" in out and "Table1_KeyDown_orig KeyCode" in out
    assert 'SolCallback(1) = "bsTrough.SolOut"' in out and "SolCallback(7)" not in out
    assert "Const UseSolenoids = 1, UseLamps = 0, UseGI = 0, UsePdbLeds = 0" in out


def test_shadow_makes_pinup_player_optional(shadow):
    out, rep = shadow
    assert "Class PadNoPuP" in out
    assert "Public Sub B2SInit(a0, a1) : End Sub" in out
    assert "Public Sub LabelSet(a0, a1, a2, a3, a4) : End Sub" in out
    i = out.index('CreateObject("PinUpPlayer.PinDisplay")')
    assert "On Error Resume Next" in out[i - 60:i]
    assert "Set PuPlayer = New PadNoPuP" in out[i:i + 200]


def test_shadow_flipper_subs_are_found_whole_word_only():
    vs = pytest.importorskip("vpxshadow")
    lines = ["Sub SolLFlipperX(e)", "  Private Sub SolRFlipper (Enabled) ' x", "Function SolURFlipper()"]
    assert not vs.has_sub(lines, "SolLFlipper")
    assert vs.has_sub(lines, "SolRFlipper") and vs.has_sub(lines, "SolURFlipper")
    had = {"SolRFlipper": True, "SolURFlipper": True}
    assert vs.flipper_subs({}, had) == {"sLRFlipper": "SolRFlipper", "sURFlipper": "SolURFlipper"}
    assert vs.flipper_subs({"flippers": {"_": "x", "sLLFlipper": "MyFlipL"}}, had) == {"sLLFlipper": "MyFlipL"}


def test_shadow_lamps_drive_the_tables_lights():
    # with `lamps` the machine lights the table: a dictionary from the lamp
    # number (1000 + node*100 + index, the FIRST LED of an RGB insert) to the
    # table lights, filled from ChangedLamps every tick; the tribute's own
    # light shows are quieted and its hit subs stay out of the way
    vs = pytest.importorskip("vpxshadow")
    m = json.loads(json.dumps(MINI_SHADOW))
    m["lamps"] = {"_": "x",
                  "L1": {"leds": [[9, 59]], "name": "(R)USH TARGET"},
                  "L2": {"leds": [[8, 32], [8, 33], [8, 34]], "name": "SHOOT ME LEFT ORBIT"},
                  "gi1": {"leds": [[8, 1]], "name": "BOTTOM GI"},
                  "gi2": {"leds": [[8, 1]], "name": "BOTTOM GI"}}
    m["quiet_subs"] = ["LightEffect", "NoSuchSub"]
    m["orig_hits"] = False
    m["orig_keep"] = ["LeftSlingShot"]
    m["_lightseqs"] = ["LightSeqAttract"]
    script = MINI_TRIBUTE + "Sub LightEffect(n)\n    LightSeqInserts.Play SeqRandom\nEnd Sub\n"
    out, rep = vs.patch(script, m)
    assert 'PadLamps.Add "1959", Array(L1)' in out
    assert 'PadLamps.Add "1832", Array(L2)' in out                 # the first LED names the insert
    assert 'PadLamps.Add "1801", Array(gi1, gi2)' in out           # several lights on one LED
    assert "\tLightSeqAttract.StopPlay\n\tPadLampsInit\n\tSet LampCallback = GetRef(\"PadUpdateLamps\")" in out
    assert "chg = Controller.ChangedLamps" in out and "o.State = chg(ii, 1)" in out
    assert "Sub LightEffect_orig(n)" in out and "Sub LightEffect(n) : End Sub" in out
    assert any("NoSuchSub" in r for r in rep)
    assert "Sub sw001_Hit : vpmTimer.PulseSw 1053 : End Sub" in out               # no _orig: its rules are quiet
    assert "Sub LeftSlingShot_Slingshot : vpmTimer.PulseSw 1069 : LeftSlingShot_Slingshot_orig : End Sub" in out
    assert "Sub PadDumpLamps(path)" in out and 'If parts(0) = "lamps" Then PadDumpLamps parts(1)' in out
    assert out.count("End Sub") == len(re.findall(r"(?im)^\s*(?:public |private )?sub\s", out))


@pytest.mark.parametrize("title", ["rush_le", "foo_fighters_le"])
def test_shadow_maps_are_consistent(title):
    vs = pytest.importorskip("vpxshadow")
    path = os.path.join(VPX, title + ".shadow.json")
    if not os.path.exists(path):
        pytest.skip("no map")
    m = json.load(open(path, encoding="utf-8"))
    assert m["title"] == title and m["output"].endswith(".vpx")
    cab = m["cabinet"]
    ids = [v - 1000 for k, v in cab.items() if isinstance(v, int)]
    assert all(1 <= i < 1000 for i in ids) and len(set(ids)) == len(ids), "cabinet switches"
    sw = [s["id"] for k, s in m["switches"].items() if k != "_"]
    sw += m["trough"]["switches"] + [s["switch"] for k, s in m["saucers"].items() if k != "_"]
    if m.get("plunger"):
        sw.append(m["plunger"]["lane_switch"])
    sw += ids
    assert len(set(sw)) == len(sw), "a switch id named twice: %s" % sorted(i for i in sw if sw.count(i) > 1)
    assert all(1 <= i < 1000 for i in sw)
    assert len(m["trough"]["switches"]) == 7, "TROUGH 1..6 + JAM"
    nums = [int(n) for n in m["solenoids"] if n != "_"]
    assert len(set(nums)) == len(nums) and max(nums) <= m.get("solenoid_max", 68)
    coils = [tuple(s["coil"]) for n, s in m["solenoids"].items() if n != "_"]
    assert len(set(coils)) == len(coils), "a coil named twice"
    assert all(8 <= n <= 15 and 0 <= i <= 15 for n, i in coils)
    g = m["game_on"]
    assert g["number"] not in nums and g["number"] <= m.get("solenoid_max", 68)
    assert all(tuple(c) in coils for c in g["coils"]), "game_on names the flipper coils"
    for ev in (s.get("event", "hit") for k, s in m["switches"].items() if k != "_"):
        assert ev in ("hit", "hold", "spin", "slingshot")
    # every coil callback is something the generated script defines
    extra = m.get("extra_vbs", "")
    saucers = {k for k in m["saucers"] if k != "_"}
    for n, s in m["solenoids"].items():
        cb = s.get("callback") if n != "_" else None
        if not cb:
            continue
        if cb == "bsTrough.SolOut" or cb == "PadAutoPlunge":
            continue
        if cb.startswith("bs") and cb.endswith(".SolOut"):
            assert cb[2:-7] in saucers, cb
        else:
            assert re.search(r"(?i)\bSub\s+%s\b" % re.escape(cb), extra), "%s has no Sub" % cb
    # every lamp names LEDs on a board, one table light per entry
    lamps = m.get("lamps", {})
    for name, v in lamps.items():
        if name == "_":
            continue
        assert all(0 <= n <= 15 and 0 <= i < 200 for n, i in v["leds"]), name
        assert len(v["leds"]) in (1, 3), "%s: one LED or an RGB triple" % name
    had = {k: False for k in ("Table1_Init", "Table1_KeyDown", "Table1_KeyUp", "Table1_Exit")}
    out = vs.gen(m, had)
    assert "None" not in out and "Sub Table1_Init\n" in out
