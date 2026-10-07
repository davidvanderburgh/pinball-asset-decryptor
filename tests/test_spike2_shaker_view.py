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


def test_a_table_without_the_cabinet_board_gets_group_5_index_0(tmp_path):
    # godzilla_le: its table names no cabinet coil, and its game's drive 7 reached
    # the rig's board as node 1 coil 0 (PAD-414)
    p = _table(tmp_path, "coil TROUGH 260 613 20 20 6 1 - playfield",
               "coil VUK 132 43 20 20 7 1 - playfield")
    assert coilmap.shaker_address(p) == (1, 0)


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
