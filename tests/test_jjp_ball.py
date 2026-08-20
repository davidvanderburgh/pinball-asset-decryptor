"""Headless tests for the JJP ball feeder (tools/jjp_emu/jjpball.py).

The whole point of jjpball's Plan shape is that the DECISIONS can be tested
without a running game, a mapped block or a sleep - so these drive the model
against switch tables written by hand, and the Feeder against a fake shm.
"""

import importlib.util
import os

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JJPBALL = os.path.join(HERE, "tools", "jjp_emu", "jjpball.py")


@pytest.fixture(scope="module")
def b():
    if not os.path.exists(JJPBALL):
        pytest.skip("tools/jjp_emu/jjpball.py not present")
    spec = importlib.util.spec_from_file_location("jjpball_undertest", JJPBALL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The real Wonka addresses, from the live device tables.  Note the frame order
# is NOT the position order - trough_5 is bit 0 and trough_1 is bit 4, with the
# jam at bit 5 BETWEEN #1 and #6.
WONKA_SWITCHES = {
    (4, 0x01): {"symbol": "switch_trough_5", "name": "6-Ball Trough #5"},
    (4, 0x02): {"symbol": "switch_trough_4", "name": "6-Ball Trough #4"},
    (4, 0x04): {"symbol": "switch_trough_3", "name": "6-Ball Trough #3"},
    (4, 0x08): {"symbol": "switch_trough_2", "name": "6-Ball Trough #2"},
    (4, 0x10): {"symbol": "switch_trough_1", "name": "6-Ball Trough #1 (right)"},
    (4, 0x20): {"symbol": "switch_trough_jam", "name": "6-Ball Trough jam"},
    (4, 0x40): {"symbol": "switch_trough_6", "name": "6-Ball Trough #6 (left)"},
    (10, 0x40): {"symbol": "switch_shooter", "name": "Shooter Lane"},
    (9, 0x04): {"symbol": "switch_outlane_left", "name": "Left Outlane"},
    (7, 0x80): {"symbol": "switch_loop_left", "name": "Left Loop"},
}

WONKA_COILS = [
    {"symbol": "coil_vuk_gobstopper", "name": "Gobstopper Hole VUK",
     "frame_byte": 0, "frame_bit": 0x01, "pulse_ms": 32},
    {"symbol": "coil_vuk_trough", "name": "Trough VUK",
     "frame_byte": 1, "frame_bit": 0x10, "pulse_ms": 32},
    {"symbol": "coil_autolaunch", "name": "Auto Launch",
     "frame_byte": 1, "frame_bit": 0x20, "pulse_ms": 32},
]

TROUGH_KEYS = [(4, 0x10), (4, 0x08), (4, 0x04), (4, 0x02), (4, 0x01), (4, 0x40)]
LANE = (10, 0x40)
JAM = (4, 0x20)


class FakeShm:
    """Just enough of SwitchShm: closed/open by key, plus rise counters."""

    FRAME_LEN = 64

    def __init__(self):
        self.closed = set()
        self.rise = {}

    def set_switch(self, fb, mask, closed):
        (self.closed.add if closed else self.discard)((fb, mask))

    def discard(self, key):
        self.closed.discard(key)

    def get_switch(self, fb, mask):
        return (fb, mask) in self.closed

    def out_rise(self, board, fb, bitno):
        return self.rise.get((board, fb, bitno), 0)

    def fire(self, fb, mask, board=0, times=1):
        k = (board, fb, mask.bit_length() - 1)
        self.rise[k] = (self.rise.get(k, 0) + times) % 256


def make_feeder(b, shm, **kw):
    """A feeder whose 'wait' happens immediately, so tests need no sleeps."""
    clock = {"t": 0.0}
    kw.setdefault("now", lambda: clock["t"])
    f = b.Feeder(shm, WONKA_SWITCHES, WONKA_COILS,
                 after=lambda ms, fn: fn(), **kw)
    f.clock = clock
    return f


# --------------------------------------------------------------- resolution

def test_trough_is_ordered_by_name_not_by_frame_address(b):
    positions, how = b.find_trough(WONKA_SWITCHES)
    assert how == "named switch_trough_N"
    # Position 1 is the EJECT end; sorting by address would give 5,4,3,2,1,6.
    assert [n for n, _k in positions] == [1, 2, 3, 4, 5, 6]
    assert [k for _n, k in positions] == TROUGH_KEYS
    # The jam is NOT a ball position.
    assert JAM not in [k for _n, k in positions]
    assert b.find_jam(WONKA_SWITCHES) == JAM
    assert b.find_lane(WONKA_SWITCHES) == LANE


def test_trough_falls_back_to_frame_order_and_says_so(b):
    odd = {(4, 0x02): {"symbol": "switch_ball_home_b", "name": "Trough right"},
           (4, 0x01): {"symbol": "switch_ball_home_a", "name": "Trough left"}}
    positions, how = b.find_trough(odd)
    assert [k for _n, k in positions] == [(4, 0x01), (4, 0x02)]
    assert "UNVERIFIED" in how


def test_no_trough_switches_is_said_plainly(b):
    positions, how = b.find_trough({LANE: WONKA_SWITCHES[LANE]})
    assert positions == []
    assert "no trough" in how


def test_find_coil_prefers_the_exact_symbol(b):
    # 'trough' alone also matches coil_vuk_trough, but the exact name must win
    # over any prefix/substring hit.
    assert b.find_coil(WONKA_COILS, b.EJECT_COIL_PATTERNS) == \
        (1, 0x10, 32, "coil_vuk_trough")
    assert b.find_coil(WONKA_COILS, b.LAUNCH_COIL_PATTERNS) == \
        (1, 0x20, 32, "coil_autolaunch")
    assert b.find_coil(WONKA_COILS, ("coil_nonexistent",)) is None


def test_coil_without_an_out_address_is_not_resolved(b):
    # A coil we cannot watch is the same as a coil that is not there; returning
    # it half-resolved would make the feeder silently never fire.
    assert b.find_coil([{"symbol": "coil_vuk_trough", "frame_byte": None,
                         "frame_bit": None}], b.EJECT_COIL_PATTERNS) is None


# ------------------------------------------------------------------- trough

def _closed_from(keys):
    s = set(keys)
    return lambda k: k in s


def test_leaving_is_the_far_end_not_the_eject_end(b):
    tr = b.Trough([(i + 1, k) for i, k in enumerate(TROUGH_KEYS)])
    full = _closed_from(TROUGH_KEYS)
    assert tr.count(full) == 6 and tr.full(full)
    # THE TRAP: the eject kicks position 1, the rest roll down, and the hole
    # appears at position 6.
    assert tr.leaving(full) == TROUGH_KEYS[5]
    assert tr.arriving(full) is None            # full - nowhere to arrive
    four = _closed_from(TROUGH_KEYS[:4])
    assert tr.leaving(four) == TROUGH_KEYS[3]
    assert tr.arriving(four) == TROUGH_KEYS[4]  # lowest OPEN position
    empty = _closed_from([])
    assert tr.leaving(empty) is None
    assert tr.arriving(empty) == TROUGH_KEYS[0]


def test_anomaly_names_a_trough_that_is_not_a_stack(b):
    tr = b.Trough([(i + 1, k) for i, k in enumerate(TROUGH_KEYS)])
    assert tr.anomaly(_closed_from(TROUGH_KEYS[:3])) is None
    hole = _closed_from([TROUGH_KEYS[0], TROUGH_KEYS[4]])
    msg = tr.anomaly(hole)
    assert msg and "not a stack" in msg and "1,5" in msg


# -------------------------------------------------------------------- plans

def test_plan_eject_opens_the_far_end_then_fills_the_lane(b):
    tr = b.Trough([(i + 1, k) for i, k in enumerate(TROUGH_KEYS)])
    plan = b.plan_eject(tr, _closed_from(TROUGH_KEYS), LANE, False, flight_ms=350)
    assert plan
    assert plan.sets() == [(TROUGH_KEYS[5], False), (LANE, True)]
    assert [s[0] for s in plan.steps] == ["set", "wait", "set"]
    assert plan.steps[1][1] == 350


def test_plan_eject_refuses_an_empty_trough_and_an_occupied_lane(b):
    tr = b.Trough([(i + 1, k) for i, k in enumerate(TROUGH_KEYS)])
    empty = b.plan_eject(tr, _closed_from([]), LANE, False)
    assert not empty and "empty" in empty.refused
    busy = b.plan_eject(tr, _closed_from(TROUGH_KEYS), LANE, True)
    assert not busy and "already in the shooter lane" in busy.refused
    none = b.plan_eject(b.Trough([]), _closed_from([]), LANE, False)
    assert not none and "no trough switches" in none.refused


def test_plan_launch_and_drain(b):
    tr = b.Trough([(i + 1, k) for i, k in enumerate(TROUGH_KEYS)])
    assert b.plan_launch(LANE, True).sets() == [(LANE, False)]
    assert not b.plan_launch(LANE, False)
    assert not b.plan_launch(None, True)
    # A drained ball comes home to the lowest OPEN position.
    assert b.plan_drain(tr, _closed_from(TROUGH_KEYS[:4])).sets() == \
        [(TROUGH_KEYS[4], True)]
    full = b.plan_drain(tr, _closed_from(TROUGH_KEYS))
    assert not full and "already full" in full.refused


# ------------------------------------------------------------------- feeder

def test_seat_trough_fills_balls_leaves_jam_and_lane_open(b):
    shm = FakeShm()
    f = make_feeder(b, shm)
    keys = f.seat_trough()
    assert set(keys) == set(TROUGH_KEYS)
    assert all(shm.get_switch(*k) for k in TROUGH_KEYS)
    assert not shm.get_switch(*JAM)     # a closed jam reads as a stuck ball
    assert not shm.get_switch(*LANE)
    assert f.in_trough() == 6 and f.in_play() == 0


def test_first_sight_of_a_counter_seeds_it_and_feeds_nothing(b):
    # Coming up beside a run already in progress must not read the whole run's
    # fire count as one fire.
    shm = FakeShm()
    shm.fire(1, 0x10, times=40)         # the run has been ejecting for a while
    f = make_feeder(b, shm)
    f.seat_trough()
    assert f.poll() is False
    assert f.in_trough() == 6


def test_eject_moves_one_ball_to_the_lane(b):
    shm = FakeShm()
    f = make_feeder(b, shm)
    f.seat_trough()
    f.poll()                            # seed
    shm.fire(1, 0x10)
    assert f.poll() is True
    assert f.in_trough() == 5
    assert not shm.get_switch(*TROUGH_KEYS[5])   # the FAR end opened
    assert shm.get_switch(*LANE)                 # ball waiting in the lane
    assert f.in_play() == 0                      # the lane is not "in play"
    assert f.fed == 1


def test_launch_takes_the_ball_out_of_the_lane_and_into_play(b):
    shm = FakeShm()
    f = make_feeder(b, shm)
    f.seat_trough()
    f.poll()
    shm.fire(1, 0x10)
    f.poll()
    shm.fire(1, 0x20)                   # coil_autolaunch
    f.poll()
    assert not shm.get_switch(*LANE)
    assert f.in_trough() == 5 and f.in_play() == 1
    assert f.launched == 1


def test_the_whole_loop_returns_the_ball_home(b):
    shm = FakeShm()
    f = make_feeder(b, shm)
    f.seat_trough()
    f.poll()
    shm.fire(1, 0x10)
    f.poll()
    f.clock["t"] += 5.0
    shm.fire(1, 0x20)
    f.poll()
    assert f.in_play() == 1
    assert f.drain() is True
    assert f.in_trough() == 6 and f.in_play() == 0
    # And the trough is a contiguous stack again.
    assert f.trough.anomaly(f.is_closed) is None


def test_a_second_eject_inside_the_min_gap_is_refused_as_a_retry(b):
    # A chopped drive raises the bit several times inside one 32 ms fire, and a
    # game that has not seen its trough change re-pulses the coil.
    shm = FakeShm()
    said = []
    f = make_feeder(b, shm, log=said.append, min_gap_ms=600)
    f.seat_trough()
    f.poll()
    shm.fire(1, 0x10)
    f.poll()
    assert f.in_trough() == 5
    # Clear the lane so the lane rule is not what refuses, then fire again.
    shm.set_switch(LANE[0], LANE[1], False)
    f.clock["t"] += 0.1
    shm.fire(1, 0x10)
    f.poll()
    assert f.in_trough() == 5           # still one ball out, not two
    assert any("min gap" in s for s in said)
    # Past the gap it feeds again.
    f.clock["t"] += 1.0
    shm.fire(1, 0x10)
    f.poll()
    assert f.in_trough() == 4


def test_an_eject_into_an_occupied_lane_is_refused_once_not_every_poll(b):
    shm = FakeShm()
    said = []
    f = make_feeder(b, shm, log=said.append, plunge_delay_s=0)  # no auto-plunge
    f.seat_trough()
    f.poll()
    shm.fire(1, 0x10)
    f.poll()                            # ball now in the lane
    for i in range(5):
        f.clock["t"] += 1.0
        shm.fire(1, 0x10)
        f.poll()
    lane_msgs = [s for s in said if "already in the shooter lane" in s]
    assert len(lane_msgs) == 1          # deduplicated, not a flood
    assert f.in_trough() == 5


def test_a_parked_ball_auto_plunges_after_the_delay_and_validates(b):
    shm = FakeShm()
    said = []
    f = make_feeder(b, shm, log=said.append, plunge_delay_s=2.5)
    f.seat_trough()
    f.poll()
    shm.fire(1, 0x10)                   # trough eject -> ball to the lane
    f.poll()
    assert f.lane_made()               # parked in the shooter lane
    for _ in range(2):                 # not yet past the delay
        f.clock["t"] += 1.0
        f.poll()
    assert f.lane_made()               # still parked
    f.clock["t"] += 1.0                # now past 2.5 s
    f.poll()
    assert not f.lane_made()           # launched
    assert f.validated == 1            # and the playfield was validated
    assert any("plunge:" in s for s in said)
    assert any("validate:" in s for s in said)


def test_a_human_plunge_also_validates(b):
    shm = FakeShm()
    said = []
    f = make_feeder(b, shm, log=said.append)
    f.seat_trough()
    f.poll()
    shm.fire(1, 0x10)
    f.poll()                            # ball in the lane
    assert f.plunge() is True
    assert not f.lane_made()
    assert f.validated == 1


def test_auto_plunge_off_leaves_the_ball_in_the_lane(b):
    shm = FakeShm()
    f = make_feeder(b, shm, plunge_delay_s=0)
    f.seat_trough()
    f.poll()
    shm.fire(1, 0x10)
    f.poll()
    for _ in range(10):
        f.clock["t"] += 1.0
        f.poll()
    assert f.lane_made()               # never auto-plunged
    assert f.validated == 0


def test_empty_trough_refuses_rather_than_inventing_a_ball(b):
    shm = FakeShm()
    said = []
    f = make_feeder(b, shm, log=said.append)
    f.poll()                            # trough never seated: it is empty
    f.clock["t"] += 1.0
    shm.fire(1, 0x10)
    assert f.poll() is False
    assert any("empty" in s for s in said)
    assert f.in_trough() == 0


def test_a_title_without_the_eject_coil_is_unusable_and_says_so(b):
    shm = FakeShm()
    f = b.Feeder(shm, WONKA_SWITCHES, [], after=lambda ms, fn: fn())
    assert f.usable() is False
    assert any("NOT IN THE COIL TABLE" in line for line in f.describe())
    assert f.poll() is False


def _launch_one(b, shm, f):
    """Get one ball from the trough, through the lane, into play."""
    f.seat_trough()
    f.poll()
    shm.fire(1, 0x10)
    f.poll()
    shm.fire(1, 0x20)
    f.poll()
    assert f.in_play() == 1


def test_a_forgotten_ball_comes_home_by_itself(b):
    # The machine's own power-up ball search launches every ball it has; with
    # nothing bringing them back the trough empties and the game hunts for
    # balls for ever.  A real ball drains in seconds when nobody is flipping.
    shm = FakeShm()
    said = []
    f = make_feeder(b, shm, log=said.append, auto_drain_s=20.0)
    _launch_one(b, shm, f)
    f.clock["t"] += 5.0
    f.poll()
    assert f.in_play() == 1              # not yet - still inside the window
    f.clock["t"] += 20.0
    f.poll()
    assert f.in_play() == 0 and f.in_trough() == 6
    assert f.auto_drained == 1
    assert any("nobody was flipping" in s for s in said)


def test_playing_keeps_the_ball_alive(b):
    # Any switch outside the ball path is somebody playing, and restarts the
    # clock - otherwise the ball would vanish mid-game.
    shm = FakeShm()
    f = make_feeder(b, shm, auto_drain_s=20.0)
    _launch_one(b, shm, f)
    for _ in range(4):
        f.clock["t"] += 15.0
        shm.set_switch(9, 0x04, True)        # a playfield switch
        f.poll()
        f.clock["t"] += 1.0
        shm.set_switch(9, 0x04, False)
        f.poll()
        assert f.in_play() == 1
    # Stop touching it and it drains.
    f.clock["t"] += 30.0
    f.poll()
    assert f.in_play() == 0


def test_a_whole_ball_search_comes_home_together(b):
    # Five balls flung out during a search drain within a second of each other,
    # not one every timeout.
    shm = FakeShm()
    said = []
    f = make_feeder(b, shm, log=said.append, auto_drain_s=20.0, min_gap_ms=0)
    f.seat_trough()
    f.poll()
    for _ in range(5):
        f.clock["t"] += 1.0
        shm.fire(1, 0x10)
        f.poll()
        shm.fire(1, 0x20)
        f.poll()
    assert f.in_play() == 5 and f.in_trough() == 1
    f.clock["t"] += 25.0
    for _ in range(6):
        f.poll()                            # six polls = well under a second
    assert f.in_play() == 0 and f.in_trough() == 6
    assert len([s for s in said if "nobody was flipping" in s]) == 1


def test_auto_drain_can_be_turned_off(b):
    shm = FakeShm()
    f = make_feeder(b, shm, auto_drain_s=0)
    _launch_one(b, shm, f)
    f.clock["t"] += 10000.0
    f.poll()
    assert f.in_play() == 1                 # only a human drains now
    assert "auto-drain off" in f.settings()


def test_describe_names_what_resolved(b):
    f = make_feeder(b, FakeShm())
    text = " | ".join(f.describe())
    assert "trough 1,2,3,4,5,6" in text
    assert "coil_vuk_trough" in text and "OUT 1.4" in text
    assert "coil_autolaunch" in text
