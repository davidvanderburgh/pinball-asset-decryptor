#!/usr/bin/env python3
"""cgcroms.py <rom> [--json] - the switch, flipper-switch and coil names a
Williams WPC game ROM prints in its own service menu.

A Chicago Gaming remake runs the original Williams ROM (Medieval Madness
mm_10.rom, ...), and that ROM carries the tables its test menu reads: big-
endian pointers into its own 16 KiB page, each to a NUL-ended name.  Found
here by shape, not by address, so any WPC ROM works:

Each table starts with the text for a bad number ("INVALID SW. NUMBER",
"Null"), then:

  switches  64-72 pointers: D1..D8 (the coin door: LEFT COIN SLOT, ...,
            ESCAPE, DOWN, UP, ENTER) then the matrix 11..78 or ..88
  flippers  8 pointers, the flipper switches (R. FLIPPER E.O.S. ...)
  coils     24+ pointers, solenoids 1.. (TROUGH EJECT ...)

Unused entries ("NOT USED", Cactus Canyon's "UNUSED ##9") are left out, and
a switch's '*' (the ROM's opto mark) is dropped from its name.  Prints a table, or
with --json {"switches": {"D1": ..., "11": ...}, "flippers": {"F1": ...},
"coils": {"1": ...}}.
"""
import json
import re
import struct
import sys

PAGE = 0x4000
# a name: printable, starting like one (AFM has "M"ARTIAN TARGET; Cactus
# Canyon marks its optos "*TROUGH BALL 1" and names coils "##1 (L) DROP TGT.")
NAME = re.compile(rb"[A-Z0-9\"'(.*#][\x20-\x7e]{1,30}\x00")
# entry 0 of a table: the text for a bad number
BAD_ENTRY = re.compile(r"^(INVALID|NULL$)", re.I)


def page_tables(rom, base):
    """Every run of >= 8 BE pointers in this page to names in this page."""
    page = rom[base:base + PAGE]
    names = {}

    def name_at(ptr):
        if not 0x4000 <= ptr < 0x8000:
            return None
        if ptr in names:
            return names[ptr]
        # a name does not follow a printable byte: a pointer into the
        # middle of one is past the end of the table
        at = ptr - 0x4000
        m = NAME.match(page, at) if at > 0 and not 0x20 <= page[at - 1] <= 0x7e else None
        names[ptr] = m.group()[:-1].decode("latin-1") if m else None
        return names[ptr]

    runs, i = [], 0
    while i + 1 < len(page):
        j, out = i, []
        while j + 1 < len(page):
            n = name_at(struct.unpack_from(">H", page, j)[0])
            if n is None:
                break
            out.append(n)
            j += 2
        if len(out) >= 8:
            runs.append((base + i, out))
            i = j
        else:
            i += 1
    return runs


def tables(rom):
    """The English tables: a ROM carries one set per language, and the
    English set's page is the one whose switch table ends D1..D8 in ENTER."""
    for base in range(0, len(rom) - PAGE + 1, PAGE):
        if b"LEFT COIN SLOT\x00" not in rom[base:base + PAGE]:
            continue
        found = page_set(rom, base)
        sw = found.get("switches", [])
        if len(sw) >= 8 and sw[7] == "ENTER":
            return found
    return {}


def page_set(rom, base):
    found = {}
    for off, names in page_tables(rom, base):
        # entry 0 of every table is its "invalid number" text - unless a
        # printable byte right before that text hid it from page_tables
        # (Cactus Canyon's flipper-switch table) and the run starts at 1
        if names and BAD_ENTRY.match(names[0]):
            names = names[1:]
        if "switches" not in found and len(names) >= 64 and "LEFT COIN SLOT" in names[0]:
            found["switches"] = names[:72]
        elif "flippers" not in found and sum("FLIPPER" in n for n in names[:8]) >= 4                 and any("BUTTON" in n or "BUT." in n for n in names[:8]):
            found["flippers"] = names[:8]
        elif "coils" not in found and any("TROUGH" in n or "EJECT" in n for n in names[:12]) \
                and not any("COIN SLOT" in n for n in names[:8]):
            found["coils"] = names[:32]
    return found


def named(rom):
    t = tables(rom)
    out = {"switches": {}, "flippers": {}, "coils": {}}
    for i, n in enumerate(t.get("switches", [])):
        key = "D%d" % (i + 1) if i < 8 else "%d%d" % ((i - 8) // 8 + 1, (i - 8) % 8 + 1)
        n = n.lstrip("*")               # the ROM's opto mark, not the name
        if n != "NOT USED" and not n.startswith("UNUSED"):
            out["switches"][key] = n
    for i, n in enumerate(t.get("flippers", [])):
        if n != "NOT USED":
            out["flippers"]["F%d" % (i + 1)] = n
    # a coil table runs on into whatever follows it: keep names only until
    # the first entry that is not a plausible coil name
    for i, n in enumerate(t.get("coils", [])):
        if not re.match(r"^[A-Z0-9\"'(.#][A-Z0-9 .#/()\"'+-]+$", n) or len(n) < 3:
            break
        if n != "NOT USED" and not n.startswith("UNUSED"):
            out["coils"][str(i + 1)] = n
    return out


def main(argv):
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    with open(argv[0], "rb") as f:
        rom = f.read()
    out = named(rom)
    if not out["switches"]:
        print("cgcroms: no WPC switch table in %s" % argv[0], file=sys.stderr)
        return 1
    if "--json" in argv:
        print(json.dumps(out, indent=1))
    else:
        for k in ("switches", "flippers", "coils"):
            print("[%s]" % k)
            for n, v in out[k].items():
                print("  %-4s %s" % (n, v))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
