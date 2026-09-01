"""The early-era Spike 1 node-bus responder (tools/spike1_emu/s1early.py).

The 2012 home models (Transformers The Pin, PAD-101) speak a wire format with
no checksums and implied reply lengths; these tests pin the framing and every
reply the game binary was read to expect (node_pdi.cpp's functions, by name in
the module docstring), plus the two things that are the OPPOSITE of the 2015
firmware: active-high switches, and the settings EEPROM on the net bridge.
"""

import os
import sys

_RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "spike1_emu")
if _RIG not in sys.path:
    sys.path.insert(0, _RIG)

import s1early  # noqa: E402
from nodebus import SW_IDLE  # noqa: E402


def _events(*chunks):
    p = s1early.EarlyParser()
    out = []
    for c in chunks:
        out.extend(p.feed(c))
    return out


# ----------------------------------------------------------------- framing --

def test_poll_is_a_bare_zero():
    assert _events(b"\x00") == [("poll",)]


def test_switch_read_frame():
    # node_query_t: [0x80|node, 1, 0x11]
    assert _events(b"\x88\x01\x11") == [("frame", 8, 0x11, b"")]


def test_coil_frame_carries_its_four_bytes():
    # node_coilmsg: [0x80|node, 5, 0x40|coil, p1..p4]
    assert _events(b"\x88\x05\x43\x10\x20\x30\x40") == [
        ("frame", 8, 0x43, b"\x10\x20\x30\x40")]


def test_frames_reassemble_across_reads():
    assert _events(b"\x88", b"\x05\x43\x10", b"\x20\x30\x40\x00") == [
        ("frame", 8, 0x43, b"\x10\x20\x30\x40"), ("poll",)]


def test_bridge_frames_are_seven_bytes():
    # LL_sys_eep_read sends 7 (the last one is uninitialised); a write is 7 too
    ev = _events(b"\x55\x00\x02\x00\x05\xf9\xaa")
    assert ev == [("bridge", 0x00, b"\x00\x05\xf9\xaa")]


def test_a_stray_byte_is_dropped_not_fatal():
    assert _events(b"\x7f\x00") == [("junk", 0x7F), ("poll",)]


# ----------------------------------------------------------------- replies --

class _Eep:
    def __init__(self):
        self.mem = bytearray(64)
        self.path = "<mem>"

    def read(self, addr):
        return self.mem[addr] if addr < 64 else 0xFF

    def write(self, addr, val):
        if addr >= 64:
            return False
        self.mem[addr] = val
        return True


def test_switch_read_returns_eight_active_high_bytes():
    sw = {8: bytes([0x01, 0, 0, 0, 0, 0, 0, 0x80])}
    assert s1early.reply_for(("frame", 8, 0x11, b""), sw, _Eep()) == sw[8]


def test_switch_read_on_an_unknown_node_is_idle_zero():
    assert s1early.reply_for(("frame", 3, 0x11, b""), {}, _Eep()) == b"\x00" * 8


def test_status_is_six_zero_bytes():
    # node_status_t: [0..1] is the error mask -> zero means no NODE ERROR lines
    assert s1early.reply_for(("frame", 8, 0xFF, b""), {}, _Eep()) == b"\x00" * 6


def test_quadrature_is_one_zero_byte():
    assert s1early.reply_for(("frame", 8, 0x60, b"\x01\x02"), {}, _Eep()) == b"\x00"


def test_coils_and_lamps_get_no_reply():
    assert s1early.reply_for(("frame", 8, 0x43, b"\x10\x20\x30\x40"), {}, _Eep()) is None
    assert s1early.reply_for(("frame", 8, 0x85, b"\x01\x02"), {}, _Eep()) is None


def test_eeprom_read_reply_is_aa_01_data_and_its_complement():
    e = _Eep()
    e.mem[5] = 0x3C
    r = s1early.reply_for(("bridge", 0x00, b"\x00\x05\xf9\xaa"), {}, e)
    assert r == bytes([0xAA, 0x01, 0x3C, 0xFF - 0x3C])
    # LL_sys_eep_read's own acceptance test: (data + ck + 1) & 0xff == 0
    assert (r[2] + r[3] + 1) & 0xFF == 0


def test_eeprom_write_stores_and_acks():
    e = _Eep()
    r = s1early.reply_for(("bridge", 0x01, b"\x00\x07\x5a\x00"), {}, e)
    assert r == bytes([0xAA, 0x00, 0x00])
    assert e.mem[7] == 0x5A


def test_eeprom_is_persisted(tmp_path):
    p = str(tmp_path / "s1eep.bin")
    e = s1early.Eeprom(p)
    e.write(3, 0x77)
    assert s1early.Eeprom(p).read(3) == 0x77
    assert s1early.Eeprom(p).read(64) == 0xFF        # off the part


# ---------------------------------------------------------------- polarity --

def test_active_high_flips_nodebus_active_low_bytes():
    assert s1early.active_high(SW_IDLE) == b"\x00" * 8
    low = bytes([0xFE]) + b"\xff" * 7                 # index 0 closed, 2015-style
    assert s1early.active_high(low) == bytes([0x01]) + b"\x00" * 7


def test_nodebus_hands_the_early_era_to_s1early(monkeypatch):
    import nodebus
    called = {}
    monkeypatch.setenv("S1_ERA", "early")

    def fake_main(argv):
        called["argv"] = argv
        return 0

    monkeypatch.setattr(s1early, "main", fake_main)
    monkeypatch.setattr(nodebus.sys, "argv", ["nodebus.py", "slave", "cap", "log"])
    assert nodebus.main() == 0
    assert called["argv"] == ["slave", "cap", "log"]
