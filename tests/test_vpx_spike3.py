"""The Spike 3 rig behind PAD.Controller (PAD-1560): a Visual Pinball table
of a Spike 3 title (The Walking Dead Remastered) starts and plays a Spike 3
run the way a Spike 2 table plays a Spike 2 one.

A Spike 3 run is Spike 2-shaped for the controller - s3leds.py fills
dump/padled at padled.h's offsets and s3keys.py merges dump/padsw into the
node inputs - so what is worth failing on is only what differs, none of it
needing a run:

  * THE RUN: found by its own board record (spike3-<n>.run, its slot
    directory as `root`), never one gone stale with WSL; its switch table is
    the slot's tables/game/switch_list.txt, which no other slot seeds.
  * THE LAUNCH: s3launch.sh as root on a Spike 3 slot nobody runs or leases,
    the user's own OTP key file, the kit's label in the game window's title,
    Guided Setup walked (the player is at the table, not the game's buttons);
    a run is up at s3prog.py's `progress run` line.
  * THE BALLS: the run's ball model stands aside while the controller's
    dump/ballfeed.off is there, and serves the trough again once it goes.
  * THE BOOT LINE: Guided Setup's time on the screen does not count toward
    s3prog.py giving up, so "run" still comes after a slow Save & Exit.
"""
import json
import os
import pathlib
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
VPX = ROOT / "tools" / "spike2_emu" / "vpx"
S3 = ROOT / "tools" / "spike3_emu"
for p in (ROOT / "tools" / "spike2_emu", VPX, S3):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
pytestmark = pytest.mark.skipif(not VPX.is_dir(), reason="rig not present")

import padlaunch  # noqa: E402

TITLE = "walking_dead_remastered_le"


def _post(board, slot, game, label="PAD-VPX", started=100, age=0):
    rec = {"emu": "spike3", "slot": slot, "game": game, "title": "", "label": label,
           "distro": "Ubuntu", "pid": 1, "started": started, "hidden": False, "audio": True,
           "root": "/var/tmp/pad-s3/slot%d" % slot}
    path = board / ("spike3-%d.run" % slot)
    path.write_text(json.dumps(rec))
    if age:
        t = time.time() - age
        os.utime(path, (t, t))
    return rec


# ------------------------------------------------------------------ the run --

def test_a_spike3_run_is_found_by_title_or_slot_and_never_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(padlaunch, "BOARD", str(tmp_path))
    _post(tmp_path, 2, "fallout_le")
    _post(tmp_path, 5, TITLE, started=100)
    _post(tmp_path, 6, TITLE, started=200)
    _post(tmp_path, 4, TITLE, started=300, age=padlaunch.RUN_FRESH_S + 60)   # WSL took it down
    assert padlaunch.spike3_record(TITLE)["slot"] == 6          # the newest live one
    assert padlaunch.spike3_record(slot=2)["game"] == "fallout_le"
    assert padlaunch.spike3_record(slot=4) is None
    assert padlaunch.spike3_record("pokemon_le") is None


def test_the_controller_finds_the_run_and_its_switch_table(tmp_path, monkeypatch):
    pc = pytest.importorskip("padcontroller")
    monkeypatch.setattr(padlaunch, "BOARD", str(tmp_path))
    monkeypatch.setenv("PAD_ROOT_WSL", "/home/pad/spike2root")     # the app's own Spike 2 rig
    monkeypatch.setenv("PAD_WSL_DISTRO", "PAD-Runtime")
    _post(tmp_path, 7, TITLE)
    rig = pc.Rig(TITLE, emu="spike3")
    assert rig.root == "/var/tmp/pad-s3/slot7" and rig.distro == "Ubuntu" and rig.slot == 7
    # the dump dir is a \\wsl.localhost path whatever the host (the
    # controller runs on Windows), so read it with either separator
    assert rig.led_path().replace("\\", "/").endswith("slot7/dump/padled")
    assert rig.sw_path().replace("\\", "/").endswith("slot7/dump/padsw")
    # the switch table is the slot's tables/game, whatever the title
    tables = tmp_path / "slot7"
    (tables / "dump").mkdir(parents=True)
    (tables / "tables" / "game").mkdir(parents=True)
    (tables / "tables" / "game" / "switch_list.txt").write_text(
        "13 13 1 11 START BUTTON\n64 64 8 37 TROUGH 1\n")
    rig.dump = str(tables / "dump")
    seeded = []
    monkeypatch.setattr(rig, "seed_switch_list", lambda *a: seeded.append(a))
    assert rig.switch_ids(TITLE) == {(1, 11): 13, (8, 37): 64}
    assert seeded == []
    # a Spike 2 title's Rig keeps the environment's rig and the board's slot-N.run
    assert pc.Rig("godzilla_le").root == "/home/pad/spike2root"


def test_a_spike3_map_runs_the_spike2_path_on_the_spike3_board(tmp_path, monkeypatch):
    pc = pytest.importorskip("padcontroller")
    (tmp_path / ("%s.shadow.json" % TITLE)).write_text(json.dumps(
        {"platform": "spike3", "title": TITLE, "cabinet": {"start": 1013}}))
    monkeypatch.setattr(pc, "USER_MAPS", str(tmp_path))
    m = pc.VpxMap(TITLE)
    assert m.platform == "spike3"
    b = pc.Bridge.__new__(pc.Bridge)
    b.map = m
    assert b.emu == "spike3" and not b.slots      # padled / padsw, not a block of slots
    b.map = pc.VpxMap("godzilla_le")
    assert b.emu == "spike2"


# --------------------------------------------------------------- the launch --

def test_the_launch_takes_a_spike3_slot_nobody_runs_or_leases(tmp_path, monkeypatch):
    monkeypatch.setattr(padlaunch, "BOARD", str(tmp_path))
    monkeypatch.setattr(padlaunch, "distro", lambda: "Ubuntu")
    _post(tmp_path, 7, "pokemon_le", label="PAD-1327")
    (tmp_path / "slot-6.lock").write_text("holder=PAD-1415 doing=fallout run\n")
    _post(tmp_path, 5, "fallout_le", age=padlaunch.RUN_FRESH_S + 60)      # stale: free
    launch = padlaunch.launch_for("spike3", TITLE, r"D:\cards\twd.raw")
    assert isinstance(launch, padlaunch.Spike3Launch)
    assert launch.take_slot() == 5
    for n in (5, 4):
        _post(tmp_path, n, "x", label="PAD-1415")
    with pytest.raises(RuntimeError, match="every Spike 3 rig slot"):
        launch.take_slot()


def test_the_launch_hands_the_users_key_and_labels_the_window(tmp_path, monkeypatch):
    monkeypatch.setattr(padlaunch, "BOARD", str(tmp_path))
    monkeypatch.setattr(padlaunch, "distro", lambda: "Ubuntu")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(padlaunch, "kit_load", lambda: {})
    cards = tmp_path / "cards"
    cards.mkdir()
    card = cards / ("%s-0_92_0.Release.64G.sdcard-secure.raw" % TITLE)
    card.write_bytes(b"")
    # a padkeys.json with only the .spk key is not the store's key
    (cards / "padkeys.json").write_text(json.dumps({"spk_keyfile": "k"}))
    assert padlaunch.spike3_keyfile(str(card)) is None
    (tmp_path / ".pad").mkdir()
    own = tmp_path / ".pad" / "spike3_padkeys.json"
    own.write_text(json.dumps({"otp_keyfile": "x"}))
    assert padlaunch.spike3_keyfile(str(card)) == str(own)
    launch = padlaunch.Spike3Launch(TITLE, str(card))
    launch.slot = 7
    env, _ = launch.env()
    assert "PAD_TITLE_TAG=[rig 7: PAD-VPX]" in env and "PAD_LABEL=PAD-VPX" in env
    assert "PAD_S3_AUTOGUIDE=walk" in env
    args = launch.args("/mnt/d/twd.raw")
    assert args[:4] == ["/mnt/d/twd.raw", "7", "240", "--audio"]
    assert args[4] == "--keyfile"
    launch.audio = False
    assert "--audio" not in launch.args("/mnt/d/twd.raw")


def test_a_spike3_card_is_the_secure_image_in_the_spike3_library(tmp_path, monkeypatch):
    lib = tmp_path / "Stern" / "spike2"
    lib.mkdir(parents=True)
    s3 = tmp_path / "Stern" / "spike3"
    s3.mkdir()
    old = s3 / ("%s-0_90_0.Release.64G.sdcard-secure.raw" % TITLE)
    new = s3 / ("%s-0_92_0.Release.64G.sdcard-secure.raw" % TITLE)
    for p in (old, new, s3 / "pokemon_le-0_82_0.Release.64G.sdcard-secure.raw"):
        p.write_bytes(b"")
    monkeypatch.delenv("PAD_VPX_CARD", raising=False)
    monkeypatch.delenv("PAD_VPX_LIBRARY", raising=False)
    monkeypatch.setattr(padlaunch, "kit_load", lambda: {"library": str(lib)})
    assert padlaunch.card_for(TITLE, "spike3") == str(new)


def test_the_boot_is_read_off_the_runs_progress_lines(tmp_path):
    log = tmp_path / "padvpx.log"
    log.write_text("an earlier run's lines\n[s3run] progress run 100 Running\n")
    boot = padlaunch.Spike3Boot(str(log), start=log.stat().st_size)
    assert boot.poll() is None                     # that "run" was the last run's
    with open(log, "a") as f:
        f.write("s3launch: starting slot 7 for 240 min\n")
    assert boot.poll() == ("booting", 5, "starting slot 7 for 240 min")
    with open(log, "a") as f:
        f.write("[s3run] progress nodes 80 Node boards found (8 of 8); the game is starting\n")
    assert boot.poll() == ("booting", 80, "Node boards found (8 of 8); the game is starting")
    with open(log, "a") as f:
        f.write("[s3run] progress run 100 Running - the game is in attract\n")
    assert boot.poll()[0] == "attract"
    failed = padlaunch.Spike3Boot(str(log), start=log.stat().st_size)
    with open(log, "a") as f:
        f.write("s3launch: failed - no OTP key for this card\n")
    assert failed.poll() == ("booting", 0, "Stuck: no OTP key for this card")


# ---------------------------------------------------------------- the balls --

def test_the_ball_model_stands_aside_while_the_table_owns_the_balls(tmp_path, monkeypatch):
    import s3balls
    monkeypatch.setattr(s3balls, "ALIVE_S", 0)
    devs = [("TROUGH 2", 8, 36, "switch"), ("TROUGH 1", 8, 37, "switch"),
            ("SHOOTER LANE", 8, 28, "switch"), ("TROUGH", 8, 1, "coil"),
            ("AUTO PLUNGER", 8, 4, "coil")]
    (tmp_path / "dump").mkdir()
    sw = bytearray(512)
    b = s3balls.Balls(sw, s3balls.resolve(devs), d=str(tmp_path))
    b.coil(8, [0x40, 1, 0, 0])                     # the eject coil's configuration
    home = b.home()
    off = tmp_path / "dump" / "ballfeed.off"
    off.write_text("PAD.Controller\n")
    b._aside = (0.0, False)
    b.coil(8, [0x40, 1])                           # a fire: the table's to answer
    assert b.due == [] and b.home() == home
    off.unlink()
    b._aside = (0.0, True)
    b.coil(8, [0x40, 1])
    assert b.due, "the model serves the trough again once the table lets go"


# ------------------------------------------------------------ the boot line --

def test_guided_setups_time_on_screen_does_not_end_the_report(monkeypatch, tmp_path, capsys):
    import s3prog
    clock = [1000.0]
    monkeypatch.setattr(s3prog.time, "time", lambda: clock[0])
    monkeypatch.setattr(s3prog.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    monkeypatch.setattr(s3prog, "state", lambda sd: (8, 8, 50))
    start = clock[0]
    # Guided Setup up for 700 s - longer than GIVE_UP_S - then Save & Exit
    monkeypatch.setattr(s3prog, "guided",
                        lambda sd: "showing" if clock[0] - start < 700 else "clear")
    monkeypatch.setattr(sys, "argv", ["s3prog.py", str(tmp_path)])
    assert s3prog.GIVE_UP_S < 700
    s3prog.main()
    out = capsys.readouterr().out
    assert "Guided Setup is waiting for you" in out
    assert out.strip().splitlines()[-1].startswith("[s3run] progress run 100")


def test_a_table_started_run_walks_guided_setup():
    """s3run.sh: a window run only watches Guided Setup, unless the launch
    asked it walked (PAD_S3_AUTOGUIDE=walk); 0 still turns both off."""
    text = (S3 / "s3run.sh").read_text(encoding="utf-8")
    assert '[ "${PAD_S3_AUTOGUIDE:-1}" != 0 ]' in text
    assert '[ "$WINDOW" = 1 ] && [ "${PAD_S3_AUTOGUIDE:-1}" != walk ]' in text


# ------------------------------------------- the Walking Dead table (25269) --

def _twd_map():
    return json.load(open(VPX / "walking_dead_remastered_le.vpxmap.json", encoding="utf-8"))


def test_a_raw_lamp_on_several_leds_reads_the_brightest(tmp_path):
    """PAD-1560: a SAM table's one-colour insert on an RGB insert of the
    Remastered game reads the brightest of its three channels, 0..255."""
    pc = pytest.importorskip("padcontroller")
    mapping = tmp_path / "raw.vpxmap.json"
    mapping.write_text(json.dumps({"raw_lamp_rewrite": {
        "25": [[8, 35], [8, 36], [8, 37]], "4": [8, 66]}}), encoding="utf-8")
    vm = pc.VpxMap(None)
    vm.load(str(mapping))
    assert vm.raw_lamp_rewrite == {25: ((8, 35), (8, 36), (8, 37)), 4: (8, 66)}
    b = pc.Bridge.__new__(pc.Bridge)
    b.map, b.lamp_state, b.lamp_pending = vm, {}, set()
    b.lock = __import__("threading").Lock()
    data = bytearray(20 + 16 * 96)
    data[20 + 8 * 96 + 36] = 180                   # only the green channel lit
    data[20 + 8 * 96 + 66] = 40
    b._poll_lamps(bytes(data))
    assert b.lamp(25) == 180 and b.lamp(4) == 40
    for bad in ([[8, 35], [8]], [], [[8, 35], "x"]):
        mapping.write_text(json.dumps({"raw_lamp_rewrite": {"25": bad}}), encoding="utf-8")
        with pytest.raises(ValueError, match="raw_lamp_rewrite"):
            pc.VpxMap(None).load(str(mapping))


def test_walking_dead_gets_only_lamp_numbers_its_arrays_hold(tmp_path):
    """PAD-1560 (Mike: "Subscript out of range: 'ii'"): the table's LampTimer
    indexes PFInsertState(220) with every ChangedLamps number, so its map turns
    off the 1000 + node * 100 + index LED numbers; a map without the switch
    still reports them."""
    pc = pytest.importorskip("padcontroller")
    data = bytearray(20 + 16 * 96)
    for i in range(20, len(data)):
        data[i] = 200                                  # every LED lit
    for path, led_lamps in ((str(VPX / "walking_dead_remastered_le.vpxmap.json"), False),
                            (None, True)):
        vm = pc.VpxMap(None)
        if path:
            vm.load(path)
        else:
            plain = tmp_path / "plain.vpxmap.json"
            plain.write_text(json.dumps({"raw_lamp_rewrite": {"25": [8, 35]}}), encoding="utf-8")
            vm.load(str(plain))
        assert vm.led_lamps is led_lamps
        b = pc.Bridge.__new__(pc.Bridge)
        b.map, b.lamp_state, b.lamp_pending = vm, {}, set()
        b.lock = __import__("threading").Lock()
        b._poll_lamps(bytes(data))
        nums = [n for n, _ in b.changed_lamps()]
        if led_lamps:
            assert max(nums) >= 1000
        else:
            assert nums and max(nums) <= 220 and len(nums) == len(vm.raw_lamp_rewrite)


def test_the_walking_dead_map_is_whole():
    """Every number the table uses is the Remastered game's or a known gap,
    every flasher a lamp of the map's own that the table's arrays hold, the
    prison doors one coil for SAM 3 and 4."""
    pc = pytest.importorskip("padcontroller")
    m = _twd_map()
    vm = pc.VpxMap(None)
    vm.load(str(VPX / "walking_dead_remastered_le.vpxmap.json"))
    assert m["platform"] == "spike3" and m["detect"] and "twd_160h" in m["detect"]
    rw = {int(k): v for k, v in m["switch_rewrite"].items() if k != "_"}
    used = {1, 2, 3, 4, 9, 10, 11, 16, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31,
            32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52,
            70, 71, 72}
    assert used <= set(rw), "every SAM switch the table writes is mapped (or dropped as 0)"
    live = [v for v in rw.values() if v]
    assert len(live) == len(set(live)), "two SAM switches on one Remastered switch"
    assert rw[21] == 64 and rw[18] == 61 and rw[23] == 55 and rw[16] == 13 and rw[71] == 10
    assert set(m["notes"] if "notes" in m else m["switch_notes"]) >= {str(n) for n in rw}
    sols = {int(k): tuple(v["coil"]) for k, v in m["solenoids"].items() if k != "_"}
    assert sols[3] == sols[4] and sols[1] == (8, 1) and sols[2] == (8, 4)
    assert sols[48] == tuple(m["game_on"]["coils"][0]) and sols[46] == tuple(m["game_on"]["coils"][1])
    flash = {int(k) for k in m["flash_subs"] if k != "_"}
    assert flash == set(range(211, 219)) and flash <= set(vm.raw_lamp_rewrite)
    assert max(vm.raw_lamp_rewrite) <= 220, "the table's lamp arrays are 0 to 220"
    for n in (152, 153, 154, 133, 134, 135, 120, 121, 122, 106, 107):
        assert n in vm.raw_lamp_rewrite


SAM_SCRIPT = """Option Explicit
ExecuteGlobal GetTextFile("controller.vbs")
If Err Then MsgBox "You need the controller.vbs in order to run this table, available in the vp10 package"
Const UseVPMModSol = 2
Const cGameName = "twd_160h" \t 'The unique alphanumeric name for this table
LoadVPM "01560000", "sam.VBS", 3.10
Const UseSolenoids = 1
Const UseLamps = 0
Sub Table1_Init
\tvpmNudge.TiltSwitch = -7
\tInitVpmFFlipsSAM
\tIf Err Then MsgBox "You need the latest sam.vbs in order to run this table, available from vp10.5 and higher"
End Sub
SolCallback(15)    = "SolLFlipper"
SolCallback(16)    = "SolRFlipper"
Sub Dazz_Motor(enabled)
\tDim xlss
\tIf enabled Then
\t\tcbdir = 1 : Darryl.enabled = 1
\tElse
\t\tDarryl.enabled = 0\t
\tEnd If
End Sub

Dim cbdir, ckdir, ccount : cbdir = 1
Dim CBDist: CBDist = Distance(Cannon_Load.x, Cannon_Load.y, BM_crossbow.x, BM_crossbow.y)
Dim CBDrop, CBrotZ: CBDrop = 0 : CBRotZ = 55 + 125

Sub Darryl_Timer()
\tDim nrx
\tPlaySound SoundFX("bridge2",DOFGear), , 0.001
\tckdir = CBRotZ - 180
\tSelect Case cbdir
\tCase 1:
\t\tIf CBRotZ => 127 Then
\t\t\tController.Switch(50) = 0 : Controller.Switch(52) = 0
\t\t\tIf CBDrop < 85 Then CBDrop = CBDrop + 2.5
\t\tEnd If
\t\tIf CBRotZ => 160 Then Controller.Switch(51) = 1
\t\tIf CBRotZ => 198 Then cbdir = 3
\t\tCBRotZ = CBRotZ + 0.2 + Rnd(1) * 0.3
\t\tFor Each nrx in BP_crossbow : nrx.RotZ = CBRotZ - 180.5: Next : crossshadow.RotZ = CBRotZ - 180.5
\tCase 2:
\t\tIf CBRotZ <= 127 Then
\t\t\tController.Switch(50) = 1
\t\t\tIf Not isEmpty(CBBall) Then Controller.Switch(52) = 1
\t\tEnd If
\t\tIf CBRotZ <= 160 Then Controller.Switch(51) = 0
\t\tIf CBRotZ <= 124.8 Then
\t\t\tCBRotZ = 125
\t\t\tFor Each nrx in BP_crossbow : nrx.RotZ = CBRotZ - 180.5: Next : crossshadow.RotZ = CBRotZ - 180.5
\t\t\tme.enabled = 0
\t\tEnd If
\t\tCBRotZ = CBRotZ - 0.2 - Rnd(1) * 0.3
\t\tFor Each nrx in BP_crossbow : nrx.RotZ = CBRotZ - 180.5: Next : crossshadow.RotZ = CBRotZ - 180.5
\tCase 3:
\t\tIf ccount = 20 Then cbdir = 2 : ccount = -1
\t\tccount = ccount + 1
\tEnd Select
\tIf not isEmpty(CBBall) Then
\t\tCBBall.x = (CBDist - CBDrop) * dCos(CBRotZ + 90) + BM_crossbow.x
\t\tCBBall.y = (CBDist - CBDrop) * dSin(CBRotZ + 90) + BM_crossbow.y
\tElse
\t\tCBDrop = 0
\tEnd If
End Sub

Dim CBBall

Sub Cannon_Load_Hit()
\tWireRampOff\t 'Turn off the Plastic Ramp Sound
\tSoundSaucerLock
\tSet CBBall = Activeball
\tController.Switch(52) = 1
End Sub

Sub Shoot_Cannon(Enabled)
\tIf Enabled Then
\t\tdim kang
\t\tIf cbdir = 1 Then kang = 0.8 Else kang = -0.8
\t\tkang = kang + CBRotZ - 180
\t\tSoundSaucerKick 1, BM_crossbow
\t\tCannon_Load.kick kang, 50, 0.05
\t\tCBBall = Empty
\tEnd If
End Sub
Sub LampTimer_Timer()
\tDim chgLamp, ii, cnt : chgLamp = Controller.ChangedLamps
\tIf Not IsEmpty(chgLamp) Then
\t\tFor cnt = 0 To UBound(chgLamp)
\t\t\tii = chglamp(cnt,0) : PFInsertState(ii) = chglamp(cnt,1) / 255
\t\tNext
\tEnd If
End Sub
"""


def test_the_patcher_rewires_the_tables_script():
    import patch_walking_dead as pw
    m = _twd_map()
    text, rep = pw.patch_script(SAM_SCRIPT, m)
    assert 'ExecuteGlobal GetTextFile("PADSPIKE2.vbs")' in text
    assert 'Const cGameName = "walking_dead_remastered_le"' in text and 'PadB2SName = "twd_160h"' in text
    assert "swStartButton = 1013 : swTilt = 1015" in text and "swLRFlip = 1052 : swLLFlip = 1053" in text
    assert 'LoadVPM "01000000", "PADSPIKE2.vbs", 3.10' in text and "sam.VBS" not in text
    assert "InitVpmFFlipsSAM" not in text.replace("' PAD: no SAM fast-flip", "")
    assert "SolCallback(sLLFlipper)" in text and "SolCallback(sRFlipper)" not in text
    assert "If PadFlash.Exists(CStr(ii)) Then PadFlashCall ii, PFInsertState(ii)" in text
    assert "\tPadEncStep cbdir" in text and "Controller.Switch(1039)" in text
    assert 'PadFlash.Add "211", GetRef("WellWalkerFlash")' in text
    assert "Controller.Switch(1060) = 1" in text and "Controller.Switch(1059) = 1" in text
    assert "Sub Table1_Exit" in text and "PadStopB2S" in text
    with pytest.raises(SystemExit, match="encoder"):
        pw.patch_script(SAM_SCRIPT.replace("Sub Darryl_Timer()", "Sub Other_Timer()"), m)


def test_the_walking_dead_crossbow_rests_at_home_and_sweeps_like_a_motor():
    """PAD-1560 (Mike): the crossbow stood straight up between the flippers. The
    table starts it out (RotZ 180) for the SAM ROM to home at power-on, which
    the Remastered game never does in attract; and the game stops and restarts
    the motor mid-sweep, which the table's Dazz_Motor took as a new aim outward."""
    import patch_walking_dead as pw
    text, _ = pw.patch_script(SAM_SCRIPT, _twd_map())
    assert "CBDrop = 0 : CBRotZ = 125\t' PAD: at home" in text
    assert "If CBRotZ <= 125.5 Then cbdir = 1" in text
    assert "cbdir = 1 : Darryl.enabled = 1" not in text
    assert "me.enabled = 0" not in text.split("Sub Darryl_Timer")[1].split("End Sub")[0]
    assert "Controller.Switch(50) = (CBRotZ <= 127)" in text
    for gone in ("Dim CBDrop, CBrotZ: CBDrop = 0 : CBRotZ = 55 + 125", "cbdir = 1 : Darryl.enabled = 1"):
        with pytest.raises(SystemExit, match="no cb"):
            pw.patch_script(SAM_SCRIPT.replace(gone, "' gone"), _twd_map())


@pytest.mark.skipif(sys.platform != "win32", reason="cscript runs the table's VBScript")
def test_the_patched_crossbow_carries_on_through_a_motor_restart(tmp_path):
    """The table's own patched crossbow code under cscript: it starts at home;
    a motor run sweeps out and back; the motor stopped and restarted on the
    way back carries it on home instead of swinging it out again."""
    import subprocess
    import patch_walking_dead as pw
    text, _ = pw.patch_script(SAM_SCRIPT, _twd_map())
    lines = text.split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.startswith("Sub Dazz_Motor"))
    end = next(i for i in range(start, len(lines)) if lines[i].startswith("Sub Cannon_Load_Hit"))
    enc0 = next(i for i, ln in enumerate(lines) if ln.startswith("Dim PadEncPh"))
    enc1 = next(i for i in range(enc0, len(lines)) if lines[i] == "End Sub")
    harness = "\n".join([
        "Class Sw : Public s(2000)",
        "  Public Property Let Switch(n, v) : s(n) = v : End Property",
        "  Public Property Get Switch(n) : Switch = s(n) : End Property",
        "End Class",
        "Class Obj : Public x, y, RotZ, enabled : End Class",
        "Dim Controller : Set Controller = New Sw",
        "Dim Cannon_Load, BM_crossbow, crossshadow, Darryl",
        "Set Cannon_Load = New Obj : Set BM_crossbow = New Obj : Set crossshadow = New Obj",
        "Set Darryl = New Obj",
        "Cannon_Load.x = 0 : Cannon_Load.y = 50 : BM_crossbow.x = 0 : BM_crossbow.y = 0",
        "Dim BP_crossbow : BP_crossbow = Array(crossshadow)",
        "Const DOFGear = 0",
        "Function Distance(a, b, c, d) : Distance = Sqr((a - c) ^ 2 + (b - d) ^ 2) : End Function",
        "Function dCos(a) : dCos = Cos(a * 3.14159265 / 180) : End Function",
        "Function dSin(a) : dSin = Sin(a * 3.14159265 / 180) : End Function",
        "Function SoundFX(a, b) : SoundFX = a : End Function",
        "Sub PlaySound(a, b, c) : End Sub",
    ] + lines[enc0:enc1 + 1] + lines[start:end] + [
        "Sub Run(n)",
        "  Dim i : For i = 1 To n : If Darryl.enabled Then Darryl_Timer",
        "  Next",
        "End Sub",
        "Dim peak, i",
        'WScript.Echo "start " & CBRotZ',
        "Dazz_Motor True : Run 280",
        'WScript.Echo "back " & cbdir & " " & Round(CBRotZ, 1)',
        "Dazz_Motor False : Dazz_Motor True",
        "peak = CBRotZ",
        "For i = 1 To 400",
        "  Run 1 : If CBRotZ > peak Then peak = CBRotZ",
        "  If Controller.Switch(50) Then Exit For",
        "Next",
        "Dazz_Motor False",
        'WScript.Echo "home " & Controller.Switch(50) & " " & Round(CBRotZ, 1) & " peak " & Round(peak, 1)',
    ])
    vbs = tmp_path / "xbow.vbs"
    vbs.write_text(harness, encoding="latin-1")
    out = subprocess.run(["cscript", "//nologo", str(vbs)], capture_output=True, text=True, timeout=60)
    got = out.stdout.split()
    assert out.returncode == 0, out.stdout + out.stderr
    assert got[:2] == ["start", "125"], out.stdout
    assert got[2] == "back" and got[3] == "2" and 127 < float(got[4]) < 198, out.stdout
    assert got[5] == "home" and got[6] in ("1", "True") and float(got[7]) <= 127, out.stdout
    assert float(got[9]) <= float(got[4]) + 0.01, out.stdout       # never swung out again


_S3_DEVICES = """# walking_dead_remastered_le device positions (Spike 3, s3pf.py).
# binary: spike3
# reader-rev 3
# class     name                                   x     y    w    h  grp index  conn   image
led       SPEAKER L 1-R                         24   196   30   30    3     1  -      System/TestMode/spike_3_speaker_panel
led       SPEAKER L 1-G                         24   196   30   30    3     0  -      System/TestMode/spike_3_speaker_panel
led       SPEAKER L 1-B                         24   196   30   30    3     2  -      System/TestMode/spike_3_speaker_panel
led       SPEAKER L 2-R                         30   218   30   30    3     4  -      System/TestMode/spike_3_speaker_panel
led       SPEAKER L 2-G                         30   218   30   30    3     3  -      System/TestMode/spike_3_speaker_panel
led       SPEAKER L 2-B                         30   218   30   30    3     5  -      System/TestMode/spike_3_speaker_panel
led       SPEAKER R 1-R                        591   196   30   30    3    61  -      System/TestMode/spike_3_speaker_panel
led       SPEAKER R 1-G                        591   196   30   30    3    60  -      System/TestMode/spike_3_speaker_panel
led       SPEAKER R 1-B                        591   196   30   30    3    62  -      System/TestMode/spike_3_speaker_panel
coil      SHAKER MOTOR                           0     0    0    0    6     0  -      System/TestMode/shaker_motor_cropped
led       START BUTTON                         102   228   30   30    6     2  -      System/TestMode/spike_2_no_tournament_cabinet_front_cropped
"""


def test_a_spike3_run_reads_the_cabinet_from_the_titles_own_tables(tmp_path, monkeypatch):
    """PAD-1560 (Mike: "does spike3 led signals work differently?"): the
    cabinet's DOF light strips and shaker were read from the run's
    tables/game, which holds only the switch list, so Walking Dead found no
    shaker and no speaker lights. The title's own folder has the card's
    device list and node directory."""
    pc = pytest.importorskip("padcontroller")
    monkeypatch.setattr(padlaunch, "BOARD", str(tmp_path))
    _post(tmp_path, 7, TITLE)
    rig = pc.Rig(TITLE, emu="spike3")
    slot = tmp_path / "slot7"
    (slot / "dump").mkdir(parents=True)
    (slot / "tables" / "game").mkdir(parents=True)
    (slot / "tables" / "game" / "switch_list.txt").write_text("13 13 1 11 START BUTTON\n")
    own = slot / "tables" / TITLE
    own.mkdir(parents=True)
    (own / "device_xy.txt").write_text(_S3_DEVICES)
    (own / "group_node_exact.txt").write_text("# group node\n3 7\n6 1\n7 8\n")
    (own / "node_ident.txt").write_text(
        "node=7 type=ws2812node group=3 name=ws2812node\nnode=1 type=pinnode group=6 name=pinnode\n"
        "node=8 type=pinnode group=7 name=pinnode\n")
    rig.dump = str(slot / "dump")
    rig.share = True
    assert rig.tables_dir(TITLE).replace("\\", "/").endswith("slot7/tables/game")
    assert rig.tables_dir(TITLE, own=True).replace("\\", "/").endswith("slot7/tables/" + TITLE)
    b = pc.Bridge.__new__(pc.Bridge)
    b.rig, b.map, b.title = rig, None, TITLE
    b._read_cabinet(kit={"cabinet": {"dof_shaker": 192, "dof_strips": 836}})
    assert b.cab_shaker == (1, 0)
    assert b.cab_strips and b.cab_strips["source"] == "speakers" and b.cab_strips["node"] == 7
    assert b.cab_strips["sides"][0][0] == {"R": (7, 1), "G": (7, 0), "B": (7, 2)}
