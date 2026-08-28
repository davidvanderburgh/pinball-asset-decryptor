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


def read_list(path):
    """{NAME: (id, node, bit)} from an on-disk switch_list.txt.

    The run-free source (item 27): swnames.py fills the list's names from the
    device table in the binary, so a cached list carries real names on titles
    whose LIVE dump answers `?` for every row (jaws, led_zeppelin, elvira -
    their message-table address resolves wrong, which is the whole reason
    swnames exists). Rows still named `?` are skipped rather than joined."""
    out = {}
    for line in open(path):
        if line.startswith("#"):
            continue
        p = line.split()
        if len(p) < 5:
            continue
        try:
            sid, node, bit = int(p[0]), int(p[2]), int(p[3])
        except ValueError:
            continue
        name = " ".join(p[4:]).strip()
        if not name or name == "?":
            continue
        out[name.upper()] = (sid, node, bit)
    return out


def join(live, recs):
    """[(id, node, bit, record)] for every switch with BOTH an id and a position.

    `live` is {NAME: (id, node, bit)} from whichever dump was captured - the
    `[swmap]` lines read above, or the `[sw]` lines swtable.py reads. Either
    will do: this join only needs the id and the name, and both carry both.
    That matters because `[swmap]` needs `PAD_SW_MAP` set while `[sw]` is
    printed by every run, so requiring the first made switch positions depend on
    a deliberately-instrumented run rather than on any run at all.
    """
    rows = []
    # The LAYOUT image, not the literal "playfield" - that literal is one
    # title family's spelling (item 50: bond says `Test/scaled_playfield`,
    # beatles `Test/beatles_playfield`), and hard-coding it here made this
    # join return zero rows on every such title while their 50-odd named
    # switches sat one filter away. devicexy.layout_image() owns the choice,
    # and it is the same call playfield.py draws with, so a position joined
    # here is by construction on the image the window shows.
    img = devicexy.layout_image(recs)
    for r in recs:
        if r["kind"] != "switch" or r["image"] != img:
            continue
        hit = live.get(r["name"].upper())
        if hit:
            rows.append((hit[0], hit[1], hit[2], r))
    return sorted(rows)


def text(game, rows):
    """switch_xy.txt, as a string."""
    lines = ["# %s switch ID -> playfield position." % game,
             "# id from the running game's own switch table, position from the",
             "# device table in the binary, joined on the NAME.",
             "# %-4s %-4s %-4s %-32s %5s %5s"
             % ("id", "node", "bit", "name", "x", "y")]
    for sid, node, bit, r in rows:
        lines.append("%-6d %-5d %-5d %-32s %5d %5d"
                     % (sid, node, bit, r["name"], r["x"], r["y"]))
    return "\n".join(lines) + "\n"


def build(swmap_log, recs=None):
    live = read_live(swmap_log)
    if recs is None:
        recs = devicexy.build()
    return join(live, recs), live


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    game = gameinfo.active()
    if not game:
        print("no active title - set PAD_GAME, or start a run.")
        return 1
    rows, live = build(sys.argv[1])
    print("%d live switches, %d joined to a playfield position" % (len(live), len(rows)))

    # Default into the TITLE's table directory, not the cwd - these are per
    # title now and a second game must not overwrite the first one's.
    dest = sys.argv[2] if len(sys.argv) > 2 else gameinfo.table("switch_xy.txt", game)
    d = os.path.dirname(os.path.abspath(dest))
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(dest, "w", newline="") as f:
        f.write(text(game, rows))
    print("-> %s" % dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
