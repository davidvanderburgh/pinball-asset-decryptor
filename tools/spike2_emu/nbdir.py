"""nbdir.py - read a title's NODE DIRECTORY out of its own game ELF, and emit
the per-node identity claims the shim should make on the node bus.

    python3 nbdir.py <game-elf> [--hexdir DIR] [--out FILE] [--check-godzilla]

WHY THIS FILE EXISTS. hwshim.c answers the game's 0xfe identity request from
nb_idents[], and that table is GODZILLA'S node set hard-coded - measured on one
title and claimed on every title, which its own comment calls out. On
star_wars_le (nodes 10/11/13/15 unknown to the table, node 12 a coil4node the
table claims as ws2812node) the game grades the claims against its own
firmware files, fails, shows "UPDATING NODE BOARD RUNTIME N / UPDATE FAILED"
over attract forever, and re-asks every board's identity in bursts of six for
the whole run (item 51's trace: 215-226 `fe` per node in five minutes).

THE TITLE DECLARES ITS OWN NODES, STATICALLY, IN THE GAME BINARY. Two
structures in the RW .data segment, found and decoded on star_wars_le and
godzilla_pro (item 51), godzilla's agreeing 100% with what hwshim measured
from game memory at runtime:

  NODE DIRECTORY - 16-byte records:
      u32 flags
      u32 handler      code pointer (RX segment); node-board records share
                       one handler, the CPU/bridge record has its own
      u32 name_cell    pointer to a 5-language name cell (RW segment)
      u32 w3           byte2 = NODE ID (0..63), low u16 = board-model CODE
  preceded by an all-zero sentinel record pointing at the "INVALID" cell.

  BOARD-MODEL CATALOG - 0x14-byte records:
      u32 type_name    pointer to "pinnode"/"ws2812node"/... (RX segment)
      u32 name_cell
      u32 flags
      u32 part_number  pointer to "520-XXXX-XX"
      u32 hash
  indexed by the directory's CODE MINUS 2 (two reserved entries precede it;
  validated on both titles: code 2 -> pinnode 520-6967 on both, and the CPU
  record's code lands on the SPIKE2 CPU entry on both).

POINTER BIASES, the trap that made this look like garbage on first read: the
RX LOAD segment maps file+0x8000, the RW LOAD segment maps file+0x10000 (both
read from the program headers here, never assumed). A pointer into .data
resolves with the RW bias; a pointer to a string resolves with the RX bias.

WHAT THE CLAIM MUST SATISFY (the game's grading, RE'd on godzilla and
annotated in hwshim.c 2728-2799): the claimed PART ID picks a CPU CLASS
(1 LPC1112_101, 2 LPC1112_201, 3 LPC1113_302, 4 LPC1124_303, 5 LPC1313,
6 LPC812, 7 RP235x); the game then wants ./<type>-<CLASS>-<its version>.hex
to exist, and compares the claimed firmware version and variant byte against
the DECRYPTED image (variant at flash 0x1008, version at 0x1009..0x100b). So
this file chooses, per node:
  - a class whose part id is KNOWN and whose <type>-<class>-*.hex the title
    actually ships (the known part ids are the three hwshim measured;
    claiming a class with an unknown part id would fail registration
    entirely, which is worse than a version mismatch);
  - the firmware version from THAT file's own filename (per node - the old
    nb_fw_title() took the first *.hex readdir returned, globally);
  - the variant from measured priors per type. pinnode 0x01, ws2812node
    0x05, node4 0x98 are measured (godzilla's [nbhex] dump); anything else
    defaults to 0x01 and is MARKED "guess" in the output. The shim logs
    identity refusals per node, so a wrong guess names itself in one run.

Output (default $PAD_TABLES-style tables dir is the caller's business; this
writes wherever --out points):

    # nbdir v1 elf=<basename> nodes=<n>
    node=1 type=pinnode code=2 part=0x00020023 class=1 variant=0x01 fw=0x011d00 hexver=1.29.0 name=CABINET
    ...
    # skipped node=5 type=magsensornode reason=no-usable-class

The shim (hwshim.c) reads this through /dump/tables/<PAD_GAME>/node_ident.txt
inside the guest and falls back to the built-in godzilla table when absent -
so a title with no derived table behaves exactly as before this file existed.
"""
import io
import os
import re
import struct
import sys

# Known type-name strings (the game's own 43-entry type table carries these;
# search anchors, not an exhaustive claim about what exists).
TYPE_NAMES = [
    b"pinnode", b"ws2812pinnode", b"ws2812node", b"coil4_lednode",
    b"coil4node", b"lcdnode", b"hdminode", b"hdmi_ws2812node", b"afnode",
    b"magsensornode", b"node4", b"tmc2590node", b"tmc5041node", b"netbridge",
]

# MCU part ids the game's 28-entry descriptor table recognises, of the ones
# hwshim has MEASURED (claiming an unmeasured id risks failing registration,
# which is strictly worse than a graded mismatch). class index per hwshim.c.
PART_BY_CLASS = {
    1: 0x00020023,   # LPC1112_101  (pinnode et al)
    4: 0x00140040,   # LPC1124_303  (node4)
    5: 0x2C40102B,   # LPC1313      (ws2812node, coil4node, ...)
}
CLASS_NAMES = {1: "LPC1112_101", 2: "LPC1112_201", 3: "LPC1113_302",
               4: "LPC1124_303", 5: "LPC1313", 6: "LPC812", 7: "RP235x"}
CLASS_BY_NAME = {v: k for k, v in CLASS_NAMES.items()}

# Measured variants per type (godzilla [nbhex] dump, via hwshim nb_idents[]).
# Everything else is a GUESS the output marks as one.
VARIANT_PRIOR = {"pinnode": 0x01, "ws2812node": 0x05, "node4": 0x98}
VARIANT_DEFAULT = 0x01

# Class preference PER TYPE, measured pair first: the variant byte lives
# INSIDE the per-class image, and the priors above were measured against
# these exact (type, class) pairs on godzilla - substituting another class
# whose file also happens to ship would grade the prior against an image
# nobody has read. Unlisted types fall back to (5, 1, 4).
CLASS_PREF = {
    "pinnode":    (1, 5),
    "ws2812node": (5,),
    "node4":      (4,),
    "coil4node":  (5, 1),
}
CLASS_PREF_DEFAULT = (5, 1, 4)

# node4's image reports a version that is not the filename's (124.107.0 for
# LPC1124_303 on godzilla, reproduced not corrected in hwshim). Claim the
# measured internal version for node4 boards; the refusal detector will say
# if another title's node4 image disagrees.
NODE4_FW_AS_READ = 0x7C6B00


def load_segments(elf):
    """(rx, rw) as (file_off, file_size, vaddr) triples from program headers."""
    if elf[:4] != b"\x7fELF":
        raise SystemExit("not an ELF: %r" % elf[:4])
    if elf[4] != 1:
        raise SystemExit("not ELF32")
    e_phoff, = struct.unpack_from("<I", elf, 28)
    e_phentsize, e_phnum = struct.unpack_from("<HH", elf, 42)
    rx = rw = None
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsize
        p_type, p_offset, p_vaddr, _pa, p_filesz, _msz, p_flags, _al = \
            struct.unpack_from("<8I", elf, o)
        if p_type != 1:          # PT_LOAD
            continue
        if p_flags & 2:          # writable -> RW (.data)
            rw = (p_offset, p_filesz, p_vaddr)
        else:                    # RX (text + rodata)
            rx = (p_offset, p_filesz, p_vaddr)
    if not rx or not rw:
        raise SystemExit("missing LOAD segment (rx=%r rw=%r)" % (rx, rw))
    return rx, rw


def va_to_off(va, seg):
    off, size, base = seg
    if base <= va < base + size:
        return off + (va - base)
    return None


def in_seg(va, seg):
    return va_to_off(va, seg) is not None


def cstr(elf, off, cap=64):
    end = elf.find(b"\0", off, off + cap)
    if end < 0:
        return None
    s = elf[off:end]
    try:
        return s.decode("ascii")
    except UnicodeDecodeError:
        return None


def find_catalog(elf, rx, rw):
    """The board-model catalog: 0x14-stride records whose word0 points at a
    type-name string. Returns (base_file_off, entries) where entries[i] is the
    resolved type name or a part-number-bearing placeholder."""
    # All file offsets of known type-name strings, as their RX virtual addrs.
    anchors = {}
    for t in TYPE_NAMES:
        start = rx[0]
        while True:
            i = elf.find(t + b"\0", start, rx[0] + rx[1])
            if i < 0:
                break
            # left boundary: previous byte NUL or segment start, so
            # "ws2812pinnode" does not also anchor as "pinnode"
            if i == 0 or elf[i - 1] == 0:
                anchors[rx[2] + (i - rx[0])] = t.decode()
            start = i + 1
    if not anchors:
        raise SystemExit("no type-name strings in RX segment")

    # Scan RW for runs of 0x14-stride records with word0 in anchors.
    best = None
    data_lo, data_n = rw[0], rw[1]
    for off in range(data_lo, data_lo + data_n - 0x14, 4):
        va0, = struct.unpack_from("<I", elf, off)
        if va0 not in anchors:
            continue
        # walk backwards to the run's start
        base = off
        while base - 0x14 >= data_lo:
            v, = struct.unpack_from("<I", elf, base - 0x14)
            if v in anchors or _plausible_cat_entry(elf, base - 0x14, rx, rw):
                base -= 0x14
            else:
                break
        # walk forwards to the end
        end = off
        while end + 0x14 <= data_lo + data_n - 0x14:
            v, = struct.unpack_from("<I", elf, end + 0x14)
            if v in anchors or _plausible_cat_entry(elf, end + 0x14, rx, rw):
                end += 0x14
            else:
                break
        n = (end - base) // 0x14 + 1
        if n >= 8 and (not best or n > best[1]):
            best = (base, n)
        if best and off > best[0] + best[1] * 0x14:
            break
    if not best:
        raise SystemExit("no board-model catalog found")
    base, n = best
    entries = []
    for i in range(n):
        va0, = struct.unpack_from("<I", elf, base + i * 0x14)
        entries.append(anchors.get(va0))
    return base, entries


def _plausible_cat_entry(elf, off, rx, rw):
    """A catalog row whose type-name pointer is not one of the known anchors
    (reserved rows, CPU row): word0 and word3 look like RX string pointers,
    word1 like an RW pointer."""
    w0, w1, _f, w3, _h = struct.unpack_from("<5I", elf, off)
    return (in_seg(w0, rx) and in_seg(w1, rw) and
            (w3 == 0 or in_seg(w3, rx)))


def find_node_directory(elf, rx, rw):
    """Runs of 16-byte records {flags, handler(RX), name_cell(RW), w3} where
    byte2 of w3 is a node id < 64. Node records share a handler; the CPU
    record differs, so a run may carry at most a few distinct handlers.
    Returns list of (node_id, code) sorted by node id."""
    data_lo, data_n = rw[0], rw[1]
    runs = []
    off = data_lo
    end_off = data_lo + data_n - 16
    while off <= end_off:
        rec = []
        o = off
        while o <= end_off:
            _fl, hand, cell, w3 = struct.unpack_from("<4I", elf, o)
            nid = (w3 >> 16) & 0xFF
            code = w3 & 0xFFFF
            # w3's TOP byte is a per-node FLAG, not padding: star_wars node 8
            # carries 0x04 there and requiring zero broke the run at exactly
            # that record, silently costing 7 of its 13 nodes. Do not test it.
            if not (in_seg(hand, rx) and in_seg(cell, rw)
                    and nid < 64 and 0 < code < 0x100):
                break
            rec.append((nid, code, hand))
            o += 16
        if len(rec) >= 5:
            # node ids must be unique and the handlers few
            ids = [r[0] for r in rec]
            if len(set(ids)) == len(ids) and len(set(r[2] for r in rec)) <= 3:
                runs.append(rec)
        off = o + 16 if o > off else off + 4
    if not runs:
        raise SystemExit("no node directory found")
    rec = max(runs, key=len)
    return sorted((nid, code) for nid, code, _h in rec)


def hex_inventory(hexdir):
    """{(type, class_index): (version_word, 'maj.min.patch', filename)}"""
    inv = {}
    if not hexdir or not os.path.isdir(hexdir):
        return inv
    pat = re.compile(r"^(.+)-([A-Za-z0-9_]+)-(\d+)_(\d+)_(\d+)\.hex$")
    for nm in os.listdir(hexdir):
        m = pat.match(nm)
        if not m:
            continue
        typ, cls_name = m.group(1), m.group(2)
        cls = CLASS_BY_NAME.get(cls_name)
        if cls is None:
            continue
        maj, mnr, pat_ = int(m.group(3)), int(m.group(4)), int(m.group(5))
        if maj > 255 or mnr > 255 or pat_ > 255:
            continue
        inv[(typ, cls)] = ((maj << 16) | (mnr << 8) | pat_,
                           "%d.%d.%d" % (maj, mnr, pat_), nm)
    return inv


def derive(elf_path, hexdir):
    elf = io.open(elf_path, "rb").read()
    rx, rw = load_segments(elf)
    cat_base, cat = find_catalog(elf, rx, rw)
    nodes = find_node_directory(elf, rx, rw)
    inv = hex_inventory(hexdir)

    rows, skipped = [], []
    for nid, code in nodes:
        idx = code - 2                      # two reserved entries precede
        typ = cat[idx] if 0 <= idx < len(cat) else None
        if typ is None:
            # the CPU/bridge record and reserved rows land here - real nodes
            # always resolve to a type name
            skipped.append((nid, code, "no-type (CPU/bridge or reserved)"))
            continue
        # choose a class: the measured pair for this type first, then any
        # class with a KNOWN part id whose hex the title ships
        pick = None
        for cls in CLASS_PREF.get(typ, CLASS_PREF_DEFAULT):
            if (typ, cls) in inv and cls in PART_BY_CLASS:
                pick = cls
                break
        if pick is None:
            have = [c for (t, c) in inv if t == typ]
            skipped.append((nid, code,
                            "no-usable-class type=%s shipped=%s" %
                            (typ, [CLASS_NAMES.get(c, c) for c in have])))
            continue
        fw_word, fw_str, fname = inv[(typ, pick)]
        if typ == "node4":
            fw_word, fw_str = NODE4_FW_AS_READ, "as-read(124.107.0)"
        var = VARIANT_PRIOR.get(typ, VARIANT_DEFAULT)
        guess = typ not in VARIANT_PRIOR
        rows.append((nid, typ, code, PART_BY_CLASS[pick], pick, var,
                     fw_word, fw_str, fname, guess))
    return rows, skipped


def emit(rows, skipped, elf_path, out):
    w = io.open(out, "w", encoding="ascii", newline="\n") if out else sys.stdout
    w.write("# nbdir v1 elf=%s nodes=%d\n"
            % (os.path.basename(elf_path), len(rows)))
    for (nid, typ, code, part, cls, var, fw, fw_str, fname, guess) in rows:
        w.write("node=%d type=%s code=%d part=0x%08x class=%d "
                "variant=0x%02x%s fw=0x%06x hexver=%s hex=%s\n"
                % (nid, typ, code, part, cls, var,
                   " variant_guess=1" if guess else "", fw, fw_str, fname))
    for nid, code, why in skipped:
        w.write("# skipped node=%d code=%d reason=%s\n" % (nid, code, why))
    if out:
        w.close()


def check_godzilla(rows):
    """The labelled example: godzilla's directory must reproduce hwshim's
    runtime-measured nb_idents[] claims EXACTLY - type, part, variant, fw.
    (fw 0x012300 in the C table is 1.35.0, which is also what the hex
    filenames carry, so filename-derived fw must equal it here.)"""
    want = {  # nid: (type, part, variant, fw)
        1:  ("pinnode",    0x00020023, 0x01, 0x012300),
        8:  ("pinnode",    0x00020023, 0x01, 0x012300),
        9:  ("pinnode",    0x00020023, 0x01, 0x012300),
        2:  ("ws2812node", 0x2C40102B, 0x05, 0x012300),
        7:  ("ws2812node", 0x2C40102B, 0x05, 0x012300),
        12: ("ws2812node", 0x2C40102B, 0x05, 0x012300),
        14: ("ws2812node", 0x2C40102B, 0x05, 0x012300),
        4:  ("node4",      0x00140040, 0x98, 0x7C6B00),
    }
    got = {r[0]: (r[1], r[3], r[5], r[6]) for r in rows}
    for nid, (typ, part, var, fw) in want.items():
        g = got.get(nid)
        if g != (typ, part, var, fw):
            raise SystemExit(
                "GODZILLA CHECK FAILED node %d: want %s/0x%08x/0x%02x/0x%06x "
                "got %r" % (nid, typ, part, var, fw, g))
    extra = set(got) - set(want)
    if extra:
        raise SystemExit("GODZILLA CHECK FAILED: unexpected nodes %s" % extra)
    print("godzilla check OK: %d nodes reproduce hwshim's measured claims "
          "exactly" % len(want))


def main(argv):
    elf_path = None
    hexdir = None
    out = None
    check = False
    it = iter(argv[1:])
    for a in it:
        if a == "--hexdir":
            hexdir = next(it)
        elif a == "--out":
            out = next(it)
        elif a == "--check-godzilla":
            check = True
        else:
            elf_path = a
    if not elf_path:
        raise SystemExit(__doc__)
    if hexdir is None:
        hexdir = os.path.dirname(os.path.abspath(elf_path))
    rows, skipped = derive(elf_path, hexdir)
    if check:
        check_godzilla(rows)
    emit(rows, skipped, elf_path, out)


if __name__ == "__main__":
    main(sys.argv)
