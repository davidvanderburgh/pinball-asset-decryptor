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


def test_an_unnamed_trough_is_index_1_beside_the_auto_plunger(coilmap):
    """JP The Pin 1.05 names six coils and not the trough; every title naming both has the
    trough at index 1 on the plunger's board. Only when that slot is free and the plunger is 4."""
    named = coilmap.parse(GZ_COILS)
    assert coilmap.eject_address(named) == coilmap.address(named, coilmap.TROUGH) == (8, 1)
    pin = [c for c in named if c["name"] != coilmap.TROUGH]
    assert coilmap.address(pin, coilmap.TROUGH) is None
    assert coilmap.eject_address(pin) == (8, 1)
    taken = pin + [dict(pin[0], name="SOMETHING ELSE", index=1)]
    taken[-1]["node"] = 8
    assert coilmap.eject_address(taken) is None
    moved = [dict(c, index=5) if c["name"] == coilmap.AUTO_PLUNGER else c for c in pin]
    assert coilmap.eject_address(moved) is None
    assert coilmap.eject_address([]) is None


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


def _settles_at(plan):
    """The write a drain ENDS on - the position the ball stays in."""
    return plan.switches()[-1]


def _rolls_over(plan):
    """The positions the ball passed on its way down, far end first: each one
    closed and opened again before the next (PAD-186)."""
    writes = plan.switches()[:-1]
    assert [v for _, v in writes] == [1, 0] * (len(writes) // 2)
    return [sw for sw, v in writes if v == 1]


def test_a_drain_closes_the_lowest_open_position(ballmodel, tr):
    plan = ballmodel.plan_drain(tr, mrg_with(71, 70, 69, 68, 67))
    assert plan.switches() == [(66, 1)]          # far end IS the settling spot
    plan = ballmodel.plan_drain(tr, mrg_with(71, 70, 69))
    assert _settles_at(plan) == (68, 1)


def test_a_multiball_drain_rolls_down_the_ramp_before_it_settles(ballmodel, tr):
    """PAD-186, David's live Mechagodzilla Multiball (2026-09-20): three balls
    out, three Drain clicks, every one delivered - and the game credited one
    of them and searched for the rest for ever. The rig had closed position 4
    with 5 and 6 never moving, which no ball can do: a returning ball enters
    at the FAR end and rolls over every open position down to the stack. With
    one ball out the far end is the settling position, which is exactly why
    single-ball drains never showed this.
    """
    plan = ballmodel.plan_drain(tr, mrg_with(71, 70, 69))       # 3 out
    assert _rolls_over(plan) == [66, 67]                        # 6 then 5
    assert _settles_at(plan) == (68, 1)                         # stays at 4
    waits = [s for s in plan.steps if s[0] == "wait"]
    assert len(waits) == 4 and all(0 < s[1] < 0.5 for s in waits)
    # Two out: passes 6, settles at 5.
    plan = ballmodel.plan_drain(tr, mrg_with(71, 70, 69, 68))
    assert _rolls_over(plan) == [66]
    assert _settles_at(plan) == (67, 1)
    # One out: nothing to roll over.
    plan = ballmodel.plan_drain(tr, mrg_with(71, 70, 69, 68, 67))
    assert _rolls_over(plan) == []


def test_a_full_trough_cannot_drain_because_nothing_is_in_play(ballmodel, tr):
    plan = ballmodel.plan_drain(tr, mrg_with(*FULL))
    assert not plan and "full" in plan.refused


def test_a_ball_waiting_in_the_lane_cannot_drain_before_it_is_plunged(
        ballmodel, tr):
    """PAD-153, DragonRR: "I drained before I plunged.. and that forces an
    endless cycle." Five home and the sixth in the lane left position 6 open,
    and closing it put seven balls on a six-ball machine."""
    served = mrg_with(71, 70, 69, 68, 67, 62)
    plan = ballmodel.plan_drain(tr, served, lane_id=62, lane_made=True)
    assert not plan and "shooter lane" in plan.refused
    assert plan.switches() == []
    assert ballmodel.in_play(tr, served, 62, True) == 0


def test_a_launched_ball_drains_and_a_multiball_drains_past_a_waiting_one(
        ballmodel, tr):
    launched = mrg_with(71, 70, 69, 68, 67)
    assert ballmodel.plan_drain(tr, launched, lane_id=62,
                                lane_made=False).switches() == [(66, 1)]
    # Three home, one waiting in the lane, two out there: a drain is real.
    multi = mrg_with(71, 70, 69, 62)
    assert ballmodel.in_play(tr, multi, 62, True) == 2
    assert _settles_at(ballmodel.plan_drain(tr, multi, lane_id=62,
                                            lane_made=True)) == (68, 1)


def test_a_title_with_no_lane_switch_drains_on_the_trough_alone(ballmodel, tr):
    """No lane to read is not a lane with a ball in it."""
    plan = ballmodel.plan_drain(tr, mrg_with(71, 70, 69, 68, 67), lane_id=None,
                                lane_made=True)
    assert plan.switches() == [(66, 1)]


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
        assert _settles_at(plan) == (expect, 1)
        for sw, val in plan.switches():         # the roll-down included
            m[sw] = val
        assert tr.anomaly(m) is None            # never a hole mid-roll
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


# --- the clickable trough dots --------------------------------------------
#
# THE WINDOW IS A WEB PAGE NOW (2026-09-23). The dots are a model
# (`playfield.TroughDots`) that the page (pfpage/pf.js `troughStrip`) draws,
# and a click comes back as the controller's `api_trough(i)`. The Tk tests
# here asked a real canvas about bindings; what is left to ask is the model's
# decision, the controller's refusal, and where the page puts the listener.


def _dots(clickable=True):
    import playfield
    positions = [dict(pos=i + 1, id=71 - i, name="Trough %d" % (i + 1))
                 for i in range(6)]
    return playfield.TroughDots(positions, "named", clickable=clickable)


def test_clicking_a_ball_takes_one_out_and_an_empty_slot_brings_one_home():
    """David, 2026-08-11, mid-multiball: "how do i drain a ball?"

    Pressing the trough SWITCH cannot do it - item 24's hold is momentary and
    a ball is a latched closure - so the six dots are the control.
    """
    dots = _dots()
    dots.update([True, True, True, False, False, False], "x")
    assert dots.click(0) == "take"            # a ball -> one fewer
    assert dots.click(2) == "take"            # a deeper ball -> still one fewer
    assert dots.click(4) == "drain"           # an empty slot -> one more
    assert dots.click(99) == "drain"          # off the end: never a crash


def test_the_click_reaches_the_plunge_helper_only_when_clickable():
    """The controller's side: a clickable strip runs plunge.py with the
    model's decision; a read-only one (the key panel's dots) or no strip at
    all is a refusal, so a stale page cannot press through it."""
    import playfield
    ctl = playfield.Playfield.__new__(playfield.Playfield)
    ran = []
    ctl.run_plunge = ran.append

    class V:
        trough = _dots()
    ctl.view = V
    V.trough.update([True] * 6, "x")
    assert ctl.api_trough(0) == "take" and ran == ["take"]
    V.trough = _dots(clickable=False)
    assert ctl.api_trough(0) is None and ran == ["take"]
    V.trough = None
    assert ctl.api_trough(0) is None and ran == ["take"]


def test_an_EMPTY_dot_is_clickable_across_its_whole_cell_not_just_its_ring():
    """David, 2026-08-11: "when hovering over the circles, it's not always
    indicating that i can click on it."

    In Tk the cause was the `fill=""` rule (a hollow item is hittable only on
    its outline). On the page the listener is on the CELL - the dot and its
    number - so an empty position is as big a target as a full one, and the
    pointer cursor is the cell's too."""
    js = open(os.path.join(RIG, "pfpage", "pf.js"), encoding="utf8").read()
    assert 'c.addEventListener("click", () => api("trough", i))' in js
    css = open(os.path.join(RIG, "pfpage", "pf.css"), encoding="utf8").read()
    assert ".pf-trough.click .cell { cursor: pointer; }" in css


def test_a_strip_with_no_control_is_not_clickable_at_all():
    """The key panel's dots are read-only (PAD-134): the spec says so, and
    the page binds nothing for a spec that says so."""
    dots = _dots(clickable=False)
    assert dots.spec()["clickable"] is False
    assert dots.spec()["pos"] == [1, 2, 3, 4, 5, 6]
    dots.update([True, False, True, False, False, False], "t")
    assert dots.dyn() == {"flags": [True, False, True, False, False, False],
                          "text": "t"}


def test_the_caption_says_the_dots_are_clickable():
    """Six small dots on a status strip do not look like buttons, and the
    thing a user reaches for instead is the trough switch, which cannot work."""
    import playfield
    import trough as tmod
    w = playfield.SwitchWatch.__new__(playfield.SwitchWatch)
    w.positions = [dict(pos=1, id=71, name="Trough 1")]
    w.how = "named"
    w.balls = tmod.Balls()
    w.balls.update([True])
    assert "click a ball" in playfield.trough_text(w)


def test_the_feeder_writes_a_source_letter_that_padsw_h_documents():
    """Every writer says who it is, or the [sw] log cannot attribute an edge.

    Source-level, because importing padsw twice with different environments
    inside one test session is worse than reading the two files.
    """
    src = open(os.path.join(RIG, "ballfeed.py"), encoding="utf8").read()
    assert "padsw.set_source('b')" in src
    hdr = open(os.path.join(RIG, "padsw.h"), encoding="utf8").read()
    assert "b  ballfeed.py" in hdr


# --- PAD-134: who is playing, and the balls the feeder launched ------------
#
# DragonRR, 2026-09-12, trying to reach players 2, 3 and 4 to check their
# images: "WITH BALL SAVE ON I can reliably drain the ball for player 1 ...
# but now when I click ball 6 on the B/W display for player 2 it ignores me",
# and "I suspect the machine thinks a ball is still in play". Every input in
# his report is a MOUSE click in the playfield window, and the feeder's test
# for "is a human playing this ball" read the KEYBOARD array - which a mouse
# never moves. So it called him nobody and drained his live ball back to the
# trough, and with ball save on that is every ball: the game re-serves and
# fires its own AUTO PLUNGER (measured on godzilla_pro, item 21b).
#
# Offline, against a block written by hand: the only thing faked is the
# guest's merge (_publish), which is one loop.


def _sw(tmp_path, monkeypatch):
    """ballfeed and padsw, pointed at a block that is not a running game's."""
    monkeypatch.setenv("PAD_ROOT", str(tmp_path))
    monkeypatch.setenv("PAD_SW_FILE", str(tmp_path / "padsw"))
    monkeypatch.setenv("PAD_LED_FILE", str(tmp_path / "padled"))
    import ballfeed
    import padsw
    return ballfeed, padsw


def _feeder(ballfeed, tr, lane=62):
    """A Feeder with its resolution skipped - no tables, no emulator."""
    f = ballfeed.Feeder.__new__(ballfeed.Feeder)
    f.dry = False
    f.trough = tr
    f.lane = lane
    f.seen, f.said = {}, {}
    f.shape = None
    f.fed = 0
    f.last_feed = 0.0
    f.pending = []
    f.my_gen = None
    f.hands = 0
    f.last_claim = None
    f.human_at = None
    f.holding = False
    f.van = f.van_lower = f.van_upper = None
    f.van_attract = 0
    f.van_game = False
    f.eject_at, f.eject_from_full = None, False
    f.home_at, f.home_count = 0.0, None
    f.van_stocked = True
    f.extra = f.extra_max = 0
    f.homebound = []
    f.drops = []
    f.hold = f.feed_at = None
    return f


class _Block(bytearray):
    """The switch block, as mutable as the mmap the helpers are written for.

    A bare bytearray is not enough: padsw.bump() calls flush() on what it was
    handed, because on a run that is a shared mapping the guest reads. One
    no-op method is the whole difference.
    """

    def flush(self):
        pass


def _block(padsw, *made):
    """The 4096-byte block with `made` closed in the script array AND the
    merge, which is the only state a real run could be in."""
    import struct
    m = _Block(4096)
    struct.pack_into("<I", m, padsw.OFF_MAGIC, padsw.MAGIC)
    for i in made:
        m[padsw.OFF_SCR_HELD + i] = 1
        m[padsw.OFF_MRG + i] = 1
    return m


def _publish(padsw, m):
    """The one thing the guest does that a desk test has to do itself."""
    for i in range(padsw.MAX_ID):
        m[padsw.OFF_MRG + i] = m[padsw.OFF_SCR_HELD + i]


def _other_writer(padsw, m, sw, tag):
    """Somebody else's script write, tagged the way padsw.bump() tags one."""
    import struct
    m[padsw.OFF_SCR_HELD + sw] = 1
    struct.pack_into("<I", m, padsw.OFF_SCR_SRC, ord(tag))
    struct.pack_into("<I", m, padsw.OFF_SCR_GEN,
                     struct.unpack_from("<I", m, padsw.OFF_SCR_GEN)[0] + 1)


def test_a_ball_played_with_the_MOUSE_is_not_a_ball_nobody_is_playing(
        tmp_path, monkeypatch, tr):
    """PAD-134's fault in one assertion: the window drives switches through
    the helpers with PAD_SW_SRC=f, and that has to count as somebody playing.
    """
    ballfeed, padsw = _sw(tmp_path, monkeypatch)
    f = _feeder(ballfeed, tr)
    m = _block(padsw, 71, 70, 69, 68, 67)          # one ball out, five home
    f.pending = [(0.0, f._claim(m))]
    _other_writer(padsw, m, 53, "f")               # a click on the artwork
    f._way_home(m, 1000.0, f._claim(m))
    assert f.pending == []                         # the ball is the player's
    assert m[padsw.OFF_SCR_HELD + 66] == 0         # and it was NOT drained


def test_the_rigs_own_automation_is_not_somebody_playing(tmp_path, monkeypatch,
                                                        tr):
    """The other half, and the reason this is a letter test and not "anything
    wrote": autoattract, the switch exerciser and longplay run with nobody
    watching, and THEIR launched balls must still come home - that is what
    the game's ball search is waiting to see.
    """
    ballfeed, padsw = _sw(tmp_path, monkeypatch)
    f = _feeder(ballfeed, tr)
    m = _block(padsw, 71, 70, 69, 68, 67)
    f.pending = [(0.0, f._claim(m))]
    _other_writer(padsw, m, 53, "a")               # autoattract's Service Back
    f._way_home(m, 1000.0, f._claim(m))
    assert f.pending == []
    assert m[padsw.OFF_SCR_HELD + 66] == 1         # drained home


def test_the_feeders_own_writes_are_not_a_pair_of_hands(tmp_path, monkeypatch,
                                                        tr, ballmodel):
    """The trap in counting script writes: the feeder writes that array too.

    Without adopting its own bumps, answering one eject would read as a human
    and cancel the way home of every ball already launched - the stranded ball
    this fix is about, reintroduced from the other end.
    """
    ballfeed, padsw = _sw(tmp_path, monkeypatch)
    f = _feeder(ballfeed, tr)
    m = _block(padsw, 71, 70, 69, 68, 67, 62)      # a ball waiting in the lane
    before = f._claim(m)
    assert f.run_plan(m, ballmodel.plan_launch(62, True), "auto plunger:")
    _publish(padsw, m)
    assert f._claim(m) == before


def test_two_launched_balls_both_come_home_rather_than_one_being_forgotten(
        tmp_path, monkeypatch, tr, ballmodel):
    """It was ONE slot, so the second launch overwrote the first ball's timer
    and that ball never came home: the game goes on believing it is in play,
    which is a START that refuses and a ball search that never ends. A
    multiball is the game doing this on purpose.
    """
    ballfeed, padsw = _sw(tmp_path, monkeypatch)
    f = _feeder(ballfeed, tr)
    m = _block(padsw, 71, 70, 69, 68)              # two out, four home
    claim = f._claim(m)
    f.pending = [(0.0, claim), (1.0, claim)]
    f._way_home(m, 1000.0, f._claim(m))
    # ONE per poll: two drains off one merged read could both pick the same
    # hole and put two balls in one position.
    assert len(f.pending) == 1
    _publish(padsw, m)
    f._way_home(m, 1000.0, f._claim(m))
    _publish(padsw, m)
    assert f.pending == []
    mrg = m[padsw.OFF_MRG:padsw.OFF_MRG + padsw.MAX_ID]
    assert tr.count(mrg) == 6
    assert tr.anomaly(mrg) is None


def _player_then_a_launch(ballfeed, padsw, f, m):
    """A player clicks, and the game then serves and plunges a ball itself.

    The order is the whole of PAD-186: the click comes FIRST (it is what
    drained the last ball), the launch the game answers it with is a launch
    this feeder owns, and nothing moves after that because the player is
    watching the mode intro. Returns the time of the click.
    """
    f._way_home(m, 0.0, f._claim(m))               # a poll, to seed the claim
    _other_writer(padsw, m, 53, "f")               # their click on the artwork
    _publish(padsw, m)
    f._way_home(m, 1.0, f._claim(m))               # the poll that sees it
    m[padsw.OFF_SCR_HELD + 66] = 0                 # the feeder's own eject...
    m[padsw.OFF_MRG + 66] = 0                      # ...and its own launch
    f.pending = [(2.0, f._claim(m))]
    return 1.0


def test_a_ball_launched_after_the_players_last_click_is_not_taken_back(
        tmp_path, monkeypatch, tr):
    """PAD-186's fault in one assertion. PAD-134 cancelled the way home for
    the balls pending when somebody touched the machine; the ball the game
    serves NEXT starts a fresh timer from the claim as it now stands, so five
    seconds of watching a battle intro read as an empty room and the feeder
    took the ball. The game hands it straight back (a battle's ball save is
    16-45 s), the feeder owns that launch too, and the player's own Drain
    click lands on a trough this already filled.
    """
    ballfeed, padsw = _sw(tmp_path, monkeypatch)
    f = _feeder(ballfeed, tr)
    m = _block(padsw, 71, 70, 69, 68, 67, 66)      # a machine at rest
    clicked = _player_then_a_launch(ballfeed, padsw, f, m)
    assert f.human_at == clicked
    f._way_home(m, 2.0 + ballfeed.HOME_S + 1.0, f._claim(m))
    assert len(f.pending) == 1                     # still the player's ball
    assert m[padsw.OFF_SCR_HELD + 66] == 0         # and it was NOT drained


def test_a_room_that_really_did_empty_still_gets_its_ball_back(
        tmp_path, monkeypatch, tr):
    """The other half, and why this is a window and not a latch: the way home
    is what a ball search is waiting to see, so a window somebody walked away
    from has to go back to the old behaviour rather than hold their ball for
    ever.
    """
    ballfeed, padsw = _sw(tmp_path, monkeypatch)
    f = _feeder(ballfeed, tr)
    m = _block(padsw, 71, 70, 69, 68, 67, 66)
    clicked = _player_then_a_launch(ballfeed, padsw, f, m)
    f._way_home(m, clicked + ballfeed.HUMAN_S + 1.0, f._claim(m))
    assert f.pending == []
    assert m[padsw.OFF_SCR_HELD + 66] == 1         # drained home


def test_plunge_only_ever_launches_and_never_takes_a_ball_from_the_trough(
        tmp_path, monkeypatch, capsys):
    """The button half of the same fault: the game counts the balls it asked
    for, so a ball the rig adds is a ball the machine is short for ever, and
    the next Start gets LOCATING PINBALLS. With ball save on it was one click
    away - the game auto-plunges the saved ball itself, leaving an empty lane
    with a ball in play - and with every ball home it was one click away in
    attract. David, 2026-09-13: "yes make plunge launch-only".
    """
    monkeypatch.setenv("PAD_ROOT", str(tmp_path))
    monkeypatch.setenv("PAD_SW_FILE", str(tmp_path / "padsw"))
    import padsw
    import plunge
    # PINNED, not resolved: plunge.py looks its ids up in the running title's
    # switch table at import, and on a machine that HAS the rig's tables that
    # is whichever title ran last - a unit test that reads them is a test whose
    # answer depends on the desk it runs at.
    monkeypatch.setattr(plunge, "TROUGH", (71, 70, 69, 68, 67, 66))
    monkeypatch.setattr(plunge, "SHOOTER", 62)
    monkeypatch.setattr(plunge, "STEP_S", 0.0)
    monkeypatch.setattr(plunge, "LANE_S", 0.0)
    trough = (71, 70, 69, 68, 67, 66)

    def held(blk):
        return [blk[padsw.OFF_SCR_HELD + i] for i in trough]

    out = _block(padsw, 71, 70, 69, 68, 67)        # one ball in play
    assert plunge.do_plunge(out) == 1
    said = capsys.readouterr().out
    assert said.startswith("nothing in the shooter lane")
    assert "a ball is in play" in said and "Drain" in said
    assert held(out) == [1, 1, 1, 1, 1, 0]         # no second ball served

    # Every ball home and the lane empty: attract, or a Start that did not
    # take. This used to eject one, and that ball was one the game never
    # asked for.
    rest = _block(padsw, *trough)
    assert plunge.do_plunge(rest) == 1
    said = capsys.readouterr().out
    assert said.startswith("nothing in the shooter lane")
    assert "Start" in said                         # what does put one there
    assert held(rest) == [1] * 6

    # The one thing it does: a ball waiting in the lane is launched, and the
    # trough is not touched.
    lane = _block(padsw, 71, 70, 69, 68, 67, 62)
    assert plunge.do_plunge(lane) == 0
    assert lane[padsw.OFF_SCR_HELD + 62] == 0
    assert held(lane) == [1, 1, 1, 1, 1, 0]
    assert "ball launched" in capsys.readouterr().out


def test_game_waits_for_a_ball_that_stays_in_the_lane(tmp_path, monkeypatch):
    """PAD-654: D&D LE fills its dragon and TMNT LE runs its turtle select before ball 1, so a lane empty 5 s after
    Start is not "no game". A ball the game itself launches within half a second (a lock being loaded) is not ball 1
    either: launching it by hand took it from the lock."""
    monkeypatch.setenv("PAD_ROOT", str(tmp_path))
    monkeypatch.setenv("PAD_SW_FILE", str(tmp_path / "padsw"))
    import padsw
    import plunge
    monkeypatch.setattr(plunge, "SHOOTER", 62)
    monkeypatch.setattr(plunge, "TROUGH", FULL)
    monkeypatch.setitem(plunge._IDS, "locks", [83])
    now = [0.0]
    at = {}                                         # game second -> [(switch, level)]

    class Clock:
        def __init__(self, m):
            pass

        def now(self):
            return now[0]

    def sleep(m, s):
        now[0] += s
        for t, moves in at.items():
            if abs(now[0] - t) < 0.05:
                for sw, v in moves:
                    m[padsw.OFF_MRG + sw] = v
    monkeypatch.setattr(plunge.padsw, "GameClock", Clock)
    monkeypatch.setattr(plunge.padsw, "game_sleep", sleep)

    def run(moves, budget):
        now[0] = 0.0
        at.clear()
        at.update(moves)
        return plunge.wait_serve(_block(padsw, *FULL), budget=budget)

    # a lock's ball launched at once (into the lock), then ball 1 that waits
    assert run({2.0: [(66, 0), (62, 1)], 2.5: [(62, 0)], 3.3: [(83, 1)], 8.0: [(67, 0), (62, 1)]}, 20) == "lane"
    assert 9.4 <= now[0] < 10.0                     # 1.5 s after ball 1 arrived, not at the lock's ball
    assert run({}, 3) is None and now[0] >= 3       # nothing served
    # D&D LE's first Start: the dragon filled by the game's own launches, then nothing - over QUIET_S later, not
    # at the end of the budget
    loads = {2.0: [(66, 0), (62, 1)], 2.5: [(62, 0)], 3.3: [(83, 1)]}
    assert run(loads, 90) is None
    assert 2.5 + plunge.QUIET_S - 0.6 <= now[0] < 2.5 + plunge.QUIET_S + 0.6
    # Godzilla LE once: ball 1 launched by the game 0.6 s after its serve - in play, not home, not locked
    assert run({2.0: [(66, 0), (62, 1)], 2.6: [(62, 0)]}, 90) == "self"
    # an attract-style launch that came home is not a game
    assert run({2.0: [(66, 0), (62, 1)], 2.6: [(62, 0)], 7.6: [(66, 1)]}, 90) is None
    # PAD-713: D&D LE's attract loading its dragon and kicking each ball back out until the trough ran dry - every
    # ball off home and none locked, which read as "the game launched ball 1 itself"
    drain = {}
    for k, sw in enumerate(FULL):
        drain[2.0 + 2 * k] = [(sw, 0), (62, 1)]
        drain[2.5 + 2 * k] = [(62, 0)]
    assert run(drain, 90) is None


# --- the van (item 167, TMNT LE/Premium) ------------------------------------
#
# The LE's van is a physical ball lock the rig had no model of: in attract the
# game loads a ball into it and lets it straight out again, and with no van
# every one of those balls was lost - Start refused for ~150 s, and a
# multiball's count collapsed after the game's first ball search. Its real
# switch ids off turtles_le's switch list: LOWER LOCK 1-2 = 50, 51, UPPER LOCK
# 1-3 = 52..54, VAN ENTER OPTO = 84.

VAN_NAMES = {"LOWER LOCK 1": 50, "LOWER LOCK 2": 51, "UPPER LOCK 1": 52, "UPPER LOCK 2": 53,
             "UPPER LOCK 3": 54, "VAN ENTER OPTO": 84, "SHOOTER LANE": 69}


def test_only_a_title_with_all_six_van_switches_has_a_van(ballmodel):
    assert ballmodel.Van.from_names({"SHOOTER LANE": 69}) is None
    half = dict(VAN_NAMES)
    del half["UPPER LOCK 3"]
    assert ballmodel.Van.from_names(half) is None
    van = ballmodel.Van.from_names(VAN_NAMES)
    assert van.stack == [50, 51, 52, 53, 54] and van.enter == 84


def test_a_ball_loads_past_the_opto_into_the_upper_lock(ballmodel):
    van = ballmodel.Van.from_names(VAN_NAMES)
    plan = van.plan_load(mrg_with())
    assert plan.switches() == [(84, 1), (84, 0), (52, 1)]
    assert van.plan_load(mrg_with(52)).switches()[-1] == (53, 1)
    assert van.plan_load(mrg_with(50, 51, 52)).switches()[-1] == (53, 1)   # the lower lock is not in the way
    assert van.plan_load(mrg_with(52, 53, 54)).refused                    # the upper lock is full


def test_lower_lock_lets_the_bottom_ball_out_and_the_next_drops(ballmodel):
    van = ballmodel.Van.from_names(VAN_NAMES)
    assert van.plan_release(mrg_with()).refused
    assert van.plan_release(mrg_with(50)).switches() == [(50, 0)]
    assert van.plan_release(mrg_with(50, 51)).switches() == [(50, 0), (51, 0), (50, 1)]


def test_upper_lock_drops_a_ball_into_the_lower_section(ballmodel):
    van = ballmodel.Van.from_names(VAN_NAMES)
    assert van.plan_drop(mrg_with(50)).refused                       # nothing up there
    assert van.plan_drop(mrg_with(50, 51, 52)).refused               # nowhere to go
    assert van.plan_drop(mrg_with(52)).switches() == [(52, 0), (50, 1)]
    assert van.plan_drop(mrg_with(50, 52, 53, 54)).switches() == [
        (52, 0), (51, 1), (53, 0), (52, 1), (54, 0), (53, 1)]


def test_a_ball_in_the_van_is_neither_home_nor_drainable(ballmodel, tr):
    # five home, one in the van: nothing is in play, so a drain has nothing to take
    m = mrg_with(*FULL[:5])
    assert ballmodel.in_play(tr, m) == 1
    assert ballmodel.in_play(tr, m, held=1) == 0
    assert ballmodel.plan_drain(tr, m, held=1).refused
    assert not ballmodel.plan_drain(tr, m).refused


def _van_feeder(ballfeed, ballmodel, tr, monkeypatch, padsw):
    f = _feeder(ballfeed, tr, lane=62)
    f.van = ballmodel.Van.from_names(VAN_NAMES)
    f.van_lower, f.van_upper = (8, 7), (8, 8)
    f.eject_coil, f.plunge_coil = (8, 1), (8, 4)
    for k in ("VAN_FLIGHT_S", "VAN_ENTER_S", "VAN_DROP_S"):
        monkeypatch.setattr(ballmodel, k, 0.0)

    def confirmed(m, sw, v):                    # the guest's merge, at once
        m[padsw.OFF_SCR_HELD + sw] = v
        m[padsw.OFF_MRG + sw] = v
        return True
    monkeypatch.setattr(padsw, "set_confirmed", confirmed)
    return f


def _led(coilmap):
    d = bytearray(coilmap.PADLED_READ)
    d[0:4] = (coilmap.PADLED_MAGIC).to_bytes(4, "little")
    return d


def _fire(coilmap, d, node, idx):
    d[coilmap.COIL_OFF + node * coilmap.COIL_N + idx] += 1


def test_in_attract_a_launch_goes_into_the_van_and_its_release_comes_home(
        tmp_path, monkeypatch, tr, ballmodel, coilmap):
    """The game's attract van check, as the probe measured it: auto plunger, the ball arrives in the van,
    LOWER LOCK lets it out, and with nobody at the machine the way home takes it back to the trough."""
    ballfeed, padsw = _sw(tmp_path, monkeypatch)
    f = _van_feeder(ballfeed, ballmodel, tr, monkeypatch, padsw)
    m = _block(padsw, *FULL[:5], 62)            # a ball waiting in the lane, nobody here
    d = _led(coilmap)
    f.poll(m, d, 1.0)                           # seeds every counter
    _fire(coilmap, d, 8, 4)                     # AUTO PLUNGER
    f.poll(m, d, 2.0)
    assert m[padsw.OFF_MRG + 62] == 0           # launched...
    assert m[padsw.OFF_MRG + 52] == 1           # ...into the van's upper lock
    assert f.pending == []                      # so not a ball on the playfield
    _fire(coilmap, d, 8, 8)                     # UPPER LOCK: down into the lower lock
    f.poll(m, d, 2.5)
    assert m[padsw.OFF_MRG + 52] == 0 and m[padsw.OFF_MRG + 50] == 1
    _fire(coilmap, d, 8, 7)                     # LOWER LOCK: out
    f.poll(m, d, 3.0)
    assert m[padsw.OFF_MRG + 50] == 0 and f.homebound == [3.0] and f.pending == []
    f.human_at = 3.5                            # somebody presses Start mid-check...
    f.poll(m, d, 9.0)
    assert f.homebound == [] and m[padsw.OFF_MRG + FULL[5]] == 1   # ...and the ball still rolls home


def test_in_a_game_the_served_ball_goes_onto_the_playfield_not_the_van(
        tmp_path, monkeypatch, tr, ballmodel, coilmap):
    """The fourth live run: a multiball's served balls sent into the van were taken for locked balls, held
    12-26 s, and the game's count climbed to 7."""
    ballfeed, padsw = _sw(tmp_path, monkeypatch)
    f = _van_feeder(ballfeed, ballmodel, tr, monkeypatch, padsw)
    m = _block(padsw, *FULL[:5], 62)
    d = _led(coilmap)
    f.poll(m, d, 1.0)
    f.van_game = True                           # the game's ball 1 waited for its plunge
    _fire(coilmap, d, 8, 4)
    f.poll(m, d, 2.0)
    assert m[padsw.OFF_MRG + 62] == 0 and m[padsw.OFF_MRG + 52] == 0     # onto the playfield
    assert len(f.pending) == 1


def test_start_pressed_while_an_attract_ball_is_in_the_van_still_sends_it_home(
        tmp_path, monkeypatch, tr, ballmodel, coilmap):
    """The first live runs' fault: Start pressed while the attract's balls were in the van, those balls were
    kept on the playfield for the new player, the game counted them missing and ignored Start."""
    ballfeed, padsw = _sw(tmp_path, monkeypatch)
    f = _van_feeder(ballfeed, ballmodel, tr, monkeypatch, padsw)
    m = _block(padsw, *FULL[:5], 62)
    d = _led(coilmap)
    f.poll(m, d, 1.0)
    _fire(coilmap, d, 8, 4)
    f.poll(m, d, 2.0)                           # loaded with nobody here
    f.human_at = 2.2                            # Start
    _fire(coilmap, d, 8, 8)
    f.poll(m, d, 2.5)
    _fire(coilmap, d, 8, 7)
    f.poll(m, d, 3.0)
    assert f.homebound == [3.0] and f.pending == []


def test_a_ball_waiting_in_the_lane_means_a_game_and_a_quiet_full_trough_means_attract_again(
        tmp_path, monkeypatch, tr, ballmodel, coilmap):
    ballfeed, padsw = _sw(tmp_path, monkeypatch)
    f = _van_feeder(ballfeed, ballmodel, tr, monkeypatch, padsw)
    monkeypatch.setattr(ballfeed.time, "monotonic", lambda: 0.0)   # the retry gap reads this clock
    m = _block(padsw, *FULL)                    # every ball home
    d = _led(coilmap)
    f.poll(m, d, 1.0)
    _fire(coilmap, d, 8, 1)                     # the game's ball 1: eject...
    f.poll(m, d, 2.0)
    assert m[padsw.OFF_MRG + 62] == 1 and f.eject_from_full
    f.poll(m, d, 4.0)
    assert not f.van_game                       # attract plunges within a second or so
    f.poll(m, d, 5.5)
    assert f.van_game                           # ...this one waits for its player
    m[padsw.OFF_SCR_HELD + 62] = m[padsw.OFF_MRG + 62] = 0         # plunged; later the game is over,
    for i in FULL:                                                   # every ball home and quiet
        m[padsw.OFF_SCR_HELD + i] = m[padsw.OFF_MRG + i] = 1
    f.poll(m, d, 30.0)
    _fire(coilmap, d, 8, 1)                     # attract's eject from the full trough
    f.poll(m, d, 45.0)
    _fire(coilmap, d, 8, 4)                     # and its auto plunge
    f.poll(m, d, 45.5)
    assert not f.van_game and m[padsw.OFF_MRG + 52] == 1                # into the van again


def test_the_van_starts_with_its_resting_balls_once_the_trough_is_full(
        tmp_path, monkeypatch, tr, ballmodel, coilmap):
    """David: 8 balls installed, a 6-ball trough - two live in the van. An empty van at boot was a machine two
    balls short, and its attract searched for them for ever."""
    van = ballmodel.Van.from_names(VAN_NAMES)
    assert van.plan_stock(mrg_with(), 2, "lower").switches() == [(50, 1), (51, 1)]
    assert van.plan_stock(mrg_with(), 2, "upper").switches() == [(52, 1), (53, 1)]
    assert van.plan_stock(mrg_with(52), 2, "lower").refused
    ballfeed, padsw = _sw(tmp_path, monkeypatch)
    f = _van_feeder(ballfeed, ballmodel, tr, monkeypatch, padsw)
    f.van_stocked = False
    m = _block(padsw, *FULL)
    f.poll(m, _led(coilmap), 1.0)
    assert f.van_stocked and f.van.count(m[padsw.OFF_MRG:padsw.OFF_MRG + padsw.MAX_ID]) == ballmodel.VAN_STOCK


def test_the_vans_attract_release_fills_an_empty_glider_lock(tmp_path, monkeypatch, tr, ballmodel, coilmap):
    """PAD-654, turtles_le 1.59: the van cycle ran every ~20 s for as long as the rig ran, until one ball closed
    GLIDER LOCK OPTO - then it stopped and the next Start served ball 1. Later releases roll home as before."""
    ballfeed, padsw = _sw(tmp_path, monkeypatch)
    f = _van_feeder(ballfeed, ballmodel, tr, monkeypatch, padsw)
    f.van = ballmodel.Van.from_names(dict(VAN_NAMES, **{"GLIDER LOCK OPTO": 91}))
    monkeypatch.setattr(ballmodel, "VAN_CATCH_S", 0.0)
    m = _block(padsw, *FULL[:5], 62)
    d = _led(coilmap)
    f.poll(m, d, 1.0)
    for t in (2.0, 4.0):
        m[padsw.OFF_MRG + 62] = m[padsw.OFF_SCR_HELD + 62] = 1
        _fire(coilmap, d, 8, 4)                 # AUTO PLUNGER: into the van
        f.poll(m, d, t)
        _fire(coilmap, d, 8, 8)                 # UPPER LOCK
        f.poll(m, d, t + 0.5)
        _fire(coilmap, d, 8, 7)                 # LOWER LOCK: out
        f.poll(m, d, t + 1.0)
        if t == 2.0:
            assert m[padsw.OFF_MRG + 91] == 1 and f.homebound == []       # the glider took the first
    assert f.homebound == [5.0]                                         # the next rolls home
    assert f.held(m[padsw.OFF_MRG:padsw.OFF_MRG + padsw.MAX_ID]) == 1   # the glider's ball is not in play


def test_a_drain_by_hand_does_not_count_balls_in_a_lock(ballmodel):
    names = dict(VAN_NAMES, **{"GLIDER LOCK OPTO": 91})
    assert sorted(ballmodel.lock_ids(names)) == [50, 51, 52, 53, 54, 91]
    assert sorted(ballmodel.lock_ids(DND_HOLD)) == [83, 91, 92, 93, 94]
    assert ballmodel.lock_ids({"SHOOTER LANE": 62}) == []


# --- PAD-654: a hold the game stocks in attract (D&D LE's dragon) -------

#: dungeons_and_dragons_le 1.10's own ids and coils
DND_HOLD = {"DRAGON HOLD STACK": 83, "DRAGON HOLD 4": 94, "DRAGON HOLD 3": 93, "DRAGON HOLD 2": 92,
            "DRAGON HOLD 1": 91}
DND_COILS = {"DRAGON VUK": (9, 3), "DIVERTER": (9, 0)}


def test_only_a_title_with_every_hold_switch_and_both_coils_has_a_hold(ballmodel):
    h = ballmodel.Hold.from_names(DND_HOLD, DND_COILS.get)
    assert h.stack == [91, 92, 93, 94, 83] and h.balls == 4     # PAD-713: HOLD 1 is the release end, STACK last     # the four Start fills it with, on top of the six
    assert ballmodel.Hold.from_names(DND_HOLD, {"DRAGON VUK": (9, 3)}.get) is None
    half = dict(DND_HOLD)
    del half["DRAGON HOLD 1"]
    assert ballmodel.Hold.from_names(half, DND_COILS.get) is None


def test_a_hold_fills_from_its_release_end_and_lets_out_the_ball_there(ballmodel, monkeypatch):
    monkeypatch.setattr(ballmodel, "VAN_DROP_S", 0.0)
    h = ballmodel.Hold.from_names(DND_HOLD, DND_COILS.get)
    assert h.plan_load(mrg_with()).switches() == [(91, 1)]
    assert h.plan_load(mrg_with(91)).switches() == [(92, 1)]
    assert h.plan_load(mrg_with(91, 92, 93, 94)).switches() == [(83, 1)]     # STACK only as the fifth
    assert h.plan_load(mrg_with(83, 94, 93, 92, 91)).refused
    assert h.plan_release(mrg_with()).refused
    assert h.plan_release(mrg_with(91)).switches() == [(91, 0)]
    # two balls: the one at the release end leaves, the one behind it rolls down
    out = mrg_with(91, 92)
    for sw, v in h.plan_release(out).switches():
        out[sw] = v
    assert (out[91], out[92]) == (1, 0)


def test_a_lone_ball_in_the_hold_never_sits_on_stack(ballmodel):
    """PAD-713: the game reads DRAGON HOLD STACK made with the hold empty as a JAM (dragon_jam_event_handler kicks
    it out at once, on every boot after the first) - attract loaded and kicked for ever and no game ever started."""
    h = ballmodel.Hold.from_names(DND_HOLD, DND_COILS.get)
    m = mrg_with()
    for _ in range(4):
        for sw, v in h.plan_load(m).switches():
            m[sw] = v
        assert m[83] == 0


def _hold_feeder(ballfeed, ballmodel, tr, monkeypatch, padsw):
    f = _feeder(ballfeed, tr, lane=62)
    f.hold = ballmodel.Hold.from_names(DND_HOLD, DND_COILS.get)
    f.eject_coil, f.plunge_coil = (8, 1), (8, 4)
    for k in ("HOLD_FLIGHT_S", "VAN_DROP_S"):
        monkeypatch.setattr(ballmodel, k, 0.0)

    def confirmed(m, sw, v):                    # the guest's merge, at once
        m[padsw.OFF_SCR_HELD + sw] = v
        m[padsw.OFF_MRG + sw] = v
        return True
    monkeypatch.setattr(padsw, "set_confirmed", confirmed)
    return f


def test_in_attract_a_diverted_launch_goes_into_the_hold(tmp_path, monkeypatch, tr, ballmodel, coilmap):
    """The live loop (D&D LE 1.10, 2026-10-20): TROUGH + DIVERTER, AUTO PLUNGER, every ~8 s while the hold is
    empty - each ball came back to the trough and the game never took Start."""
    ballfeed, padsw = _sw(tmp_path, monkeypatch)
    f = _hold_feeder(ballfeed, ballmodel, tr, monkeypatch, padsw)
    m = _block(padsw, *FULL[:5], 62)            # attract's ball waits in the lane
    d = _led(coilmap)
    f.poll(m, d, 1.0)                           # seeds every counter
    _fire(coilmap, d, 9, 0)                     # DIVERTER, with the eject
    f.poll(m, d, 1.5)
    _fire(coilmap, d, 8, 4)                     # AUTO PLUNGER
    f.poll(m, d, 2.0)
    assert m[padsw.OFF_MRG + 62] == 0 and m[padsw.OFF_MRG + 91] == 1 and m[padsw.OFF_MRG + 83] == 0
    assert f.pending == []                      # not a ball on the playfield


def test_start_fills_the_hold_and_ball_1_with_no_diverter_goes_onto_the_playfield(
        tmp_path, monkeypatch, tr, ballmodel, coilmap):
    """D&D LE at Start: three more diverted launches fill the hold to four, then ball 1 is served with NO diverter
    fire. A rule keyed on Start sent the diverted ones onto the playfield and the game emptied its trough."""
    ballfeed, padsw = _sw(tmp_path, monkeypatch)
    f = _hold_feeder(ballfeed, ballmodel, tr, monkeypatch, padsw)
    m = _block(padsw, *FULL, 91)                # attract left one in the hold
    d = _led(coilmap)
    f.poll(m, d, 1.0)
    t = 1.0
    for _ in range(3):
        m[padsw.OFF_MRG + 62] = m[padsw.OFF_SCR_HELD + 62] = 1   # the eject's ball in the lane
        _fire(coilmap, d, 9, 0)                 # DIVERTER
        f.poll(m, d, t + 0.1)
        _fire(coilmap, d, 8, 4)                 # AUTO PLUNGER
        f.poll(m, d, t + 0.6)
        t += 2.0
    assert [m[padsw.OFF_MRG + i] for i in (91, 92, 93, 94, 83)] == [1, 1, 1, 1, 0]
    assert f.pending == []
    m[padsw.OFF_MRG + 62] = m[padsw.OFF_SCR_HELD + 62] = 1       # ball 1, no diverter
    _fire(coilmap, d, 8, 4)
    f.poll(m, d, t + ballmodel.HOLD_FEED_S + 1)
    assert m[padsw.OFF_MRG + 62] == 0 and m[padsw.OFF_MRG + 83] == 0 and len(f.pending) == 1


def test_a_launch_long_after_the_diverter_is_not_the_holds(tmp_path, monkeypatch, tr, ballmodel, coilmap):
    ballfeed, padsw = _sw(tmp_path, monkeypatch)
    f = _hold_feeder(ballfeed, ballmodel, tr, monkeypatch, padsw)
    m = _block(padsw, *FULL[:5], 62)
    d = _led(coilmap)
    f.poll(m, d, 1.0)
    _fire(coilmap, d, 9, 0)
    f.poll(m, d, 1.5)
    _fire(coilmap, d, 8, 4)
    f.poll(m, d, 1.5 + ballmodel.HOLD_FEED_S + 1)
    assert m[padsw.OFF_MRG + 91] == 0 and len(f.pending) == 1


def test_the_holds_release_is_a_ball_on_the_playfield(tmp_path, monkeypatch, tr, ballmodel, coilmap):
    ballfeed, padsw = _sw(tmp_path, monkeypatch)
    f = _hold_feeder(ballfeed, ballmodel, tr, monkeypatch, padsw)
    m = _block(padsw, *FULL[:4], 91, 92)
    d = _led(coilmap)
    f.poll(m, d, 1.0)
    _fire(coilmap, d, 9, 3)                     # DRAGON VUK
    f.poll(m, d, 2.0)
    assert (m[padsw.OFF_MRG + 91], m[padsw.OFF_MRG + 92]) == (1, 0) and len(f.pending) == 1
    _fire(coilmap, d, 9, 3)
    f.poll(m, d, 3.0)
    assert m[padsw.OFF_MRG + 91] == 0 and len(f.pending) == 2
    f.poll(m, d, 3.0 + ballfeed.HOME_S + 0.5)    # nobody playing: the way home takes one back
    assert len(f.pending) == 1 and m[padsw.OFF_MRG + FULL[4]] == 1



# --- PAD-248: drop target banks --------------------------------------------

#: john_wick_le's, off its built tables: DROP TARGET OPTO is switch 81, DROP TRIP node 9 index 6, DROP RESET
#: node 9 index 8
JW_DROP = {"DROP TRIP": (9, 6), "DROP RESET": (9, 8)}


def test_a_bank_needs_its_coils_and_every_switch(ballmodel):
    B = ballmodel.DropBank
    assert B.from_names({"DROP TARGET OPTO": 81}, JW_DROP.get)
    assert B.from_names({"DROP TARGET OPTO": 81}, {"DROP TRIP": (9, 6)}.get) == []   # no reset coil
    assert B.from_names({"DROP TARGET OPTO": 81}, {"DROP RESET": (9, 8)}.get) == []  # the named trip is missing
    assert B.from_names({"SHOOTER LANE": 69}, JW_DROP.get) == []
    t, = B.from_names({"DROP TARGET OPTO": 81}, JW_DROP.get)
    assert (t.trip, t.reset, t.switches) == ((9, 6), (9, 8), [81])


def test_one_coil_name_on_two_titles_matches_only_with_its_own_switches(ballmodel):
    """"3 BANK DROP" is jaws_le's reset coil and metallica's - with different switches."""
    coil = {"3 BANK DROP": (9, 1)}.get
    jaws, = ballmodel.DropBank.from_names({"3 BANK BOT": 69, "3 BANK MID": 70, "3 BANK TOP": 71}, coil)
    assert jaws.switches == [69, 70, 71] and jaws.trip is None
    met, = ballmodel.DropBank.from_names({"DROP TGT- BOT": 48, "DROP TGT- MID": 49, "DROP TGT- TOP": 50}, coil)
    assert met.switches == [48, 49, 50]
    assert ballmodel.DropBank.from_names({"3 BANK BOT": 69, "3 BANK MID": 70}, coil) == []   # one missing


def test_trip_makes_the_switches_and_reset_opens_them(ballmodel):
    """Measured: john_wick_le fires RESET then TRIP and is satisfied once the opto reads MADE - so made is
    down. A reset moves only the targets that are down."""
    t, = ballmodel.DropBank.from_names({"DROP TARGET OPTO": 81}, JW_DROP.get)
    assert t.down_level == 1
    assert t.plan_fire("trip", mrg_with()).switches() == [(81, 1)]
    assert t.plan_fire("reset", mrg_with(81)).switches() == [(81, 0)]
    assert t.plan_fire("trip", mrg_with(81)) is None             # already down
    assert t.plan_fire("reset", mrg_with()) is None              # already up
    bank = ballmodel.DropBank(None, (9, 1), [69, 70, 71], ["B", "M", "T"])
    assert bank.plan_fire("reset", mrg_with(69, 71)).switches() == [(69, 0), (71, 0)]
    flipped = ballmodel.DropBank((9, 6), (9, 8), [81], ["X"], down_level=0)
    assert flipped.plan_fire("trip", mrg_with(81)).switches() == [(81, 0)]


def test_the_feeder_answers_the_games_reset_trip_burst(tmp_path, monkeypatch, tr, ballmodel, coilmap):
    """The burst the rig measured: RESET, TRIP 100 ms later. Answered, the target ends down (opto made);
    a later RESET brings it up. Nothing answers before the counters are seeded."""
    ballfeed, padsw = _sw(tmp_path, monkeypatch)
    f = _van_feeder(ballfeed, ballmodel, tr, monkeypatch, padsw)
    f.van = None
    monkeypatch.setattr(ballmodel, "DROP_MOVE_S", 0.0)
    f.drops = ballmodel.DropBank.from_names({"DROP TARGET OPTO": 81}, JW_DROP.get)
    m = _block(padsw, *FULL)
    d = _led(coilmap)
    _fire(coilmap, d, 9, 6)                     # a run already going: seeds, moves nothing
    f.poll(m, d, 1.0)
    assert m[padsw.OFF_MRG + 81] == 0
    _fire(coilmap, d, 9, 8)                     # RESET: already up
    f.poll(m, d, 2.0)
    assert m[padsw.OFF_MRG + 81] == 0
    _fire(coilmap, d, 9, 6)                     # TRIP
    f.poll(m, d, 2.1)
    assert m[padsw.OFF_MRG + 81] == 1
    _fire(coilmap, d, 9, 8)                     # RESET
    f.poll(m, d, 3.0)
    assert m[padsw.OFF_MRG + 81] == 0


def test_every_listed_bank_is_well_formed(ballmodel):
    """Every DROP_BANKS row is well formed: names upper-case and trimmed (the feeder compares them that way,
    so a lower-case one could never match) and no switch listed twice."""
    for trip, reset, names in ballmodel.DROP_BANKS:
        assert reset and names and len(set(names)) == len(names)
        assert all(n == n.upper().strip() for n in names + ((trip,) if trip else ()) + (reset,))


def test_coilcount_names_the_fires_busiest_first():
    """motorcheck.sh's coils= field (PAD-248): cmd 40 fire frames by (node, index), names from the table,
    everything else in the trace ignored."""
    import coilcount
    lines = ["[nbts] t=62143 node=9 cmd=40 len=14 890b4008ff060000000000001f00",
             "[nbts] t=62243 node=9 cmd=40 len=14 890b4006ff060000000000002100",
             "[nbts] t=62493 node=9 cmd=40 len=14 890b4008ff060000000000001f00",
             "[nbts] t=62500 node=9 cmd=53 len=10 89075300fa14c8004700",
             "[nbts] t=62600 node=8 cmd=40 len=14 880b4001ff000000000000002e00",
             "[sw] 62109 ms +36l"]
    c = coilcount.count(lines)
    assert c == {(9, 8): 2, (9, 6): 1, (8, 1): 1}
    names = {(9, 8): "DROP RESET", (9, 6): "DROP TRIP"}
    assert coilcount.text(c, names) == "DROP_RESET=2,n8i1=1,DROP_TRIP=1"
    assert coilcount.text(c, names, least=2) == "DROP_RESET=2"
    assert coilcount.text({}, names) == "-"

