#!/usr/bin/env python3
"""Masked byte-pattern locators for game functions, checked across two builds.

A mode.so cannot carry fixed addresses: godzilla Pro 1.15, LE and 1.16 move every
function. This builds a signature from a function's first N instructions on the
REFERENCE build, with the build-specific fields masked out - branch offsets,
pc-relative literal offsets, movw/movt immediates (addresses) - grows N until the
signature is unique in the reference text, and then counts where it lands in the
OTHER build. One hit there = a portable locator; 0 = the function changed; >1 =
still ambiguous at that length (say so, do not guess).

Usage:
    patloc.py <ref_elf> <other_elf> name=0xVA [name=0xVA ...] [--json OUT]
    patloc.py <ref_elf> <other_elf> --engine [--json OUT]
        --engine takes every CODE address in armxref.ENGINE_PRO115

Tiny leaf functions (a four-instruction getter) will not go unique - there are
hundreds of `movw r3; movt r3; ldrb r0,[r3]; bx lr`. Those are reached through a
unique caller instead, and this prints them as NOT UNIQUE rather than inventing
a pattern. Item 125, 2026-09-15. Read-only.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rtti_tree as rt  # noqa: E402

MIN_N, MAX_N = 8, 40


def mask_of(w, loose=False):
    if (w & 0x0E000000) == 0x0A000000:  # b / bl: offset moves
        return 0xFF000000
    if (w & 0x0F7F0000) == 0x051F0000:  # ldr rt, [pc, #imm]: pool offset moves
        return 0xFFFFF000
    if (w & 0x0FB00000) == 0x03000000:  # movw / movt: an address
        return 0xFFF0F000
    if (w & 0x0FEF0000) == 0x028F0000:  # adr
        return 0xFFFFF000
    if loose:
        # the LOOSE level, tried only when the strict one misses on the other
        # build: struct offsets and small constants (`cmp r1,#207`, `ldr r3,[r0,#84]`)
        # are exactly what a new build changes while the code shape stays put
        if (w & 0x0E000000) == 0x02000000:  # data processing, immediate operand
            return 0xFFFFF000
        if (w & 0x0E000000) == 0x04000000:  # ldr/str with an immediate offset
            return 0xFFFFF000
    return 0xFFFFFFFF


class Text:
    def __init__(self, path):
        b = open(path, "rb").read()
        loads = rt.load_segments(b)
        self.va2off, self.off2va = rt.make_mappers(loads)
        t = [s for s in loads if s[4] & 1][0]
        self.toff, self.tva, self.tsz = t[0], t[1], t[2]
        self.words = struct.unpack_from("<%dI" % (self.tsz // 4), b, self.toff)
        self.b = b

    def index_of(self, va):
        return (self.va2off(va) - self.toff) // 4

    def va_of(self, i):
        return self.tva + 4 * i  # the text LOAD starts at file offset 0 here


def sig_at(t, va, n, loose=False):
    i = t.index_of(va)
    return [(w & mask_of(w, loose), mask_of(w, loose)) for w in t.words[i:i + n]]


def find(t, sig, cands=None):
    fv, fm = sig[0]
    if cands is None:
        cands = [i for i, w in enumerate(t.words) if (w & fm) == fv]
    out = []
    n = len(sig)
    for i in cands:
        if i + n > len(t.words):
            continue
        for k in range(1, n):
            v, m = sig[k]
            if (t.words[i + k] & m) != v:
                break
        else:
            out.append(i)
    return out


def locate(ref, other, va, loose=False):
    """(n, sig, ref_hits, other_vas) at the shortest length that is unique in ref."""
    base = sig_at(ref, va, MIN_N, loose)
    rc = [i for i, w in enumerate(ref.words) if (w & base[0][1]) == base[0][0]]
    oc = [i for i, w in enumerate(other.words) if (w & base[0][1]) == base[0][0]]
    n = MIN_N
    while True:
        sig = sig_at(ref, va, n, loose)
        rh = find(ref, sig, rc)
        if len(rh) <= 1 or n >= MAX_N:
            oh = find(other, sig, oc)
            return n, sig, [ref.va_of(i) for i in rh], [other.va_of(i) for i in oh]
        rc = rh
        n += 4


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    ref, other = Text(argv[0]), Text(argv[1])
    out_json = None
    items = []
    rest = argv[2:]
    if "--json" in rest:
        k = rest.index("--json")
        out_json = rest[k + 1]
        rest = rest[:k] + rest[k + 2:]
    if "--engine" in rest:
        import armxref
        for va, name in sorted(armxref.ENGINE_PRO115.items()):
            if ref.tva <= va < ref.tva + ref.tsz:
                items.append((name.split("(")[0], va))
    for a in rest:
        if "=" in a:
            name, va = a.split("=")
            items.append((name, int(va, 16)))
    report = []
    for name, va in items:
        n, sig, rh, oh = locate(ref, other, va)
        level = "strict"
        if len(rh) == 1 and len(oh) != 1:
            ln, lsig, lrh, loh = locate(ref, other, va, loose=True)
            if len(lrh) == 1 and len(loh) == 1:
                n, sig, rh, oh, level = ln, lsig, lrh, loh, "loose"
        if len(rh) != 1:
            verdict = "NOT UNIQUE on ref (%d hits at %d words)" % (len(rh), n)
        elif len(oh) == 1:
            verdict = "portable%s: other 0x%x" % (" (loose)" if level == "loose" else "", oh[0])
        elif not oh:
            verdict = "absent on other (function changed)"
        else:
            verdict = "ambiguous on other (%d hits)" % len(oh)
        print("%-32s ref 0x%-7x %2d words  %s" % (name, va, n, verdict))
        report.append({"name": name, "ref": va, "words": n, "level": level, "ref_hits": rh, "other_hits": oh,
                       "values": [v for v, _ in sig], "masks": [m for _, m in sig]})
    if out_json:
        with open(out_json, "w") as f:
            json.dump(report, f, indent=1)
        print("wrote", out_json)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
