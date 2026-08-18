#!/usr/bin/env python3
"""swelf.py <game.elf> [title] - the switch list, READ STRAIGHT OUT OF THE ELF.

    swelf.py /home/david/i52/st_game stranger_things_le

WHY THIS EXISTS ALONGSIDE swtable.py. swtable.py reads the shim's `[sw]` dump
out of a run log, which is the right source when the shim can find the game's
switch table - and on stranger_things_le it cannot, and never could. The shim
hunts by SHAPE: sw_run_len()/sw_entry_ok() walk `base + k*32` and read the node
at +20 and the bit at +18, which is Godzilla Pro's record. stranger_things'
entries are 44 bytes and carry NEITHER field; node and bit live in a separate
device table. So the hunt is looking for a structure this title does not have,
the log never gets a `[sw]` line, switch_list.txt is never written, and the
virtual playfield window sits on "No tables for stranger_things_le yet" for
ever. That is not a timing problem and no amount of waiting fixes it.

It is all static, though. Three tables, all reachable from three .data roots:

    entry(id) = *(ENT) + 44*id      +24 u16 num      +26 u16 device index
    dev(i)    = *(DEV) + 24*i       +12 -> 5-language name cell (English first)
                                    +16 u16 slot     +18 u16 bit
                                    +20 u16 kind     (7 = switch)
    board(s)  = *(BRD) + 16*s       +14 u16 node id  (slot -> node)

HOW THIS WAS VALIDATED, because a table of numbers is easy to produce and hard
to trust. Three independent checks, all of which had to pass before it shipped:

  * David photographed stranger_things' TECH ALERTS screen, which named eight
    switches by NUMBER. All eight come out of this walk with the same number and
    the same name: #7 LEFT SLINGSHOT, #8 RIGHT SLINGSHOT, #9 LEFT FLIPPER
    BUTTON, #10 RIGHT FLIPPER BUTTON, #11 LEFT FLIPPER EOS, #12 RIGHT FLIPPER
    EOS, #15 TROUGH 6, #22 SHOOTER LANE - and all eight land on node 8.
  * An earlier pass established independently that ids 17..24 are DIP 1..DIP 8
    at NODE 0, BITS 0..7 and that id 25 is SERVICE SELECT at node 0 bit 8. This
    walk reproduces exactly that, through the slot->node indirection rather than
    by assuming it.
  * The entry table's length is not guessed. `ENT + 44*100 == DEV` exactly, so
    there are precisely 100 entries with id 0 a dummy. The count word the game
    itself uses lives in .bss and cannot be read statically at all.

ADDRESSES ARE PER-TITLE and there is no search here, so a title that is not in
ROOTS gets nothing rather than a plausible-looking table built from another
title's pointers. Everything below also self-checks - the slot must resolve to a
node, the kind must say switch, the name must decode - and rows() returns [] the
moment the shape disagrees. Producing an empty file is recoverable; producing a
wrong one sends the next reader somewhere that does not exist.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# title -> (entry-array root, device-table root, board-table root)
ROOTS = {
    "stranger_things_le": (0x724608, 0x7260b8, 0x725aac),
}

ENTRY_STRIDE = 44
DEV_STRIDE = 24
BOARD_STRIDE = 16
KIND_SWITCH = 7


class Elf:
    """Just enough ELF to turn a virtual address into a file offset.

    A single constant bias does NOT work here: this image has two PT_LOADs with
    different biases (0x8000 for the text segment, 0x10000 for the data one) and
    every pointer this walk follows lands in the second.
    """

    def __init__(self, path):
        self.d = open(path, "rb").read()
        d = self.d
        phoff = struct.unpack_from("<I", d, 0x1c)[0]
        phentsize = struct.unpack_from("<H", d, 0x2a)[0]
        phnum = struct.unpack_from("<H", d, 0x2c)[0]
        self.segs = []
        for i in range(phnum):
            o = phoff + i * phentsize
            typ, off, va, _pa, filesz = struct.unpack_from("<IIIII", d, o)
            if typ == 1 and filesz:
                self.segs.append((va, off, filesz))

    def off(self, va):
        for base, off, size in self.segs:
            if base <= va < base + size:
                return off + (va - base)
        return None

    def u32(self, va):
        o = self.off(va)
        return struct.unpack_from("<I", self.d, o)[0] if o is not None else None

    def u16(self, va):
        o = self.off(va)
        return struct.unpack_from("<H", self.d, o)[0] if o is not None else None

    def cstr(self, va, cap=80):
        o = self.off(va)
        if o is None:
            return None
        end = self.d.find(b"\x00", o, o + cap)
        if end < 0:
            return None
        raw = self.d[o:end]
        if not raw or any(c < 0x20 for c in raw):
            return None
        # names are UTF-8 on this title ("TRAP 'EM", "WHERE'S BARB?")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1")


def rows(elf_path, title):
    """[(id, num, node, bit, name)] - the same tuples swtable.read() returns.

    [] for a title with no recorded roots, and [] rather than a partial table if
    any structural self-check fails.
    """
    roots = ROOTS.get(title)
    if not roots:
        return []
    try:
        e = Elf(elf_path)
    except (OSError, struct.error):
        return []
    ent_root, dev_root, brd_root = roots
    ent = e.u32(ent_root)
    dev = e.u32(dev_root)
    brd = e.u32(brd_root)
    if not ent or not dev or not brd or dev <= ent:
        return []

    # The entry table runs right up to the device table - that is what bounds it.
    span = dev - ent
    if span % ENTRY_STRIDE:
        return []
    count = span // ENTRY_STRIDE
    if not 8 <= count <= 512:
        return []

    slot_node = {}
    for s in range(16):
        n = e.u16(brd + BOARD_STRIDE * s + 14)
        if n is None:
            break
        slot_node[s] = n

    out = []
    for sid in range(1, count):           # id 0 is a dummy with a null name
        base = ent + ENTRY_STRIDE * sid
        num = e.u16(base + 24)
        devidx = e.u16(base + 26)
        if num is None or devidx is None:
            return []
        dbase = dev + DEV_STRIDE * devidx
        if e.u16(dbase + 20) != KIND_SWITCH:
            continue                      # a coil or an LED sharing the table
        slot = e.u16(dbase + 16)
        bit = e.u16(dbase + 18)
        node = slot_node.get(slot)
        if node is None or node > 63 or bit is None or bit > 255:
            continue
        cell = e.u32(dbase + 12)
        name = e.cstr(e.u32(cell)) if cell else None
        out.append((sid, num, node, bit, name or "?"))

    # A handful of rows would mean the walk found something that merely looks
    # like the table. A real title has dozens.
    named = sum(1 for r in out if r[4] != "?")
    if len(out) < 16 or named < len(out) // 2:
        return []
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) > 2 else os.path.basename(
        os.path.dirname(os.path.abspath(path)))
    r = rows(path, title)
    if not r:
        print("no switch table recovered for %r" % title, file=sys.stderr)
        return 1
    import swtable
    sys.stdout.write(swtable.text(title, r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
