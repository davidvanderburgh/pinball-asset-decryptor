"""Node-bus responder for the EARLY Spike 1 firmware era (the 2012 home models:
Transformers The Pin — PAD-101).

Same job as :mod:`nodebus` — sit on the pty bound at the guest's /dev/ttyS4
and be the machine's node board — for a wire protocol five years older than
the one nodebus.py speaks.  Everything below was read out of the game binary
(``gamer``, ``node_pdi.cpp`` per its assert strings), not guessed; the function
names are the ELF's own.

WIRE FORMAT (node_sar_t = serial_write + node_read_serial, NO checksum, NO
reply-length byte — the reply length is implied by the command):

    poll            0x00                              -> 1 byte: node with
                                                          switch data, 0 = none
                    (node_poll_t; the game then queries THAT node)
    switch read     [0x80|node, 0x01, 0x11]           -> 8 bytes, ACTIVE-HIGH
                    (node_query_t -> node_switch_setdata; node_switch_update
                    ORs each raw bit straight into g_switch_data_internal, so
                    bit set == closed.  The 2015 firmware is the other way.)
    status          [0x80|node, 0x01, 0xFF]           -> 6 bytes; [0..1] is a
                    LE16 error mask, printed as "NODE %d ERROR %d" per bit
                    (node_status_t) — all zero == healthy
    quadrature      [0x80|node, 0x03, 0x60, a, b]     -> 1 byte: signed delta
                    (node_query_quadrature; a spinner/encoder — none here)
    coil            [0x80|node, 0x05, 0x40|coil, p1, p2, p3, p4]   no reply
                    (node_coilmsg)
    lamps           [0x80|node, n+1, 0x80|c, d0..dn]                no reply
                    (node_ledmsg)

The SETTINGS EEPROM (64 bytes: sys_eep_init reads them one by one, then
sys_eep_checksum_check wants (3 + sum of all 64) % 256 == 0) lives on the
NET BRIDGE, reached with the same serial port in "command mode" (a GPIO the
game flips around each access — sys_command_mode).  Its frames start 0x55:

    read            [0x55, 0x00, 0x02, hi, lo, ck, x]  (7 bytes; x is junk)
                    -> [0xAA, 0x01, data, 0xFF - data]  (LL_sys_eep_read)
    write           [0x55, 0x01, 0x03, hi, lo, val, ck] (7 bytes)
                    -> [0xAA, 0x00, 0x00]               (LL_sys_eep_write)

Topology: nodemap_init registers ONE node-bus board, node 8 (plus GPIO
switches on the CPU board), and g_max_node_address bounds the status
round-robin, so a responder that answers for node 8 is the whole machine.

Switch injection reuses the viewer/keeper bitmaps (S1_SW_INPUT / S1_SW_AUTO,
see nodebus.read_injected_switches) — the same slot = node*64 + index — with
the polarity flipped for this era.

Usage (nodebus.py delegates here when S1_ERA=early; same argv):
    python3 nodebus.py <slave-path-out-file> <capture-file> [log-file]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nodebus import read_injected_switches  # noqa: E402

NODE = 8                     # the one node-bus board (nodemap_init)
EEP_SIZE = 64                # sys_eep_init reads exactly 0x40 bytes
SW_IDLE_HIGH = b"\x00" * 8   # active-high: nothing pressed
STATUS_OK = b"\x00" * 6      # error mask 0 == no NODE %d ERROR lines
BRIDGE = 0x55
BRIDGE_ACK = 0xAA


def active_high(active_low_bytes):
    """nodebus's active-low switch bytes -> this era's active-high ones."""
    return bytes((~b) & 0xFF for b in active_low_bytes)


class Eeprom:
    """The 64-byte settings EEPROM on the net bridge, persisted so the game's
    own defaults (written once the checksum fails on a blank part) survive
    a restart — and so a later boot passes sys_eep_checksum_check."""

    def __init__(self, path):
        self.path = path
        self.data = bytearray(EEP_SIZE)
        try:
            with open(path, "rb") as f:
                blob = f.read(EEP_SIZE)
            self.data[:len(blob)] = blob
        except OSError:
            pass

    def read(self, addr):
        return self.data[addr] if 0 <= addr < EEP_SIZE else 0xFF

    def write(self, addr, val):
        if not 0 <= addr < EEP_SIZE:
            return False
        self.data[addr] = val & 0xFF
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(bytes(self.data))
            os.replace(tmp, self.path)
        except OSError:
            pass
        return True


class EarlyParser:
    """Incremental parser for the early wire format.  ``feed(data)`` yields:

      ("poll",)
      ("bridge", sub, payload)          the 0x55 command-mode frames
      ("frame", node, cmd, data)        an addressed node frame
      ("junk", byte)                    a byte no frame starts with
    """

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data):
        self.buf += data
        while self.buf:
            b0 = self.buf[0]
            if b0 == 0x00:
                del self.buf[0]
                yield ("poll",)
                continue
            if b0 == BRIDGE:
                if len(self.buf) < 7:
                    return
                frame = bytes(self.buf[:7])
                del self.buf[:7]
                yield ("bridge", frame[1], frame[3:7])
                continue
            if b0 & 0x80:
                if len(self.buf) < 2:
                    return
                ln = self.buf[1]
                if ln == 0:
                    del self.buf[:2]
                    yield ("junk", b0)
                    continue
                if len(self.buf) < 2 + ln:
                    return
                body = bytes(self.buf[2:2 + ln])
                del self.buf[:2 + ln]
                yield ("frame", b0 & 0x7F, body[0], body[1:])
                continue
            del self.buf[0]
            yield ("junk", b0)


def reply_for(ev, switches, eeprom):
    """The bytes to send back for parsed event *ev*, or None."""
    kind = ev[0]
    if kind == "poll":
        return None                         # the caller decides the node
    if kind == "bridge":
        sub, payload = ev[1], ev[2]
        addr = (payload[0] << 8) | payload[1]
        if sub == 0x00:                     # LL_sys_eep_read
            val = eeprom.read(addr)
            return bytes([BRIDGE_ACK, 0x01, val, (0xFF - val) & 0xFF])
        if sub == 0x01:                     # LL_sys_eep_write
            ok = eeprom.write(addr, payload[2])
            return bytes([BRIDGE_ACK, 0x00, 0x00 if ok else 0x01])
        return None
    if kind == "frame":
        node, cmd, data = ev[1], ev[2], ev[3]
        if cmd == 0x11:
            return switches.get(node, SW_IDLE_HIGH)
        if cmd == 0xFF and not data:
            return STATUS_OK
        if cmd == 0x60:
            return b"\x00"
        return None
    return None


def main(argv=None):
    import termios
    argv = sys.argv[1:] if argv is None else argv
    slave_path_file, capture_file = argv[0], argv[1]
    log_file = argv[2] if len(argv) > 2 and argv[2] else None

    master, slave = os.openpty()
    slave_path = os.ttyname(slave)
    attrs = termios.tcgetattr(slave)
    attrs[0] = attrs[1] = attrs[3] = 0      # raw, no echo/canon/signals
    termios.tcsetattr(slave, termios.TCSANOW, attrs)
    with open(slave_path_file, "w") as f:
        f.write(slave_path + "\n")

    cap = open(capture_file, "wb", buffering=0)
    log = open(log_file, "w", buffering=1) if log_file else None

    def logline(s):
        if log:
            log.write(s + "\n")

    eeprom = Eeprom(os.environ.get("S1_EEP_FILE") or
                    os.path.join(os.path.dirname(capture_file), "s1eep.bin"))
    sw_input = os.environ.get("S1_SW_INPUT")
    sw_auto = os.environ.get("S1_SW_AUTO")
    logline("early-era responder up: node %d, eeprom %s" % (NODE, eeprom.path))

    def injected_now():
        """{node: active-high switch bytes} from the viewer + keeper files."""
        out = {}
        for src in (sw_input, sw_auto):
            for node, low in read_injected_switches(src).items():
                cur = out.get(node, SW_IDLE_HIGH)
                out[node] = bytes(a | b for a, b in zip(cur, active_high(low)))
        return out

    delivered = {}
    parser = EarlyParser()
    try:
        while True:
            try:
                data = os.read(master, 1 << 16)
            except OSError:
                break
            if not data:
                break
            cap.write(data)
            switches = injected_now()
            for ev in parser.feed(data):
                if ev[0] == "poll":
                    # name a node whose switches changed since the game last
                    # read them; otherwise 0 (nothing pending) — the game's
                    # scan loop polls until it gets 0 (node_serial_update_t)
                    pending = 0
                    for node in sorted(set(switches) | set(delivered)):
                        if switches.get(node, SW_IDLE_HIGH) != \
                                delivered.get(node, SW_IDLE_HIGH):
                            pending = node
                            break
                    os.write(master, bytes([pending]))
                    if pending:
                        logline("POLL -> node %d" % pending)
                    continue
                if ev[0] == "junk":
                    logline("junk byte 0x%02x" % ev[1])
                    continue
                resp = reply_for(ev, switches, eeprom)
                if ev[0] == "frame":
                    node, cmd, body = ev[1], ev[2], ev[3]
                    if cmd == 0x11:
                        delivered[node] = switches.get(node, SW_IDLE_HIGH)
                    tag = ("COIL" if 0x40 <= cmd < 0x80 else
                           "LAMP" if cmd >= 0x80 and cmd != 0xFF else "REQ")
                    logline("%s node=%d cmd=0x%02x data=%s -> %s"
                            % (tag, node, cmd, body.hex(),
                               resp.hex() if resp else "(no reply)"))
                else:
                    logline("BRIDGE sub=0x%02x payload=%s -> %s"
                            % (ev[1], ev[2].hex(),
                               resp.hex() if resp else "(no reply)"))
                if resp:
                    try:
                        os.write(master, resp)
                    except OSError as e:
                        logline("  write failed: %s" % e)
    finally:
        cap.close()
        if log:
            log.close()
        os.close(master)
        os.close(slave)
    return 0


if __name__ == "__main__":
    sys.exit(main())
