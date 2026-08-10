#!/usr/bin/env python3
"""nodecensus.py - which node-bus boards a title actually HAS, from its own binary.

    nodecensus.py                    # census for the active title
    nodecensus.py --game jaws_le
    nodecensus.py --elf ~/card/jaws_le-1_02_0/jaws_le/game
    nodecensus.py --silent           # just the PAD_NB_SILENT value, for watch.sh

WHAT THIS IS FOR. The shim answers the node bus for all 64 addresses, so every
address the game polls looks populated - including boards the machine does not
physically have. For ONE address that is not harmless. `hwshim.c` records the
disassembly: 0x39d554 makes slot 2 the one board whose "registered" bit is
`board[+144] != 0`, and board[+144] is computed at registration from the game's
own static config table, not from anything on the wire. A title with no devices
on node 2 therefore manufactures a board that can never register, and the game
sits on Tech Alerts forever. No bus reply can change that; the fix is for the
shim to stop answering for the address, which is what PAD_NB_SILENT does.

Which nodes to silence is PER TITLE, and that is the whole reason this file
exists. It used to be a `case "$GAME"` in watch.sh with exactly one entry
(godzilla_pro|godzilla_le -> 2), so Godzilla cleared its Tech Alerts and every
other title sat on one. That is what David hit on Jaws: "it got past the initial
service screen, but said node 2 wasn't registered".

★ SILENCING A NODE THAT IS POPULATED LOSES ITS DEVICES WITH NO MESSAGE AT ALL,
so this errs towards saying nothing. That is not a theoretical risk and the
counter-example is one of the titles on this disk: **John Wick LE names
connector `2a` on 288 of its 503 device records.** Its node 2 is real and full.
A "silence node 2" that was not per-title would have quietly cost John Wick 288
devices while looking like a fix, because the symptom it removes (a Tech Alert)
is loud and the symptom it creates (devices that are simply absent) is silent.

HOW A NODE IS IDENTIFIED, and the obvious way is WRONG. devicexy's own header
says "group N is node N+2", and that is Godzilla Pro's mapping rather than a
law. Measured across two titles:

    godzilla_pro   group 6 -> connectors 8a,8b,8c     group 7 -> 9a,9b,9c
    jaws_le        group 7 -> connectors 8a,8b,8c     group 8 -> 9a,9b,9c...

so the offset is +2 on one title and +1 on the next, and arithmetic on `group`
silently reads the wrong board on any title but the one it was derived from.
**The connector string names the board directly** - "8b" is board 8 - so that is
what is used here. It is also self-checking in a way the arithmetic is not: a
record either carries a connector or it does not.

THE GROUP IS STILL THE UNIT, because most records carry no connector at all -
451 of Godzilla's 575. Measured on four titles, **no group names more than one
board**, so the connectors inside a group identify the whole group and its
connectorless records come with it. Groups whose connectors name nothing are
reported as unattributed rather than folded into a total, because "boards this
census could not name" is exactly the residual risk in the decision below.

How well a group is named is PRINTED rather than thresholded, because a
threshold here would be a free parameter and this rig has already paid for one
of those (see ledcensus.py). The `named` column is how many of the group's
records carried a connector at all, and the spread is wide and real: Godzilla's
node 9 is 68 of 84, John Wick's node 2 is 287 of 288, and John Wick's cabinet
group is **1 of 12** - a single LOCKDOWN BUTTON-B carrying "2a" where its own -R
and -G siblings carry nothing, which is Stern filling in one channel of three
rather than an error. That lone record pulls the whole cabinet group onto node 2
in the totals below. It changes no decision - node 2 is already named 287 times
on that title - but a reader should be able to see it, so it is a column and not
a silent rounding.

WHICH WAY THE ERRORS FALL, and it is the safe way by construction. A stray or
misparsed connector can only ever ADD a node to the set considered present. A
false "present" costs nothing - the Tech Alert stays, exactly as it does today -
while a false "absent" costs devices. So the reading has to fail in a specific
and unlikely direction (every record of a real node-2 board carrying no
connector) before it can do harm, and the run log names what was decided so the
evidence is in the run rather than in this file.

Two independent labelled results say the connector reading is right, both from
facts this rig established elsewhere and neither of them from this file:

  * item 3's coil map found node 8 carrying coil indices 0..8 and node 9
    carrying one coil. Godzilla's records under connectors 8a/8b/8c hold
    exactly 9 coils, and those under 9a/9b/9c hold exactly 1.
  * hwshim.c's own measurement says Godzilla's node 2 has no devices of any
    kind. No Godzilla record names a connector on node 2.

AN EMPTY CENSUS MEANS "I COULD NOT SEE", NOT "THERE IS NOTHING THERE", and
conflating the two is how the John Wick failure above would happen by accident.
The device table is not readable on every title: of the seven on this disk,
`turtles_pro`, `led_zeppelin_le` and `star_wars_le` yield zero records and
`elvira3` yields 275 records that carry no connector string at all. (That reader
gap is item 29's, not this file's.) So a census that cannot find the I/O table
declines to silence anything, which leaves those titles behaving exactly as they
do today.

The trust test is that the census names at least one of the two PLAYFIELD boards,
8 or 9. Every Spike 2 has them - all three titles whose table reads name both -
so finding neither means the table was not read, however many records came back.
"""
import argparse
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import devicexy

#: A connector that names a board: "8b", "9a", "2a", and bare "8" if it ever
#: appears. Anything else - Godzilla's "CN4" on the topper strip - names a
#: connector on a board this scheme does not number, and is counted separately
#: rather than guessed at.
CONN_NODE = re.compile(r"^(\d+)[a-z]?$")

#: The playfield boards. Their presence is what says the I/O table was really
#: found; see the header. Not a list of "nodes that matter" - node 2 is what
#: matters - but of nodes whose ABSENCE means the reading failed.
PLAYFIELD_NODES = (8, 9)

#: The only node worth silencing, per hwshim.c's 0x39d554: the one board whose
#: registered bit is board[+144] != 0, so the one that an empty config table can
#: strand. Deliberately not "every node with no devices" - silencing costs
#: devices when it is wrong, and no other node has this failure mode.
CANDIDATES = (2,)


def group_node(recs):
    """{group: node or None} - the board each group's connectors name.

    Measured on godzilla_pro, jaws_le, john_wick_le and elvira3: no group names
    more than one board. If one ever does, the group is left unattributed rather
    than a winner being picked, because picking one would be the arithmetic
    mistake this file exists to avoid, just with extra steps.
    """
    named = collections.defaultdict(set)
    for r in recs:
        m = CONN_NODE.match(r["conn"] or "")
        if m:
            named[r["group"]].add(int(m.group(1)))
    return {g: (next(iter(n)) if len(n) == 1 else None)
            for g, n in named.items()}


def census(game=None, elf_path=None):
    """(nodes, unattributed, total) from the title's binary alone.

    `nodes` is {node: Counter} over every record in every group that names that
    board - the connectorless ones included, per the header. `unattributed` is
    {group: Counter} for the boards this census could not name; they are real
    devices on real nodes and reporting them as a total of zero would be a lie
    of exactly the kind that makes a silencing decision unsafe.
    """
    recs = devicexy.build(game=game, elf_path=elf_path)
    gnode = group_node(recs)
    nodes = collections.defaultdict(collections.Counter)
    unattributed = collections.defaultdict(collections.Counter)
    for r in recs:
        node = gnode.get(r["group"])
        bucket = nodes[node] if node is not None else unattributed[r["group"]]
        bucket[r["kind"]] += 1
        bucket["total"] += 1
        if CONN_NODE.match(r["conn"] or ""):
            bucket["named"] += 1
    return nodes, unattributed, len(recs)


def readable(counts):
    """Whether this census actually found the I/O table. See the header."""
    return any(n in counts for n in PLAYFIELD_NODES)


def switch_nodes(game=None, table_path=None):
    """{node: switch count} from the title's switch_list.txt, or {}.

    THE SECOND-BEST EVIDENCE, and it exists because the best evidence is
    missing on real titles. star_wars_le, led_zeppelin_le and turtles_pro yield
    ZERO device records, so the census above declines and they keep the fault -
    and David's 2026-08-10 recording is what that costs: Star Wars sitting on
    `Check Node Board 2 : Not Registered`, flickering, unplayable, because the
    safe direction left it exactly as broken as before.

    The switch list is available where the device table is not: it comes from
    the shim's own dump of the running game's table, so it needs a previous run
    of the title but no address and no parsing of the binary.
    """
    path = table_path or gameinfo.table("switch_list.txt", game)
    out = collections.Counter()
    try:
        with open(path) as f:
            for line in f:
                if line.startswith("#"):
                    continue
                fields = line.split(None, 4)
                if len(fields) >= 4:
                    out[int(fields[2])] += 1
    except (OSError, TypeError, ValueError):
        return {}
    return dict(out)


def silent_nodes(counts, swnodes=None):
    """The nodes the shim should NOT answer for, and why, as (list, reason).

    Two sources, and the weaker one is used ONLY when the stronger is absent.
    Returns an empty list whenever neither can support the claim, which is the
    safe direction: an extra board answering is a Tech Alert you can see and
    then explain, where a silenced board that exists is devices that vanish.
    """
    if readable(counts):
        absent = [n for n in CANDIDATES if n not in counts]
        if not absent:
            return [], ("every candidate board is populated (%s), so nothing "
                        "is silenced" % ", ".join(
                            "node %d: %d devices" % (n, counts[n]["total"])
                            for n in CANDIDATES))
        return absent, ("no device names a connector on %s, and this title's "
                        "own config is what decides the board's registered bit"
                        % ", ".join("node %d" % n for n in absent))

    # FALLBACK: the switch list. WEAKER, AND HERE IS EXACTLY HOW IT COULD BE
    # WRONG, so that nobody has to rediscover it - john_wick_le's node 2 carries
    # 288 LEDs and NOT ONE SWITCH. On that title this test would say "absent"
    # and cost 288 devices. It is safe only because john_wick_le's device table
    # READS, so this branch is never reached for it; the risk that remains is a
    # title with an unreadable device table AND a switch-free populated node 2.
    # No such title is known. It is written down rather than guarded against
    # because there is nothing left to test it with.
    swnodes = swnodes or {}
    if not any(n in swnodes for n in PLAYFIELD_NODES):
        return [], ("neither the device table nor a switch list could be read "
                    "(no board %s in either), so nothing is silenced"
                    % " or ".join(str(n) for n in PLAYFIELD_NODES))
    absent = [n for n in CANDIDATES if n not in swnodes]
    if not absent:
        return [], ("the device table did not read; the switch list puts %s, "
                    "so nothing is silenced" % ", ".join(
                        "%d switches on node %d" % (swnodes[n], n)
                        for n in CANDIDATES if n in swnodes))
    return absent, ("the device table did not read, so this is off the SWITCH "
                    "LIST alone, which has no switch on %s - weaker evidence, "
                    "see nodecensus.silent_nodes()"
                    % ", ".join("node %d" % n for n in absent))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game", help="title name; default is the active one")
    ap.add_argument("--elf", help="the game binary, for a title that is not "
                                  "extracted and has no run published yet")
    ap.add_argument("--switches", help="switch_list.txt, for the fallback when "
                                       "the device table cannot be read")
    ap.add_argument("--silent", action="store_true",
                    help="print only the PAD_NB_SILENT value (may be empty)")
    a = ap.parse_args()

    try:
        counts, unattributed, total = census(a.game, a.elf)
    except (OSError, SystemExit) as e:
        # A census that cannot run must not stop a run starting, and it must
        # still get to the switch-list fallback: the titles whose binary cannot
        # be parsed are exactly the ones that need it.
        counts, unattributed, total = {}, {}, 0
        if not a.silent:
            print("no device table: %s" % e, file=sys.stderr)

    sw = switch_nodes(a.game, a.switches)
    nodes, why = silent_nodes(counts, sw)

    if a.silent:
        print(",".join(str(n) for n in nodes))
        return 0

    print("%d device records" % total)
    print("%-8s %-7s %-6s %-6s %-6s %s"
          % ("node", "switch", "coil", "led", "total", "named"))
    for node in sorted(counts):
        c = counts[node]
        print("%-8s %-7d %-6d %-6d %-6d %d/%d" % (
            node, c["switch"], c["coil"], c["led"], c["total"],
            c["named"], c["total"]))
    for grp in sorted(unattributed):
        c = unattributed[grp]
        print("%-8s %-7d %-6d %-6d %-6d %d/%d" % (
            "grp%d?" % grp, c["switch"], c["coil"], c["led"], c["total"],
            c["named"], c["total"]))
    print()
    if sw:
        print("switch list: %s" % " ".join(
            "node %d: %d" % (n, c) for n, c in sorted(sw.items())))
    print("table read: %s" % ("yes" if readable(counts) else "NO"))
    if unattributed:
        print("unnamed boards: %d group(s), %d devices - real devices whose "
              "board this census cannot name" % (
                  len(unattributed),
                  sum(c["total"] for c in unattributed.values())))
    print("silence: %s" % (",".join(str(n) for n in nodes) or "nothing"))
    print("because: %s" % why)
    return 0


if __name__ == "__main__":
    sys.exit(main())
