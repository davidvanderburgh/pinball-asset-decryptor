"""A title's first run: the switch table is not there yet, and every consumer
must either wait for it or SAY it is guessing.

Queue item 49. The fault class: on a first run the switch list does not exist
(mktables derives it from the run's own [sw] dump, a minute in), and three
different consumers fell back to godzilla_pro's compiled ids SILENTLY - the
window-open trough latch closed six switches Bond does not watch, swshow.py
printed a confident `6 of 6` under Godzilla's names while Bond's real trough
sat open, and plunge.py drove the wrong ids while its callers printed success.
The game's LOCATING PINBALLS ball search was the machine being CORRECT about
the state it was handed - reproduced both ways on 2026-08-14 by hiding and
restoring the table on the same card and launch.

The C half (padglhost withholding non-platform rows until the table resolves,
then latching mid-run) has no offline harness; its proof is the live repro.
These tests pin the Python half: the fallback is LABELLED, never silent
(trough.py's own contract), and a Feeder can be rebuilt into usability once
the table lands, which is what ballfeed's new wait loop does every 2 s.
"""
import importlib
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)


BOND_LIKE = """# test switch list, bond's trough shape
77  70  8  37  TROUGH 1
76  69  8  36  TROUGH 2
75  68  8  35  TROUGH 3
74  67  8  34  TROUGH 4
73  66  8  33  TROUGH 5
72  65  8  32  TROUGH 6
78  71  8  38  TROUGH JAM
68  62  8  30  SHOOTER LANE
36  1001 0  2  START BUTTON
"""

#: One well-formed coil row: `class NAME x y w h grp index conn image`,
#: group 6 -> node 8, which is what coilmap's GROUP_NODE table maps.
DEVICE_XY = """# test device table
coil      TROUGH                               168   381   20   20    6     1  -      Test/img
coil      AUTO PLUNGER                         120   300   20   20    6     4  -      Test/img
"""


def _rig_env(monkeypatch, tmp_path, game="testtitle"):
    monkeypatch.setenv("PAD_ROOT", str(tmp_path))
    monkeypatch.setenv("PAD_TABLES", str(tmp_path / "tables"))
    monkeypatch.setenv("PAD_GAME", game)
    (tmp_path / "tables").mkdir(exist_ok=True)
    return tmp_path / "tables" / game


def _write_tables(tdir, switch_list=BOND_LIKE, device_xy=DEVICE_XY):
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "switch_list.txt").write_text(switch_list)
    (tdir / "device_xy.txt").write_text(device_xy)


# --- swshow: the fallback is labelled, never silent ------------------------

def test_swshow_names_the_fallback_when_there_is_no_table(monkeypatch, tmp_path):
    _rig_env(monkeypatch, tmp_path)
    import swshow
    ids, names, trough_ids, note = swshow.at_rest()
    assert trough_ids == [71, 70, 69, 68, 67, 66], "not the compiled fallback"
    assert note, "the fallback came back with no warning - that silence is " \
                 "exactly what made every instrument agree and be wrong"
    assert "FALLBACK" in note and "godzilla" in note.lower()


def test_swshow_is_quiet_when_the_title_names_its_own_trough(monkeypatch,
                                                             tmp_path):
    tdir = _rig_env(monkeypatch, tmp_path)
    _write_tables(tdir)
    import swshow
    ids, names, trough_ids, note = swshow.at_rest()
    assert trough_ids == [77, 76, 75, 74, 73, 72], "did not read the title's own"
    assert note is None, "a named table must not carry a warning"
    assert names[77].startswith("TROUGH 1")


# --- plunge: the guess is said out loud ------------------------------------

def test_plunge_warns_on_stderr_when_resolving_without_a_table(monkeypatch,
                                                               tmp_path,
                                                               capsys):
    _rig_env(monkeypatch, tmp_path)
    import plunge
    importlib.reload(plunge)          # _IDS resolves at import time
    err = capsys.readouterr().err
    assert "godzilla" in err.lower() and "wrong" in err.lower(), \
        "the fallback resolve said nothing - plunge drove wrong ids silently"
    assert plunge.TROUGH == (71, 70, 69, 68, 67, 66)


def test_plunge_is_quiet_with_the_title_s_own_table(monkeypatch, tmp_path,
                                                    capsys):
    tdir = _rig_env(monkeypatch, tmp_path)
    _write_tables(tdir)
    import plunge
    importlib.reload(plunge)
    err = capsys.readouterr().err
    assert err == "", "a resolved table must not warn: %r" % err
    assert plunge.TROUGH == (77, 76, 75, 74, 73, 72)


# --- ballfeed: rebuilt into usability when the table lands ------------------

def test_a_feeder_rebuilt_after_the_table_lands_becomes_usable(monkeypatch,
                                                               tmp_path):
    """The wait loop's whole mechanism is `Feeder(dry=dry)` again every 2 s;
    what makes that work is that a FRESH Feeder reads the table fresh. No
    clock is involved here on purpose - the loop's timing is trivial, the
    re-read is the thing that has to be true."""
    tdir = _rig_env(monkeypatch, tmp_path)
    import ballfeed
    importlib.reload(ballfeed)
    before = ballfeed.Feeder(game="testtitle", dry=True)
    assert not before.usable(), "usable with no table at all?"

    _write_tables(tdir)
    after = ballfeed.Feeder(game="testtitle", dry=True)
    assert after.usable(), "the table landed and a fresh Feeder still " \
                           "cannot feed - the wait loop would spin for nothing"
    assert after.trough.ids == [77, 76, 75, 74, 73, 72]
    assert after.eject_coil == (8, 1)


def test_the_wait_budget_exists_and_is_tunable(monkeypatch, tmp_path):
    _rig_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PAD_BALL_TABLE_WAIT_S", "7")
    import ballfeed
    importlib.reload(ballfeed)
    assert ballfeed.TABLE_WAIT_S == 7.0
