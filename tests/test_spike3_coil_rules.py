"""PAD-1134: the coils a Spike 3 node board fires itself by the game's cmd 41
rules - flippers, slingshots, pop bumpers - against the rule frames captured
off pokemon_le 0.82.0's bus at ball start (unmasked; each named by the
game's own device table)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "spike3_emu"))

import s3bridge  # noqa: E402
import s3leds  # noqa: E402
import s3rules  # noqa: E402

Z = "00 "


def _hex(s):
    return bytes.fromhex(s.replace(" ", ""))


# the armed rules, unmasked (cmd 41, 49 bytes), node 8 / node 9
RIGHT_FLIPPER = _hex("41 00 f5 04 00 1e 03" + " 00" * 17 + " 58 00 00 5f" + " 00" * 17 + " 05 01 00 ef")
LEFT_FLIPPER = _hex("41 05 f5 04 00 1e 03" + " 00" * 17 + " 59 00 00 50" + " 00" * 17 + " 05 01 00 f8")
RIGHT_SLING = _hex("41 02 cc 03" + " 00" * 8 + " 13" + " 00" * 11 + " 5d" + " 00" * 23 + " 85")
TOP_POP = _hex("41 02 f5 02" + " 00" * 8 + " 01" + " 00" * 11 + " 5c" + " 00" * 23 + " 6f")
CLEAR_RIGHT_FLIPPER = _hex("41 00" + " 00" * 22 + " 40" + " 00" * 23 + " 86")  # the boot clear, coil 0
BALLOON = _hex("41 07 5a e8 03" + " 00" * 23 + " 58" + " 00" * 19 + " 21")
BALLOON_RUN = _hex("40 07 ed")


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


def _rig(monkeypatch, tmp_path=None):
    monkeypatch.setenv("PAD_MOTOR_MS", "600")
    br = s3bridge.Bridge(0, open(os.devnull, "w"))
    br.sw = bytearray(512)
    fired = []
    clk = Clock()
    br.rules = s3rules.Rules(br.sw, fire=lambda n, c, p: fired.append((n, c, p)), clock=clk)
    return br, fired, clk


def _send(br, node, plain):
    """One coil frame as the game puts it on the wire: masked, no reply."""
    addr = 0xC0 | node
    assert br.handle(0x41, 1, bytes([addr, len(plain)]) + s3bridge.unmask(addr, plain) + b"\x00") is None


def _sw(br, node, bit, on):
    o = 8 * node + bit // 8
    br.sw[o] = (br.sw[o] | 1 << bit % 8) if on else (br.sw[o] & ~(1 << bit % 8))


def _made(br, node, bit):
    return bool(br.sw[8 * node + bit // 8] & 1 << bit % 8)


def test_captured_rule_frames_checksum_and_parse():
    for node, f in ((8, RIGHT_FLIPPER), (8, LEFT_FLIPPER), (8, RIGHT_SLING), (9, TOP_POP),
                    (8, CLEAR_RIGHT_FLIPPER), (9, BALLOON)):
        assert len(f) == s3rules.RULE_LEN
        assert s3rules.frame_ok(0xC0 | node, f), f.hex()
    r = s3rules.parse(RIGHT_FLIPPER)
    assert r == {"coil": 0, "pwr": 0xF5, "pulse": 4, "hold_pwr": 0x1E, "hold": 3,
                 "trig": 24, "eos": 31, "stop": None, "stop_hi": False}  # RIGHT FLIPPER BUTTON / EOS
    assert s3rules.parse(LEFT_FLIPPER)["trig"] == 25 and s3rules.parse(LEFT_FLIPPER)["eos"] == 16
    assert s3rules.parse(RIGHT_SLING)["trig"] == 29 and not s3rules.parse(RIGHT_SLING)["hold_pwr"]
    b = s3rules.parse(BALLOON)
    assert (b["trig"], b["stop"], b["pulse"]) == (None, 24, 1000)  # MEOWTH UP, 10 s limit
    assert s3rules.parse(CLEAR_RIGHT_FLIPPER)["pwr"] == 0


def test_flipper_button_fires_and_holds_the_flipper(monkeypatch):
    br, fired, clk = _rig(monkeypatch)
    _sw(br, 8, 24, True)
    br.rules.tick()
    assert fired == []                                   # no rule yet: the button is dead
    _sw(br, 8, 24, False)
    br.rules.tick()
    _send(br, 8, RIGHT_FLIPPER)
    _sw(br, 8, 24, True)                                  # RIGHT FLIPPER BUTTON
    br.attention()                                        # the bridge's poll ticks the board
    assert fired == [(8, 0, 0xF5)]
    assert not _made(br, 8, 31)                           # still in its 40 ms pulse
    clk.t += 0.05
    br.rules.tick()
    assert _made(br, 8, 31)                               # bat up: RIGHT FLIPPER EOS made
    for _ in range(5):
        br.rules.tick()
    assert fired == [(8, 0, 0xF5)]                        # held: one fire, not one per poll
    _sw(br, 8, 24, False)
    br.rules.tick()
    assert not _made(br, 8, 31)                           # released, EOS open
    _sw(br, 8, 24, True)
    br.rules.tick()
    assert len(fired) == 2


def test_slings_and_pops_fire_once_per_closing(monkeypatch):
    br, fired, clk = _rig(monkeypatch)
    _send(br, 8, RIGHT_SLING)
    _send(br, 9, TOP_POP)
    for _ in range(3):
        _sw(br, 8, 29, True)
        _sw(br, 9, 28, True)
        br.rules.tick()
        br.rules.tick()
        _sw(br, 8, 29, False)
        _sw(br, 9, 28, False)
        br.rules.tick()
    assert fired.count((8, 2, 0xCC)) == 3 and fired.count((9, 2, 0xF5)) == 3
    assert not _made(br, 8, 31) and not _made(br, 8, 16)   # no EOS on a sling


def test_cleared_rule_kills_the_flipper_and_drops_it(monkeypatch):
    br, fired, clk = _rig(monkeypatch)
    _send(br, 8, RIGHT_FLIPPER)
    _sw(br, 8, 24, True)
    br.rules.tick()
    clk.t += 0.05
    br.rules.tick()
    assert _made(br, 8, 31)
    _send(br, 8, CLEAR_RIGHT_FLIPPER)                      # game over
    assert not _made(br, 8, 31)                            # the bat falls
    _sw(br, 8, 24, False)
    br.rules.tick()
    _sw(br, 8, 24, True)
    br.rules.tick()
    assert fired == [(8, 0, 0xF5)]


def test_armed_with_the_button_down_waits_for_a_new_press(monkeypatch):
    br, fired, clk = _rig(monkeypatch)
    _sw(br, 8, 25, True)
    _send(br, 8, LEFT_FLIPPER)
    br.rules.tick()
    assert fired == []
    _sw(br, 8, 25, False)
    br.rules.tick()
    _sw(br, 8, 25, True)
    br.rules.tick()
    assert fired == [(8, 5, 0xF5)]


def test_a_frame_that_does_not_checksum_arms_nothing(monkeypatch):
    br, fired, clk = _rig(monkeypatch)
    bad = bytearray(RIGHT_FLIPPER)
    bad[-1] ^= 1
    _send(br, 8, bytes(bad))
    _sw(br, 8, 24, True)
    br.rules.tick()
    assert fired == [] and br.rules.rules == {}


def test_ruled_motor_reaches_its_stop(monkeypatch):
    """MEOWTH BALLOON MOTOR: armed to stop at MEOWTH UP, run by the short 40;
    unanswered the game re-tried it every 10 s for ever."""
    br, fired, clk = _rig(monkeypatch)
    _send(br, 9, BALLOON)
    _send(br, 9, BALLOON_RUN)
    assert fired == [(9, 7, 0x5A)]
    br.rules.tick()
    assert not _made(br, 9, 24)
    clk.t += 0.7
    br.rules.tick()
    assert _made(br, 9, 24)


def _held_lock(node=9):
    """PAD-1239: Spike 2 rush_le 1.19's TROUGH LOCK rule as sent (pulse ff 3
    ticks, HOLD 0x50 300 ticks, [28] = 0x80|0x40|16 SIDE SCOOP OPTO), checksum
    redone for this bus's address."""
    body = bytes.fromhex("4100ff0300502c01" + "00" * 20 + "d0" + "00" * 19)
    return body + bytes([-(0xC0 | node) - len(body) - 1 - sum(body) & 0xFF])


def test_a_held_coil_its_switch_lets_go_is_not_a_motor(monkeypatch):
    """PAD-1239: a stop input with a hold (or 0x80 on it) is a coil held until
    the ball crosses that switch. Played as a motor the switch closed with no
    ball: rush_le said SIDE SCOOP DEVICE MALFUNCTION and never kicked."""
    br, fired, clk = _rig(monkeypatch)
    lock = _held_lock()
    assert s3rules.frame_ok(0xC9, lock)
    _send(br, 9, lock)
    _send(br, 9, _hex("40 00 f4"))   # the short 40, coil 0
    assert fired == [(9, 0, 0xFF)]
    clk.t += 5
    br.rules.tick()
    assert not _made(br, 9, 16) and br.rules.motors == {}
    for hold, stop in ((0x50, 0x50), (0, 0xD0)):     # either sign alone
        r = dict(s3rules.parse(lock), hold_pwr=hold, stop_hi=stop & 0x80 != 0)
        assert not s3rules.is_motor(r)
    assert s3rules.is_motor(s3rules.parse(BALLOON))


def test_rules_off(monkeypatch):
    monkeypatch.setenv("PAD_S3_RULES", "0")
    br, fired, clk = _rig(monkeypatch)
    _send(br, 8, RIGHT_FLIPPER)
    _sw(br, 8, 24, True)
    br.rules.tick()
    assert fired == []


def test_board_fire_is_published_for_the_playfield(tmp_path):
    led = s3leds.PadLed(str(tmp_path / "padled"))
    led.fire(8, 0, 0xF5)
    led.fire(8, 0, 0xF5)
    o = 8 * s3leds.COILS + 0
    assert led.m[s3leds.COIL + o] == 2 and led.m[s3leds.LVL + o] == 0xF5
    led.frame(8, bytes.fromhex("400100"))                  # a short 40 is the rule's, not counted here
    assert led.m[s3leds.COIL + 8 * s3leds.COILS + 1] == 0
    led.close()
