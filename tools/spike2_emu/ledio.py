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
"""
import collections
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import devicexy
import ledframes

#: group in the device table -> node on the bus. Verified with devjoin.py
#: against the live switch table; it is a lookup, not arithmetic.
GROUP_NODE = {4: 0, 5: 1, 6: 8, 7: 9}

ENUM_CMDS = (0x84, 0x85)


def wire_enumeration(path):
    """{node: {index, ...}} from the boot per-LED config writes."""
    out = collections.defaultdict(set)
    for _, b in ledframes.read(path):
        if len(b) == 6 and b[2] in ENUM_CMDS:
            out[b[0] & 0x3F].add(b[3])
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    wire = wire_enumeration(sys.argv[1])
    d, cs = devicexy.load()
    recs = devicexy.records(d, cs)

    rows, problems = [], []
    for group, node in sorted(GROUP_NODE.items()):
        leds = [r for r in recs if r["kind"] == "led" and r["group"] == group]
        if not leds:
            continue
        tbl = {r["index"] for r in leds}
        seen = wire.get(node, set())
        missing = sorted(tbl - seen)
        extra = sorted(seen - tbl)
        print("node %-2d (group %d): %d LEDs in the table, %d enumerated on the wire"
              % (node, group, len(tbl), len(seen)))
        print("    every table index on the wire: %s"
              % ("YES" if not missing else "NO - missing %s" % missing))
        if extra:
            print("    on the wire with no table entry: %s" % extra)
        if missing:
            problems.append((node, missing))
        for r in sorted(leds, key=lambda r: r["index"]):
            rows.append((node, r))

    if problems:
        # REFUSE, rather than write a map that says it is untrustworthy in a
        # comment nobody reads. The usual cause is a log without the boot
        # enumeration in it: those 6-byte 0x84/0x85 writes only survive with
        # PAD_NB_LOG raised, and the default 400-line budget drops them, so the
        # wire simply looks like it has no LEDs.
        print("\nJOIN IS NOT CLEAN - refusing to write. Missing indices per node:")
        for node, missing in problems:
            print("   node %d: %d missing (%s%s)"
                  % (node, len(missing), missing[:8],
                     " ..." if len(missing) > 8 else ""))
        print("Capture again with PAD_NB_LOG=400000 and a run that reaches"
              " ~25 s, then re-run this.")
        return 2

    lines = ["# Godzilla Pro LED I/O map.",
             "# Position from the device table in the binary; node/index verified",
             "# against the boot enumeration on the wire (see ledio.py).",
             "# %-4s %-5s %-34s %5s %5s  %-5s %s"
             % ("node", "index", "name", "x", "y", "conn", "image")]
    for node, r in rows:
        lines.append("%-6d %-5d %-34s %5d %5d  %-5s %s"
                     % (node, r["index"], r["name"], r["x"], r["y"],
                        r["conn"], r["image"]))
    text = "\n".join(lines) + "\n"

    if len(sys.argv) > 2:
        open(sys.argv[2], "w").write(text)
        print("\n%d LEDs -> %s" % (len(rows), sys.argv[2]))
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
