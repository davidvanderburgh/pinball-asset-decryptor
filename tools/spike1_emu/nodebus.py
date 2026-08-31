"""Spike 1 node-bus pty handler + responder.

The game drives the node bus over /dev/ttyS4 (a real serial port, 460800 baud),
via NODEBUS_TransferMessage in the game ELF.  A regular file/dev-null fails the
port's tcsetattr, so this allocates a pty, publishes the slave path (the
launcher binds it at /dev/ttyS4), captures the game's writes, AND answers the
polls so the node boards register.

Wire format (derived from NODEBUS_TransferMessage/SendData in the game ELF and
confirmed against a live capture):

    request:  [ addr, len, <len bytes: cmd, data..., checksum>, resp_len ]
      * addr      node address; bit7 set = addressed node (0x80 = node 0)
      * len       count of the {cmd,data,checksum} bytes
      * checksum  last of those `len` bytes; makes sum(addr..checksum) == 0 (mod 256)
      * resp_len  number of reply bytes the node must return (0 = none)

Observed: node 0 gets broadcast lamp/coil frames (cmd 0x0f, resp 0); nodes
1,8,9,10,11,12 get status polls (cmd 0x01, resp 12).

The reply framing (length + a sum-to-zero checksum) is known; the exact reply
*content* the game's enumerator wants is still being reverse-engineered, so the
payload here is a first cut (node id + zeros) used to probe the game's reaction.
Every request/response is logged for that analysis.

Usage:  nodebus.py <slave-path-out-file> <capture-file> [log-file]
"""

import os
import struct
import sys
# NOTE: termios is imported lazily inside main() — it is Unix-only, but the pure
# framing helpers (checksum / build_response) are imported by the test suite on
# any platform.


def checksum(byts):
    """The trailing byte that makes sum(byts + [cksum]) == 0 (mod 256)."""
    return (-sum(byts)) & 0xFF


def build_response(addr, body, resp_len, switch_bits=None, board=None,
                   fw=None, lcd_sum=None):
    """Reply frame the game's NODEBUS_TransferMessage (game ELF @0xbfc28)
    expects for an addressed poll:

        [ payload : resp_len-2 bytes ][ checksum : 1 ][ status : 1 ]

    Reply framing + the per-command payload were reverse-engineered from the
    game ELF (NODEBUS_TransferMessage @0xbfc28, node_bus_update_node_status
    @0x71c5c, GetVersion @0xc02f0) and cross-checked against the working Spike 2
    shim.  The three accept gates (all must pass):
      1. exact byte count == resp_len (a short reply = "board absent");
      2. sum(payload + checksum) == 0 (mod 256) — the STATUS byte is EXCLUDED,
         so the checksum is the SECOND-TO-LAST byte, not the last;
      3. the last (status) byte must have bit2 (0x04) and bit3 (0x08) CLEAR.

    Registration needs NO proc-id/part match — any well-formed reply registers
    the node (an unknown proc-id lands it at "status 4 = present", not a crash).
    But the reply MUST be DETERMINISTIC per (node, cmd): the game re-polls and
    memcmp's the 12 bytes up to 5x; differing bytes grade the node "status 9"
    instead of registering it.

    Per-command payloads:
      * cmd 0xfe  GetVersion  = the presence / registration poll (10 payload):
          [0]=mode flags (bit7=0 -> application mode)
          [1..3]=fw version maj/min/sub — MUST MATCH the version of the board's
              runtime hex image on the card (`fw`, e.g. (0,52,0) from
              coil4node-…-0_52_0.hex; the game globs "./%s-%s-%d_%d_[0-9]*.hex"
              and compares via NODEBUS_GetRuntimeHEXImageVersion).  A mismatch
              sends every boot through "UPDATING NODE BOARD RUNTIME" →
              "UPDATE FAILED / PLEASE POWER-CYCLE GAME" (the flash protocol
              isn't modelled), which is exactly the screen the old hardcoded
              1.0.0 produced.  No `fw` -> 1.0.0, the pre-fix behaviour.
          [4..7]=LE32 proc id (any value safe)
          [8..9]=LE16 board id (non-zero, per-node)
      * cmd 0x11  GetInputState (10 payload): [0..7]=switch bytes, [8..9]=aux.
          The 8 switch bytes are ACTIVE-LOW: idle = 0xff, a CLOSED switch at
          node-local position P CLEARS bit (P&7) of byte (P>>3) (LSB-first). The
          game reads bit==0 as closed/pressed, bit==1 as open (verified from
          sys_node_board_device_switch_update_inputs @0x62c2c + the matrix
          orr/bic at @0x72478). `switch_bits` is the 8-byte active-low bitmap.
      * cmd 0xf9  GetFullBoardID == the board's PART NUMBER, read as two 16-byte
          pages (a page selector byte follows the cmd: 0 then 1).  The game turns
          PAGE 0 bytes [0..3] into an LE32 part number and feeds it to
          sys_node_board_type_get_from_part_number (match on part // 100), which
          recovers the board TYPE — and that type both selects the node's
          firmware image and BUILDS ITS SWITCH MAP.  So returning, per node, the
          part number of the type the game expects there (from `board`, the ELF's
          node_board_table -> node_board_type_table; see s1elf.py) makes the whole
          topology validate: the "CHECK POWER DISTRIBUTION BOARD" tech alert
          clears and switch nodes start getting cmd 0x11 polls.  `board` is
          {"type", "part"} for this node (None -> zero part -> the game's
          "unknown board / type 1" path, the pre-fix behaviour).
      * cmd 0xff  GetStatus (8 payload): all-zero = present, no faults.
      * cmd 0xf2 sub 0x30  LCDInsertInfo (12 payload) — the LCD node's insert
          query.  The boot updater (node_bus_update_lcd_insert_data @0x81000
          GBLE) compares the u32 at payload[7..10] (lcdinfo_t+8) against
          NODEBUS_LCDInsertFileChecksum("<name>.bin") — which is simply the
          LE32 at OFFSET 8 of the game dir's lcdinsert.bin header.  Equal =
          the insert flash is current = the whole "UPDATING NODE BOARD
          RUNTIME / WRITING LCD FLASH → UPDATE FAILED / POWER-CYCLE" pass is
          SKIPPED.  `lcd_sum` is that header word (None = no such file ->
          zero payload, the pre-fix behaviour).
      * anything else: a zero payload keeps the node quiet + present.
    (NOTE the trap that cost the Spike 2 shim a third of its playfield: the LAST
    reply byte is a STATUS byte, NOT the checksum.)"""
    if resp_len < 2:
        return bytes(resp_len)
    node = addr & 0x7F
    cmd = body[0] if body else None
    plen = resp_len - 2
    p = bytearray(plen)

    if cmd == 0xFE and plen >= 10:          # GetVersion == presence / register
        maj, mnr, sub = fw if fw else (1, 0, 0)
        p[0] = 0x00                         # bit7=0 -> application mode
        p[1] = maj & 0xFF                   # fw version: match the card's hex
        p[2] = mnr & 0xFF                   # image or the game flashes it
        p[3] = sub & 0xFF                   # (see the docstring)
        # p[4..7] proc id LE32 = 0 (any value safe; unknown -> sentinel)
        board_id = node or 1                # p[8..9] LE16, non-zero per node
        p[8] = board_id & 0xFF
        p[9] = (board_id >> 8) & 0xFF
    elif cmd == 0x11 and plen >= 8:         # GetInputState == switch matrix
        # 8 switch bytes, ACTIVE-LOW: idle 0xff, a closed switch clears its bit.
        sw = switch_bits if switch_bits is not None else b"\xff" * 8
        for i in range(8):
            p[i] = sw[i] if i < len(sw) else 0xFF
        # p[8..9] aux "input mask" — ignored by the runtime path, keep 0.
    elif (cmd == 0xF2 and plen >= 11 and len(body) > 1
            and body[1] == 0x30):           # LCDInsertInfo (see the docstring)
        if lcd_sum is not None:
            p[7:11] = struct.pack("<I", lcd_sum & 0xFFFFFFFF)
    elif cmd == 0xF9 and plen >= 4:         # GetFullBoardID == part number pages
        page = body[1] if len(body) > 1 else 0
        if page == 0 and board and board.get("part"):
            # page 0 bytes[0..3] = LE32 part number -> board type.  The remaining
            # payload (fw fields on the real board) is unused for classification,
            # so zero is fine — same as the version poll the game already accepts.
            p[0:4] = struct.pack("<I", board["part"] & 0xFFFFFFFF)
        # page 1, or an unknown node: zero payload (the game reads part 0 as an
        # unknown board / type 1 — exactly the pre-topology behaviour).
    # cmd 0xff (status) and others: zero payload = present, no faults

    chk = checksum(p)                       # byte plen: payload sums to 0
    status = 0x00                           # byte plen+1: NAK bits clear
    return bytes(p) + bytes([chk, status])


# ---- unaddressed "bridge" commands ----------------------------------------
# Besides the addressed node polls (frame byte0 has bit7 SET), the game issues
# UNADDRESSED commands to the local node-bus bridge (the ASYNCSERIAL front-end,
# "node 0"): NODEBUS_BridgeState/Status/Version, NODEBUS_SetPower, …  These go
# through the SAME NODEBUS_TransferMessage @0xbfc28, but its unaddressed path
# (byte0 bit7 clear) sends a bare {cmd, len, <len bytes>} frame — NO checksum
# and, crucially, NO resp_len byte on the wire (the reply length is implicit per
# command) — and copies the reply straight back with no checksum/status framing
# (unlike the addressed 12-byte polls).  See build_response's note for the
# addressed framing; the bridge replies are just `resp_len` raw bytes.
#
# The one that gates the whole boot is NODEBUS_GetPower (@0xc4608): on this
# platform (mode 2) it calls NODEBUS_BridgeState (cmd 0x0a) and returns
# reply[0] bit0 as the power state.  sys_node_bus_control_thread_startup only
# calls node_bus_are_all_nodes_OK when GetPower()>0 — so if the bridge never
# answers 0x0a, GetPower returns -1, the readiness check is skipped every retry,
# and the game sits on "LOCATING NODE BOARDS" no matter how correct the nodes
# are.  Worse, our old parser DROPPED {0x0a,0x00} (len==0) and then read the
# trailing 0x00 as a NODEBUS_Poll token — corrupting the enumerator stream and
# making the boot flaky.  Recognising these frames (and consuming them by their
# wire length byte) fixes both.  Reply-expecting bridge commands and their
# implicit reply lengths:
#   0x03 BridgeVersion -> 3 bytes (fw maj/min/sub)   [cosmetic; any nonzero ver]
#   0x05 BridgeStatus  -> 1 byte  (status; 0 = no faults)
#   0x0a BridgeState   -> 2 bytes (reply[0] bit0 = power good; rest = no fault)
# Everything else unaddressed (SetPower 0x07, Reset, SetTraffic, …) is
# fire-and-forget (resp_len 0): consumed, no reply.
BRIDGE_REPLY = {
    0x03: bytes([0x01, 0x00, 0x00]),        # bridge fw v1.0.0 (present, valid)
    0x05: bytes([0x00]),                    # bridge status: no faults
    0x0A: bytes([0x01, 0x00]),              # bit0=power good; no 48V/fault bits
}


# ---- switch injection (viewer -> game) ------------------------------------
# The viewer writes SwitchInput (pinball_decryptor...spike1_emulate): a 12-byte
# header {magic 0x53315357, version, seq} + a 128-byte bitmap, one bit per slot
# (slot = node*64 + index).  We turn that into per-node ACTIVE-LOW switch bytes.
_SW_MAGIC = 0x53315357
_SW_HEADER = 12
_SW_NBYTES = 128
_NODE_INDEXES = 64
SW_IDLE = b"\xff" * 8                       # nothing pressed (active-low)


def read_injected_switches(path):
    """Read the viewer's SwitchInput bitmap -> {node: bytes(8)} of active-low
    switch bytes, for nodes with any closed switch.  {} if the file is missing/
    malformed (so a run with no viewer simply injects nothing)."""
    if not path:
        return {}
    try:
        with open(path, "rb") as f:
            buf = f.read()
    except OSError:
        return {}
    if len(buf) < _SW_HEADER + _SW_NBYTES:
        return {}
    import struct
    if struct.unpack_from("<I", buf, 0)[0] != _SW_MAGIC:
        return {}
    bits = buf[_SW_HEADER:_SW_HEADER + _SW_NBYTES]
    out = {}
    for node in range(16):
        sw = bytearray(SW_IDLE)
        closed = False
        for i in range(_NODE_INDEXES):
            slot = node * _NODE_INDEXES + i
            if bits[slot >> 3] & (1 << (slot & 7)):
                sw[i >> 3] &= ~(1 << (i & 7)) & 0xFF   # clear bit = closed
                closed = True
        if closed:
            out[node] = bytes(sw)
    return out


class WireParser:
    """Incremental parser for the game->CPU wire stream (the bytes the game
    transmits).  ``feed(data)`` yields events:

      ("poll",)                        — a bare 0x00 NODEBUS_Poll token
      ("bridge", cmd, data)            — an unaddressed bridge command
      ("frame", addr, body, resp_len)  — an addressed frame (checksum ok);
                                         body[0] is the command byte

    Shared by the responder (main) and by capture followers (s1ball.py tails
    ttyS4.cap with one of these to see coil fires).
    """

    # NO artificial length cap: ln is one byte (<= 255) and every rejected
    # frame start desyncs the stream — GOT LE's cmd-0x75 nonce frames
    # (ln=0x12) blew through a 16-byte cap, then Ghostbusters' config frames
    # blew through 64.  Each time the shifted stream mis-parsed a byte as a
    # "bridge command" whose length byte swallowed hundreds of real bytes
    # (poll tokens included) and wedged the bus.  A garbage byte read as a big
    # ln just waits for the bytes and self-corrects via the checksum below.
    MAX_LEN = 255

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data):
        buf = self.buf
        buf += data
        while buf:
            if buf[0] == 0x00:               # NODEBUS_Poll token
                del buf[0]
                yield ("poll",)
                continue
            if not (buf[0] & 0x80):          # UNADDRESSED bridge command
                # {cmd, len, <len bytes>} — no checksum, no resp_len on the
                # wire.  Consume by the wire length byte so a bridge command
                # can never desync the poll stream.
                if len(buf) < 2:
                    return                   # need cmd + len byte
                bcmd = buf[0]
                blen = buf[1]
                if len(buf) < 2 + blen:
                    return                   # wait for the data bytes
                bdata = bytes(buf[2:2 + blen])
                del buf[:2 + blen]
                yield ("bridge", bcmd, bdata)
                continue
            if len(buf) < 3:
                return
            ln = buf[1]
            need = ln + 3      # addr, len, len bytes, resp_len
            if ln == 0 or ln > self.MAX_LEN:
                del buf[0]     # resync: not a frame start
                continue
            if len(buf) < need:
                return         # wait for the rest of the frame
            frame = bytes(buf[:2 + ln])          # addr..checksum
            resp_len = buf[2 + ln]
            if (sum(frame) & 0xFF) != 0:
                del buf[0]     # bad checksum -> resync
                continue
            del buf[:need]     # consume the frame
            yield ("frame", frame[0], frame[2:], resp_len)


def main():
    import termios
    slave_path_file = sys.argv[1]
    capture_file = sys.argv[2]
    log_file = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None

    master, slave = os.openpty()
    slave_path = os.ttyname(slave)

    attrs = termios.tcgetattr(slave)
    attrs[0] = 0            # iflag: raw
    attrs[1] = 0            # oflag: raw
    attrs[3] = 0            # lflag: no echo/canon/signals
    termios.tcsetattr(slave, termios.TCSANOW, attrs)

    with open(slave_path_file, "w") as f:
        f.write(slave_path + "\n")

    cap = open(capture_file, "wb", buffering=0)
    log = open(log_file, "w", buffering=1) if log_file else None

    def logline(s):
        if log:
            log.write(s + "\n")
            log.flush()

    import time as _t
    _dbgpath = os.environ.get("NB_DEBUG")
    _dbg = open(_dbgpath, "w", buffering=1) if _dbgpath else None

    def _d(m):
        if _dbg:
            _dbg.write("%.3f %s\n" % (_t.monotonic(), m))

    _d("START log=%r" % log_file)

    # node topology (env S1_GAME_ELF): the game's own node_board tables tell us
    # which board TYPE — and thus which part number — each node address expects,
    # so the cmd-0xf9 GetFullBoardID reply classifies every board correctly (see
    # s1elf.py / build_response).  Best-effort: a bare responder (no part numbers)
    # if the ELF is absent or unreadable, which is the pre-fix behaviour.
    topology = {}
    elf_path = os.environ.get("S1_GAME_ELF")
    if elf_path:
        try:
            import s1elf
            topology = s1elf.extract_topology(elf_path)
            _d("topology: %r" % topology)
            logline("topology: %d boards from %s" % (len(topology), elf_path))
        except Exception as e:                             # noqa: BLE001
            _d("topology extract failed: %s" % e)
            logline("topology extract failed: %s" % e)

    # NODEBUS_Poll (a bare 0x00 broadcast, 1-byte reply) is the bus enumerator:
    # the game hands out each node that is "present" via this poll, blocks it, and
    # polls again for the next, until a 0 ends the scan.  It serves TWO callers:
    #   * boot: node_bus_identify_attached_nodes (game ELF @0x74070) enumerates the
    #     ATTACHED node boards this way — then sys_node_board_set_runtime_flags
    #     SETS the boot "ready" flag on the nodes it saw and CLEARS it on the rest.
    #     If we hand out nothing here, every node's ready flag is cleared and the
    #     game sits on "LOCATING NODE BOARDS" forever.  So the scan MUST return the
    #     real attached nodes (the playfield node boards from the ELF topology).
    #   * runtime: the game re-polls to find a node whose switches CHANGED.
    # We return the union: the attached playfield nodes (always, so identify sees
    # them) plus any node with an injected switch change.  Bridge/CPU nodes
    # (board type 2/3) are EXCLUDED — the boot gate wants their ready flag CLEAR,
    # so they must NOT be reported as attached here.
    attached = sorted(a for a, b in topology.items()
                      if isinstance(b, dict) and b.get("type") not in (2, 3))
    _d("attached (poll scan): %r" % attached)

    # The firmware version every node reports (cmd 0xFE bytes [1..3]) — taken
    # from the card's own runtime hex images (…-<maj>_<min>_<sub>.hex, next to
    # the game ELF) so it MATCHES what the game ships and no boot ever detours
    # through "UPDATING NODE BOARD RUNTIME / UPDATE FAILED".  Majority vote
    # across the images (they are uniform per system release); S1_FW_VER
    # ("maj.min.sub") overrides for experiments.
    fw_ver = None
    env_fw = os.environ.get("S1_FW_VER")
    if env_fw:
        try:
            fw_ver = tuple(int(x) for x in env_fw.split("."))[:3]
        except ValueError:
            pass
    if fw_ver is None and elf_path:
        import collections
        import re as _re
        seen = collections.Counter()
        try:
            for fn in os.listdir(os.path.dirname(elf_path) or "."):
                m = _re.search(r"-(\d+)_(\d+)_(\d+)\.hex$", fn)
                if m:
                    seen[tuple(int(g) for g in m.groups())] += 1
        except OSError:
            pass
        if seen:
            fw_ver = seen.most_common(1)[0][0]
    _d("fw_ver: %r" % (fw_ver,))
    logline("node fw version reported: %s"
            % (".".join(map(str, fw_ver)) if fw_ver else "1.0.0 (fallback)"))

    # The LCD-insert content checksum (cmd 0xf2/0x30 reply): the LE32 at
    # offset 8 of the title's lcdinsert.bin, so the boot updater sees the
    # insert flash as current and skips its rewrite (see build_response).
    lcd_sum = None
    if elf_path:
        try:
            with open(os.path.join(os.path.dirname(elf_path),
                                   "lcdinsert.bin"), "rb") as f:
                hdr = f.read(12)
            if len(hdr) >= 12:
                lcd_sum = struct.unpack_from("<I", hdr, 8)[0]
        except OSError:
            pass
    _d("lcd_sum: %r" % (lcd_sum,))
    logline("lcd insert checksum: %s"
            % ("0x%08x" % lcd_sum if lcd_sum is not None else "no lcdinsert.bin"))
    sw_input_path = os.environ.get("S1_SW_INPUT")
    sw_auto_path = os.environ.get("S1_SW_AUTO")
    injected = {}             # node -> current active-low switch bytes
    last_reported = {}        # node -> switch bytes last delivered via cmd 0x11
    blocked = set()           # nodes the game has "blocked" for the current scan
    sw_attempts = {}          # node -> deliveries since its state was last READ
    offered = set()           # nodes handed out this scan by the default rule

    # Cap on how many times poll_next() offers a switch-CHANGED node before the
    # game reads it.  The runtime scanner (sys_node_bus_control_thread_poll)
    # reads a polled node's switches ONLY if the node's block flag [+4]&1 is set
    # (in attract that is just node 1); a node without it is BLOCKED, not read.
    # So a changed node the game refuses to read must not be offered forever —
    # after the cap we fall back to the default poll so the loop can't hang.
    _SW_ATTEMPT_CAP = 8

    def poll_next():
        # The bus enumerator (NODEBUS_Poll, the bare 0x00 token) serves two
        # callers, and BOTH read whatever node we hand back:
        #   * boot: node_bus_identify_attached_nodes polls, BLOCKS the node it
        #     got (cmd 0xF0), polls for the next, … until it gets 0 — so at boot
        #     we hand out the lowest attached node NOT yet blocked, then 0, and
        #     the scan terminates with every node identified.
        #   * runtime: sys_node_bus_control_thread_poll polls to find a node with
        #     a SWITCH CHANGE to report, reads it, and (for a scan-enabled node)
        #     does NOT block it — so the OLD "lowest unblocked" rule handed back
        #     node 1 on every poll forever (2.6M reads) and NEVER advanced to the
        #     playfield nodes, so an injected switch on node 8/9/10 (e.g. the
        #     START button at node 9) was never delivered.
        # Fix: first offer any node whose injected switch state DIFFERS from what
        # we last delivered (a real change to report), capped so a node the game
        # won't read can't spin; otherwise offer each attached node AT MOST ONCE
        # per scan, then answer 0 so the scan TERMINATES.  The runtime scanner
        # (an inner loop in the game's node-bus control thread) polls until it
        # gets 0 — a responder that always names a node traps that thread in the
        # scan forever, and the control loop's OTHER duties (the CPU-SPI
        # dedicated-switch read, coil output drain) never run: coins/flippers/
        # interlock go dead and the trough-eject coil can never fire.
        for n in sorted(set(injected) | set(last_reported)):
            cur = injected.get(n, SW_IDLE)
            if cur != last_reported.get(n) and sw_attempts.get(n, 0) < _SW_ATTEMPT_CAP:
                sw_attempts[n] = sw_attempts.get(n, 0) + 1
                return n
        for n in sorted(set(attached) | set(injected.keys())):
            if n not in blocked and n not in offered:
                offered.add(n)
                return n
        offered.clear()
        return 0

    def handle_traffic(addr, body):
        # cmd 0xF0 = the game's traffic-control command (NODEBUS_BlockTraffic /
        # ClearTraffic / SetTraffic).  body[1]: 0x20 block, 0x22 unblock; a
        # 0x22/reset addressed to node 0 (BlockTraffic(0,0)) starts a fresh scan.
        node = addr & 0x7F
        sub = body[1] if len(body) > 1 else 0
        if sub == 0x20:
            blocked.add(node)
        elif sub == 0x22:
            blocked.clear() if node == 0 else blocked.discard(node)

    parser = WireParser()
    try:
        while True:
            try:
                data = os.read(master, 1 << 16)
            except OSError:
                break
            if not data:
                break
            cap.write(data)
            _d("read %d bytes head=%s" % (len(data), bytes(data[:12]).hex()))
            if sw_input_path or sw_auto_path:
                # merge the viewer's clicks with the automation daemon's state
                # (s1ball.py): both are SwitchInput bitmaps; a switch is closed
                # if EITHER source closes it (active-low -> AND the byte maps).
                injected.clear()
                injected.update(read_injected_switches(sw_input_path))
                for node, sw in read_injected_switches(sw_auto_path).items():
                    cur = injected.get(node)
                    if cur is None:
                        injected[node] = sw
                    else:
                        injected[node] = bytes(a & b for a, b in zip(cur, sw))

            # parse the bare-0x00 poll token + framed messages out of the buffer
            for ev in parser.feed(data):
                if ev[0] == "poll":
                    node = poll_next()
                    try:
                        os.write(master, bytes([node & 0xFF]))
                    except OSError:
                        pass
                    if node:
                        logline("POLL -> node %d (switch data pending)" % node)
                    _d("poll -> %d" % node)
                    continue
                if ev[0] == "bridge":
                    # reply the implicit number of raw bytes for the bridge
                    # commands the boot waits on; the rest get no reply.
                    bcmd, bdata = ev[1], ev[2]
                    reply = BRIDGE_REPLY.get(bcmd)
                    if reply is not None:
                        try:
                            os.write(master, reply)
                        except OSError:
                            pass
                        logline("BRIDGE cmd=0x%02x len=%d -> %s"
                                % (bcmd, len(bdata), reply.hex()))
                        _d("bridge cmd=%02x -> %s" % (bcmd, reply.hex()))
                    else:
                        logline("BRIDGE cmd=0x%02x len=%d data=%s (no reply)"
                                % (bcmd, len(bdata), bdata.hex()))
                        _d("bridge cmd=%02x data=%s (no reply)"
                           % (bcmd, bdata.hex()))
                    continue
                _, addr, body, resp_len = ev
                cmd = body[0] if body else None
                if resp_len:
                    node = addr & 0x7F
                    sb = injected.get(node) if cmd == 0x11 else None
                    resp = build_response(addr, body, resp_len, switch_bits=sb,
                                          board=topology.get(node), fw=fw_ver,
                                          lcd_sum=lcd_sum)
                    if cmd == 0x11:
                        # the game actually READ this node's switches: record what
                        # we delivered (so poll_next stops offering it as changed)
                        # and clear its spin-guard counter.
                        last_reported[node] = injected.get(node, SW_IDLE)
                        sw_attempts[node] = 0
                    logline("REQ addr=0x%02x node=%d cmd=0x%02x resp_len=%d -> %s"
                            % (addr, node, cmd if cmd is not None else 0,
                               resp_len, resp.hex()))
                    try:
                        n = os.write(master, resp)
                        _d("frame addr=%02x cmd=%02x resp_len=%d wrote=%d"
                           % (addr, cmd or 0, resp_len, n))
                    except OSError as e:
                        logline("  write failed: %s" % e)
                        _d("frame addr=%02x resp_len=%d WRITE FAILED %s"
                           % (addr, resp_len, e))
                else:
                    if cmd == 0xF0:                 # traffic block/unblock
                        handle_traffic(addr, body)
                    logline("REQ addr=0x%02x node=%d cmd=0x%02x data=%s (no reply)"
                            % (addr, addr & 0x7F, cmd if cmd is not None else 0,
                               body.hex()))
    finally:
        cap.close()
        if log:
            log.close()
        os.close(master)
        os.close(slave)


if __name__ == "__main__":
    main()
