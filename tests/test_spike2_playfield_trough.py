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
import json
import os
import shutil
import subprocess
import sys
import types

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


def _pf_js():
    with open(os.path.join(RIG, "pfpage", "pf.js"), encoding="utf8") as f:
        return f.read()


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_state_markers_stay_out_of_the_hit_test():
    """Item 24 measured that the centre of RIGHT SCOOP hit-tests to the COIL
    marker, and coilact.py depends on it. The live-state dot is drawn in the
    middle of the switch ring and must never become what a press lands on -
    filling the ring would have moved that press to the SWITCH.

    On the page the hit test is pfHit() (pf.js), and made state is not one of
    its inputs at all; this runs it under Node on RIGHT SCOOP's shape - the
    coil a few pixels off its switch - and checks the switch's centre, where
    the dot is drawn, still reaches the coil and a lone ring's centre still
    reaches nothing."""
    src = _pf_js()
    i = src.index("function pfHit(view, fx, scale, px, py) {")
    body = src[i:src.index("\n}\n", i)]
    assert "made" not in body                   # the dots are not an input
    scoop = {"switches": [[0, 100, 100, 53]], "coils": [[0, 107, 100, "6:8"]],
             "fixtures": []}
    lone = {"switches": [[0, 100, 100, 53]], "coils": [], "fixtures": []}
    js = ("const { pfHit } = require(%s);\n"
          "console.log(JSON.stringify([pfHit(%s, {}, 1, 100, 100),"
          " pfHit(%s, {}, 1, 100, 100)]));\n"
          % (json.dumps(os.path.join(RIG, "pfpage", "pf.js")),
             json.dumps(scoop), json.dumps(lone)))
    run = subprocess.run([shutil.which("node"), "-e", js],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == [["coil", 0], None]
    # The schematic's dot sits beside its row and takes no event of its own.
    sch = src[src.index("function schematicView("):
              src.index("function waitingView(")]
    assert 'const d = el("span", "d");' in sch
    assert "d.addEventListener" not in sch.split(
        'const d = el("span", "d");', 1)[1]


def test_made_state_travels_apart_from_the_markers():
    """The model's half of the same rule: the markers the hit test reads come
    from spec(), made state only ever from dyn() / a frame's "sw"."""
    pf = pytest.importorskip("playfield")
    ns = types.SimpleNamespace(
        art=None, base=(313, 710), fixtures=[], coils=[], coil_drawn={},
        sw_rows=[dict(id=53, x=250, y=357, name="Right Scoop")],
        trough=None, _dot_drawn={53: True})
    spec = pf.Field.spec(ns)
    assert spec["switches"] == [[0, 250, 357, 53]]
    assert pf.Field.dyn(ns)["sw"] == {"53": True}
