"""The virtual playfield's shaker panel (PAD-424): the cabinet's shaker motor, live.

The shaker is a cabinet coil with no place on the artwork, so the playfield window
shows it in its own panel, from padled version 5's drive table (what each coil is
driven at and for how long, PAD-381). What is worth failing on:

  * WHICH COIL: the table's SHAKER MOTOR row when it names one (group 5 index 0 on
    every table that does); group 5 index 0 when the table leaves the cabinet board
    out (godzilla); NONE on a Home Edition, whose whole machine is group 5.
  * THE DRIVE READ: padled.h's version-5 offsets, nothing from a version-4 block.
  * THE TIMING: the guest's `until` is on a clock the window cannot read, so a
    command runs from the frame its entry CHANGES in, for pulse + hold; an OFF ends
    it at once; what was already in the block when the window opened is not a shake.
"""
import os
import struct
import sys
import types

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
if RIG not in sys.path:
    sys.path.insert(0, RIG)

import coilmap  # noqa: E402

HDR = "# class name x y w h grp index conn image\n"


def _table(tmp_path, *rows):
    p = tmp_path / "device_xy.txt"
    p.write_text(HDR + "".join(r + "\n" for r in rows))
    return str(p)


def test_a_named_shaker_row_is_the_shaker(tmp_path):
    p = _table(tmp_path, "coil SHAKER MOTOR 0 0 0 0 5 0 - -",
               "coil COIN METER 0 0 0 0 5 2 - -",
               "coil TROUGH 260 613 20 20 6 1 - playfield")
    assert coilmap.shaker_address(p) == (1, 0)


#: godzilla_le's own group-5 rows: the cabinet board's lamps and buttons, on
#: the test menu's cabinet picture, and not one coil.
GODZILLA_CABINET = (
    "led COIN ENABLE 0 0 0 0 5 0 - -",
    "led COIN DOOR GI 268 255 30 30 5 1 - System/TestMode/spike_2_cabinet_front_cropped",
    "led START BUTTON 102 228 30 30 5 2 - System/TestMode/spike_2_cabinet_front_cropped",
    "led TOURNAMENT START 102 277 30 30 5 3 - System/TestMode/spike_2_cabinet_front_cropped",
    "led LOCKDOWN BUTTON-G 250 169 30 30 5 4 - System/TestMode/spike_2_cabinet_front_cropped",
    "led LOCKDOWN BUTTON-R 250 169 30 30 5 5 - System/TestMode/spike_2_cabinet_front_cropped",
    "led LOCKDOWN BUTTON-B 250 169 30 30 5 7 - System/TestMode/spike_2_cabinet_front_cropped",
    "switch LEFT COIN 261 334 30 30 5 16 - System/TestMode/spike_2_cabinet_front_cropped",
    "switch CENTER COIN 203 342 51 50 5 17 - System/TestMode/spike_2_cabinet_front_cropped",
    "switch RIGHT COIN 299 334 30 30 5 18 - System/TestMode/spike_2_cabinet_front_cropped",
)


def test_a_table_without_the_cabinet_board_gets_group_5_index_0(tmp_path):
    # godzilla_le: its table names no cabinet coil, and its game's drive 7 reached
    # the rig's board as node 1 coil 0 (PAD-414)
    p = _table(tmp_path, "coil TROUGH 260 613 20 20 6 1 - playfield",
               "coil VUK 132 43 20 20 7 1 - playfield", *GODZILLA_CABINET)
    assert coilmap.shaker_address(p) == (1, 0)


def test_the_cabinet_boards_lamps_and_buttons_are_not_a_use(tmp_path):
    # PAD-532: the group-5 LEDs and switches above are the cabinet board itself;
    # counting them hid the Shaker panel on godzilla_le and eleven other titles.
    # Only a group-5 COIL says group 5 is a playfield board.
    p = _table(tmp_path, "coil TROUGH 260 613 20 20 6 1 - playfield",
               *GODZILLA_CABINET)
    assert coilmap.shaker_address(p) == (1, 0)
    p = _table(tmp_path, "coil AUTO PLUNGER 219 453 20 20 5 4 - Test/pf",
               *GODZILLA_CABINET)
    assert coilmap.shaker_address(p) is None


def test_the_coin_door_lockout_is_not_a_use_of_the_cabinet_board(tmp_path):
    # PAD-367: devicexy now reads COIN ENABLE, a group-5 index-0 lamp every cabinet
    # carries; on beatles 1.29.0 it is the only group-5 row, and counting it turned
    # the shaker off. A real group-5 row still does.
    p = _table(tmp_path, "led COIN ENABLE 0 0 0 0 5 0 - -",
               "coil TROUGH 260 613 20 20 6 1 - playfield")
    assert coilmap.shaker_address(p) == (1, 0)
    p = _table(tmp_path, "led COIN ENABLE 0 0 0 0 5 0 - -",
               "coil AUTO PLUNGER 219 453 20 20 5 4 - Test/pf")
    assert coilmap.shaker_address(p) is None


def test_a_home_edition_has_no_shaker(tmp_path):
    p = _table(tmp_path, "coil AUTO PLUNGER 219 453 20 20 5 4 - Test/pf",
               "coil T-REX 98 111 20 20 5 6 - Test/pf")
    assert coilmap.shaker_address(p) is None


def test_no_table_no_shaker(tmp_path):
    assert coilmap.shaker_address(str(tmp_path / "device_xy.txt")) is None


def _block(version=5, until=0, pulse_t=0, hold_t=0, pulse_pwr=0, hold_pwr=0,
           node=1, idx=0, tps=100):
    b = bytearray(8192)
    struct.pack_into("<I", b, 0, coilmap.PADLED_MAGIC)
    struct.pack_into("<I", b, 4, version)
    o = node * 16 + idx
    struct.pack_into("<I", b, coilmap.DRIVE_TPS_OFF, tps)
    struct.pack_into("<I", b, coilmap.DRIVE_UNTIL_OFF + 4 * o, until)
    struct.pack_into("<H", b, coilmap.DRIVE_PULSE_T_OFF + 2 * o, pulse_t)
    struct.pack_into("<H", b, coilmap.DRIVE_HOLD_T_OFF + 2 * o, hold_t)
    b[coilmap.DRIVE_PULSE_PWR_OFF + o] = pulse_pwr
    b[coilmap.DRIVE_HOLD_PWR_OFF + o] = hold_pwr
    return bytes(b)


def test_the_drive_offsets_are_padled_h_s():
    hdr = open(os.path.join(RIG, "padled.h"), encoding="utf-8").read()
    for name, off in (("drive_t0", coilmap.DRIVE_T0_OFF), ("drive_tps", coilmap.DRIVE_TPS_OFF),
                      ("drive_until", coilmap.DRIVE_UNTIL_OFF),
                      ("drive_pulse_t", coilmap.DRIVE_PULSE_T_OFF),
                      ("drive_hold_t", coilmap.DRIVE_HOLD_T_OFF),
                      ("drive_pulse_pwr", coilmap.DRIVE_PULSE_PWR_OFF),
                      ("drive_hold_pwr", coilmap.DRIVE_HOLD_PWR_OFF),
                      ("drive_fires", coilmap.DRIVE_FIRES_OFF)):
        assert "%s %d" % (name, off) in hdr, name
    assert "drive_rule_fires %d" % (coilmap.DRIVE_READ - 4) in hdr


def test_the_drive_reads_ms_at_the_boards_tick_rate():
    got = coilmap.drive(_block(until=9000, pulse_t=150, pulse_pwr=31), 1, 0)
    assert got == {"until": 9000, "pulse_ms": 1500, "hold_ms": 0, "pulse_pwr": 31,
                   "hold_pwr": 0}
    assert coilmap.drive(_block(version=4, until=9000), 1, 0) is None
    assert coilmap.drive(_block()[:4776], 1, 0) is None


@pytest.fixture()
def watch():
    import playfield
    return playfield.ShakerWatch((1, 0))


def test_what_was_there_at_open_is_not_a_shake(watch):
    assert watch.tick(_block(until=500, pulse_t=150, pulse_pwr=31), 1000.0) == [0, 0, 0, 0, ""]
    assert watch.level(1100.0) == 0


def test_a_shake_runs_from_the_frame_it_changed_for_its_length(watch):
    watch.tick(_block(), 0.0)
    st = watch.tick(_block(until=7000, pulse_t=150, pulse_pwr=31), 1000.0)
    assert st == [31, 1500, 1500, 1, "1500 ms at 31/255"]
    assert watch.tick(_block(until=7000, pulse_t=150, pulse_pwr=31), 1016.0) is None
    assert watch.tick(_block(until=7000, pulse_t=150, pulse_pwr=31), 2450.0)[:2] == [31, 100]
    assert watch.tick(_block(until=7000, pulse_t=150, pulse_pwr=31), 2500.0)[:2] == [0, 0]


def test_an_off_ends_it_at_once(watch):
    watch.tick(_block(), 0.0)
    watch.tick(_block(until=7000, pulse_t=500, pulse_pwr=51), 1000.0)
    assert watch.tick(_block(until=0, pulse_t=500, pulse_pwr=51), 1200.0)[0] == 0
    assert watch.count == 1


def test_a_pulse_then_hold_drops_to_the_hold_power(watch):
    watch.tick(_block(), 0.0)
    st = watch.tick(_block(until=3000, pulse_t=3, hold_t=100, pulse_pwr=255, hold_pwr=40), 0.0)
    assert st[0] == 255 and st[2] == 1030 and st[4] == "1030 ms at 255/255, then 40/255"
    assert watch.tick(_block(until=3000, pulse_t=3, hold_t=100, pulse_pwr=255, hold_pwr=40),
                      100.0)[0] == 40


def test_the_same_shake_again_is_a_second_shake(watch):
    watch.tick(_block(), 0.0)
    watch.tick(_block(until=2000, pulse_t=20, pulse_pwr=51), 0.0)
    watch.tick(_block(until=2000, pulse_t=20, pulse_pwr=51), 300.0)
    st = watch.tick(_block(until=2400, pulse_t=20, pulse_pwr=51), 400.0)
    assert st[0] == 51 and st[3] == 2


def test_the_switch_list_view_has_the_shaker_panel_too(tmp_path, monkeypatch):
    """PAD-551 (peanuts): "missing shaker" on Aerosmith, Sword of Rage, Elvira,
    Foo Fighters, Guardians, Led Zeppelin, Mandalorian, Munsters, Rush, TMNT
    and Venom - every one a title with no playfield picture, whose window is
    the switch list, which had no shaker panel. It has the same one now,
    driven from the same drive table."""
    import playfield
    p = _table(tmp_path, "coil SHAKER MOTOR 0 0 0 0 5 0 - -")
    monkeypatch.setattr(playfield, "TDIR", str(tmp_path))
    rows = [{"id": 5, "num": 5, "node": 8, "bit": 0, "name": "LEFT OUTLANE"}]
    S = playfield.Schematic(types.SimpleNamespace(), rows)
    spec = S.spec()
    assert spec["kind"] == "schematic"
    assert spec["shaker"] == {"name": "SHAKER MOTOR", "addr": "node 1 coil 0"}
    assert S.dyn()["shaker"] is None
    S.shaker.tick(_block(until=0), 1000.0)
    S.shaker.tick(_block(until=500, pulse_t=150, pulse_pwr=31), 1100.0)
    assert S.dyn()["shaker"][0] == 31
    js = open(os.path.join(RIG, "pfpage", "pf.js"), encoding="utf-8").read()
    assert "if (info && S.view.shaker)" in js       # the page is view-agnostic
