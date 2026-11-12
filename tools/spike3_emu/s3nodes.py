#!/usr/bin/env python3
"""s3nodes.py - a Spike 3 title's NODE DIRECTORY, read out of its own game
program, and the identity each node board must claim (PAD-1090, stage 4).

    python3 s3nodes.py <game-elf> [--hexdir DIR]      prints the claims

The 64-bit counterpart of ../spike2_emu/nbdir.py: the same two static tables
in the game's data, laid out for aarch64 and resolved through the program's
R_AARCH64_RELATIVE relocations (the game is position-independent, so every
pointer in .data is a relocation addend, zero in the file):

  BOARD-MODEL CATALOG, 0x28-byte rows, starting at the part number:
      +0x00 ptr  "520-XXXX-XX"           +0x08 u32  the same number x100
      +0x10 ptr  type name ("pinnode")   +0x18 ptr  5-language name cell
      +0x20 u64  flags
  NODE DIRECTORY, 0x20-byte records sharing one handler (the CPU's has its
  own), the w3 word = node id << 16 | model code:
      +0x00 ptr  handler   +0x08 ptr  name cell   +0x10 u32  w3   +0x18 flags
  and the catalog row of a code is code - 2, as on Spike 2 - checked here by
  the CPU record (node 0) landing on the row named "SPIKE3 CPU".

pokemon_le 0.82.0: node 1 pinnode 520-5319, 4 node4 520-5790, 8/9 pinnode
520-7017, 10/13 pinnode 520-8511, 2/7/12/14 ws2812node 520-8511.

THE CLAIM is nbdir.py's, unchanged (its comments carry the measurements): a
CPU class whose part id the game recognises and whose
<type>-<class>-<maj>_<min>_<patch>.hex the title ships beside its program;
the firmware version from that file's name; the variant from the per-type
priors measured on Spike 2 (the node boards are the same family).
"""
import os
import re
import struct
import sys

PART_BY_CLASS = {1: 0x00020023, 3: 0x00030030, 4: 0x00140040, 5: 0x2C40102B}
CLASS_NAMES = {1: "LPC1112_101", 2: "LPC1112_201", 3: "LPC1113_302",
               4: "LPC1124_303", 5: "LPC1313", 6: "LPC812", 7: "RP235x"}
VARIANT_PRIOR = {"pinnode": 0x01, "ws2812node": 0x05, "node4": 0x03,
                 "tmc5041node": 0x0d, "coil4node": 0x04, "lcdnode": 0x02,
                 "hdmi_ws2812node": 0x0c, "coil4_lednode": 0x10}
VARIANT_DEFAULT = 0x01
CLASS_PREF = {"pinnode": (1, 5), "ws2812node": (5,), "node4": (4,),
              "coil4node": (5, 1), "lcdnode": (3,), "hdmi_ws2812node": (5,),
              "coil4_lednode": (5,)}
CLASS_PREF_DEFAULT = (5, 1, 4)
HWID = 0x0064            # board id: only tested non-zero (hwshim NB_HWID_DEFAULT)

TYPE_NAMES = ["pinnode", "ws2812node", "ws2812pinnode", "coil4node",
              "coil4_lednode", "lcdnode", "hdminode", "hdmi_ws2812node",
              "magsensornode", "magsensor11node", "node4", "tmc2590node",
              "tmc5041node", "afnode", "accbridgenode"]


class Elf:
    def __init__(self, path):
        self.d = d = open(path, "rb").read()
        if d[:4] != b"\x7fELF" or d[4] != 2:
            raise ValueError("%s: not a 64-bit ELF" % path)
        phoff, = struct.unpack_from("<Q", d, 0x20)
        phsz, phn = struct.unpack_from("<HH", d, 0x36)
        self.segs, dyn = [], None
        for i in range(phn):
            t, fl, off, va, pa, fs, ms, al = struct.unpack_from("<IIQQQQQQ", d, phoff + i * phsz)
            if t == 1:
                self.segs.append((va, off, fs, fl))
            elif t == 2:
                dyn = (off, fs)
        tags = {}
        for k in range(0, dyn[1], 16):
            tg, val = struct.unpack_from("<qQ", d, dyn[0] + k)
            if tg == 0:
                break
            tags.setdefault(tg, val)
        self.rel = {}
        ro = self.off(tags[7])
        for k in range(0, tags[8], 24):
            off, info, add = struct.unpack_from("<QQq", d, ro + k)
            if info & 0xFFFFFFFF == 1027:        # R_AARCH64_RELATIVE
                self.rel[off] = add
        self.inv = {}
        for off, add in self.rel.items():
            self.inv.setdefault(add, []).append(off)

    def off(self, va):
        for s, o, fs, fl in self.segs:
            if s <= va < s + fs:
                return o + va - s
        return None

    def u32(self, va):
        o = self.off(va)
        return struct.unpack_from("<I", self.d, o)[0] if o is not None else None

    def u64(self, va):
        o = self.off(va)
        return struct.unpack_from("<Q", self.d, o)[0] if o is not None else None

    def cstr(self, va):
        o = self.off(va)
        if o is None:
            return None
        e = self.d.find(b"\0", o, o + 80)
        return self.d[o:e].decode("latin1") if e > o else None

    def ptr(self, va):
        return self.rel.get(va)

    def strva(self, s):
        m = re.search(re.escape(b"\0" + s.encode() + b"\0"), self.d)
        if not m:
            return None
        o = m.start() + 1
        for sv, so, fs, fl in self.segs:
            if so <= o < so + fs:
                return sv + o - so
        return None

    def is_code(self, va):
        return any(s <= va < s + fs and fl & 1 for s, o, fs, fl in self.segs)


def catalog(e):
    """(first row va, {row: (part str, part value, type, english name)}); row
    0 is model code 2. Rows run while the part field is a "520-" number."""
    slots = []
    for t in TYPE_NAMES:
        va = e.strva(t)
        if va is not None:
            slots += e.inv.get(va, [])
    if not slots:
        raise ValueError("no board-model catalog (no node type names referenced)")

    def row(a):
        p, t, c = e.ptr(a), e.ptr(a + 0x10), e.ptr(a + 0x18)
        ps = e.cstr(p) if p else None
        if not (ps and ps.startswith("520-")):
            return None
        en = e.ptr(c) if c else None
        return (ps, e.u32(a + 8), (e.cstr(t) if t else None), (e.cstr(en) if en else None))
    # Only a reference that sits IN a catalog row counts (its row's part
    # field a "520-" number): transformers_mtmte_le 0.96 also names
    # "pinnode" in a plain list of node-type names (0x978d18, beside "lcd
    # node", "qr node", ...) far below its catalog, and starting from the
    # lowest reference found no rows at all (PAD-1140).
    slots = [a for a in slots if row(a - 0x10)]
    if not slots:
        raise ValueError("no board-model catalog (no node type name in a catalog row)")
    lo = min(slots) - 0x10
    while row(lo - 0x28):
        lo -= 0x28
    rows, a = {}, lo
    while row(a):
        rows[(a - lo) // 0x28] = row(a)
        a += 0x28
    return lo, rows


def directory(e, cat):
    """[(node, code, flags)]: the 0x20-byte records around the CPU's own
    (node 0, whose model row is named "... CPU"), each a code pointer, a
    name cell, node<<16|code, flags; node ids distinct."""
    cpu_codes = {i + 2 for i, r in cat.items() if r[3] and r[3].endswith("CPU")}
    if not cpu_codes:
        raise ValueError("no CPU row in the board catalog")

    def rec(a):
        h, w3 = e.ptr(a), e.u32(a + 0x10)
        # the top byte is a per-record flag, not part of the node id:
        # star_wars_elg 1.10's node 8 record reads 0x01080005, and stopping
        # there lost every playfield board (pokemon_le's are all 0)
        if h is None or not e.is_code(h) or w3 is None or (w3 >> 24) > 0x0F:
            return None
        nid, code = (w3 >> 16) & 0xFF, w3 & 0xFFFF
        if nid >= 64 or (code - 2) not in cat:
            return None
        return nid, code, e.u64(a + 0x18) or 0
    for a, add in sorted(e.rel.items()):
        if not e.is_code(add):
            continue
        r = rec(a)
        if not (r and r[0] == 0 and r[1] in cpu_codes):
            continue
        lo = hi = a
        while rec(lo - 0x20):
            lo -= 0x20
        while rec(hi + 0x20):
            hi += 0x20
        out = [rec(x) for x in range(lo, hi + 0x20, 0x20)]
        if len({n for n, _, _ in out}) == len(out) and len(out) >= 2:
            return out
    raise ValueError("no node directory found")


DEV_CLASS = {1: "switch", 2: "coil", 3: "led", 5: "gi"}


def devices(e, directory_rows=None, with_location=False):
    """[(name, node, index, class)] from the title's device tables: 0x50-byte
    records, a name pointer at +0 and at +0x20 four u16s - the GROUP (the
    1-based position of the board's record in the node directory: on
    pokemon_le the CPU board, whose inputs are the SPI chain, is record 5
    and node 8 record 7 - checked against the live bus), the index on that board, the
    class (1 switch, 2 coil, 3 LED, 5 GI) and a sub-kind. Every table is
    walked out from a record named "TROUGH 1" or "START BUTTON" (several
    tables, one per class family). node -1 = a group past the directory.
    with_location=True adds a 5th field, the u16 at +0x28: the switch's
    LOCATION (one value for every playfield switch, others for the cabinet
    buttons, the coin door, the jumpers) - see active_low_masks()."""
    if directory_rows is None:
        directory_rows = directory(e, catalog(e)[1])
    order = [nid for nid, _c, _f in directory_rows]

    def rec(a):
        n = e.rel.get(a)
        name = e.cstr(n) if n else None
        if not name or len(name) > 40 or not name.isprintable():
            return None
        w = e.u64(a + 0x20)
        if w is None:
            return None
        g, idx, cls = w & 0xFFFF, (w >> 16) & 0xFFFF, (w >> 32) & 0xFFFF
        if not (1 <= g <= 64 and idx < 512 and cls in DEV_CLASS):
            return None
        row = (name, (order[g - 1] if g - 1 < len(order) else -1), idx, DEV_CLASS[cls])
        if with_location:
            row += ((e.u64(a + 0x28) or 0) & 0xFFFF,)
        return row
    out, done = [], set()
    for anchor in ("TROUGH 1", "START BUTTON", "TROUGH", "AUTO PLUNGER"):
        va = e.strva(anchor)
        for a in e.inv.get(va, []) if va is not None else []:
            if a in done or not rec(a):
                continue
            lo = a
            while rec(lo - 0x50):
                lo -= 0x50
            while rec(lo):
                if lo not in done:
                    done.add(lo)
                    out.append(rec(lo))
                lo += 0x50
    return out


def _text(e, a):
    """The string a relocated pointer at *a* names, or ""."""
    n = e.rel.get(a)
    s = e.cstr(n) if n else None
    return s if s and s.isprintable() and len(s) < 200 else ""


def records(e, directory_rows=None):
    """Every device record WITH ITS PLACE, for the virtual playfield: dicts of
    name, kind, group (1-based node directory position), node, index, and
    where the title's own test menu draws it - image (+0x18, the picture's
    name under assets/nuk/images, e.g. "playfield"), x, y (u16s at +0x2c,
    +0x2e: TROUGH 1 at 358,844 on pokemon_le's 451x998 playfield), w, h
    (+0x30, +0x32) - plus the connector (+0x38) and part text (+0x40). The
    same table devices() walks; read from the data, as the menu reads it."""
    if directory_rows is None:
        directory_rows = directory(e, catalog(e)[1])
    order = [nid for nid, _c, _f in directory_rows]
    by_name = {}
    for row in devices(e, directory_rows):
        by_name.setdefault(row[0], row)
    out, done = [], set()
    for anchor in ("TROUGH 1", "START BUTTON", "TROUGH", "AUTO PLUNGER"):
        va = e.strva(anchor)
        for a in e.inv.get(va, []) if va is not None else []:
            lo = a
            while _rec_ok(e, lo - 0x50):
                lo -= 0x50
            while _rec_ok(e, lo):
                if lo not in done:
                    done.add(lo)
                    w = e.u64(lo + 0x20)
                    g, idx, cls = w & 0xFFFF, (w >> 16) & 0xFFFF, (w >> 32) & 0xFFFF
                    p = e.u64(lo + 0x28) or 0
                    sz = e.u64(lo + 0x30) or 0
                    conn = _text(e, lo + 0x38)
                    part = _text(e, lo + 0x40)
                    out.append(dict(
                        name=_text(e, lo), kind=DEV_CLASS[cls], group=g, index=idx,
                        node=order[g - 1] if g - 1 < len(order) else -1,
                        location=p & 0xFFFF, x=(p >> 32) & 0xFFFF, y=(p >> 48) & 0xFFFF,
                        w=sz & 0xFFFF, h=(sz >> 16) & 0xFFFF,
                        image=_text(e, lo + 0x18), conn=conn, part=part))
                lo += 0x50
    return out


def _rec_ok(e, a):
    n = e.rel.get(a)
    name = e.cstr(n) if n else None
    if not name or len(name) > 40 or not name.isprintable():
        return False
    w = e.u64(a + 0x20)
    if w is None:
        return False
    g, idx, cls = w & 0xFFFF, (w >> 16) & 0xFFFF, (w >> 32) & 0xFFFF
    return 1 <= g <= 64 and idx < 512 and cls in DEV_CLASS


def active_low_masks(devs5):
    """{node: 8-byte mask} of the switch inputs a node board reports as wire
    bit 0 when CLOSED.

    PLAYFIELD switches (the location the TROUGH n switches carry) and the
    FLIPPER BUTTONS are active low; the other cabinet switches (node 1's
    START BUTTON, the coins) active high. Measured on pokemon_le: the game's
    own Ball Trough Test sees a trough ball, and the game serves and scores
    balls, with the playfield answered active low.

    THE FLIPPER BUTTONS ARE ACTIVE LOW TOO (PAD-1090). They are cabinet
    switches wired to playfield node 8, and an earlier rule took them active
    high by their location - which reads as "held" at rest. The game ignores
    a switch it never saw open, so attract hid it; in the service menu one
    tap became a held button and the menu auto-repeated for ever (David's
    recording; reproduced headless: a tap scrolled the Main Menu without
    end, and with the whole board active low each tap moves exactly one
    row, as SERVICE PLUS on the SPI chain always did)."""
    pf = {loc for name, node, idx, cls, loc in devs5
          if cls == "switch" and name.strip().upper().startswith("TROUGH ")}
    per = {}
    for name, node, idx, cls, loc in devs5:
        if cls == "switch" and node > 0 and idx < 64:
            # the flipper buttons: active low with their board (measured)
            low = loc in pf or "FLIPPER BUTTON" in name.upper()
            per.setdefault(node, {})[idx] = low
    masks = {}
    for node, bits in per.items():
        # NARROW ON PURPOSE: star_wars_elg carries its START BUTTON and TILT
        # PENDULUM on node 8 too, unmeasured - they keep the location rule
        # (cabinet: high), and an unnamed bit the majority of its board
        maj = sum(bits.values()) * 2 > len(bits)
        m = bytearray(8)
        for b in range(64):
            if bits.get(b, maj):
                m[b // 8] |= 1 << (b % 8)
        masks[node] = bytes(m)
    return masks


def hexfiles(hexdir):
    """{(type, class name): (maj, min, patch, filename)}"""
    out = {}
    for f in sorted(os.listdir(hexdir)) if hexdir and os.path.isdir(hexdir) else []:
        m = re.match(r"^(.+?)-(LPC[0-9A-Z_]+|RP235x)-(\d+)_(\d+)_(\d+)\.hex$", f)
        if m:
            out[(m.group(1), m.group(2))] = (int(m.group(3)), int(m.group(4)), int(m.group(5)), f)
    return out


def derive(elf_path, hexdir=None):
    """{node: claim dict} for every node board the title declares."""
    e = Elf(elf_path)
    lo, cat = catalog(e)
    hexes = hexfiles(hexdir or os.path.dirname(os.path.realpath(elf_path)))
    claims = {}
    for nid, code, flags in directory(e, cat):
        part_s, part_v, typ, _name = cat.get(code - 2, (None, 0, None, None))
        if nid == 0 or typ is None:
            continue
        klass, fw, fname = None, None, None
        for c in CLASS_PREF.get(typ, CLASS_PREF_DEFAULT):
            h = hexes.get((typ, CLASS_NAMES[c]))
            if h and c in PART_BY_CLASS:
                klass, fw, fname = c, h[:3], h[3]
                break
        claims[nid] = dict(type=typ, code=code, flags=flags, partno=part_v,
                           partstr=part_s, klass=klass,
                           part=PART_BY_CLASS.get(klass, PART_BY_CLASS[1]),
                           variant=VARIANT_PRIOR.get(typ, VARIANT_DEFAULT),
                           variant_guess=typ not in VARIANT_PRIOR,
                           fw=fw or (0, 1, 0), hex=fname, hwid=HWID)
    return claims


def main():
    args = sys.argv[1:]
    hexdir = None
    if "--hexdir" in args:
        i = args.index("--hexdir")
        hexdir = args[i + 1]
        del args[i:i + 2]
    for nid, c in sorted(derive(args[0], hexdir).items()):
        print("node %2d %-16s %s part=0x%08x class=%s variant=0x%02x%s fw=%d.%d.%d hex=%s flags=%#x" % (
            nid, c["type"], c["partstr"], c["part"], CLASS_NAMES.get(c["klass"], "-"),
            c["variant"], " (guess)" if c["variant_guess"] else "", *c["fw"], c["hex"], c["flags"]))


if __name__ == "__main__":
    main()
