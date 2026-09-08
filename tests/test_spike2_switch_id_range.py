"""A switch list can hold ids this rig has no address for, and it must say so.

2026-09-08, peanuts (PAD-115): "for Foo Fighters and The Munsters, the list of
Switches is still incomplete with some question marks".

THE ID IN A SWITCH LIST IS AN ADDRESS. Every switch array the shim and
padglhost share is ``padsw.MAX_ID`` long - 256 since item 73 widened it from
128 for this very generation - and each slot is the game's own switch id, which
is what a poke writes to and what a key bind resolves to.

THE DERIVED READER DOES NOT ALWAYS HAVE ONE. Item 102 added a reader that needs
no stored address, and on the 48-byte generation there is no entry table for it
to take an id from, so it numbers each row by its position in the DEVICE array.
foo_fighters_le is the proof those are different numbers rather than the same
one written larger: 1.03.0 and 1.04.0 are the same machine with the same 105
switches, 1.03.0 has a stored address and puts the coin door at id 34, and
1.04.0 falls through to the derived reader and puts it at 583.

Measured over the card library: foo_fighters_le 1.04.0 has 89 of its 105 rows
past 256, elvira3 1.13.0 93 of 109, munsters_le 1.28.0 13 of 103,
sword_of_rage_le 1.18.0 11 of 98, and every ROOTS-generation title 0.

WHAT THAT COST, and both halves are fixed here. ``SwitchWatch.poll()`` indexed
the merged array with the coin door's id and nothing else, so on
foo_fighters_le 1.04.0 it raised IndexError out of a paced callback and the
whole virtual playfield window died on its first tick. And a row past the end
looked exactly like any other row while showing no state and doing nothing when
clicked - which is what "incomplete" looks like from the front.

NOT FIXED BY RENUMBERING, ever: an id is an address, so a dense 0..n-1 renumber
would make every row addressable and half of them press a switch nobody asked
for. Finding the real id is queue item 103.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
if RIG not in sys.path:
    sys.path.insert(0, RIG)


@pytest.fixture
def pf():
    return pytest.importorskip("playfield")


@pytest.fixture
def watch(pf, monkeypatch):
    """A SwitchWatch with no rows, so nothing here needs Tk or a run."""
    monkeypatch.setattr(pf, "load_switch_list", lambda *a, **k: [])
    return pf.SwitchWatch([], every=1)


def test_an_id_past_the_arrays_end_is_not_addressable(pf, watch):
    import padsw
    assert watch.addressable(0)
    assert watch.addressable(padsw.MAX_ID - 1)
    assert not watch.addressable(padsw.MAX_ID)
    assert not watch.addressable(583)        # foo_fighters_le 1.04.0's door
    assert not watch.addressable(-1)


def test_a_door_id_past_the_arrays_end_does_not_kill_the_poll(pf, watch,
                                                              monkeypatch):
    """THE CRASH. foo_fighters_le 1.04.0 resolves the coin door to 583 and the
    merged array is 256 long, so this raised IndexError every tick - out of a
    paced Tk callback, which takes the window with it."""
    monkeypatch.setattr(pf, "read_merged", lambda: bytes(256))
    watch.door_id = 583
    assert watch.poll() is True             # no IndexError
    assert watch.door is False              # and no invented answer


def test_a_door_that_cannot_be_read_is_not_reported_open(pf, watch,
                                                         monkeypatch):
    """"Unknown" and "open" are not the same answer: an unreadable door read as
    open puts a 48 V warning on a closed one."""
    monkeypatch.setattr(pf, "read_merged", lambda: bytes(256))
    watch.door_id = 999
    watch.poll()
    assert watch.door is False
    assert watch.is_made(999) is None


def test_a_door_inside_the_array_still_reads_both_ways(pf, watch, monkeypatch):
    """The regression control: nothing changes for the titles that worked."""
    closed = bytearray(256)
    closed[33] = 1
    monkeypatch.setattr(pf, "read_merged", lambda: bytes(closed))
    watch.door_id = 33
    watch.poll()
    assert watch.door is False              # bit set = made = door shut
    monkeypatch.setattr(pf, "read_merged", lambda: bytes(256))
    watch._n = 1
    watch.poll()
    assert watch.door is True               # bit clear = the door is open


def test_the_switch_list_view_dims_a_row_it_cannot_address(pf):
    """Source-level, like the rest of the window's rules: an unaddressable row
    is drawn dim, is not put in the click map, and gets no state dot."""
    src = open(os.path.join(RIG, "playfield.py"), encoding="utf-8",
               errors="replace").read()
    i = src.index("class Schematic")          # the switch-list view
    body = src[i:]
    assert 'live = 0 <= d["id"] < padsw.MAX_ID' in body
    assert 'fill="#d8d8d8" if live else "#5a5a5a"' in body
    # the click map and the dot are both AFTER the guard, so neither is built
    guard = body.index("if not live:")
    assert body.index('self.info[i] = dict(kind="switch"', guard) > guard
    assert body.index("self.sw_dots.append", guard) > guard


def test_the_bar_counts_them_so_the_list_stops_looking_incomplete(pf):
    src = open(os.path.join(RIG, "playfield.py"), encoding="utf-8",
               errors="replace").read()
    assert "cannot be read or clicked on this build" in src
    assert "their ids are past the %d this rig addresses" in src
