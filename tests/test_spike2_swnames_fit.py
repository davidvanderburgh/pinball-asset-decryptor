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


# ---------------------------------------------------------------------------
# A connector the bits contradict. king_kong_le, 2026-09-01, David's E2E
# sweep: "missing a lot of switch input ... ramp optos and other switches not
# being displayed on the playfield. probably missing a board or two." No board
# was missing. The CPU-board group (4) carries connector `9c` on ONE record -
# DIP 8 - so device_switches() filed all 12 CPU switches onto node 9 beside the
# 27 the board really has, no single shift covered the 39, node 9 was refused,
# and every ramp opto, spinner, drop and pit target stayed `?`: unplaced, and
# so undrawn. The shapes below are King Kong's real ones.
# ---------------------------------------------------------------------------

CPU_NAMES = ["DIP 1", "DIP 2", "DIP 3", "DIP 4", "DIP 5", "DIP 6", "DIP 7",
             "DIP 8", "SERVICE SELECT", "SERVICE PLUS", "SERVICE MINUS",
             "SERVICE BACK"]

#: group 4, the CPU board: 12 records, index 0..11, `9c` on DIP 8 alone.
KK_GROUP4 = [dict(cls=1, group=4, index=i, name=n, conn="9c" if i == 7 else "")
             for i, n in enumerate(CPU_NAMES)]

#: group 8, the second playfield board: 27 records, no connector anywhere.
KK_NODE9_IDX = (list(range(10)) + [12, 13, 14] + list(range(17, 22))
                + list(range(23, 31)) + [38])
KK_NODE9_NAMES = {17: "CENTER RAMP MADE OPTO", 19: "LEFT RAMP MADE OPTO",
                  20: "BIPLANE RAMP MADE OPTO", 38: "PUNCHBACK FIRED VIRTUAL"}
KK_GROUP8 = [dict(cls=1, group=8, index=i,
                  name=KK_NODE9_NAMES.get(i, "NODE 9 SWITCH %d" % i), conn="")
             for i in KK_NODE9_IDX]

#: the live wire, from the shim's reading of the game's own switch table.
KK_BITS = {0: set(range(12)) | {16, 17, 18, 19, 23},
           1: {2, 8, 11, 12, 14, 16, 17, 18, 19, 20, 21, 22},
           4: set(range(16)),
           8: set(range(8, 39)),
           9: set(KK_NODE9_IDX) | {39}}

#: the names the game reported: its own on node 0, `?` on all of node 9.
KK_WIRE_NAMES = {(0, i): n.title() for i, n in enumerate(CPU_NAMES)}
KK_WIRE_NAMES.update({(9, b): "?" for b in KK_BITS[9]})


def _table(monkeypatch, recs):
    monkeypatch.setattr(swnames.devicexy, "build",
                        lambda game=None, elf_path=None: recs)


def test_a_connector_the_bits_contradict_does_not_poison_the_board(monkeypatch):
    _table(monkeypatch, KK_GROUP4 + KK_GROUP8)
    notes = []
    out = swnames.device_switches(bits_by_node=KK_BITS, names=KK_WIRE_NAMES,
                                  notes=notes)
    assert {r["group"] for r in out[9]} == {8}
    assert [r["index"] for r in out[9]] == KK_NODE9_IDX
    assert len(notes) == 1
    assert "group 4" in notes[0] and "9c" in notes[0] and "node 9" in notes[0]


def test_the_contradicted_group_is_placed_by_its_bits_instead(monkeypatch):
    """Exactly as a connectorless group is: _fit() finds node 0 (its 12
    indices land there at shift 0 and the game's own names agree), so the
    group is not lost, merely moved off the board it was never on."""
    _table(monkeypatch, KK_GROUP4 + KK_GROUP8)
    out = swnames.device_switches(bits_by_node=KK_BITS, names=KK_WIRE_NAMES)
    assert {r["group"] for r in out[0]} == {4}
    assert len(out[0]) == 12


def test_a_connector_the_bits_agree_with_still_wins(monkeypatch):
    """The regression guard for every title measured on 2026-09-01: jaws's
    group 7 carries `8a` and its indices fit node 8 AND node 9, which _fit()
    alone would refuse as a tie. The connector breaks it, as it always did."""
    recs = [dict(cls=1, group=7, index=i, name="SW %d" % i,
                 conn="8a" if i == 8 else "") for i in range(8, 39)]
    _table(monkeypatch, recs)
    bits = {8: set(range(8, 39)), 9: set(range(8, 39))}
    assert swnames._fit(recs, bits, {}) is None
    out = swnames.device_switches(bits_by_node=bits)
    assert len(out[8]) == 31 and 9 not in out


def test_without_wire_bits_the_connector_is_trusted_as_before(monkeypatch):
    """The ELF-only CLI path has nothing to check a connector against."""
    _table(monkeypatch, KK_GROUP4 + KK_GROUP8)
    notes = []
    out = swnames.device_switches(notes=notes)
    assert {r["group"] for r in out[9]} == {4}
    assert notes == []


def test_king_kong_fill_names_every_ramp_opto(monkeypatch):
    _table(monkeypatch, KK_GROUP4 + KK_GROUP8)
    rows, sid = [], 0
    for node in (0, 4, 1, 8, 9):
        for bit in sorted(KK_BITS[node]):
            sid += 1
            rows.append((sid, sid, node, bit,
                         KK_WIRE_NAMES.get((node, bit), "X%d" % sid)))
    out, report = swnames.fill(rows, "king_kong_le")
    by_wire = {(node, bit): name for _s, _n, node, bit, name in out}
    assert by_wire[(9, 17)] == "CENTER RAMP MADE OPTO"
    assert by_wire[(9, 19)] == "LEFT RAMP MADE OPTO"
    assert by_wire[(9, 20)] == "BIPLANE RAMP MADE OPTO"
    assert by_wire[(9, 39)] == "?"              # the wire's one extra bit
    assert by_wire[(0, 7)] == "Dip 8"           # the game's own name, kept
    assert sum(1 for r in out if r[4] == "?") == 1
    assert any(l.startswith("group 4: connector 9c names node 9") for l in report)
    assert any(l.startswith("node 9: 27 names") for l in report)


# ---------------------------------------------------------------------------
# THE THIRD NAME SOURCE: the title's own STATIC switch table
#
# 2026-09-08, peanuts: "for Foo Fighters and The Munsters, the list of
# Switches is still incomplete with some question marks". The device table is
# the join above and it does not always reach - devicexy yields
# foo_fighters_le 1.04.0 FIFTEEN switch records for a machine with 105
# switches, so nine playfield rows in ten stayed `?`. swelf's derived reader
# (item 102) reads all 105 out of the same binary WITH the game's own names,
# and nothing was asking it for names: mktables only ever used it as a
# substitute for a missing run.
#
# Measured on the builds he tested, modelling item 29's failure (the dump
# finds the table and names nothing): foo_fighters_le 1.04.0 60 `?` -> 0,
# munsters_le 1.28.0 3 -> 0, and the rows carrying the title's own word
# rather than a generic label 0 -> 97 and 64 -> 95.
# ---------------------------------------------------------------------------

def _static(monkeypatch, rows):
    """swelf's derived table, without a card or an ELF."""
    import swelf
    monkeypatch.setattr(swelf, "rows", lambda path, title: rows)
    monkeypatch.setattr(swnames.gameinfo, "elf", lambda game=None: "/no/elf")
    monkeypatch.setattr(swnames.gameinfo, "active", lambda *a, **k: "t")


def test_the_static_table_names_what_the_device_table_cannot_reach(monkeypatch):
    """foo_fighters_le's shape: a full roster on the wire, a device table that
    covers almost none of it."""
    _table(monkeypatch, [])                       # no device records at all
    _static(monkeypatch, [(0, 0, 8, 3, "LEFT RAMP OPTO"),
                          (1, 0, 8, 4, "RIGHT RAMP OPTO"),
                          (2, 0, 9, 7, "SPINNER")])
    rows = [(1, 0, 8, 3, "?"), (2, 0, 8, 4, "?"), (3, 0, 9, 7, "?")]
    out, report = swnames.fill(rows, "foo_fighters_le", "/no/elf")
    assert [r[4] for r in out] == ["LEFT RAMP OPTO", "RIGHT RAMP OPTO",
                                   "SPINNER"]
    assert any("static switch table" in l for l in report)


def test_the_static_table_never_replaces_a_name_the_game_gave(monkeypatch):
    """swnames' standing rule, and the static table is not an exception: a
    title that can read its own message table is the better authority."""
    _table(monkeypatch, [])
    _static(monkeypatch, [(0, 0, 8, 3, "LEFT RAMP OPTO")])
    rows = [(1, 0, 8, 3, "Left Ramp Made Opto")]
    out, _report = swnames.fill(rows, "t", "/no/elf")
    assert out == rows


def test_the_device_table_still_wins_where_it_answers(monkeypatch):
    """Nothing that resolved before this existed resolves differently now.
    The device table carries the connector that names the board, which is a
    tighter pin on the row than a wire join."""
    _table(monkeypatch, [dict(cls=1, group=7, index=3, name="FROM DEVICE",
                              conn="8a")])
    _static(monkeypatch, [(0, 0, 8, 3, "FROM STATIC")])
    rows = [(1, 0, 8, 3, "?")]
    out, _report = swnames.fill(rows, "t", "/no/elf")
    assert out[0][4] == "FROM DEVICE"


def test_the_titles_own_word_beats_a_generic_platform_label(monkeypatch):
    """PLATFORM is documented as a fallback LABEL - node 1 bit 2 is "Action
    Button" on Godzilla and "LOCKDOWN BUTTON" on Star Wars, one physical
    button that games rename. The static table is the title's own word for
    the same switch, so it goes first."""
    _table(monkeypatch, [])
    _static(monkeypatch, [(0, 0, 1, 2, "LOCKDOWN BUTTON")])
    rows = [(1, 0, 1, 2, "?")]
    out, _report = swnames.fill(rows, "t", "/no/elf")
    assert out[0][4] == "LOCKDOWN BUTTON"
    assert swnames.PLATFORM[(1, 2)] == "Action Button"    # the label it beat


def test_a_wire_the_static_table_names_twice_is_refused(monkeypatch):
    """The derived reader numbers its rows by position in the device ARRAY,
    which is not the live dump's id space - so the wire is the only safe key,
    and a wire it answers twice is no answer. A wrong name here is a marker
    that presses the wrong switch (item 29's warning)."""
    _table(monkeypatch, [])
    _static(monkeypatch, [(0, 0, 8, 3, "ONE"), (1, 0, 8, 3, "OTHER"),
                          (2, 0, 8, 4, "ONLY")])
    rows = [(1, 0, 8, 3, "?"), (2, 0, 8, 4, "?")]
    out, _report = swnames.fill(rows, "t", "/no/elf")
    assert out[0][4] == "?"
    assert out[1][4] == "ONLY"


def test_a_row_the_static_table_leaves_unnamed_is_not_invented(monkeypatch):
    _table(monkeypatch, [])
    _static(monkeypatch, [(0, 0, 8, 3, "?"), (1, 0, 8, 4, "")])
    rows = [(1, 0, 8, 3, "?"), (2, 0, 8, 4, "?")]
    out, _report = swnames.fill(rows, "t", "/no/elf")
    assert [r[4] for r in out] == ["?", "?"]


def test_the_expensive_source_is_not_asked_when_nothing_needs_it(monkeypatch):
    """The derived reader indexes the whole image - ten seconds on a 117 MB
    binary - and this runs on every start of a title whose list keeps a `?`.
    It must not run when the device table already covered every one."""
    _table(monkeypatch, [dict(cls=1, group=7, index=3, name="FROM DEVICE",
                              conn="8a")])
    asked = []
    import swelf
    monkeypatch.setattr(swelf, "rows",
                        lambda p, t: asked.append(1) or [])
    swnames.fill([(1, 0, 8, 3, "?")], "t", "/no/elf")
    assert asked == []


def test_no_rootfs_means_no_static_table_rather_than_a_crash(monkeypatch):
    """A machine with no Spike 2 rootfs has no ELF to walk, and asking for one
    must read as "this source has nothing" - not as an exception.

    `gameinfo.elf()` answers None there, and `open(None)` raises TypeError,
    which the OSError/ValueError guard around the walk does not hold. That is
    what took the whole switch list down on the one CI runner without a
    rootfs, and it is why the path is checked before the walk, not after."""
    _table(monkeypatch, [])
    asked = []
    import swelf
    monkeypatch.setattr(swelf, "rows", lambda p, t: asked.append(p) or [])
    monkeypatch.setattr(swnames.gameinfo, "elf", lambda game=None: None)
    monkeypatch.setattr(swnames.gameinfo, "active", lambda *a, **k: None)

    assert swnames.static_switch_names("king_kong_le") == {}
    out, _report = swnames.fill([(1, 0, 8, 3, "?")], "king_kong_le")
    assert out[0][4] == "?"
    assert asked == []                       # never walked a None path


def test_use_static_off_is_the_old_behaviour(monkeypatch):
    _table(monkeypatch, [])
    asked = []
    import swelf
    monkeypatch.setattr(swelf, "rows", lambda p, t: asked.append(1) or [])
    out, _r = swnames.fill([(1, 0, 8, 3, "?")], "t", "/no/elf",
                           use_static=False)
    assert asked == []
    assert out[0][4] == "?"


# ------------------------------------------- asked once per build ----------

def test_the_list_remembers_that_the_static_table_was_asked(tmp_path,
                                                            monkeypatch):
    """Without the memo, a title whose `?` no source can fill pays the walk on
    every single start, for ever - the shape of the cost item 101 spent a
    whole pass removing from rush_le's boot."""
    import mktables
    import swtable
    elf = tmp_path / "game"
    elf.write_bytes(b"x" * 32)
    monkeypatch.setattr(mktables.devicexy, "binary_id",
                        lambda p: "game 32 bytes")
    monkeypatch.setattr(swtable.devicexy, "binary_id",
                        lambda p: "game 32 bytes")
    rows = [(1, 0, 8, 3, "?")]

    plain = tmp_path / "plain.txt"
    plain.write_text(swtable.text("t", rows, str(elf)), encoding="utf-8")
    assert not mktables._static_names_asked(str(plain), str(elf))

    stamped = tmp_path / "stamped.txt"
    stamped.write_text(swtable.text("t", rows, str(elf), static_asked=True),
                       encoding="utf-8")
    assert mktables._static_names_asked(str(stamped), str(elf))
    # ... and the memo is tied to the BINARY, so a new build clears it
    monkeypatch.setattr(mktables.devicexy, "binary_id",
                        lambda p: "game 999 bytes")
    assert not mktables._static_names_asked(str(stamped), str(elf))


def test_the_memo_line_does_not_disturb_the_readers(tmp_path, monkeypatch):
    """It goes in the header, which every reader of this file skips, and the
    `# binary:` line the build check reads is still found."""
    import mktables
    import swtable
    elf = tmp_path / "game"
    elf.write_bytes(b"x" * 32)
    monkeypatch.setattr(swtable.devicexy, "binary_id", lambda p: "game 32 bytes")
    monkeypatch.setattr(mktables.devicexy, "binary_id", lambda p: "game 32 bytes")
    p = tmp_path / "switch_list.txt"
    p.write_text(swtable.text("t", [(1, 2, 8, 3, "LEFT RAMP")], str(elf),
                              static_asked=True), encoding="utf-8")
    assert mktables._read_list(str(p)) == [(1, 2, 8, 3, "LEFT RAMP")]
    assert mktables._recorded_binary(str(p)) == "game 32 bytes"
    assert mktables._built_from(str(p), str(elf))
