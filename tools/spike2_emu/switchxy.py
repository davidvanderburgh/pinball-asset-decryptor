#!/usr/bin/env python3
"""switchxy.py <swmap.log> [out.txt] - switch ID -> playfield position.

The clickable half of the virtual playfield. The device table in the binary
gives every switch a name and a position; `PAD_SW_MAP` gives the running game's
switches an ID, a node and a bit. Joining them on the NAME gives what a UI needs:
click at (x, y) -> press switch ID -> the game sees it.

JOIN ON THE NAME, NOT THE NUMBER. The device table's `index` is a sequential
position within its board and not the hardware bit - on node 8 the switches run
bit 9,10,11..20 against index 8,9,10..19 and then the hardware skips 21-23 while
the index does not. Matching on the number produces a map that looks right and
presses the wrong switch.

Names differ in case between the two sources ("Left Spinner" live, "LEFT SPINNER"
static), so the match is case-insensitive.
"""
import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import devicexy
import gameinfo

LIVE = re.compile(r"\[swmap\] id=(\d+)\s+node=(\d+)\s+bit=(\d+).*?lvl=\d+ (.+)$")


def read_live(path):
    out = {}
    for line in open(path, "rb"):
        m = LIVE.search(line.decode("latin-1").rstrip())
        if m:
            out[m.group(4).strip().upper()] = (int(m.group(1)), int(m.group(2)),
                                               int(m.group(3)))
    return out


def build(swmap_log):
    live = read_live(swmap_log)
    d, cs = devicexy.load()
    rows = []
    for r in devicexy.records(d, cs):
        if r["kind"] != "switch" or r["image"] != "playfield":
            continue
        hit = live.get(r["name"].upper())
        if hit:
            rows.append((hit[0], hit[1], hit[2], r))
    return sorted(rows), live


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    rows, live = build(sys.argv[1])
    print("%d live switches, %d joined to a playfield position" % (len(live), len(rows)))

    lines = ["# Godzilla Pro switch ID -> playfield position.",
             "# id from the running game (PAD_SW_MAP), position from the device",
             "# table in the binary, joined on the NAME.",
             "# %-4s %-4s %-4s %-32s %5s %5s" % ("id", "node", "bit", "name", "x", "y")]
    for sid, node, bit, r in rows:
        lines.append("%-6d %-5d %-5d %-32s %5d %5d"
                     % (sid, node, bit, r["name"], r["x"], r["y"]))
    text = "\n".join(lines) + "\n"
    # Default into the TITLE's table directory, not the cwd - these are per
    # title now and a second game must not overwrite the first one's.
    dest = sys.argv[2] if len(sys.argv) > 2 else gameinfo.table("switch_xy.txt")
    d = os.path.dirname(os.path.abspath(dest))
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(dest, "w", newline="") as f:
        f.write(text)
    print("-> %s" % dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
