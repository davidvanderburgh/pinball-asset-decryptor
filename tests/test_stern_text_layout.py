"""Tests for the scene text-layout manifest (``text/layout.tsv``).

Moving a line, re-aligning it or resizing it is recorded per scene per
string, the way a colour edit is; the manifest is the model (Write re-reads
it), and a row every field of which is neutral is not an edit at all.
"""

import os

from pinball_decryptor.plugins.stern import text_layout as tl

CARD = "/g/a.radium"


def test_manifest_round_trips(tmp_path):
    a = str(tmp_path)
    row = tl.set_layout(a, CARD, "BALL 1", dx=10, dy=-4, align="center",
                        size=120)
    assert row == {"dx": 10.0, "dy": -4.0, "align": "center", "size": 120}
    assert tl.load(a) == {CARD: {"BALL 1": row}}
    assert tl.layout_for(a, CARD) == {"BALL 1": row}
    assert tl.layout_for(a, "/g/other.radium") == {}
    assert tl.count(a) == 1
    assert os.path.isfile(tl.manifest_path(a))
    with open(tl.manifest_path(a), encoding="utf-8") as f:
        body = f.read()
    assert body.startswith("#")
    assert "%s\tBALL 1\t10\t-4\tcenter\t120\n" % CARD in body


def test_set_layout_merges_fields_and_drops_neutral_rows(tmp_path):
    a = str(tmp_path)
    tl.set_layout(a, CARD, "X", dx=5)
    tl.set_layout(a, CARD, "X", align="right")
    assert tl.load(a)[CARD]["X"] == {"dx": 5.0, "dy": 0.0, "align": "right",
                                     "size": None}
    # putting each field back in turn
    tl.set_layout(a, CARD, "X", dx=0)
    assert tl.load(a)[CARD]["X"]["dx"] == 0.0
    assert tl.count(a) == 1
    assert tl.set_layout(a, CARD, "X", align="") is None
    assert tl.load(a) == {}
    assert not os.path.exists(tl.manifest_path(a))

    # a 100 % size and a 0,0 move are not edits
    assert tl.set_layout(a, CARD, "Y", dx=0, dy=0, size=100) is None
    assert tl.count(a) == 0


def test_reset_drops_one_line_only(tmp_path):
    a = str(tmp_path)
    tl.set_layout(a, CARD, "X", size=150)
    tl.set_layout(a, CARD, "Y", dy=3)
    tl.set_layout(a, "/g/b.radium", "Z", align="left")
    tl.reset(a, CARD, "X")
    tl.reset(a, CARD, "not there")               # harmless
    assert tl.load(a) == {
        CARD: {"Y": {"dx": 0.0, "dy": 3.0, "align": None, "size": None}},
        "/g/b.radium": {"Z": {"dx": 0.0, "dy": 0.0, "align": "left",
                              "size": None}}}
    assert tl.clear_all(a) == 2
    assert tl.load(a) == {}
    assert tl.clear_all(a) == 0


def test_describe():
    assert tl.describe({"dx": 10, "dy": -4}) == "moved +10,-4"
    assert tl.describe({"align": "center"}) == "centred"
    assert tl.describe({"align": "left"}) == "left"
    assert tl.describe({"size": 120}) == "120 %"
    assert tl.describe({"dx": 10, "dy": -4, "align": "center",
                        "size": 120}) == "moved +10,-4 · centred · 120 %"
    assert tl.describe({"dx": 2.5, "align": "right", "size": 75}) == \
        "moved +2.5,+0 · right · 75 %"
    assert tl.describe({}) == ""
    assert tl.describe(None) == ""


def test_is_neutral():
    assert tl.is_neutral({})
    assert tl.is_neutral({"dx": 0, "dy": "", "align": "", "size": 100})
    assert not tl.is_neutral({"dy": 1})
    assert not tl.is_neutral({"align": "center"})
    assert not tl.is_neutral({"size": 99})


def test_align_code_and_name():
    assert [tl.align_code(n) for n in tl.ALIGN_VALUES] == [0, 1, 2]
    assert tl.align_code("centre") == 1
    assert tl.align_code("Right") == 2
    assert tl.align_code("") is None
    assert tl.align_code("diagonal") is None
    assert [tl.align_name(c) for c in (0, 1, 2)] == ["left", "center", "right"]
    assert tl.align_name(3) is None
    assert tl.align_name(None) is None


def test_load_ignores_garbage_columns_and_comments(tmp_path):
    a = str(tmp_path)
    os.makedirs(os.path.join(a, "text"))
    with open(tl.manifest_path(a), "w", encoding="utf-8") as f:
        f.write("# a comment\n\n"
                "%s\tOK\tabc\t2\tsideways\tlots\n" % CARD      # dy survives
                + "%s\tBAD\tx\ty\tz\tw\n" % CARD                # all garbage
                + "short\n"
                + "%s\tNEG\t\t\t\t-5\n" % CARD                  # bad size
                + "%s\tPCT\t\t\tCENTRE\t150%%\n" % CARD)
    got = tl.load(a)
    assert got == {CARD: {
        "OK": {"dx": 0.0, "dy": 2.0, "align": None, "size": None},
        "PCT": {"dx": 0.0, "dy": 0.0, "align": "center", "size": 150}}}


def test_old_manifest_missing_trailing_columns_still_loads(tmp_path):
    a = str(tmp_path)
    os.makedirs(os.path.join(a, "text"))
    with open(tl.manifest_path(a), "w", encoding="utf-8") as f:
        f.write("%s\tA\t7\n" % CARD                # dx only
                + "%s\tB\t1\t2\n" % CARD           # dx, dy
                + "%s\tC\t\t\tright\n" % CARD)     # no size column
    got = tl.load(a)[CARD]
    assert got["A"] == {"dx": 7.0, "dy": 0.0, "align": None, "size": None}
    assert got["B"] == {"dx": 1.0, "dy": 2.0, "align": None, "size": None}
    assert got["C"] == {"dx": 0.0, "dy": 0.0, "align": "right", "size": None}
    # and saving rewrites it in the full six-column form
    tl.save(a, tl.load(a))
    with open(tl.manifest_path(a), encoding="utf-8") as f:
        rows = [ln for ln in f.read().splitlines() if not ln.startswith("#")]
    assert all(len(r.split("\t")) == 6 for r in rows)


def test_string_with_a_tab_stays_one_row(tmp_path):
    a = str(tmp_path)
    tl.set_layout(a, CARD, "A\tB", dx=1)
    assert list(tl.load(a)[CARD]) == ["A B"]


def test_save_skips_neutral_rows(tmp_path):
    a = str(tmp_path)
    tl.save(a, {CARD: {"N": {"dx": 0, "dy": 0, "align": "", "size": 100},
                       "E": {"size": 50}}})
    assert list(tl.load(a)[CARD]) == ["E"]
    tl.save(a, {CARD: {"N": {}}})
    assert not os.path.exists(tl.manifest_path(a))
