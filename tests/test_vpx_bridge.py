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
import shutil
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


B2S_TRIBUTE = """Option Explicit
ExecuteGlobal GetTextFile("controller.vbs")
Sub Table1_Init : LoadEM : End Sub
Sub Table1_Exit : If B2SOn Then Controller.Stop
End Sub
Sub Lights : If B2SOn Then Controller.B2SSetData 50, 1 : B2SController.B2SSetData 9, 1
End Sub
"""


def test_shadow_keeps_dof_on_the_b2s_server():
    # PAD-841: LoadEM puts B2S.Server in Controller; Table1_Init then gives
    # Controller to PAD.Controller, and every DOF event (controller.vbs's DOF
    # sub, the table's own B2SSetData) went to PAD instead of B2S.
    vs = pytest.importorskip("vpxshadow")
    m = json.loads(json.dumps(MINI_SHADOW))
    out, rep = vs.patch(B2S_TRIBUTE, m)
    assert 'ExecuteGlobal PadB2SText(GetTextFile("controller.vbs"))' in out
    assert "PadB2SCtl.B2SSetData 50, 1 : B2SController.B2SSetData 9, 1" in out
    assert "If B2SOn Then Controller.Stop" in out        # Stop/Pause stay PAD's
    i = out.index("If Not Controller Is Nothing Then Set PadB2S = Controller")
    assert i < out.index('Set Controller = CreateObject("PAD.Controller")')
    assert "If IsObject(PadB2S) Then PadB2S.Stop" in out
    assert "1 call(s) in the script, and controller.vbs's" in " ".join(rep)
    assert out.count("End Sub") == len(re.findall(r"(?im)^\s*(?:public |private )?sub\s", out))


@pytest.mark.skipif(not (sys.platform == "win32" and shutil.which("cscript")),
                    reason="runs the generated VBScript under cscript")
def test_shadow_dof_reaches_b2s_under_vbscript(tmp_path):
    # the generated helpers and Init swap, run for real: a controller.vbs
    # shaped DOF sub, loaded through PadB2SText, must reach the B2S server
    vs = pytest.importorskip("vpxshadow")
    out, _ = vs.patch(B2S_TRIBUTE, json.loads(json.dumps(MINI_SHADOW)))
    lines = out.split("\n")
    a = lines.index("Dim PadB2S")
    b = next(n for n in range(a, len(lines)) if lines[n].startswith("End Function")
             and "PadB2SText" in "".join(lines[a:n]))
    helpers = "\n".join(lines[a:b + 1])
    k = out.index("\tOn Error Resume Next\n\tIf IsObject(Controller)")
    swap = out[k:out.index("\tController.GameName", k)]
    lib = ('Dim Controller, B2SController, B2SOn\\n'
           'Sub LoadEM : Set Controller = New FakeB2S : Controller.B2SName = "x" : B2SOn = True : End Sub\\n'
           'Sub DOF(e, s)\\nIf B2SOn Then\\nIf s = 2 Then\\n'
           'Controller.B2SSetData e, 1:Controller.B2SSetData e, 0\\nElse\\n'
           'Controller.B2SSetData e, s\\nEnd If\\nEnd If\\nEnd Sub')
    vbs = tmp_path / "t.vbs"
    vbs.write_text("\n".join([
        "Class FakeB2S", "Public Log",
        "Public Property Let B2SName(v) : Log = Log & \"name \" : End Property",
        "Public Sub B2SSetData(a, b) : Log = Log & a & \"=\" & b & \" \" : End Sub", "End Class",
        "Class FakePad", "Public Sub B2SSetData(a, b) : WScript.Echo \"PAD got \" & a : End Sub", "End Class",
        "Function CreateObject(p) : Set CreateObject = New FakePad : End Function",
        helpers,
        "ExecuteGlobal PadB2SText(Replace(\"%s\", \"\\n\", vbNewLine))" % lib.replace('"', '""'),
        "Sub PadSwap", swap, "End Sub",
        "LoadEM : PadSwap : DOF 101, 1 : DOF 110, 2",
        "WScript.Echo \"B2S got \" & PadB2S.Log"]), encoding="latin-1")
    import subprocess
    r = subprocess.run(["cscript", "//nologo", str(vbs)], capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "B2S got name 101=1 110=1 110=0", r.stdout + r.stderr


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
    assert "PadLampState(k) = chg(ii, 1)" in out and "If PadTick Mod 5 = 0 Then PadReassertLamps" in out
    assert out.count("End Sub") == len(re.findall(r"(?im)^\s*(?:public |private )?sub\s", out))


def test_board_run_takes_the_newest_run_of_a_title(tmp_path, monkeypatch):
    # a library sweep had foo_fighters_le up on another slot while the
    # table's own run came up: the title alone named the wrong rig
    pc = pytest.importorskip("padcontroller")
    monkeypatch.setattr(pc, "BOARD", str(tmp_path))
    runs = [{"emu": "spike2", "slot": 2, "game": "foo_fighters_le", "started": 100},     # a sweep's: no hidden flag
            {"emu": "spike2", "slot": 4, "game": "foo_fighters_le", "hidden": True, "started": 200},
            {"emu": "spike2", "slot": 5, "game": "rush_le", "hidden": False, "started": 300}]
    for r in runs:
        (tmp_path / ("slot-%d.run" % r["slot"])).write_text(json.dumps(r), encoding="utf-8")
    assert pc.Rig.board_run("foo_fighters_le")["slot"] == 4          # the newest, hidden or not
    assert pc.Rig.board_run("rush_le")["slot"] == 5
    assert pc.Rig.board_run("godzilla_le") is None                    # several runs, none of it


def test_the_users_own_map_is_found_first(tmp_path, monkeypatch):
    pc = pytest.importorskip("padcontroller")
    monkeypatch.setattr(pc, "USER_MAPS", str(tmp_path))
    assert pc.VpxMap("nosuchtitle").path is None
    (tmp_path / "nosuchtitle.shadow.json").write_text(json.dumps(
        {"solenoids": {"1": {"coil": [8, 1]}}, "cabinet": {"start": 1036}}), encoding="utf-8")
    m = pc.VpxMap("nosuchtitle")
    assert m.path and m.solenoids[1] == (8, 1) and m.cabinet["start"] == 1036
    assert pc.VpxMap("rush_le").path.endswith("rush_le.shadow.json")       # the kit's own still answer


def test_lcd_window_goes_where_the_kit_says():
    # Visual Pinball comes up full screen: the game's LCD window is put on
    # top, in the upper middle of the main screen by default, or on the
    # monitor / at the rectangle the kit names
    pc = pytest.importorskip("padcontroller")
    mons = [(0, 0, 2560, 1440), (2560, 0, 4480, 1080)]
    assert pc.lcd_rect(None, mons) == (768, 0, 1024, 576)              # 40% wide, 16:9, centred
    assert pc.lcd_rect({"monitor": 2}, mons) == (2560, 0, 1920, 1080)
    assert pc.lcd_rect({"monitor": 9}, mons) == (768, 0, 1024, 576)     # no such screen: the default
    assert pc.lcd_rect({"x": 10, "y": 20, "w": 300, "h": 200, "topmost": False}, mons) == (10, 20, 300, 200)
    assert pc.lcd_rect({}, []) == (576, 0, 768, 432)                     # no monitor answer: 1920x1080 assumed


def test_board_slot_reads_one_record(tmp_path, monkeypatch):
    pc = pytest.importorskip("padcontroller")
    monkeypatch.setattr(pc, "BOARD", str(tmp_path))
    assert pc.Rig.board_slot(3) is None                                  # watch.sh has not written it
    (tmp_path / "slot-3.run").write_text('{"slot": 3, "game": "rush_le"}', encoding="utf-8")
    assert pc.Rig.board_slot(3) is None                                  # no root yet: not a run
    (tmp_path / "slot-3.run").write_text(
        '{"slot": 3, "game": "rush_le", "root": "/home/pad/padslots/3/root", "distro": "PAD-Runtime"}',
        encoding="utf-8")
    rig = pc.Rig("rush_le", record=pc.Rig.board_slot(3))
    assert rig.slot == 3 and rig.distro == "PAD-Runtime" and "padslots" in rig.dump


# ------------------------------------------------- the launcher + kit -----

def test_launcher_finds_the_card_env_then_kit_then_library(tmp_path, monkeypatch):
    pl = pytest.importorskip("padlaunch")
    monkeypatch.setattr(pl, "KIT", str(tmp_path / "kit.json"))
    monkeypatch.delenv("PAD_VPX_CARD", raising=False)
    monkeypatch.delenv("PAD_VPX_LIBRARY", raising=False)
    assert pl.card_for("rush_le") is None
    lib = tmp_path / "lib"
    lib.mkdir()
    for n in ("rush_le-1_18_0.Release.16G.sdcard.raw", "rush_le-1_19_0.Release.16G.sdcard.raw",
              "rush_pro-1_19_0.Release.16G.sdcard.raw", "rush_le-1_9_0.Release.16G.sdcard.raw"):
        (lib / n).write_bytes(b"x")
    monkeypatch.setenv("PAD_VPX_LIBRARY", str(lib))
    assert pl.card_for("rush_le").endswith("rush_le-1_19_0.Release.16G.sdcard.raw")   # newest, 1.19 > 1.9
    assert pl.card_for("foo_fighters_le") is None
    mine = tmp_path / "my_rush.raw"
    mine.write_bytes(b"x")
    pl.remember_card("rush_le", str(mine))                              # the kit beats the library
    assert pl.card_for("rush_le") == str(mine)
    assert pl.kit_load()["cards"]["rush_le"] == str(mine)
    monkeypatch.setenv("PAD_VPX_CARD", str(lib / "rush_le-1_18_0.Release.16G.sdcard.raw"))
    assert pl.card_for("rush_le").endswith("1_18_0.Release.16G.sdcard.raw")   # the env beats both
    assert pl._version_key("x-1_19_0.raw") == (1, 19, 0) and pl._version_key("x.raw") == (0, 0, 0)


def test_launcher_run_is_visible_audible_and_without_the_rigs_playfield(tmp_path, monkeypatch):
    pl = pytest.importorskip("padlaunch")
    monkeypatch.setattr(pl, "KIT", str(tmp_path / "kit.json"))
    monkeypatch.setattr(pl, "win_python", lambda: None)
    la = pl.Launch("rush_le", "/mnt/d/cards/rush_le-1_19_0.raw", dist="PAD-Runtime")
    la.slot = 4
    env = la.env()
    assert "PAD_SLOT=4" in env and "PAD_LABEL=PAD-VPX" in env
    assert "PAD_HIDDEN=0" in env and "PAD_AUDIO=1" in env and "PAD_PLAYFIELD=0" in env
    assert "PAD_CARD=/mnt/d/cards/rush_le-1_19_0.raw" in env
    assert pl.wsl_head("PAD-Runtime", root=True) == ["wsl.exe", "-d", "PAD-Runtime", "-u", "root"]
    monkeypatch.setattr(pl, "account", lambda d=None: ("pad", "/home/pad"))
    head, root = la.head()
    assert root and head[:7] == ["wsl.exe", "-d", "PAD-Runtime", "-u", "root", "-e", "env"]
    assert "HOME=/home/pad" in head and "PAD_PIVOT=1" in head
    monkeypatch.setattr(pl, "account", lambda d=None: ("root", ""))
    head, root = la.head()
    assert not root and "-u" not in head


def test_launcher_takes_its_rig_as_root_on_the_apps_board(tmp_path, monkeypatch):
    """PAD-803: the take ran as the plain user on the board riglock.sh guessed
    from an installed rig (the Linux home's ~/.pad-rig, root's after the app's
    runs), and refused with every slot free. It runs as root, like the run,
    and every rig command names the board the app and the controller read."""
    pl = pytest.importorskip("padlaunch")
    monkeypatch.setattr(pl, "KIT", str(tmp_path / "kit.json"))
    monkeypatch.setattr(pl, "win_python", lambda: None)
    monkeypatch.setattr(pl, "account", lambda d=None: ("pad", "/home/pad"))
    monkeypatch.setattr(pl, "app_home", lambda d: "/mnt/wsl/paddata/spike2")
    monkeypatch.setattr(pl.padpath, "to_wsl", lambda p: "/mnt/c/Users/me/.pad-rig")
    calls = []

    class R:
        returncode, stdout, stderr = 0, b"slot=3\n", b""

    monkeypatch.setattr(pl, "_run", lambda cmd, timeout=60: calls.append(cmd) or R())
    la = pl.Launch("foo_fighters__le", "/mnt/d/cards/ff.raw", dist="PAD-Runtime")
    assert la.take_slot() == 3
    cmd = calls[0]
    assert cmd[:7] == ["wsl.exe", "-d", "PAD-Runtime", "-u", "root", "-e", "env"]
    assert "HOME=/home/pad" in cmd and "PAD_HOME=/mnt/wsl/paddata/spike2" in cmd
    if sys.platform == "win32":
        assert "PAD_BOARD=/mnt/c/Users/me/.pad-rig" in cmd
        assert "PAD_BOARD=/mnt/c/Users/me/.pad-rig" in la.env()
    assert cmd[-4:] == ["take", "--any", "PAD-VPX", "foo_fighters__le for Visual Pinball"]
    assert "PAD_HOME=/mnt/wsl/paddata/spike2" in la.env()
    # riglock's own last words come back whole, not cut to the slot table
    R.returncode, R.stdout = 1, b""
    R.stderr = (b"x" * 400) + b"\nriglock: cannot write the board at /home/pad/.pad-rig"
    la.slot = None
    with pytest.raises(RuntimeError, match="cannot write the board"):
        la.take_slot()


def test_launcher_says_wsl_is_missing_not_no_rig_slot(tmp_path, monkeypatch):
    """PAD-806: on a PC with no WSL, Play opened the table and the launcher
    came back with "no rig slot free for foo_fighters_le", which reads like a
    game already running. The registry says there is no Linux before any
    wsl.exe is asked, and the launch and Play both say that instead."""
    pl = pytest.importorskip("padlaunch")
    vs = pytest.importorskip("vpxsetup")
    monkeypatch.setattr(pl, "KIT", str(tmp_path / "kit.json"))
    calls = []
    monkeypatch.setattr(pl, "_run", lambda cmd, timeout=60: calls.append(cmd))
    monkeypatch.setattr(pl, "registered", lambda: [])
    assert pl.no_linux() == pl.no_linux("PAD-Runtime") == pl.NO_LINUX
    assert "WSL is not installed" in pl.NO_LINUX and "slot" not in pl.NO_LINUX
    la = pl.Launch("foo_fighters_le", "/mnt/d/cards/ff.raw", dist=None)
    with pytest.raises(RuntimeError, match="WSL is not installed"):
        la.start()
    assert calls == [] and la.slot is None              # no wsl.exe, no slot taken
    # Play refuses before Visual Pinball opens the table
    vp = tmp_path / "vp"
    (vp / "tables").mkdir(parents=True)
    (vp / "tables" / "Foo (PAD).vpx").write_bytes(b"x")
    monkeypatch.setattr(vs, "find_vpx", lambda: str(vp))
    monkeypatch.setattr(pl, "distro", lambda: None)
    opened = []
    monkeypatch.setattr(vs.subprocess, "Popen", lambda *a, **k: opened.append(a))
    assert vs.open_table("Foo (PAD).vpx") == pl.NO_LINUX and opened == []
    # a distro the kit names that is not there is named
    monkeypatch.setattr(pl, "registered", lambda: ["Ubuntu"])
    assert "(PAD-Runtime) is not installed" in pl.no_linux("PAD-Runtime")
    assert pl.no_linux("ubuntu") == pl.no_linux(None) == ""
    assert vs.open_table("Foo (PAD).vpx") == "ok" and len(opened) == 1
    # the registry unreadable (or not Windows): nothing refused on a guess
    monkeypatch.setattr(pl, "registered", lambda: None)
    assert pl.no_linux("PAD-Runtime") == ""


def test_launcher_reads_no_distros_from_a_failing_wsl_list(monkeypatch):
    """With no WSL, `wsl -l -q` exits non-zero and prints its complaint;
    those lines are not distro names."""
    pl = pytest.importorskip("padlaunch")

    class R:
        returncode = -1
        stdout = "Windows Subsystem for Linux has no installed distributions.\r\n".encode("utf-16-le")

    monkeypatch.setattr(pl.subprocess, "run", lambda *a, **k: R())
    assert pl.distros() == []
    R.returncode, R.stdout = 0, "Ubuntu\r\nPAD-Runtime\r\n".encode("utf-16-le")
    assert pl.distros() == ["Ubuntu", "PAD-Runtime"]
    # and a refusal wsl.exe prints itself reads as words, not "W i n d o w s"
    assert pl._text("There is no distribution.\r\n".encode("utf-16-le")).strip() == "There is no distribution."
    assert pl._text("slot=3\n".encode()) == "slot=3\n" and pl._text(None) == ""


def test_launcher_uses_the_rigs_own_home_off_the_runtime(monkeypatch):
    pl = pytest.importorskip("padlaunch")
    assert pl.app_home("Ubuntu") == ""


def test_kit_recognises_each_supported_table(monkeypatch):
    pv = pytest.importorskip("padvpx")
    titles = pv.maps()
    assert set(titles) >= {"rush_le", "foo_fighters_le", "foo_fighters_pro", "godzilla_le"}
    assert all(t["detect"] for t in titles.values()), "every map names the words that identify its table"

    class Fake:
        def __init__(self, script):
            self._s = script

        def script(self):
            return self._s

    monkeypatch.setattr(pv.padlaunch, "card_for", lambda t: None)
    for title, words in (("rush_le", ["Rush LE ver 2.0.2 / PUP ver 2.0.0 - By DrHotWing"]),
                         ("foo_fighters_pro", ["'  JP's Foo Fighters - a tribute", "script by jpsalas - 2025"]),
                         ("godzilla_le", ["' Godzilla Limited Edition", 'ExecuteGlobal GetTextFile("SEGA.VBS")'])):
        monkeypatch.setattr(pv.vpxfile, "VpxTable", lambda p, s="\n".join(words): Fake(s))
        got, info = pv.recognise("x.vpx")
        assert got == title, (title, got)
    monkeypatch.setattr(pv.vpxfile, "VpxTable", lambda p: Fake("Option Explicit\n' some other table"))
    assert pv.recognise("x.vpx") == (None, None)


def test_jps_foo_fighters_plays_as_the_pro_unless_only_an_le_card_is_there(monkeypatch):
    """PAD-808: JP's table has no upper playfield and no Overlord magnet or
    hit coil - a Pro's playfield. Both maps fit the download; Patch takes the
    one asked for, else the one the card given is for, else the first with a
    card known, else the Pro."""
    pv = pytest.importorskip("padvpx")

    class Fake:
        def script(self):
            return "'  JP's Foo Fighters - a tribute\n' script by jpsalas - 2025"
    monkeypatch.setattr(pv.vpxfile, "VpxTable", lambda p: Fake())
    fits = [t for t, _ in pv.fitting("x.vpx")]
    assert fits == ["foo_fighters_pro", "foo_fighters_le"], "the preferred map first"
    cards = {}
    monkeypatch.setattr(pv.padlaunch, "card_for", lambda t: cards.get(t))
    assert pv.recognise("x.vpx")[0] == "foo_fighters_pro"
    cards["foo_fighters_le"] = "D:/c/foo_fighters_le-1_04_0.Release.16G.sdcard.raw"
    assert pv.recognise("x.vpx")[0] == "foo_fighters_le", "only an LE card: the LE"
    cards["foo_fighters_pro"] = "D:/c/foo_fighters_pro-1_04_0.Release.16G.sdcard.raw"
    assert pv.recognise("x.vpx")[0] == "foo_fighters_pro", "both: the Pro"
    assert pv.recognise("x.vpx", title="foo_fighters_le")[0] == "foo_fighters_le"
    assert pv.recognise("x.vpx", card="E:/foo_fighters_le-1_04_0.Release.16G.sdcard.raw")[0] \
        == "foo_fighters_le", "setup's card names the title"
    assert pv.card_title("rush_le-1_19_0.Release.16G.sdcard.raw") == "rush_le"
    assert pv.patch("x.vpx", title="rush_le") == 2, "a title whose map does not fit"


def _ff_maps():
    return [json.load(open(os.path.join(VPX, "foo_fighters_%s.shadow.json" % m), encoding="utf-8"))
            for m in ("le", "pro")]


def test_the_foo_fighters_pro_map_is_the_le_map_on_the_pros_numbers():
    """PAD-808: the Pro map was made from the LE one through both programs'
    own switch tables (swelf, 1.04.0): the same table objects on the same
    switch names, the Pro's ids (lower past each of the LE's upper
    playfield switches, which the Pro has none of), the LE-only coils gone,
    the lights as they are."""
    le, pro = _ff_maps()
    assert pro["title"] == "foo_fighters_pro" and pro["model"] == "Pro" and pro["preferred"]
    assert le["model"] == "LE" and not le.get("preferred")
    for k in ("detect", "output", "table", "game_on", "keys_skip_orig", "neuter", "extra_vbs",
              "quiet_subs", "orig_keep", "retrofit_timers"):
        assert pro[k] == le[k], k
    assert {k: v["name"] for k, v in pro["switches"].items() if k != "_"} == \
        {k: v["name"] for k, v in le["switches"].items() if k != "_"}
    for k, v in pro["switches"].items():
        if k != "_":
            assert 0 <= le["switches"][k]["id"] - v["id"] <= 3, (k, v)
    assert pro["switches"]["Target004"]["id"] == 48, "LOWER RIGHT TARGET: below every UP PF switch"
    assert pro["switches"]["Trigger003"]["id"] == 54, "LEFT OUTLANE on the Pro"
    assert pro["switches"]["LeftSlingShot"]["id"] == 65
    assert pro["switches"]["Trigger015"]["id"] == 82, "OVERLORD OPTO on the Pro"
    assert pro["trough"]["switches"] == [72, 71, 70, 69, 68, 67, 73]
    assert pro["plunger"]["lane_switch"] == 63
    assert pro["cabinet"]["left_flipper"] == 1061 and pro["cabinet"]["start"] == 1036
    gone = {v["name"] for k, v in le["solenoids"].items() if k not in pro["solenoids"]}
    assert gone == {"OUTLANE UP POST", "OVERLORD MAGNET", "OVERLORD HIT", "UP PF DIVERTER"}
    assert all(pro["solenoids"][k] == v for k, v in le["solenoids"].items() if k in pro["solenoids"])
    assert {k: v["leds"] for k, v in pro["lamps"].items() if k != "_"} ==         {k: v["leds"] for k, v in le["lamps"].items() if k != "_"}


# ------------------------------------------------ the table generator -----

MINI_TABLES = {
    "switch_list.txt": "\n".join([
        "# id   num   node  bit  name",
        "34     100   1     2    Action Button", "36     103   1     11   Start Button",
        "39     106   1     16   LEFT COIN", "38     111   1     14   TILT PENDULUM",
        "63     10    8     24   RIGHT FLIPPER BUTTON", "64     9     8     25   LEFT FLIPPER BUTTON",
        "66     22    8     28   SHOOTER LANE", "67     8     8     29   RIGHT SLINGSHOT",
        "68     7     8     30   LEFT SLINGSHOT", "70     15    8     32   TROUGH 2", "71     16    8     33   TROUGH 1",
        "72     21    8     38   TROUGH JAM", "80     40    9     8    LEFT ORBIT", "81     41    9     9    TANK TARGET",
        "82     42    9     10   LEFT POP BUMPER", "83     43    9     11   LEFT SPINNER OPTO",
        "84     44    9     12   RIGHT VUK OPTO", "85     45    9     13   CENTER 3 BANK DROP LEFT OPTO",
        "86     46    9     14   JETPACK HOME OPTO", ""]),
    "switch_xy.txt": "\n".join([
        "# id   node bit  name                                 x     y",
        "66     8     28    SHOOTER LANE                       416   859", "67     8     29    RIGHT SLINGSHOT   310   710",
        "68     8     30    LEFT SLINGSHOT                     114   710", "70     8     32    TROUGH 2   364   859",
        "71     8     33    TROUGH 1                           377   854", "72     8     38    TROUGH JAM   377   840",
        "80     9     8     LEFT ORBIT                          43   169", "81     9     9     TANK TARGET   235   271",
        "82     9     10    LEFT POP BUMPER                    305   263", "83     9     11    LEFT SPINNER OPTO   77   383",
        "84     9     12    RIGHT VUK OPTO                     388   549", "85     9     13    CENTER 3 BANK DROP LEFT OPTO 124 273",
        "86     9     14    JETPACK HOME OPTO                  234    17", ""]),
    "device_xy.txt": "\n".join([
        "# class   name                                   x     y    w    h  grp index  conn   image",
        "coil      RIGHT FLIPPER                        281   813   20   20    7     0  -      playfield",
        "coil      TROUGH                               370   858   20   20    7     1  -      playfield",
        "coil      AUTO PLUNGER                         415   872   20   20    7     4  -      playfield",
        "coil      LEFT FLIPPER                         141   813   20   20    7     5  -      playfield",
        "coil      UPPER LEFT FLIPPER                    60   432   20   20    7     6  -      playfield",
        "coil      RIGHT VUK                            389   550   20   20    8     1  -      playfield",
        "coil      CENTER 3 BANK DROP TARGET            147   258   20   20    8     4  -      playfield",
        "led       SHOOT AGAIN                          210   863   20   20    8     8  -      playfield", ""]),
    "group_node.txt": "\n".join([
        "# group node devices", "4     0    led=1 switch=12", "5     1    led=9 switch=6",
        "7     8    coil=9 led=60 switch=30", "8     9    coil=8 led=55 switch=32", ""]),
    "led_io.txt": "\n".join([
        "# node index name                                   x     y  conn  image",
        "0      0     BACKBOX GI                             0     0  -     ",
        "8      3     LEFT LANE ARROW-R                    117   356  -     playfield",
        "8      4     LEFT LANE ARROW-G                    117   356  -     playfield",
        "8      5     LEFT LANE ARROW-B                    117   356  -     playfield",
        "8      8     SHOOT AGAIN                          210   863  -     playfield",
        "8      37    BATH-O-SUB                           207   465  -     playfield",
        "9      45    BACKPANEL FLASH                      620   116  -     playfield",
        "12     0     TOPPER 1-G                            69    77  -     topper", ""]),
}


@pytest.fixture(scope="module")
def mini_tables(tmp_path_factory):
    PIL = pytest.importorskip("PIL.Image")
    d = tmp_path_factory.mktemp("tables")
    for name, text in MINI_TABLES.items():
        (d / name).write_text(text, encoding="utf-8")
    PIL.new("L", (459, 998), 40).save(str(d / "playfield.png"))
    return str(d)


def test_generator_puts_the_titles_devices_on_a_table(mini_tables):
    vg = pytest.importorskip("vpxgen")
    g = vg.Gen("james_bond_le", mini_tables)
    g.build()
    kinds = {}
    names = {}
    for d in g.items:
        kind, name, pos = vg.vpxfile.VpxTable.item_info(d)
        kinds[kind] = kinds.get(kind, 0) + 1
        names[name] = (kind, pos)
    assert kinds["Flipper"] == 3 and kinds["Plunger"] == 1
    assert kinds["Timer"] == 3 and "PulseTimer" in names, "vpmTimer runs on PulseTimer: no PulseSw without it"
    assert kinds["Bumper"] == 1 and kinds["Spinner"] == 1 and kinds["HitTarget"] == 2
    assert kinds["Light"] == 3, "an RGB triple is one light, the backpanel and topper none"
    assert "LBathOSub" in names, "a name ending in B is not a blue channel"
    assert kinds["Kicker"] == 4                                   # drain, ball release, the VUK, the test shooter
    # james_bond_le's traced geometry rides along: outline, guides, slings, ramps
    assert kinds["Ramp"] == 3 and "RightRamp" in names and "Outline" in names
    assert "LeftSling" in names and "LeftSlingshot" not in names, "the traced sling is the switch's"
    assert "JetpackHomeOpto" not in names, "a mechanism's sensor is no object"
    sx = vg.TABLE_W / 459.0
    assert abs(names["LeftFlipper"][1][0] - 141 * sx) < 0.01 and abs(names["LeftFlipper"][1][1] - 813 * sx) < 0.01
    assert abs(names["LeftPopBumper"][1][0] - 305 * sx) < 0.01
    m = g.map
    assert m["cabinet"]["start"] == 1036 and m["cabinet"]["launch"] == 1034 and m["cabinet"]["launch_key"] == "LockBarKey"
    assert m["trough"]["switches"] == [71, 70, 72], "TROUGH 1 first, the jam last"
    assert m["plunger"]["lane_switch"] == 66
    assert m["switches"]["LeftOrbit"] == {"id": 80, "event": "hit", "name": "LEFT ORBIT"}
    assert m["switches"]["LeftSpinnerOpto"]["event"] == "spin"
    assert m["switches"]["LeftSling"]["event"] == "slingshot"      # the traced sling wall
    assert m["saucers"]["RightVukOpto"]["switch"] == 84
    sols = {v["callback"]: v["coil"] for v in m["solenoids"].values() if v["callback"]}
    # the coil table's group is a place in the node directory: 7 -> node 8, 8 -> node 9
    assert sols["bsTrough.SolOut"] == [8, 1] and sols["PadAutoPlunge"] == [8, 4]
    assert sols["bsRightVukOpto.SolOut"] == [9, 1] and sols["PadResetDrops"] == [9, 4]
    assert m["game_on"]["coils"] == [[8, 5], [8, 0]]
    assert m["lamps"]["LLeftLaneArrow"]["leds"] == [[8, 3], [8, 4], [8, 5]]
    assert "Center3BankDropLeftOpto.IsDropped = 0" in m["extra_vbs"]
    script = g.script()
    assert 'Controller.GameName = "james_bond_le"' in script
    assert "Sub LeftOrbit_Hit : vpmTimer.PulseSw 1080 : End Sub" in script
    assert 'SolCallback(sLLFlipper) = "SolLFlipper"' in script and "Sub SolLFlipper(e)" in script
    assert 'PadLamps.Add "1803", Array(LLeftLaneArrow)' in script
    assert "bsTrough.InitSw 0,1071,1070,1072" in script
    assert script.count("End Sub") == len(re.findall(r"(?im)^\s*(?:public |private )?sub\s", script))


def test_generator_ramps_slings_and_guides(mini_tables):
    vg = pytest.importorskip("vpxgen")
    g = vg.Gen("james_bond_le", mini_tables)
    g.build()
    by = {vg.vpxfile.VpxTable.item_info(d)[1]: d for d in g.items}

    def fields(d):
        out = {}
        for t, p, _ in vg.vpxfile.item_records(d, 4):
            out.setdefault(t, p)
        return out

    ramp = fields(by["RightRamp"])
    # collidable (the example table's ramp is not), flat, climbing 0 -> 90
    assert struct.unpack("<i", ramp["CLDR"])[0] == 1 and struct.unpack("<i", ramp["TYPE"])[0] == 0
    assert struct.unpack("<f", ramp["HTBT"])[0] == 0 and struct.unpack("<f", ramp["HTTP"])[0] == 90
    drop = fields(by["RightRampDrop"])
    assert struct.unpack("<f", drop["HTBT"])[0] == 75 and struct.unpack("<f", drop["HTTP"])[0] == 0
    # a switch on the ramp rides it
    assert fields(by["RightRampExitOpto"])["SURF"][4:] == b"RightRamp" if "RightRampExitOpto" in by else True
    # the sling kicks OUT: its corners wound the way Visual Pinball pushes outwards
    pts = [struct.unpack_from("<ff", p, 0) for t, p, _ in vg.vpxfile.item_records(by["LeftSling"], 4) if t == "VCEN"]
    n = len(pts)
    assert sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n)) <= 0
    flags = [struct.unpack("<i", p)[0] for t, p, _ in vg.vpxfile.item_records(by["LeftSling"], 4) if t == "SLNG"]
    k = flags.index(1)
    a, b = pts[k], pts[(k + 1) % n]
    s = vg.TABLE_W / 459.0
    assert {(round(a[0] / s), round(a[1] / s)), (round(b[0] / s), round(b[1] / s))} == {(90, 672), (128, 748)}
    # the upper flipper points down from where the geometry puts it
    fl = fields(by["UpperLeftFlipper"])
    assert struct.unpack("<f", fl["ANGS"])[0] == 172 and abs(struct.unpack_from("<f", fl["VCEN"], 0)[0] - 66 * s) < 0.01
    m = g.map
    assert m["saucers"]["RightVukOpto"]["dir"] in (0.0, 180.0)
    script = g.script()
    assert "Sub PlaySoundAt(sound, obj)" in script, "the bridge's saucer and drain subs call it"
    assert 'If parts(0) = "shoot" Then' in script and "Sub PadShoot(x, y, a, s)" in script


def test_winding_and_thick_walls():
    vg = pytest.importorskip("vpxgen")
    cw = [(90, 672), (128, 748), (112, 760), (88, 738)]           # clockwise on screen
    q, s = vg.sling_winding(cw, 0)
    assert q == list(reversed(cw)) and (q[s], q[(s + 1) % 4]) == ((128, 748), (90, 672))
    q2, s2 = vg.sling_winding(q, s)
    assert q2 == q and s2 == s, "a polygon already wound the right way is kept"
    poly = vg.thick([(0, 0), (0, 100)], 10)
    assert len(poly) == 4 and {round(x) for x, _ in poly} == {-5, 5}
    bend = vg.thick([(0, 0), (0, 100), (100, 100)], 10)
    assert len(bend) == 6
    assert vg.load_geo("nosuchtitle") is None and vg.load_geo("james_bond_le")["ramps"]


def test_generator_shapes_carry_their_points():
    vg = pytest.importorskip("vpxgen")
    data = vg.set_points(vg.proto("trigger"), vg.circle(100, 200, 10, n=6))
    recs = list(vg.vpxfile.item_records(data, 4))
    pts = [struct.unpack_from("<ff", p, 0) for t, p, _ in recs if t == "VCEN"][1:]
    assert len(pts) == 6 and abs(pts[0][0] - 110) < 0.01 and abs(pts[0][1] - 200) < 0.01
    assert [t for t, _, _ in recs].count("DPNT") == 6 and recs[-1][0] == "ENDB"
    wall = vg.set_points(vg.proto("wall"), [(0, 0), (10, 0), (10, 10)], slingshot_seg=1)
    flags = [struct.unpack("<i", p)[0] for t, p, _ in vg.vpxfile.item_records(wall, 4) if t == "SLNG"]
    assert flags == [0, 1, 0]
    assert vg.ident("LEFT RAMP ENTER OPTO") == "LeftRampEnterOpto" and vg.ident("3 BANK") == "X3Bank"


@pytest.mark.parametrize("title", ["rush_le", "foo_fighters_le", "foo_fighters_pro"])
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


# ------------------------------------------------- the app's setup -----

def test_setup_reads_the_card_folder(tmp_path):
    vs = pytest.importorskip("vpxsetup")
    lib = tmp_path / "lib"
    lib.mkdir()
    for n in ("rush_le-1_19_0.Release.16G.sdcard.raw", "rush_le-1_18_0.Release.16G.sdcard.raw",
              "foo_fighters_le-1_04_0.Release.16G.sdcard.raw", "notes.txt", "godzilla_le.raw"):
        (lib / n).write_bytes(b"x")
    cards = vs.cards_in(str(lib))
    assert sorted(cards) == ["foo_fighters_le", "rush_le"] and len(cards["rush_le"]) == 2
    assert vs.cards_in(str(tmp_path / "missing")) == {}


def test_setup_names_each_known_table_and_what_is_patched(tmp_path, monkeypatch):
    """PAD-802: the app ships no table, so every map says which download it
    fits (the tab lists them), and a table counts as patched once its (PAD)
    copy is in Visual Pinball's tables folder."""
    vs = pytest.importorskip("vpxsetup")
    pl = pytest.importorskip("padlaunch")
    monkeypatch.setattr(pl, "KIT", str(tmp_path / "kit.json"))
    monkeypatch.delenv("PAD_VPX_CARD", raising=False)
    monkeypatch.delenv("PAD_VPX_LIBRARY", raising=False)
    tables = tmp_path / "tables"
    tables.mkdir()
    (tables / "Rush LE 2.0.2 (PAD).vpx").write_bytes(b"x")
    (tables / "Rush LE 2.0.2.vpx").write_bytes(b"x")
    got = {t["title"]: t for t in vs.known_tables(str(tables))}
    assert set(got) >= {"rush_le", "foo_fighters_pro", "godzilla_le"}
    for t in got.values():
        assert t["name"] and t["by"] and t["where"] and t["output"].endswith("(PAD).vpx"), t
        assert t["card"] == ""
    assert got["rush_le"]["patched"] and not got["foo_fighters_pro"]["patched"]
    # PAD-808: one row for JP's Foo Fighters, the Pro first, the LE beside it
    assert "foo_fighters_le" not in got
    ff = got["foo_fighters_pro"]
    assert ff["titles"] == ["foo_fighters_pro", "foo_fighters_le"]
    assert ff["models"] == {"foo_fighters_pro": "Pro", "foo_fighters_le": "LE"}
    assert got["rush_le"]["titles"] == ["rush_le"]
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "foo_fighters_le-1_04_0.Release.16G.sdcard.raw").write_bytes(b"x")
    monkeypatch.setenv("PAD_VPX_LIBRARY", str(lib))
    ff = {t["output"]: t for t in vs.known_tables(str(tables))}[ff["output"]]
    assert ff["title"] == "foo_fighters_le" and ff["card"].endswith("foo_fighters_le-1_04_0.Release.16G.sdcard.raw")
    assert vs.patched_in(str(tables)) == ["Rush LE 2.0.2 (PAD).vpx"]
    assert vs.patched_in(str(tmp_path / "none")) == []


def test_setup_layouts_fit_the_screens_found():
    vs = pytest.importorskip("vpxsetup")
    one = vs.layout_presets([(0, 0, 3840, 2160)])
    keys = [k for k, _, _, _ in one]
    assert keys == ["side", "centre"]
    _, _, player, lcd = one[0]
    assert player == (0, 0, 1440, 2160)              # a 2:3 playfield, full height
    assert lcd[0] == 1440 and lcd[2] == 2400 and lcd[3] == 1350    # the rest, 16:9
    two = vs.layout_presets([(0, 0, 1920, 1080), (1920, 0, 3840, 1080)])
    assert [k for k, _, _, _ in two] == ["side", "two", "centre"]
    assert two[1][3] == (1920, 0, 1920, 1080)        # the LCD fills the second screen
    assert vs.layout_presets([])[0][2][3] == 1080    # no screens known: a 1080p guess


def test_setup_layout_writes_the_kit_and_the_ini_and_reads_back(tmp_path, monkeypatch):
    vs = pytest.importorskip("vpxsetup")
    pl = pytest.importorskip("padlaunch")
    pv = pytest.importorskip("padvpx")
    monkeypatch.setattr(pl, "KIT", str(tmp_path / "kit.json"))
    ini = tmp_path / "VPinballX.ini"
    ini.write_text("[Player]\nFullScreen = 1\nWidth = 1920\n[Editor]\nX = 1\n", encoding="utf-8")
    monkeypatch.setattr(pv, "vpx_ini_path", lambda: str(ini))
    # PAD-811: a layout also saves the game display; never the real one
    pd = pytest.importorskip("padisplay")
    conf = str(tmp_path / "display.conf")
    monkeypatch.setattr(pd, "CONF", conf)
    monkeypatch.setattr(pd, "monitors", lambda: [
        {"n": 1, "x": 0, "y": 0, "w": 3840, "h": 2160, "primary": True}])
    presets = vs.layout_presets([(0, 0, 3840, 2160)])
    assert vs.layout_key(pl.kit_load(), presets) == ""
    assert vs.apply_layout("side", [0, 0, 1440, 2160], [1440, 0, 2400, 1350]).startswith("layout side")
    kit = pl.kit_load()
    assert kit["player"] == {"x": 0, "y": 0, "w": 1440, "h": 2160}
    assert kit["lcd"] == {"x": 1440, "y": 0, "w": 2400, "h": 1350, "topmost": True}
    assert vs.layout_key(kit, presets) == "side"      # the tab ticks the layout in use
    text = ini.read_text(encoding="utf-8")
    assert "FullScreen = 0" in text and "Width = 1440" in text and "Height = 2160" in text and "X = 1" in text
    # the LCD rectangle is a borderless window there
    assert pd.load(conf) == {"mode": "window", "monitor": 1, "border": False,
                             "rx": 1440, "ry": 0, "w": 2400, "h": 1350}
    vs.apply_layout("centre", None, None)                 # Visual Pinball's own place, the LCD's default
    kit = pl.kit_load()
    assert "player" not in kit and kit["lcd"] == {"topmost": True}
    assert vs.layout_key(kit, presets) == "centre"
    assert "FullScreen = 0" in ini.read_text(encoding="utf-8")
    assert pd.load(conf)["mode"] == "free"                # the kit places it, as before


def test_setup_layout_display_fills_a_monitor_or_sits_on_one():
    """PAD-811: the LCD rectangle becomes the game display setting: full
    screen on a monitor it fills, else a borderless window on the monitor
    holding its middle, at its offset there."""
    vs = pytest.importorskip("vpxsetup")
    mons = [{"n": 1, "x": 0, "y": 0, "w": 1920, "h": 1080, "primary": True},
            {"n": 2, "x": 1920, "y": 0, "w": 1920, "h": 1080, "primary": False}]
    assert vs.display_for([1920, 0, 1920, 1080], mons) == {
        "mode": "fullscreen", "monitor": 2, "border": False}
    assert vs.display_for([2000, 100, 1360, 768], mons) == {
        "mode": "window", "monitor": 2, "border": False, "rx": 80, "ry": 100, "w": 1360, "h": 768}
    # off every monitor: on the main one
    assert vs.display_for([9000, 0, 100, 100], mons)["monitor"] == 1
    assert vs.display_for(None, mons)["mode"] == "free"


def test_setup_state_reports_the_game_display(tmp_path, monkeypatch):
    vs = pytest.importorskip("vpxsetup")
    pl = pytest.importorskip("padlaunch")
    pd = pytest.importorskip("padisplay")
    monkeypatch.setattr(pl, "KIT", str(tmp_path / "kit.json"))
    monkeypatch.setattr(pd, "CONF", str(tmp_path / "display.conf"))
    monkeypatch.setattr(pd, "monitors", lambda: [
        {"n": 1, "x": 0, "y": 0, "w": 1920, "h": 1080, "primary": True}])
    monkeypatch.setattr(vs, "controller_registered", lambda: False)
    monkeypatch.setattr(vs, "vpx_tables_dir", lambda: "")
    pd.save({"mode": "fullscreen", "monitor": 1, "border": False}, pd.CONF)
    got = vs.state()["display"]
    assert got["setting"]["mode"] == "fullscreen"
    assert got["text"] == "full screen on monitor 1, borderless"


def test_setup_finds_visual_pinball_from_the_kit_first(tmp_path, monkeypatch):
    vs = pytest.importorskip("vpxsetup")
    pl = pytest.importorskip("padlaunch")
    monkeypatch.setattr(pl, "KIT", str(tmp_path / "kit.json"))
    monkeypatch.setattr(vs, "VPX_DEFAULT_DIR", str(tmp_path / "nowhere"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path / "home"))
    assert vs.find_vpx() == "" and vs.vpx_tables_dir() == ""
    mine = tmp_path / "vp"
    mine.mkdir()
    assert vs.set_vpx(str(mine)).startswith("There is no VPinballX64.exe")
    (mine / "VPinballX64.exe").write_bytes(b"x")
    assert vs.set_vpx(str(mine)) == "ok" and vs.find_vpx() == str(mine)
    assert vs.vpx_tables_dir() == os.path.join(str(mine), "tables")


def test_setup_answers_the_app_in_one_json_line(tmp_path, monkeypatch, capsys):
    """The app's tab reads the LAST line of the kit's output as JSON."""
    vs = pytest.importorskip("vpxsetup")
    pl = pytest.importorskip("padlaunch")
    monkeypatch.setattr(pl, "KIT", str(tmp_path / "kit.json"))
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "rush_le-1_19_0.Release.16G.sdcard.raw").write_bytes(b"x")
    assert vs.main(["library", str(lib)]) == 0
    got = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert got == {"result": "ok", "cards": {"rush_le": ["rush_le-1_19_0.Release.16G.sdcard.raw"]}}
    assert vs.main(["nonsense"]) == 2


def test_no_table_ships_with_the_app():
    """PAD-802: the tables are their authors' to hand out. The installer
    carries none and offers no separate setup window."""
    iss = open(os.path.join(ROOT, "installer", "pinball_decryptor.iss"), encoding="utf-8").read()
    lines = [ln for ln in iss.splitlines() if not ln.lstrip().startswith(";")]
    assert not [ln for ln in lines if "vpx_tables" in ln or "*.vpx" in ln]
    assert not [ln for ln in lines if "wizard" in ln]
    assert not os.path.exists(os.path.join(VPX, "padwizard.py"))


def test_a_slots_first_run_takes_the_titles_switch_table_from_another_slot(tmp_path):
    # PAD-811: TMNT on a slot that had never run it sat on its logo, the
    # table unable to report a trough without the run's switch_list.txt
    pc = pytest.importorskip("padcontroller")
    slots = tmp_path / "padslots"
    old = slots / "3" / "root" / "dump" / "tables" / "turtles_le"
    old.mkdir(parents=True)
    (old / "switch_list.txt").write_text("# turtles_le\n36 73 1 11 Start Button\n", encoding="utf-8")
    dump = slots / "2" / "root" / "dump"
    dump.mkdir(parents=True)
    rig = pc.Rig.__new__(pc.Rig)
    rig.dump = str(dump)
    assert rig.switch_ids("turtles_le") == {(1, 11): 36}
    assert (dump / "tables" / "turtles_le" / "switch_list.txt").exists()
    assert rig.switch_ids("venom_le") == {}          # nobody has one: nothing made up


def test_losing_the_focus_lets_go_of_held_buttons():
    # PAD-811: VPX sends no key-up once its window loses the focus; TMNT's
    # launch button stayed down and launched every ball it was given
    pc = pytest.importorskip("padcontroller")

    class Pipe:
        def __init__(self):
            self.held = {34: 1, 36: 0, 65: 1, 39: 1}

        def set(self, sid, level):
            self.held[sid] = 1 if level else 0

    class Map:
        cabinet = {"start": 1036, "launch": 1034, "right_flipper": 1065, "coin": 1039}

        def switch_id(self, n):
            return n - 1000

    b = pc.Bridge.__new__(pc.Bridge)
    b.pipe, b.map = Pipe(), Map()
    b._release_buttons()
    assert b.pipe.held == {34: 0, 36: 0, 65: 0, 39: 1}   # coins are not buttons


def test_a_titles_card_is_the_stock_release_over_a_custom_one_of_its_version(tmp_path, monkeypatch):
    pl = pytest.importorskip("padlaunch")
    for n in ("turtles_pro-1_59_0.1987-upscaled.8G.sdcard.raw", "turtles_pro-1_59_0.Release.8G.sdcard.raw",
              "turtles_pro-1_58_0.Release.8G.sdcard.raw"):
        (tmp_path / n).write_bytes(b"")
    monkeypatch.setattr(pl, "kit_load", lambda: {"library": str(tmp_path)})
    monkeypatch.delenv("PAD_VPX_CARD", raising=False)
    monkeypatch.delenv("PAD_VPX_LIBRARY", raising=False)
    assert os.path.basename(pl.card_for("turtles_pro")) == "turtles_pro-1_59_0.Release.8G.sdcard.raw"


def test_a_named_table_never_takes_the_lone_run_of_another_title(tmp_path, monkeypatch):
    # PAD-811: JAWS attached to another ticket's hidden Godzilla run, the
    # only one up, drove its switches and never started its own
    pc = pytest.importorskip("padcontroller")
    monkeypatch.setattr(pc, "BOARD", str(tmp_path))
    (tmp_path / "slot-2.run").write_text(json.dumps(
        {"emu": "spike2", "slot": 2, "game": "godzilla_le", "label": "PAD-827", "hidden": True}), encoding="utf-8")
    assert pc.Rig.board_run("jaws_le") is None
    assert pc.Rig.board_run("godzilla_le")["slot"] == 2
    assert pc.Rig.board_run(None)["slot"] == 2                         # a nameless table still finds it


def test_patched_table_gets_its_backglass_under_the_matching_name(tmp_path):
    # B2S looks for <table name>.directb2s, and the patched table is
    # "<name> (PAD).vpx": the original's backglass is copied to match
    pv = pytest.importorskip("padvpx")
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir(), out.mkdir()
    (src / "JAWS.vpx").write_bytes(b"t")
    (src / "JAWS.directb2S").write_bytes(b"bg")
    got = pv.copy_backglass(str(src / "JAWS.vpx"), str(out / "JAWS (PAD).vpx"))
    assert got == str(out / "JAWS (PAD).directb2s")
    assert (out / "JAWS (PAD).directb2s").read_bytes() == b"bg"
    # one the user already put there is theirs
    (out / "JAWS (PAD).directb2s").write_bytes(b"mine")
    pv.copy_backglass(str(src / "JAWS.vpx"), str(out / "JAWS (PAD).vpx"))
    assert (out / "JAWS (PAD).directb2s").read_bytes() == b"mine"
    # no backglass anywhere: nothing
    (src / "Bond.vpx").write_bytes(b"t")
    assert pv.copy_backglass(str(src / "Bond.vpx"), str(out / "Bond (PAD).vpx")) is None


def test_the_tables_folder_can_be_chosen(tmp_path, monkeypatch):
    # PAD-848: David keeps his patched tables in a folder on the desktop; the
    # tab's folder is where "Patched" looks, what Play lists and opens
    vs = pytest.importorskip("vpxsetup")
    pl = pytest.importorskip("padlaunch")
    monkeypatch.setattr(pl, "KIT", str(tmp_path / "kit.json"))
    vpx = tmp_path / "Visual Pinball"
    (vpx / "tables").mkdir(parents=True)
    (vpx / "VPinballX64.exe").write_bytes(b"x")
    monkeypatch.setattr(vs, "find_vpx", lambda: str(vpx))
    assert vs.vpx_tables_dir() == str(vpx / "tables")                     # nothing chosen: Visual Pinball's
    mine = tmp_path / "desktop tables"
    mine.mkdir()
    (mine / "Rush LE 2.0.2 (PAD).vpx").write_bytes(b"x")
    assert vs.set_tables(str(mine)) == "ok"
    assert vs.vpx_tables_dir() == str(mine)
    rush = next(t for t in vs.known_tables() if t["title"] == "rush_le")
    assert rush["patched"]
    assert vs.patched_in(vs.vpx_tables_dir()) == ["Rush LE 2.0.2 (PAD).vpx"]
    assert "no folder" in vs.set_tables(str(tmp_path / "gone")).lower()    # refused, the setting kept
    assert vs.vpx_tables_dir() == str(mine)
    import shutil
    shutil.rmtree(mine)                                                     # a folder that went away
    assert vs.vpx_tables_dir() == str(vpx / "tables")
    assert vs.set_tables("") == "ok" and "tables" not in pl.kit_load()


def test_tmnt_lists_only_the_pro():
    # PAD-848: the TMNT LE card starts no game in the emulator (PAD-829); the
    # tab lists the Pro alone, and Patch still takes the Pro for the download
    vs = pytest.importorskip("vpxsetup")
    pv = pytest.importorskip("padvpx")
    titles = [t for row in vs.known_tables("") for t in row["titles"]]
    assert "turtles_pro" in titles and "turtles_le" not in titles
    assert pv.maps()["turtles_le"]["listed"] is False and pv.maps()["turtles_pro"]["listed"]
