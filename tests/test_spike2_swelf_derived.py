"""The switch list survives a NEW BUILD of a title it already knew.

WHAT THIS PROTECTS. `swelf.py`'s readers are keyed on addresses measured from
one build of each title, and a new build moves every one of them. Measured
2026-09-07 against the cards on this disk:

    munsters_le      1.27.0 -> 103 rows      1.28.0 -> NOTHING
    foo_fighters_le  1.03.0 -> 105 rows      1.04.0 -> NOTHING
    jurassic_park_le 1.15.0 -> 107 rows      1.16.0 -> NOTHING

That is what "the switch list is incomplete" in a field report turned out to
mean, and the third title was not even reported - a title only looks broken
once somebody runs the build that broke it, and this rig ships to people whose
machines run newer code than anything here.

So there is now a reader that stores no address at all: it finds the device
array from a switch name every Spike 2 machine has, and the board array as the
one referenced address that maps those switches' slots into the node set the
title's OWN node directory declares. These tests pin the two properties that
make it safe to have at all:

  * it runs ONLY as a fallback, so every title that works today is untouched;
  * it refuses rather than guesses - a layout that half-fits, a board table
    with two candidates or none, or a table too small to be real all yield
    nothing, because this file's standing rule is that an honestly missing
    table beats a plausible wrong one.

The live proof that it reads a real table is in the item: on munsters_le
1.28.0 the derived table is the same 103 rows, the same names and the same
bits as 1.27.0's trusted list, and the board address it picks is the one the
previous build's list pins by name.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.join(HERE, "..", "tools", "spike2_emu")
sys.path.insert(0, RIG)


@pytest.fixture(scope="module")
def swelf():
    import swelf as mod
    return mod


def test_the_layouts_cover_every_shape_that_has_been_measured(swelf):
    """Three record shapes are known, and each needs its own field offsets.

    KIND IS THE ONE THAT BITES: a switch is 7 in the two 24-byte shapes and 1
    in the 48-byte one, so a reader that fixed the offsets and kept the
    constant would return a confident table of COILS. That is why the anchor
    is a name and not a field.
    """
    lays = swelf.DERIVED_LAYOUTS
    assert len(lays) >= 3
    assert {lay["stride"] for lay in lays} == {24, 48}
    by_stride = {}
    for lay in lays:
        by_stride.setdefault(lay["stride"], set()).add(lay["switch"])
    assert by_stride[48] == {1}, "the 48-byte generation calls a switch 1"
    assert by_stride[24] == {7}, "the older shapes call a switch 7"
    # only the 48-byte generation carries the Stern number in the record
    assert [lay["num"] for lay in lays if lay["stride"] == 48] == [0]
    assert all(lay["num"] is None for lay in lays if lay["stride"] == 24)


def test_a_title_with_stored_addresses_never_reaches_the_derived_reader(
        swelf, monkeypatch, tmp_path):
    """★ THE WHOLE SAFETY ARGUMENT. Every title that works today keeps the
    exact table it has always produced; the stored addresses are a measurement
    of that build and nothing here second-guesses them."""
    elf = tmp_path / "game"
    elf.write_bytes(b"\x7fELF" + b"\0" * 512)
    called = []
    monkeypatch.setattr(swelf, "_rows_gen2",
                        lambda *a, **k: called.append(1) or [])
    monkeypatch.setattr(swelf, "_rows_roots",
                        lambda *a, **k: [(1, 2, 8, 3, "TROUGH 1")] * 20)
    monkeypatch.setitem(swelf.ROOTS, "fake_le", (None, 0x1000, 0x2000))
    out = swelf.rows(str(elf), "fake_le")
    assert len(out) == 20
    assert called == [], "the stored addresses answered; nothing else ran"


def test_the_derived_reader_takes_over_when_the_addresses_stop_working(
        swelf, monkeypatch, tmp_path):
    """A NEW BUILD: the title is in the table, and its addresses now yield
    nothing. That is the case this whole reader exists for."""
    elf = tmp_path / "game"
    elf.write_bytes(b"\x7fELF" + b"\0" * 512)
    monkeypatch.setattr(swelf, "_rows_roots", lambda *a, **k: [])
    monkeypatch.setattr(swelf, "_rows_gen2",
                        lambda *a, **k: [(1, 2, 8, 3, "TROUGH 1")] * 18)
    monkeypatch.setitem(swelf.ROOTS, "fake_le", (None, 0x1000, 0x2000))
    assert len(swelf.rows(str(elf), "fake_le")) == 18


def test_a_title_that_was_never_in_the_tables_gets_the_derived_reader(
        swelf, monkeypatch, tmp_path):
    """Nine titles were surveyed and left unsolved by the address hunt; a
    reader that needs no address is exactly what they were waiting for."""
    elf = tmp_path / "game"
    elf.write_bytes(b"\x7fELF" + b"\0" * 512)
    monkeypatch.setattr(swelf, "_rows_gen2",
                        lambda *a, **k: [(1, 2, 8, 3, "TROUGH 1")] * 17)
    assert len(swelf.rows(str(elf), "a_title_nobody_measured")) == 17


def test_the_board_table_must_be_the_only_candidate(swelf):
    """Two addresses that both fit is not evidence for either, so the reader
    refuses. A silenced switch list is recoverable; a wrong one sends the
    keyboard, the playfield and the trough to switches that do not exist."""
    class FakeElf(object):
        def __init__(self, table):
            self.table = table

        def off(self, va):
            return 0

        def u16(self, va):
            return self.table.get(va)

    slots, nodes = [2, 6], {4, 8}
    # two addresses, each mapping slot 2 -> node 4 and slot 6 -> node 8
    tbl = {}
    for base in (0x1000, 0x2000):
        tbl[base + swelf.BOARD_STRIDE * 2 + 14] = 4
        tbl[base + swelf.BOARD_STRIDE * 6 + 14] = 8
    e = FakeElf(tbl)
    assert swelf._gen2_find_board(e, {0x1000: 1, 0x2000: 1}, slots, nodes) is None
    # ...and with only one, it answers
    e = FakeElf({k: v for k, v in tbl.items() if k < 0x2000})
    assert swelf._gen2_find_board(e, {0x1000: 1, 0x2000: 1}, slots, nodes) == 0x1000


def test_a_board_table_that_collides_two_slots_is_refused(swelf):
    """Every slot must reach a DISTINCT node - two slots on one node means the
    array is not the board table, whatever else it decodes to."""
    class FakeElf(object):
        def off(self, va):
            return 0

        def u16(self, va):
            return 8               # every slot answers the same node

    assert swelf._gen2_find_board(FakeElf(), {0x1000: 1}, [2, 6], {8}) is None
