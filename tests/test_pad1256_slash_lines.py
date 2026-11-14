"""PAD-1256 (DoomWalrus666): "IMPOSTER BATTLE" on Godzilla's imposter battle screen
(293641e4) could not be changed anywhere.

The scene's words are a stand-in: the game sets that title box (Award_Textbox.Title_Instance)
to its line 3697, ``IMPOSTER BATTLE %d/%d``, filled in with the battle's number and count
(read from the Pro 1.16 program: the code that names the screen formats line 0xe71 with
``level + 1`` and the total, then calls set_text on the box).  The Text tab never offered that
line: a slash anywhere ruled a program string out as a path, which hid 400 lines on Godzilla
1.16 (every ``%d/%d`` counter and ``%P1//S/%`` plural).  Now a slash in a line of words is
wording, an existing project gains such lines on its next Scan, the locked line's note names
``IMPOSTER BATTLE %d/%d``, and an edit that drops its %-codes is refused at Apply rather than
skipped at Write.
"""

import struct

import pytest

pytest.importorskip("numpy")

from pinball_decryptor.core import text_manifest as tm               # noqa: E402
from pinball_decryptor.plugins.stern import engine, progtext         # noqa: E402
from pinball_decryptor.webui import game_filled as G                 # noqa: E402
from pinball_decryptor.webui import text_rules as R                  # noqa: E402
from tests.test_stern_progtext import BODY_OFF, VBASE, _elf          # noqa: E402
from tests.test_stern_text_refresh import GAME, _fake_card, _project  # noqa: E402

SCENE = "/godzilla_le/assets/lcd/auto_loaded/293641e4676a432bb2b75f800eba880ce12a84df/scene.radium"
IMPOSTER = "IMPOSTER BATTLE %d/%d"


@pytest.mark.parametrize("s", [
    IMPOSTER, "RAID\nBATTLE %d/%d", "%d SKILL SHOT%P1//S/%", "SECRET COMBO %d/%d",
    "Up/down bank not controlled", "BATTLE VS GHIDORAH/GIGAN DIFFICULTY", "1/2 Sec",
    "USE -/+ TO ADJUST VOLUME", "%d%P1/ST/ND/RD/TH/% PLACE"])
def test_a_slash_in_words_is_wording(s):
    assert progtext.is_display_string(s)


@pytest.mark.parametrize("s", [
    "ON/OFF", "a/b", "/games/godzilla_le/x y", "see sound/fx.ogg now", "../up one",
    "Content-Type: application/octet-stream", "Content-Range: bytes 0-0/",
    "version posted at www.sternpinball.com/EULA. Your", "http://x y",
    "293641e4676a432b/abcd x", "audio/mpeg stream"])
def test_a_path_is_still_no_line(s):
    assert not progtext.is_display_string(s)


def _build():
    """A program holding the imposter line, a path with spaces and a plural, each pointed at
    by a five-language group as the game's line table does."""
    strings = [IMPOSTER, "LOAD /games/gz/a.bin NOW", "%d SKILL SHOT%P1//S/%"]
    body = bytearray(b"\x00")
    offs = []
    for s in strings:
        offs.append(BODY_OFF + len(body))
        body += s.encode() + b"\x00"
    while (BODY_OFF + len(body)) % 4:
        body += b"\x00"
    for off in offs:
        body += struct.pack("<5I", *([VBASE + off] * 5)) + b"\x00" * 4
    return _elf(bytes(body))


def test_the_imposter_line_is_offered_and_keeps_its_codes():
    raw = _build()
    rows = {r["text"]: r for r in progtext.enumerate_program_strings(raw)}
    assert rows[IMPOSTER]["growable"] and rows[IMPOSTER]["refs"] == 1
    assert "%d SKILL SHOT%P1//S/%" in rows
    assert "LOAD /games/gz/a.bin NOW" not in rows
    msgs = []
    log = lambda m, lvl="info": msgs.append((lvl, m))                   # noqa: E731
    writes, n, _blob = progtext.plan_writes(raw, {IMPOSTER: "RIVAL BATTLE %d/%d"}, log)
    assert n == 1 and writes
    writes, n, _blob = progtext.plan_writes(raw, {IMPOSTER: "RIVAL BATTLE"}, log)
    assert n == 0 and any("placeholders" in m for lvl, m in msgs if lvl == "warning")


def test_a_scan_adds_the_lines_an_older_project_never_listed(tmp_path, monkeypatch):
    rows = [{"path": SCENE, "original": "IMPOSTER BATTLE", "replacement": ""},
            {"path": GAME, "original": "IMPOSTER BATTLE CHAMPION", "replacement": "RIVAL",
             "budget": 96, "grow": True}]
    assets, _card = _project(tmp_path, rows=rows)
    _fake_card(monkeypatch, _build())
    (assets / "text" / "program_modes.json").write_text('{"rev": 2, "scenes_rev": 3}')
    assert engine.program_text_needs_refresh(str(assets), tm.load(str(assets)))
    assert engine.refresh_program_text_flags(str(assets)) == 2
    got = tm.load(str(assets))
    assert [r["original"] for r in got[:2]] == ["IMPOSTER BATTLE", "IMPOSTER BATTLE CHAMPION"]
    assert got[1]["replacement"] == "RIVAL"                 # an edit is never touched
    new = {r["original"]: r for r in got[2:]}
    assert set(new) == {IMPOSTER, "%d SKILL SHOT%P1//S/%"}
    assert new[IMPOSTER]["path"] == GAME and new[IMPOSTER].get("grow") is True
    assert not engine.program_text_needs_refresh(str(assets), got)
    # a second read adds nothing twice
    engine.refresh_program_text_flags(str(assets))
    assert len(tm.load(str(assets))) == 4


def test_the_note_names_the_line_with_its_fill_ins():
    rows = [{"path": SCENE, "original": "IMPOSTER BATTLE"},
            {"path": "/godzilla_le/game", "original": "IMPOSTER BATTLE CHAMPION"},
            {"path": "/godzilla_le/game", "original": IMPOSTER}]
    assert G.game_row_for(rows, "IMPOSTER BATTLE")["original"] == IMPOSTER
    assert "the game program row “IMPOSTER BATTLE %d/%d”" in G.locked_note("IMPOSTER BATTLE", rows)
    assert G.locked_note("IMPOSTER BATTLE", rows, short=True).endswith(
        "change the game program row “IMPOSTER BATTLE %d/%d” on the Text tab")
    # a line reading the same outright still comes first
    rows.append({"path": "/godzilla_le/game", "original": "Imposter Battle!"})
    assert G.game_row_for(rows, "IMPOSTER BATTLE")["original"] == "Imposter Battle!"
    # Show in Scenes from the game's line finds the screen's stand-in
    assert [r["path"] for r in R.stand_in_rows(rows, rows[2])] == [SCENE]
    assert R.format_index(rows[:3]) == {"IMPOSTER BATTLE": [(IMPOSTER, [])]}


@pytest.mark.parametrize("line, words", [
    (IMPOSTER, "IMPOSTER BATTLE"), ("RAID\\nBATTLE %d/%d", "RAID BATTLE"),
    ("%d SKILL SHOT%P1//S/%", "SKILL SHOT"), ("%d SECOND%P1//S/%", ""),
    ("%s BATTLE", ""), ("GIGAN AWARD", ""), ("CITY COMBO NEW YORK %d/%d", "CITY COMBO NEW YORK")])
def test_format_words(line, words):
    assert R.format_words(line) == words


def test_an_edit_must_keep_the_codes():
    r = {"path": "/godzilla_le/game", "original": IMPOSTER, "budget": 96, "grow": True}
    assert R.fill_in_message(r, "RIVAL BATTLE %d/%d") is None
    why = R.fill_in_message(r, "RIVAL BATTLE")
    assert why.startswith("“RIVAL BATTLE” has to keep the %-codes of “IMPOSTER BATTLE %d/%d”: %d %d.")
    assert R.FILL_IN_NOTE in R.program_note(r)
    assert R.fill_in_message(r, "") is None                  # back to the original
    plain = {"path": "/godzilla_le/game", "original": "GIGAN AWARD", "budget": 96}
    assert "leave the % out" in R.fill_in_message(plain, "100% KAIJU")
    assert R.FILL_IN_NOTE not in R.program_note(plain)
    assert R.fill_in_message({"path": SCENE, "original": "IMPOSTER BATTLE"}, "50%") is None
