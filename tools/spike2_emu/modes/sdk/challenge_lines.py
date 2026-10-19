#!/usr/bin/env python3
"""challenge_lines.py - the port lines of a Spike 2 build's named Player Challenge picks, read from the game's own
code (PAD-615; MODE_SDK.md "A mode in the game's Challenge list"; the finder is
pinball_decryptor/plugins/stern/portchallenge.py, which says what it reads).

    challenge_lines.py <game ELF> [--port <port>]   prints the lines (only those the port lacks, with --port)

Exit 1 when the build names no challenge or a named one has no handler (the reason goes to stderr)."""
import argparse
import os
import sys

WT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
if WT not in sys.path:
    sys.path.insert(0, WT)

from pinball_decryptor.plugins.stern import portchallenge  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("elf")
    ap.add_argument("--port", help="print only the lines this port lacks (a differing one is flagged)")
    a = ap.parse_args(argv)
    out, notes = portchallenge.find(a.elf)
    for n in notes:
        print("# " + n, file=sys.stderr)
    if not out:
        return 1
    if a.port:
        with open(a.port, encoding="utf-8") as f:
            out = portchallenge.missing_from(out, f.read())
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
