"""PAD-1090: the Spike 3 emulator's node bus - the frame mask, the switch
scan, the fault probe and the ball model - against frames captured off the
live bus (pokemon_le 0.82.0)."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "spike3_emu"))

import s3balls  # noqa: E402
import s3bridge  # noqa: E402


def _frame(hexs):
    b = bytes.fromhex(hexs)
    return b[0], b[2:2 + b[1]]


# (raw 0x41 payload head: node, n, n bytes) -> the Spike 2 frame it carries
CAPTURED = [
    ("c80bcb7474748b748b748b7465", "40 00 ff 00 00 00 00 00 00 00 ee"),   # coil 0 config
    ("c80bcb7574748b748b748b7466", "40 01 ff 00 00 00 00 00 00 00 ed"),   # TROUGH config
    ("c804c2857b8a", "46 fe ff f1"),
    ("c1030257630c"[:10], None),                                          # a switch scan
    ("c80b2fbb81b5888f8a88fa0b8f", None),
]


def test_unmask_gives_spike2_frames_that_checksum():
    for raw, want in CAPTURED:
        node, data = _frame(raw)
        plain = s3bridge.unmask(node, data)
        assert (node + len(data) + sum(plain)) & 0xFF == 0, raw
        if want:
            assert plain.hex(" ") == want
    # the scan request decodes to Spike 2's `11 key ck`
    node, data = _frame("c1030257630c"[:10])
    assert s3bridge.unmask(node, data)[0] == 0x11


def test_unmask_is_its_own_inverse():
    data = bytes(range(17))
    assert s3bridge.unmask(0xC9, s3bridge.unmask(0xC9, data)) == data


def _node(bits):
    n = s3bridge.Node(1, dict(fw=(1, 33, 0), part=0, hwid=100, variant=1, type="pinnode",
                              hex="x", partno=0, partstr="x"), log=open(os.devnull, "w"))
    n.inputs = lambda: bits
    return n


def test_scan_reply_keyed_with_the_decoded_key():
    bits = bytes([0, 0x08, 0, 0, 0, 0, 0, 0])            # START BUTTON, bit 11
    n = _node(bits)
    key = 0x57
    r = n(bytes([0x11, key, (-(0x41 + 3 + 0x11 + key)) & 0xFF]), 11)
    got = bytes(r[i] ^ (((key << i) | (key >> ((8 - i) & 7))) & 0xFF) for i in range(8))
    assert got == bits
    assert sum(r) & 0xFF == 0


def test_fault_probe_does_not_clear_a_request():
    """The once-a-second ff probe is not a switch read: a change (a trough
    closed before boot, a Start press) must stay raised until a scan."""
    for bits in (bytes([0, 0, 0, 0, 0x3F, 0, 0, 0]), bytes([0, 0x08, 0, 0, 0, 0, 0, 0])):
        n = _node(bits)
        n(bytes([0xFF, 0x77]), 9)
        assert n.reported != bits
        n(bytes([0x11, 0x00, 0x00]), 11)
        assert n.reported == bits


def _balls():
    sw = bytearray(512)
    w = s3balls.resolve([
        ("TROUGH 6", 8, 32, "switch"), ("TROUGH 5", 8, 33, "switch"), ("TROUGH 4", 8, 34, "switch"),
        ("TROUGH 3", 8, 35, "switch"), ("TROUGH 2", 8, 36, "switch"), ("TROUGH 1", 8, 37, "switch"),
        ("TROUGH JAM", 8, 38, "switch"), ("SHOOTER LANE", 8, 28, "switch"),
        ("LEFT EJECT OPTO", 8, 5, "switch"), ("TROUGH", 8, 1, "coil"), ("AUTO PLUNGER", 8, 4, "coil")])
    return sw, w, s3balls.Balls(sw, w)


def test_resolve_by_name():
    _sw, w, _b = _balls()
    assert w["trough"][0] == (8, 37) and w["trough"][-1] == (8, 32)
    assert w["shooter"] == (8, 28) and w["eject"] == (8, 1) and w["launch"] == (8, 4)
    assert w["optos"] == [(8, 5)]


def _run(b, secs):
    end = time.time() + secs
    while time.time() < end:
        b.tick()
        time.sleep(0.01)


def test_eject_launch_drain():
    sw, w, b = _balls()
    assert b.home() == 6 and not b.made((8, 5))              # optos rest open
    b.coil(8, bytes([0x40, 1, 0xFF] + [0] * 8))              # boot configuration
    _run(b, 0.6)
    assert b.home() == 6
    b.coil(8, bytes([0x40, 1, 0xE1, 6] + [0] * 7))           # a fire
    _run(b, 0.6)
    assert b.home() == 5 and not b.made((8, 32)) and b.made((8, 28))
    b.coil(8, bytes([0x40, 4, 0xFF] + [0] * 8))
    b.coil(8, bytes([0x40, 4, 0x96, 6] + [0] * 7))
    _run(b, 0.2)
    assert not b.made((8, 28)) and b.in_play == 1
    assert b.drain() and b.home() == 6


def test_eject_retry_inside_the_gap_moves_one_ball():
    sw, w, b = _balls()
    b.coil(8, bytes([0x40, 1, 0xFF] + [0] * 8))
    b.coil(8, bytes([0x40, 1, 0xE1, 6] + [0] * 7))
    b.coil(8, bytes([0x40, 1, 0xE1, 6] + [0] * 7))
    _run(b, 0.7)
    assert b.home() == 5


def test_status_probe_reports_frames_received():
    """Word A of the ff reply = addressed frames since the last probe, this
    one included (Spike 2 PAD-249); a mismatch made the game re-init the
    board for ever."""
    import struct as _s
    br = s3bridge.Bridge(0, open(os.devnull, "w"))
    br.nodes[8] = _node(bytes(8))

    def send(payload, reply_len):
        p = bytes([0x88, len(payload)]) + payload + bytes([reply_len])
        return br.handle(0x41, 0, p)
    send(bytes([0x46, 0xFF, 0x01, 0x00]), 0)
    send(bytes([0x48, 0x00, 0x00, 0x00]), 0)
    r = send(bytes([0xFF, 0x77]), 10)
    body = s3bridge.frames_in(r)[0][0][2]
    assert _s.unpack("<I", body[0:4])[0] == 3 and body[4:8] == bytes(4)
    r = send(bytes([0xFF, 0x77]), 10)
    assert _s.unpack("<I", s3bridge.frames_in(r)[0][0][2][0:4])[0] == 1


def test_playfield_switches_are_active_low():
    """The game's Ball Trough Test shows a trough ball for wire bit 0: the
    PLAYFIELD switches (by location word) answer closed as 0, while cabinet
    buttons - even the flipper buttons on playfield node 8 - stay high."""
    import s3nodes
    PF, CAB = 0x0A6A, 0x0A67
    devs5 = [("START BUTTON", 1, 11, "switch", CAB), ("TROUGH 1", 8, 37, "switch", PF),
             ("SHOOTER LANE", 8, 28, "switch", PF), ("LEFT FLIPPER BUTTON", 8, 25, "switch", CAB)]
    masks = s3nodes.active_low_masks(devs5)
    br = s3bridge.Bridge(0, open(os.devnull, "w"))
    br.nodes[1] = _node(bytes([0, 0x08, 0, 0, 0, 0, 0, 0]))
    br.nodes[8] = _node(bytes([0, 0, 0, 0, 0x20, 0, 0, 0]))   # TROUGH 1 closed
    br.set_polarity(masks)
    assert br.nodes[1].low_mask == bytes(8)
    m8 = br.nodes[8].low_mask
    assert m8[37 // 8] & (1 << 5) and m8[28 // 8] & (1 << 4)
    assert not m8[25 // 8] & (1 << 1)                         # flipper button high
    assert m8[0] == 0xFF                                       # unnamed: majority (playfield)
    r = br.nodes[1](bytes([0x11, 0x00, 0x00]), 11)
    assert r[:8] == bytes([0, 0x08, 0, 0, 0, 0, 0, 0])
    r = br.nodes[8](bytes([0x11, 0x00, 0x00]), 11)
    assert r[4] & 0x20 == 0 and r[3] & 0x10 and not r[3] & 0x02


def test_short_press_is_queued_until_scanned():
    """A coin pulse released before the game came to read was lost."""
    state = {"b": bytes(8)}
    br = s3bridge.Bridge(0, open(os.devnull, "w"))
    n = _node(bytes(8))
    n.inputs = lambda: state["b"]
    n.registered = time.time() - 60
    br.nodes[1] = n
    state["b"] = bytes([0, 0, 0x01, 0, 0, 0, 0, 0])      # coin closes
    assert br.attention() == 1
    state["b"] = bytes(8)                                # ...and opens again
    assert br.attention() == 1
    scan = lambda: n(bytes([0x11, 0x00, 0x00]), 11)[:8]
    assert scan() == bytes([0, 0, 0x01, 0, 0, 0, 0, 0])
    assert br.attention() == 1
    assert scan() == bytes(8)
    assert br.attention() == 0


def test_stepper_homes_and_reports(monkeypatch):
    """fallout_le 0.81's Fat Man (node 10): configure, home, poll 38+motor.
    Answered with zeros the game homed and polled for ever, never booting."""
    monkeypatch.setenv("PAD_STEPPER_SPS", "100000")
    import s3motors
    br = s3bridge.Bridge(0, open(os.devnull, "w"))
    sw = bytearray(512)
    br.steppers = s3motors.Steppers(sw)
    cfg0 = bytes.fromhex("3200 00f401 4041 a080 6400 0000 0005 007d 0000 74".replace(" ", ""))
    cfg1 = bytes.fromhex("3201 00f401 4243 a080 3200 0000 0005 007d 0000 a1".replace(" ", ""))

    def send(payload, reply_len):
        p = bytes([0x8A, len(payload)]) + payload + bytes([reply_len])
        r = br.handle(0x41, 0, p)
        return s3bridge.frames_in(r)[0][0][2] if r else None
    send(cfg0, 0)
    send(cfg1, 0)
    assert send(bytes([0x39, 0xFB]), 7)[4] == 0                 # not homed yet
    send(bytes([0x34, 0x01, 0x00, 0xFD]), 0)                     # home motor 1, dir 0
    deadline = time.time() + 2
    while time.time() < deadline:
        st = send(bytes([0x39, 0xFB]), 7)
        if st[4] & 0x04:
            break
        time.sleep(0.01)
    assert st[4] == 0x04 and st[0:2] == bytes(2)
    # dir 0 = data[6]'s input (0x43 -> input 3, FAT MAN TILT-HOME) is home
    assert sw[8 * 10] & (1 << 3)


def test_end_stop_motor_runs_to_its_input(monkeypatch):
    """star_wars_2025_le 0.96's AT-AT (node 9 motor 2): 51 configures stops
    24/25, 55 sends it to input 24, 52 is polled for the arrival (0x20)."""
    monkeypatch.setenv("PAD_MOTOR_MS", "50")
    import s3motors
    br = s3bridge.Bridge(0, open(os.devnull, "w"))
    sw = bytearray(512)
    br.motors = s3motors.Motors(sw)
    cfg = bytes.fromhex("510258592200000000cb4c4d0028800000004a01c800dd".replace(" ", ""))[:21]
    go = bytes.fromhex("55025800faf401048c")

    def send(payload, reply_len):
        p = bytes([0xC9, len(payload)]) + s3bridge.unmask(0xC9, payload) + bytes([reply_len])
        r = br.handle(0x41, 0, p)
        return s3bridge.frames_in(r)[0][0][2] if r else None
    send(cfg, 0)
    send(go, 0)
    assert send(bytes([0x52, 0x02, 0xE0]), 6)[2] == 0x01        # moving
    time.sleep(0.1)
    assert send(bytes([0x52, 0x02, 0xE0]), 6)[2] == 0x20        # arrived
    assert sw[8 * 9 + 3] & 0x01                                  # input 24 made
