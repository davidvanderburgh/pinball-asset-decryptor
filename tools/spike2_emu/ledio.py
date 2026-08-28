#!/usr/bin/env python3
"""ledio.py <nblog> [out.txt] - the LED I/O map: name, position, node, index.

Joins the STATIC device table (devicexy.py) to the LIVE node bus, and verifies
the join rather than asserting it.

THE KEY IS THE BOOT ENUMERATION, and it needs no operator menu at all - which
matters, because two attempts to reach the game's LED Tests screen were lost to
menu navigation. About 21 s into a run, every LED board is sent a pair of 6-byte
writes per LED:

    [0x80|node] [len=2] [0x85] [INDEX] [cksum] [00]
    [0x80|node] [len=2] [0x84] [INDEX] [cksum] [00]

one pair per LED, indices ascending and SKIPPING the gaps. It is the per-LED
analogue of the `70 XX` per-switch config writes already documented.

THE VERIFICATION. Those index bytes are exactly the device table's LED `index`
for that node - not approximately, exactly, INCLUDING the irregular skips:

    node 8: both sides skip 2, 3, 13, 20, 40, 45, 46, 61
    node 9: both sides skip 37, 45, 46, 55, 56, 57, 58, 61, 63, 64, 65

Every index in the table appears on the wire (53/53 on node 8, 69/69 on node 9).
Two derivations from unrelated evidence - a static table in the binary and bytes
on a serial bus - agreeing on ~70 irregular values is not a coincidence, and it
is a much stronger check than "the numbers look plausible".

The wire carries a couple of indices the table does not (0 and 1 on both nodes,
plus 53 on node 8). Those are reported, not hidden: they are most likely board
channels with no playfield fixture behind them.

  ledio.py ~/gzwatch.log led_io.txt     # log from a run with PAD_NB_LOG raised
  ledio.py                              # no log: build from the binary alone

THE MAP ITSELF IS STATIC AND THE WIRE IS ONLY THE CHECK. Every column written
below - node, index, name, position, connector - comes from the device table in
the ELF; the enumeration contributes not one field, it agrees or it does not. So
the map can be built with no run at all, which is what mktables.py does when it
first sees a title, and the wire check is applied when a log happens to be
there. Requiring the log was a real cost: it meant the LEDs on the virtual
playfield could not be drawn until someone had captured a boot with PAD_NB_LOG
raised, which quadruples the boot, for a table that never depended on it.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coilmap
import devicexy
import gameinfo
import ledframes

#: group in the device table -> node on the bus. Verified with devjoin.py
#: against the live switch table; it is a lookup, not arithmetic.
#:
#: ★ THE FALLBACK NOW, NOT THE ANSWER (item 53). This is godzilla's map, and
#: writing every title's led_io.txt through it is what made the file unable to
#: carry a title whose lamps sit elsewhere: james_bond_60th_le's playfield
#: lamps are groups 8 and 9, so its led_io.txt held 29 cabinet and backbox rows
#: and NONE of its 73 playfield inserts. build() takes a derived map now -
#: coilmap.group_node() owns the derivation - and keeps this only for a caller
#: that has no table to derive from. It is a fourth copy of the constant
#: otherwise, which is what coilmap.py exists to prevent.
GROUP_NODE = coilmap.GROUP_NODE

ENUM_CMDS = (0x84, 0x85)


def wire_enumeration(path):
    """{node: {index, ...}} from the boot per-LED config writes."""
    out = collections.defaultdict(set)
    for _, b in ledframes.read(path):
        if len(b) == 6 and b[2] in ENUM_CMDS:
            out[b[0] & 0x3F].add(b[3])
    return out


def build(recs, wire=None, mapping=None):
    """([(node, record)], problems, report) for a title's LEDs.

    `wire` is the boot enumeration when a log was captured, and None when there
    is no run to read - see the header. With no wire there is nothing to
    disagree with, so `problems` is empty and the rows are exactly what the
    binary says.

    `mapping` is THIS TITLE'S group -> node map from coilmap.group_node(), or
    None to fall back to the module constant. Passing it is what lets a title
    whose lamps are not in godzilla's four groups appear in this file at all
    (item 53); the join and the verification below are unchanged, because they
    never depended on WHICH groups were in the map, only on there being one.
    """
    rows, problems, report = [], [], []
    for group, node in sorted((mapping or GROUP_NODE).items()):
        leds = [r for r in recs if r["kind"] == "led" and r["group"] == group]
        if not leds:
            continue
        tbl = {r["index"] for r in leds}
        if wire is not None:
            seen = wire.get(node, set())
            missing = sorted(tbl - seen)
            extra = sorted(seen - tbl)
            report.append("node %-2d (group %d): %d LEDs in the table, %d "
                          "enumerated on the wire" % (node, group, len(tbl), len(seen)))
            report.append("    every table index on the wire: %s"
                          % ("YES" if not missing else "NO - missing %s" % missing))
            if extra:
                report.append("    on the wire with no table entry: %s" % extra)
            if missing:
                problems.append((node, missing))
        else:
            report.append("node %-2d (group %d): %d LEDs in the table (no wire "
                          "log - not verified)" % (node, group, len(tbl)))
        for r in sorted(leds, key=lambda r: r["index"]):
            rows.append((node, r))
    return rows, problems, report


def text(game, rows, verified):
    """led_io.txt, as a string.

    The header line SAYS whether the wire agreed, because "verified against the
    boot enumeration" was previously printed on every file whether or not any
    enumeration had been read.
    """
    lines = ["# %s LED I/O map." % game,
             "# Position, node and index from the device table in the binary.",
             "# node/index %s"
             % ("verified against the boot enumeration on the wire (see ledio.py)."
                if verified else
                "NOT verified - built from the binary alone, no wire log."),
             "# %-4s %-5s %-34s %5s %5s  %-5s %s"
             % ("node", "index", "name", "x", "y", "conn", "image")]
    for node, r in rows:
        # "-" not "" for a missing connector: the reader counts fields from the
        # right (the NAME is the multi-word one), so an empty column silently
        # shifts every number. It bit device_xy.txt's coils for real.
        lines.append("%-6d %-5d %-34s %5d %5d  %-5s %s"
                     % (node, r["index"], r["name"], r["x"], r["y"],
                        r["conn"] or "-", r["image"]))
    return "\n".join(lines) + "\n"


def main():
    game = gameinfo.active()
    if not game:
        print(__doc__)
        print("no active title - set PAD_GAME, or start a run.")
        return 1
    wire = wire_enumeration(sys.argv[1]) if len(sys.argv) > 1 else None
    recs = devicexy.build(game)
    rows, problems, report = build(recs, wire)
    for line in report:
        print(line)

    if problems:
        # REFUSE, rather than write a map that says it is untrustworthy in a
        # comment nobody reads. The usual cause is a log without the boot
        # enumeration in it: those 6-byte 0x84/0x85 writes only survive with
        # PAD_NB_LOG raised, and the default 400-line budget drops them, so the
        # wire simply looks like it has no LEDs.
        #
        # Only reachable when a log was NAMED. Asking for verification and
        # getting a contradiction is an error; not asking is not.
        print("\nJOIN IS NOT CLEAN - refusing to write. Missing indices per node:")
        for node, missing in problems:
            print("   node %d: %d missing (%s%s)"
                  % (node, len(missing), missing[:8],
                     " ..." if len(missing) > 8 else ""))
        print("Capture again with PAD_NB_LOG=400000 and a run that reaches"
              " ~25 s, then re-run this.")
        return 2

    # Default into the TITLE's table directory, not the cwd: these tables are
    # per title now, and a second game must not overwrite the first one's.
    dest = sys.argv[2] if len(sys.argv) > 2 else gameinfo.table("led_io.txt", game)
    d = os.path.dirname(os.path.abspath(dest))
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(dest, "w", newline="") as f:       # newline='': LF even on Windows
        f.write(text(game, rows, wire is not None))
    print("\n%d LEDs -> %s" % (len(rows), dest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
