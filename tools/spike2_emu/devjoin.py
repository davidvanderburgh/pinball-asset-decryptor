#!/usr/bin/env python3
"""devjoin.py <swmap.log> - check the static device table against the live game.

devicexy.py reads a STATIC table out of the binary: name, class, position, and a
(group, index) that looks like an I/O address. `PAD_SW_MAP=<n>` makes the shim
print the LIVE table out of the running game's memory: name, node, bit. Joining
them on the name is the only way to find out whether `group` really is the node,
and it is the difference between a verified mapping and a plausible one.

  wsl -e bash runbridge.sh ~/swmap.log 70 gpu     # with PAD_SW_MAP=3000 exported
  python3 devjoin.py ~/swmap.log

WHAT IT SETTLED. `group` maps to a node, but NOT by arithmetic. "group N is node
N+2" fits groups 6 and 7 and is wrong for everything else - groups 4 and 5 are
nodes 0 and 1. It is a small lookup:

    group 4 -> node 0      cabinet / CPU board
    group 5 -> node 1      cabinet front
    group 6 -> node 8      lower playfield   (LED connectors 8a / 8b / 8c)
    group 7 -> node 9      upper playfield   (LED connectors 9a / 9b / 9c)
    group 3, 8             topper, not on the playfield

For the LED rows the CONNECTOR STRING says it outright - "8b" is node 8
connector b - which is the signal to trust. Switch rows carry no connector, and
that is why the group column had to be checked against the live table instead.

`index` is a sequential position within the board, NOT the hardware bit: on node
8 the switches run bit 9,10,11..20 against index 8,9,10..19, and then the
hardware skips bits 21-23 while the index does not. Join on the NAME, never on
the number.
"""
import collections
import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import devicexy

LIVE = re.compile(r"\[swmap\] id=(\d+)\s+node=(\d+)\s+bit=(\d+).*?lvl=\d+ (.+)$")


def read_live(path):
    out = {}
    for line in open(path, "rb"):
        m = LIVE.search(line.decode("latin-1").rstrip())
        if m:
            out[m.group(4).strip().upper()] = (int(m.group(1)), int(m.group(2)),
                                               int(m.group(3)))
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    live = read_live(sys.argv[1])
    d, cs = devicexy.load()
    sw = [r for r in devicexy.records(d, cs) if r["kind"] == "switch"]
    print("live switches %d, device-table switches %d" % (len(live), len(sw)))

    pairs = collections.Counter()
    odd = []
    for r in sw:
        hit = live.get(r["name"].upper())
        if not hit:
            continue
        pairs[(r["group"], hit[1])] += 1
    for (g, n), c in sorted(pairs.items()):
        print("  group %d -> node %-2d  %3d switches" % (g, n, c))
    # any group that maps to more than one node is worth naming individually
    bygroup = collections.defaultdict(set)
    for (g, n) in pairs:
        bygroup[g].add(n)
    for g, ns in sorted(bygroup.items()):
        if len(ns) > 1:
            print("\n  group %d spans nodes %s - the exceptions:" % (g, sorted(ns)))
            major = max(ns, key=lambda n: pairs[(g, n)])
            for r in sw:
                hit = live.get(r["name"].upper())
                if hit and r["group"] == g and hit[1] != major:
                    print("    %-30s index %-4d node %d bit %d"
                          % (r["name"], r["index"], hit[1], hit[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
