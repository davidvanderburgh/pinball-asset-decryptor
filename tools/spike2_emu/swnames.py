#!/usr/bin/env python3
"""swnames.py - real names for a title whose switch dump comes back all `?`.

    swnames.py --game jaws_le --log ~/jawswatch.log     # what it would fill
    swnames.py --elf ~/card/jaws_le-1_02_0/jaws_le/game --table .../switch_list.txt

THE PROBLEM. The shim reads each switch's name through `msg_row()`, which needs
a per-title message-table address; on most titles that resolves wrong and every
name comes back `?`. Measured: Led Zeppelin LE 96/96 `?`, Elvira's HoH 109/109,
Jaws LE 108/108 - against John Wick LE 0/105, Star Wars LE 0/104 and Godzilla.
So the reader works and the ADDRESS is what is wrong (item 29).

**This does not fix the reader. It gets the names from somewhere else entirely**,
which turns out to be enough and needs no run: the same DEVICE TABLE devicexy.py
already parses carries a name for every playfield switch, as plain strings in the
ELF. What it does not carry is the switch ID, and that is the whole difficulty.

WHY THE JOIN LOOKS IMPOSSIBLE AND IS NOT. Item 29 ruled out joining on the
NUMBER, correctly, quoting switchxy.py: the device table's `index` is a
sequential position within its board, not the hardware bit, so "a numeric join
produces a map that looks right and presses the wrong switch". Both halves of
that are true. But the two sequences are the SAME PHYSICAL ORDER, so within one
node the k-th switch by `index` is the k-th by `bit` - and the join is on ORDER,
not on value.

Measured, and the two titles disagree about the value in exactly the way that
kills the naive version:

    jaws_le        node 8   index == bit   (gaps included: 11 -> 14 on both)
    godzilla_pro   node 8   index == bit - 1

THE OFFSET IS THEREFORE DISCOVERED PER NODE, NOT ASSUMED, and it is what makes
the join self-checking. `_offset()` picks the shift that lands the most device
indices on real hardware bits and then REQUIRES it to place every device record
on that node. A node where no single shift does that is refused and left `?`,
which is the safe direction: a wrong name here is a marker that presses the
wrong switch, and item 29's warning about that stands.

VALIDATED ON THE TWO TITLES THAT ALREADY HAVE REAL NAMES, before it was used on
one that does not: **godzilla_pro 41/41 and john_wick_le 57/57, 98/98 = 100%**,
comparing the name this produces against the name the game itself reported.
That is the whole reason to trust it on Jaws, where there is nothing to check
against.

WHAT IT UNBLOCKS, concretely: Jaws's trough comes out as ids 60..65 (TROUGH 6
down to TROUGH 1) and TROUGH JAM as 66, against Godzilla's 66..71 and 72. Every
ball tool in this rig - plunge.py, swinit.py - had Godzilla's ids written in, so
on Jaws they closed six switches the game does not watch and it ball-searched
for ever. That is what stopped a game starting on any title but Godzilla.

THE PLATFORM SWITCHES ARE A DIFFERENT ANIMAL and are handled separately. Nodes
0, 1 and 4 are the CPU board, the cabinet and the QR scanner - Spike 2 hardware,
not playfield - and they carry no connector, so no device record names them.
They do not need one: their (node, bit) layout is **identical on all three
titles measured, spanning 2017 to 2024** (star_wars_le 1.30.0, godzilla_pro
1.15.0, john_wick_le 1.01.0), 45 switches each. So PLATFORM below is a fallback
LABEL keyed on (node, bit).

**It is a generic label and not the title's own word, and the difference is
real:** node 1 bit 2 is "Action Button" on Godzilla and "LOCKDOWN BUTTON" on
Star Wars - one physical button that games rename. A title's own name always
wins; this only fills a `?`.
"""
import argparse
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import devicexy
import gameinfo
# NOT `import swtable` at module scope: swtable imports THIS module to fill its
# names, so a top-level import here is a cycle. main() needs it, nothing else
# does, so it is imported there.

CONN_NODE = re.compile(r"^(\d+)[a-z]?$")

#: (node, bit) -> generic label, for the Spike 2 boards that ship with every
#: machine. Read off godzilla_pro 1.15.0 and confirmed position-for-position on
#: john_wick_le 1.01.0 and star_wars_le 1.30.0. See the header for why these are
#: labels rather than the title's own names.
PLATFORM = {
    (0, 0): "DIP 1", (0, 1): "DIP 2", (0, 2): "DIP 3", (0, 3): "DIP 4",
    (0, 4): "DIP 5", (0, 5): "DIP 6", (0, 6): "DIP 7", (0, 7): "DIP 8",
    (0, 8): "Service Select", (0, 9): "Service Plus",
    (0, 10): "Service Minus", (0, 11): "Service Back",
    (0, 16): "Headphone Detect", (0, 17): "Headphone Kit Cable Detect",
    (0, 18): "Volume Encoder 1", (0, 19): "Volume Encoder 2",
    (0, 23): "Coin Door Power Interlock",
    (1, 2): "Action Button", (1, 8): "Ticket Notch", (1, 11): "Start Button",
    (1, 12): "Tournament Start Button", (1, 14): "Tilt Pendulum",
    (1, 16): "Left Coin", (1, 17): "Center Coin", (1, 18): "Right Coin",
    (1, 19): "Fourth Coin", (1, 20): "Fifth Coin", (1, 21): "Sixth Coin",
    (1, 22): "Slam Tilt",
    (4, 0): "QR Scanner Status Ready", (4, 1): "QR Scanner Status String",
    (4, 2): "QR Scanner Status Encoded Data",
    (4, 3): "QR Scanner Status Missed String",
    (4, 4): "QR Scanner Status Overrun",
    (4, 5): "QR Scanner Status Unsupported AP",
    (4, 6): "QR Scanner Status FIFO Overrun",
    (4, 7): "QR Scanner Status Config", (4, 8): "QR Scanner Status Error",
    (4, 9): "QR Scanner Status Err1", (4, 10): "QR Scanner Status Err2",
    (4, 11): "QR Scanner Status Err3", (4, 12): "QR Scanner Status Err4",
    (4, 13): "QR Scanner Status Err5", (4, 14): "QR Scanner Status Err6",
    (4, 15): "QR Scanner Status No Reader",
}


def _fit(recs, bits_by_node, names):
    """The one (node, shift) a group's device indices ALL land on, or None.

    ★ THE FALLBACK FOR A TABLE WITH NO CONNECTOR COLUMN (2026-08-28). An
    artwork-less device table - devicexy.BLANK_IMAGE, led_zeppelin_le - carries
    the class, the (group, index) and the name, and NOTHING else: no image, no
    position, no part number and no connector. So `device_switches()`'s rule
    below, which reads the node off the connector and is right to, has nothing
    to read and every group goes unresolved.

    NOT CIRCULAR, which is the first thing to check because swnames writes the
    names that other derivations in this rig join back on. The device table
    supplies (group, index); the SHAPE it is matched against - which bits are
    live on which node - comes from the shim's reading of the running game's
    own switch table, and the device table knows nothing about it. Only the
    NAME column of that table is `?`, and nothing here reads the name column
    except as a tiebreak among candidates the bits have already admitted.

    WHY NOT coilmap.group_node(), which is this rig's home for group -> node:
    it answers for COILS, from the node directory's ascending pinnodes, and on
    this title it cannot answer at all - led_zeppelin_le has three playfield
    pinnodes {8, 9, 12} against two switch groups {7, 8}, so the ascending rule
    bails on the count mismatch exactly as it does on Bond and falls back to
    godzilla's constant, which reads group 7 as node 9. Group 7 is node 8 here.
    A constant from another title is precisely what must not decide this.

    THE BITS DECIDE, and on this title they are decisive on their own: group 7
    holds 32 indices and node 8 holds exactly those 32 bits, group 8 holds 18 of
    node 9's 19. Measured, every group resolves to ONE (node, shift):

        group 2 -> node 4   group 4 -> node 0   group 5 -> node 1
        group 7 -> node 8   group 8 -> node 9

    Groups 4 and 5 also fit node 8 under a shift, and there the NAME is what
    separates them - 16 of group 4's names are already on node 0 (DIP 1..8,
    SERVICE SELECT/PLUS/MINUS/BACK ...), none on node 8. A tie that names
    cannot break is REFUSED and left `?`, which is this module's standing rule:
    a wrong name here is a marker that presses the wrong switch.
    """
    idx = {r["index"] for r in recs}
    if not idx:
        return None
    fits = []
    for node, bits in sorted(bits_by_node.items()):
        for shift in sorted({b - i for b in bits for i in idx}):
            if not all(i + shift in bits for i in idx):
                continue
            # Agreement is scored, not required: on a node the game DID name,
            # a real pairing agrees on most rows, and the odd disagreement is
            # a generic PLATFORM label meeting the title's own word for the
            # same button ("Action Button" / "LOCKDOWN BUTTON").
            agree = 0
            for r in recs:
                have = names.get((node, r["index"] + shift))
                if have and have != "?":
                    agree += 1 if have.upper() == r["name"].upper() else -1
            fits.append((agree, node, shift))
    if not fits:
        return None
    fits.sort(key=lambda f: -f[0])
    if len(fits) > 1 and fits[0][0] == fits[1][0]:
        return None                 # nothing separates them - refuse, not guess
    return fits[0][1], fits[0][2]


def device_switches(game=None, elf_path=None, bits_by_node=None, names=None):
    """{node: [device record]} for CLASS-1 (switch) records, sorted by index.

    The node comes from the CONNECTOR string, never from arithmetic on `group`:
    nodecensus.py's header has the measurement that killed `group + 2`. A table
    that carries no connector at all falls through to `_fit()`, which matches
    the group's indices against the live wire instead; the connector still wins
    wherever there is one, so a title that resolved before this existed
    resolves exactly as it did.
    """
    recs = devicexy.build(game=game, elf_path=elf_path)
    named = collections.defaultdict(set)
    for r in recs:
        m = CONN_NODE.match(r["conn"] or "")
        if m:
            named[r["group"]].add(int(m.group(1)))
    gnode = {g: (next(iter(n)) if len(n) == 1 else None)
             for g, n in named.items()}
    by_group = collections.defaultdict(list)
    for r in recs:
        if r["cls"] == 1:
            by_group[r["group"]].append(r)
    for group, grecs in sorted(by_group.items()):
        if gnode.get(group) is None and bits_by_node:
            hit = _fit(grecs, bits_by_node, names or {})
            if hit:
                gnode[group] = hit[0]
    out = collections.defaultdict(list)
    for group, grecs in by_group.items():
        if gnode.get(group) is not None:
            out[gnode[group]].extend(grecs)
    for node in out:
        out[node].sort(key=lambda r: r["index"])
    return out


def _offset(dev, bits):
    """The single shift that maps EVERY device index onto a real bit, or None.

    Requiring all of them is the guard, not a nicety. The device table can hold
    fewer switches than the wire does - Jaws's node 9 has 39 records against 42
    live switches, the extra three sitting at bits 61-63 - and a shift that
    explained only most of them would be a shift that had silently paired the
    wrong ones.
    """
    if not dev:
        return None
    want = {r["index"] for r in dev}
    best, best_n = None, 0
    for cand in {b - r["index"] for b in bits for r in dev}:
        n = sum(1 for i in want if i + cand in bits)
        if n > best_n:
            best, best_n = cand, n
    return best if best_n == len(want) else None


def fill(rows, game=None, elf_path=None):
    """Fill `?` names in swtable rows. Returns (rows, [report lines]).

    Never overwrites a name the game itself supplied: a title that can read its
    own message table is the better authority, and this must not quietly replace
    "LOCKDOWN BUTTON" with "Action Button".
    """
    unknown = [r for r in rows if r[4] == "?"]
    if not unknown:
        return rows, ["every switch already has the game's own name"]

    report = []
    bits_by_node = collections.defaultdict(set)
    for _sid, _num, node, bit, _name in rows:
        bits_by_node[node].add(bit)

    names_by_wire = {(node, bit): name
                     for _sid, _num, node, bit, name in rows}
    try:
        dev = device_switches(game, elf_path, bits_by_node, names_by_wire)
    except (OSError, SystemExit) as e:
        dev = {}
        report.append("no device table (%s)" % e)

    named = {}
    for node, drecs in sorted(dev.items()):
        off = _offset(drecs, bits_by_node.get(node, set()))
        if off is None:
            report.append("node %d: %d device records, but no single index->bit "
                          "shift covers them all - left as ?"
                          % (node, len(drecs)))
            continue
        for r in drecs:
            named[(node, r["index"] + off)] = r["name"]
        report.append("node %d: %d names from the title's device table "
                      "(index -> bit %+d)" % (node, len(drecs), off))

    out, from_dev, from_plat = [], 0, 0
    for sid, num, node, bit, name in rows:
        if name == "?":
            if (node, bit) in named:
                name = named[(node, bit)]
                from_dev += 1
            elif (node, bit) in PLATFORM:
                name = PLATFORM[(node, bit)]
                from_plat += 1
        out.append((sid, num, node, bit, name))

    still = sum(1 for r in out if r[4] == "?")
    report.append("filled %d of %d unnamed: %d from this title's device table, "
                  "%d generic platform labels, %d still ?"
                  % (from_dev + from_plat, len(unknown), from_dev, from_plat,
                     still))
    return out, report


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game")
    ap.add_argument("--elf")
    ap.add_argument("--log", help="a run log to read the [sw] dump from")
    ap.add_argument("--table", help="an existing switch_list.txt instead")
    a = ap.parse_args()

    if a.log:
        import swtable
        rows = swtable.read(a.log)
    else:
        path = a.table or gameinfo.table("switch_list.txt", a.game)
        rows = []
        for line in open(path):
            if line.startswith("#"):
                continue
            f = line.split(None, 4)
            if len(f) >= 5:
                rows.append((int(f[0]), int(f[1]), int(f[2]), int(f[3]),
                             f[4].strip()))
    if not rows:
        print("no switch rows", file=sys.stderr)
        return 2

    out, report = fill(rows, a.game, a.elf)
    for line in report:
        print("  %s" % line)
    print()
    for sid, _num, node, bit, name in out:
        print("%-5d node=%-3d bit=%-3d %s" % (sid, node, bit, name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
