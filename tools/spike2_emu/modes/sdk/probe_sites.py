#!/usr/bin/env python3
"""probe_sites.py - the sites file for call_probe.c: every hookable virtual of some classes.

    probe_sites.py <game ELF> <class> [<class> ...] -o probe.sites [--first <address>]

A title the port tool cannot place a function in still names its classes (RTTI). This lists
each named class's virtual functions that the runtime's trampoline can hook - first two
instructions not relative to the program counter, except a literal load, which it moves -
one per address, named `<class>.<slot>`, with their instruction words read from the ELF.
--first puts one address before them, named `first` (the tick is a good one: call_probe.c
only acts in the process whose program maps the first site, and `first` lines in its log
then show the game running).

Slots are counted the way rtti_tree.py counts them. At most 80 sites (call_probe.c's limit).
"""
import argparse
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))          # tools/spike2_emu
import rtti_tree  # noqa: E402

_spec = importlib.util.spec_from_file_location("port_tool", os.path.join(HERE, "port_tool.py"))
port_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(port_tool)

LIMIT = 80


def sites(elf, model, classes, first=None):
    out, seen, refused = [], set(), []
    if first is not None:
        out.append(("first", first))
        seen.add(first)
    for cls in classes:
        info = model.get(cls)
        if not info or not info.get("vtable"):
            raise SystemExit("no vtable for class %r in this program" % cls)
        for k in range(info["nvirt"]):
            f = elf.word(info["vtable"] + 4 * k)
            if not f or not elf.in_text(f) or f in seen:
                continue
            seen.add(f)
            if (elf.word(f) >> 28) != 0xE or not port_tool.is_hooked_ok(elf, f):
                refused.append("%s.%d" % (cls, k))
                continue
            out.append(("%s.%d" % (cls, k), f))
    return out[:LIMIT], refused, max(0, len(out) - LIMIT)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("elf")
    ap.add_argument("classes", nargs="+")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--first", type=lambda s: int(s, 0))
    args = ap.parse_args(argv)
    elf = port_tool.Elf(args.elf)
    model = rtti_tree.build_model(elf.b)
    got, refused, dropped = sites(elf, model, args.classes, args.first)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        for name, va in got:
            f.write("%s 0x%x %08x %08x\n" % (name[:39], va, elf.word(va), elf.word(va + 4)))
    print("wrote %d sites to %s" % (len(got), args.out))
    if refused:
        print("not hookable (a return, a branch or a pc-relative read up front): %s" % " ".join(refused))
    if dropped:
        print("DROPPED %d sites past the limit of %d: probe fewer classes" % (dropped, LIMIT))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
