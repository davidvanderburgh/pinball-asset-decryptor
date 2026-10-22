"""PAD-662: a mode's HUD words never sit on the game's own words.

Seen in PAD-658 (David's Heisei project, emulator run kiryu_r2 k15): SUPER X2's instruction line was lettered over
Godzilla's own SHOOT TARGETS TO DISABLE BARRIER. That is Mechagodzilla's DEFENSE NEO BARRIER: a screen of the game's
that no list of its modes names (pm_aside says nothing), a BACKGROUND of the layered display other than the city,
whose scene letters its words in the title / line / counter places a mode's HUD copies (emulator probe, PAD-662: the
game's set_text from 0x15bc1c onto that background's own node, background vtable 0x00645de8).

The runtime watches what is drawn (pm_game_words: a background of the game's other than the city whose scene_show is
let through), and every mode's words step aside while it is up: the kit HUD moves its lines into the award line and
hides its counters, a qualification note goes in the award line, a mode file's own screen and a blocks mode's own
screen and info line are hidden. Unlike pm_aside it never ends a mode (give_way) or refuses a start.

Desk: the blocks modes and the kit's examples through examples/desk_harness.c (`words <0|1>`), a mode file's screen
through the roster harness; the runtime's watch read off its source.
"""
import os
import re

import pytest

from tests.test_stern_block_modes import BM, maser_hud, play as play_blocks, _hud_words
from tests.test_spike2_intricate_modes import harness, play, hud, has, _at, POWERLINES  # noqa: F401 (fixture)
from tests.test_spike2_mode_aside import SCREEN_STUBS, _build, _run, RUSH
from tests.test_spike2_mode_display import SDK

RUNTIME = os.path.join(str(SDK), "pad_mode_runtime.c")


def _section(out, a, b=None):
    return out[out.index(a):out.index(b)] if b else out[out.index(a):]


# ---- the kit HUD of a blocks mode -------------------------------------------------------------------------------
def test_the_hud_steps_aside_while_a_screen_of_the_games_has_its_words_up(tmp_path):
    p = maser_hud()
    p["screen"] = True
    out = play_blocks(tmp_path, p, "shot", "Maser target", "secs", 1, "words", 1, "secs", 1, "words", 0, "secs", 1,
                      slug="maser")
    up = _section(out, ">> words 1", ">> words 0")
    # its lines into the award line, the counters blank, its own screen hidden; the badge stays in its own slot
    assert "a screen of the game's has its words up - its lines in the award line, its counters hidden" in up
    assert "Hud_Award: TEST MODE" in up and "Hud_AwardSub: LEFT RAMP  >  RIGHT RAMP  >  BUILDING" in up
    assert "Hud_Title:  " in up and "Hud_Line:  " in up
    assert "Hud_C1_Value:  " in up and "Hud_C1_Label:  " in up
    assert "SHOW PadMode_maser_Screen 0" in up
    assert "_Hud_Timer2 1" not in up and "_Hud_Timer 0" not in up
    # gone: back in its places, its screen back
    back = _section(out, ">> words 0")
    assert "the game's words are gone - back in its places" in back
    assert "Hud_Title: TEST MODE" in back and "Hud_C1_Label: MULTIPLIER" in back
    assert "SHOW PadMode_maser_Screen 1" in back
    # the mode ran on through it (it is no mode of the game's)
    assert "[TEST MODE] END" not in up


def test_a_give_way_mode_is_not_ended_by_the_games_words(tmp_path):
    p = maser_hud()
    p["game_modes"] = "give_way"
    out = play_blocks(tmp_path, p, "shot", "Maser target", "secs", 1, "words", 1, "secs", 2, "battle", 1, "secs", 1,
                      slug="maser")
    words = _section(out, ">> words 1", ">> battle 1")
    assert "END" not in words and "its lines in the award line" in words
    assert "END (the game's own mode began)" in _section(out, ">> battle 1")      # a mode of the game's still does


def test_a_battle_over_a_screen_of_the_games_is_still_the_battle_aside(tmp_path):
    """the existing aside is unchanged: a battle moves the badge one slot down, and says it is a battle's"""
    out = play_blocks(tmp_path, maser_hud(), "shot", "Maser target", "secs", 1, "words", 1, "battle", 1, "secs", 1,
                      "battle", 0, "words", 0, "secs", 1, slug="maser")
    battle = _section(out, ">> battle 1", ">> battle 0")
    assert "aside for a battle - its lines in the award line" in out
    assert "_Hud_Timer2 1" in battle
    back = _section(out, ">> words 0")
    assert "Hud_C1_Label: MULTIPLIER" in back


def test_the_blocks_watch_the_games_words_for_their_screen_and_info_line():
    src = BM.to_c(dict(maser_hud(), screen=True), "maser")
    assert "pm_display_covered() || pm_aside() || pm_game_words()" in src


# ---- a qualification note of the kit's examples -----------------------------------------------------------------
def test_a_note_over_a_screen_of_the_games_goes_in_the_award_line(harness):
    out = play(harness, "words", 1, "secs", 1, "shot", "Powerline left", "secs", 1, "words", 0, "secs", 1)
    t0, t1 = _at(out, ">> words 1"), _at(out, ">> words 0")
    assert has(out, "KING GHIDORAH", "powerlines 1 of 3 (player 1)")
    # shown, in the award line, never in the title place over the game's words
    assert [ms for ms, w in hud(out, "ghidorah_heads", "Award") if t0 <= ms < t1 and w == "POWERLINES 1 OF 3"]
    assert not [ms for ms, w in hud(out, "ghidorah_heads", "Title") if t0 <= ms < t1 and w == "POWERLINES 1 OF 3"]
    assert has(out, "KING GHIDORAH", "hud ghidorah_heads: a screen of the game's has its words up - the note in the award line")


def test_a_note_up_when_the_games_words_come_stays_in_the_award_line(harness):
    # PAD-680: a progress note is in the award line from the start (no longer the title place PAD-658 gave it), so
    # the game's words coming leave it where it is, shown on through them
    out = play(harness, "shot", "Powerline left", "secs", 0.5, "words", 1, "secs", 1)
    t = _at(out, ">> words 1")
    award = hud(out, "ghidorah_heads", "Award")
    assert [ms for ms, w in award if ms < t and w == "POWERLINES 1 OF 3"]
    assert not [ms for ms, w in award if ms >= t and w.strip() == ""]
    assert not [ms for ms, w in hud(out, "ghidorah_heads", "Title") if w == "POWERLINES 1 OF 3"]


def test_a_running_mode_of_the_kit_steps_aside_and_runs_on(harness):
    out = play(harness, *POWERLINES, "secs", 2, "words", 1, "secs", 2, "words", 0, "secs", 1)
    t0, t1 = _at(out, ">> words 1"), _at(out, ">> words 0")
    s = "ghidorah_heads"
    assert has(out, "KING GHIDORAH", "START (three powerlines)")
    assert [w for ms, w in hud(out, s, "Award") if t0 <= ms < t1 and w == "KING GHIDORAH"]
    assert [w for ms, w in hud(out, s, "Title") if t0 <= ms < t1 and not w.strip()]
    assert [w for ms, w in hud(out, s, "Title") if ms >= t1 and w == "KING GHIDORAH"]
    assert not [ln for ln in out.splitlines() if "[KING GHIDORAH] END" in ln and t0 <= int(ln.split()[0]) < t1]


# ---- a mode file's own screen ------------------------------------------------------------------------------------
WORDS_STUBS = SCREEN_STUBS + [
    ("static int stock;\n", "static int stock, game_words;\nint pm_game_words(void) { return in_game ? game_words : 0; }\n"),
    ("        } else if (!strcmp(argv[k], \"ball_end\")) {",
     "        } else if (!strcmp(argv[k], \"words\")) {   /* words <0|1>: a screen of the game's has its words up */\n"
     "            game_words = atoi(argv[++k]);\n"
     "            printf(\"WORDS %d at %lu\\n\", game_words, now_ms);\n"
     "        } else if (!strcmp(argv[k], \"ball_end\")) {"),
]


@pytest.fixture(scope="module")
def harness_words(tmp_path_factory):
    return _build(tmp_path_factory, WORDS_STUBS, "words")


def test_a_mode_files_screen_steps_aside_for_the_games_words(harness_words, tmp_path):
    out = _run(harness_words, tmp_path, RUSH, "shot", "0x08000000", "tick", "30", "words", "1", "tick", "30",
               "words", "0", "tick", "30")
    lines = out.splitlines()
    on = next(i for i, ln in enumerate(lines) if ln.startswith("WORDS 1"))
    off = next(i for i, ln in enumerate(lines) if ln.startswith("WORDS 0"))
    shows = [(i, ln.split()[1]) for i, ln in enumerate(lines) if ln.startswith("SHOW ")]
    assert [v for i, v in shows if i < on][-1] == "1"
    hidden = [v for i, v in shows if on < i < off]
    assert hidden and set(hidden) == {"0"}
    assert set(v for i, v in shows if i > off) == {"1"}
    assert "RUSH: its screen steps aside - a screen of the game's has its words up" in out
    assert not [ln for ln in lines[on:off] if "RUSH END" in ln]


def test_aside_keep_keeps_a_mode_files_screen_up_over_the_games_words(harness_words, tmp_path):
    out = _run(harness_words, tmp_path, RUSH + "aside keep\n", "shot", "0x08000000", "tick", "30", "words", "1",
               "tick", "30")
    lines = out.splitlines()
    start = next(i for i, ln in enumerate(lines) if "RUSH START" in ln)
    assert [ln for ln in lines[start:] if ln.startswith("SHOW 0")] == []


# ---- the runtime's watch -----------------------------------------------------------------------------------------
def _runtime():
    with open(RUNTIME, encoding="utf-8") as f:
        return f.read()


def test_the_runtime_counts_a_drawn_background_of_the_games_that_is_not_the_city():
    src = _runtime()
    body = src[src.index("static void on_scene_show(unsigned *r)"):]
    body = body[:body.index("\n}\n")]
    # the background's own scene, let through (not swapped for a mode's clip in its place), and not the city
    assert "scene_show_backdrop(r);" in body
    # (and not under a full-screen clip of ours, drawn over everything)
    assert re.search(r"if \(bg && r\[0\] == sc && !bd_is_city\(e\) && !clip\.on\) gw_seen\(e\);", body)
    fn = src[src.index("static void gw_tick(void)\n{"):]
    fn = fn[:fn.index("\n}\n")]
    # only in a game, on a port with the backdrop lines; up after GW_HOLD_MS of shows, gone after GW_MISS_TICKS ticks
    # AND GW_GAP_MS without one (a pause of the whole machine is not "gone")
    for need in ("PM_CAN_BACKDROP", "!bd_v2", "pm_in_game()", "GW_GAP_MS", "GW_HOLD_MS", "GW_MISS_TICKS",
                 "GW_RECENT_MS"):
        assert need in fn, need
    assert "gw_tick();" in src[src.index("static void clip_tick(void)\n{"):][:600]      # once a tick


def test_the_sdk_declares_it():
    with open(os.path.join(str(SDK), "pad_mode.h"), encoding="utf-8") as f:
        assert "int pm_game_words(void);" in f.read()
