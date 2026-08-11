"""The ball model, the coil map, and the feeder's decisions. Item 21b.

WHAT THESE GUARD, and each one is a fault this rig has actually had:

  * the ramp rule. Item 20 was `plunge.py` opening TROUGH 1, the eject end,
    where a ball leaving can only ever open TROUGH 6. The rule now lives in
    one place and these tests are what stop it being written the other way
    round again.
  * the device table's field order. The connector column is empty for every
    coil, so counting fields from the LEFT read `h` as the group for a whole
    release and every coil tooltip said "group 20 index 6".
  * the index -> name mapping itself, against item 3's LABELLED experiment.
    The game ran a ball search and fired indices 2, 3, 4, 7 and 8 and no
    others; if this parse ever shifts by a field again, that 5-positive
    4-negative control is what notices.

FAST AND SYNTHETIC like the rest of the rig's tests: no WSL, no emulator, no
Tk. The rows here are the real shapes off this disk and the merged array is a
bytearray written by hand, so what is under test is the reasoning and not the
machine.
"""
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)


# --- the real shapes off this disk -----------------------------------------

#: godzilla_pro's ten coil rows, verbatim from its built device_xy.txt. Group 6
#: is node 8 and group 7 is node 9.
GZ_COILS = """\
# godzilla_pro device positions, from the game binary.
# class     name                                 x     y    w    h  grp index  conn   image
coil      RIGHT FLIPPER                        195   581   20   20    6     0  -      playfield
coil      TROUGH                               260   613   20   20    6     1  -      playfield
coil      RIGHT SLINGSHOT                      219   503   20   20    6     2  -      playfield
coil      LEFT SLINGSHOT                        79   503   20   20    6     3  -      playfield
coil      AUTO PLUNGER                         283   638   20   20    6     4  -      playfield
coil      LEFT FLIPPER                          99   581   20   20    6     5  -      playfield
coil      UP LEFT FLIP                          52   315   20   20    6     6  -      playfield
coil      POP BUMPER                           251   413   20   20    6     7  -      playfield
coil      RIGHT SCOOP                          250   357   20   20    6     8  -      playfield
coil      GODZILLA MAGNET                       74   221   20   20    7     6  -      playfield
switch    TROUGH 1                             254   613   20   20    6    20  8b     playfield
""".splitlines()

#: jaws_le's, which is why nothing may hard-code node 8: the same coils sit in
#: group 7, and its toys are on group 8, a board the boot enumeration does not
#: name.
JAWS_COILS = """\
coil      TROUGH                               249   609   20   20    7     1  -      playfield
coil      AUTO PLUNGER                         282   638   20   20    7     4  -      playfield
coil      SHARK MOTOR UP/DOWN                  179   199   20   20    8     0  -      playfield
""".splitlines()


def gz_trough_rows():
    """godzilla_pro's trough switch rows: bit 37 = Trough 1 = id 71."""
    return [dict(id=66 + i, num=15 + i, node=8, bit=32 + i,
                 name="Trough %d" % pos)
            for i, pos in enumerate((6, 5, 4, 3, 2, 1))]


@pytest.fixture()
def coilmap():
    import coilmap as mod
    return mod


@pytest.fixture()
def ballmodel():
    import ballmodel as mod
    return mod


@pytest.fixture()
def tr(ballmodel):
    import trough
    positions, how = trough.find(gz_trough_rows())
    assert how == "named"
    return ballmodel.Trough(positions)


def mrg_with(*ids):
    m = bytearray(256)
    for i in ids:
        m[i] = 1
    return m


FULL = (71, 70, 69, 68, 67, 66)       # positions 1..6


# --- the coil map ----------------------------------------------------------

def test_coil_rows_parse_with_the_name_counted_from_the_right(coilmap):
    coils = coilmap.parse(GZ_COILS)
    assert len(coils) == 10                      # the switch row is not a coil
    first = coils[0]
    assert (first["name"], first["group"], first["index"]) == \
        ("RIGHT FLIPPER", 6, 0)
    assert (first["x"], first["y"]) == (195, 581)


def test_the_index_to_name_map_matches_item_3s_labelled_ball_search(coilmap):
    """Five coils the game fired and four it did not, on one run.

    Item 3 closed the coin door, emptied the trough and pressed Start; the
    game put up LOCATING PINBALLS and ran a ball search, firing indices 2, 3,
    4, 7 and 8. A ball search fires slingshots, the plunger, the pop bumper
    and the scoop, and must NOT fire the flippers or the trough eject. That
    is a labelled experiment against a table derived from the binary, and it
    is what makes index 1 = TROUGH trustworthy enough to feed balls on.
    """
    coils = coilmap.parse(GZ_COILS)
    by_index = {c["index"]: c["name"] for c in coils if c["group"] == 6}
    assert by_index[2] == "RIGHT SLINGSHOT"
    assert by_index[3] == "LEFT SLINGSHOT"
    assert by_index[4] == "AUTO PLUNGER"
    assert by_index[7] == "POP BUMPER"
    assert by_index[8] == "RIGHT SCOOP"
    # The four it did NOT fire, which is half the strength of the control.
    assert by_index[0] == "RIGHT FLIPPER"
    assert by_index[1] == "TROUGH"
    assert by_index[5] == "LEFT FLIPPER"
    assert by_index[6] == "UP LEFT FLIP"


def test_the_eject_address_is_per_title_and_not_node_8(coilmap):
    """godzilla_pro's trough is node 8; jaws_le's is node 9."""
    assert coilmap.address(coilmap.parse(GZ_COILS), coilmap.TROUGH) == (8, 1)
    assert coilmap.address(coilmap.parse(JAWS_COILS), coilmap.TROUGH) == (9, 1)
    assert coilmap.address(coilmap.parse(GZ_COILS),
                           coilmap.AUTO_PLUNGER) == (8, 4)


def test_a_board_the_enumeration_cannot_name_gives_none_not_a_guess(coilmap):
    """jaws_le's group 8 toys. A guessed node would watch the wrong wire."""
    shark = coilmap.by_name(coilmap.parse(JAWS_COILS), "SHARK MOTOR UP/DOWN")
    assert shark["group"] == 8 and shark["node"] is None
    assert coilmap.address(coilmap.parse(JAWS_COILS),
                           "SHARK MOTOR UP/DOWN") is None


def test_no_table_at_all_is_an_empty_list_not_an_exception(coilmap):
    """star_wars_le ships no device records. A feeder must say so itself."""
    assert coilmap.load("no/such/device_xy.txt") == []
    assert coilmap.address([], coilmap.TROUGH) is None


def test_the_fire_counter_is_read_by_node_and_index(coilmap):
    d = bytearray(coilmap.PADLED_READ)
    d[0:4] = (coilmap.PADLED_MAGIC).to_bytes(4, "little")
    d[coilmap.COIL_OFF + 8 * coilmap.COIL_N + 1] = 7
    assert coilmap.has_magic(d)
    assert coilmap.counter(d, 8, 1) == 7
    assert coilmap.counter(d, 9, 1) == 0
    assert coilmap.counter(d, None, 1) is None
    assert coilmap.counter(bytearray(8), 8, 1) is None
    assert not coilmap.has_magic(bytearray(coilmap.PADLED_READ))


# --- the ramp rule ---------------------------------------------------------

def test_a_ball_leaves_from_the_far_end_which_is_item_20s_bug(tr):
    """Position 1 is the eject end and is the one place a hole cannot appear."""
    assert tr.leaving(mrg_with(*FULL)) == 66            # Trough 6, the far end
    assert tr.leaving(mrg_with(71, 70, 69, 68, 67)) == 67
    assert tr.leaving(mrg_with(71)) == 71               # the last ball
    assert tr.leaving(bytearray(256)) is None


def test_a_returning_ball_fills_the_far_end_first(tr):
    assert tr.arriving(mrg_with(71, 70, 69, 68, 67)) == 66
    assert tr.arriving(mrg_with(71, 70, 69)) == 68
    assert tr.arriving(bytearray(256)) == 71
    assert tr.arriving(mrg_with(*FULL)) is None          # full


def test_a_trough_with_a_hole_in_it_is_reported_not_corrected(tr):
    """Something moved a switch no ball could have moved - item 20's shape."""
    assert tr.anomaly(mrg_with(*FULL)) is None
    assert tr.anomaly(mrg_with(71, 70, 69)) is None      # a normal 3 home
    bad = tr.anomaly(mrg_with(71, 70, 66))               # a gap at 4 and 5
    assert bad and "not a stack" in bad and "1,2,6" in bad


# --- what the feeder decides ----------------------------------------------

def test_an_eject_opens_the_trough_before_it_closes_the_lane(ballmodel, tr):
    """A real ball cannot be in both places, and the game's accounting notices."""
    plan = ballmodel.plan_eject(tr, mrg_with(*FULL), lane_id=62,
                                lane_made=False)
    assert plan
    assert plan.switches() == [(66, 0), (62, 1)]
    assert [s[0] for s in plan.steps] == ["set", "wait", "set"]


def test_an_empty_trough_is_refused_rather_than_inventing_a_ball(ballmodel, tr):
    """What a real machine does here is put up LOCATING PINBALLS."""
    plan = ballmodel.plan_eject(tr, bytearray(256), lane_id=62)
    assert not plan and "empty" in plan.refused
    assert plan.switches() == []


def test_an_occupied_lane_is_refused_which_is_what_folds_a_retry_burst(
        ballmodel, tr):
    """A game that has not seen its trough change re-pulses the coil."""
    plan = ballmodel.plan_eject(tr, mrg_with(*FULL), lane_id=62,
                                lane_made=True)
    assert not plan and "shooter lane" in plan.refused


def test_a_title_with_no_lane_still_ejects_the_ball(ballmodel, tr):
    """The trough is the half that must be right; the lane is a courtesy."""
    plan = ballmodel.plan_eject(tr, mrg_with(*FULL), lane_id=None)
    assert plan.switches() == [(66, 0)]


def test_a_title_with_no_trough_refuses_everything(ballmodel):
    empty = ballmodel.Trough([])
    assert not ballmodel.plan_eject(empty, bytearray(256))
    assert not ballmodel.plan_drain(empty, bytearray(256))


def test_launching_needs_a_ball_in_the_lane(ballmodel):
    assert ballmodel.plan_launch(62, True).switches() == [(62, 0)]
    assert not ballmodel.plan_launch(62, False)
    assert not ballmodel.plan_launch(None, True)


def test_a_drain_closes_the_lowest_open_position(ballmodel, tr):
    plan = ballmodel.plan_drain(tr, mrg_with(71, 70, 69, 68, 67))
    assert plan.switches() == [(66, 1)]
    plan = ballmodel.plan_drain(tr, mrg_with(71, 70, 69))
    assert plan.switches() == [(68, 1)]


def test_a_full_trough_cannot_drain_because_nothing_is_in_play(ballmodel, tr):
    plan = ballmodel.plan_drain(tr, mrg_with(*FULL))
    assert not plan and "full" in plan.refused


def test_three_ejects_and_three_drains_come_back_to_where_they_started(
        ballmodel, tr):
    """A multiball, in miniature, played against the array itself.

    The point is the ROUND TRIP: feeding three balls and draining them must
    leave the trough exactly as it was, or the rig's idea of the machine and
    the game's would part company over one ball a game.
    """
    m = mrg_with(*FULL)
    for expect in (66, 67, 68):
        plan = ballmodel.plan_eject(tr, m, lane_id=62, lane_made=False)
        assert plan.switches()[0] == (expect, 0)
        for sw, val in plan.switches():
            if sw != 62:
                m[sw] = val
    assert tr.count(m) == 3
    for expect in (68, 67, 66):
        plan = ballmodel.plan_drain(tr, m)
        assert plan.switches() == [(expect, 1)]
        m[expect] = 1
    assert tr.count(m) == 6
    assert tr.anomaly(m) is None


# --- the feeder's one piece of state --------------------------------------

def test_the_first_sight_of_a_counter_seeds_it_and_feeds_nothing(monkeypatch,
                                                                 tmp_path,
                                                                 coilmap):
    """Coming up beside a run already in progress must not read that run's
    whole fire count as one fire and eject a ball nobody asked for."""
    monkeypatch.setenv("PAD_ROOT", str(tmp_path))
    monkeypatch.setenv("PAD_SW_FILE", str(tmp_path / "padsw"))
    monkeypatch.setenv("PAD_LED_FILE", str(tmp_path / "padled"))
    import ballfeed

    f = ballfeed.Feeder.__new__(ballfeed.Feeder)
    f.seen = {}
    d = bytearray(coilmap.PADLED_READ)
    d[0:4] = (coilmap.PADLED_MAGIC).to_bytes(4, "little")
    d[coilmap.COIL_OFF + 8 * coilmap.COIL_N + 1] = 42   # a run already going
    assert f.fired(d, (8, 1)) is False                  # seeds, says nothing
    assert f.fired(d, (8, 1)) is False                  # unchanged
    d[coilmap.COIL_OFF + 8 * coilmap.COIL_N + 1] = 43
    assert f.fired(d, (8, 1)) is True
    d[coilmap.COIL_OFF + 8 * coilmap.COIL_N + 1] = 0    # the byte wraps
    assert f.fired(d, (8, 1)) is True
    assert f.fired(d, None) is False


def test_the_feeder_writes_a_source_letter_that_padsw_h_documents():
    """Every writer says who it is, or the [sw] log cannot attribute an edge.

    Source-level, because importing padsw twice with different environments
    inside one test session is worse than reading the two files.
    """
    src = open(os.path.join(RIG, "ballfeed.py"), encoding="utf8").read()
    assert "padsw.set_source('b')" in src
    hdr = open(os.path.join(RIG, "padsw.h"), encoding="utf8").read()
    assert "b  ballfeed.py" in hdr
