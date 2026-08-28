#!/usr/bin/env python3
"""coilmap.py - which (node, index) on the wire is which COIL, in one place.

THE FIRE FRAME NAMES A COIL BY INDEX AND NOTHING ELSE. `cmd 0x40` carries a
node and an index (coildecode.py has the frame), and the index is the device
table's own - so turning "something fired on node 8 index 1" into "the game
asked for a ball" needs the title's device table and the group -> node lookup.
Both already existed, in two copies: `GROUP_NODE` in playfield.py and again in
coildecode.py, and the coil row parse in playfield.py alone. This module is
that fact stated once, which is the rig's standing rule (alive.sh vs
killgame.sh, autoattract.sh vs status.sh - both drifted rather than broke).

IT READS device_xy.txt, NOT THE ELF, and that is what makes it usable from
WSL. coildecode.py's `coil_names()` goes through devicexy.load(), which needs
the game binary and a couple of linear passes over it; the built table says the
same thing in a text file that mktables.py has already written beside the
switch list. ballfeed.py runs inside WSL in a poll loop and cannot afford
either the binary or - like every other WSL-side helper - an import of
playfield.py, which needs tkinter this WSL does not have.

THE INDEX->NAME MAPPING IS CONFIRMED, 5 POSITIVE AND 4 NEGATIVE, and it is
worth writing down because item 21b was filed believing the trough eject was
unknown. Item 3's ball search (see coildecode.py) made the game label its own
experiment: on godzilla_pro it fired indices 2, 3, 4, 7 and 8, and this table
names those RIGHT SLINGSHOT, LEFT SLINGSHOT, AUTO PLUNGER, POP BUMPER and
RIGHT SCOOP - exactly the coils a ball search fires. It did NOT fire 0, 1, 5
or 6, which this table names RIGHT FLIPPER, TROUGH, LEFT FLIPPER and UP LEFT
FLIP - exactly the coils a ball search must not fire. So `TROUGH` at index 1
is the eject, on a mapping that scored 9 of 9 against a labelled run.

THE NODE IS PER TITLE, so nothing here hard-codes 8. godzilla_pro keeps its
playfield coils in group 6 (node 8) and its magnet in group 7 (node 9);
jaws_le uses group 7 for the same set (node 8) and group 8 for its toys
(node 9); james_bond_60th_le uses groups 8 and 9, which godzilla's map has no
key for at all. group_node() derives the mapping per title and says how.

A GROUP NOTHING CAN RESOLVE STILL COMES BACK None RATHER THAN A GUESS, and
that has not changed - it is now rarer and better evidenced, not softer.
"""
import collections
import os
import re
import struct

#: A connector cell that NAMES ITS NODE: "8", "8b", "9a". The device table
#: writes the board number into the connector for the devices that are wired
#: to a numbered node board, and swnames.py and nodecensus.py already read it
#: exactly this way - "the node comes from the CONNECTOR string, never from
#: arithmetic on `group`". This is the third copy of the pattern and the two
#: existing ones are unchanged; see connector_group_node() for what it buys.
CONN_NODE = re.compile(r"^(\d+)[a-z]?$")

#: Written into every derived table; LF on Windows too, like _write() does.
NEWLINE = chr(10)

#: Device-table group -> node on the bus. Verified by ledio.py against the
#: boot enumeration, and now stated ONCE - playfield.py and coildecode.py
#: import it from here.
#:
#: THIS IS GODZILLA'S MAP AND THE GROUPS SHIFT PER TITLE - it is the fallback
#: now, not the answer; see group_node() below.
GROUP_NODE = {4: 0, 5: 1, 6: 8, 7: 9}

#: Groups 4 and 5 are the CPU and the cabinet on every title measured, so only
#: the playfield groups (>= 6) move. Kept beside GROUP_NODE so the two halves
#: of the same fact sit together.
FIXED_GROUPS = {4: 0, 5: 1}


def parse_rows(lines):
    """EVERY device_xy.txt row, not just the coils, as dicts.

    The group -> node derivations below need the SWITCH and LED rows too - the
    switches because the running game names their node, the connectors because
    a lamp row carries one where a coil row never does (every coil connector on
    this disk is "-"). parse() below still returns coils alone; this is the
    shared reader underneath it, so the field-counting rule that has already
    cost one release lives in exactly one place.
    """
    out = []
    for line in lines:
        if line.startswith("#") or not line.strip():
            continue
        p = line.split()
        if len(p) < 10:
            continue
        try:
            row = dict(kind=p[0], name=" ".join(p[1:-8]), x=int(p[-8]),
                       y=int(p[-7]), group=int(p[-4]), index=int(p[-3]),
                       conn=p[-2], image=p[-1], node=None)
        except ValueError:
            continue
        out.append(row)
    return out


def switch_group_node(dev_rows, switch_lines):
    """{group: node} measured by joining SWITCH NAMES to the running game.

    THE STRONGEST EVIDENCE AVAILABLE, because it is the game answering. The
    device table gives a switch a NAME and a GROUP; the title's own switch
    table - which the shim reads out of the running game and mktables.py
    writes to switch_list.txt - gives the same name a NODE. Joining on the
    name therefore says which node a group is on without assuming anything
    about the numbering, which is the whole fault this module had.

    IT IS THE SAME JOIN switchxy.py ALREADY MAKES, for positions, and for the
    same stated reason: the device table's `index` is not the hardware bit, so
    a numeric join "produces a map that looks right and presses the wrong
    switch". Names are matched upper-cased and trimmed, like by_name() above.

    NOT CIRCULAR, and it was worth checking before relying on it: swnames.py
    fills a `?` switch list from the device table, so a filled name joined back
    could in principle just re-derive whatever it assumed. It does not - it
    resolves the node from the CONNECTOR string, "never from arithmetic on
    `group`" (swnames.device_switches) - so the two derivations here rest on
    the same independent column rather than on this module's constant.

    Rows whose name is `?` are skipped: an unnamed switch cannot be joined, and
    the titles that have them (elvira3, 109/109) simply get no answer here.
    A group whose switches disagree about their node takes the majority, which
    on every title on this disk is unanimous.
    """
    live = {}
    for line in switch_lines or []:
        if line.startswith("#"):
            continue
        p = line.split()
        if len(p) < 5:
            continue
        try:
            node = int(p[2])
        except ValueError:
            continue
        name = " ".join(p[4:]).strip().upper()
        if name and name != "?":
            live[name] = node
    if not live:
        return {}
    votes = collections.defaultdict(collections.Counter)
    for r in dev_rows or []:
        if r.get("kind") != "switch":
            continue
        node = live.get((r.get("name") or "").upper().strip())
        if node is not None:
            votes[r["group"]][node] += 1
    return {g: c.most_common(1)[0][0] for g, c in votes.items()}


def connector_group_node(dev_rows):
    """{group: node} from the device table's own CONNECTOR column.

    The second derivation, and it is INDEPENDENT of the first: it needs no run,
    no switch table and no live game, so it answers on the titles whose switch
    names come back `?` and which the join above cannot touch at all
    (king_kong_le, metallica_spike, james_bond_le on this disk).

    A GROUP THAT NAMES TWO NODES IS DROPPED, NOT GUESSED. On
    dungeons_and_dragons_le groups 7 and 8 each carry connectors for BOTH node
    8 and node 9, so this returns nothing for them and the switch join - which
    answers 7 -> 8, the value that title's own Single Coil Test page prints -
    is what decides. That is the ambiguity this rule exists to admit to.

    PLAYFIELD GROUPS ONLY (>= 6). Groups 4 and 5 are the CPU and the cabinet on
    every title measured, FIXED_GROUPS pins them, and the connector column
    disagrees on three titles here - john_wick_le, king_kong_le and
    metallica_spike all put a connector "2" on a group-5 row, against a switch
    join that says node 1 on every title it can answer for. Reading connectors
    for those groups would import that error for the two titles where nothing
    contradicts it.
    """
    seen = collections.defaultdict(set)
    for r in dev_rows or []:
        if r["group"] < 6:
            continue
        m = CONN_NODE.match(r.get("conn") or "")
        if m:
            seen[r["group"]].add(int(m.group(1)))
    return {g: next(iter(n)) for g, n in seen.items() if len(n) == 1}


def group_node(rows, nodedir_path=None, dev_rows=None,
               switch_lines=None):
    """Build this TITLE's group -> node map, falling back to GROUP_NODE.

    WHY THIS IS NOT A CONSTANT, measured 2026-08-27 on dungeons_and_dragons_le.
    Its device table puts the TROUGH in group 7, and the static map above -
    godzilla's - reads group 7 as node 9. The game itself says otherwise: its
    Single Coil Test page for that very coil prints "Node: 8 - Lower Playfield"
    and "Address: 8-DR-1". So ballfeed.py sat watching node 9 index 1 for an
    eject that can only ever arrive on node 8, which is the coil half of why
    that title never fed a ball. godzilla is not wrong either - its playfield
    coils really are group 6 - the GROUPS THEMSELVES SHIFT between titles, and
    a constant cannot be right for both.

    THE RULE, and it reproduces the labelled example rather than replacing it:
    the playfield coil groups (>= 6), ascending, map onto the title's own
    PLAYFIELD node boards, ascending. The node list is the title's declared
    node directory (node_ident.txt, from nbdir.py) filtered to `pinnode`
    boards past the cabinet - which is exactly the set that carries coils.

        godzilla_pro : groups {6,7} -> nodes {8,9}   (6->8, 7->9)  = GROUP_NODE
        dnd 1.00     : groups {7,8} -> nodes {8,9}   (7->8, 8->9)  = the game's
                                                                     own answer

    Anything the rule cannot decide - no directory, no coil rows, or a count
    mismatch between groups and boards - keeps GROUP_NODE, so a title that
    worked before this existed still resolves exactly as it did.

    ---- ITEM 53: TWO MEASURED SOURCES ABOVE THE RULE ------------------------

    The ascending rule is an INFERENCE, and it cannot answer at all for a title
    whose group count and board count differ - james_bond_60th_le has playfield
    coil groups {8, 9} against three playfield pinnodes {7, 8, 9}, so it fell
    straight back to godzilla's constant, which knows neither group. The result
    was 0 of its 73 playfield lamps and 0 of its 16 coils having a wire
    address, drawn dark on a complete piece of artwork, while the shim decoded
    36351 lamp writes on exactly the nodes those devices are on.

    So two sources that MEASURE the mapping are consulted first:

      1. switch_group_node() - the running game's own switch table, joined on
         the name. The game is the authority and this wins on disagreement.
      2. connector_group_node() - the device table's connector column. Needs
         no run, so it answers where (1) cannot.

    THEY AGREE, and that is the argument for trusting either. On every title on
    this disk where both can answer - beatles, deadpool_pro, godzilla_pro,
    godzilla_le, james_bond_60th_le, jaws_le, john_wick_le - the two derivations
    return the SAME node for every playfield group they share. Two derivations
    from unrelated columns agreeing is the same standard ledio.py already holds
    the boot enumeration to, and it is why this ships without a wire capture.

    WHAT THEY DERIVE, measured 2026-08-28 at the desk:

        godzilla_pro / godzilla_le : 6 -> 8, 7 -> 9   IDENTICAL to GROUP_NODE
        james_bond_60th_le         : 8 -> 8, 9 -> 9, 10 -> 12
        jaws_le / deadpool_pro     : 7 -> 8, 8 -> 9
        dungeons_and_dragons_le    : 7 -> 8, 8 -> 9, 9 -> 10

    ★ WHEN A TITLE MEASURES ITS OWN MAP, GODZILLA'S IS DROPPED RATHER THAN
    USED TO FILL THE GAPS, and Bond is why. Its group 7 is 24 BACKBOX lamps;
    GROUP_NODE reads group 7 as node 9, which on Bond is a PLAYFIELD board - so
    every backbox swatch was rendering playfield values under backbox labels.
    A wrong address is worse than a known-missing one: this item exists because
    one title's answer stood in for every title's, and filling holes from that
    same constant is the same mistake one layer down. Only FIXED_GROUPS
    survives, because groups 4 and 5 are the CPU and the cabinet on every title
    measured and the switch join confirms 4 -> 0 and 5 -> 1 wherever it can
    answer.

    A title neither source can speak for is untouched: elvira3 names none of
    its 109 switches and writes no numeric connector, and it resolves exactly
    as it did before this existed.
    """
    inferred = {}
    groups = sorted({r["group"] for r in rows or [] if r.get("group", 0) >= 6})
    nodes = _playfield_nodes(nodedir_path)
    if groups and nodes and len(groups) == len(nodes):
        inferred = dict(zip(groups, nodes))

    dev_rows = dev_rows if dev_rows is not None else rows
    measured = dict(connector_group_node(dev_rows))
    measured.update(switch_group_node(dev_rows, switch_lines))

    # The ladder, weakest first. GROUP_NODE is the only rung that is ANOTHER
    # title's answer, so it is the only one dropped the moment this title says
    # anything about itself; the ascending rule is this title's own inference
    # and stays underneath, covering groups the measured sources are silent on.
    mapping = dict(FIXED_GROUPS if (inferred or measured) else GROUP_NODE)
    mapping.update(inferred)
    mapping.update(measured)
    mapping.update(FIXED_GROUPS)
    return mapping


def _playfield_nodes(path=None):
    """Ascending pinnode ids past the cabinet, from node_ident.txt, or [].

    NO IMPLICIT DISCOVERY - this module never reaches for "whatever title is
    active right now" on its own. It used to (via gameinfo.table_dir()), and
    that is a real bug this test suite caught rather than a theoretical one:
    parse()/load() are called with an EXPLICIT device_xy.txt path already, so
    silently re-deriving the node directory from global machine state means
    the answer depends on which title some OTHER process on the same machine
    last touched - a synthetic unit test for jaws_le picked up a live rig's
    real dungeons_and_dragons_le node_ident.txt over \\wsl.localhost\\... and
    mapped jaws_le's TROUGH onto DnD's nodes, purely because both happened to
    have 2 playfield groups. The Compare feature reads two different titles'
    tables in one process for the same reason this cannot be implicit - each
    load must name its own directory. Callers that DO want "whatever's
    active" (coildecode.py's log-analysis tools, which have no path at all)
    resolve that themselves and pass it in; see coildecode.py's coil_names().
    """
    if not path:
        return []
    out = []
    try:
        with open(path) as f:
            for line in f:
                if not line.startswith("node="):
                    continue
                fields = dict(kv.split("=", 1) for kv in line.split()
                              if "=" in kv)
                try:
                    nid = int(fields.get("node", ""))
                except ValueError:
                    continue
                # The cabinet is a pinnode too and owns group 5, not a
                # playfield group, so it is excluded by id rather than type.
                if fields.get("type") == "pinnode" and nid >= 2:
                    out.append(nid)
    except OSError:
        return []
    return sorted(out)

#: The most a node's coil index can be. The shim publishes fires into a
#: [16][16] table (padled.h), so an index past it has nowhere to land and the
#: row is not addressable however good its name looks.
COIL_N = 16
NODES = 16

#: Where the fire counters live in the padled block (padled.h). THE THIRD COPY
#: OF THESE NUMBERS IS THE ONE THAT MADE THEM WORTH MOVING: coilread.py,
#: playfield.py and ledrate.py each carried their own, and ballfeed.py needed a
#: fourth. Python cannot include a C header, so the offsets are hard-coded
#: somewhere no matter what; the point is that it is somewhere singular, next
#: to the names of the things being counted.
PADLED_MAGIC = 0x44454C50
COIL_OFF = 1556
LVL_OFF = COIL_OFF + NODES * COIL_N
GEN_OFF = LVL_OFF + NODES * COIL_N
PADLED_READ = GEN_OFF + 8


def counter(data, node, index):
    """The wrapping fire counter for one coil, or None if the block is short.

    A COUNTER RATHER THAN AN ON/OFF BIT is what makes a poll loop able to see a
    coil at all: a slingshot pulse is ~30 ms and would fall between two 20 ms
    reads about half the time. It wraps at 256 (it is one byte), so readers
    compare for INEQUALITY against what they last saw and never subtract.
    """
    if data is None or node is None or len(data) < PADLED_READ:
        return None
    if not (0 <= node < NODES and 0 <= index < COIL_N):
        return None
    return data[COIL_OFF + node * COIL_N + index]


def has_magic(data):
    """True when this really is a padled block and not a stale or empty file."""
    return (data is not None and len(data) >= 4
            and struct.unpack_from("<I", data, 0)[0] == PADLED_MAGIC)

#: The two coils a ball model needs by name. They are the same words in every
#: device table on this disk; a title that spells one differently gets None
#: and the caller says so rather than feeding the wrong coil.
TROUGH = "TROUGH"
AUTO_PLUNGER = "AUTO PLUNGER"


def parse(lines, nodedir_path=None, switch_lines=None):
    """device_xy.txt coil rows -> dicts with name, x, y, group, index, node.

    THE FIELDS ARE COUNTED FROM THE RIGHT because the NAME is the multi-word
    one: `class NAME... x y w h grp index conn image`. That has already cost a
    release - the connector column is empty for every coil, so a row was one
    field short and `h` was read as the group; every coil tooltip said "group
    20 index 6". devicexy.py writes "-" for a missing connector now, and this
    parse still refuses a row it cannot make sense of instead of placing it.

    `nodedir_path` NAMES this table's own node_ident.txt, or is left None for
    "no directory available" (bare synthetic rows, GROUP_NODE fallback - see
    group_node()). It is never auto-discovered here; see _playfield_nodes()'s
    docstring for why guessing which title's directory to read is the bug.
    `switch_lines` is this table's own switch_list.txt, under the same rule and
    for the same reason - load() names it as a sibling, nothing discovers it.
    """
    dev_rows = parse_rows(lines)
    out = [dict(r) for r in dev_rows if r["kind"] == "coil"]
    for row in out:
        del row["kind"], row["conn"]
    # The node is filled in AFTER the whole table is read, because the map is
    # derived from the set of groups the table uses - see group_node(). It is
    # passed the WHOLE table, not just the coils: item 53's two measured
    # sources live on the switch and lamp rows, and every coil connector on
    # this disk is "-".
    mapping = group_node(out, nodedir_path, dev_rows=dev_rows,
                         switch_lines=switch_lines)
    for row in out:
        if row["index"] < COIL_N:
            row["node"] = mapping.get(row["group"])
    return out


def _maybe_lines(path):
    """A file's lines, or None when it is not there.

    None rather than [] because "no switch table" and "an empty switch table"
    are the same thing to every caller here, and a missing sibling is normal:
    mktables.py writes switch_list.txt on the first boot of a title, so a
    device table can exist for a run or two before one does.
    """
    try:
        with open(path) as f:
            return f.readlines()
    except OSError:
        return None


def load(path):
    """The coil rows of a device_xy.txt, or [] when there is no table.

    Silent on a missing file on purpose: several titles on this disk ship no
    device table at all (star_wars_le has 104 real switch names and no device
    records), and a ball feeder must say "this title has no coil table" in its
    own words rather than die in a library.

    node_ident.txt IS THIS FILE'S OWN SIBLING, not a global lookup: mktables.py
    writes both into the same <title>/ directory, so the node directory to use
    is named by `path` itself - no need to ask gameinfo which title is active,
    and no risk of answering with a DIFFERENT title's if `path` names one this
    process is not currently running (the Compare tab reads two titles' tables
    in one process for exactly this reason).
    """
    try:
        with open(path) as f:
            lines = f.readlines()
    except OSError:
        return []
    nodedir = os.path.join(os.path.dirname(path), "node_ident.txt")
    swlist = os.path.join(os.path.dirname(path), "switch_list.txt")
    return parse(lines, nodedir if os.path.exists(nodedir) else None,
                 switch_lines=_maybe_lines(swlist))


def group_node_for(table_path, dev_rows=None):
    """This title's derived group -> node map, from a device_xy.txt PATH.

    THE ONE PLACE THAT KNOWS THE SIBLING FILENAMES. group_node() takes already-
    read rows and lines because it must stay callable on synthetic data and
    from inside WSL; this wraps it for every caller that has a real table on
    disk - playfield.py, ledio.py, mktables.py - so "node_ident.txt and
    switch_list.txt live beside device_xy.txt" is written down once.

    IT IS STILL NOT DISCOVERY. The path NAMES the title, exactly as load()
    does, and _playfield_nodes()'s docstring has the bug that rule exists to
    prevent: a synthetic jaws_le test picked up a live rig's real
    dungeons_and_dragons_le node directory when the lookup was implicit.

    `dev_rows` is the already-parsed table when the caller has one (playfield.py
    reads it through devicexy.read_table for its own reasons), so the file is
    not parsed twice.
    """
    d = os.path.dirname(table_path or "")
    if dev_rows is None:
        dev_rows = parse_rows(_maybe_lines(table_path) or [])
    nodedir = os.path.join(d, "node_ident.txt")
    return group_node([r for r in dev_rows if r.get("kind") == "coil"],
                      nodedir if os.path.exists(nodedir) else None,
                      dev_rows=dev_rows,
                      switch_lines=_maybe_lines(os.path.join(
                          d, "switch_list.txt")))


def group_node_text(game, mapping, dev_rows=None):
    """group_node.txt, as a string: this title's derived map, with its support.

    ITEM 53 ASKED FOR THE RESULT TO BE WRITTEN PER TITLE "rather than editing
    the constant, because the whole fault is one title's answer standing in for
    every title's". This is that file. Nothing reads it back - every consumer
    derives the map from the device table in one call - so it is EVIDENCE, not
    a cache: it is what lets someone check a map without running Python, and
    what a future wire capture would be diffed against.

    The counts are the point of it. A group with a node has devices that can be
    addressed; a group without one has devices with a POSITION and no wire
    address, which is a real state the playfield window draws and explains, and
    it should be countable here rather than inferred from a dark playfield.
    """
    by_group = collections.defaultdict(collections.Counter)
    for r in dev_rows or []:
        by_group[r["group"]][r.get("kind") or "?"] += 1
    out = ["# %s device-table group -> bus node map." % game,
           "# Derived per title (coilmap.group_node): the running game's own",
           "# switch table joined on NAME, then the device table's connector",
           "# column, then this title's node directory. NOT godzilla's map,",
           "# which is what item 53 was about.",
           "# group node devices"]
    for group in sorted(set(by_group) | set(mapping)):
        node = mapping.get(group)
        kinds = by_group.get(group) or {}
        out.append("%-5s %-4s %s" % (
            group, "-" if node is None else node,
            " ".join("%s=%d" % kv for kv in sorted(kinds.items())) or "-"))
    unmapped = sorted(g for g in by_group if mapping.get(g) is None)
    if unmapped:
        out.append("# groups with devices and NO node: %s"
                   % " ".join(str(g) for g in unmapped))
        out.append("# (position known, wire address not - drawn dark, see"
                   " playfield.load_leds)")
    return NEWLINE.join(out) + NEWLINE


def by_name(coils, name):
    """The row for a coil, matched the way the rest of the rig matches names.

    Upper case, trimmed, compared WHOLE - the same rule trough.py and
    padglhost's binds_resolve() use, so a title where these three disagree is
    a bug in one place and not three different spellings of a near-match.
    """
    want = (name or "").upper().strip()
    for c in coils:
        if (c.get("name") or "").upper().strip() == want:
            return c
    return None


def address(coils, name):
    """(node, index) for a coil by name, or None.

    None covers three different things on purpose - no table, no such coil,
    and a coil on a board the enumeration cannot name - because all three mean
    the same thing to a caller: nothing can watch this coil fire. Callers
    print which title and which name; that is enough to tell them apart.
    """
    c = by_name(coils, name)
    if c is None or c.get("node") is None:
        return None
    return (c["node"], c["index"])


def for_game(tables_dir):
    """Every coil for a title, given its built tables directory."""
    return load(os.path.join(tables_dir or "", "device_xy.txt"))
