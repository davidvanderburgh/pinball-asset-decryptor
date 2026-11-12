#!/usr/bin/env python3
"""s3keys.py - the game window's keyboard, onto a Spike 3 rig's switches
(PAD-1090).

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

EDGES ONLY, as Spike 2's merge (last edge wins, per switch): a switch is
written when the union of the sources that name it CHANGES, and never
re-asserted - the ball model and s3press.py write the same switches, and a
level rewritten 100 times a second would undo every ball they move.

AND THE ANSWER GOES BACK (PAD-1181): mrg[id] / mrg_gen are what Spike 2's
guest shim publishes - the level each switch actually has - and every reader
of the block takes its switch state from there: the playfield window's
trough dots, its `balls 5/6 trough   lane 1   in play 0` line, Drain's
grey-out, the key panel's lit rows. Nothing on a Spike 3 run wrote it, so
the window fell back to the keyboard's own array: a trough forever full and
no ball ever in the shooter lane, whatever the ball model had moved. This
publishes the slot's live levels (nodesw, and spi.in for the CPU board's
switches) there, by the same switch ids.
"""
import mmap
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s3bridge  # noqa: E402

BASE = "/var/tmp/pad-s3/slot%s"

# padsw.h, field by field (unsigned = 4 bytes, PADSW_MAX_ID = 256)
MAGIC = 0x53444150
OFF_HELD = 8
OFF_SCR_HELD = 8 + 256 + 12 + 4
OFF_MRG_GEN = OFF_SCR_HELD + 256          # 536: the merged answer's generation
OFF_MRG = OFF_MRG_GEN + 4                 # 540: the merged answer, by switch id
MAX_ID = 256
OFF_CAB = 1068
OFF_SCR_CAB = OFF_CAB + 8
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


def cab_targets(by_name):
    """{cab index: (node, bit)} from the title's switch names."""
    out = {}
    for i, cab in enumerate(CAB_NAMES):
        for n in CAB_SWITCH[cab]:
            if n in by_name:
                out[i] = by_name[n]
                break
    return out


class Keys:
    def __init__(self, slot, padsw, switch_list):
        self.sd = BASE % slot
        self.ids = s3bridge.read_switch_list(switch_list)
        by_name = {name.upper(): (node, bit) for node, bit, name in self.ids.values()}
        self.cab = cab_targets(by_name)
        self.padsw = padsw
        self.mm = None
        self.last = {}                       # (node, bit) -> closed, as last written

    def attach(self):
        if self.mm is None:
            try:
                f = open(self.padsw, "r+b")
                self.mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_WRITE)
                self.writable = True
            except (OSError, ValueError):
                try:                                 # read-only: keys still work
                    f = open(self.padsw, "rb")
                    self.mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
                    self.writable = False
                except (OSError, ValueError):
                    return False
        return struct.unpack_from("<I", self.mm, 0)[0] == MAGIC

    def levels(self):
        """{id: closed} - every switch's live level on the slot: nodesw for
        the node boards (logical, 1 = closed), spi.in for the CPU board's
        (active low; node 0 index i = SPI bit i - 8)."""
        try:
            with open(os.path.join(self.sd, "nodesw"), "rb") as f:
                sw = f.read()
        except OSError:
            sw = b""
        try:
            with open(os.path.join(self.sd, "spi.in"), "rb") as f:
                spi = f.read()
        except OSError:
            spi = b""
        out = {}
        for sid, (node, bit, _n) in self.ids.items():
            if node == 0:
                b = bit - 8
                on = 0 <= b and b // 8 < len(spi) and not spi[b // 8] & (1 << (b % 8))
            else:
                o = 8 * node + bit // 8
                on = 0 <= bit < 64 and o < len(sw) and bool(sw[o] & (1 << (bit % 8)))
            out[sid] = bool(on)
        return out

    def publish(self):
        """The live levels into mrg[] (module docstring); bumps mrg_gen when
        one changed, and once at the start so readers switch over to it.
        True when it wrote."""
        if not getattr(self, "writable", False) or self.mm is None:
            return False
        m = self.mm
        changed = not struct.unpack_from("<I", m, OFF_MRG_GEN)[0]
        for sid, on in self.levels().items():
            if 0 < sid < MAX_ID and m[OFF_MRG + sid] != int(on):
                m[OFF_MRG + sid] = int(on)
                changed = True
        if changed:
            gen = struct.unpack_from("<I", m, OFF_MRG_GEN)[0]
            struct.pack_into("<I", m, OFF_MRG_GEN, (gen + 1) & 0xFFFFFFFF or 1)
        return changed

    def wanted(self):
        """{(node, bit): closed} - every switch the window's sources name."""
        m = self.mm
        want = {}
        for sid, (node, bit, _n) in self.ids.items():
            on = m[OFF_HELD + sid] or m[OFF_SCR_HELD + sid]
            want[(node, bit)] = want.get((node, bit), False) or bool(on)
        for i, nb in self.cab.items():
            if m[OFF_CAB + i] or m[OFF_SCR_CAB + i]:
                want[nb] = True
            else:
                want.setdefault(nb, False)
        return want

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

    def step(self):
        """Apply every switch whose wanted state changed; returns the edges.
        Held back (not dropped) while Guided Setup is being walked: what the
        keys say once it is done is applied then."""
        if self.walking():
            return []
        edges = []
        for nb, on in self.wanted().items():
            if self.last.get(nb, False) != on:
                self.last[nb] = on
                self.apply(nb[0], nb[1], on)
                edges.append((nb, on))
        return edges


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    k = Keys(*sys.argv[1:4])
    print("[s3keys] %d switches, cabinet buttons %s" % (
        len(k.ids), {CAB_NAMES[i]: nb for i, nb in sorted(k.cab.items())}), flush=True)
    while not k.attach():
        time.sleep(0.5)
    print("[s3keys] window keyboard attached (%s)" % k.padsw, flush=True)
    names = {(n, b): nm for n, b, nm in k.ids.values()}
    if not getattr(k, "writable", False):
        print("[s3keys] the block is read-only here: the window will not see the live switches",
              flush=True)
    n = 0
    while True:
        n += 1
        if n % 5 == 0:                       # 20 Hz: the window reads at 10
            k.publish()
        for (nb, on) in k.step():
            # wall-clock time: lines up with the bridge's [scan] trace and a
            # screen recording (PAD-1090: "one press, the menu ran away")
            print("%s [s3keys] %s %s" % (time.strftime("%H:%M:%S") + ".%03d" % (time.time() % 1 * 1000),
                                         names.get(nb, "node %d bit %d" % nb), "closed" if on else "open"),
                  flush=True)
        time.sleep(0.01)


if __name__ == "__main__":
    sys.exit(main())
