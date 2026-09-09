"""The device-table GROUP -> bus NODE map, derived per title. Item 53, PAD-120.

WHAT THIS GUARDS. The map used to be `coilmap.GROUP_NODE = {4:0, 5:1, 6:8,
7:9}` - godzilla's measurement, applied to every title. On james_bond_60th_le
the playfield devices are groups 8 and 9, which that dict has no key for, so
all 73 of its playfield lamps and all 16 of its coils were drawn dark with a
position and no wire address, while the shim decoded 36351 lamp writes on
exactly those boards. These tests are what stop one title's answer standing in
for every title's again.

AND THE SAME FAULT CAME BACK ONE LAYER DOWN (PAD-120). What item 53 left in
place was `FIXED_GROUPS = {4:0, 5:1}` - the CPU and the cabinet - applied LAST,
over everything the title had measured about itself. Both HOME EDITIONS put
their entire machine in group 5, and neither has a node 1 at all, so every
insert and every coil on Star Wars Home Edition and Jurassic Park Home Edition
was addressed to a board that does not exist and the virtual playfield stayed
dark through a full attract light show. The pin is now the floor, not the
ceiling.

THE TWO DERIVATIONS ARE INDEPENDENT AND THEY AGREE, which is the whole argument
for shipping this without a wire capture: the running game's switch table
joined on NAME, and the device table's own connector column. On every title on
this disk where both can answer they return the same node for every playfield
group they share. Each is tested here on its own, and so is what happens when
they disagree, when a connector is ambiguous, and when neither can speak.

FAST AND SYNTHETIC like the rest of the rig's tests: no WSL, no emulator, no
Tk. The rows are the real shapes off this disk.
"""
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)


@pytest.fixture()
def coilmap():
    import coilmap as mod
    return mod


# --- the real shapes off this disk -----------------------------------------

#: godzilla_pro. Its playfield coils are group 6 and its magnet group 7, and
#: the connector on a node-8 switch row says `8b`. This title is the control:
#: it MUST derive the map it already had.
GZ = """\
coil      RIGHT FLIPPER                        195   581   20   20    6     0  -      playfield
coil      TROUGH                               260   613   20   20    6     1  -      playfield
coil      GODZILLA MAGNET                       74   221   20   20    7     6  -      playfield
switch    TROUGH 1                             254   613   20   20    6    20  8b     playfield
switch    GODZILLA MAGNET SW                    74   221   20   20    7     4  9a     playfield
""".splitlines()

#: james_bond_60th_le, the title item 53 was filed for. Groups 8 and 9, which
#: GROUP_NODE has no key for; its lamps carry `8b`/`9a` connectors and its
#: topper sits on group 10 against a ws2812 board.
BOND = """\
coil      RIGHT FLIPPER                        126   360   20   20    8     0  -      Test/scaled_playfield
coil      TROUGH                               168   381   20   20    8     1  -      Test/scaled_playfield
coil      TOP LEFT SCOOP                        43    72   20   20    9     1  -      Test/scaled_playfield
led       RIGHT RETURN 3                       157   339   20   20    8     7  8b     Test/scaled_playfield
led       CENTER SPINNER                       100   200   20   20    9    12  9a     Test/scaled_playfield
led       PLAYER 1                             196    53   20   20    7     0  LED2   Test/scaled_backbox
led       TOPPER 1                               1     1   20   20   10     0  12a    Test/scaled_topper
switch    TROUGH 1                             168   381   20   20    8    37  -      Test/scaled_playfield
switch    LEFT LOOP                             80    90   20   20    9    19  -      Test/scaled_playfield
""".splitlines()

#: james_bond_60th_le's switch table as the shim reads it out of the running
#: game: `id num node bit name`.
BOND_SWITCHES = """\
# james_bond_60th_le switch list, from the shim's reading of the game's own table.
# id   num   node  bit  name
77     20    8     37   TROUGH 1
89     53    9     19   LEFT LOOP
""".splitlines()


#: star_wars_elg's service drawing, the image its 64 positioned lamps sit on.
SWHE_PF = "TestMode/Playfield_AK_SW_PIN_DIAG_GRAPHIC_cropped"


def _rows(kind, group, count, conn=None, first=0, stem="X", image=SWHE_PF):
    """`count` device_xy.txt lines in one group, `conn` on every one of them.

    THE COUNTS ARE THE LOAD-BEARING PART of the Home Edition fixtures below -
    fixed_group_node()'s rule reads how many of a group's rows name a board -
    so they are the measured ones off the two cards and the NAMES past the few
    written out by hand are elided.
    """
    return ["%-9s %-34s %5d %5d %4d %4d %4d %5d  %-6s %s"
            % (kind, "%s %d" % (stem, first + i), 120, 240, 20, 20,
               group, first + i, conn or "-", image)
            for i in range(count)]


#: star_wars_elg 1.10.0 - "Star Wars Home Edition", the title PAD-120 was filed
#: for. ONE playfield board, and the whole machine is in GROUP 5: 9 coils, 68
#: lamps and 43 switches, 120 rows of which 73 spell the board out in the
#: connector column (55 `8a` + 7 `8b` on lamps, 5 `8a` + 6 `8c` on switches).
#: Group 4 is the five CPU rows - BACKBOX GI and the four service buttons -
#: and carries no connector at all. The coils are written out by name because
#: the ball feeder addresses two of them by name.
SWHE = (
    ["coil      RIGHT FLIPPER                        195   581   20   20    5     0  -      " + SWHE_PF,
     "coil      TROUGH                               260   613   20   20    5     1  -      " + SWHE_PF,
     "coil      AUTO PLUNGER                         300   600   20   20    5     4  -      " + SWHE_PF]
    + _rows("coil", 5, 6, None, first=2, stem="SW COIL")
    + _rows("led", 5, 55, "8a", first=7, stem="SW INSERT")
    + _rows("led", 5, 7, "8b", first=62, stem="SW BACKPANEL")
    + _rows("led", 5, 6, None, first=69, stem="SW LAMP")
    + _rows("switch", 5, 5, "8a", first=0, stem="SW SWITCH")
    + _rows("switch", 5, 6, "8c", first=5, stem="SW OPTO")
    + _rows("switch", 5, 32, None, first=11, stem="SW TARGET")
    + ["led       BACKBOX GI                            10    10   20   20    4     0  -      "
       "System/TestMode/chuck_buttons_cropped"]
    + _rows("switch", 4, 4, None, stem="SERVICE",
            image="System/TestMode/chuck_buttons_cropped"))

#: jurassic_park_the_pin 1.05.0 - "Jurassic Park Home Edition". The same shape
#: with TWO differences that each matter on their own: it has NO group above 5
#: at all, so nothing this title said could reach the map and it fell all the
#: way back to godzilla's constant; and ONE of its 51 lamps carries `12a`
#: against the 59 rows that carry `8a`, which the unanimity rule that guards
#: the playfield groups would have thrown the whole group out over.
JPHE_PF = "Test/jurassic_park_the_pin_playfield"
JPHE = (
    ["coil      AUTO PLUNGER                         300   600   20   20    5     4  -      " + JPHE_PF]
    + _rows("coil", 5, 5, None, first=5, stem="JP COIL", image=JPHE_PF)
    + _rows("led", 5, 46, "8a", first=7, stem="JP INSERT", image=JPHE_PF)
    + _rows("led", 5, 1, "12a", first=53, stem="JP TOPPER", image=JPHE_PF)
    + _rows("led", 5, 4, None, first=54, stem="JP LAMP", image=JPHE_PF)
    + _rows("switch", 5, 7, "8a", first=0, stem="JP SWITCH", image=JPHE_PF)
    + _rows("switch", 5, 6, "8b", first=7, stem="JP OPTO", image=JPHE_PF)
    + _rows("switch", 5, 31, None, first=13, stem="JP TARGET", image=JPHE_PF)
    + _rows("led", 4, 1, None, stem="BACKBOX GI", image="cabinet")
    + _rows("switch", 4, 12, None, stem="DIP", image="cabinet"))

#: john_wick_le's group 5, the shape connector_group_node() refuses to read and
#: which must stay refused: 12 CABINET rows - coin switches and the lockdown
#: button's three channels - of which exactly ONE carries a connector, `2a` on
#: LOCKDOWN BUTTON-B while its own -R and -G siblings carry nothing.
#: king_kong_le (1 of 12 on group 5, 1 of 13 on group 4) and metallica_spike
#: (1 of 15) are the same shape, and neither can be answered by the switch join.
CAB = "System/TestMode/spike_2_cabinet_front_cropped"
WICK = (
    _rows("led", 5, 5, None, first=1, stem="CAB LAMP", image=CAB)
    + ["led       LOCKDOWN BUTTON-B                    50    50   20   20    5     7  2a     " + CAB]
    + _rows("switch", 5, 6, None, first=16, stem="COIN", image=CAB)
    + ["led       PF                                  100   100   20   20    8     0  9a     playfield"])


def rows_of(text_lines, coilmap):
    return coilmap.parse_rows(text_lines)


def coils_of(rows):
    return [r for r in rows if r["kind"] == "coil"]


# --- the control: godzilla must not move -----------------------------------

def test_godzilla_derives_the_map_it_already_had(coilmap):
    """Item 53's hard requirement: a title already working derives the SAME
    map. If this fails the change is a regression however good Bond looks."""
    rows = rows_of(GZ, coilmap)
    m = coilmap.group_node(coils_of(rows), dev_rows=rows)
    assert m[6] == 8 and m[7] == 9
    assert m[4] == 0 and m[5] == 1
    assert coilmap.address(coilmap.parse(GZ), coilmap.TROUGH) == (8, 1)


# --- Bond: the fault this item was filed for -------------------------------

def test_bond_playfield_groups_resolve_where_godzillas_map_had_no_key(coilmap):
    rows = rows_of(BOND, coilmap)
    m = coilmap.group_node(coils_of(rows), dev_rows=rows)
    assert 8 not in coilmap.GROUP_NODE and 9 not in coilmap.GROUP_NODE
    assert m[8] == 8 and m[9] == 9
    assert coilmap.address(coilmap.parse(BOND), coilmap.TROUGH) == (8, 1)


def test_bond_resolves_from_connectors_alone_with_no_switch_table(coilmap):
    """The connector half must answer on its own - it is what carries the
    titles whose switch names all come back `?` (elvira3, king_kong_le)."""
    rows = rows_of(BOND, coilmap)
    assert coilmap.connector_group_node(rows) == {8: 8, 9: 9, 10: 12}


def test_the_topper_group_is_addressed_and_it_is_not_a_pinnode(coilmap):
    """group 10 -> node 12 is a ws2812 board. The map does not care what KIND
    of board it is, and it must not: the ascending rule it replaces could only
    ever land on pinnodes, which is one reason Bond fell through it."""
    rows = rows_of(BOND, coilmap)
    assert coilmap.group_node([], dev_rows=rows)[10] == 12


# --- the two sources, on their own and against each other ------------------

def test_the_switch_join_reads_the_running_games_own_answer(coilmap):
    rows = rows_of(BOND, coilmap)
    assert coilmap.switch_group_node(rows, BOND_SWITCHES) == {8: 8, 9: 9}


def test_the_switch_join_wins_when_the_connector_disagrees(coilmap):
    """Measured on john_wick_le, whose group-5 rows carry a connector `2`
    against a switch table that says node 1. The game is the authority."""
    rows = rows_of(
        ["led       X                            1  1 20 20    7     0  9a     playfield",
         "switch    LEFT LOOP                    1  1 20 20    7     3  -      playfield"],
        coilmap)
    assert coilmap.connector_group_node(rows) == {7: 9}
    m = coilmap.group_node([], dev_rows=rows, switch_lines=["1 0 8 3 LEFT LOOP"])
    assert m[7] == 8


def test_a_group_whose_connectors_name_two_nodes_is_dropped_not_guessed(coilmap):
    """dungeons_and_dragons_le: groups 7 and 8 each carry connectors for BOTH
    node 8 and node 9, so the connector half must abstain and let the switch
    join - which prints the value that title's own Single Coil Test page shows
    - decide."""
    rows = rows_of(
        ["led       A                            1  1 20 20    7     0  8a     playfield",
         "led       B                            1  1 20 20    7     1  9a     playfield"],
        coilmap)
    assert coilmap.connector_group_node(rows) == {}


def test_switches_the_game_could_not_name_are_skipped(coilmap):
    """elvira3 answers `?` for all 109 of its switches. An unnamed switch
    cannot be joined, and joining it to nothing must not invent a group."""
    rows = rows_of(
        ["switch    LEFT LOOP                    1  1 20 20    7     3  -      playfield"],
        coilmap)
    assert coilmap.switch_group_node(rows, ["1 0 8 3 ?"]) == {}


# --- the rule that keeps a wrong address from replacing a missing one ------

def test_a_title_that_measures_itself_does_not_inherit_godzillas_groups(coilmap):
    """THE ONE THAT COST BOND ITS BACKBOX. Its group 7 is 24 BACKBOX lamps;
    GROUP_NODE reads group 7 as node 9, which on Bond is a PLAYFIELD board, so
    every backbox swatch rendered playfield values under backbox labels. Once a
    title has spoken for itself, godzilla's constant must not fill the holes -
    a known-missing address is better than a confident wrong one."""
    rows = rows_of(BOND, coilmap)
    m = coilmap.group_node(coils_of(rows), dev_rows=rows,
                           switch_lines=BOND_SWITCHES)
    assert 7 in coilmap.GROUP_NODE
    assert m.get(7) is None


def test_a_lone_connector_row_does_not_unpin_a_cabinet_group(coilmap):
    """john_wick_le, king_kong_le and metallica_spike all put a connector `2`
    on ONE group-5 row - Stern filling in one channel of three - against a
    switch join that says node 1 on every title it can answer for. One row of
    twelve is not the group answering, so the pin holds and the two titles
    with no switch names do not import the error."""
    rows = rows_of(WICK, coilmap)
    assert coilmap.fixed_group_node(rows) == {}
    m = coilmap.group_node([], dev_rows=rows)
    assert m[5] == 1 and m[8] == 9


# --- PAD-120: the pin is a census, not a law -------------------------------

def test_star_wars_home_edition_puts_its_whole_playfield_in_group_5(coilmap):
    """THE FAULT PAD-120 WAS FILED FOR. 73 of its 120 group-5 rows name board
    8 in the connector column, and its own node directory (nbdir.py) reads
    {0, 2, 4, 8, 12, 14} - there is NO node 1 on this machine - so the pin was
    addressing a board the title does not have and all 64 positioned inserts
    drew dark through the attract light show."""
    rows = rows_of(SWHE, coilmap)
    coils = coils_of(rows)
    assert coilmap.FIXED_GROUPS[5] == 1
    assert coilmap.fixed_group_node(rows) == {5: 8}
    m = coilmap.group_node(coils, dev_rows=rows)
    assert m[5] == 8 and m[4] == 0
    # the ball feeder addresses these two by name, and they were on node 1 too
    assert coilmap.address(coilmap.parse(SWHE), coilmap.TROUGH) == (8, 1)
    assert coilmap.address(coilmap.parse(SWHE), coilmap.AUTO_PLUNGER) == (8, 4)


def test_jurassic_park_home_edition_has_no_group_above_5_at_all(coilmap):
    """The Pin says nothing through any source that reads groups >= 6, so
    before this it fell all the way back to GROUP_NODE - godzilla's map, keys
    6 and 7 included, for a machine that has neither group."""
    rows = rows_of(JPHE, coilmap)
    assert coilmap.connector_group_node(rows) == {}
    m = coilmap.group_node(coils_of(rows), dev_rows=rows)
    assert m == {4: 0, 5: 8}


def test_a_minority_dissenter_is_outvoted_rather_than_fatal(coilmap):
    """The Pin has ONE lamp row carrying `12a` against 59 carrying `8a`. The
    unanimity rule that guards the playfield groups would drop the whole group
    over it and leave all 50 inserts dark to protect them from one."""
    rows = rows_of(JPHE, coilmap)
    named = [r for r in rows if r["group"] == 5 and r["conn"] == "12a"]
    assert len(named) == 1
    assert coilmap.fixed_group_node(rows) == {5: 8}


def test_the_running_game_can_unpin_a_group_too(coilmap):
    """The switch join used to be overruled here as well - FIXED_GROUPS was
    applied after it. The game is the authority everywhere else in this
    ladder, and a Home Edition's group-5 switches are on node 8."""
    rows = rows_of(
        ["switch    LEFT FLIPPER LANE            1  1 20 20    5     3  -      playfield"],
        coilmap)
    m = coilmap.group_node([], dev_rows=rows,
                           switch_lines=["12 3 8 3 LEFT FLIPPER LANE"])
    assert m[5] == 8


def test_a_connector_column_that_agrees_with_the_pin_changes_nothing(coilmap):
    """Only a DISAGREEMENT is reported, so a title that was already right keeps
    the fallback branch it had - the map does not start resolving differently
    because a cabinet row happens to spell out the board it is already on."""
    rows = rows_of(
        _rows("led", 5, 6, "1a", stem="CAB LAMP", image="cabinet"), coilmap)
    assert coilmap.fixed_group_node(rows) == {}
    assert coilmap.group_node([], dev_rows=rows) == coilmap.GROUP_NODE


def test_the_home_edition_lamps_reach_the_led_map(coilmap):
    """The map is only worth anything through the file the window reads: every
    one of star_wars_elg's 68 group-5 lamps must come out of ledio.build on
    node 8, where the shim publishes them."""
    import ledio
    rows = rows_of(SWHE, coilmap)
    m = coilmap.group_node(coils_of(rows), dev_rows=rows)
    leds = [dict(r, kind=r["kind"]) for r in rows if r["kind"] == "led"]
    built, problems, _report = ledio.build(leds, None, m)
    assert not problems
    assert len([1 for node, _r in built if node == 8]) == 68
    # ...and BACKBOX GI, the one group-4 lamp, still comes out on the CPU.
    assert [node for node, _r in built if node != 8] == [0]


def test_a_title_neither_source_can_speak_for_is_unchanged(coilmap):
    """No connectors, no switch table, no node directory - the jaws synthetic
    rows the ball-model tests use. It must resolve exactly as it did before
    this existed, which is through GROUP_NODE."""
    rows = rows_of(
        ["coil      TROUGH                       1  1 20 20    7     1  -      playfield",
         "coil      SHARK MOTOR UP/DOWN          1  1 20 20    8     0  -      playfield"],
        coilmap)
    m = coilmap.group_node(coils_of(rows), dev_rows=rows)
    assert m == coilmap.GROUP_NODE
    assert m.get(8) is None


# --- the written evidence --------------------------------------------------

def test_group_node_text_counts_devices_and_names_what_has_no_node(coilmap):
    rows = rows_of(BOND, coilmap)
    txt = coilmap.group_node_text("james_bond_60th_le",
                                  coilmap.group_node([], dev_rows=rows), rows)
    assert "james_bond_60th_le" in txt
    assert "8     8" in txt and "10    12" in txt
    # group 7 has devices and no node, and the file has to say so out loud.
    assert "groups with devices and NO node: 7" in txt
    assert txt.endswith("\n") and "\r" not in txt
