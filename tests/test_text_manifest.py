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
