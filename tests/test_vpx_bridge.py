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
    item = struct.pack("<i", 7) + _rec("VCEN", struct.pack("<ff", 100, 200)) + \
        _rec("NAME", vpxfile.wide("L21")) + _rec("DPNT", b"") + \
        _rec("VCEN", struct.pack("<ff", 110, 205)) + _rec("ENDB", b"")
    out = vpxfile.clone_item(item, "PL_NEW", 300, 400)
    assert struct.unpack_from("<i", out, 0)[0] == 7
    recs = [(t, p) for t, p, _ in vpxfile.biff_records(out, 4)]
    vcens = [struct.unpack("<ff", p) for t, p in recs if t == "VCEN"]
    assert vcens == [(300.0, 400.0), (310.0, 405.0)]
    assert vpxfile.unwide(dict(recs)["NAME"]) == "PL_NEW"


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
    for num, s in gzmap["solenoids"].items():
        if num == "_":
            continue
        node, idx = s["coil"]
        assert int(num) == 1000 + node * 16 + idx, num
        assert 0 <= idx < 16
    ids = {int(v) for k, v in gzmap["switch_rewrite"].items() if k != "_"}
    ids |= {int(v) for k, v in gzmap["switch_by_object"].items() if k != "_"}
    ids |= set(gzmap["switch_holds"]["trough"])
    assert all(0 <= i <= 97 for i in ids), "godzilla_le has switch ids 1..97"
    assert 1999 == gzmap["game_on"]["number"]


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
        'Sub UpdateLamps',
        ' NFadeL 1, l1',
        'End Sub',
        '\t\tbsTrough.InitSw 0,14,13,12,11,0,0,0',
        '\t\tbsTrough.Balls = 4',
        '\t\tbsTrough.InitExitSnd SoundFX("ballrelease",DOFContactors), SoundFX("Solenoid",DOFContactors)',
        '\t\tmTopMagnet.Solenoid = 3',
        'Sub Table1_KeyDown(ByVal KeyCode)',
        '\tIf KeyCode=PlungerKey Then Controller.Switch(53)=1',
        'End Sub',
    ])
    out, rep = patch.patch_script(mini, gzmap)
    assert 'GetTextFile("PADSPIKE2.vbs")' in out and "SEGA.VBS" not in out
    assert 'cGameName="godzilla_le",UseSolenoids=2' in out
    assert out.count("PAD: Spike 2 coils") == 1
    assert 'SolCallback(1129) = "SolRelease"' in out and "solTopMagnet" not in out
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
    assert "mMechaMagnet.Solenoid = 1151" in out
    assert out.count("End Sub") + out.count("end Sub") == \
        len(re.findall(r"(?im)^\s*(?:public |private )?sub\s", out)), "every Sub closes once"
