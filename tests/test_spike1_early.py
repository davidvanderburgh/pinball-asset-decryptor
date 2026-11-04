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


# ------------------------------------------- drop targets (PAD-235) --------
def test_drop_target_slots_are_the_targets_not_the_reset():
    names = {16: "DROP TARGET 1", 17: "DROP TARGET 2", 18: "DROP TARGET 3",
             19: "MEGATRON", 50: "DROP TARGET RESET"}
    assert s1early.drop_target_slots(names) == {16, 17, 18}


def test_a_hit_drop_target_stays_down_until_the_reset_fires():
    bank = s1early.DropBank({16, 17, 18}, {7})
    bank.feed({16})                  # a click closes it for a moment...
    bank.feed(set())                 # ...and lets go
    assert bank.down == {16}         # the target is still lying down
    bank.feed({13})                  # other switches are not targets
    assert bank.down == {16}
    assert not bank.on_coil(3)       # a trough eject is not the reset
    assert bank.on_coil(7)
    assert bank.down == set()


def test_a_target_held_through_the_reset_does_not_relatch():
    bank = s1early.DropBank({16}, {7})
    bank.feed({16})
    bank.on_coil(7)
    bank.feed({16})                  # still held: the hold reads it, no edge
    assert bank.down == set()
    bank.feed(set())
    bank.feed({16})                  # a fresh hit latches again
    assert bank.down == {16}


def test_switch_masks_round_trip():
    idx = {0, 7, 13, 16, 18, 63}
    assert s1early.mask_indexes(s1early.indexes_mask(idx)) == idx


# ----------------------------------------- the switch window's state -------
def _read_block(path):
    from pinball_decryptor.plugins.stern.spike1_emulate import StateBlock
    with open(path, "rb") as f:
        st, seq, _ = StateBlock.unpack(f.read())
    return st, seq


def test_lamp_frames_land_in_s1hw_state(tmp_path):
    t = [0.0]
    w = s1early.HwStateWriter(str(tmp_path / "s1hw.state"), clock=lambda: t[0])
    w.lamp_frame(8, 0x8f, b"\xff\x58")        # channels 15, 16
    w.lamp_frame(8, 0xbf, b"\xff\xff")        # 63, then 64 is off the node
    assert w.flush()
    st, seq = _read_block(tmp_path / "s1hw.state")
    assert st.get_lamp(8, 15) == (255, 255, 255)
    assert st.get_lamp(8, 16) == (0x58, 0x58, 0x58)
    assert st.get_lamp(8, 63) == (255, 255, 255)
    assert seq == 1


def test_switches_and_fired_coils_land_in_s1hw_state(tmp_path):
    t = [0.0]
    path = str(tmp_path / "s1hw.state")
    w = s1early.HwStateWriter(path, clock=lambda: t[0])
    w.set_switches(8, {13, 14, 16})
    w.coil_fire(8, 7)
    w.flush()
    st, _ = _read_block(path)
    assert [i for i in range(64) if st.get_switch(8, i)] == [13, 14, 16]
    assert st.get_coil(8, 7)
    t[0] += s1early.COIL_SHOW_S + 0.01
    w.flush()
    st, _ = _read_block(path)
    assert not st.get_coil(8, 7)              # a pulse, not a latch


def test_a_node_past_the_block_leaves_the_lamps_where_they_are(tmp_path):
    # PAD-979: Ghostbusters LE has a board at node 24. Its switch reads grew
    # the 1024-byte switch area to 1600 bytes, so its lamps on node 1, 8, 9,
    # 10 and 12 were read back three nodes up.
    from pinball_decryptor.plugins.stern.spike1_emulate import MAX_NODES, StateBlock
    assert s1early.STATE_NODES == MAX_NODES
    path = tmp_path / "s1hw.state"
    w = s1early.HwStateWriter(str(path), clock=lambda: 0.0)
    for _ in range(12):
        w.set_switches(24, {3})
    w.lamp_level(24, 5, 200)
    w.lamp_frame(31, 0x80, b"\xff")
    w.coil_on(24, 2, 1.0)
    w.coil_off(24, 2)
    w.lamp_level(1, 7, 191)
    w.lamp_level(8, 4, 255)
    w.set_switches(12, {5})
    assert w.flush(force=True)
    assert path.stat().st_size == StateBlock.SIZE
    st, _ = _read_block(path)
    assert st.get_lamp(1, 7) == (191, 191, 191)
    assert st.get_lamp(8, 4) == (255, 255, 255)
    assert st.get_lamp(4, 7) == (0, 0, 0)
    assert st.get_lamp(11, 4) == (0, 0, 0)
    assert [i for i in range(64) if st.get_switch(12, i)] == [5]


def test_state_writes_are_throttled_and_only_on_change(tmp_path):
    t = [0.0]
    w = s1early.HwStateWriter(str(tmp_path / "s1hw.state"), clock=lambda: t[0])
    assert w.flush()                          # first frame
    assert not w.flush()                      # nothing changed
    w.lamp_frame(8, 0x8a, b"\xff")
    assert not w.flush()                      # changed, but too soon
    t[0] += w.min_interval
    assert w.flush()
