"""PAD-450: a VUK on the virtual playfield holds its ball until the game kicks it.

luvthatapex, James Bond LE 1.06: "Right vuk is not functioning in emulation so
I am unable to test Q modes." Measured on the rig: a 170 ms click on RIGHT VUK
OPTO (the click in the user's log) scored nothing and the game only cleared the
VUK, while the switch held made scored 35,070 and the game fired RIGHT VUK
3.8 s in. A real ball sits on the opto until that kick, and the window let go
of the switch on mouse-up. And the RIGHT VUK coil marker, drawn on top of the
switch, did nothing at all: coilact.py knew godzilla_pro's switch IDS, so on
Bond the flipper and slingshot markers pressed whatever wore Godzilla's
numbers (the Right Flipper coil held 59, Bond's LEFT OUTLANE).

So: a coil finds its switch by NAME in the title's own list, and a press on a
VUK / scoop / eject switch is a ball dropped in - it stays made past the
mouse-up until the device's coil fire counter moves.
"""
import os
import sys
import threading
import types

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)


def _row(sid, name):
    return dict(id=sid, num=0, node=8, bit=0, name=name)


#: james_bond_le 1.06's own switch names and ids (its switch_list.txt)
BOND = [_row(50, "DB5 ROOF"), _row(53, "LEFT EJECT"), _row(59, "LEFT OUTLANE"),
        _row(63, "RIGHT FLIPPER BUTTON"), _row(64, "LEFT FLIPPER BUTTON"),
        _row(65, "UP LEFT FLIPPER BUTTON"), _row(67, "RIGHT SLINGSHOT"),
        _row(68, "LEFT SLINGSHOT"), _row(69, "RIGHT FLIPPER EOS"),
        _row(77, "CENTER LANE DIVERTER EOS"), _row(85, "ROCKET VUK OPTO"),
        _row(86, "ROCKET LOCK 1 OPTO"), _row(101, "RIGHT VUK OPTO")]

#: godzilla_pro 1.15's, which the table used to carry as numbers
GODZILLA = [_row(49, "Pop Bumper"), _row(53, "Right Scoop"),
            _row(59, "Right Flipper Button"), _row(60, "Left Flipper Button"),
            _row(61, "Up Left Flip Button"), _row(63, "Right Slingshot"),
            _row(64, "Left Slingshot"), _row(65, "Right Flipper EOS"),
            _row(87, "Godzilla Magnet Fired Virtual")]


@pytest.fixture
def coilact():
    return pytest.importorskip("coilact")


@pytest.mark.parametrize("coil, want", [
    ("RIGHT VUK", 101),                 # the ticket: the marker on the switch
    ("ROCKET VUK", 85),
    ("LEFT EJECT", 53),
    ("RIGHT FLIPPER", 63),              # was 59 = Bond's LEFT OUTLANE
    ("LEFT FLIPPER", 64),
    ("UPPER LEFT FLIPPER", 65),         # Bond spells the button UP LEFT
    ("RIGHT SLINGSHOT", 67),            # was 63 = Bond's RIGHT FLIPPER BUTTON
    ("LEFT SLINGSHOT", 68),
    # nothing fires these from a switch: a same-named one is where the ball
    # or the part ends up, and pressing it would be a lie
    ("ROCKET LOCK", None),
    ("CENTER LANE DIVERTER", None),
    ("JET PACK MAGNET", None),
    ("TROUGH", None),                   # a sequence (plunge.py), not a hold
    ("AUTO PLUNGER", None),
])
def test_bond_coils_hold_bonds_own_switches(coilact, coil, want):
    assert coilact.hold_switch(coil, BOND) == want


@pytest.mark.parametrize("coil, want", [
    ("RIGHT SCOOP", 53), ("POP BUMPER", 49), ("LEFT SLINGSHOT", 64),
    ("RIGHT SLINGSHOT", 63), ("LEFT FLIPPER", 60), ("RIGHT FLIPPER", 59),
    ("UP LEFT FLIP", 61), ("GODZILLA MAGNET", 87),
])
def test_godzilla_keeps_the_switches_it_always_had(coilact, coil, want):
    """The ids the table used to carry, now found by name - item 24's scoop
    and the rest behave exactly as before on the title they were read off."""
    assert coilact.hold_switch(coil, GODZILLA) == want


def test_a_coil_with_no_switch_on_this_title_is_nothing_wired(coilact):
    assert coilact.hold_switch("RIGHT VUK", GODZILLA) is None
    assert coilact.describe("RIGHT VUK", GODZILLA) is None
    assert coilact.describe("TROUGH", BOND) == "ejects a ball into the shooter lane"


def test_the_tooltip_names_the_switch_and_the_kick(coilact):
    t = coilact.describe("RIGHT VUK", BOND)
    assert "RIGHT VUK OPTO (101)" in t and "until the game fires" in t
    assert coilact.holds_ball("RIGHT VUK") and coilact.holds_ball("Right Scoop")
    assert not coilact.holds_ball("RIGHT SLINGSHOT")
    assert "RIGHT FLIPPER BUTTON (63)" in coilact.describe("RIGHT FLIPPER", BOND)


# --------------------------------------------------------------- the latch

class Drv:
    def __init__(self):
        self.log = []

    def press(self, sw):
        self.log.append(("press", sw))

    def release(self, sw):
        self.log.append(("release", sw))


def _block(counts):
    """A padled block as Field._coil_count reads it: magic, version 2+, and
    the fire counters at COIL_OFF."""
    import coilmap
    import struct
    pf = sys.modules["playfield"]
    b = bytearray(max(pf.PADLED_READ, coilmap.COIL_OFF + 256))
    struct.pack_into("<I", b, 0, coilmap.PADLED_MAGIC)
    struct.pack_into("<I", b, 4, 5)
    for (node, idx), c in counts.items():
        b[coilmap.COIL_OFF + node * coilmap.COIL_N + idx] = c
    return bytes(b)


@pytest.fixture
def rig(monkeypatch):
    """A real Playfield controller over a real Field, built without their
    constructors (which start a driver thread and read a title's tables)."""
    pf = pytest.importorskip("playfield")
    monkeypatch.setattr(pf, "wsl_run", lambda *a, **k: None)
    monkeypatch.setattr(pf, "LATCH_ARM_S", 0.0)
    ctl = pf.Playfield.__new__(pf.Playfield)
    ctl.lock = threading.RLock()
    ctl.drv = Drv()
    ctl.holding = None
    ctl._state_msg = None
    view = pf.Field.__new__(pf.Field)
    view.ctl = ctl
    view.coils = [dict(name="RIGHT VUK", node=9, index=1, group=8, x=389, y=550),
                  dict(name="RIGHT SLINGSHOT", node=8, index=2, group=7, x=310, y=710),
                  dict(name="ROCKET LOCK", node=9, index=3, group=8, x=103, y=129)]
    view.switches = []
    view._sw_named = list(BOND)
    view._kick_map = None
    view._kick_n = 0
    view.latched = {}
    made = {}
    view.sw = types.SimpleNamespace(is_made=lambda sid: made.get(sid, False))
    view.last = _block({(9, 1): 7})
    ctl.view = view
    return types.SimpleNamespace(pf=pf, ctl=ctl, view=view, made=made)


def test_only_a_ball_device_latches(rig):
    assert rig.view.kicker(101)["name"] == "RIGHT VUK"
    assert rig.view.kicker(67) is None          # a slingshot is a hold
    assert rig.view.kicker(86) is None          # ROCKET LOCK follows nothing


def test_a_click_on_the_vuk_stays_made_until_the_game_kicks(rig):
    ctl, view = rig.ctl, rig.view
    ctl.api_hold(101)
    assert ctl.drv.log == [("press", 101)]
    assert ctl.api_unhold() is False            # the mouse-up lets go of nothing
    assert ctl.drv.log == [("press", 101)]
    assert 101 in view.latched and "until the game fires RIGHT VUK" in ctl.state_status()
    rig.made[101] = True
    view.latch_tick(_block({(9, 1): 7}))        # no fire: the ball sits there
    assert ctl.drv.log == [("press", 101)] and 101 in view.latched
    view.latch_tick(_block({(9, 1): 8}))        # RIGHT VUK fired
    assert ctl.drv.log == [("press", 101), ("release", 101)]
    assert view.latched == {}
    assert "RIGHT VUK fired" in ctl.state_status()


def test_a_fire_before_the_press_lands_does_not_take_the_ball(rig, monkeypatch):
    """The press crosses wsl.exe; a fire inside LATCH_ARM_S came first."""
    monkeypatch.setattr(rig.pf, "LATCH_ARM_S", 60.0)
    rig.ctl.api_hold(101)
    rig.view.latch_tick(_block({(9, 1): 9}))
    assert ("release", 101) not in rig.ctl.drv.log and 101 in rig.view.latched


def test_a_second_click_takes_the_ball_out_by_hand(rig):
    rig.ctl.api_hold(101)
    rig.ctl.api_unhold()
    rig.ctl.api_hold(101)
    assert rig.ctl.drv.log == [("press", 101), ("release", 101)]
    assert rig.view.latched == {} and "by hand" in rig.ctl.state_status()


def test_the_coil_marker_drops_the_ball_too(rig, monkeypatch):
    sw = rig.ctl.api_coil(0)                    # the RIGHT VUK square
    assert sw == 101 and 101 in rig.view.latched
    assert rig.ctl.drv.log == [("press", 101)]


def test_anything_else_is_still_held_only_while_the_mouse_is_down(rig):
    rig.ctl.api_hold(67)
    assert rig.ctl.api_unhold() is True
    assert rig.ctl.drv.log == [("press", 67), ("release", 67)]
    assert rig.view.latched == {}


def test_no_coil_data_means_an_ordinary_hold(rig):
    """With nothing to watch, nothing would ever open a latched switch."""
    rig.view.last = None
    rig.ctl.api_hold(101)
    assert rig.ctl.api_unhold() is True
    assert rig.ctl.drv.log == [("press", 101), ("release", 101)]


def test_a_latched_switch_opened_elsewhere_is_let_go(rig):
    rig.ctl.api_hold(101)
    rig.view.latch_tick(_block({(9, 1): 7}))    # not seen made yet: kept
    assert 101 in rig.view.latched
    rig.made[101] = True
    rig.view.latch_tick(_block({(9, 1): 7}))
    rig.made[101] = False                       # the keyboard / a script
    rig.view.latch_tick(_block({(9, 1): 7}))
    assert rig.view.latched == {}
    assert ("release", 101) not in rig.ctl.drv.log


def test_the_switch_tooltip_says_click_not_hold(rig):
    rig.view.sw_rows = [dict(id=101, name="RIGHT VUK OPTO", node=9, bit=24,
                             x=388, y=549),
                        dict(id=67, name="RIGHT SLINGSHOT", node=8, bit=29,
                             x=310, y=710)]
    vuk = rig.view.describe("switch", 0)
    assert "a ball drops in" in vuk and "RIGHT VUK" in vuk
    assert "hold to keep it closed" in rig.view.describe("switch", 1)
