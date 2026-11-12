"""The original-layout LE conversion: synthetic script, no table assets."""
import json
import importlib.util
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VPX = os.path.join(ROOT, "tools", "spike2_emu", "vpx")
for p in (os.path.dirname(VPX), VPX, os.path.join(ROOT, "tools", "spike1_emu")):
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


def test_replica_slimer_position_flows_from_selected_map_to_controller_lamp(tmp_path, monkeypatch):
    from types import SimpleNamespace
    pc = pytest.importorskip("padcontroller")
    pl = pytest.importorskip("padlaunch")
    # The controller also imports Spike 2's rig, which has a different
    # nodebus.py. Load this platform's responder explicitly, as its own tests
    # do, rather than depending on whichever rig was imported first.
    spec = importlib.util.spec_from_file_location(
        "ghostbusters_spike1_nodebus", os.path.join(ROOT, "tools", "spike1_emu", "nodebus.py"))
    nb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nb)
    s1 = pytest.importorskip("s1bridge")
    state_model = pytest.importorskip("pinball_decryptor.plugins.stern.spike1_emulate")
    for module in (pc, pl):
        monkeypatch.setattr(module, "USER_MAPS", str(tmp_path / "no-user-overrides"))
    monkeypatch.setattr(pl, "kit_load", lambda: {})
    monkeypatch.setattr(pl, "win_python", lambda: "")
    monkeypatch.setattr(pl.padpath, "to_wsl", lambda p, d: p)
    launch = pl.Spike1Launch("ghostbusters_le_replica", "fixture.iso", dist="TestRuntime")
    launch.work = str(tmp_path)
    env, _ = launch.env()
    assert launch.title == "ghostbusters_le" and launch.map_title == "ghostbusters_le_replica"
    wiring = next(s.split("=", 1)[1] for s in env if s.startswith("S1_ENCODER_LAMPS="))
    state = state_model.HardwareState()
    now = [0.0]
    motors = nb.EncoderMotors(clock=lambda: now[0], position=nb.motor_lamp_publisher(
        SimpleNamespace(lamp_level=state.set_lamp), nb.encoder_lamp_outputs(wiring)))
    motors.note(8, b"\x51\x00\x45\x00\x00\x43\x44\x00")
    motors.note(8, b"\x55\x00\x8e\x00\x00")  # move to 142 encoder counts
    bridge = pc.Bridge()
    bridge.set_game("ghostbusters_le_replica")
    rig = s1.Spike1Rig.__new__(s1.Spike1Rig)
    rig.dump = str(tmp_path)
    bridge.rig, bridge.sw_ids = rig, {}
    assert bridge.native_title == "ghostbusters_le"
    for stamp, low, high in ((.3, 70, 71), (.7, 142, 142)):
        now[0] = stamp
        motors.status(8, 0)
        (tmp_path / "s1hw.state").write_bytes(state_model.StateBlock.pack(state, seq=1))
        bridge._poll_once_s1()
        assert low <= bridge.lamp(281) <= high


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
