"""The original-layout LE conversion: synthetic script, no table assets."""
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VPX = os.path.join(ROOT, "tools", "spike2_emu", "vpx")
for p in (os.path.dirname(VPX), VPX):
    if p not in sys.path:
        sys.path.insert(0, p)
pytestmark = pytest.mark.skipif(not os.path.isdir(VPX), reason="rig not present")

MINI = '''Const cGameName = "spagb_100"
Const B2ScGameName = "spagb_100b2s"
Dim UseVPMDMD:UseVPMDMD = DesktopMode
Sub LoadSPAController()
Set Controller = CreateObject("VPinSPA.Controller")
End Sub
Sub Table1_Exit:Controller.Stop:End Sub
Sub ServiceKeys
Controller.Switch(0) = 1
Controller.Switch(-1) = 1
Controller.Switch(-2) = 1
Controller.Switch(-3) = 1
End Sub
Sub LampTimer_Timer()
    Dim chgLamp, ii, vid
    vid = False
    chgLamp = Controller.ChangedLamps
    If Not IsEmpty(chgLamp) Then
        For ii = 0 To UBound(chgLamp)
            LampState(chgLamp(ii, 0)) = chgLamp(ii, 1)
        Next
        if vid then
            WScript.Echo "video changed"
        End If
    End If
End Sub
'''


def test_replica_map_keeps_its_native_game_and_original_authors():
    patch = pytest.importorskip("patch_ghostbusters_le")
    with open(patch.MAP, encoding="utf-8") as f:
        m = json.load(f)
    assert m["title"] == "ghostbusters_le_replica" and m["game"] == "ghostbusters_le"
    assert m["platform"] == "spike1" and m["patcher"] == "patch_ghostbusters_le.py"
    assert m["table"]["by"] == "ninuzzu, tom tower and djrobx"
    assert m["switch_rewrite"]["78"] == 75 and m["cabinet"]["start"] == 1075
    assert m["solenoids"]["1"]["coil"] == [8, 1]
    assert m["raw_lamp_rewrite"]["198"] == [8, 6]
    assert m["raw_lamp_rewrite"]["281"] == [15, 63]
    assert m["encoder_lamps"] == {"8,0": [15, 63]}
    pc = pytest.importorskip("padcontroller")
    table_map = pc.VpxMap()
    table_map.load(patch.MAP)
    assert table_map.raw_lamp_rewrite[281] == (15, 63)
    with open(os.path.join(VPX, "ghostbusters_le.shadow.json"), encoding="utf-8") as f:
        jp = json.load(f)
    assert jp["detect"] == ["jp_ghostbusters"] and jp["output"] != m["output"]


def test_replica_patcher_replaces_spa_routes_service_and_preserves_unrelated_code():
    patch = pytest.importorskip("patch_ghostbusters_le")
    with open(patch.MAP, encoding="utf-8") as f:
        m = json.load(f)
    physics = '\nSub PhysicsStep : Ball.VelX = Ball.VelX * 0.9 : End Sub\n'
    out, _ = patch.patch_script(MINI + physics, m)
    assert 'Const cGameName = "ghostbusters_le_replica"' in out
    assert 'CreateObject("PAD.Controller")' in out and 'CreateObject("VPinSPA.Controller")' not in out
    assert 'Set B2SController = CreateObject("B2S.Server")' in out and 'B2SController.Stop' in out
    assert 'UseVPMDMD = False' in out
    assert all('Controller.Switch(%d)' % n in out for n in (9008, 9009, 9010, 9011))
    assert physics in out
    with pytest.raises(ValueError, match="expected one"):
        patch.patch_script(MINI.replace('Const cGameName = "spagb_100"', ''), m)


@pytest.mark.skipif(not (sys.platform == "win32" and shutil.which("cscript")), reason="executes the lamp loop")
def test_replica_lamp_arrays_ignore_native_and_negative_indices_but_keep_raw_values(tmp_path):
    patch = pytest.importorskip("patch_ghostbusters_le")
    with open(patch.MAP, encoding="utf-8") as f:
        m = json.load(f)
    out, _ = patch.patch_script(MINI, m)
    lamp = out[out.index("Sub LampTimer_Timer"):]
    harness = '''Class TestController
Public Property Get ChangedLamps
Dim data(3,1)
data(0,0) = 281 : data(0,1) = 71
data(1,0) = 1563 : data(1,1) = 200
data(2,0) = -1 : data(2,1) = 5
data(3,0) = 199 : data(3,1) = 128
ChangedLamps = data
End Property
End Class
Dim Controller, LampState(300)
Set Controller = New TestController
'''
    vbs = tmp_path / "lamps.vbs"
    vbs.write_text(harness + lamp + '\nLampTimer_Timer\nWScript.Echo LampState(281) & "," & LampState(199)\n', encoding="utf-8")
    r = subprocess.run(["cscript", "//nologo", str(vbs)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["71,128"]
