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
    assert b.drain()                                         # rolls home (PAD-1181)
    _run(b, 0.3)
    assert b.home() == 6


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
    """The game's Ball Trough Test shows a trough ball for wire bit 0: a
    board carrying PLAYFIELD switches (by location word) answers closed as 0
    on EVERY input - the flipper buttons on node 8 included (PAD-1090: taken
    active high, one flipper tap ran the service menu for ever) - and the
    cabinet board's switches too (PAD-1189, test below)."""
    import s3nodes
    PF, CAB = 0x0A6A, 0x0A67
    devs5 = [("START BUTTON", 1, 11, "switch", CAB), ("TROUGH 1", 8, 37, "switch", PF),
             ("SHOOTER LANE", 8, 28, "switch", PF), ("LEFT FLIPPER BUTTON", 8, 25, "switch", CAB)]
    masks = s3nodes.active_low_masks(devs5)
    br = s3bridge.Bridge(0, open(os.devnull, "w"))
    br.nodes[1] = _node(bytes([0, 0x08, 0, 0, 0, 0, 0, 0]))   # START held
    br.nodes[8] = _node(bytes([0, 0, 0, 0, 0x20, 0, 0, 0]))   # TROUGH 1 closed
    br.set_polarity(masks)
    assert br.nodes[1].low_mask == bytes([0, 0x08, 0, 0, 0, 0, 0, 0])
    m8 = br.nodes[8].low_mask
    assert m8[37 // 8] & (1 << 5) and m8[28 // 8] & (1 << 4)
    assert m8[25 // 8] & (1 << 1)                             # flipper button LOW too
    assert m8 == b"\xff" * 8                                   # the whole board
    r = br.nodes[1](bytes([0x11, 0x00, 0x00]), 11)
    assert r[:8] == bytes(8)                                  # START held reads 0
    r = br.nodes[8](bytes([0x11, 0x00, 0x00]), 11)
    # TROUGH 1 closed reads 0; the open flipper button reads 1 (not held)
    assert r[4] & 0x20 == 0 and r[3] & 0x10 and r[3] & 0x02


def test_cabinet_board_rests_released():
    """PAD-1189: node 1's cabinet switches are active low. Taken active high,
    its resting scan (the PAD-1139 baseline) told the game the SLAM TILT and
    TILT PENDULUM were made at boot: TILT on the screen, and the game stopped
    dead ~35 s later - no frame, no lamp - every title, every boot. At rest
    the board answers Spike 2's measured node-1 word, 04 59 7f 00 ...: every
    switch released (1), every bit without a switch 0; a coin clears its bit."""
    import s3nodes
    CAB = 0x0A67
    names = {2: "LOCKDOWN BUTTON", 8: "TICKET NOTCH", 11: "START BUTTON",
             12: "TOURNAMENT START BUTTON", 14: "TILT PENDULUM", 16: "LEFT COIN",
             17: "CENTER COIN", 18: "RIGHT COIN", 19: "FOURTH COIN", 20: "FIFTH COIN",
             21: "SIXTH COIN", 22: "SLAM TILT"}
    devs5 = [(nm, 1, i, "switch", CAB) for i, nm in names.items()]
    devs5.append(("TROUGH 1", 8, 37, "switch", 0x0A6A))
    state = {"b": bytes(8)}
    br = s3bridge.Bridge(0, open(os.devnull, "w"))
    n = _node(bytes(8))
    n.inputs = lambda: state["b"]
    br.nodes[1] = n
    br.set_polarity(s3nodes.active_low_masks(devs5))
    scan = lambda: n(bytes([0x11, 0x00, 0x00]), 11)[:8]
    assert scan() == bytes([0x04, 0x59, 0x7F, 0, 0, 0, 0, 0])
    state["b"] = bytes([0, 0, 0x01, 0, 0, 0, 0, 0])      # LEFT COIN made
    assert scan() == bytes([0x04, 0x59, 0x7E, 0, 0, 0, 0, 0])


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


def test_resting_board_is_read_once_before_a_press():
    """PAD-1139: the cabinet board (coins, Start) has nothing closed at boot,
    so it never raised a request and the game's FIRST scan of it was the
    player's first coin - which the game took as the starting state: the
    first two coins after boot never credited (pokemon_le, 2 of 4). Past
    bring-up the board now raises one request with its resting inputs."""
    state = {"b": bytes(8)}
    br = s3bridge.Bridge(0, open(os.devnull, "w"))
    n = _node(bytes(8))
    n.inputs = lambda: state["b"]
    br.nodes[1] = n
    scan = lambda: n(bytes([0x11, 0x00, 0x00]), 11)[:8]
    n.registered = time.time()                           # still in bring-up
    assert br.attention() == 0
    n.registered = time.time() - 60
    assert br.attention() == 1                           # the baseline read
    assert scan() == bytes(8)
    assert br.attention() == 0                           # once only
    state["b"] = bytes([0, 0, 0x01, 0, 0, 0, 0, 0])      # then a coin
    assert br.attention() == 1
    assert scan() == bytes([0, 0, 0x01, 0, 0, 0, 0, 0])


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


def test_netbridge_crc_range_and_version_come_from_the_card(tmp_path):
    """The CRC runs to the end of the image's first flash segment and the
    version is the card's version.txt: star_wars_2025_pro ships 0.97.0, a
    shorter image, and Pokemon's fixed range froze it on the boot logo."""
    import struct as _s
    import zlib
    flash = bytes(range(256)) * 0x40                       # 0x4000 bytes at 0x10000000
    ph = _s.pack("<8I", 1, 0x100, 0x10000000, 0x10000000, len(flash), len(flash), 5, 0x1000)
    hdr = bytearray(0x34)
    hdr[0:4] = b"\x7fELF"
    _s.pack_into("<I", hdr, 0x1C, 0x34)                   # e_phoff
    _s.pack_into("<HH", hdr, 0x2A, 32, 1)                 # e_phentsize, e_phnum
    img = bytes(hdr) + ph
    img += bytes(0x100 - len(img)) + flash
    elf = tmp_path / "netbridge.elf"
    elf.write_bytes(img)
    (tmp_path / "version.txt").write_text("0.97.0\n")
    assert s3bridge.flash_crc(str(elf)) == zlib.crc32(flash[0x100:]) & 0xFFFFFFFF
    assert s3bridge.fw_version(str(elf)) == (0, 97, 0)


def test_frames_sort_numerically_and_frame_after_waits(tmp_path, monkeypatch):
    """frame_999 sorted after frame_1000 made 'the newest' a stale frame;
    frame_after must not return a frame drawn before the press."""
    import s3press
    monkeypatch.setattr(s3press, "BASE", str(tmp_path / "slot%s"))
    d = tmp_path / "slot5" / "frames"
    d.mkdir(parents=True)
    for n in (998, 999, 1000, 1001):
        (d / ("frame_%d.png" % n)).write_bytes(b"")
    names = [os.path.basename(f) for f in s3press.frames("5")]
    assert names[-1] == "frame_1001.png" and names[0] == "frame_998.png"
    assert os.path.basename(s3press.newest_frame("5")) == "frame_1000.png"
    before = str(d / "frame_1000.png")
    t = time.time()
    got = s3press.frame_after("5", before, timeout=0.6, gap=2)   # none newer yet
    assert time.time() - t >= 0.5 and os.path.basename(got) == "frame_1000.png"
    for n in (1002, 1003):
        (d / ("frame_%d.png" % n)).write_bytes(b"")
    assert os.path.basename(s3press.frame_after("5", before, gap=2)) == "frame_1002.png"


def test_legacy_power_distribution_answered_by_the_bridge():
    """netbridge answers 0x10/0x12/0x15/0x19 itself with a Spike 1/2 power
    board; unanswered, star_wars_2025_pro waited out a timeout per poll."""
    br = s3bridge.Bridge(0, open(os.devnull, "w"))
    body = lambda cmd: s3bridge.frames_in(br.handle(cmd, 1, b""))[0][0][2]
    assert body(0x10) == bytes(3)
    assert body(0x12) == bytes([s3bridge.LINE_HZ])
    assert body(0x15) == b"\xff"
    assert len(body(0x19)) == 2
    assert br.handle(0x11, 1, b"") is None


def test_window_keys_reach_spike3_switches(tmp_path, monkeypatch):
    """padglhost's keyboard block (padsw.h) onto nodesw / spi.in, by the
    s3bridge-written switch_list.txt: edges only, CPU switches on the SPI."""
    import struct as _s
    import s3keys
    table = {"START BUTTON": [1, 11], "LEFT COIN": [1, 16], "TROUGH 1": [8, 37],
             "SERVICE SELECT": [0, 8], "LEFT FLIPPER BUTTON": [8, 25]}
    rows = s3bridge.write_switch_list(table, str(tmp_path / "t" / "switch_list.txt"))
    ids = {name: sid for sid, node, bit, name in rows}
    slot = tmp_path / "slot7"
    slot.mkdir()
    (slot / "nodesw").write_bytes(bytes(512))
    (slot / "spi.in").write_bytes(b"\xff" * 8)
    padsw = tmp_path / "padsw"
    blk = bytearray(4096)
    _s.pack_into("<I", blk, 0, s3keys.MAGIC)
    padsw.write_bytes(bytes(blk))
    monkeypatch.setattr(s3keys, "BASE", str(tmp_path / "slot%s"))
    k = s3keys.Keys("7", str(padsw), str(tmp_path / "t" / "switch_list.txt"))
    assert k.attach()
    sw = lambda: (slot / "nodesw").read_bytes()

    def poke(off, v):
        k.mm.close(); k.mm = None                      # Windows: no rewrite under a map
        b = bytearray(padsw.read_bytes()); b[off] = v; padsw.write_bytes(bytes(b))
        k.attach()
    poke(s3keys.OFF_CAB + 2, 1)                        # the window's START
    k.step()
    assert sw()[8 + 1] & 0x08
    poke(s3keys.OFF_CAB + 2, 0)
    k.step()
    assert not sw()[8 + 1] & 0x08
    poke(s3keys.OFF_HELD + ids["LEFT COIN"], 1)        # a coin by id
    k.step()
    assert sw()[8 + 2] & 0x01
    poke(s3keys.OFF_CAB + 4, 1)                        # SELECT -> SPI bit 0, active low
    k.step()
    assert (slot / "spi.in").read_bytes()[0] == 0xFE
    # edges only: a switch the ball model moved is not re-asserted
    b = bytearray(sw()); b[8 * 8 + 4] |= 0x20; (slot / "nodesw").write_bytes(bytes(b))
    k.step()
    assert sw()[8 * 8 + 4] & 0x20


def test_coin_door_starts_shut_whatever_the_title_names_it(tmp_path, monkeypatch):
    """PAD-1142: a headless run left the interlock (SPI bit 15, active low)
    open - 48V DISABLED, and with saved settings the game waited ~56 s
    before its first node board. The bridge shuts it by name, as the
    window's keyboard does; PAD_S3_DOOR=open keeps it open."""
    monkeypatch.delenv("PAD_S3_DOOR", raising=False)
    for name in ("COIN DOOR POWER INTERLOCK", "COIN DOOR INTERLOCK"):
        spi = tmp_path / "spi.in"
        spi.write_bytes(b"\xff" * 8)
        table = {name: [0, 23], "SERVICE SELECT": [0, 8], "PRISON DOOR CLOSED": [9, 14]}
        assert s3bridge.close_coin_door(table, str(spi)) == [15]
        assert spi.read_bytes() == b"\xff\x7f" + b"\xff" * 6
    spi.write_bytes(b"\xff" * 8)
    assert s3bridge.close_coin_door({"DOOR SWITCH OPTO": [0, 12]}, str(spi)) == []
    monkeypatch.setenv("PAD_S3_DOOR", "open")
    assert s3bridge.close_coin_door({"COIN DOOR INTERLOCK": [0, 23]}, str(spi)) == []
    assert spi.read_bytes() == b"\xff" * 8
    monkeypatch.delenv("PAD_S3_DOOR")
    assert s3bridge.close_coin_door({"COIN DOOR INTERLOCK": [0, 23]}, str(tmp_path / "none")) == []


def _poll(br):
    return s3bridge.frames_in(br.handle(0x25, 1, b""))[0][0][2][0]


def _send(br, node, payload, reply_len=0):
    return br.handle(0x41, 0, bytes([node, len(payload)]) + bytes(payload) + bytes([reply_len]))


def test_boot_discovery_hands_out_every_board_once():
    """PAD-1180: the game's boot discovery polls 0x25, blocks the board it is
    handed (F0 10 + F0 20) and polls again until a 0. Answered 0 from the
    first poll, every Spike 3 title sat 30 s on LOCATING NODE BOARDS. Each
    declared board goes out until it is blocked, then the walk is over for
    good - until the next bus reset (F1 to node 0)."""
    br = s3bridge.Bridge(0, open(os.devnull, "w"))
    for nid in (1, 2, 8):
        br.nodes[nid] = _node(bytes(8))
    _send(br, 0x80, [0xF1, 0x8D])                        # bus reset
    _send(br, 0x80, [0xF0, 0x22, 0x6B])                  # unblock all
    got = []
    for _ in range(4):
        a = _poll(br)
        got.append(a)
        if a:
            _send(br, 0x80 | a, [0xF0, 0x10, 0])
            _send(br, 0x80 | a, [0xF0, 0x20, 0])
    assert got == [1, 2, 8, 0]
    assert br.discovered == {1, 2, 8}
    _send(br, 0x80, [0xF0, 0x22, 0x6B])                  # the walk ends: unblock all
    assert _poll(br) == 0                                # no second walk
    _send(br, 0x80, [0xF1, 0x8D])                        # a new bus reset: again
    assert _poll(br) == 1


def test_board_not_blocked_is_offered_once_a_pass():
    """A board the game is handed but does not block comes round again on the
    next pass, never twice in one (the walk always ends in a 0)."""
    br = s3bridge.Bridge(0, open(os.devnull, "w"))
    br.nodes[1] = _node(bytes(8))
    br.nodes[4] = _node(bytes(8))
    assert _poll(br) == 1
    _send(br, 0x81, [0xF0, 0x20, 0])                     # node 1 blocked
    assert [_poll(br), _poll(br)] == [4, 0]              # node 4 is not
    assert [_poll(br), _poll(br)] == [4, 0]              # so it comes round again


def test_service_loop_ends_discovery_and_the_request_hold():
    """Once the service loop's status probe (ff) has reached a board, the poll
    is the switch requests' alone and the board's hold is over at once - not
    30 s after its identity: attract comes ~25 s sooner with the discovery
    answered, and a coin there would have waited ~20 s (PAD-1180)."""
    br = s3bridge.Bridge(0, open(os.devnull, "w"))
    n = _node(bytes([0, 0, 0x01, 0, 0, 0, 0, 0]))        # a coin closed
    br.nodes[9] = n
    br.discovered = {9}                                  # the walk is done
    n.registered = time.time()                           # identity just read
    assert br.attention() == 0                           # still in bring-up
    n(bytes([0xFF, 0x77]), 9)                            # the service probe
    assert n.in_service
    assert br.attention() == 9
    # re-addressed in service (F0 10/F0 20): back in bring-up until probed
    _send(br, 0x89, [0xF0, 0x10, 0])
    assert not n.in_service
    br2 = s3bridge.Bridge(0, open(os.devnull, "w"))
    br2.nodes[1] = _node(bytes(8))
    br2.nodes[1].in_service = True                       # service has begun:
    assert _poll(br2) == 0                               # no discovery answer
