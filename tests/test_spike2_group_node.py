"""The device-table GROUP -> bus NODE map, derived per title. Item 53.

WHAT THIS GUARDS. The map used to be `coilmap.GROUP_NODE = {4:0, 5:1, 6:8,
7:9}` - godzilla's measurement, applied to every title. On james_bond_60th_le
the playfield devices are groups 8 and 9, which that dict has no key for, so
all 73 of its playfield lamps and all 16 of its coils were drawn dark with a
position and no wire address, while the shim decoded 36351 lamp writes on
exactly those boards. These tests are what stop one title's answer standing in
for every title's again.

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


def test_groups_4_and_5_are_pinned_against_the_connector_column(coilmap):
    """john_wick_le, king_kong_le and metallica_spike all put a connector `2`
    on a group-5 row; the switch join says node 1 on every title it can answer
    for. FIXED_GROUPS wins, so the two titles with no switch names do not
    import the error."""
    rows = rows_of(
        ["led       CAB                          1  1 20 20    5     0  2a     cabinet",
         "led       PF                           1  1 20 20    8     0  9a     playfield"],
        coilmap)
    m = coilmap.group_node([], dev_rows=rows)
    assert m[5] == 1 and m[8] == 9


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
