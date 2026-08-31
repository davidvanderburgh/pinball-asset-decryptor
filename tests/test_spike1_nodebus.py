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
