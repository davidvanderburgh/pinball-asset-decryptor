"""The table author's live probe, LED matching and stubs (PAD-1303):
tools/spike2_emu/vpx/vpxprobe.py and vpxstubs.py.

What is worth failing on, none of it needing WSL, a run or a .vpx:

  * THE PROBE NAMES WHAT CHANGED between two padled / padsw snapshots: a
    named LED and an unnamed channel, a coil's command with its pulse and
    hold (and its OFF), a switch with who moved it - the probe, PAD's own
    helper by its padsw tag, never the probe's tag taken for someone else.
  * A SWITCH IS FOUND BY ID, WHOLE NAME, OR A PART ONLY ONE NAME HAS.
  * MATCH-LEDS PAIRS EACH LIGHT WITH THE INSERT UNDER IT, nearest pairs
    first, none twice; a table drawn a little off is pulled in by the
    lights themselves; lights off the playfield are nobody's; a pair that
    is not clear-cut is a GUESS.
  * THE STUBS: the right event per switch kind, a default per coil kind,
    a coil number core.vbs can index and nobody else has, each told to the
    controller; a drop TRIP knocks the bank down, a reset raises it; parts
    the script already names are left out; the block is replaced on a
    second run, and PadStubsInit is called from the table's Init once.
  * THE BLOCK IS VBSCRIPT: on Windows, cscript compiles and runs it with
    stand-ins, some objects placed and some not, under Option Explicit.
  * THE CONTROLLER KEEPS A SCRIPT'S PadSolenoid NUMBER across GameName.
"""
import os
import re
import shutil
import struct
import subprocess
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
def P():
    import vpxprobe
    return vpxprobe


@pytest.fixture(scope="module")
def S():
    import vpxstubs
    return vpxstubs


# ------------------------------------------------------------ the machine --

def _insert(name, node, idx, x, y, rgb=False):
    leds = [(node, idx + i) for i in range(3)] if rgb else [(node, idx)]
    names = ["%s-%s" % (name, c) for c in "RGB"] if rgb else [name]
    return {"name": name, "leds": leds, "names": names, "x": x, "y": y, "image": "playfield.png",
            "where": "playfield", "rgb": rgb, "rgb_order": "RGB" if rgb else None,
            "lamp": 1000 + node * 100 + idx}


def _sw(sid, name, kind, x=None, y=None):
    return {"id": sid, "num": sid, "node": 0, "bit": sid, "name": name, "kind": kind, "x": x, "y": y,
            "where": "playfield" if x is not None else "unplaced"}


def _coil(name, node, idx, kind):
    return {"name": name, "node": node, "index": idx, "kind": kind, "x": None, "y": None,
            "number": 1000 + node * 16 + idx}


def machine():
    ins = []
    # a 10 x 10 grid of inserts on a 100 x 200 drawing, 20 drawing px apart
    for i in range(10):
        for j in range(10):
            ins.append(_insert("INSERT %d %d" % (i, j), 8 + (i * 10 + j) // 90, (i * 10 + j) % 90,
                               5 + i * 10, 10 + j * 19))
    ins.append(_insert("SHOOT AGAIN", 9, 60, 50, 195, rgb=True))
    ins.append(dict(_insert("SPEAKER LEFT", 12, 0, 0, 0), where="cabinet", x=None, y=None))
    sws = [_sw(40, "LEFT OUTLANE", "lane", 5, 180), _sw(41, "RIGHT OUTLANE", "lane", 95, 180),
           _sw(42, "CENTER TARGET", "target", 50, 100), _sw(43, "LEFT SPINNER", "spinner", 20, 80),
           _sw(44, "LEFT SLING", "slingshot", 20, 170), _sw(45, "DROP LEFT", "drop target", 40, 60),
           _sw(46, "DROP RIGHT", "drop target", 60, 60), _sw(47, "LEFT EJECT", "saucer", 10, 40),
           _sw(48, "TROUGH 1", "trough"), _sw(49, "START BUTTON", "cabinet"),
           _sw(50, "LEFT FLIPPER EOS", "flipper eos"), _sw(51, "DROP RESET OPTO", "drop target")]
    coils = [_coil("MAGNET", 8, 0, "magnet"), _coil("DROP RESET", 8, 1, "drop reset"),
             _coil("DROP TRIP", 8, 2, "drop reset"), _coil("LEFT EJECT", 8, 3, "kick"),
             _coil("UP POST", 8, 4, "post"), _coil("DIVERTER GATE", 8, 5, "gate"),
             _coil("TROUGH", 8, 6, "trough"), _coil("AUTO PLUNGER", 8, 7, "auto plunger"),
             _coil("DISC MOTOR", 8, 8, "motor"), _coil("LEFT FLIPPER", 9, 0, "flipper"),
             _coil("LEFT SLING", 9, 1, "slingshot")]
    return {"title": "test_le", "image": "playfield.png", "image_size": (100, 200), "switches": sws,
            "coils": coils, "inserts": ins}


def table(m, dx=0.0, dy=0.0, jitter=0.0, extra=()):
    """Lights where each insert is, the drawing scaled x9.52 / x10.81 to a
    952 x 2162 table, shifted by (dx, dy)."""
    lights = []
    for k, g in enumerate(m["inserts"]):
        if g["x"] is None:
            continue
        j = jitter * (1 if k % 2 else -1)
        lights.append({"kind": "Light", "name": "L" + re.sub(r"\W", "", g["name"].title()),
                       "x": g["x"] * 9.52 + dx + j, "y": g["y"] * 10.81 + dy - j})
    lights += list(extra)
    return {"size": (0.0, 0.0, 952.0, 2162.0), "objects": list(lights), "lights": lights, "script": "",
            "name": "Table1"}


# ------------------------------------------------------------ the probe --

def block(P, leds=None, coils=None, drive=None):
    import coilmap
    data = bytearray(coilmap.HI_READ)
    struct.pack_into("<I", data, 0, coilmap.PADLED_MAGIC)
    struct.pack_into("<I", data, 4, 7)
    struct.pack_into("<I", data, coilmap.DRIVE_TPS_OFF, 1000)
    for (node, idx), v in (leds or {}).items():
        if idx < 96:
            data[20 + node * 96 + idx] = v
        else:
            data[coilmap.HI_OFF + node * coilmap.HI_IDX + idx - 96] = v
    for (node, idx), n in (coils or {}).items():
        data[coilmap.COIL_OFF + node * 16 + idx] = n
    for (node, idx), (until, pt, ht) in (drive or {}).items():
        o = node * 16 + idx
        struct.pack_into("<I", data, coilmap.DRIVE_UNTIL_OFF + 4 * o, until)
        struct.pack_into("<H", data, coilmap.DRIVE_PULSE_T_OFF + 2 * o, pt)
        struct.pack_into("<H", data, coilmap.DRIVE_HOLD_T_OFF + 2 * o, ht)
    return bytes(data)


def swblock(merged=None, script=None, src=""):
    import padsw
    data = bytearray(padsw.OFF_SPIN + padsw.MAX_ID)
    for sid, v in (merged or {}).items():
        data[padsw.OFF_MRG + sid] = v
    for sid, v in (script or {}).items():
        data[padsw.OFF_SCR_HELD + sid] = v
    if src:
        data[padsw.OFF_SCR_SRC] = ord(src)
    return bytes(data)


def test_probe_names_leds_coils_switches(P):
    names = P.names_for(machine())
    pr = P.Probe(names)
    assert pr.step(block(P), swblock(), 0.0) == []              # the baseline says nothing
    ev = pr.step(block(P, leds={(8, 0): 255, (4, 120): 90}, coils={(8, 6): 1}, drive={(8, 6): (5000, 60, 0)}),
                 swblock({48: 1}, {48: 1}, "b"), 0.5)
    by = {(e["what"], e["number"]): e for e in ev}
    led = by[("led", 1800)]
    assert led["name"] == "INSERT 0 0" and led["state"] == "on" and led["level"] == 255
    hi = by[("led", 1000 + 4 * 100 + 120)]                       # the hi plane, a channel nobody named
    assert not hi["named"] and "(unnamed: node 4 LED 120)" in P.line(hi)
    coil = by[("coil", 1000 + 8 * 16 + 6)]
    assert coil["name"] == "TROUGH" and coil["state"] == "fired" and coil["pulse_ms"] == 60
    assert "fired 60 ms" in P.line(coil)
    sw = by[("switch", 1048)]
    assert sw["state"] == "closed" and sw["by"] == "PAD: ballfeed"
    # the coil's OFF, the LED going dark, a switch the probe itself closed
    pr.mine[40] = 1
    ev = pr.step(block(P, coils={(8, 6): 1}), swblock({48: 1, 40: 1}, {48: 1, 40: 1}, P.PROBE_SRC), 1.0)
    by = {(e["what"], e["number"]): e for e in ev}
    assert by[("coil", 1134)]["state"] == "off"
    assert by[("led", 1800)]["state"] == "off"
    assert by[("switch", 1040)]["by"] == "probe"


def test_probe_never_credits_its_own_tag_to_another_switch(P):
    pr = P.Probe(P.names_for(machine()))
    pr.step(block(P), swblock(), 0.0)
    ev = pr.step(block(P), swblock({41: 1}, {41: 1}, P.PROBE_SRC), 0.1)
    assert ev[0]["by"] == "PAD"                                  # PAD moved it; the tag is the probe's
    ev = pr.step(block(P), swblock({41: 1, 42: 1}, {41: 1}, "b"), 0.2)
    assert ev[0]["number"] == 1042 and ev[0]["by"] == "rig"      # in the merged truth only


def test_probe_levels_and_filters(P):
    pr = P.Probe(P.names_for(machine()), levels=True, switches=False)
    pr.step(block(P, leds={(8, 0): 255}), swblock(), 0.0)
    ev = pr.step(block(P, leds={(8, 0): 100}), swblock({40: 1}), 0.1)
    assert [(e["what"], e["level"]) for e in ev] == [("led", 100)]     # a fade step; no switches asked
    e = ev[0]
    assert P._wanted(e, ["insert 0"]) and P._wanted(e, ["1800"]) and not P._wanted(e, ["SHOOT"])


def test_find_switch(P):
    names = P.names_for(machine())
    assert P.find_switch(names, "1042") == (42, "CENTER TARGET")
    assert P.find_switch(names, "42") == (42, "CENTER TARGET")
    assert P.find_switch(names, "left outlane") == (40, "LEFT OUTLANE")
    assert P.find_switch(names, "spinner") == (43, "LEFT SPINNER")
    sid, why = P.find_switch(names, "OUTLANE")
    assert sid is None and "LEFT OUTLANE (40)" in why and "RIGHT OUTLANE (41)" in why
    assert P.find_switch(names, "nothing")[0] is None


def test_probe_says_when_no_run_is_up(P, capsys):
    class Rig:
        dump, how = "X:\\nowhere", "test"

        def led_path(self):
            return "X:\\nowhere\\padled"

    import io
    out = io.StringIO()
    assert P.run("test_le", seconds=0, rig=Rig(), read=lambda p, n: None, out=out) == 1
    assert "No run of test_le is up" in out.getvalue()


# ------------------------------------------------------------ match-leds --

def _right(got):
    return [m for m in got["matches"] if m["light"] == "L" + re.sub(r"\W", "", m["insert"].title())]


def test_match_leds_pairs_each_light_with_its_insert(S):
    m = machine()
    off = {"kind": "Light", "name": "BackglassLight", "x": -300.0, "y": 50.0}
    got = S.match_leds(m, table(m, jitter=6, extra=[off]))
    assert len(got["matches"]) == 101 and len(_right(got)) == 101
    assert all(x["sure"] for x in got["matches"])
    assert "BackglassLight" not in [x["light"] for x in got["matches"]] + got["lights_left"]
    rgb = next(x for x in got["matches"] if x["insert"] == "SHOOT AGAIN")
    assert rgb["leds"] == [[9, 60], [9, 61], [9, 62]] and rgb["rgb"] is True
    e = S.lamps_entry(rgb)
    assert e == {"leds": [[9, 60], [9, 61], [9, 62]], "name": "SHOOT AGAIN", "rgb": True}


def test_match_leds_pulls_in_a_table_drawn_off(S):
    m = machine()
    # every light 45 units right of and 40 below its insert: about half the
    # grid's pitch, so the scaled drawing alone pairs many wrongly
    got = S.match_leds(m, table(m, dx=45, dy=40))
    assert got["fit"]["how"] == "scaled+refined"
    assert len(_right(got)) >= 98


def test_match_leds_ambiguous_is_a_guess(S):
    m = machine()
    # a light half way between two inserts of a row is neither's for sure
    mid = {"kind": "Light", "name": "Lmid", "x": 10 * 9.52, "y": 10 * 10.81}     # INSERT 0 0 | INSERT 1 0
    t = table(m)
    t["lights"] = [o for o in t["lights"] if o["name"] not in ("LInsert00", "LInsert10")] + [mid]
    got = S.match_leds(m, t)
    x = next(x for x in got["matches"] if x["light"] == "Lmid")
    assert not x["sure"] and "GUESS" in S.lamps_entry(x)["note"]


def test_match_leds_skips_what_the_map_wires(S):
    m = machine()
    got = S.match_leds(m, table(m), skip_lights=["LInsert00"], skip_leds=[(8, 1)])
    assert "LInsert00" not in [x["light"] for x in got["matches"]]
    assert "INSERT 0 1" not in [x["insert"] for x in got["matches"]]


# ------------------------------------------------------------ stubs --

@pytest.fixture(autouse=True)
def _own_sols(S, monkeypatch):
    """No test reads this PC's maps for the made-up title's numbers."""
    monkeypatch.setattr(S, "_controller_sols", lambda title: {})


def _block(S, script="", title_sols=None, m=None):
    S._controller_sols = lambda title: dict(title_sols or {})
    geo = {"script": script, "name": "Table1", "size": (0, 0, 952, 2162), "objects": [], "lights": []}
    return S.stub_block(m or machine(), geo, {"solenoids": {}, "solenoid_max": 68} if title_sols is None
                        else None)


def test_stubs_switches_by_kind(S):
    t = _block(S)["text"]
    assert "Sub sw_LEFT_OUTLANE_Hit : Controller.Switch(1040) = 1" in t
    assert "Sub sw_LEFT_OUTLANE_UnHit : Controller.Switch(1040) = 0" in t
    assert "Sub sw_CENTER_TARGET_Hit : vpmTimer.PulseSw 1042" in t
    assert "Sub sw_LEFT_SPINNER_Spin : vpmTimer.PulseSw 1043" in t
    assert "Sub sw_LEFT_SLING_Slingshot : vpmTimer.PulseSw 1044" in t
    assert "Sub sw_DROP_LEFT_Hit : Controller.Switch(1045) = 1" in t
    assert "sw_DROP_LEFT_UnHit" not in t                          # down until the bank resets
    assert "Sub sw_LEFT_EJECT_Hit : Controller.Switch(1047) = 1" in t
    for never in ("START_BUTTON", "FLIPPER_EOS"):
        assert "sw_%s" % never not in t


def test_stubs_coils_by_kind(S):
    got = _block(S)
    t = got["text"]
    nums = {c["name"]: c["solenoid"] for c in got["coils"]}
    assert set(nums) == {"MAGNET", "DROP RESET", "DROP TRIP", "LEFT EJECT", "UP POST", "DIVERTER GATE",
                         "TROUGH", "AUTO PLUNGER", "DISC MOTOR"}          # never the board's flipper, sling
    assert len(set(nums.values())) == len(nums) and not set(nums.values()) & set(S.FLIPPER_SOLS)
    assert all(1 <= n <= 68 for n in nums.values())
    for name, n in nums.items():
        c = next(c for c in got["coils"] if c["name"] == name)
        assert "Controller.PadSolenoid(%d) = Array(%d, %d)" % (n, c["node"], c["index"]) in t
        assert 'SolCallback(%d) = "%s"' % (n, c["sub"]) in t
    assert "PadMag_MAGNET.InitMagnet mag_MAGNET, 15" in t and 'PadMag_MAGNET.CreateEvents "PadMag_MAGNET"' in t
    assert "PadMag_MAGNET.MagnetOn = aOn" in t
    assert 'PadStubDropsUp Array("sw_DROP_LEFT", "sw_DROP_RIGHT"), Array(1045, 1046)' in t
    assert 'PadStubDropsDown Array("sw_DROP_LEFT", "sw_DROP_RIGHT"), Array(1045, 1046)' in t
    assert "DROP_RESET_OPTO" not in t.split("'---- coils")[1].split("'---- the helpers")[0].replace(
        "Sol_DROP_RESET", "")                                     # a reset switch is not in its bank
    assert 'PadStubKick "sw_LEFT_EJECT", 180, 8, 0' in t           # the saucer's own Kicker
    assert 'PadStubPost "post_UP_POST", aOn' in t
    assert 'PadStubGate "gate_DIVERTER_GATE", aOn' in t
    assert "bsTrough.SolOut aOn" in t
    assert 'PadStubPlunge "plunger_AUTO_PLUNGER"' in t
    assert "Sub Sol_DISC_MOTOR(aOn)" in t
    assert not re.search(r"\(on\)|\bon\b\s*:", t)                  # `on` is VBScript's own word


def test_stubs_inserts(S):
    got = _block(S)
    t = got["text"]
    assert 'PadStubAddLamp "l_INSERT_0_0", Array(1800)' in t
    assert 'PadStubAddLamp "l_SHOOT_AGAIN", Array(1960, 1961, 1962)' in t
    assert "SPEAKER" not in t
    assert "vpmTimer.EnableUpdate PadStubTick, False, True" in t


def test_stubs_numbers_avoid_the_map_and_the_script(S):
    m = machine()
    script = "SolCallback(1) = \"Mine\"\r\nSolCallback(2) = \"Mine2\"\r\n"
    got = _block(S, script, title_sols={3: (7, 7), 5: (8, 0)}, m=m)
    nums = {c["name"]: c["solenoid"] for c in got["coils"]}
    assert not {1, 2, 3}.intersection(nums.values())
    # a coil the controller's map numbers (5) that the script hands to
    # SolCallback is wired already: no stub
    got = _block(S, script + "SolCallback(5) = \"MyMagnet\"\r\n", title_sols={5: (8, 0)}, m=m)
    assert "MAGNET" not in {c["name"] for c in got["coils"]}


def test_stubs_leave_out_what_the_script_names(S):
    script = ("Sub LeftLane_Hit : Controller.Switch(1040) = 1 : End Sub\r\n"
              "PadLamps.Add \"1800\", Array(L1)\r\n"
              "Controller.PadSolenoid(9) = Array(8, 4)\r\n")
    got = _block(S, script)
    assert 1040 - 1000 not in [s["id"] for s in got["switches"]]
    assert "INSERT 0 0" not in [g["name"] for g in got["inserts"]]
    assert "UP POST" not in [c["name"] for c in got["coils"]]


def test_stubs_by_the_map_gaps(S):
    import vpxauthor
    m = machine()
    cov = vpxauthor.coverage({"switches": {"LeftLane": {"id": 40}},
                              "solenoids": {"7": {"coil": [8, 6], "callback": "bsTrough.SolOut"},
                                            "9": {"coil": [8, 4], "callback": None}},
                              "lamps": {"L1": {"leds": [[8, 0]]}}})
    geo = {"script": "", "name": "Table1", "size": (0, 0, 952, 2162), "objects": [], "lights": []}
    got = S.stub_block(m, geo, {"solenoids": {"7": {"coil": [8, 6]}, "9": {"coil": [8, 4]}}}, cov)
    assert 40 not in [s["id"] for s in got["switches"]]
    names = {c["name"]: c for c in got["coils"]}
    assert "TROUGH" not in names
    post = names["UP POST"]                                         # listed with nothing firing it
    assert post["solenoid"] == 9 and not post["told"]
    assert "Controller.PadSolenoid(9)" not in got["text"] and 'SolCallback(9) = "Sol_UP_POST"' in got["text"]


def test_with_stubs_replaces_and_calls_init_once(S):
    script = "Option Explicit\r\nSub Table1_Init\r\n\tController.GameName = \"x\"\r\nEnd Sub\r\n"
    b1 = _block(S, script)["text"]
    s1, in_init = S.with_stubs(script, b1, "Table1")
    assert in_init and s1.count(S.BEGIN) == 1
    assert re.search(r"Sub Table1_Init\r\n\tPadStubsInit", s1)
    s2, _ = S.with_stubs(s1, _block(S, s1)["text"], "Table1")
    assert s2 == s1                                                 # the same parts: the same script
    assert s2.count("PadStubsInit   ' the PAD stubs") == 1
    s3, in_init = S.with_stubs("Sub Other_Init\r\nEnd Sub\r\n", b1, "Table1")
    assert not in_init and s3.rstrip().endswith(S.END)


VBS_STANDINS = r'''Option Explicit
Sub Say(s) : WScript.Echo s : End Sub
Class MockController
    Private sw
    Private Sub Class_Initialize : Set sw = CreateObject("Scripting.Dictionary") : End Sub
    Public Property Let Switch(n, v) : Say "Switch " & n & " = " & CInt(v) : sw(n) = v : End Property
    Public Property Get Switch(n) : Switch = sw(n) : End Property
    Public Property Let PadSolenoid(n, v) : Say "PadSolenoid " & n & " = " & v(0) & "," & v(1) : End Property
    Public Property Get Lamp(n) : Lamp = (n = 1800) : End Property
End Class
Dim Controller : Set Controller = New MockController
Dim Ticker
Class MockTimer
    Public Sub PulseSw(n) : Say "PulseSw " & n : End Sub
    Public Sub EnableUpdate(o, fast, en) : Set Ticker = o : End Sub
End Class
Dim vpmTimer : Set vpmTimer = New MockTimer
Dim SolCallback(68)
Class cvpmMagnet
    Public GrabCenter
    Public Sub InitMagnet(t, s) : Say "InitMagnet " & t.Name : End Sub
    Public Sub CreateEvents(n) : End Sub
    Public Property Let MagnetOn(v) : Say "MagnetOn " & CInt(v) : End Property
End Class
Class MockObj
    Public Name, Open, AutoPlunger
    Private mDropped, mState
    Public Property Let IsDropped(v) : mDropped = v : Say Name & ".IsDropped = " & v : End Property
    Public Property Get IsDropped : IsDropped = mDropped : End Property
    Public Property Let State(v) : mState = v : Say Name & ".State = " & v : End Property
    Public Property Get State : State = mState : End Property
    Public Sub Kick(a, s, i) : Say Name & ".Kick " & a & "," & s & "," & i : End Sub
    Public Sub Fire : Say Name & ".Fire" : End Sub
End Class
'''


@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("cscript"), reason="needs Windows' cscript")
def test_stub_block_runs_under_vbscript(S, tmp_path):
    got = _block(S)
    placed = ["mag_MAGNET", "sw_DROP_LEFT", "sw_LEFT_EJECT", "post_UP_POST", "plunger_AUTO_PLUNGER",
              "l_INSERT_0_0"]                                       # sw_DROP_RIGHT, gate_..., the rest: not
    objs = "\n".join('Dim %s : Set %s = New MockObj : %s.Name = "%s"' % (n, n, n, n) for n in placed)
    subs = re.findall(r"^Sub (\w+)", got["text"], re.M)
    calls = [s for s in subs if s.startswith("sw_")]
    calls += ["%s True\n%s False" % (s, s) for s in subs if s.startswith("Sol_")]
    calls += ["Ticker.Update", "PadStubsInit", 'Say "done"']
    src = VBS_STANDINS + objs + "\n" + got["text"].replace("\r\n", "\n") + "\n" + "\n".join(calls) + "\n"
    f = tmp_path / "stubs.vbs"
    f.write_text(src, encoding="ascii", newline="\r\n")
    r = subprocess.run(["cscript", "//nologo", str(f)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = r.stdout.splitlines()
    assert out[-1] == "done"
    assert out.count("InitMagnet mag_MAGNET") == 1                  # PadStubsInit runs once
    for line in ("Switch 1040 = 1", "Switch 1040 = 0", "PulseSw 1042", "PulseSw 1043", "MagnetOn -1",
                 "MagnetOn 0", "sw_DROP_LEFT.IsDropped = False", "sw_DROP_LEFT.IsDropped = True",
                 "Switch 1045 = 0", "Switch 1046 = 1", "sw_LEFT_EJECT.Kick 180,8,0",
                 "post_UP_POST.IsDropped = False", "post_UP_POST.IsDropped = True", "plunger_AUTO_PLUNGER.Fire",
                 "l_INSERT_0_0.State = 1"):
        assert line in out, line
    assert sum(1 for ln in out if ln.startswith("PadSolenoid ")) == len(got["coils"])


# ------------------------------------------------------------ the controller --

def test_controller_keeps_a_scripts_coil_number(monkeypatch):
    import padcontroller as pc
    b = pc.Bridge()
    assert b.own_solenoid(12, (8, 3))
    assert b.map.solenoids[12] == (8, 3)
    b.set_game("no_such_title_pad1303")                            # the map is made again
    assert b.map.solenoids[12] == (8, 3)
    assert 12 in b._sol_nums((8, 3))
    assert not b.own_solenoid(0, (8, 3)) and not b.own_solenoid(500, (8, 3))
    assert not b.own_solenoid(5, "x") and not b.own_solenoid(5, (8, 99))
    ctl = pc.PadController.__new__(pc.PadController)
    ctl.bridge, ctl.props = b, {}
    ctl._put("padsolenoid", (14, (9, 2)))
    assert b.map.solenoids[14] == (9, 2)


def test_match_leds_confirm_and_into(S, tmp_path, monkeypatch):
    m = machine()
    monkeypatch.setattr(S, "_machine", lambda title, d=None: (m, None))
    monkeypatch.setattr(S, "table_geometry", lambda path: table(m))
    monkeypatch.setattr(S, "_map_for_table", lambda title, path: (None, None))
    answers = iter(["y", "n", "y"])

    def ask(prompt):
        try:
            return next(answers)
        except StopIteration:
            raise EOFError                                          # the answers ran out: stop asking
    into = tmp_path / "map.json"
    into.write_text('{"lamps": {"LInsert00": {"leds": [[1, 1]], "name": "mine"}}}', encoding="utf-8")
    got = S.match_leds_cmd("test_le", str(tmp_path / "t.vpx"), str(into), True, str(tmp_path / "out.json"),
                           ask=ask, say=lambda s: None)
    assert got["accepted"] == 2
    import json
    lamps = json.loads(into.read_text(encoding="utf-8"))["lamps"]
    assert lamps["LInsert00"] == {"leds": [[1, 1]], "name": "mine"}           # the map's own stays
    assert len([k for k in lamps if k != "_"]) == 2
