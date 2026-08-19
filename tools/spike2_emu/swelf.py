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

★ 2026-08-19, aerosmith_le/avengers_infinity_le: SAME THREE STRUCTS, but ENT
has no root of its own on these titles - exhaustively checked, zero literal
references anywhere in the binary to any address that looks like the entry
table's start, unlike DEV/BRD, which both have one (found the same way: the
whole .data segment cross-referenced for a literal pointer to the candidate
array's own address - the identical trick that finds a device's NAME from a
pointer, run one level up, on the array instead of a string). The table is
still there, still runs right up to DEV, just reached only via
`dev - stride*count` arithmetic in the compiled code rather than through a
second global. `_ent_by_walkback()` derives it by walking backward from the
(already-dereferenced) DEV address; pass `None` as a title's entry-root in
ROOTS to use it. Validated against GROUND TRUTH, not just self-consistency:
avengers_infinity_le's derived table reproduces the real, standard Stern
switch numbers at their real ids - DIP 1..8 at num=1..8, SERVICE SELECT/PLUS/
MINUS/BACK at 9-12, COIN DOOR INTERLOCK at 25, LOCKDOWN BUTTON at 70, START
BUTTON at 73, TILT PENDULUM at 81 - the exact numbering scheme real Stern
manuals use across machines. No coincidental byte pattern reproduces a whole
manual's numbering by accident.

★ Same session, widened to 9 titles total (batman, foo_fighters_le,
guardians_le, iron_maiden_le, jurassic_park_le, mando_le, rush_le added
alongside the two above) by turning the method above into a repeatable
pipeline: derive the title's valid node set from `nbdir.py` (also static,
also no run), then DEV/BRD/ENT as above. Every one of the nine reproduces
the same real Stern numbering on LEFT/RIGHT FLIPPER BUTTON, TROUGH 1..6,
LEFT/RIGHT SLINGSHOT. Surveyed but NOT solved this pass - the device-name
table itself was found (same keyword fingerprint), but no literal reference
to its own address exists anywhere in the binary, so it could not be
trusted the way DEV/BRD are elsewhere: james_bond_le, king_kong_le,
led_zeppelin_le, metallica_spike, munsters_le, sword_of_rage_le, turtles_le,
uncanny_xmen_le, venom_le. Full detail and the discovery scripts' shape are
in plans/TODO.md under item 57.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# title -> (entry-array root, device-table root, board-table root).
# entry-array root is None where the title has no independent pointer to it -
# see _ent_by_walkback(). dev/board roots below are POINTER SLOTS (each has
# TWO in the binary that hold the same value; either works, one was picked),
# found by cross-referencing the whole .data segment for a literal reference
# to the array address itself - the same trick that finds a switch/LED name
# by its address, run one level up. Method and verification: item 57,
# 2026-08-18/19 (plans/TODO.md).
ROOTS = {
    "stranger_things_le": (0x724608, 0x7260b8, 0x725aac),
    "aerosmith_le": (None, 0x599f0c, 0x599eb8),
    "avengers_infinity_le": (None, 0x5fcc1c, 0x5fcbc8),
    "batman": (None, 0x6d8780, 0x6d8714),
    "foo_fighters_le": (None, 0x5be464, 0x5be410),
    "guardians_le": (None, 0x569e30, 0x569ddc),
    "iron_maiden_le": (None, 0x530c88, 0x530c34),
    "jurassic_park_le": (None, 0x62d248, 0x62d1f4),
    "mando_le": (None, 0x6591c4, 0x659170),
    "rush_le": (None, 0x5a1880, 0x5a182c),
}

# title -> (dev array address, brd array address). BOTH are the array's OWN
# address, not a pointer-slot to dereference (unlike ROOTS above) - neither
# has ever been found with a literal reference on these two titles, so there
# is no root variable to point at; the array address itself is trusted the
# same way ENT's walkback result is, by matching real Stern names at
# plausible slots rather than by a GOT-style reference.
#
# ★ 2026-08-19, sword_of_rage_le/munsters_le: these two fail the RUNTIME's
# own switch hunt too (`[swfind] no switch table yet ... (node,bit) not
# distinct`) - the exact failure class item 52 built this whole file for -
# so they are not a "different generation" the way the 48-byte-stride
# titles above turned out to be irrelevant noise; they need this file's
# fallback for real. Their DEV record is NOT the ROOTS-shape struct: the
# name pointer sits at the record's OWN start (+0), not +12, so `slot`/
# `bit`/`kind` land at +4/+6/+8 instead of +16/+18/+20. Found by scanning a
# wide offset window for a field that stayed small and repeated in blocks
# across many records (the tell that gave away the ORIGINAL struct's kind
# field too) - see `sor_decode.py`/`stride48_probe.py` in the item 57
# writeup for the discovery. Validated against real Stern names AND real
# Stern numbering has NOT been possible: no ENT-equivalent table exists for
# either title (walkback finds only garbage immediately before DEV; an
# exhaustive independent stride/shape search across `.data` found several
# candidate runs, none of which decode to real switch names through the
# confirmed DEV array). `swtable.py`'s own `read()` never uses `num` for
# anything (`for sid, _num, node, bit, name in rows` - the leading
# underscore is Python's "deliberately unused" convention), so ROWS_NONUM
# below serves the switches with a **placeholder num** rather than either a
# guessed one (this file's own rule: a wrong number is worse than an
# honestly missing one) or blocking on a table that plainly is not there.
#
# TRAP that cost real time finding this: the array's start is NOT always
# `min(hits)`. sword_of_rage_le's hit-address scan turns up two ISOLATED
# matches (1144 and 1560 bytes apart from each other and from the real run)
# before the true, densely-packed 24-byte-stride array begins - almost
# certainly one or two devices allocated separately from the main table.
# Blindly taking the minimum decoded record 0 plausibly ("FLAIL MOTOR OPTO
# 2") and then garbage from record 1 on, because record 1 under that wrong
# anchor was 1144 bytes into unrelated memory, not the array's real second
# entry. The tell was in data already on hand: stride_diag.py's own delta
# histogram for this title reported "delta=24 count=270, delta=1144
# count=1, delta=1560 count=1" - the two outlier deltas ARE the two
# isolated hits, and they should have been read as "skip past these," not
# shrugged off as noise. The fix: anchor on the first hit that begins an
# actually-dense run of 24-byte-stride neighbours, not the lowest address.
#
# ★ 2026-08-19, munsters_le: shares this title's exact DEV struct (same
# offsets, decodes just as cleanly), but its BRD table needed a DIFFERENT
# search - the bijective bare-address scan that found sword_of_rage_le's
# turned up nothing trustworthy here; the same scan restricted to addresses
# that have at least one literal reference elsewhere in `.data` (a much
# smaller, much cleaner universe - 6,858 candidates instead of every
# 4-byte-aligned offset in the segment) found exactly ONE with distinct
# valid nodes across slots 2-7, at a genuine TWO-reference root
# (0x5512e4 - the same "usually exactly 2" pattern every other confirmed
# root in this file has). One slot (5, the busiest by far - 92 of the
# title's DEV records - almost certainly the main lower-playfield board)
# read as 1032 instead of a plausible node, which is exactly 0x0408: a
# valid node (8, unused by any other slot) in the LOW byte with an
# unrelated nonzero flag byte sitting above it - a byte-width mismatch,
# not a wrong address. Confirmed by masking every slot's read to `& 0xFF`
# (harmless for the other 15 slots, whose values were already under 256)
# and rebuilding the full table: 103/103 rows named, all 18 ground-truth
# keyword rows (LEFT/RIGHT FLIPPER BUTTON, LEFT/RIGHT SLINGSHOT, TROUGH
# 1-6) land on node 8 - the slot the raw u16 read alone could not resolve.
ROOTS_NONUM = {
    "sword_of_rage_le": (0x5de4f4, 0x5db848),
    "munsters_le": (0x553f50, 0x5512e4),
}

NONUM_DEV_STRIDE = 24
NONUM_BOARD_STRIDE = 16
NUM_PLACEHOLDER = 0   # not a real Stern number - see ROOTS_NONUM's docstring

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


def _entry_ok(e, va, dev_bound):
    """Does a 44-byte record at `va` look like a plausible entry?

    Generous on purpose - this is used to WALK, not to validate a single
    guess, and a false accept just gets overwritten by the real boundary a
    few records later while a false reject cuts a real table short.
    """
    num = e.u16(va + 24)
    devidx = e.u16(va + 26)
    return num is not None and devidx is not None and 0 <= devidx < dev_bound and num < 1024


def _ent_by_walkback(e, dev, dev_bound=2048, min_count=16):
    """Derive the entry table's address when it has NO root of its own.

    ★ aerosmith_le/avengers_infinity_le, 2026-08-19: titles where the entry
    table is never referenced by an independent GOT-style pointer anywhere in
    the binary (checked exhaustively - zero literal references to any
    candidate address), unlike `dev_root`/`brd_root`, which both are. The
    entry table still sits immediately before the device table in memory
    ("runs right up to" it, same as when a root exists) - the compiler
    apparently reaches it only via `dev - stride*count` arithmetic, with no
    separate global holding its own address. So: walk backward from the
    ALREADY-DEREFERENCED `dev` address at ENTRY_STRIDE until a record stops
    looking plausible, and the far end of that run is the table's start.

    VALIDATED on both titles against ground truth, not just self-consistency:
    avengers_infinity_le's derived table reproduces the REAL, standard Stern
    switch numbers at their real ids - DIP 1..8 at num=1..8, SERVICE SELECT/
    PLUS/MINUS/BACK at 9-12, COIN DOOR INTERLOCK at 25, LOCKDOWN BUTTON at 70,
    START BUTTON at 73, TILT PENDULUM at 81 - the same numbering scheme real
    Stern manuals use across machines, which no coincidental byte pattern
    would reproduce this exactly. `dev_bound` is deliberately generous (the
    real device count is not known yet at this point in the walk); `min_count`
    guards against accepting a short run of coincidental noise as the table.
    """
    va = dev - ENTRY_STRIDE
    n = 0
    while _entry_ok(e, va, dev_bound):
        n += 1
        va -= ENTRY_STRIDE
    return (va + ENTRY_STRIDE) if n >= min_count else None


def _rows_nonum(e, dev, brd, max_dev=400):
    """ROOTS_NONUM's reader - see its docstring for why this struct and this
    title bucket exist. No ENT indirection at all: DEV is walked directly by
    index (there is no separate entry id/num layer to go through), each
    record's own index doubles as `id`, and `num` is NUM_PLACEHOLDER.

    Bounded by `max_dev` and stopped early the moment a record's `kind`
    field cannot be read at all (`None`) - that is the array running off
    the mapped segment, the same end-of-table signal `rows()` gets for free
    from ENT's span check on the ROOTS path.

    Node is masked to its low byte (`& 0xFF`) - see `ROOTS_NONUM`'s
    munsters_le note: one slot's raw u16 read carries an unrelated nonzero
    flag in its high byte, and the node itself is the byte below it. Every
    OTHER slot on both titles in this bucket was already under 256, so the
    mask is a no-op for them - this is a generalisation, not a special case
    bolted onto one title.
    """
    slot_node = {}
    for s in range(16):
        n = e.u16(brd + NONUM_BOARD_STRIDE * s + 14)
        if n is None:
            break
        slot_node[s] = n & 0xFF

    out = []
    for i in range(max_dev):
        base = dev + NONUM_DEV_STRIDE * i
        kind = e.u16(base + 8)
        if kind is None:
            break
        if kind != KIND_SWITCH:
            continue
        slot = e.u16(base + 4)
        bit = e.u16(base + 6)
        node = slot_node.get(slot)
        if node is None or node > 63 or bit is None or bit > 255:
            continue
        p1 = e.u32(base)
        p2 = e.u32(p1) if p1 else None
        name = e.cstr(p2) if p2 else None
        out.append((i, NUM_PLACEHOLDER, node, bit, name or "?"))

    named = sum(1 for r in out if r[4] != "?")
    if len(out) < 16 or named < len(out) // 2:
        return []
    return out


def rows(elf_path, title):
    """[(id, num, node, bit, name)] - the same tuples swtable.read() returns.

    [] for a title with no recorded roots, and [] rather than a partial table if
    any structural self-check fails.
    """
    roots = ROOTS.get(title)
    nonum_roots = ROOTS_NONUM.get(title)
    if not roots and not nonum_roots:
        return []
    try:
        e = Elf(elf_path)
    except (OSError, struct.error):
        return []
    if nonum_roots:
        dev_addr, brd_addr = nonum_roots
        return _rows_nonum(e, dev_addr, brd_addr)
    ent_root, dev_root, brd_root = roots
    dev = e.u32(dev_root)
    brd = e.u32(brd_root)
    if not dev or not brd:
        return []
    # ent_root is None for titles with no independent pointer to the entry
    # table - see _ent_by_walkback(). A real root is dereferenced as usual.
    ent = _ent_by_walkback(e, dev) if ent_root is None else e.u32(ent_root)
    if not ent or dev <= ent:
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
