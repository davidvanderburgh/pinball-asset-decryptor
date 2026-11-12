#!/usr/bin/env python3
"""s3keys.py - the game window's keyboard and the virtual playfield, onto a
Spike 3 rig's switches, and the rig's switches back (PAD-1090, PAD-1183).

    s3keys.py SLOT PADSW_FILE SWITCH_LIST

The window is Spike 2's renderer (padglhost), and it publishes its keys
into the padsw.h block (PAD_SW_SHM) exactly as on a Spike 2 rig:

  held[id]     the KEYBOARD's switches, by the ids of SWITCH_LIST - the
               s3bridge-written switch_list.txt, so the window binds by the
               title's own names (flippers, Start, coins, the window-open
               trough and coin-door latch)
  scr_held[id] the scripts' (a virtual playfield)
  cab[8]       the cabinet buttons BY NAME, whatever the title's ids:
               LEFT RIGHT START ACTION SELECT PLUS MINUS BACK
  scr_cab[8]   the same, from the scripts

On Spike 2 the guest shim merges those; here this does, into the slot's
nodesw (s3bridge's live node inputs, LOGICAL: 1 = closed) and spi.in (the
CPU board's SPI chain, ACTIVE LOW: node 0 index i = SPI bit i - 8).

LAST EDGE WINS, PER SWITCH, as Spike 2's merge (PAD-1183). A switch moves
when ONE of the sources that name it changes, to that source's new level,
and is never re-asserted - the ball model and s3press.py write the same
switches, and a level rewritten 100 times a second would undo every ball
they move. It used to be the UNION of the sources, and that is wrong the
moment two disagree: padglhost latches the coin door shut and a full trough
in the keyboard's half at window open, so the playfield's door click (the
scripts' half going 1 -> 0) never opened the door at all.

THE SHIM'S OTHER JOBS ON SPIKE 2, done here for the same readers:

  mrg[id]      what the GAME is handed: every switch's live level, read back
               off nodesw / spi.in after the merge - so the window's dots, the
               trough and the key panel show what the ball model and the board
               rules did too, and padsw.set_confirmed can see a write land.
               guest_t0 is stamped at attach, which is what tells the helpers
               a game is there to take a write (padsw.merging).
  spin[id]     the RIP (right-hold on a spinner): the switch alternates every
               RIP_MS while it is set, an edge each time, so the game counts
               spins (Spike 2's shim flips it per scan).
  stop_*       the PAUSE (Pause / F9, either window): padglhost asks, as on a
               Spike 2 app run (PAD_PAUSE_KEEPER=1, pausekeep.py), and this -
               root, beside the game - SIGSTOPs / SIGCONTs the slot's game and
               answers with the count and the generation served. A frozen game
               is resumed if this exits.
"""
import mmap
import os
import signal
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(os.path.dirname(HERE), "spike2_emu"))
import s3bridge  # noqa: E402

BASE = "/var/tmp/pad-s3/slot%s"

# padsw.h, field by field (unsigned = 4 bytes, PADSW_MAX_ID = 256); padsw.py
# is the Python copy and tests/test_spike3_emu_bus.py pins these to it
MAGIC = 0x53444150
MAX_ID = 256
OFF_HELD = 8
OFF_SCR_HELD = 8 + 256 + 12 + 4
OFF_MRG_GEN = OFF_SCR_HELD + MAX_ID          # 536
OFF_MRG = OFF_MRG_GEN + 4                    # 540
OFF_GUEST_T0 = 804
OFF_SPIN = 812
OFF_CAB = 1068
OFF_SCR_CAB = OFF_CAB + 8
OFF_STOP_WANT = 1096
OFF_STOP_GEN = 1100
OFF_STOP_N = 1104
OFF_STOP_ACK = 1108
CAB_NAMES = ("LEFT", "RIGHT", "START", "ACTION", "SELECT", "PLUS", "MINUS", "BACK")
# the cabinet buttons' switches: by name where the title names them, the
# service cluster by its SPI bits (CPU indices 8..11 on every title)
CAB_SWITCH = {
    "LEFT": ("LEFT FLIPPER BUTTON", "L FLIPPER BUTTON"),
    "RIGHT": ("RIGHT FLIPPER BUTTON", "R FLIPPER BUTTON"),
    "START": ("START BUTTON",),
    "ACTION": ("ACTION BUTTON", "LOCKDOWN BUTTON", "FIRE BUTTON"),
    "SELECT": ("SERVICE SELECT",),
    "PLUS": ("SERVICE PLUS",),
    "MINUS": ("SERVICE MINUS",),
    "BACK": ("SERVICE BACK",),
}
#: a rip's half period: one edge this often while the spinner is held. The
#: game raises a scan per change at its ~100 Hz poll, so 30 ms is never missed
RIP_MS = float(os.environ.get("PAD_S3_RIP_MS") or 30)


def cab_targets(by_name):
    """{cab index: (node, bit)} from the title's switch names."""
    out = {}
    for i, cab in enumerate(CAB_NAMES):
        for n in CAB_SWITCH[cab]:
            if n in by_name:
                out[i] = by_name[n]
                break
    return out


def game_pids(slot):
    """The slot's game: comm `game` (the PAD_PIVOT copy of qemu, s3run.sh)
    whose root overlay's upper layer is this slot's - s3save.sh's rule, so a
    Pause in one rig never freezes another's."""
    want = "upperdir=%s/root.up," % (BASE % slot)
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open("/proc/%s/comm" % d) as f:
                if f.read().strip() != "game":
                    continue
            with open("/proc/%s/mountinfo" % d) as f:
                if any(" / / " in ln and want in ln for ln in f):
                    out.append(int(d))
        except OSError:
            pass
    return out


class Keys:
    def __init__(self, slot, padsw, switch_list):
        self.slot = slot
        self.sd = BASE % slot
        self.ids = s3bridge.read_switch_list(switch_list)
        by_name = {name.upper(): (node, bit) for node, bit, name in self.ids.values()}
        self.cab = cab_targets(by_name)
        self.padsw = padsw
        self.mm = None
        self.writable = False
        self.last = {}                       # (node, bit) -> closed, as last written
        self.src = None                      # source -> level, as last read
        self.mrg = None                      # the merged array as last published
        self.stop_seen = None                # stop_gen as last served
        self.frozen = []                     # pids this stopped

    def attach(self):
        if self.mm is None:
            for mode, acc in (("r+b", mmap.ACCESS_WRITE), ("rb", mmap.ACCESS_READ)):
                try:
                    with open(self.padsw, mode) as f:
                        self.mm = mmap.mmap(f.fileno(), 0, access=acc)
                    self.writable = acc == mmap.ACCESS_WRITE
                    break
                except (OSError, ValueError):
                    continue
            if self.mm is None:
                return False
        if struct.unpack_from("<I", self.mm, 0)[0] != MAGIC:
            return False
        if self.writable and not struct.unpack_from("<I", self.mm, OFF_GUEST_T0)[0]:
            # padsw.guest_ms's origin: CLOCK_MONOTONIC ms, as the shim's pad_ms
            struct.pack_into("<I", self.mm, OFF_GUEST_T0,
                             (time.monotonic_ns() // 1000000 - 1) & 0xFFFFFFFF or 1)
        return True

    def sources(self):
        """{source: (target (node, bit), level)} - every input the window's
        block carries, one entry per writer and switch."""
        m = self.mm
        out = {}
        for sid, (node, bit, _n) in self.ids.items():
            out[("h", sid)] = ((node, bit), bool(m[OFF_HELD + sid]))
            out[("s", sid)] = ((node, bit), bool(m[OFF_SCR_HELD + sid]))
        for i, nb in self.cab.items():
            out[("c", i)] = (nb, bool(m[OFF_CAB + i]))
            out[("sc", i)] = (nb, bool(m[OFF_SCR_CAB + i]))
        return out

    def wanted(self):
        """{(node, bit): closed} - the merge: on the first look the union of
        every source (what the window opened with: the door and trough
        latches), after that each switch follows the LAST source that moved."""
        src = self.sources()
        want = {}
        if self.src is None:
            for nb, on in src.values():
                want[nb] = want.get(nb, False) or on
        else:
            want = dict(self.want)
            for k, (nb, on) in src.items():
                if self.src.get(k) != on:
                    want[nb] = on
        self.src = {k: on for k, (_nb, on) in src.items()}
        self.want = want
        return want

    def spinning(self):
        """{(node, bit)} the window is ripping (padsw spin[])."""
        m = self.mm
        return {(node, bit) for sid, (node, bit, _n) in self.ids.items()
                if m[OFF_SPIN + sid]}

    def apply(self, node, bit, closed):
        if node == 0:                       # the CPU board: the SPI chain
            spi = bit - 8
            if not 0 <= spi < 64:
                return
            p = os.path.join(self.sd, "spi.in")
            with open(p, "r+b") as f:
                b = bytearray(f.read())
                if spi // 8 >= len(b):
                    return
                if closed:
                    b[spi // 8] &= ~(1 << (spi % 8)) & 0xFF
                else:
                    b[spi // 8] |= 1 << (spi % 8)
                f.seek(0)
                f.write(bytes(b))
            return
        if not 0 <= bit < 64:
            return
        p = os.path.join(self.sd, "nodesw")
        off = 8 * node + bit // 8
        with open(p, "r+b") as f:
            f.seek(off)
            v = f.read(1)[0]
            v = (v | (1 << (bit % 8))) if closed else (v & ~(1 << (bit % 8)) & 0xFF)
            f.seek(off)
            f.write(bytes([v]))

    def walking(self):
        """s3press.py autoguide is walking Guided Setup (SLOT/guided.state):
        the user's keys wait - a flipper pressed into the walk fought it, and
        the game's own menu auto-repeat ran away with it (David, PAD-1090)."""
        try:
            with open(os.path.join(self.sd, "guided.state")) as f:
                return f.read().strip() == "walking"
        except OSError:
            return False

    def step(self, now=None):
        """Apply every switch whose wanted state changed; returns the edges.
        Held back (not dropped) while Guided Setup is being walked: what the
        keys say once it is done is applied then."""
        if self.walking():
            return []
        now = time.monotonic() if now is None else now
        want = self.wanted()
        rip = self.spinning()
        if rip:
            phase = int(now * 1000 / RIP_MS) & 1 == 0
            want = dict(want)
            for nb in rip:
                want[nb] = phase
        edges = []
        for nb, on in want.items():
            if self.last.get(nb, False) != on:
                self.last[nb] = on
                self.apply(nb[0], nb[1], on)
                edges.append((nb, on))
        self.publish()
        return edges

    def live(self):
        """{(node, bit): closed} for every switch, off nodesw and spi.in as
        the bridge answers the game - whoever moved it."""
        try:
            with open(os.path.join(self.sd, "nodesw"), "rb") as f:
                nsw = f.read()
            with open(os.path.join(self.sd, "spi.in"), "rb") as f:
                spi = f.read()
        except OSError:
            return None
        out = {}
        for node, bit, _n in self.ids.values():
            if node == 0:
                i = bit - 8
                out[(node, bit)] = (0 <= i < 8 * len(spi)
                                    and not spi[i // 8] >> (i % 8) & 1)
            else:
                o = 8 * node + bit // 8
                out[(node, bit)] = (0 <= bit < 64 and o < len(nsw)
                                    and bool(nsw[o] >> (bit % 8) & 1))
        return out

    def publish(self):
        """mrg[]: what the game is handed, for the window and the helpers."""
        if not self.writable:
            return
        live = self.live()
        if live is None:
            return
        arr = bytearray(MAX_ID)
        for sid, (node, bit, _n) in self.ids.items():
            if 0 <= sid < MAX_ID:
                arr[sid] = 1 if live.get((node, bit)) else 0
        if arr == self.mrg:
            return
        self.mm[OFF_MRG:OFF_MRG + MAX_ID] = bytes(arr)
        struct.pack_into("<I", self.mm, OFF_MRG_GEN,
                         (struct.unpack_from("<I", self.mm, OFF_MRG_GEN)[0] + 1) & 0xFFFFFFFF)
        self.mrg = arr

    # ---- the Pause keeper ------------------------------------------------
    def pause_serve(self, pids=None):
        """Serve one padglhost stop request (stop_want / stop_gen), if a new
        one is waiting: SIGSTOP or SIGCONT the slot's game, then answer
        stop_n and stop_ack, in that order (padglhost reads the ack). Returns
        what was done, or None."""
        if not self.writable:
            return None
        gen = struct.unpack_from("<I", self.mm, OFF_STOP_GEN)[0]
        if self.stop_seen is None:
            # requests from before this attach are not replayed
            self.stop_seen = struct.unpack_from("<I", self.mm, OFF_STOP_ACK)[0]
        if gen == self.stop_seen:
            return None
        stop = bool(struct.unpack_from("<I", self.mm, OFF_STOP_WANT)[0])
        if stop:
            targets = game_pids(self.slot) if pids is None else pids
        else:
            targets = self.frozen or (game_pids(self.slot) if pids is None else pids)
        n = 0
        sig = getattr(signal, "SIGSTOP" if stop else "SIGCONT", None)
        for pid in targets if sig is not None else ():
            try:
                os.kill(pid, sig)
                n += 1
            except OSError:
                pass
        self.frozen = list(targets) if stop and n else []
        struct.pack_into("<I", self.mm, OFF_STOP_N, n)
        struct.pack_into("<I", self.mm, OFF_STOP_ACK, gen)
        self.stop_seen = gen
        return ("stop" if stop else "cont", n)

    def thaw(self):
        """Never leave the game frozen behind this process."""
        for pid in self.frozen:
            try:
                os.kill(pid, getattr(signal, "SIGCONT", signal.SIGTERM))
            except OSError:
                pass
        self.frozen = []


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    k = Keys(*sys.argv[1:4])
    print("[s3keys] %d switches, cabinet buttons %s" % (
        len(k.ids), {CAB_NAMES[i]: nb for i, nb in sorted(k.cab.items())}), flush=True)

    def bye(*_a):
        k.thaw()
        sys.exit(0)
    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    while not k.attach():
        time.sleep(0.5)
    print("[s3keys] window keyboard attached (%s%s)" % (
        k.padsw, "" if k.writable else ", read-only: no switch state back, no Pause"), flush=True)
    names = {(n, b): nm for n, b, nm in k.ids.values()}
    ripping = set()
    try:
        while True:
            rip = k.spinning()
            for nb in rip ^ ripping:
                print("%s [s3keys] %s %s" % (time.strftime("%H:%M:%S"),
                                             names.get(nb, "node %d bit %d" % nb),
                                             "ripping" if nb in rip else "rip ended"), flush=True)
            ripping = rip
            for (nb, on) in k.step():
                if nb in rip:
                    continue                 # a rip's edges are not news
                # wall-clock time: lines up with the bridge's [scan] trace and a
                # screen recording (PAD-1090: "one press, the menu ran away")
                print("%s [s3keys] %s %s" % (time.strftime("%H:%M:%S") + ".%03d" % (time.time() % 1 * 1000),
                                             names.get(nb, "node %d bit %d" % nb), "closed" if on else "open"),
                      flush=True)
            got = k.pause_serve()
            if got:
                print("%s [s3keys] pause: %s %d game process(es)" % (
                    time.strftime("%H:%M:%S"), "froze" if got[0] == "stop" else "resumed", got[1]),
                    flush=True)
            time.sleep(0.01)
    finally:
        k.thaw()


if __name__ == "__main__":
    sys.exit(main())
