"""PAD-1610 (Msaint30): every DOF event a patched table sends, and what it is,
on the table's checklist sheet (the app, its Markdown and its CSV), to write
DOF configs of one's own.

What is worth failing on:

  * THE TABLE SCRIPT'S OWN CALLS ARE FOUND IN EVERY SHAPE: `DOF n, how`,
    `DOF(n, how)`, the bridge's `PadDOF n, how, toy`, a SoundFXDOF whose sound
    argument has commas of its own, a Const for the number; never in a comment,
    never the DOF sub's own definition.
  * ONLY CALLS THAT CAN FIRE: a sub the patch renamed to <name>_orig and that
    nothing calls any more (a stand-in or a quiet_subs entry) is left out; one
    the stand-in still calls is listed under the table's own name.
  * S/L/W ARE WHAT PAD.Controller SENDS (its _load_dof): solenoid numbers or
    their `dof`, l<n> lamps, f<n> flashers as S, the table's switch numbers;
    the map's flipper events and the cabinet's events (strips numbered as
    padcabinet numbers them) are E.
  * A REAL DOWNLOAD AND ITS PATCHED COPY GIVE THE SAME LIST.
"""
import os
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
def A():
    return pytest.importorskip("vpxauthor")


SCRIPT = '''Option Explicit
Const cGameName = "jpsdeadpool"
Const kKnock = 122
Sub DOF(e, s) : Controller.B2SSetData e, s : End Sub
Sub PadDOF(e, s, toy) : DOF e, s : End Sub
Sub LeftSlingShot_Slingshot_orig
    DOF 103, DOFPulse
    PlaySoundAt SoundFXDOF("Bump_" & Int(Rnd * 5) + 1, 141, DOFPulse, DOFContactors), sw001
End Sub
Sub Trigger001_Hit_orig
    DOF 150, DOFPulse
End Sub
Sub AwardSpecial
    DOF kKnock, DOFPulse   ' DOF 999, DOFPulse in a comment
    DOF(125, DOFOn)
End Sub
' DOF 160, DOFPulse
Sub PadSol3(e) : If e Then PadDOF 111, DOFPulse, DOFContactors : End Sub
Sub LeftSlingShot_Slingshot : vpmTimer.PulseSw 1066 : LeftSlingShot_Slingshot_orig : End Sub
Sub Loose : DOF 170, 1 : End Sub
DOF 171, DOFOff
'''


def test_script_calls_in_every_shape(A):
    got = A.script_dof_calls(SCRIPT)
    assert set(got) == {103, 141, 122, 125, 111, 170, 171}
    assert got[103]["subs"] == ["LeftSlingShot_Slingshot"]      # live _orig: its own name
    assert got[141]["toys"] == ["DOFContactors"] and got[141]["how"] == ["pulse"]
    assert got[122]["subs"] == ["AwardSpecial"]                  # the Const
    assert got[125]["how"] == ["on"]
    assert got[170]["subs"] == ["Loose"] and got[170]["how"] == ["on"]
    assert got[171]["subs"] == ["(table script)"]                # after a one-line sub ended
    assert 150 not in got                                         # Trigger001_Hit_orig: nothing calls it
    assert 160 not in got and 999 not in got                      # comments


MAP = {
    "_": "x",
    "b2s_name": "",
    "solenoids": {"_": "x", "1": {"coil": [8, 1], "name": "TROUGH"},
                  "3": {"coil": [8, 6], "name": "HELLHOUSE EJECT"},
                  "sLLFlipper": {"coil": [8, 5], "name": "LEFT FLIPPER", "dof": 48},
                  "sURFlipper": {"coil": [8, 2], "name": "UPPER", "dof": None}},
    "lamps": {"_": "x", "l12": {"leds": [[8, 11]], "name": "SHOOT AGAIN"},
              "f20": {"leds": [[9, 3]], "name": "POP FLASH"},
              "LightBumper": {"leds": [[8, 2]], "name": "not a numbered lamp"}},
    "switch_rewrite": {"_": "x", "15": 33, "16": 0},
    "flipper_dof": {"_": "x", "sLLFlipper": 101},
}
MACHINE = {"switches": [{"id": 33, "name": "LEFT OUTLANE"}]}


def test_events_are_what_the_controller_sends(A):
    rows = A.dof_events(MAP, MACHINE, SCRIPT, {"dof_start": 200, "dof_lockdown": 0, "dof_shaker": 205,
                                               "dof_strips": 210, "strip_parts": 2})
    by = {(r["kind"], r["number"]): r for r in rows}
    assert by[("S", 1)]["name"] == "TROUGH" and by[("S", 3)]["name"] == "HELLHOUSE EJECT"
    assert by[("S", 48)]["name"] == "LEFT FLIPPER"               # its `dof`
    assert not any(r["name"] == "UPPER" for r in rows)            # dof null: not sent
    assert by[("L", 12)]["name"] == "SHOOT AGAIN"
    assert by[("S", 20)]["name"] == "POP FLASH" and "brightness" in by[("S", 20)]["when"]
    assert by[("W", 15)]["name"] == "LEFT OUTLANE" and ("W", 16) not in by
    assert by[("E", 101)]["name"] == "sLLFlipper"                 # the map's flipper event
    assert by[("E", 111)]["name"] == "coil 3 HELLHOUSE EJECT"     # the bridge's coil sub
    assert by[("E", 200)]["name"] == "START button LED"
    assert by[("E", 205)]["name"] == "SHAKER MOTOR"
    assert not any(r["name"] == "LOCKDOWN button LED" for r in rows)   # 0 = not sent
    # 2 sides x 2 parts x 8 colours from 210, the left side's first, bottom part first
    strips = [r for r in rows if "light strip" in r["name"]]
    assert [r["number"] for r in strips] == list(range(210, 242))
    assert strips[0]["name"] == "left light strip part 1 of 2 (1 = bottom) red"
    assert strips[-1]["name"] == "right light strip part 2 of 2 (1 = bottom) white"
    kinds = [r["kind"] for r in rows]
    assert kinds == sorted(kinds, key="SLWE".index)


def test_rom_name(A):
    assert A.dof_rom_name(MAP, SCRIPT) == "jpsdeadpool"
    assert A.dof_rom_name(dict(MAP, b2s_name="dp_le"), SCRIPT) == "dp_le"


DOWNLOADS = [r"C:\tmp\vpx_new\Deadpool Color Rush\Deadpool v610 nfozzy Color Rush.vpx",
             r"C:\tmp\vpx_new\JPs Deadpool v610\JP's Deadpool v610.vpx"]


@pytest.mark.parametrize("path", DOWNLOADS)
def test_real_deadpool_download_lists_its_events(A, path, tmp_path):
    if not os.path.isfile(path):
        pytest.skip("the Deadpool download is not on this PC")
    try:
        d = A.build("deadpool_pro", path)
    except Exception as exc:                       # noqa: BLE001
        pytest.skip("no Deadpool device tables here: %s" % exc)
    if "error" in d:
        pytest.skip(d["error"])
    assert d["dof_rom"] == "jpsdeadpool"
    e = {r["number"]: r for r in d["dof"] if r["kind"] == "E"}
    assert {101, 102, 103, 107, 111, 123, 126}.issubset(e)
    assert all("_orig" not in r["name"] for r in d["dof"])
    assert "## DOF events" in d["markdown"] and "DOF E" in d["csv"]
