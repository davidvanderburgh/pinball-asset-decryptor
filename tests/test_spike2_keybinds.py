"""The key-bind export/parse contract (item 39).

The playfield's key panel replaced the Controls X11 window, and the two sides
of that move live in two languages: padglhost.c WRITES dump/padbinds,
keybinds.py READS it. This pins the reading half to the format binds_export()
writes - tab-separated because a key can be "KP Ent", `0` ids for a bind not
on this title, consecutive same-action rows merged - so a drift in either
side fails in half a second here instead of as a silently wrong panel.

FAST AND SYNTHETIC like the rest of the rig's tests: the lines below are the
shapes binds_export() produces for godzilla_pro's table, written by hand.
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
def keybinds():
    import keybinds as mod
    return mod


SAMPLE = [
    "# key\tflags\tids\tlabel  (padglhost binds[], resolved for godzilla_pro)",
    "Enter\tc\t25\tService Select",
    "KP Ent\tc\t25\tService Select",
    "Bksp\tc\t28\tService Back",
    "Esc\tc\t28\tService Back",
    "C\tct\t33\tCoin Door Closed",
    "Left\t-\t60\tLeft Flipper",
    "Q\t-\t0\tSkill Shot",
    "B\tt\t66,67,68,69,70,71\t6 balls in trough",
]


def test_rows_parse_with_flags_and_ids(keybinds):
    rows = keybinds.parse(SAMPLE)
    by_label = {r["label"]: r for r in rows}
    left = by_label["Left Flipper"]
    assert left["ids"] == [60] and not left["toggle"] and not left["cabinet"]
    door = by_label["Coin Door Closed"]
    assert door["toggle"] and door["cabinet"] and door["ids"] == [33]
    trough = by_label["6 balls in trough"]
    assert trough["ids"] == [66, 67, 68, 69, 70, 71] and trough["toggle"]


def test_two_keys_one_action_merge(keybinds):
    """Enter + KP Ent are ONE action and must be one row - the panel would
    otherwise spend four lines saying two things."""
    rows = keybinds.parse(SAMPLE)
    labels = [r["label"] for r in rows]
    assert labels.count("Service Select") == 1
    assert labels.count("Service Back") == 1
    sel = next(r for r in rows if r["label"] == "Service Select")
    assert sel["keys"] == ["Enter", "KP Ent"]


def test_merge_is_consecutive_only(keybinds):
    """Two actions sharing a label across a gap must NOT collapse: the merge
    exists for keysym aliases, which the C table always writes adjacently."""
    rows = keybinds.parse(["A\t-\t64\tSlingshot",
                           "S\t-\t63\tOther",
                           "D\t-\t64\tSlingshot"])
    assert len(rows) == 3


def test_na_row_is_marked_and_unarmed(keybinds):
    """ids `0` = binds_resolve found no such name on this title. The panel
    draws it dim; nothing may ever treat 0 as a switch id."""
    rows = keybinds.parse(SAMPLE)
    q = next(r for r in rows if r["label"] == "Skill Shot")
    assert q["na"] and q["ids"] == []


def test_junk_lines_are_skipped_not_fatal(keybinds):
    rows = keybinds.parse(["", "# comment", "not a bind line",
                           "X\t-\tnope\tBad ids",
                           "Left\t-\t60\tLeft Flipper"])
    assert len(rows) == 1 and rows[0]["label"] == "Left Flipper"


def test_missing_file_is_empty_not_error(keybinds, tmp_path):
    """Absent is the NORMAL state until the renderer is up - the window polls
    through it, so load() must answer [] rather than raise."""
    assert keybinds.load(str(tmp_path / "padbinds")) == []


def test_load_reads_a_real_file(keybinds, tmp_path):
    p = tmp_path / "padbinds"
    p.write_text("\n".join(SAMPLE) + "\n", encoding="utf8")
    rows = keybinds.load(str(p))
    assert [r["label"] for r in rows][:2] == ["Service Select", "Service Back"]
