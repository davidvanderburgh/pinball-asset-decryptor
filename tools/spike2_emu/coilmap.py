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
jaws_le uses group 7 for the same set and group 8 for its toys, and group 8 is
not a board the boot enumeration named, so those rows come back with node
None rather than with a guess.
"""
import os
import struct

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


def group_node(rows, nodedir_path=None):
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
    """
    mapping = dict(GROUP_NODE)
    groups = sorted({r["group"] for r in rows or [] if r.get("group", 0) >= 6})
    nodes = _playfield_nodes(nodedir_path)
    if groups and nodes and len(groups) == len(nodes):
        mapping = dict(FIXED_GROUPS)
        mapping.update(dict(zip(groups, nodes)))
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


def parse(lines, nodedir_path=None):
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
    """
    out = []
    for line in lines:
        if line.startswith("#") or not line.strip():
            continue
        p = line.split()
        if len(p) < 10 or p[0] != "coil":
            continue
        try:
            group, index = int(p[-4]), int(p[-3])
            row = dict(name=" ".join(p[1:-8]), x=int(p[-8]), y=int(p[-7]),
                       group=group, index=index, image=p[-1], node=None)
        except ValueError:
            continue
        out.append(row)
    # The node is filled in AFTER the whole table is read, because the map is
    # derived from the set of groups the table uses - see group_node().
    mapping = group_node(out, nodedir_path)
    for row in out:
        if row["index"] < COIL_N:
            row["node"] = mapping.get(row["group"])
    return out


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
    return parse(lines, nodedir if os.path.exists(nodedir) else None)


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
