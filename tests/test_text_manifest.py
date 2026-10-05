"""Tests for the shared editable-text manifest format (text/strings.tsv).

This is the single source of truth the Replace Text GUI tab writes and the
plugin engines read at Write time, so the round-trip (save -> load -> changed)
and the parser's tolerance for comments / blank / short rows are what matter.
"""

from pinball_decryptor.core import text_manifest as tm


def test_load_missing_is_empty(tmp_path):
    assert tm.load(str(tmp_path)) == []
    assert tm.changed(str(tmp_path)) == {}
    assert tm.count_changed(str(tmp_path)) == 0


def test_revert_all_blanks_every_edit(tmp_path):
    rows = [
        {"path": "/g/a.radium", "original": "AWARD INFO", "replacement": ""},
        {"path": "/g/a.radium", "original": "REPLAY AT", "replacement": "BONUS AT"},
        {"path": "/g/b.radium", "original": "TILT", "replacement": "OOPS"},
    ]
    tm.save(str(tmp_path), rows)
    assert tm.count_changed(str(tmp_path)) == 2
    cleared = tm.revert_all(str(tmp_path))
    assert cleared == 2
    assert tm.count_changed(str(tmp_path)) == 0
    # Originals (and their rows) are preserved — only the replacement is blanked.
    back = tm.load(str(tmp_path))
    assert [r["original"] for r in back] == ["AWARD INFO", "REPLAY AT", "TILT"]
    assert all(r["replacement"] == "" for r in back)


def test_revert_all_noop_when_no_edits(tmp_path):
    assert tm.revert_all(str(tmp_path)) == 0


def test_save_then_load_round_trips_dicts(tmp_path):
    rows = [
        {"path": "/g/a.radium", "original": "AWARD INFO", "replacement": ""},
        {"path": "/g/a.radium", "original": "REPLAY AT", "replacement": "BONUS AT"},
    ]
    tm.save(str(tmp_path), rows)
    back = tm.load(str(tmp_path))
    assert back == rows
    # file lives where the engine expects it
    assert tm.manifest_path(str(tmp_path)).endswith("strings.tsv")
    assert (tmp_path / "text" / "strings.tsv").is_file()


def test_save_accepts_tuples_and_blank_replacement(tmp_path):
    tm.save(str(tmp_path), [("/g/b.radium", "PLAYER 1", None),
                            ("/g/b.radium", "PLAYER 2", "")])
    back = tm.load(str(tmp_path))
    assert [r["replacement"] for r in back] == ["", ""]


def test_changed_only_returns_real_edits(tmp_path):
    tm.save(str(tmp_path), [
        {"path": "/g/a.radium", "original": "CLOCK NOT SET",
         "replacement": "GAME OVER MAN"},            # edited (shorter)
        {"path": "/g/a.radium", "original": "PLAYER 1",
         "replacement": ""},                          # blank -> unchanged
        {"path": "/g/a.radium", "original": "REPLAY",
         "replacement": "REPLAY"},                    # equal -> unchanged
        {"path": "/g/b.radium", "original": "AWARD INFO",
         "replacement": "PRIZE INFO"},               # edited
    ])
    assert tm.changed(str(tmp_path)) == {
        "/g/a.radium": [("CLOCK NOT SET", "GAME OVER MAN")],
        "/g/b.radium": [("AWARD INFO", "PRIZE INFO")],
    }
    assert tm.count_changed(str(tmp_path)) == 2


def test_load_skips_comments_blanks_and_short_rows(tmp_path):
    d = tmp_path / "text"
    d.mkdir()
    (d / "strings.tsv").write_text(
        "# a comment\n"
        "\n"
        "/g/a.radium\tHELLO\tHI\n"
        "justonecolumn\n"                  # < 2 cols -> skipped
        "/g/b.radium\tNOREPCOL\n",         # 2 cols -> replacement defaults ''
        encoding="utf-8")
    rows = tm.load(str(tmp_path))
    assert rows == [
        {"path": "/g/a.radium", "original": "HELLO", "replacement": "HI"},
        {"path": "/g/b.radium", "original": "NOREPCOL", "replacement": ""},
    ]


def test_escape_cell_keeps_one_line():
    assert tm.escape_cell("a\tb\r\nc") == "a b  c"


def test_save_escapes_embedded_tabs(tmp_path):
    tm.save(str(tmp_path), [{"path": "/g/a.radium",
                             "original": "TWO\tWORDS", "replacement": "ok"}])
    # the embedded tab must not split the row into extra columns
    rows = tm.load(str(tmp_path))
    assert len(rows) == 1
    assert rows[0]["original"] == "TWO WORDS"


def test_budget_column_round_trips(tmp_path):
    """Game-program rows carry an explicit 4th-column byte budget (a
    standalone name may exceed its own length — it lives inside a longer
    line); radium rows never write the column."""
    rows = [
        {"path": "/g/a.radium", "original": "TILT", "replacement": ""},
        {"path": "/g/game", "original": "EBIRAH", "replacement": "BIOLLANTE",
         "budget": 18},
    ]
    tm.save(str(tmp_path), rows)
    back = tm.load(str(tmp_path))
    assert "budget" not in back[0]
    assert back[1]["budget"] == 18
    assert back[1]["replacement"] == "BIOLLANTE"
    # the edit survives into changed() even though it exceeds len(original)
    assert tm.changed(str(tmp_path)) == {
        "/g/game": [("EBIRAH", "BIOLLANTE")]}


# PAD-382 (DragonRR): a scene line with line breaks is stored flattened, so
# the Scenes preview and Write must still find it, and keep its breaks.
GZ = "GODZILLA AND JET JAGUAR\nVS.\nMEGALON AND GIGAN"
GZ_FLAT = "GODZILLA AND JET JAGUAR VS. MEGALON AND GIGAN"


def test_flattened_original_is_found_with_its_line_breaks_kept(tmp_path):
    tm.save(str(tmp_path), [{"path": "/g/s.radium", "original": tm.escape_cell(GZ),
                             "replacement": "GODZILLA AND JET JAGUAR VS. "
                                            "SPACEGODZILLA AND GIGAN"}])
    edits = dict(tm.changed(str(tmp_path))["/g/s.radium"])
    assert list(edits) == [GZ_FLAT]
    want = "GODZILLA AND JET JAGUAR\nVS.\nSPACEGODZILLA AND GIGAN"
    assert tm.edit_for(edits, GZ) == want
    assert tm.resolve({GZ: [1]}, list(edits.items())) == [(GZ, want)]


def test_card_form_breaks():
    # the start changed, the end did not: the breaks follow the end
    assert tm.card_form(GZ, "KING KONG VS. MEGALON AND GIGAN") \
        == "KING KONG\nVS.\nMEGALON AND GIGAN"
    # a typed \n is a line break and overrides the original's
    assert tm.card_form(GZ, "ONE\nTWO") == "ONE\nTWO"
    assert tm.card_form("TILT", "OOPS\nNOW") == "OOPS\nNOW"
    # nothing in common and another word count: the breaks are dropped
    assert tm.card_form(GZ, "A B C") == "A B C"
    # a line without breaks is left exactly as typed
    assert tm.card_form("TILT", "OOPS") == "OOPS"


def test_edit_for_and_resolve_leave_other_strings_alone():
    assert tm.edit_for({"TILT": "OOPS"}, "TILT") == "OOPS"
    assert tm.edit_for({"TILT": "OOPS"}, "SLAM") is None
    assert tm.edit_for({}, GZ) is None
    assert tm.resolve({"TILT": [1]}, [("GONE", "X")]) == [("GONE", "X")]
