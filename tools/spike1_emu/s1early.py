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
this era's polarity: a switch is closed when its raw bit DIFFERS from the
wire's IDLE state (an all-zero reply held the volume button and the game sat on
"VOLUME: 27%").

**The idle state is per switch, and it must be read in PHYSICAL WIRE ORDER.**
The node map is laid out physically, but every entry names its DESTINATION —
``{u32 game-id byte, u8 game-id bit, u8 negative-logic flag, char name[48]}`` at
stride 0x38 — and ``g_switch_negative_logic_bitmask`` is indexed by GAME ID, not
by wire position.  Rebuilding that global from the entries' flags proves it:
game-id order reproduces the live ``e7 7b fd 01 cf 31 00 00`` exactly, physical
order is 30 bits out.  Reading the global and XORing it against the physical
bytes we put on the wire therefore INVERTED every switch whose two indexes
disagree — including SHOOTER LANE (physical 12, game id 10, true idle 0), which
the game then saw as permanently closed: a ball forever sitting in the shooter
lane, so it prompted PLUNGE BALL for ever (PAD-101).  So the idle mask is built
here from each entry's own flag, at its own physical position.  The switch
NAMES — this era keeps
each switch's name inside its own map entry (``SWITCH_START`` at byte 2 bit 5,
``SWITCH_TROUGH_1``…) — are read out of guest memory once the game is up
(:func:`sync_from_guest`), which also writes ``s1switches.json`` for the
switch window and the ball keeper, with the trough-eject coil taken from the
game's static coil table.  This is the early era's s1swmap.

Usage (nodebus.py delegates here when S1_ERA=early; same argv):
    python3 nodebus.py <slave-path-out-file> <capture-file> [log-file]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nodebus import read_injected_switches  # noqa: E402
from s1elf import _Elf  # noqa: E402
from s1swmap import Guest, NotReady, game_pid  # noqa: E402

NODE = 8                     # the one node-bus board (nodemap_init)
EEP_SIZE = 64                # sys_eep_init reads exactly 0x40 bytes
SW_IDLE_HIGH = b"\x00" * 8   # active-high: nothing pressed
STATUS_OK = b"\x00" * 6      # error mask 0 == no NODE %d ERROR lines
BRIDGE = 0x55
BRIDGE_ACK = 0xAA


def active_high(active_low_bytes):
    """nodebus's active-low switch bytes -> a set-bit-per-closed-switch mask."""
    return bytes((~b) & 0xFF for b in active_low_bytes)


def wire_bytes(closed_mask, wire_idle):
    """The 8 reply bytes for cmd 0x11: with nothing pressed the wire reads the
    idle mask; a closed switch flips its own bit."""
    return bytes(c ^ n for c, n in zip(closed_mask, wire_idle))


# ---- the game's own tables, read live -------------------------------------
NODE_MAP_ENTRY = 0x38            # per switch bit; 8 bits per byte, 8 bytes
COIL_ENTRY = 60                  # __coil_table stride (nodemap_init prints it)
COIL_NAME_OFF = 12
_NAME_PREFIX = "SWITCH_"


#: offsets inside a node-map entry (stride NODE_MAP_ENTRY, physical order)
_ENT_GID_BIT = 4          # u8: the destination bit within the game-id byte
_ENT_NEG = 5              # u8: 1 = this switch idles HIGH on the wire
_ENT_NAME = 6


def read_wire_idle(g, syms, node=NODE):
    """The 8 switch bytes meaning "nothing pressed", in PHYSICAL wire order.

    Built from each map entry's own negative-logic flag at its own physical
    position — NOT from g_switch_negative_logic_bitmask, which is indexed by
    game id and inverts every switch whose two indexes disagree (see above)."""
    base = g.u32(syms["g_nMessagesSent"] + 0x24 + node * 4)
    idle = bytearray(8)
    if not base:
        return bytes(idle)
    for phys in range(64):
        ent = g.read(base + phys * NODE_MAP_ENTRY, NODE_MAP_ENTRY)
        if not ent[_ENT_GID_BIT]:          # no destination: unused position
            continue
        if ent[_ENT_NEG]:
            idle[phys >> 3] |= 1 << (phys & 7)
    return bytes(idle)


def read_switch_names(g, syms, node=NODE):
    """{index: name} for *node*, index = byte*8 + bit, from the runtime switch
    map (node_switch_setdata's per-node pointer table at
    g_nMessagesSent + 0x24 + node*4; each bit's entry carries its name)."""
    base = g.u32(syms["g_nMessagesSent"] + 0x24 + node * 4)
    names = {}
    if not base:
        return names
    for byte in range(8):
        for bit in range(8):
            ent = g.read(base + (byte * 8 + bit) * NODE_MAP_ENTRY,
                         NODE_MAP_ENTRY)
            if not ent[_ENT_GID_BIT]:            # unused position
                continue
            raw = ent[_ENT_NAME:].split(b"\0")[0].decode("latin1", "replace")
            if raw.startswith(_NAME_PREFIX):
                raw = raw[len(_NAME_PREFIX):]
            name = raw.replace("_", " ").strip()
            if name:
                names[byte * 8 + bit] = name
    return names


def coils_named(elf, syms, *words):
    """[[node, coil], …] for every coil whose name in the game's static coil
    table (node, index, …, name at +12) carries all of *words*."""
    base = syms.get("__coil_table")
    out = []
    if not base:
        return out
    for i in range(48):
        try:
            ent = elf.read_vaddr(base + i * COIL_ENTRY, COIL_ENTRY)
        except ValueError:
            break
        name = ent[COIL_NAME_OFF:].split(b"\0")[0].decode("latin1", "replace")
        if all(w in name.upper() for w in words):
            out.append([int(ent[0]), int(ent[1])])
    return out


def trough_coils(elf, syms):
    """[[node, coil], …] for the trough-eject coil(s)."""
    return coils_named(elf, syms, "TROUGH", "EJECT")


def drop_target_slots(names):
    """The switch indexes of the drop targets themselves (not their reset)."""
    return {i for i, n in names.items()
            if n.upper().startswith("DROP TARGET") and "RESET" not in n.upper()}


class DropBank:
    """A drop-target bank: a hit target STAYS DOWN until the reset coil fires.

    A click in the switch window (or a keeper pulse) closes a switch for a
    fraction of a second, the way a ball brushes a standup.  A drop target is
    not a standup: once hit it lies down and its switch reads closed until the
    game pulses DROP TARGET RESET (coil 7 on Transformers The Pin) and the
    bank springs back up.  The game reads the targets' LEVEL
    (Megatron_GetNumDropTargetsDown), so without this the bank bounced back
    up on its own the moment the click ended — and with the targets held
    down, the reset re-fired seven times in a row and gave up (measured,
    PAD-235), because nothing ever answered it.

    Latches on the closed EDGE, so a target someone is still holding down
    after a reset reads closed through the hold, not through a re-latch."""

    def __init__(self, slots=(), reset_coils=()):
        self.slots = set(slots)
        self.reset_coils = set(reset_coils)
        self.down = set()
        self._prev = set()

    def feed(self, closed):
        """*closed*: the switch indexes injected closed right now."""
        now = closed & self.slots
        self.down |= now - self._prev
        self._prev = now

    def on_coil(self, coil):
        """True when *coil* is the bank's reset (and the bank stood up)."""
        if coil not in self.reset_coils:
            return False
        self.down.clear()
        return True


def mask_indexes(mask):
    """8 closed-bit bytes -> the set of closed switch indexes."""
    return {b * 8 + i for b in range(len(mask)) for i in range(8)
            if mask[b] & (1 << i)}


def indexes_mask(idx):
    out = bytearray(8)
    for i in idx:
        if 0 <= i < 64:
            out[i >> 3] |= 1 << (i & 7)
    return bytes(out)


# ---- the switch window's view of the machine (s1hw.state) ------------------
def _load_state_model():
    """spike1_emulate's HardwareState/StateBlock, loaded BY PATH: importing it
    through the package runs the plugin package's __init__, which pulls in
    the codec stack (Crypto…) the rig's python3 does not have (PAD-100)."""
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "..", "pinball_decryptor", "plugins",
                        "stern", "spike1_emulate.py")
    spec = importlib.util.spec_from_file_location("_s1emulate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


COIL_SHOW_S = 0.25       # a fired coil stays lit this long in the window
# The block holds nodes 0-15 (spike1_emulate.MAX_NODES); the bus addresses up
# to 31.  Ghostbusters LE has a board at 24, and its switch reads, written as
# switches[1536:1600] on the 1024-byte area, GREW the area by 64 bytes a time
# (a bytearray slice past the end appends) to 1600 - every lamp after it then
# sat 576 bytes on, three nodes up (PAD-979).  Nodes past the block are left
# out: no title names a switch, lamp or coil on one.
STATE_NODES = 16


class HwStateWriter:
    """Keeps s1hw.state — the block the switch window paints — in step with
    the wire: the switches the game is being told are closed, every lamp
    frame's levels, and the coils it fires.  Nothing wrote it in this era,
    so the window showed no lamp colour at all (PAD-235).

    Lamp frames (node_ledmsg) are ``[0x80|node, n+1, 0x80|c, d0..dn-1]``:
    channel *c* onward, one level byte per channel, 64 channels per node — so
    each byte is lamp (node, c+i) at that level, a mono lamp.  Written at most
    every *min_interval* seconds and only when something changed."""

    def __init__(self, path, min_interval=0.05, clock=None):
        import time
        self.path = path
        self.min_interval = min_interval
        self.clock = clock or time.monotonic
        m = _load_state_model()
        self._pack = m.StateBlock.pack
        self.state = m.HardwareState()
        self.coil_until = {}
        self.dirty = True
        self.seq = 0
        self.written_at = -1e9

    def set_switches(self, node, closed_idx):
        if not 0 <= node < STATE_NODES:
            return
        base = node * 64
        cur = self.state.switches[base:base + 64]
        new = bytearray(64)
        for i in closed_idx:
            if 0 <= i < 64:
                new[i] = 1
        if new != cur:
            self.state.switches[base:base + 64] = new
            self.dirty = True

    def lamp_frame(self, node, cmd, data):
        start = cmd & 0x7F
        if not 0 <= node < STATE_NODES:
            return
        for i, level in enumerate(data):
            ch = start + i
            if ch >= 64:
                break
            if self.state.get_lamp(node, ch) != (level, level, level):
                self.state.set_lamp(node, ch, level)
                self.dirty = True

    def coil_fire(self, node, coil):
        self.coil_on(node, coil, COIL_SHOW_S)

    # PAD-943: the DMD era's responder (nodebus.py) writes the block too, and
    # its wire says how long a coil is driven, so these take the time.
    def lamp_level(self, node, ch, level):
        """One mono lamp at *level* (a Spike 1 lamp has no colour)."""
        if 0 <= node < STATE_NODES and 0 <= ch < 64 and self.state.get_lamp(node, ch) != (level, level, level):
            self.state.set_lamp(node, ch, level)
            self.dirty = True

    def coil_on(self, node, coil, seconds):
        """A coil energized for *seconds* (None: until coil_off)."""
        if 0 <= node < STATE_NODES and 0 <= coil < 64:
            key = (node, coil)
            if seconds is None:
                self.coil_until.pop(key, None)
            else:
                self.coil_until[key] = self.clock() + seconds
            if not self.state.get_coil(node, coil):
                self.state.set_coil(node, coil, True)
                self.dirty = True

    def coil_off(self, node, coil):
        if 0 <= node < STATE_NODES and 0 <= coil < 64:
            self.coil_until.pop((node, coil), None)
            if self.state.get_coil(node, coil):
                self.state.set_coil(node, coil, False)
                self.dirty = True

    def flush(self, force=False):
        now = self.clock()
        for key, until in list(self.coil_until.items()):
            if now >= until:
                del self.coil_until[key]
                self.state.set_coil(key[0], key[1], False)
                self.dirty = True
        if not (self.dirty or force) or \
                (not force and now - self.written_at < self.min_interval):
            return False
        self.seq += 1
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(self._pack(self.state, self.seq))
            os.replace(tmp, self.path)
        except OSError:
            return False
        self.dirty = False
        self.written_at = now
        return True


def sync_from_guest(work, elf_path, out_path):
    """Read the negative-logic mask and the switch names from the running
    game and write *out_path* (the s1switches.json the window and keeper
    read).  Returns (negmask, names); raises NotReady until the game is up."""
    with open(elf_path, "rb") as f:
        elf = _Elf(f.read())
    syms = elf.syms
    g = Guest(game_pid(work))
    negmask = read_wire_idle(g, syms)
    names = read_switch_names(g, syms)
    if not names:
        raise NotReady("switch map not populated yet")
    doc = {"%d,%d" % (NODE, i): n for i, n in sorted(names.items())}
    doc["_trough_coils"] = trough_coils(elf, syms)
    doc["_drop_reset_coils"] = coils_named(elf, syms, "DROP", "TARGET", "RESET")
    doc["_wire_idle"] = negmask.hex()
    import json
    tmp = out_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1)
    os.replace(tmp, out_path)
    return negmask, names


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


def reply_for(ev, switches, eeprom, idle=SW_IDLE_HIGH):
    """The bytes to send back for parsed event *ev*, or None.  *switches* is
    {node: wire bytes} for nodes with a closed switch; *idle* is the wire
    bytes of an all-open node (the negative-logic mask once known)."""
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
            return switches.get(node, idle)
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

    work = os.path.dirname(capture_file)
    eeprom = Eeprom(os.environ.get("S1_EEP_FILE") or
                    os.path.join(work, "s1eep.bin"))
    sw_input = os.environ.get("S1_SW_INPUT")
    sw_auto = os.environ.get("S1_SW_AUTO")
    elf_path = os.environ.get("S1_GAME_ELF") or os.path.join(work, "game", "gamer")
    names_path = os.environ.get("S1_SWITCHES") or os.path.join(work, "s1switches.json")
    logline("early-era responder up: node %d, eeprom %s" % (NODE, eeprom.path))

    state = {"idle": SW_IDLE_HIGH, "synced": False, "next_sync": 0.0}
    bank = DropBank()
    try:
        hw = HwStateWriter(os.path.join(work, "s1hw.state"))
    except (OSError, ImportError, AttributeError) as exc:
        hw = None
        logline("s1hw.state: not written (%s)" % exc)
    import time

    def maybe_sync():
        if state["synced"] or time.monotonic() < state["next_sync"]:
            return
        state["next_sync"] = time.monotonic() + 2.0
        try:
            wire_idle, names = sync_from_guest(work, elf_path, names_path)
        except (NotReady, OSError, KeyError, ValueError) as exc:
            logline("sync: not yet (%s)" % exc)
            return
        state["idle"] = wire_idle
        state["synced"] = True
        logline("sync: wire idle %s (physical order), %d switches named -> %s"
                % (wire_idle.hex(), len(names), names_path))
        try:
            with open(elf_path, "rb") as f:
                elf = _Elf(f.read())
            resets = [c for n, c in coils_named(elf, elf.syms, "DROP",
                                                "TARGET", "RESET") if n == NODE]
        except (OSError, ValueError):
            resets = []
        bank.__init__(drop_target_slots(names), resets)
        if bank.slots:
            logline("drop targets %s latch down until coil %s fires"
                    % (sorted(bank.slots), resets))

    def injected_now():
        """{node: closed-bit mask} from the viewer + keeper files."""
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
            maybe_sync()
            closed = injected_now()
            bank.feed(mask_indexes(closed.get(NODE, SW_IDLE_HIGH)))
            if bank.down:
                closed[NODE] = bytes(
                    a | b for a, b in zip(closed.get(NODE, SW_IDLE_HIGH),
                                          indexes_mask(bank.down)))
            if hw:
                hw.set_switches(NODE, mask_indexes(closed.get(NODE,
                                                              SW_IDLE_HIGH)))
            switches = {n: wire_bytes(m, state["idle"])
                        for n, m in closed.items()}
            idle = wire_bytes(SW_IDLE_HIGH, state["idle"])
            for ev in parser.feed(data):
                if ev[0] == "poll":
                    # name a node whose switches changed since the game last
                    # read them; otherwise 0 (nothing pending) — the game's
                    # scan loop polls until it gets 0 (node_serial_update_t)
                    pending = 0
                    for node in sorted(set(switches) | set(delivered)):
                        if switches.get(node, idle) != delivered.get(node, idle):
                            pending = node
                            break
                    os.write(master, bytes([pending]))
                    if pending:
                        logline("POLL -> node %d" % pending)
                    continue
                if ev[0] == "junk":
                    logline("junk byte 0x%02x" % ev[1])
                    continue
                resp = reply_for(ev, switches, eeprom, idle)
                if ev[0] == "frame":
                    node, cmd, body = ev[1], ev[2], ev[3]
                    if cmd == 0x11:
                        delivered[node] = switches.get(node, idle)
                    tag = ("COIL" if 0x40 <= cmd < 0x80 else
                           "LAMP" if cmd >= 0x80 and cmd != 0xFF else "REQ")
                    if tag == "COIL" and any(body):   # all-zero = coil off
                        if node == NODE and bank.on_coil(cmd & 0x3F):
                            logline("drop targets reset: bank up")
                        if hw:
                            hw.coil_fire(node, cmd & 0x3F)
                    elif tag == "LAMP" and hw:
                        hw.lamp_frame(node, cmd, body)
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
            if hw:
                hw.flush()
    finally:
        cap.close()
        if log:
            log.close()
        os.close(master)
        os.close(slave)
    return 0


if __name__ == "__main__":
    sys.exit(main())
