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


# --------------------------------------------------------------------------
# ★ THE 48-BYTE GENERATION, AND IT IS DERIVED - NO ADDRESS IS STORED FOR IT.
#
# Everything above is keyed on an address measured from ONE build of a title,
# and a new build of the SAME title moves every one of them. That is not
# hypothetical: munsters_le 1.28.0 and foo_fighters_le 1.04.0 both return
# nothing at all from the tables above, while 1.27.0 and 1.03.0 return 103 and
# 105 rows - which is what "the switch list is incomplete" in a 2026-09-07
# field report turned out to mean. An address table cannot be right about a
# build it has never seen, and this rig ships to people whose machines run
# newer code than anything on this disk.
#
# So this half finds the arrays by SHAPE and by the title's own declarations,
# and stores nothing per title. Measured on both new builds:
#
#     +0   u32  the switch NUMBER - the number in the Stern manual, which the
#               24-byte shape above does not carry at all (ROOTS_NONUM serves
#               NUM_PLACEHOLDER instead). This generation has it.
#     +4   u32  -> the English name, directly
#     +8   u32  -> the 5-language name cell (English first), as the old shape
#     +12  u32  }  one shared pointer, the same value on every record
#     +16  u32  }
#     +20  u16  slot (low)  u16 bit (high)
#     +24  u16  kind (low): 1 = switch, 2 = coil, 3 = lamp
#
# ★ KIND CHANGED VALUE. A switch is 7 in the old shape and 1 in this one, so a
# reader that kept the old constant and merely fixed the offsets would return a
# confident, wrong table of coils. That is why the anchor below is a NAME and
# not a field: the names are the one thing that did not move.
#
# HOW EACH ARRAY IS FOUND, and neither is a guess:
#
#   * THE DEVICE ARRAY, from a name every Spike 2 machine has. Find the string,
#     find the cell that points at it, find the record that points at the cell,
#     then walk out to both ends of the run of records whose own name cells
#     resolve. Nothing about the address is assumed - the array identifies
#     itself by containing LEFT SLINGSHOT.
#   * THE BOARD ARRAY (slot -> node), by item 57's method, which still works:
#     among the addresses something in the image holds a literal pointer to,
#     take the one whose table maps every slot the switches actually use to a
#     DISTINCT node that this title's own node directory declares. nbdir.py
#     supplies that node set from the same binary, so no run and no card is
#     involved. Measured: EXACTLY ONE address satisfies it on each of the two
#     titles - and on munsters_le 1.28.0 it is the same address, and the same
#     map, that the previous build's trusted switch list pins by name.
#
# The board struct itself did NOT change: 16-byte stride, node at +14, exactly
# as above. Only its address moved.
# --------------------------------------------------------------------------

GEN2_STRIDE = 48
GEN2_NUM, GEN2_CELL, GEN2_SLOTBIT, GEN2_KIND = 0, 8, 20, 24
GEN2_KIND_SWITCH = 1

#: ★ AND THE SAME ANCHOR FINDS THE OLDER SHAPES TOO, which matters because the
#: 48-byte generation is not the only one a new build moves out from under the
#: stored addresses. jurassic_park_le is in ROOTS and reads 107 rows on 1.15.0
#: and NOTHING on 1.16.0 - the 24-byte shape, same title, addresses all moved -
#: and nobody had reported it, because a title only looks broken once someone
#: runs the build that broke it. So the layout is a parameter and every known
#: shape is tried, in the order they were measured. Fields:
#:
#:      (stride, name cell, slot|bit word, kind word, the kind that means
#:       SWITCH, the offset of the real switch number or None)
#:
#: `slot` is the LOW half of the slot|bit word and `bit` the high half on all
#: three - the old readers spell those as two u16s at +16/+18 and +4/+6, which
#: is the same two halves of the same word.
DERIVED_LAYOUTS = (
    # the 48-byte generation: carries its own number
    dict(stride=48, cell=8, slotbit=20, kind=24, switch=1, num=0),
    # ROOTS' shape: number lives in the separate entry table, not the record
    dict(stride=24, cell=12, slotbit=16, kind=20, switch=7, num=None),
    # ROOTS_NONUM's shape: no number anywhere - see that table's docstring
    dict(stride=24, cell=0, slotbit=4, kind=8, switch=7, num=None),
)

#: Switch names every Spike 2 machine carries. More than one, so a title that
#: spells any single one differently still anchors.
GEN2_ANCHORS = (b"LEFT SLINGSHOT", b"RIGHT SLINGSHOT", b"SHOOTER LANE",
                b"TROUGH 1", b"LEFT FLIPPER BUTTON")


def _gen2_name(e, rec, lay=None):
    cell = e.u32(rec + (GEN2_CELL if lay is None else lay["cell"]))
    if not cell:
        return None
    first = e.u32(cell)
    return e.cstr(first) if first else None


def _gen2_words(e):
    """{value: [va, ...]} over the loaded image, in one pass.

    Only values that could be a pointer INTO the image are kept: on a title
    whose data segment is hundreds of megabytes (rush_le's is 184.6 MB) an
    index of every distinct word would cost more than the walk it serves.
    """
    lo = min(b for b, _o, _s in e.segs)
    hi = max(b + s for b, _o, s in e.segs)
    idx = {}
    for base, off, size in e.segs:
        for i in range(off, off + size - 4, 4):
            v = struct.unpack_from("<I", e.d, i)[0]
            if lo <= v < hi:
                idx.setdefault(v, []).append(base + (i - off))
    return idx


def _gen2_va_of(e, off):
    for base, o, size in e.segs:
        if o <= off < o + size:
            return base + (off - o)
    return None


def _gen2_find_dev(e, idx, lay):
    """(start, count) of the device array under `lay`, or None."""
    for anchor in GEN2_ANCHORS:
        off = e.d.find(anchor + b"\x00")
        if off < 0:
            continue
        sva = _gen2_va_of(e, off)
        if sva is None:
            continue
        for cell in idx.get(sva, []):
            for cellref in idx.get(cell, []):
                rec = cellref - lay["cell"]
                if _gen2_name(e, rec, lay) is None:
                    continue
                start = rec
                while _gen2_name(e, start - lay["stride"], lay) is not None:
                    start -= lay["stride"]
                n = 0
                while _gen2_name(e, start + n * lay["stride"], lay) is not None:
                    n += 1
                if n >= 32:
                    return start, n
    return None


def _gen2_find_board(e, idx, slots, nodes):
    """The board table, and ONLY if exactly one address qualifies.

    Two candidates means the evidence does not pick one, and this file's
    standing rule is that an honestly missing table beats a plausible wrong
    one - see ROOTS's docstring.
    """
    hit = None
    for va in idx:
        if e.off(va) is None:
            continue
        got = {}
        for s in slots:
            v = e.u16(va + BOARD_STRIDE * s + 14)
            if v is None or (v & 0xFF) not in nodes:
                got = None
                break
            got[s] = v & 0xFF
        if got and len(set(got.values())) == len(got):
            if hit is not None:
                return None
            hit = va
    return hit


def _rows_gen2(e):
    """The switch list, derived entirely - no stored address for this build.

    Every known record layout is tried and the FIRST that yields a coherent
    table wins. Coherent is not "decodes": the board table has to be the one
    and only referenced address that maps the slots these switches use into
    the node set the title's own directory declares, and enough rows have to
    come out named. A layout that half-fits produces nothing rather than a
    partial table, which is this file's standing rule.
    """
    try:
        import nbdir
        rx, rw = nbdir.load_segments(e.d)
        nodes = {nid for nid, _c in nbdir.find_node_directory(e.d, rx, rw)}
    except (OSError, SystemExit, ValueError, ImportError):
        return []
    if not nodes:
        return []
    idx = _gen2_words(e)
    for lay in DERIVED_LAYOUTS:
        out = _rows_for_layout(e, idx, nodes, lay)
        if out:
            return out
    return []


def _rows_for_layout(e, idx, nodes, lay):
    dev = _gen2_find_dev(e, idx, lay)
    if not dev:
        return []
    start, count = dev
    sw = []
    for i in range(count):
        r = start + i * lay["stride"]
        if (e.u16(r + lay["kind"]) or 0) != lay["switch"]:
            continue
        slot = e.u16(r + lay["slotbit"])
        bit = e.u16(r + lay["slotbit"] + 2)
        if slot is None or bit is None or bit > 255:
            continue
        num = e.u32(r + lay["num"]) if lay["num"] is not None else 0
        sw.append((i, num or 0, slot, bit, _gen2_name(e, r, lay) or "?"))
    if len(sw) < 16:
        return []
    brd = _gen2_find_board(e, idx, sorted({s[2] for s in sw}), nodes)
    if brd is None:
        return []
    slot_node = {}
    for s in range(16):
        n = e.u16(brd + BOARD_STRIDE * s + 14)
        if n is None:
            break
        slot_node[s] = n & 0xFF
    out = [(i, num, slot_node[slot], bit, name)
           for i, num, slot, bit, name in sw if slot in slot_node]
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
    try:
        e = Elf(elf_path)
    except (OSError, struct.error):
        return []
    # THE DERIVED READER RUNS LAST, AND ONLY WHEN THE ADDRESSES FAIL. Every
    # title that works today keeps the exact table it has always produced -
    # the stored addresses are a measurement of that build and nothing here
    # second-guesses them. It is a NEW BUILD, whose addresses have all moved,
    # and a title that was never in the tables at all, that reach this.
    if nonum_roots:
        out = _rows_nonum(e, *nonum_roots)
        return out or _rows_gen2(e)
    if not roots:
        return _rows_gen2(e)
    return _rows_roots(e, roots) or _rows_gen2(e)


def _rows_roots(e, roots):
    """The address-keyed reader: exactly what this file has always done for a
    title whose build the stored addresses were measured on."""
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
