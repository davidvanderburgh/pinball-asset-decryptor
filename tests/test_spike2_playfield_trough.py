"""The trough display: which switches, in which order, and what it says.

REMAINING item 21(a). The fault this guards against is not "no trough is
drawn", it is "a trough is drawn in the wrong order" - item 20 was exactly
that bug (plunge.py opened TROUGH 1, the eject end, where a ball leaving can
only ever open TROUGH 6), and a display that shows a count instead of
positions would have agreed with the bug.

FAST AND SYNTHETIC, like the rest of the rig's tests: no WSL, no emulator, no
Tk. The switch rows here are the shapes of the real switch_list.txt files on
this disk - godzilla_pro's mixed case, jaws_le's upper case, led_zeppelin_le's
all-`?` names - and the merged array is a bytearray written by hand, so what
is being checked is the reading, not the machine. The real proof is a run with
swshow.py beside the window; this is the part that answers in half a second.
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
def trough():
    import trough as mod
    return mod


def rows_named(prefix="Trough", first_id=66):
    """godzilla_pro's shape: bit 32 = Trough 6 ... bit 37 = Trough 1."""
    out = []
    for i, pos in enumerate((6, 5, 4, 3, 2, 1)):
        out.append(dict(id=first_id + i, num=15 + i, node=8, bit=32 + i,
                        name="%s %d" % (prefix, pos)))
    out.append(dict(id=first_id + 6, num=21, node=8, bit=38,
                    name="%s Jam" % prefix))
    out.append(dict(id=34, num=4, node=1, bit=4, name="Action Button"))
    return out


def rows_unnamed(first_id=71):
    """led_zeppelin_le's shape: the same rows, every name a `?`."""
    return [dict(id=first_id + i, num=15 + i, node=8, bit=32 + i, name="?")
            for i in range(7)]


def test_trough_is_found_by_name_in_trough_order(trough):
    """Position 1 first, and it is the id on the HIGHEST bit."""
    positions, how = trough.find(rows_named())
    assert how == "named"
    assert [P["pos"] for P in positions] == [1, 2, 3, 4, 5, 6]
    # Godzilla: 71 is TROUGH 1 at the eject end, 66 is TROUGH 6 at the far
    # end. This exact ordering is what item 20 got wrong.
    assert [P["id"] for P in positions] == [71, 70, 69, 68, 67, 66]


def test_case_does_not_matter_and_neither_does_the_id_base(trough):
    """jaws_le is upper case and its trough is 65..60, not Godzilla's."""
    positions, how = trough.find(rows_named(prefix="TROUGH", first_id=60))
    assert how == "named"
    assert [P["id"] for P in positions] == [65, 64, 63, 62, 61, 60]


def test_trough_jam_is_not_a_ball_position(trough):
    """TROUGH JAM is a real switch on every title here and is NOT a position.

    A loose substring match would draw seven circles and call one of them a
    ball; the game would then look like it had lost a ball whenever the jam
    opto cleared.
    """
    positions, _ = trough.find(rows_named())
    assert len(positions) == 6
    assert all("JAM" not in (P["name"] or "").upper() for P in positions)


def test_unnamed_titles_fall_back_on_the_shape_and_SAY_SO(trough):
    """The `?`-name titles (item 29) still get a trough, labelled assumed."""
    positions, how = trough.find(rows_unnamed())
    assert how == "assumed"
    assert [P["pos"] for P in positions] == [1, 2, 3, 4, 5, 6]
    # bit 37 is position 1, so the ids run downward from the last row.
    assert [P["id"] for P in positions] == [76, 75, 74, 73, 72, 71]


def test_a_partial_shape_is_refused_rather_than_half_drawn(trough):
    """Five circles out of six would be a quieter lie than none at all."""
    rows = [r for r in rows_unnamed() if r["bit"] != 34]
    positions, how = trough.find(rows)
    assert (positions, how) == ([], None)


def test_nothing_at_all_gives_nothing_at_all(trough):
    assert trough.find([]) == ([], None)
    assert trough.find(None) == ([], None)


def test_closed_reads_the_merged_array_by_id(trough):
    """A ball is a made switch at that position's OWN id."""
    positions, _ = trough.find(rows_named())
    mrg = bytearray(256)
    for i in (71, 70, 69, 68, 67, 66):
        mrg[i] = 1
    assert trough.closed(mrg, positions) == [True] * 6
    mrg[66] = 0                                  # a ball leaves the FAR end
    assert trough.closed(mrg, positions) == [True, True, True, True, True,
                                             False]
    mrg[71] = 0                                  # and one at the eject end
    assert trough.closed(mrg, positions) == [False, True, True, True, True,
                                             False]


def test_a_missing_block_reads_as_open_not_as_a_crash(trough):
    """This runs in a draw loop against a file across a VM boundary."""
    positions, _ = trough.find(rows_named())
    assert trough.closed(None, positions) == [False] * 6
    assert trough.closed(bytearray(8), positions) == [False] * 6


def test_balls_in_play_is_derived_from_the_learned_complement(trough):
    """Nothing on the wire says how many balls the machine has."""
    b = trough.Balls()
    assert b.update([True] * 6) == (6, 0)        # at rest: all home
    assert b.total == 6
    assert b.update([True, True, True, True, True, False]) == (5, 1)
    assert b.update([True, True, True, False, False, False]) == (3, 3)
    assert b.update([True] * 6) == (6, 0)        # all drained again


def test_the_complement_corrects_itself_after_a_mid_game_open(trough):
    """Opening the window mid-multiball starts the count low, then learns."""
    b = trough.Balls()
    assert b.update([True, True, True, False, False, False]) == (3, 0)
    assert b.total == 3
    b.update([True] * 6)                          # the rest drain in
    assert b.total == 6
    assert b.update([True, True, True, True, True, False]) == (5, 1)


def test_nothing_seen_yet_says_so_rather_than_showing_a_confident_zero(trough):
    b = trough.Balls()
    assert b.update([False] * 6) == (0, None)
    assert b.total is None
    assert "no balls seen" in b.text()


def test_the_summary_line_carries_the_count_and_the_balls_out(trough):
    b = trough.Balls()
    b.update([True] * 6)
    b.update([True, True, True, True, False, False])
    assert b.text() == "trough 4/6   2 in play"


def test_the_denominator_is_the_positions_not_the_learned_complement(trough):
    """"trough 4/4" beside two visibly EMPTY positions is what a complement
    denominator printed on a window opened mid-multiball (offline check)."""
    b = trough.Balls()
    b.update([True, True, True, True, False, False])
    assert b.text() == "trough 4/6   0 in play"


def test_load_list_parses_the_real_file_shape(trough, tmp_path):
    """`id num node bit name...`, hashes ignored, name is the rest."""
    p = tmp_path / "switch_list.txt"
    p.write_text("# godzilla_pro switch list\n"
                 "# id   num   node  bit  name\n"
                 "66     15    8     32   Trough 6\n"
                 "71     20    8     37   Trough 1\n"
                 "72     21    8     38   Trough Jam\n"
                 "\n"
                 "bad row\n")
    rows = trough.load_list(str(p))
    assert [r["id"] for r in rows] == [66, 71, 72]
    assert rows[0]["name"] == "Trough 6"
    positions, how = trough.find(rows)
    assert (how, [P["id"] for P in positions]) == ("named", [71, 66])
    assert trough.load_list(str(tmp_path / "nope.txt")) == []


def test_the_match_rule_is_the_same_one_padglhost_uses():
    """padglhost.c resolves its window-open trough latch by the same names.

    If these two disagree, the window draws one set of switches and the run
    LATCHES a different set - the exact class of drift the rig's
    non-negotiables call out (alive.sh vs killgame.sh, autoattract vs status).
    This is a source-level check because the C side cannot be imported: it
    asserts padglhost still resolves "TROUGH %d" by name.
    """
    src = open(os.path.join(RIG, "padglhost.c"), encoding="utf8",
               errors="replace").read()
    assert 'snprintf(tn, sizeof tn, "TROUGH %d", t);' in src


def test_the_playfield_reads_the_merged_array_not_the_keyboards():
    """padsw.py's rule: WRITE scr_held, READ mrg. A window reading held[]
    would answer a question about the keyboard instead of about the game."""
    src = open(os.path.join(RIG, "playfield.py"), encoding="utf8",
               errors="replace").read()
    assert "d[off:off + padsw.MAX_ID]" in src
    assert "padsw.OFF_MRG if struct.unpack_from" in src


def test_state_markers_stay_out_of_the_hit_test():
    """Item 24 measured that the centre of RIGHT SCOOP hit-tests to the COIL
    marker, and coilact.py depends on it. The live-state dots are drawn on
    the same canvas and must never enter `self.info`, which is the only thing
    `_hit()` will return."""
    src = open(os.path.join(RIG, "playfield.py"), encoding="utf8",
               errors="replace").read()
    # The dots go into sw_dots, and nothing puts a dot into info.
    assert "self.sw_dots.append((dot, S[\"id\"]))" in src
    assert "self.info[dot]" not in src
    assert "info[dot]" not in src
