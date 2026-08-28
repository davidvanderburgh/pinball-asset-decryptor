"""Which NODE a device-table group belongs to, when the table will not say.

Queue item 80, 2026-08-28, found on led_zeppelin_le during the alphabetical
sweep: most of its switch matrix read `?`, no game would start, and the arrow
keys did nothing.

The chain, because every link of it is silent on its own. The shim reads each
switch's name through `msg_row()`, whose per-title address resolves wrong on
this title (item 29), so every playfield name comes back `?`. swnames.py exists
for exactly that and fills the names from the title's own DEVICE TABLE instead -
except that led_zeppelin_le 1.22.0 ships that table with the drawing left out
(devicexy.BLANK_IMAGE): no image name, no coordinates, no part number and, the
part that matters here, NO CONNECTOR. `device_switches()` reads the node off the
connector string and is right to, and with the column empty every group went
unresolved, so nothing was filled. padglhost's binds_playfield() then matches
keys to switches BY NAME, found no "LEFT FLIPPER BUTTON" to match, and built no
playfield rows at all; the trough ids were unknown for the same reason, which is
what stopped a game being started.

`swnames._fit()` is the fallback: match the group's device indices against the
LIVE wire - which bits are really present on which node, from the shim's own
reading of the running game's switch table - and take the one (node, shift) that
covers all of them. The fixtures below are led_zeppelin_le's real shape, cut
down: its group 7 holds 32 indices and node 8 holds exactly those 32 bits, its
group 8 holds 18 of node 9's 19, and groups 4 and 5 fit node 8 under a shift as
well as their own node, which is where the NAME tiebreak earns its place.
"""
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)

import swnames                                     # noqa: E402


def dev(pairs):
    """[{index, name}] - the two fields _fit() reads off a device record."""
    return [dict(index=i, name=n) for i, n in pairs]


#: led_zeppelin_le node 8, the run of playfield switches around the flippers
#: and the trough. index == bit on this title, and the join has to DISCOVER
#: that rather than assume it.
NODE8 = dev([(24, "RIGHT FLIPPER BUTTON"), (25, "LEFT FLIPPER BUTTON"),
             (26, "UP RIGHT FLIPPER BUTTON"), (28, "SHOOTER LANE"),
             (32, "TROUGH 6"), (33, "TROUGH 5"), (34, "TROUGH 4"),
             (35, "TROUGH 3"), (36, "TROUGH 2"), (37, "TROUGH 1"),
             (38, "TROUGH JAM")])

BITS8 = {24, 25, 26, 28, 32, 33, 34, 35, 36, 37, 38}


def test_the_only_node_the_indices_all_land_on_wins():
    assert swnames._fit(NODE8, {8: BITS8}, {}) == (8, 0)


def test_a_node_that_cannot_hold_every_index_is_not_a_candidate():
    """The guard, and it is the guard `_offset()` already applies one layer up:
    a shift explaining only MOST of a group would have silently paired the
    wrong ones. Node 9 here is missing bit 28, so nothing fits it."""
    short = BITS8 - {28}
    assert swnames._fit(NODE8, {9: short}, {}) is None
    assert swnames._fit(NODE8, {8: BITS8, 9: short}, {}) == (8, 0)


def test_the_wire_may_carry_more_bits_than_the_table_names():
    """led_zeppelin_le's node 9 has 19 live bits against 18 device records, and
    jaws_le's has 42 against 39. Extra WIRE is normal; an unexplained device
    index is not."""
    assert swnames._fit(NODE8, {8: BITS8 | {40, 41, 42}}, {}) == (8, 0)


def test_a_shift_is_discovered_rather_than_assumed():
    """index == bit on led_zeppelin_le and godzilla_pro's node 8 is index ==
    bit - 1, which is the measurement swnames' header opens with. A join that
    assumed either would press the wrong switch on the other."""
    shifted = {b + 3 for b in BITS8}
    assert swnames._fit(NODE8, {8: shifted}, {}) == (8, 3)


def test_a_tie_no_name_can_break_is_refused_rather_than_guessed():
    """Two nodes with identical bit sets say nothing about which is which, and
    a wrong answer here is a marker that presses the wrong switch. swnames'
    standing rule is to leave it `?`."""
    assert swnames._fit(NODE8, {8: BITS8, 9: set(BITS8)}, {}) is None


def test_a_name_the_game_already_reported_breaks_the_tie():
    """This is how led_zeppelin_le's groups 4 and 5 resolve: both also fit node
    8 under a shift, and the platform nodes are the ones whose names are
    already known. Matching is case-insensitive - the device table shouts
    (`SERVICE SELECT`) where the switch list does not."""
    names = {(9, i): n for i, n in [(24, "Right Flipper Button"),
                                    (25, "Left Flipper Button"),
                                    (32, "Trough 6")]}
    assert swnames._fit(NODE8, {8: BITS8, 9: set(BITS8)}, names) == (9, 0)


def test_names_that_contradict_the_pairing_count_against_it():
    """A generic PLATFORM label meeting the title's own word for one button
    ("Action Button" / "LOCKDOWN BUTTON") must not veto an otherwise good fit,
    so agreement is SCORED rather than required - but a candidate that
    disagrees everywhere loses to one that is merely silent."""
    wrong = {(9, i): "SOMETHING ELSE" for i in BITS8}
    assert swnames._fit(NODE8, {8: BITS8, 9: set(BITS8)}, wrong) == (8, 0)


def test_a_group_with_no_records_resolves_to_nothing():
    assert swnames._fit([], {8: BITS8}, {}) is None
    assert swnames._fit(NODE8, {}, {}) is None
