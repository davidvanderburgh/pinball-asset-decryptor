#!/usr/bin/env python3
"""swtable.py <run.log> [title] - the switch list, from the shim's own dump.

Writes `games/<title>/switch_list.txt`: id, node, bit, name, one line per
switch, taken from the `[sw] id=` lines the shim prints when it reads (or
finds) the game's switch table.

WHY THIS EXISTS ALONGSIDE switchxy.py. switch_xy.txt has POSITIONS, and
positions come from a device table that only some titles ship - Godzilla Pro
1.15.0 has one and TMNT 1.59 has nothing of the kind, no `images/Test`
artwork and no XY records anywhere in its binary. The switch LIST, though, is
in every title, because the game cannot run without one: ids, node, bit and a
name in five languages.

So this is the lowest common denominator and the thing to fall back to. The
playfield window draws artwork when a title has it and a schematic when it does
not, and the schematic needs exactly these four columns.

  swtable.py ~/gztmnt.log turtles_pro
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gameinfo

LINE = re.compile(
    r"\[sw\] id=(\d+)\s+num=(\d+)\s+node=(\d+)\s+bit=(\d+)\s+"
    r"raw=\S+\s+logical=(\d+)\s+flags=0x([0-9a-f]+)\s*(.*)$")


def read(path):
    """[(id, num, node, bit, name)], last dump in the log wins."""
    out = {}
    for raw in open(path, "rb"):
        m = LINE.search(raw.decode("latin-1").rstrip("\r\n"))
        if not m:
            continue
        sid = int(m.group(1))
        name = m.group(7).strip() or "?"
        out[sid] = (sid, int(m.group(2)), int(m.group(3)), int(m.group(4)), name)
    return [out[k] for k in sorted(out)]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    rows = read(sys.argv[1])
    game = gameinfo.active(sys.argv[2] if len(sys.argv) > 2 else None)
    if not rows:
        print("no [sw] id= lines in %s.\n"
              "The shim prints them when it reads the switch table: run with\n"
              "PAD_SW_DUMP=1, or let sw_find_table() find it (it dumps on find)."
              % sys.argv[1])
        return 2

    named = sum(1 for r in rows if r[4] != "?")
    nodes = sorted({r[2] for r in rows})
    print("%s: %d switches, %d named, nodes %s"
          % (game, len(rows), named, nodes))

    lines = ["# %s switch list, from the shim's reading of the game's own table."
             % game,
             "# %d switches on nodes %s." % (len(rows), nodes),
             "# %-4s %-5s %-5s %-4s %s" % ("id", "num", "node", "bit", "name")]
    for sid, num, node, bit, name in rows:
        lines.append("%-6d %-5d %-5d %-4d %s" % (sid, num, node, bit, name))

    d = gameinfo.table_dir(game)
    if not os.path.isdir(d):
        os.makedirs(d)
    dest = os.path.join(d, "switch_list.txt")
    with open(dest, "w", newline="") as f:
        f.write("\n".join(lines) + "\n")
    print("-> %s" % dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
