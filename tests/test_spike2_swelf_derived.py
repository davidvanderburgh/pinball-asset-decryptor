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
    # ★ NO SHAPE CARRIES THE STERN NUMBER IN THE DEVICE RECORD. The 48-byte
    # one was read as if it did until 2026-09-08 and the field is not that:
    # it reads 0 on foo_fighters_le 1.04.0 and elvira3 1.13.0, and 145 on
    # munsters_le 1.28.0's TILT PENDULUM, which Stern numbers 81. The number
    # lives in the entry table beside the id - see _gen2_entry_ids.
    assert all(lay["num"] is None for lay in lays)


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


# ---------------------------------------------------------------------------
# THE ID IS THE ENTRY TABLE'S INDEX, NOT THE DEVICE ARRAY'S
#
# 2026-09-08, PAD-115. The derived reader had no entry table to take an id
# from, so it reported each row's position in the DEVICE array. Those are
# different numbers, and the difference is not academic: padsw.MAX_ID is 256
# and a device position runs to 847 on foo_fighters_le 1.04.0, so 89 of its
# 105 switches had an "id" nothing in the rig could address.
#
# foo_fighters_le proves they are different rather than merely bigger, because
# ONE MACHINE ANSWERS TWICE: 1.03.0 still has a stored address, is read through
# its 44-byte entry table, and puts the coin door at id 34; 1.04.0's addresses
# have moved, so it falls through to the derived reader, whose device position
# for the same switch is 583. With the entry table read, both builds give
# 2..106 and both put SERVICE SELECT on 26.
#
# Measured over the card library once the entry table is read: every title's
# ids fall under 256, all eight titles whose SERVICE SELECT id item 73
# established from their own real switch lists come back with that id
# (aerosmith 26, batman 28, elvira3 25, foo_fighters 26, guardians 26, iron
# maiden 26, mando 26, rush 26), and both cross-build pairs agree with
# themselves (foo_fighters 1.03/1.04 = 26, munsters 1.27/1.28 = 25).
# ---------------------------------------------------------------------------

class FakeElf:
    """Just enough of swelf.Elf for the entry walk: flat memory at VA 0."""

    def __init__(self, blob):
        self.d = bytearray(blob)

    def off(self, va):
        return va if 0 <= va < len(self.d) else None

    def u16(self, va):
        if va < 0 or va + 2 > len(self.d):
            return None
        return int.from_bytes(self.d[va:va + 2], "little")


def _rec(stride, num=0, dev=0, filler=b""):
    r = bytearray(stride)
    r[24:26] = int(num).to_bytes(2, "little")
    r[26:28] = int(dev).to_bytes(2, "little")
    for i, b in enumerate(filler):
        r[i] = b
    return bytes(r)


def _image(stride, recs, dev_start):
    """recs laid out so the LAST one ends `gap` bytes before dev_start."""
    blob = bytearray(dev_start + 64)
    at = dev_start - stride * len(recs)
    for i, r in enumerate(recs):
        blob[at + stride * i:at + stride * (i + 1)] = r
    return FakeElf(blob), at


def test_a_blank_device_zero_record_is_the_dummy_and_a_busy_one_is_not(swelf):
    """★ THE RULE THAT STOPS THE WALK IN THE RIGHT PLACE. Every title measured
    has exactly one dummy - device 0, no number - immediately before its first
    switch, so the walk has to pass through it. But unrelated memory in front
    of the table reads as "device 0, number 0" too: elvira3 1.13.0 has a
    descending u32 array right there whose 15 records all passed, which put
    every id 15 too low. A dummy is EMPTY - at most the one pointer that says
    INVALID - and the neighbours are five to ten words full."""
    S = 40
    blank = _rec(S)
    one_word = _rec(S, filler=b"\x20\x67\x56\x00")           # a name pointer
    busy = _rec(S, filler=b"\x08\x0a\x84\x00\x04\x0a\x84\x00\xfc\x09\x84\x00")
    e = FakeElf(blank + one_word + busy)
    assert swelf._entry_plausible(e, 0, S, 400)              # blank
    assert swelf._entry_plausible(e, S, S, 400)              # one pointer
    assert not swelf._entry_plausible(e, 2 * S, S, 400)      # three words


def test_a_record_naming_a_real_device_is_not_held_to_the_dummy_rule(swelf):
    """foo_fighters_le 1.04.0's id 0 is a COIL entry, nine words full, and it
    is part of the table - the emptiness test is only for a record claiming
    device 0."""
    S = 40
    e = FakeElf(_rec(S, num=60, dev=37, filler=b"\x32\x00\x25\x00\x2c\x72\x50"))
    assert swelf._entry_plausible(e, 0, S, 400)


def test_an_out_of_range_device_or_number_ends_the_walk(swelf):
    S = 40
    e = FakeElf(_rec(S, num=60, dev=500) + _rec(S, num=57644, dev=79))
    assert not swelf._entry_plausible(e, 0, S, 400)       # device past the array
    assert not swelf._entry_plausible(e, S, S, 400)       # number far too big


def test_the_entry_table_gives_the_id_and_the_stern_number(swelf):
    """The shape every title measured has: a dummy, then the switches in the
    device array's own order at consecutive ids."""
    S, DEV = 40, 0x4000
    recs = [_rec(S)] + [_rec(S, num=i + 1, dev=d)
                        for i, d in enumerate(range(300, 330))]
    e, base = _image(S, recs, DEV - 12)
    got = swelf._gen2_entry_ids(e, DEV, 400, list(range(300, 330)))
    assert got[300] == (1, 1)          # id 1, Stern number 1
    assert got[329] == (30, 30)
    assert max(i for i, _n in got.values()) < 256


def test_a_device_the_entry_table_never_lists_gets_no_id(swelf):
    """munsters_le 1.28.0's RIGHT SPINNER is the only one in the library: a
    switch record the GAME does not carry in its switch array. It has no id,
    so the row is dropped rather than given the position it used to be given.
    """
    S, DEV = 40, 0x4000
    devs = [300, 301, 303, 304] + list(range(305, 330))     # 302 skipped
    recs = [_rec(S)] + [_rec(S, num=i + 1, dev=d) for i, d in enumerate(devs)]
    e, _base = _image(S, recs, DEV - 12)
    got = swelf._gen2_entry_ids(e, DEV, 400, [300, 301, 302] + devs[2:])
    assert 302 not in got
    assert got[301][0] + 1 == got[303][0], "the ids stay consecutive"


def test_a_table_out_of_step_with_the_device_array_is_refused(swelf):
    """The test that picks the answer is not the longest run: the entry table's
    switch rows have to reproduce the device array's own order. A candidate
    that half fits yields nothing, because an id space wrong by one is worse
    than the one it replaces - every id would then address a real switch that
    is not the one on the row."""
    S, DEV = 40, 0x4000
    devs = list(range(300, 330))
    shuffled = devs[:10] + devs[15:20] + devs[10:15] + devs[20:]
    recs = [_rec(S)] + [_rec(S, num=i + 1, dev=d)
                        for i, d in enumerate(shuffled)]
    e, _base = _image(S, recs, DEV - 12)
    assert swelf._gen2_entry_ids(e, DEV, 400, devs) == {}


def test_a_table_that_misses_most_of_the_switches_is_refused(swelf):
    S, DEV = 40, 0x4000
    devs = list(range(300, 340))
    recs = [_rec(S)] + [_rec(S, num=i + 1, dev=d)
                        for i, d in enumerate(devs[:20])]
    e, _base = _image(S, recs, DEV - 12)
    assert swelf._gen2_entry_ids(e, DEV, 400, devs) == {}


def test_no_entry_table_at_all_is_an_empty_answer(swelf):
    S, DEV = 40, 0x4000
    e = FakeElf(bytearray(DEV + 64))
    for i in range(0, DEV, 4):                       # dense, so nothing walks
        e.d[i:i + 4] = (0x11223344).to_bytes(4, "little")
    assert swelf._gen2_entry_ids(e, DEV, 400, list(range(300, 330))) == {}


def test_require_ids_refuses_a_reading_with_no_entry_table(swelf, monkeypatch):
    """How rows() asks whether the derived reader can beat a stored-address
    one that has no ids of its own, instead of guessing."""
    monkeypatch.setattr(swelf, "_gen2_find_dev", lambda e, idx, lay: None)
    e = FakeElf(bytearray(64))
    assert swelf._rows_for_layout(e, {}, {8}, swelf.DERIVED_LAYOUTS[0],
                                  require_ids=True) == []


def test_a_placeholder_id_title_takes_the_entry_backed_reading(swelf,
                                                              monkeypatch,
                                                              tmp_path):
    """★ sword_of_rage_le. ROOTS_NONUM reports the device position as the id -
    its docstring says why, "no ENT-equivalent table exists for either title" -
    and one does. The two readings were checked against each other first and
    agree on all 98 rows, wire for wire and name for name; only the id moves,
    from a maximum of 266 to 99."""
    elf = tmp_path / "game"
    elf.write_bytes(b"\x7fELF" + b"\0" * 512)
    monkeypatch.setitem(swelf.ROOTS_NONUM, "fake_le", (0x1000, 0x2000))
    monkeypatch.setattr(swelf, "_rows_nonum",
                        lambda *a, **k: [(266, 0, 8, 3, "SPINNER")] * 20)
    monkeypatch.setattr(
        swelf, "_rows_gen2",
        lambda e, require_ids=False:
            [(99, 5, 8, 3, "SPINNER")] * 20 if require_ids else [])
    out = swelf.rows(str(elf), "fake_le")
    assert out[0][0] == 99, "the entry-backed reading wins"


def test_the_placeholder_still_serves_a_build_with_no_entry_table(swelf,
                                                                 monkeypatch,
                                                                 tmp_path):
    """Falling back to exactly what it does today, rather than to nothing."""
    elf = tmp_path / "game"
    elf.write_bytes(b"\x7fELF" + b"\0" * 512)
    monkeypatch.setitem(swelf.ROOTS_NONUM, "fake_le", (0x1000, 0x2000))
    monkeypatch.setattr(swelf, "_rows_nonum",
                        lambda *a, **k: [(266, 0, 8, 3, "SPINNER")] * 20)
    monkeypatch.setattr(swelf, "_rows_gen2", lambda e, require_ids=False: [])
    out = swelf.rows(str(elf), "fake_le")
    assert out[0][0] == 266


def test_a_second_dummy_in_a_row_ends_the_walk(swelf):
    """An all-zero record satisfies every other test here, for as far back as
    the zeros go, so a table with a zeroed run in front of it would be walked
    to a base hundreds of records too early and every id would come out that
    much too low. Every title measured has exactly ONE dummy."""
    S, DEV = 40, 0x4000
    recs = [_rec(S)] + [_rec(S, num=i + 1, dev=d)
                        for i, d in enumerate(range(300, 330))]
    e, base = _image(S, recs, DEV - 12)          # all zeros before the table
    got = swelf._gen2_entry_ids(e, DEV, 400, list(range(300, 330)))
    assert got[300] == (1, 1), "the zeros in front were walked into"
    assert got[329] == (30, 30)
