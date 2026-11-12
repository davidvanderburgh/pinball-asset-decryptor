"""PAD-1137: the Spike 3 ball model keeps a launched ball alive. With no
playfield a ball in play moved no switch, and pokemon_le ended it (and, ball
after ball, the game) as lost. While a ball is in play and no playfield switch
has moved for ALIVE_S, the model taps a slingshot; somebody playing restarts
the wait; nothing is tapped with every ball home or in the shooter lane."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "spike3_emu"))

import s3balls  # noqa: E402

# pokemon_le's own names and places (s3nodes.devices, node 8/9)
DEVS = [
    ("TROUGH 6", 8, 32, "switch"), ("TROUGH 5", 8, 33, "switch"), ("TROUGH 4", 8, 34, "switch"),
    ("TROUGH 3", 8, 35, "switch"), ("TROUGH 2", 8, 36, "switch"), ("TROUGH 1", 8, 37, "switch"),
    ("TROUGH JAM", 8, 38, "switch"), ("SHOOTER LANE", 8, 28, "switch"),
    ("LEFT SLINGSHOT", 8, 29, "switch"), ("RIGHT SLINGSHOT", 8, 30, "switch"),
    ("LEFT RETURN LANE", 8, 26, "switch"), ("LEFT OUTLANE", 8, 27, "switch"),
    ("TOP POP BUMPER", 9, 28, "switch"), ("SPINNER OPTO", 9, 3, "switch"),
    ("LEFT FLIPPER BUTTON", 8, 25, "switch"), ("LEFT FLIPPER EOS", 8, 16, "switch"),
    ("START BUTTON", 1, 11, "switch"), ("MEOWTH UP", 9, 24, "switch"),
    ("TROUGH", 8, 1, "coil"), ("AUTO PLUNGER", 8, 4, "coil"),
]
SLINGS = {(8, 29), (8, 30)}


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(s3balls, "ALIVE_S", 0.3)
    monkeypatch.setattr(s3balls, "TAP_S", 0.03)


def _balls(devs=DEVS):
    sw = bytearray(512)
    return sw, s3balls.Balls(sw, s3balls.resolve(devs))


def _launch(b):
    """Serve and launch one ball, the way the game does."""
    b.coil(8, bytes([0x40, 1, 0xFF] + [0] * 8))
    b.coil(8, bytes([0x40, 4, 0xFF] + [0] * 8))
    b.coil(8, bytes([0x40, 1, 0xE1, 6] + [0] * 7))
    _run(b, 0.6)
    b.coil(8, bytes([0x40, 4, 0x96, 6] + [0] * 7))


def _run(b, secs, watch=None):
    """Tick for SECS; with WATCH, count the closing edges of those switches."""
    seen, was = 0, False
    end = time.time() + secs
    while time.time() < end:
        b.tick()
        on = any(b.made(nb) for nb in watch) if watch else False
        seen += on and not was
        was = on
        time.sleep(0.005)
    return seen


def test_resolve_picks_slings_and_the_playfield():
    w = s3balls.resolve(DEVS)
    assert [tuple(a[:2]) for a in w["alive"]] == [(8, 29), (8, 30)]
    pf = {tuple(x) for x in w["playfield"]}
    # ball switches are the playfield; buttons, trough, lane, EOS, motor stops are not
    assert {(8, 29), (8, 26), (8, 27), (9, 28), (9, 3)} <= pf
    assert not pf & {(8, 32), (8, 37), (8, 38), (8, 28), (8, 25), (8, 16), (1, 11), (9, 24)}


def test_resolve_falls_back_to_lanes_then_pops():
    no_sling = [d for d in DEVS if "SLING" not in d[0]]
    assert [a[2] for a in s3balls.resolve(no_sling)["alive"]] == ["LEFT RETURN LANE"]
    pops_only = [d for d in no_sling if "RETURN" not in d[0]]
    assert [a[2] for a in s3balls.resolve(pops_only)["alive"]] == ["TOP POP BUMPER"]
    # an outlane is never tapped: it would drain the ball on a real machine
    assert s3balls.resolve([d for d in pops_only if "POP" not in d[0]])["alive"] == []


def test_a_ball_in_play_is_kept_alive(fast):
    _sw, b = _balls()
    _launch(b)
    _run(b, 0.1)
    assert b.out() == 1
    taps = _run(b, 1.5, SLINGS)
    assert 3 <= taps <= 6                          # one every ~0.3 s
    _run(b, 0.1)
    assert not any(b.made(nb) for nb in SLINGS)


def test_taps_alternate_between_the_slings(fast):
    _sw, b = _balls()
    _launch(b)
    got = []
    end = time.time() + 1.6
    while time.time() < end:
        b.tick()
        for nb in SLINGS:
            if b.made(nb) and (not got or got[-1] != nb):
                got.append(nb)
        time.sleep(0.005)
    assert len(got) >= 3 and all(a != c for a, c in zip(got, got[1:]))


def test_no_tap_with_no_ball_out(fast):
    _sw, b = _balls()
    assert _run(b, 1.0, SLINGS) == 0               # attract: every ball home
    b.coil(8, bytes([0x40, 1, 0xFF] + [0] * 8))
    b.coil(8, bytes([0x40, 1, 0xE1, 6] + [0] * 7))
    _run(b, 0.6)
    assert b.made((8, 28)) and b.out() == 0         # waiting in the shooter lane
    assert _run(b, 1.0, SLINGS) == 0


def test_a_drain_clicked_in_the_window_stops_the_taps(fast):
    """The window's trough dot closes a trough switch itself: the derived
    count sees it, with no drain() call."""
    _sw, b = _balls()
    _launch(b)
    _run(b, 0.1)
    b.set((8, 32), True)                            # TROUGH 6 closes: the ball is home
    assert b.out() == 0
    assert _run(b, 1.0, SLINGS) == 0


def test_somebody_playing_is_not_tapped_over(fast):
    _sw, b = _balls()
    _launch(b)
    end = time.time() + 1.5
    taps, was = 0, False
    k = 0
    while time.time() < end:
        k += 1
        if k % 20 == 0:                             # a playfield hit every ~0.1 s
            b.set((9, 3), not b.made((9, 3)))
        b.tick()
        on = any(b.made(nb) for nb in SLINGS)
        taps += on and not was
        was = on
        time.sleep(0.005)
    assert taps == 0


def test_buttons_do_not_count_as_playing(fast):
    """A flipper button or Start is not the ball: the wait runs on."""
    _sw, b = _balls()
    _launch(b)
    end = time.time() + 1.5
    taps, was, k = 0, False, 0
    while time.time() < end:
        k += 1
        if k % 20 == 0:
            b.set((8, 25), not b.made((8, 25)))
        b.tick()
        on = any(b.made(nb) for nb in SLINGS)
        taps += on and not was
        was = on
        time.sleep(0.005)
    assert taps >= 3


def test_off_switch(monkeypatch):
    monkeypatch.setattr(s3balls, "ALIVE_S", 0.0)
    _sw, b = _balls()
    _launch(b)
    assert _run(b, 1.0, SLINGS) == 0
