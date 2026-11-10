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


def test_fault_probe_marks_only_the_bits_it_carries():
    """A trough closed before boot (node 8 bits 32..37) must still raise a
    request after the 32-bit ff probe - it was hidden for good."""
    bits = bytes([0, 0, 0, 0, 0x3F, 0, 0, 0])
    n = _node(bits)
    n(bytes([0xFF, 0x77]), 9)
    assert n.reported != bits


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
    assert b.home() == 6 and b.made((8, 5))                  # optos rest closed
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
