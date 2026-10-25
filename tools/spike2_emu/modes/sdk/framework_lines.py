#!/usr/bin/env python3
"""framework_lines.py - the port lines of a Spike 2 build's own mode framework, read from the game's code (PAD-710;
MODE_SDK.md "A mode in the place of one of the game's"; the finder is pinball_decryptor/plugins/stern/mode_framework.py,
which says what it reads).

    framework_lines.py <game ELF> [--port <port>]   prints the lines (only those the port lacks, with --port)

Exit 1 when the build has no mode framework of the shape (a plain-C title); the reason goes to stderr."""
import argparse
import os
import re
import sys

WT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
if WT not in sys.path:
    sys.path.insert(0, WT)

from pinball_decryptor.plugins.stern import mode_framework, stock_scan  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("elf")
    ap.add_argument("--port", help="print only the lines this port lacks")
    a = ap.parse_args(argv)
    with open(a.elf, "rb") as f:
        prog = stock_scan.Program(f.read())
    start_slot = None
    text = ""
    if a.port:
        with open(a.port, encoding="utf-8") as f:
            text = f.read()
        m = re.search(r"^value\s+stock_slot_start\s+(\d+)", text, re.M)
        start_slot = int(m.group(1)) if m else None
    found = mode_framework.find(prog, start_slot)
    for n in found.notes:
        print("# " + n, file=sys.stderr)
    out = mode_framework.port_lines(found, prog)
    if not out:
        return 1
    if a.port:
        out = mode_framework.missing_from(out, text)
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
