"""PAD-1304: a three-screen cabinet under Visual Pinball - the backglass on a
screen of its own (<table>.res), B2S's DMD hidden, the START and LOCKDOWN
button lights to DOF as E events, BACKBOX GI to the backglass bulbs picked."""
import json
import os
import shutil
import sys
import xml.etree.ElementTree as ET

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
VPX = os.path.join(os.path.dirname(HERE), "tools", "spike2_emu", "vpx")
for p in (VPX, os.path.dirname(VPX)):
    if p not in sys.path:
        sys.path.insert(0, p)

import padcabinet  # noqa: E402

MONS = [{"n": 1, "x": 0, "y": 0, "w": 2560, "h": 1440, "primary": True},
        {"n": 2, "x": 2560, "y": 0, "w": 1920, "h": 1080, "primary": False},
        {"n": 3, "x": -1280, "y": 0, "w": 1280, "h": 1024, "primary": False}]

#: device_xy.txt rows as the rig writes them (class name x y w h grp index conn image),
#: John Wick LE's cabinet board rows among them
DEVICE_XY = """# john_wick_le device positions, from the game binary.
# class   name                                   x     y    w    h  grp index  conn   image
led       BACKBOX GI                             0     0   30   30    4     0  -      System/TestMode/backbox
led       START BUTTON                         102   228   30   30    5     2  -      System/TestMode/spike_2_cabinet_front_cropped
led       TOURNAMENT START                     102   277   30   30    5     3  -      System/TestMode/spike_2_cabinet_front_cropped
led       LOCKDOWN BUTTON-G                    250   169   30   30    5     4  -      System/TestMode/spike_2_cabinet_front_cropped
led       LOCKDOWN BUTTON-R                    250   169   30   30    5     5  -      System/TestMode/spike_2_cabinet_front_cropped
led       LOCKDOWN BUTTON-B                    250   169   30   30    5     7  2a     System/TestMode/spike_2_cabinet_front_cropped
led       JOB START FLASH                      259   349   20   20    7    51  8c     playfield
"""


def _tables(tmp_path, device=DEVICE_XY, exact="4 0\n5 1\n7 8\n", led_io=None):
    d = tmp_path / "tables" / "john_wick_le"
    d.mkdir(parents=True)
    if device is not None:
        (d / "device_xy.txt").write_text(device, encoding="utf-8")
    if exact:
        (d / "group_node_exact.txt").write_text(exact, encoding="utf-8")
    if led_io is not None:
        (d / "led_io.txt").write_text(led_io, encoding="utf-8")
    return str(d)


def test_cabinet_lights_by_name_from_the_device_table(tmp_path):
    got = padcabinet.cabinet_leds(_tables(tmp_path))
    # TOURNAMENT START and JOB START FLASH are not the start button
    assert got == {"backbox_gi": [(0, 0)], "start": [(1, 2)], "lockdown": [(1, 4), (1, 5), (1, 7)]}


def test_cabinet_lights_from_led_io_and_the_platform_places(tmp_path):
    # a device table without the cabinet rows: led_io.txt's names
    led_io = ("# node idx name x y\n"
              "  0    0  BACKBOX GI                 10   20  backbox\n"
              "  1    2  START BUTTON               10   20  cabinet\n")
    d = _tables(tmp_path, device=DEVICE_XY.splitlines()[0] + "\n", led_io=led_io)
    assert padcabinet.cabinet_leds(d) == {"backbox_gi": [(0, 0)], "start": [(1, 2)]}
    # a device table the rig could not read (no rows): every Spike 2 title's places
    d2 = str(tmp_path / "blank")
    os.makedirs(d2)
    assert padcabinet.cabinet_leds(d2) == padcabinet.SPIKE2_PLACES
    # one that reads but names none of them (Elvira 3): none, not a guess
    d3 = tmp_path / "elvira3"
    d3.mkdir()
    (d3 / "device_xy.txt").write_text(DEVICE_XY.splitlines()[-1] + "\n", encoding="utf-8")
    (d3 / "group_node_exact.txt").write_text("7 8\n", encoding="utf-8")
    assert padcabinet.cabinet_leds(str(d3)) == {}


def test_settings_defaults_and_updates():
    c = padcabinet.settings({})
    assert c == {"backglass": 0, "hide_dmd": False, "dof_start": 0, "dof_lockdown": 0, "gi_bulbs": {}}
    kit = padcabinet.update({"library": "x"}, backglass=2, hide_dmd=True, dof_start=190)
    assert kit["library"] == "x"
    kit = padcabinet.set_bulbs(kit, "jaws_le", ["g1", "g2", ""])
    c = padcabinet.settings(json.loads(json.dumps(kit)))
    assert (c["backglass"], c["hide_dmd"], c["dof_start"], c["dof_lockdown"]) == (2, True, 190, 0)
    assert c["gi_bulbs"] == {"jaws_le": ["g1", "g2"]}
    assert padcabinet.settings(padcabinet.set_bulbs(kit, "jaws_le", []))["gi_bulbs"] == {}
    assert padcabinet.settings({"cabinet": {"dof_start": -5, "backglass": "x"}})["dof_start"] == 0
    with pytest.raises(KeyError):
        padcabinet.update({}, nonsense=1)


SCREENRES = """1920
1080
1280
1024
2
0
0
800
200
100
800
0
"""


def test_res_puts_the_backglass_on_the_screen_picked(tmp_path):
    out = tmp_path / "Jaws (PAD).vpx"
    out.write_bytes(b"")
    (tmp_path / "ScreenRes.txt").write_text(SCREENRES, encoding="utf-8")
    kit = padcabinet.update({}, backglass=3)
    said = padcabinet.write_res(str(out), kit, MONS, b2s_dirs=[])
    res = tmp_path / "Jaws (PAD).res"
    lines = res.read_text(encoding="utf-8").splitlines()
    assert lines[0] == padcabinet.RES_MARK
    # playfield and DMD as the ScreenRes.txt has them; the backglass fills screen 3,
    # named by its left edge
    assert lines[1:] == ["1920", "1080", "1280", "1024", "@-1280", "0", "0", "800", "200", "100", "800", "0"]
    assert padcabinet.parse_screenres(res.read_text(encoding="utf-8"))[4] == "@-1280"
    assert b"\r\n" in res.read_bytes()
    assert "screen 3 (1280x1024)" in said[0]
    # a "# V2" ScreenRes (a background picture) stays a V2 file
    (tmp_path / "ScreenRes.txt").write_text("# V2\n" + SCREENRES + "0\n0\n10\n10\nC:\\bg.png\n",
                                            encoding="utf-8")
    padcabinet.write_res(str(out), kit, MONS, b2s_dirs=[])
    v2 = res.read_text(encoding="utf-8").splitlines()
    assert v2[1] == "# V2" and v2[-1] == "C:\\bg.png" and v2[6] == "@-1280"
    # no ScreenRes.txt anywhere: the main screen is the playfield, no DMD
    (tmp_path / "ScreenRes.txt").unlink()
    padcabinet.write_res(str(out), padcabinet.update({}, backglass=2), MONS, b2s_dirs=[])
    assert res.read_text(encoding="utf-8").splitlines()[1:8] == ["2560", "1440", "1920", "1080", "@2560", "0", "0"]
    # back to where B2S puts it: the .res goes
    said = padcabinet.write_res(str(out), {}, MONS, b2s_dirs=[])
    assert not res.exists() and "removed" in said[0]
    # a .res the person wrote is never touched
    res.write_text("1\n2\n", encoding="utf-8")
    said = padcabinet.write_res(str(out), padcabinet.update({}, backglass=2), MONS, b2s_dirs=[])
    assert res.read_text(encoding="utf-8") == "1\n2\n" and "your own" in said[0]
    padcabinet.write_res(str(out), {}, MONS, b2s_dirs=[])
    assert res.exists()


def test_hide_b2s_dmd_keeps_the_rest_of_the_settings(tmp_path):
    xml = tmp_path / "B2STableSettings.xml"
    # showing it when there is no file: no file made
    assert not padcabinet.set_hide_b2s_dmd(str(tmp_path), "mtl_180h", False) and not xml.exists()
    assert padcabinet.set_hide_b2s_dmd(str(tmp_path), "mtl_180h", True)
    root = ET.parse(xml).getroot()
    assert root.tag == "B2STableSettings" and root.find("mtl_180h/HideB2SDMD").text == "1"
    # B2S's own file: other tables and keys kept
    xml.write_text("<?xml version=\"1.0\"?><B2STableSettings><ArePluginsOn>1</ArePluginsOn>"
                   "<jaws><HideGrill>1</HideGrill></jaws><mtl_180h><HideDMD>2</HideDMD>"
                   "<HideB2SDMD>0</HideB2SDMD></mtl_180h></B2STableSettings>", encoding="utf-8")
    assert padcabinet.set_hide_b2s_dmd(str(tmp_path), "mtl_180h", True)
    assert not padcabinet.set_hide_b2s_dmd(str(tmp_path), "mtl_180h", True)      # already
    root = ET.parse(xml).getroot()
    assert root.find("ArePluginsOn").text == "1" and root.find("jaws/HideGrill").text == "1"
    assert root.find("mtl_180h/HideDMD").text == "2" and root.find("mtl_180h/HideB2SDMD").text == "1"
    assert padcabinet.set_hide_b2s_dmd(str(tmp_path), "mtl_180h", False)
    assert ET.parse(xml).getroot().find("mtl_180h/HideB2SDMD").text == "0"
    # a file that does not parse is the person's: left alone
    xml.write_text("<B2STableSettings><broken>", encoding="utf-8")
    assert not padcabinet.set_hide_b2s_dmd(str(tmp_path), "mtl_180h", True)
    assert xml.read_text(encoding="utf-8") == "<B2STableSettings><broken>"
    # a name that is no XML tag is never written
    assert not padcabinet.set_hide_b2s_dmd(str(tmp_path), "../x y", True)


def test_bulb_names_of_a_backglass(tmp_path):
    b2s = tmp_path / "t.directb2s"
    b2s.write_text('<?xml version="1.0"?><DirectB2SData><Name Value="t"/><Illumination>'
                   '<Bulb ID="1" Name="g1" Image="AAAA"/><Bulb ID="2" Name="" Image="AAAA"/>'
                   '<Bulb ID="3" Name="e1"/><Bulb ID="4" Name="g1"/></Illumination></DirectB2SData>',
                   encoding="utf-8")
    assert padcabinet.bulb_names(str(b2s)) == ["g1", "e1"]
    assert padcabinet.bulb_names(str(tmp_path / "none.directb2s")) == []


REAL_B2S = r"C:\tmp\vpx_new\JAWS_50Th_Anniversary.3.2\JAWS_50Th_Anniversary.directb2S"


@pytest.mark.skipif(not os.path.exists(REAL_B2S), reason="a real backglass on this PC")
def test_bulb_names_of_a_real_backglass():
    assert padcabinet.bulb_names(REAL_B2S) == ["1", "e1", "e2", "g1", "g2", "2", "g4", "g3", "11"]


class FakeDOF:
    def __init__(self):
        self.got = []

    def Init(self, host, table, rom):
        pass

    def UpdateTableElement(self, kind, n, v):
        self.got.append((kind, n, v))

    def Finish(self):
        pass


class FakeB2S:
    def __init__(self):
        self.got = []

    def B2SSetIllumination(self, name, value):
        self.got.append((name, value))


def _bridge(tmp_path, kit):
    pc = pytest.importorskip("padcontroller")
    b = pc.Bridge()
    b.set_game("metallica_spike")
    b._read_cabinet(_tables(tmp_path), kit=kit)
    return pc, b


def _data(pc, levels):
    data = bytearray(pc.READ_N)
    for (node, idx), v in levels.items():
        data[20 + node * 96 + idx] = v
    return bytes(data)


def test_bridge_sends_the_buttons_to_dof_as_e_events(tmp_path):
    kit = padcabinet.update({}, dof_start=190, dof_lockdown=191)
    pc, b = _bridge(tmp_path, kit)
    dof = FakeDOF()
    assert b.dof_init("mtl_180h", "x.vpx", factory=lambda: dof)
    b._poll_dof(_data(pc, {(1, 2): 255, (1, 5): 120}))      # start lit, lockdown red
    b._poll_dof(_data(pc, {(1, 2): 255, (1, 5): 120}))      # unchanged: nothing again
    b._poll_dof(_data(pc, {(1, 7): 40}))                    # start out, lockdown blue
    b.dof_finish()
    e = [g for g in dof.got if g[0] == "E"]
    assert e == [("E", 190, 255), ("E", 191, 120), ("E", 190, 0), ("E", 191, 40)]
    # no numbers set: no E events at all
    pc, b = _bridge(tmp_path / "2", {})
    dof = FakeDOF()
    b.dof_init("mtl_180h", "x.vpx", factory=lambda: dof)
    b._poll_dof(_data(pc, {(1, 2): 255}))
    b.dof_finish()
    assert not [g for g in dof.got if g[0] == "E"]


def test_bridge_lights_the_backglass_bulbs_with_backbox_gi(tmp_path):
    kit = padcabinet.set_bulbs({}, "metallica_spike", ["g1", "g2"])
    pc, b = _bridge(tmp_path, kit)
    fake = FakeB2S()
    assert b.b2s_attach(fake, direct=True)
    b._poll_b2s(_data(pc, {}))                              # never lit yet: the backglass as B2S has it
    assert fake.got == []
    b._poll_b2s(_data(pc, {(0, 0): 200}))
    b._poll_b2s(_data(pc, {(0, 0): 180}))                   # still on: nothing again
    b._poll_b2s(_data(pc, {}))
    b.b2s_finish()
    assert fake.got == [("g1", 1), ("g2", 1), ("g1", 0), ("g2", 0)] and b.b2s is None
    # bulbs named for another title only: none set
    pc, b = _bridge(tmp_path / "2", padcabinet.set_bulbs({}, "jaws_le", ["g1"]))
    fake = FakeB2S()
    b.b2s_attach(fake, direct=True)
    b._poll_b2s(_data(pc, {(0, 0): 200}))
    b.b2s_finish()
    assert fake.got == []


def test_controller_com_hands_the_backglass_over(tmp_path):
    pc = pytest.importorskip("padcontroller")
    ctl = pc.PadController.__new__(pc.PadController)
    ctl.bridge = pc.Bridge()
    ctl.props = {}
    seen = []
    ctl.bridge.b2s_attach = lambda obj: seen.append(obj) or True
    ctl.bridge.b2s_finish = lambda: seen.append("finish")
    assert ctl._get("padb2s", ("b2s",)) is True
    assert ctl._get("padb2s", (None,)) is False
    assert ctl._get("padb2sfinish", ()) is None
    assert seen == ["b2s", "finish"]


def test_patch_and_setup_write_the_res(tmp_path, monkeypatch):
    import padlaunch
    import padvpx
    import vpxsetup
    kit_path = tmp_path / "kit.json"
    monkeypatch.setattr(padlaunch, "KIT", str(kit_path))
    tables = tmp_path / "tables"
    tables.mkdir()
    for name in ("Jaws (PAD).vpx", "Godzilla (PAD).vpx"):
        (tables / name).write_bytes(b"")
    (tables / "Jaws (PAD).directb2s").write_text('<DirectB2SData><Bulb Name="g1"/></DirectB2SData>',
                                                encoding="utf-8")
    got = vpxsetup.set_cabinet({"backglass": 2, "dof_start": 190}, tables_dir=str(tables), mons=MONS)
    assert got["cabinet"]["backglass"] == 2 and got["cabinet"]["dof_start"] == 190
    assert [m["n"] for m in got["cabinet"]["screens"]] == [1, 2, 3]
    assert got["cabinet"]["suggested"] == {"start": 190, "lockdown": 191}
    # only the table with a backglass beside it gets a .res
    assert (tables / "Jaws (PAD).res").exists() and not (tables / "Godzilla (PAD).res").exists()
    assert json.load(open(kit_path))["cabinet"]["backglass"] == 2
    assert vpxsetup.table_bulbs("Jaws (PAD).vpx", "jaws_le", tables_dir=str(tables)) == {
        "names": ["g1"], "chosen": [], "backglass": "Jaws (PAD).directb2s"}
    assert vpxsetup.set_bulbs("jaws_le", ["g1"])["chosen"] == ["g1"]
    assert vpxsetup.table_bulbs("Jaws (PAD).vpx", "jaws_le", tables_dir=str(tables))["chosen"] == ["g1"]
    assert vpxsetup.table_bulbs("Godzilla (PAD).vpx", "godzilla_le", tables_dir=str(tables))["names"] == []
    # the patch step: the same .res, never in the patch's way
    (tables / "Jaws (PAD).res").unlink()
    said = padvpx.cabinet_res(str(tables / "Jaws (PAD).vpx"), mons=MONS)
    assert (tables / "Jaws (PAD).res").exists() and "screen 2" in said[0]
    assert padvpx.cabinet_res(str(tables / "nowhere" / "x.vpx"), mons=MONS)[0].startswith("backglass screen not set")
    src = open(os.path.join(VPX, "padvpx.py"), encoding="utf-8").read()
    assert src.index("b2s = copy_backglass(table_path, out)") < src.index("for line in cabinet_res(out):")


_HARNESS = r'''
Class FakeB2S
	Public Sub Run : WScript.Echo "run" : End Sub
	Public Sub [Stop] : WScript.Echo "stop" : End Sub
	Public Property Let B2SName(v) : WScript.Echo "name" : End Property
End Class
Class FakePad
	Public Sub PadB2S(o) : WScript.Echo "handed " & TypeName(o) : End Sub
	Public Sub PadB2SFinish : WScript.Echo "taken" : End Sub
End Class
Dim Controller, NoB2S, ForceOff, VPBuildVersion, cGameName
VPBuildVersion = 10800 : ForceOff = 0 : cGameName = "metallica_spike"
Function PadNewB2S
	If NoB2S Then Err.Raise 429, "x", "ActiveX component can't create object" : Exit Function
	Set PadNewB2S = New FakeB2S
End Function
Function Setting(s, k)
	If k = "ForceDisableB2S" Then Setting = ForceOff Else Setting = 0
End Function
'''


@pytest.mark.skipif(not (sys.platform == "win32" and shutil.which("cscript")),
                    reason="runs PADSPIKE2.vbs under cscript")
@pytest.mark.parametrize("pre, want", [
    ("Set Controller = New FakePad", ["name", "run", "handed", "FakeB2S", "taken", "stop"]),
    ("Set Controller = New FakePad : NoB2S = True", ["taken"]),     # no B2S: nothing handed
    ("", ["name", "run", "stop"]),                                   # an older controller: as before
])
def test_padspike2_hands_b2s_to_the_controller(tmp_path, pre, want):
    import subprocess
    sysvbs = open(os.path.join(VPX, "PADSPIKE2.vbs"), encoding="utf-8").read()
    sysvbs = sysvbs.replace('CreateObject("B2S.Server")', "PadNewB2S")
    (tmp_path / "sys.vbs").write_text(sysvbs, encoding="latin-1")
    vbs = tmp_path / "t.vbs"
    vbs.write_text("\n".join([_HARNESS,
                              'ExecuteGlobal CreateObject("Scripting.FileSystemObject").OpenTextFile("%s").ReadAll'
                              % str(tmp_path / "sys.vbs"), pre, "PadStartB2S", "PadStopB2S"]), encoding="latin-1")
    env = dict(os.environ, TEMP=str(tmp_path), TMP=str(tmp_path))
    r = subprocess.run(["cscript", "//nologo", str(vbs)], capture_output=True, text=True, timeout=60, env=env)
    assert not r.stderr.strip(), r.stdout + r.stderr
    assert r.stdout.split() == want
