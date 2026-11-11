"""Spike 1 node-bus responder: the reply framing that registers a node.

The reply format was reverse-engineered from the game ELF
(NODEBUS_TransferMessage @0xbfc28) and confirmed live: with these replies the
game stops logging "short response (got 0, expected 12)", registers nodes
1/8/9/10/11/12, and issues runtime polls (cmd 0xf9) to them.

The game validates every reply with three gates — these tests pin each one so a
regression can't silently break registration:
  1. exact byte count (== resp_len);
  2. sum(payload + checksum) == 0 (mod 256), STATUS byte EXCLUDED (checksum is
     the SECOND-TO-LAST byte);
  3. status byte (LAST) has bit2 (0x04) and bit3 (0x08) clear.
Plus: the reply must be DETERMINISTIC per (node, cmd) — the game re-polls and
memcmp's up to 5x.
"""

import importlib.util
import os

_NB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike1_emu", "nodebus.py")
_spec = importlib.util.spec_from_file_location("nodebus", _NB)
nodebus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nodebus)


def gates_pass(reply, resp_len):
    """Reproduce the game's three accept gates (NODEBUS_TransferMessage)."""
    if len(reply) != resp_len:
        return False, "count"
    if (sum(reply[:resp_len - 1]) & 0xFF) != 0:      # payload + checksum
        return False, "checksum"
    if reply[resp_len - 1] & 0x0C:                    # status NAK bits
        return False, "status"
    return True, "ok"


def poll_body(cmd):
    return bytes([cmd, 0x00])       # body = [cmd, checksum] (checksum unused here)


def test_encoder_motor_homes_moves_signed_counts_and_preserves_other_inputs():
    import struct
    now = [0.0]
    motors = nodebus.EncoderMotors(clock=lambda: now[0])
    # Ghostbusters Slimer: node 8, motor 0, home input 5, encoders 3/4.
    motors.note(8, bytes([0x51, 0, 0x45, 0, 0, 0x43, 0x44, 0]))
    assert motors.status(8, 0) == struct.pack("<hH", 0, 0)
    motors.note(8, bytes([0x53, 0, 40, 32, 232, 3, 0]))
    assert motors.status(8, 0) == struct.pack("<hH", 0, 1)
    now[0] = .7
    assert motors.status(8, 0) == struct.pack("<hH", 0, 8)
    switches = bytearray(nodebus.SW_IDLE)
    switches[2] = 0xfe
    assert motors.switches(8, switches) == b"\xdf\xff\xfe" + b"\xff" * 5
    motors.note(8, bytes([0x55, 0]) + struct.pack("<h", -120) + b"\0")
    now[0] = 1.0
    pos, flags = struct.unpack("<hH", motors.status(8, 0))
    assert -61 <= pos <= -59 and flags == 1
    assert motors.switches(8, switches)[0] == 0xff
    assert motors.switches(8, switches)[2] == 0xfe
    now[0] = 1.4
    assert motors.status(8, 0) == struct.pack("<hH", -120, 8)
    reply = nodebus.build_response(0x88, b"\x52\x00\x00", 6, motor_status=motors.status(8, 0))
    assert gates_pass(reply, 6) == (True, "ok")
    assert reply[:4] == struct.pack("<hH", -120, 8)
    assert motors.switches(9, switches) == bytes(switches)


def test_repeated_encoder_commands_do_not_restart_a_move():
    import struct
    now = [0.0]
    motors = nodebus.EncoderMotors(clock=lambda: now[0])
    motors.note(8, b"\x51\x00\x45\x00\x00\x43\x44\x00")
    move = b"\x55\x00" + struct.pack("<h", 60) + b"\0"
    motors.note(8, move)
    now[0] = .4
    motors.note(8, move)
    now[0] = .7
    assert motors.status(8, 0) == struct.pack("<hH", 60, 0)
    motors.note(8, move)
    assert motors.status(8, 0) == struct.pack("<hH", 60, 0)
    # A home command at the same target as a position move still homes it.
    motors.note(8, b"\x55\x00\x00\x00\x00")
    motors.note(8, b"\x53\x00\x00")
    now[0] = 1.4
    assert motors.status(8, 0) == struct.pack("<hH", 0, 8)


def test_encoder_protocol_leaves_unconfigured_and_end_stop_motors_alone():
    motors = nodebus.EncoderMotors()
    motors.note(8, b"\x51\x00\x45\x46\x00\x00\x00\x00")  # no encoders
    for body in (b"", b"\x51", b"\x51\x00\0", b"\x55\x00\x05\0"):
        motors.note(8, body)
    assert motors.status(8, 0) is None
    assert motors.switches(8, nodebus.SW_IDLE) == nodebus.SW_IDLE
    assert nodebus.build_response(0x88, b"\x52\x00\x00", 6) == bytes(6)


def test_presence_reply_passes_all_gates():
    for node in (1, 8, 9, 10, 11, 12):
        addr = 0x80 | node
        reply = nodebus.build_response(addr, poll_body(0xFE), 12)
        assert len(reply) == 12
        ok, why = gates_pass(reply, 12)
        assert ok, "node %d failed gate: %s" % (node, why)


def test_checksum_is_second_to_last_not_last():
    # the classic trap: checksum must NOT be the last byte
    reply = nodebus.build_response(0x81, poll_body(0xFE), 12)
    assert reply[11] == 0x00                 # last byte = status, clean
    # byte 10 is the checksum that zeroes the payload+checksum sum
    assert (sum(reply[:11]) & 0xFF) == 0
    # and it is genuinely load-bearing: dropping it breaks the sum
    assert (sum(reply[:10]) & 0xFF) != 0 or all(b == 0 for b in reply[:10])


def test_presence_payload_shape():
    reply = nodebus.build_response(0x81, poll_body(0xFE), 12)
    assert reply[0] & 0x80 == 0             # bit7 clear -> application mode
    assert reply[1] == 0x01                 # fw major non-zero (no fw known)
    board_id = reply[8] | (reply[9] << 8)   # LE16 board id must be non-zero
    assert board_id != 0


def test_lcd_insert_info_carries_the_file_checksum():
    """cmd 0xf2 sub 0x30 (LCDInsertInfo): payload[7..10] must equal the LE32
    at offset 8 of lcdinsert.bin, or every boot runs the LCD-flash rewrite
    and shows "UPDATE FAILED / PLEASE POWER-CYCLE GAME"."""
    body = [0xF2, 0x30]
    body.append(nodebus.checksum([0x98, len(body) + 1] + body))
    reply = nodebus.build_response(0x98, bytes(body), 14,
                                   lcd_sum=0xDEADBEEF)
    assert reply[7:11] == bytes.fromhex("efbeadde")       # LE32 at payload+7
    ok, why = gates_pass(reply, 14)
    assert ok, why
    # without the file, the reply stays all-zero (pre-fix behaviour)
    reply = nodebus.build_response(0x98, bytes(body), 14)
    assert reply[7:11] == bytes(4)


def test_presence_reports_the_cards_hex_image_version():
    """The fw bytes must match the card's runtime hex images, or every boot
    detours through "UPDATING NODE BOARD RUNTIME / UPDATE FAILED" (David:
    "ideally, we would never see this screen on start up")."""
    reply = nodebus.build_response(0x81, poll_body(0xFE), 12, fw=(0, 52, 0))
    assert (reply[1], reply[2], reply[3]) == (0, 52, 0)
    ok, why = gates_pass(reply, 12)
    assert ok, why


def test_reply_is_deterministic():
    a = nodebus.build_response(0x88, poll_body(0xFE), 12)
    b = nodebus.build_response(0x88, poll_body(0xFE), 12)
    assert a == b


def test_status_poll_is_zero_payload_present():
    reply = nodebus.build_response(0x81, poll_body(0xFF), 10)   # cmd 0xff, 8 payload
    ok, why = gates_pass(reply, 10)
    assert ok, why
    assert reply[:8] == bytes(8)            # zero payload = present, no faults


def test_status_poll_reports_the_frames_the_board_received():
    # Word A is the board's received-frame count: the game compares its change
    # with the frames it sent, and a zero answer re-initialised every board on
    # every poll, which restarted Ghostbusters' Slimer homing (PAD-1160).
    import struct
    for count in (1, 300, 0x1_0000_0005):
        reply = nodebus.build_response(0x88, poll_body(0xFF), 10, rx_count=count)
        assert gates_pass(reply, 10) == (True, "ok")
        assert reply[:4] == struct.pack("<I", count & 0xFFFFFFFF)
        assert reply[4:8] == bytes(4)       # word B: no faults
    # only the status poll carries it
    assert nodebus.build_response(0x88, poll_body(0x52), 6, rx_count=7) == bytes(6)


def test_input_poll_active_low_closed_switch():
    # active-low: node-local position 0 closed -> byte0 bit0 cleared (0xfe)
    sw = bytearray(b"\xff" * 8)
    sw[0] &= ~0x01
    reply = nodebus.build_response(0x81, poll_body(0x11), 12, switch_bits=bytes(sw))
    ok, why = gates_pass(reply, 12)
    assert ok, why
    assert reply[0] == 0xFE
    assert reply[1:8] == b"\xff" * 7        # other switches idle
    assert reply[8] == 0 and reply[9] == 0  # aux bytes ignored -> 0


def test_input_poll_idle_is_all_ff():
    reply = nodebus.build_response(0x81, poll_body(0x11), 12, switch_bits=None)
    assert reply[:8] == b"\xff" * 8         # idle = nothing pressed (active-low)
    ok, why = gates_pass(reply, 12)
    assert ok, why


def test_read_injected_switches_active_low(tmp_path):
    from pinball_decryptor.plugins.stern.spike1_emulate import SwitchInput, addr
    p = tmp_path / "s1sw.input"
    p.write_bytes(SwitchInput.pack({addr(8, 3), addr(8, 10)}, seq=1))
    inj = nodebus.read_injected_switches(str(p))
    assert set(inj) == {8}
    sw = inj[8]
    assert sw[0] == (0xFF & ~(1 << 3))      # position 3 -> byte0 bit3 cleared
    assert sw[1] == (0xFF & ~(1 << 2))      # position 10 -> byte1 bit2 cleared
    assert sw[2:] == b"\xff" * 6


def test_read_injected_switches_absent():
    assert nodebus.read_injected_switches("/no/such/file") == {}
    assert nodebus.read_injected_switches(None) == {}


def test_checksum_helper_sums_to_zero():
    for payload in (b"", b"\x01", b"\x01\x02\x03", bytes(range(10))):
        c = nodebus.checksum(payload)
        assert (sum(payload) + c) & 0xFF == 0


def _boardid_body(page):
    return bytes([0xF9, page])          # cmd 0xf9, page selector


def test_full_board_id_carries_part_number_le32():
    # page 0 bytes[0..3] = LE32 part number the game feeds to
    # sys_node_board_type_get_from_part_number (resp_len 18 on the wire)
    board = {"type": 2, "part": 520693600}
    reply = nodebus.build_response(0x80, _boardid_body(0), 18, board=board)
    ok, why = gates_pass(reply, 18)
    assert ok, why
    import struct
    assert struct.unpack("<I", reply[0:4])[0] == 520693600


def test_full_board_id_unknown_node_is_zero_part():
    # no topology entry -> zero part = the game's "unknown board" path
    reply = nodebus.build_response(0x83, _boardid_body(0), 18, board=None)
    ok, why = gates_pass(reply, 18)
    assert ok, why
    assert reply[0:4] == bytes(4)


def test_full_board_id_page1_is_zero_payload():
    # only page 0 carries the part number; page 1 is unused for classification
    board = {"type": 8, "part": 520693500}
    reply = nodebus.build_response(0x88, _boardid_body(1), 18, board=board)
    ok, why = gates_pass(reply, 18)
    assert ok, why
    assert reply[0:4] == bytes(4)


def test_full_board_id_deterministic():
    board = {"type": 9, "part": 520532900}
    a = nodebus.build_response(0x89, _boardid_body(0), 18, board=board)
    b = nodebus.build_response(0x89, _boardid_body(0), 18, board=board)
    assert a == b


# ---- unaddressed bridge commands (the boot's power gate) ------------------
# NODEBUS_GetPower (@0xc4608, platform mode 2) calls NODEBUS_BridgeState (cmd
# 0x0a) and returns reply[0] bit0 as "power".  sys_node_bus_control_thread_startup
# only calls node_bus_are_all_nodes_OK when GetPower()>0, so this bit gates the
# whole boot.  These replies are RAW bytes (no checksum/status framing — the
# addressed gates above do NOT apply); the count is implicit per command.

def test_bridge_reply_command_set_and_lengths():
    # exactly the three reply-expecting bridge commands, with the implicit reply
    # lengths NODEBUS_BridgeVersion/Status/State read (3 / 1 / 2 bytes).
    assert set(nodebus.BRIDGE_REPLY) == {0x03, 0x05, 0x0A}
    assert len(nodebus.BRIDGE_REPLY[0x03]) == 3      # BridgeVersion maj/min/sub
    assert len(nodebus.BRIDGE_REPLY[0x05]) == 1      # BridgeStatus status byte
    assert len(nodebus.BRIDGE_REPLY[0x0A]) == 2      # BridgeState flags + byte


def test_bridge_state_reports_power_good():
    # the load-bearing bit: GetPower() returns reply[0] & 1; it MUST be set or
    # the boot never runs are_all_nodes_OK and sits on "LOCATING NODE BOARDS".
    assert nodebus.BRIDGE_REPLY[0x0A][0] & 0x01 == 0x01


def test_bridge_status_reports_no_faults():
    assert nodebus.BRIDGE_REPLY[0x05] == bytes([0x00])


def test_bridge_version_is_present_and_nonzero():
    # a valid (non-absent) bridge: node_bus_update_status marks it present.
    assert any(nodebus.BRIDGE_REPLY[0x03])


# ---- WireParser: the game->CPU stream parser -------------------------------

def _frame(addr, body_no_ck, resp_len):
    """Build a wire frame: {addr, len, body..., checksum, resp_len} where the
    checksum makes addr+len+body+checksum == 0 mod 256."""
    ln = len(body_no_ck) + 1
    ck = (-(addr + ln + sum(body_no_ck))) & 0xFF
    return bytes([addr, ln]) + bytes(body_no_ck) + bytes([ck, resp_len])


def test_wireparser_basic_events():
    p = nodebus.WireParser()
    data = b"\x00" + _frame(0x81, [0x11], 12) + bytes([0x03, 0x01, 0xAA])
    evs = list(p.feed(data))
    assert evs[0] == ("poll",)
    assert evs[1][0] == "frame" and evs[1][1] == 0x81 and evs[1][3] == 12
    assert evs[1][2][0] == 0x11
    assert evs[2] == ("bridge", 0x03, b"\xaa")


def test_wireparser_long_nonce_frame_keeps_sync():
    """Regression: the in-game cmd-0x75 frame carries a 16-byte nonce
    (ln=0x12=18).  The old ln>16 cap rejected it, resynced one byte into the
    frame, misread 0x12 as a bridge command, and its length byte swallowed
    hundreds of real bytes (poll tokens included) - wedging the bus."""
    p = nodebus.WireParser()
    nonce = list(range(0x40, 0x50))              # 16 bytes
    long_frame = _frame(0x89, [0x75] + nonce, 0)
    assert long_frame[1] == 0x12                 # ln really is 18
    follow = _frame(0x81, [0x11], 12)
    evs = list(p.feed(long_frame + b"\x00" + follow))
    kinds = [e[0] for e in evs]
    assert kinds == ["frame", "poll", "frame"]
    assert evs[0][2][0] == 0x75 and len(evs[0][2]) == 18
    assert evs[2][1] == 0x81 and evs[2][2][0] == 0x11


def test_wireparser_resyncs_after_garbage():
    # A stray 0x81 byte reads as a frame start claiming ln=0x88 (the real
    # frame's addr byte): the parser waits for the bytes — the bus keeps
    # flowing (polls here) — fails the checksum, drops the stray byte, and
    # re-locks on the real frame.
    p = nodebus.WireParser()
    real = _frame(0x88, [0x11], 12)
    evs = list(p.feed(b"\x81" + real + b"\x00" * 200))
    frames = [e for e in evs if e[0] == "frame"]
    assert frames == [("frame", 0x88, real[2:-1], 12)]
    assert any(e == ("poll",) for e in evs)


def test_wireparser_hundred_byte_frame_keeps_sync():
    """Regression #2: Ghostbusters LE emits config frames well past 64 bytes;
    ANY length cap under 255 rejects a real frame start and desyncs (the
    shifted stream mis-parses a byte as a bridge command that swallows real
    traffic).  ln is one byte — there must be no artificial cap."""
    p = nodebus.WireParser()
    big = _frame(0x88, [0x51] + list(range(120)), 0)
    assert big[1] == 122                    # 121 payload bytes + checksum
    evs = list(p.feed(big + b"\x00" + _frame(0x81, [0x11], 12)))
    assert [e[0] for e in evs] == ["frame", "poll", "frame"]
    assert evs[0][2][0] == 0x51 and len(evs[0][2]) == 122


def test_wireparser_split_feeds():
    p = nodebus.WireParser()
    f = _frame(0x8A, [0x40, 2, 0xFF], 0)
    assert list(p.feed(f[:3])) == []
    evs = list(p.feed(f[3:]))
    assert len(evs) == 1 and evs[0][0] == "frame"
    assert evs[0][2][:3] == bytes([0x40, 2, 0xFF])


# ---- the DMD era's s1hw.state (PAD-943) ------------------------------------
# The frames are GOT LE 1.37's own, as a run's ttyS4.cap carries them (the
# command byte first, the checksum last); the shapes are the ELF's senders
# (NODEBUS_SetLED @0xc1530, NODEBUS_SetLEDMultiple @0xc1428).

class _Hw:
    def __init__(self):
        self.lamps, self.coils, self.offs = {}, [], []

    def lamp_level(self, node, ch, level):
        self.lamps[(node, ch)] = level

    def coil_on(self, node, coil, seconds):
        self.coils.append((node, coil, seconds))

    def coil_off(self, node, coil):
        self.offs.append((node, coil))


def test_dmd_single_lamp_write_is_time_then_level():
    hw = _Hw()
    d = nodebus.DmdFrames(hw)
    d.frame(8, bytes.fromhex("a900ffcc"))        # SetLED(8, 41, 0xff, time 0)
    d.frame(10, bytes.fromhex("903e891b"))       # SetLED(10, 16, 0x89, ramp 0x3e)
    assert hw.lamps == {(8, 41): 0xFF, (10, 16): 0x89}


def test_dmd_multiple_lamps_run_from_the_index():
    hw = _Hw()
    nodebus.DmdFrames(hw).frame(9, bytes([0x85, 0x00, 0x10, 0x20, 0x30, 0x00]))
    assert hw.lamps == {(9, 5): 0x10, (9, 6): 0x20, (9, 7): 0x30}


def test_dmd_wide_index_form_and_base_layer_write():
    hw = _Hw()
    d = nodebus.DmdFrames(hw)
    d.frame(8, bytes([0xC0, 0x45, 0x00, 0x00, 0x7F, 0x00]))      # idx 69 (> 63)
    d.frame(10, bytes.fromhex("70050001fb"))                    # cmd 70, v16 0x0100
    assert hw.lamps[(8, 69)] == 0x7F
    assert hw.lamps[(10, 5)] == nodebus.level70(0x00, 0x01) == 0x100 * 255 // 0x800


def test_dmd_coil_drive_pulse_hold_rule_and_off():
    hw = _Hw()
    d = nodebus.DmdFrames(hw)
    d.frame(8, bytes.fromhex("4100ff00001e0000000000000000000000000000004200004000000000000000000500006f"))
    d.frame(8, bytes([0x40, 0x00, 0x00]))                       # short 40: the rule's 0x1e ticks
    d.frame(8, bytes.fromhex("4004ff6400ff3200000000"))         # pulse 100 + hold 50 ticks
    d.frame(1, bytes.fromhex("4002ff0000ff0000000034"))         # hold with no end
    d.frame(1, bytes([0x4D, 0x02, 0x00]))
    assert d.rules[(8, 0)] == 0x1E
    assert hw.coils == [(8, 0, nodebus.DMD_COIL_MIN_S), (8, 4, 0.15), (1, 2, nodebus.DMD_COIL_HOLD_S)]
    assert hw.offs == [(1, 2)]


def test_dmd_frames_ignore_what_they_do_not_know():
    hw = _Hw()
    d = nodebus.DmdFrames(hw)
    d.frame(8, bytes.fromhex("430400050607010403020801"))
    d.frame(8, bytes.fromhex("72ffffffffffffffffffffffff04"))
    d.frame(8, bytes([0x11, 0x6C]))
    d.frame(8, b"")
    assert not hw.lamps and not hw.coils and not hw.offs


# PAD-979: frames Ghostbusters LE 1.17's own NODEBUS_SetLEDMultiple2 built
# (run under Unicorn) for these runs, one per way it packs them. The last
# byte is the checksum slot.
_LED2_FRAMES = [
    ("940b0800", [11], [0], [8]),                               # one index, all off
    ("a603a8ff0000", [3, 40], [255, 0], [0, 0]),                # an index list
    ("99c004ff3fb66ddbb62dffc900", list(range(38)), [255] * 38,  # short mask, two times
     [255 if i % 3 == 0 else 201 for i in range(38)]),
    ("a28f0bde020202401010108001800a141e28323c46505a64"         # long mask + extra byte
     "0102030405060708090a00", [1, 9, 17, 30, 44, 52, 60, 71, 80, 95],
     [10, 20, 30, 40, 50, 60, 70, 80, 90, 100], list(range(1, 11))),
    ("9f8012ffff2184070532373c4100", list(range(8, 24)), [7] * 16,  # times listed
     [5 if i % 5 else 50 + i for i in range(16)]),
]


def test_led2_frames_read_back_to_what_the_game_packed():
    for hexbody, idx, levels, times in _LED2_FRAMES:
        assert nodebus.led2_frame(bytes.fromhex(hexbody)) == list(zip(idx, levels, times)), hexbody


def test_led2_frames_are_read_only_for_a_game_that_sends_them():
    hw = _Hw()
    nodebus.DmdFrames(hw, led2=True).frame(9, bytes.fromhex("8a8067ffff0e8000ffffff0000000000000000000000ff0a5c"))
    # off the rig's wire: 0x8a = a short mask over bytes 6-7 (48-63), levels each
    levels = bytes.fromhex("00ffffff0000000000000000000000ff")
    assert hw.lamps == {(9, 48 + i): v for i, v in enumerate(levels)}
    old = _Hw()
    nodebus.DmdFrames(old).frame(9, bytes([0x85, 0x00, 0x10, 0x20, 0x30, 0x00]))
    assert old.lamps == {(9, 5): 0x10, (9, 6): 0x20, (9, 7): 0x30}


def test_a_garbled_led2_frame_is_dropped():
    hw = _Hw()
    d = nodebus.DmdFrames(hw, led2=True)
    d.frame(8, bytes.fromhex("8ac0"))
    d.frame(8, bytes.fromhex("95ffff0000"))
    d.frame(8, bytes.fromhex("70050001fb"))                    # the base layer still reads
    assert hw.lamps == {(8, 5): nodebus.level70(0x00, 0x01)}


def test_closed_indexes_reads_active_low_bytes():
    assert nodebus.closed_indexes(nodebus.SW_IDLE) == []
    assert nodebus.closed_indexes(bytes([0xFF, 0xF7, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x7F])) == [11, 63]
