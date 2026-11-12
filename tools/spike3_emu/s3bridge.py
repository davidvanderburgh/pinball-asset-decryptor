#!/usr/bin/env python3
"""s3bridge - the Spike 3 netbridge board, answering its host UART (PAD-1090).

On the machine the CPU module talks to the RP2040 "netbridge" board over a
UART (/dev/ttyAMA5). The board's program is on the card -
games/<title>/spike3/netbridge/netbridge.elf, unstripped - and everything this
answers is read off it (uart_host.c's HOSTUART_SendMessage and main.c's
HOST_Update dispatch), the same footing as Spike 2's netbridge.py:

  frame     02 <cmd> <id> <payload...> <sum> 03; cmd..sum add to 0 mod 256
            (unescaped); 0x02/0x03/0x1b inside are sent as 1b <byte|0x80>.
            Replies carry the request's cmd and id.
  0x20      version: [0, 98, 4, adc] - the firmware's own strings "0","98",
            "4" and the board revision its ADC ladder reads (0..10)
  0x30      CRC32 (zlib's) of the board's flash 0x10000100..0x10012b40, i.e.
            of the image it runs. Computed from the card's netbridge.elf, so
            the game sees the image it would flash already there and does not
            run openocd to reflash the board.
  0x25      NODEBUS_Poll: the lowest node address raising a request, 0 for
            none (its binary search moves down on every answer)
  0x27 n    LCD; sub 0 (and 2) answer LCD_GetStatus, one byte
  0x41      a node bus exchange: [node] [n] [n bytes] [reply_len]. The board
            sends the bytes to the node chain and answers reply_len bytes:
            reply_len-1 from the node, then its node status byte - 0x00 for a
            complete reply, 0x04 for a timeout (the rest left 0x55, as the
            board's buffer is). reply_len 0 = a write, no answer.
  0x10..1f  forwarded to the power distribution board (not answered yet)

THE NODE BOARDS behind 0x41 are the title's own: s3nodes.py reads its node
directory and board catalog out of the game program, and each declared node
answers the node bus protocol Spike 2's emulator worked out (the Spike 3 game
sends the very same frames - `81 02 fe 7f 0d` is node 1's identity request on
both). The request is [0x80|node] [n] [payload..., checksum] and the node's
reply is reply_len-2 payload bytes and a checksum that makes them sum to 0:
  fe     the identity - [0, fw maj, min, patch, LE32 MCU part id, LE16 board
         id, variant] - claimed as s3nodes.py derives it (the class, part id
         and variant the title's own <type>-<class>-<ver>.hex grades against)
  f9 00  runtime info; bytes 8..11 the board's part number (catalog x100)
  else   zeros
A node the directory does not declare times out, as an empty address does.

    s3bridge.py DIR [NETBRIDGE_ELF [GAME_ELF]]
        writes DIR/bridge.path (the pty) and DIR/bridge.log
"""
import os
import select
import struct
import sys
import time
import zlib

STX, ETX, ESC = 0x02, 0x03, 0x1B
FW_VERSION = (0, 98, 4)          # main.c's version strings, pokemon_le 0.82.0
BOARD_REV = 0                    # what ADC_Update's ladder can report: 0..10
# The bridge's LCD status (cmd 27 sub 0/2). 0 held every boot ~30 s: the game
# asks at once, then every 10 s, three times, before it gives up and starts
# the node bus. 2 it takes at once - first board claimed 5.9 s after start
# instead of 36 s, attract at 38 s instead of ~90 (pokemon_le, measured twice
# each; star_wars_2025_le 8.5 s) - and the games play as before (PAD-1090).
LCD_STATUS = int(os.environ.get("PAD_S3_LCD_STATUS", "2"), 0)
SWTRACE = os.environ.get("PAD_S3_SWTRACE") == "1"   # log every scanned switch change
T0 = time.time()
# PAD-1139: scans of a board's RESTING inputs the game is given before anything
# the player does can reach it (Bridge.attention). Measured on pokemon_le.
BASELINE_SCANS = int(os.environ.get("PAD_S3_BASELINE_SCANS", "1"))
LINE_HZ = int(os.environ.get("PAD_S3_LINE_HZ", "60"))     # ADC_GetLineFrequency
LINE_V = int(os.environ.get("PAD_S3_LINE_V", "120"))      # ADC_GetLineVoltage
FLASH = (0x10000100, 0x10012B40)  # the range HOST_Update's 0x30 handler CRCs


def flash_crc(elf_path):
    """CRC32 the board computes over its own flash, from its ELF image: from
    FLASH[0] (past the 256-byte boot stage) to the END OF THE IMAGE'S FIRST
    FLASH SEGMENT. That end is per build - 0x10012b40 on netbridge 0.98.4
    (pokemon_le's FLASH[1]), 0x10012bec on 0.98.6 (fallout_le), 0x10012110
    on 0.97.0 (star_wars_2025_pro): with Pokemon's range fixed in, Pro's CRC
    could not be computed, the game tried to reflash the board with openocd,
    failed, and stopped drawing on the boot logo."""
    d = open(elf_path, "rb").read()
    phoff, = struct.unpack_from("<I", d, 0x1C)
    phsz, phn = struct.unpack_from("<HH", d, 0x2A)
    for i in range(phn):
        t, off, va, pa, fsz, msz, fl, al = struct.unpack_from("<8I", d, phoff + i * phsz)
        if t == 1 and va <= FLASH[0] < va + fsz:
            return zlib.crc32(d[off + FLASH[0] - va: off + fsz]) & 0xFFFFFFFF
    raise ValueError("%s: no load segment covers the flash start" % elf_path)


def fw_version(elf_path):
    """The netbridge build the card ships (its version.txt beside the ELF,
    "0.98.4"): the board reports what the game expects to find."""
    try:
        with open(os.path.join(os.path.dirname(elf_path), "version.txt")) as f:
            v = tuple(int(x) for x in f.read().strip().split("."))
        if len(v) == 3 and all(0 <= x < 256 for x in v):
            return v
    except (OSError, ValueError):
        pass
    return FW_VERSION


def frame(cmd, ident, payload=b""):
    body = bytes([cmd, ident]) + bytes(payload)
    body += bytes([(-sum(body)) & 0xFF])
    out = bytearray([STX])
    for b in body:
        out += bytes([ESC, b | 0x80]) if b in (STX, ETX, ESC) else bytes([b])
    out.append(ETX)
    return bytes(out)


def unmask(node, data):
    """Spike 3's node frame mask, read off the bus (its own inverse). A node
    address with bit 0x40 set carries Spike 2's frame - `cmd args... ck`,
    the whole frame summing to zero - with every byte XORed by
    m = (node & 0x0f) << 4 | (n & 0x0f), n the byte count, and the odd
    bytes by ~m instead. Measured on pokemon_le: decoded this way every one
    of 110 distinct frame kinds checksums, the switch scan reads `11 key ck`
    and the coil fire `40 IDX power ...` exactly as on Spike 2."""
    n = len(data)
    m = ((node & 0x0F) << 4) | (n & 0x0F)
    return bytes(b ^ (m if j % 2 == 0 else (~m & 0xFF)) for j, b in enumerate(data))


class Node:
    """One node board, answering as the title expects its board to."""

    def __init__(self, nid, claim, log):
        self.nid, self.c, self.log, self.said = nid, claim, log, set()
        self.inputs = None        # () -> this node's 8 live input bytes
        self.reported = bytes(8)  # what the game last read (scan or ff)
        self.registered = 0       # when its identity was first read (time)
        self.rx = 0               # addressed frames since the last ff probe
        self.low_mask = bytes(8)  # inputs whose wire bit 0 = closed
        self.queue = []           # input states seen, not yet scanned
        self.scans = 0            # switch scans (0x11) the game has made
        self.in_service = False   # the game's service loop has probed it (ff)

    def __call__(self, data, k):
        """k reply bytes (payload + checksum) for request payload `data`."""
        plen = k - 1
        if plen < 0:
            return None
        p = bytearray(plen)
        cmd = data[0] if data else None
        c = self.c
        if cmd == 0xFE and plen >= 10:
            if not self.registered:
                self.registered = time.time()
            fw = c["fw"]
            p[0:4] = bytes([0, fw[0], fw[1], fw[2]])
            p[4:8] = struct.pack("<I", c["part"])
            p[8:10] = struct.pack("<H", c["hwid"])
            if plen >= 11:
                p[10] = c["variant"]
            self.once("fe", "node %d claims %s part=0x%08x variant=0x%02x fw=%d.%d.%d (%s)" % (
                self.nid, c["type"], c["part"], c["variant"], fw[0], fw[1], fw[2], c["hex"]))
        elif cmd == 0xF9 and len(data) > 1 and data[1] == 0 and plen >= 12:
            p[8:12] = struct.pack("<I", c["partno"])
            self.once("f9", "node %d reports part %s (%d)" % (self.nid, c["partstr"], c["partno"]))
        elif plen == 10 and cmd == 0x11:
            # THE SWITCH SCAN, Spike 2's 0x11 (masked on the wire - unmask):
            # 10 bytes, [0..7] the board's 64 switch bits, [8..9] a u16 (0).
            # A request carrying a byte before its checksum (n=3: `11 key
            # ck`) keys the reply: byte c is XORed with rol8(key, c) (Spike
            # 2's hwshim, measured). The bits are the live ones from nodesw.
            # the oldest queued state first (Bridge.attention), else live
            self.scans += 1
            if self.queue:
                bits = self.queue.pop(0)
            else:
                bits = self.inputs() if self.inputs else bytes(8)
            # nodesw is LOGICAL (1 = closed); an active-low board's wire bit
            # is 0 for a closed switch
            wire = bytes(b ^ m for b, m in zip(bits, self.low_mask))
            key = data[1] if len(data) >= 3 else 0
            for i in range(8):
                p[i] = wire[i] ^ (((key << i) | (key >> ((8 - i) & 7))) & 0xFF)
            if SWTRACE and bits != self.reported:
                # every change the game SCANS (PAD_S3_SWTRACE=1): the log
                # line below says each distinct state once only
                now = time.time()
                self.log.write("%9.3f # [scan] %s.%03d node %d %s\n" % (
                    now - T0, time.strftime("%H:%M:%S", time.localtime(now)),
                    now % 1 * 1000, self.nid, bits.hex()))
            self.reported = bits
            if any(bits):
                self.once("sw" + bits.hex(), "node %d switches %s" % (self.nid, bits.hex()))
        elif cmd == 0xFF and plen >= 8:
            # the status probe (Spike 2's 0x5a43d0, PAD-249): word A = the
            # number of addressed frames the board took since the last probe,
            # this one included - the game counts the same and, on a
            # mismatch, sets bit 31 of B, and B & 0x8010211f re-initialises
            # the board (a 14/46/48/72 burst) for ever. Word B stays 0: it
            # was the input bits here, and node 9's bit 31 alone was a fault.
            p[0:4] = struct.pack("<I", self.rx)
            self.rx = 0
            # the probe comes only from the service loop: bring-up is over
            # for this board, and its requests may go up (Bridge.attention)
            self.in_service = True
            # NOT a read of the switches: the game sends it to every node once
            # a second and takes no switch events from it. Counting it as one
            # cleared a raised request with no scan - a trough closed before
            # boot went unseen (LOCATING PINBALLS for ever), and of a coin, a
            # Start and a flipper only the coin reached the game. Only the
            # scan (0x11) clears a request.
        return bytes(p) + bytes([(-sum(p)) & 0xFF])

    def once(self, key, msg):
        if key not in self.said:
            self.said.add(key)
            self.log.write("# [node] %s\n" % msg)


class Bridge:
    def __init__(self, crc, log, claims=None):
        self.crc = crc
        self.version = FW_VERSION     # main() sets the card's own (fw_version)
        self.log = log
        # node address -> model: the title's declared node boards
        self.nodes = {nid: Node(nid, c, log) for nid, c in (claims or {}).items()}
        self.counts = {}
        self.balls = None         # s3balls.Balls once the inputs are attached
        self.steppers = None      # s3motors.Steppers once the inputs are attached
        self.motors = None        # s3motors.Motors (end-stop / encoder motors)
        self.rules = None         # s3rules.Rules: coils the boards fire by rule
        # the game's boot discovery (PAD-1180, see discover())
        self.discovered = set()   # boards it has found and blocked
        self.offered = set()      # boards handed out in this pass, not yet blocked

    def discover(self):
        """The board the game's BOOT DISCOVERY finds next, 0 when it has them
        all (PAD-1180). Spike 1's node_bus_identify_attached_nodes, and Spike
        3 sends the same frames: after the bus reset (F1 to node 0) and an
        unblock-all (F0 22 to node 0) it polls NODEBUS_Poll (0x25), BLOCKS the
        board it is handed (F0 10 + F0 20 to it, no reply) and polls again,
        until a 0 ends the walk. A board found that way counts as attached.
        Answered 0 from the first poll - as this bridge did - the game found
        no board, re-ran its identity walk every 0.3 s and gave up after a
        fixed 30 s from the bus reset, its red LOCATING NODE BOARDS box on
        the screen all that time: every title, every boot (pokemon_le's
        service loop at 35 s; with the walk answered, at 10 s).

        Each declared board is handed out once until the game blocks it;
        then the walk is over for good (until another bus reset), so the
        service loop's polls meet only the switch requests of attention().
        A board the game is handed but does not block is offered again on
        its next pass, never twice in one; and none once the service loop
        has begun (a status probe reached any board)."""
        if any(n.in_service for n in self.nodes.values()):
            return 0
        for nid in sorted(self.nodes):
            if nid not in self.discovered and nid not in self.offered:
                self.offered.add(nid)
                return nid
        self.offered.clear()
        return 0

    def note_traffic(self, node, data):
        """F1 / F0 frames, as discover() needs them: F1 to node 0 resets the
        bus (a fresh discovery); F0 10 or F0 20 to a board handed out blocks
        it - found."""
        nid = node & 0x3F
        if data[0] == 0xF1 and nid == 0:
            if self.discovered:
                self.log.write("# [discover] bus reset: the boards are found again\n")
            self.discovered.clear()
            self.offered.clear()
            for n in self.nodes.values():
                n.in_service = False
        elif data[0] == 0xF0 and len(data) > 1 and data[1] in (0x10, 0x20) \
                and nid in self.offered and nid not in self.discovered:
            self.discovered.add(nid)
            if self.discovered >= set(self.nodes):
                self.log.write("%9.3f # [discover] the game found every board (%s)\n" % (
                    time.time() - T0, " ".join(str(n) for n in sorted(self.discovered))))

    def attach_inputs(self, path):
        """The slot's node switch inputs, live: 8 bytes a node (64 nodes),
        bit b of node n = byte 8n + b//8, mask 1 << b%8, 1 = closed.
        s3press.py `node` writes them while the game runs."""
        import mmap
        if not os.path.exists(path) or os.path.getsize(path) != 512:
            with open(path, "wb") as f:
                f.write(bytes(512))
        f = open(path, "r+b")
        self.sw = mmap.mmap(f.fileno(), 512)
        for nid, n in self.nodes.items():
            n.inputs = (lambda i=nid: bytes(self.sw[8 * i:8 * i + 8]))

    def attention(self):
        """The lowest node address with something to report, 0 for none: a
        node whose inputs changed since the game last read them (ff) - the
        request a real board raises, which makes the game come and read it.

        ONLY ONCE BRING-UP IS OVER for the board - the service loop's status
        probe (ff) has reached it, or 30 s since its identity was first read
        (or it was last re-addressed): during the node enumeration the game
        answers a raised request by re-addressing the board (F0 10 / F0 20,
        no reply) and polls again, so a request raised then - the trough
        switches closed before boot - held the enumerator on that node 46,000
        times a minute for ever. In the service loop a request is answered by
        the switch scan (02). With the discovery answered (PAD-1180) attract
        comes ~25 s sooner; the 30 s alone would have held a Start or a coin
        there for ~20 s."""
        now = time.time()
        found = 0
        if self.rules is not None:
            self.rules.tick()     # a flipper tap shorter than a loop pass
        for nid in sorted(self.nodes):
            n = self.nodes[nid]
            if not n.inputs:
                continue
            # every distinct state seen here (the game polls ~100 times a
            # second) is queued for its own scan: a 150 ms coin pulse was
            # often released before the game came to read, and lost
            cur = n.inputs()
            last = n.queue[-1] if n.queue else n.reported
            if cur != last:
                n.queue.append(cur)
                if len(n.queue) > 32:
                    del n.queue[1:-15]
            ready = n.registered and (n.in_service or now - n.registered > 30)
            if ready and n.scans < BASELINE_SCANS and not n.queue:
                # the first look at a board with nothing to report: queue its
                # resting state (see BASELINE_SCANS)
                n.queue.append(cur)
            if not found and n.queue and ready:
                found = nid
        return found

    def node_exchange(self, node, data, reply_len):
        """reply_len bytes for a 0x41 exchange (reply_len-1 from the node,
        then the board's status byte). Node bit 0x40 marks a MASKED frame
        (see unmask): the model always sees Spike 2's plain command. The
        REPLY goes back unmasked - measured: masking it too put up DEVICE
        MALFUNCTION alerts and lost the Start button; plain, Start starts."""
        model = self.nodes.get(node & 0x3F)
        if node & 0x40:
            data = unmask(node, data)
        st = None
        if (self.steppers is not None and data and 0x38 <= data[0] <= 0x3D
                and reply_len - 1 >= 6):
            st = self.steppers.status(node & 0x3F, data[0] - 0x38)
        if (self.motors is not None and len(data) >= 2 and data[0] == 0x52
                and reply_len - 1 >= 5):
            st = self.motors.status(node & 0x3F, data[1])
        if st is not None:
            r = st + bytes([(-sum(st)) & 0xFF])
            return r.ljust(reply_len - 1, b"\x55") + b"\x00"
        if model is not None:
            r = model(data, reply_len - 1)
            if r is not None:
                return bytes(r[:reply_len - 1]).ljust(reply_len - 1, b"\x55") + b"\x00"
        return b"\x55" * (reply_len - 1) + b"\x04"

    def set_polarity(self, masks):
        """masks: {node: 8 bytes}, the inputs that report CLOSED as wire bit
        0 (s3nodes.active_low_masks: the playfield switches, by location).
        Found with the service menu's Ball Trough Test, which draws the
        game's own reading live: trough, shooter lane, jam and scoop show a
        ball for wire 0. Cabinet buttons - on the cabinet board, and the
        flipper buttons wired to playfield node 8 - stay active high.
        PAD_S3_ACTIVE_LOW=<ids> / PAD_S3_ACTIVE_HIGH=<ids> force whole boards."""
        ids = lambda v: {int(x) for x in os.environ.get(v, "").replace(",", " ").split() if x.isdigit()}
        lo, hi = ids("PAD_S3_ACTIVE_LOW"), ids("PAD_S3_ACTIVE_HIGH")
        for nid, n in self.nodes.items():
            m = masks.get(nid, bytes(8))
            if nid in lo:
                m = b"\xff" * 8
            if nid in hi:
                m = bytes(8)
            n.low_mask = m
        self.log.write("# [polarity] active-low inputs: %s\n" % " ".join(
            "%d:%s" % (k, self.nodes[k].low_mask.hex()) for k in sorted(self.nodes)
            if any(self.nodes[k].low_mask)))

    def note_enumeration(self, node, data):
        """`F0 10`/`F0 20` re-address a node: the game is (still) enumerating it, so
        its request stays down for another 30 s (attention()). A request
        raised mid-enumeration is answered with F0 again - on a slow boot the
        fixed 30 s after registration ran out first and the game sent 45,000
        F0s a minute and never reached attract."""
        if not data:
            return
        raw = data
        if node & 0x40:
            data = unmask(node, data)
        # PAD-1134: a coil's rule (41) and "run it by its rule" (short 40) -
        # the board fires flippers, slings and pops itself (s3rules). Only a
        # frame whose checksum holds (address + count + body = 0) may arm one.
        if (self.rules is not None and data[0] in (0x40, 0x41)
                and (node + len(raw) + sum(data)) & 0xFF == 0):
            self.rules.note(node & 0x3F, data)
        # coil and motor commands ask for no reply, so they never reach
        # node_exchange: the models hear them here (the first trough eject
        # of a real game went unanswered for that reason)
        if self.balls is not None and data[0] == 0x40 and len(data) >= 3:
            self.balls.coil(node & 0x3F, data)
        if self.steppers is not None:
            self.steppers.note(node & 0x3F, data)
        if self.motors is not None:
            self.motors.note(node & 0x3F, data)
        if data[0] in (0xF0, 0xF1):
            self.note_traffic(node, data)
        model = self.nodes.get(node & 0x3F)
        if model is None:
            return
        if node & 0x80:
            model.rx += 1             # every addressed frame, as the game counts
            if data[0] == 0xF1:       # F1: the game restarts its own count
                model.rx = 0
        # F0 10 / F0 20 only: the service loop sends every node F0 11 once
        # a second, and counting that kept every request down for good
        if data[0] == 0xF0 and len(data) > 1 and data[1] in (0x10, 0x20) and model.registered:
            model.registered = time.time()
            model.in_service = False
            self.enum_said = getattr(self, "enum_said", 0) + 1
            if self.enum_said <= 20 or self.enum_said % 1000 == 0:
                self.log.write("# [enumerate] node %d re-addressed (F0 %02x), request held 30 s (%d)\n" % (
                    node & 0x3F, data[1], self.enum_said))

    def handle(self, cmd, ident, p):
        self.counts[cmd] = self.counts.get(cmd, 0) + 1
        if cmd == 0x20:
            return frame(0x20, ident, bytes(self.version) + bytes([BOARD_REV & 0xFF]))
        if 0x10 <= cmd <= 0x1F:
            # A Spike 1/2 ("legacy") power distribution board never answers
            # its UART, so netbridge's HOST_Update answers these itself once
            # its probe has given up (POWERDIST_IsSpike3() == 0), read off the
            # unstripped firmware: 0x10 -> 3 zero bytes, 0x12 -> the line
            # frequency (u8, 0xff unknown), 0x15 -> 0xff, 0x19 -> the line
            # voltage (u16); the rest of 0x10..0x1f go unanswered there too.
            # Left unanswered, star_wars_2025_pro polled 0x12 and 0x19 every
            # loop, each waiting out its timeout: it drew at 0.5 fps.
            if cmd == 0x10:
                return frame(cmd, ident, bytes(3))
            if cmd == 0x12:
                return frame(cmd, ident, bytes([LINE_HZ & 0xFF]))
            if cmd == 0x15:
                return frame(cmd, ident, b"\xff")
            if cmd == 0x19:
                return frame(cmd, ident, struct.pack("<H", LINE_V & 0xFFFF))
            return None
        if cmd == 0x30:
            return frame(0x30, ident, struct.pack("<I", self.crc))
        if cmd == 0x25:
            # NODEBUS_Poll's binary search goes DOWN on every answer: it
            # returns the LOWEST node address raising a request (0: none) -
            # the attention poll, not a count. At boot it is the game's board
            # discovery (discover()); after that, switch requests only.
            a = self.discover()
            if a:
                return frame(0x25, ident, bytes([a]))
            a = self.attention()
            if a:
                self.att_said = getattr(self, "att_said", 0) + 1
                if self.att_said <= 40:
                    self.log.write("# [attention] node %d raises a request\n" % a)
            return frame(0x25, ident, bytes([a]))
        if cmd == 0x27:
            if p and p[0] in (0, 2):
                return frame(0x27, ident, bytes([LCD_STATUS]))
            return None
        if cmd == 0x41:
            if len(p) < 3:
                return None
            n = p[1]
            if len(p) < n + 3:
                return None
            reply_len = p[n + 2]
            self.note_enumeration(p[0], p[2:2 + n])
            if reply_len == 0:
                return None
            return frame(0x41, ident, self.node_exchange(p[0], p[2:2 + n], reply_len))
        return None


def close_coin_door(table, spi_in, log=None):
    """Start the run with the coin door SHUT, as a machine on location is and
    as the game window's keyboard has it (s3keys.py closes the interlock the
    moment the window attaches). The interlock is a CPU-board input on the
    SPI chain (node 0, index 23 = SPI bit 15, ACTIVE LOW), named COIN DOOR
    POWER INTERLOCK or COIN DOOR INTERLOCK by title. Left at rest it reads
    OPEN: 48V DISABLED, and on a slot with saved settings the game sat in
    attract ~56 s before it asked for a single node board - a headless run's
    first board at 66-69 s instead of ~10 (PAD-1142). PAD_S3_DOOR=open
    leaves it open. Returns the SPI bits closed."""
    if os.environ.get("PAD_S3_DOOR", "closed") == "open":
        return []
    bits = sorted({idx - 8 for name, (node, idx) in table.items()
                   if node == 0 and "DOOR" in name and "INTERLOCK" in name
                   and 0 <= idx - 8 < 64})
    if not bits:
        return []
    try:
        with open(spi_in, "r+b") as f:
            b = bytearray(f.read())
            bits = [s for s in bits if s // 8 < len(b)]
            for s in bits:
                b[s // 8] &= ~(1 << (s % 8)) & 0xFF
            f.seek(0)
            f.write(bytes(b))
    except OSError:
        return []
    if log and bits:
        log.write("# [door] coin door closed (SPI bit %s)\n" % ",".join(map(str, bits)))
    return bits


def write_switch_list(table, path):
    """The title's switches in the rig's switch_list.txt shape (`id num node
    bit name`, Spike 2's mktables.py), so the game window - padglhost, the
    Spike 2 renderer - binds its keys (flippers, Start, coins, the window-
    open trough and coin-door latch) by NAME to this title's switches. Ids
    are this list's own 1-based rows: s3keys.py reads them back from here.
    Returns [(id, node, bit, name)]."""
    rows = []
    for i, (name, (node, bit)) in enumerate(sorted(table.items(), key=lambda kv: (kv[1], kv[0]))):
        if i + 1 >= 256:                    # padsw.h PADSW_MAX_ID
            break
        rows.append((i + 1, node, bit, name))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("# id num node bit name - Spike 3 (s3bridge.py, from the device tables)\n")
        for sid, node, bit, name in rows:
            f.write("%d %d %d %d %s\n" % (sid, sid, node, bit, name))
    return rows


def read_switch_list(path):
    """{id: (node, bit, name)} from a write_switch_list() file."""
    out = {}
    with open(path) as f:
        for line in f:
            if line.startswith("#"):
                continue
            p = line.split(None, 4)
            if len(p) == 5:
                out[int(p[0])] = (int(p[2]), int(p[3]), p[4].strip())
    return out


def frames_in(buf):
    """Split complete frames off the front of buf: (frames, rest). Each frame
    is (cmd, id, payload, ok)."""
    out = []
    while True:
        s = buf.find(bytes([STX]))
        if s < 0:
            return out, b""
        e = buf.find(bytes([ETX]), s + 1)
        if e < 0:
            return out, buf[s:]
        raw, body, i = buf[s + 1:e], bytearray(), 0
        while i < len(raw):
            if raw[i] == ESC and i + 1 < len(raw):
                body.append(raw[i + 1] & 0x7F)
                i += 2
            else:
                body.append(raw[i])
                i += 1
        buf = buf[e + 1:]
        if len(body) >= 3:
            out.append((body[0], body[1], bytes(body[2:-1]), sum(body) & 0xFF == 0))


def main():
    import pty      # Linux only: the protocol above imports anywhere (tests)
    import tty
    d = sys.argv[1] if len(sys.argv) > 1 else "."
    elf = sys.argv[2] if len(sys.argv) > 2 else None
    log = open(os.path.join(d, "bridge.log"), "w", buffering=1)
    crc = 0
    if elf:
        try:
            crc = flash_crc(elf)
            log.write("# netbridge image %s (version %d.%d.%d), flash CRC32 %08x\n" % (
                (elf,) + fw_version(elf) + (crc,)))
        except (OSError, ValueError) as e:
            log.write("# no image CRC (%s): the game will want to reflash\n" % e)
    claims = {}
    game = sys.argv[3] if len(sys.argv) > 3 else None
    if game:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import s3nodes
            claims = s3nodes.derive(game)
            log.write("# node directory of %s: %s\n" % (game, " ".join(
                "%d=%s" % (n, c["type"]) for n, c in sorted(claims.items()))))
        except Exception as e:                       # a run without nodes still boots
            log.write("# no node directory (%s): every node will time out\n" % e)
    # PAD_S3_NODES_ABSENT=12,14: boards not fitted on this machine - they time
    # out as an empty address does (an optional board the title accepts as
    # missing, such as an accessory whose own checks the emulator cannot pass)
    absent = {int(x) for x in os.environ.get("PAD_S3_NODES_ABSENT", "").replace(",", " ").split() if x.isdigit()}
    for n in sorted(absent & set(claims)):
        log.write("# node %d (%s) not fitted\n" % (n, claims.pop(n)["type"]))
    br = Bridge(crc, log, claims)
    if elf:
        br.version = fw_version(elf)
    br.attach_inputs(os.path.join(d, "nodesw"))
    try:
        import s3motors
        br.steppers = s3motors.Steppers(br.sw, log)
        br.motors = s3motors.Motors(br.sw, log)
    except Exception as e:                           # no motors: status answers zeros
        log.write("# [stepper] no stepper model (%s)\n" % e)
    if game:
        try:
            devs5 = s3nodes.devices(s3nodes.Elf(game), with_location=True)
            br.set_polarity(s3nodes.active_low_masks(devs5))
            devs = [r[:4] for r in devs5]
            # every switch by name, for `s3press.py sw SLOT NAME` (logical
            # bits in nodesw; node 0 = the CPU board's SPI chain)
            import json
            table = {}
            for name, node, idx, cls in devs:
                if cls == "switch" and node >= 0:
                    table.setdefault(name.strip().upper(), [node, idx])
            with open(os.path.join(d, "switches.json"), "w") as f:
                json.dump(table, f, indent=0, sort_keys=True)
            write_switch_list(table, os.path.join(d, "tables", "game", "switch_list.txt"))
            close_coin_door(table, os.path.join(d, "spi.in"), log)
        except Exception as e:
            log.write("# [polarity] not derived (%s): every board active high\n" % e)
    if game and os.environ.get("PAD_S3_BALLS", "1") != "0":
        try:
            import s3balls
            br.balls = s3balls.Balls.for_game(game, br.sw, log, d)
        except Exception as e:                       # no model: switches by hand only
            log.write("# [ball] no ball model (%s)\n" % e)
    master, slave = pty.openpty()
    name = os.ttyname(slave)
    tty.setraw(master)
    tty.setraw(slave)
    os.chmod(name, 0o666)
    log.write("# s3bridge on %s\n" % name)
    with open(os.path.join(d, "bridge.path"), "w") as f:
        f.write(name)
    t0 = time.time()
    pend = b""
    seen = {}
    tally, last_tally = {}, [0.0]
    trace = (open(os.path.join(d, "nbtrace.log"), "w", buffering=1)
             if os.environ.get("PAD_S3_NBTRACE") == "1" else None)
    trace_last = {}
    # PAD-1090: lamps and coils for the virtual playfield (padled.h's block)
    leds = None
    if os.environ.get("PAD_S3_PADLED"):
        try:
            import s3leds
            leds = s3leds.PadLed(os.environ["PAD_S3_PADLED"])
            log.write("# padled: %s\n" % os.environ["PAD_S3_PADLED"])
        except Exception as e:                             # noqa: BLE001
            log.write("# padled: not published (%s)\n" % e)
    try:
        import s3rules
        br.rules = s3rules.Rules(br.sw, log, fire=leds.fire if leds else None)
    except Exception as e:                                 # noqa: BLE001
        log.write("# [rule] no rule model (%s): ruled coils never fire\n" % e)
    while True:
        r, _, _ = select.select([master], [], [], 0.05 if (br.balls or br.steppers or br.rules) else 0.5)
        if br.balls:
            br.balls.tick()
        if br.steppers:
            br.steppers.tick()
        if br.motors:
            br.motors.tick()
        if br.rules:
            br.rules.tick()
        if not r:
            continue
        try:
            data = os.read(master, 4096)
        except OSError:
            time.sleep(0.2)      # no slave open (yet): hold the pty
            continue
        pend += data
        got, pend = frames_in(pend)
        now = time.time() - t0
        for cmd, ident, p, ok in got:
            reply = br.handle(cmd, ident, p) if ok else None
            if leds and ok and cmd == 0x41 and len(p) >= 3 and p[0] & 0x40:
                leds.frame(p[0] & 0x3F, unmask(p[0], p[2:2 + p[1]]))
            if reply:
                os.write(master, reply)
            key = (cmd, p[:3] if cmd == 0x41 else p)
            seen[key] = seen.get(key, 0) + 1
            # every 30 s, how often each kind came (node+command for 0x41):
            # the first-three log alone cannot say what the game polls
            tally_k = ("%02x" % cmd) if cmd != 0x41 or len(p) < 3 else ("41:%02x:%02x" % (
                p[0], unmask(p[0], p[2:2 + p[1]])[0] if p[0] & 0x40 and p[1] else p[2]))
            tally[tally_k] = tally.get(tally_k, 0) + 1
            if now - last_tally[0] >= 30:
                log.write("%9.3f # tally %s\n" % (now, " ".join(
                    "%s=%d" % kv for kv in sorted(tally.items(), key=lambda x: -x[1])[:24])))
                tally.clear()
                last_tally[0] = now
            if trace and cmd == 0x41 and len(p) >= 3:
                # PAD_S3_NBTRACE=1: every node frame that differs from the
                # last one to the same node and command (coil traffic is a
                # few changed frames among thousands of repeats)
                n = p[1]
                plain = p[2:2 + n]
                if p[0] & 0x40:
                    plain = unmask(p[0], plain)
                # one stream per node+command (coil commands per coil too)
                tk = (p[0] & 0x3F, plain[:2] if plain[:1] and 0x40 <= plain[0] < 0x50 else plain[:1])
                if trace_last.get(tk) != plain:
                    trace_last[tk] = plain
                    trace.write("%9.3f n%-2d %s%s\n" % (
                        now, p[0] & 0x3F, plain.hex(" "), (" -> " + reply.hex()) if reply else ""))
            if seen[key] <= 3:       # the first few of each kind, then quiet
                log.write("%9.3f %s cmd %02x id %02x %s%s\n" % (
                    now, "rx" if ok else "BAD-SUM", cmd, ident, p.hex(),
                    (" -> " + reply.hex()) if reply else ""))


if __name__ == "__main__":
    main()
