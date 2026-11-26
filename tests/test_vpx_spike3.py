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
Sub Darryl_Timer()
\tDim nrx
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
    with pytest.raises(SystemExit, match="no encoder"):
        pw.patch_script(SAM_SCRIPT.replace("Sub Darryl_Timer()", "Sub Other_Timer()"), m)
