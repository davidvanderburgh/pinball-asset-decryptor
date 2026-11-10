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
                f = open(self.padsw, "rb")
                self.mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            except (OSError, ValueError):
                return False
        return struct.unpack_from("<I", self.mm, 0)[0] == MAGIC

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

    def step(self):
        """Apply every switch whose wanted state changed; returns the edges."""
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
    while True:
        for (nb, on) in k.step():
            print("[s3keys] %s %s" % (names.get(nb, "node %d bit %d" % nb), "closed" if on else "open"),
                  flush=True)
        time.sleep(0.01)


if __name__ == "__main__":
    sys.exit(main())
