#!/usr/bin/env python3
"""Slot-by-slot vtable view of chosen classes in a Spike 2 game ELF.

For each class: every virtual slot with its function, whether it OVERRIDES the
first base's slot, is inherited unchanged (=base) or is NEW past the base's
count, how many other vtables share the function (a function in dozens of
vtables is a stub or __cxa_pure_virtual, not behaviour), and the code addresses
that load the class's vptr (vtable+8) from a literal pool - its constructor and
destructor sites, which is where "who builds this object" starts.

Slot offsets are printed the way a call site uses them: `ldr rX,[r0]` then
`ldr rX,[rX,#off]` then `blx rX`, so `+0x2c` greps straight into a disassembly.

Usage:
    vtslots.py <game_elf> <class> [<class>...]
    vtslots.py <game_elf> --callers 0xVA [0xVA...]   # literal-pool sites of any word

Built on rtti_tree.build_model (item 125, 2026-09-15). Read-only.
"""
import collections
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rtti_tree as rt  # noqa: E402


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    b = open(argv[0], "rb").read()
    loads = rt.load_segments(b)
    va2off, off2va = rt.make_mappers(loads)
    text = [s for s in loads if s[4] & 1][0]
    toff, tva, tsz = text[0], text[1], text[2]

    def words_equal(targets):
        hits = collections.defaultdict(list)
        for o in range(toff, toff + tsz - 4, 4):
            w = struct.unpack_from("<I", b, o)[0]
            if w in targets:
                hits[w].append(off2va(o))
        return hits

    if argv[1] == "--callers":
        want = [int(x, 16) for x in argv[2:]]
        hits = words_equal(set(want))
        for w in want:
            print("0x%06x: %s" % (w, " ".join("0x%x" % s for s in hits.get(w, [])) or "no literal"))
        return 0

    model = rt.build_model(b)

    def u32(va):
        return struct.unpack_from("<I", b, va2off(va))[0]

    def slots(name):
        r = model.get(name)
        if not r or r["vtable"] is None:
            return []
        return [u32(r["vtable"] + 8 + 4 * i) for i in range(r["nvirt"])]

    share = collections.Counter()
    owners = collections.defaultdict(list)
    for n in model:
        for i, f in enumerate(slots(n)):
            share[f] += 1
            owners[f].append((n, i))

    vptr = {r["vtable"] + 8: n for n, r in model.items() if r["vtable"] is not None}
    sites = words_equal(set(vptr))

    for name in argv[1:]:
        if name not in model:
            print("no class %s" % name)
            continue
        r = model[name]
        print("=== %s   vtable 0x%x, %d virtuals" % (rt.chain(model, name), r["vtable"] or 0, r["nvirt"] or 0))
        print("    vptr 0x%x loaded at: %s" % ((r["vtable"] or 0) + 8,
              " ".join("0x%x" % s for s in sites.get((r["vtable"] or 0) + 8, [])) or "nowhere"))
        bs = slots(r["base"]) if r["base"] else []
        for i, f in enumerate(slots(name)):
            if i < len(bs):
                tag = "=base   " if bs[i] == f else "OVERRIDE"
            else:
                tag = "NEW     "
            others = [o for o in owners[f] if o[0] != name]
            if share[f] > 12:
                note = "in %d vtables (stub/pure)" % share[f]
            elif others:
                note = "also " + ", ".join("%s[%d]" % o for o in others[:3])
                if len(others) > 3:
                    note += " +%d" % (len(others) - 3)
            else:
                note = ""
            print("    [%2d] +0x%03x  0x%06x  %s  %s" % (i, 4 * i, f, tag, note))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
