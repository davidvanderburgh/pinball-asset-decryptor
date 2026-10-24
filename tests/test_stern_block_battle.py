"""PAD-706: a blocks mode in one of Godzilla's battles - "When the player picks <battle> on the battle selection
screen" - and the battle counted as the game's own, won or lost (plugins/stern/block_modes.py; the runtime's side
is in pad_mode_runtime.c, "PAD-706: the pick counts as the battle it replaced").

- Everywhere: the hat's checks and words, the C it makes (the claim, the pick run on the tick, the battle given
  back with its outcome at the mode's end), End the mode's "the battle won", and the Godzilla ports' lines.
- The desk harness (sdk/examples/desk_harness.c), where an ELF host C compiler is: a pick plays the mode, and its
  end gives the battle back won or lost.
"""
import os
import re
import shutil
import subprocess
import sys

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import mode_project as MP

SDK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu", "modes", "sdk")
ROSTER = list(MP.ROSTER_NAMES["godzilla_le"])
SHOTS = ["Left ramp", "Right ramp", "Building", "Big loop"]


def num(v):
    return {"k": "num", "v": v}


def gigan(won_block=True, seconds=30, hat=None):
    """Gigan's slot (2) taken: two Buildings win it (or, without won_block, just end it)."""
    end = {"op": "end_mode", "won": True} if won_block else {"op": "end_mode"}
    return {"name": "GIGAN STAGES", "seconds": seconds, "game_modes": "stack",
            "vars": [{"name": "stage", "reset": "mode"}],
            "scripts": [
                {"hat": hat or {"kind": "battle", "slot": 2, "name": "Gigan"}, "do": [{"op": "start_mode"}]},
                {"hat": {"kind": "shot", "shot": "Building", "when": "running"}, "do": [
                    {"op": "score", "points": num(1000000)},
                    {"op": "change", "var": "stage", "by": num(1)},
                    {"op": "if", "cond": {"k": "cmp", "op": ">", "a": {"k": "var", "name": "stage"}, "b": num(1)},
                     "then": [end]}]}]}


def problems(program, roster=ROSTER):
    return BM.problems(program, shots=SHOTS, roster=roster)


# ---- the hat ---------------------------------------------------------------------------------------
def test_a_battle_hat_on_a_card_with_a_roster_builds():
    assert problems(gigan()) == []
    assert BM.HATS["battle"] == "When the player picks a battle"


def test_a_card_without_a_battle_selection_says_so():
    out = problems(gigan(), roster=[])
    assert any("waits for a battle to be picked, which a mode cannot take the place of" in p for p in out)


def test_a_slot_the_card_does_not_have_or_none_is_named():
    assert any("has no battle chosen" in p for p in problems(gigan(hat={"kind": "battle"})))
    out = problems(gigan(hat={"kind": "battle", "slot": 9, "name": "?"}))
    assert any("battle 9, which this card's battle selection does not have" in p for p in out)


def test_one_script_per_battle():
    p = gigan()
    p["scripts"].append({"hat": {"kind": "battle", "slot": 2, "name": "Gigan"}, "do": [{"op": "start_mode"}]})
    assert any("waits for Gigan too: one script per battle" in x for x in problems(p))


def test_the_words_name_the_battle():
    assert BM._hat_words({"kind": "battle", "slot": 2, "name": "Gigan"}) == \
        "when the player picks Gigan on the battle selection screen"
    assert BM.battle_name({"kind": "battle", "slot": 4}) == "battle 4"


def test_the_notes_say_how_the_battle_is_won():
    notes = BM.notes(gigan(won_block=False))
    assert any("counts as won when the mode ends by its clock or an End the mode block" in n for n in notes)
    assert not any("counts as won when" in n for n in BM.notes(gigan()))
    p = gigan()
    p["scripts"][0]["do"] = []
    assert any("script with no Start the mode in it starts nothing" in n for n in BM.notes(p))
    lone = {"name": "X", "seconds": 30, "scripts": [{"hat": {"kind": "mode_start"}, "do": [{"op": "end_mode", "won": True}]}]}
    assert any("wins a battle only for a mode the player picked" in n for n in BM.notes(lone))


def test_card_checks_carry_the_roster():
    p = MP.GODZILLA_PRO_1_15
    assert BM.card_checks(p)["roster"] == list(getattr(p, "roster", ()) or ())


# ---- the C ----------------------------------------------------------------------------------------
def test_the_c_claims_the_slot_and_gives_the_battle_back_with_its_outcome():
    c = BM.to_c(gigan(), "gigan_stages")
    assert "static const unsigned BATTLE_SLOTS[1] = { 2 };" in c
    assert "pm_roster_claim(BATTLE_SLOTS[i], on_battle)" in c
    assert "pm_roster_over(won);" in c
    assert "battle_won = 1;" in c                                   # the End the mode, the battle won block
    assert 'pm_port_value("roster_start_after_ms", 0)' in c        # it runs once the selection screen has closed
    # an End block that does not say "won" in a mode that has one does not win it
    assert c.count("battle_won = 1;") == 1


def test_without_a_won_block_its_own_end_wins_it():
    c = BM.to_c(gigan(won_block=False), "gigan_stages")
    assert c.count("battle_won = 1;") == 2                           # its End block, and its clock's end
    assert re.search(r"battle_won = 1;\s+/\* PAD-706: no block wins the battle: its clock's end does \*/\s+"
                     r"end\(\"time ran out\"\);", c)


def test_a_mode_with_no_battle_hat_has_no_roster_code():
    p = gigan()
    p["scripts"][0]["hat"] = {"kind": "mode_start"}
    c = BM.to_c(p, "plain")
    assert "pm_roster" not in c and "BATTLE_SLOTS" not in c
    assert "battle_won = 1;" in c                                   # the won End still compiles: it just ends


def test_the_c_only_calls_what_the_header_declares():
    with open(os.path.join(SDK, "pad_mode.h"), encoding="utf-8") as f:
        declared = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", f.read()))
    used = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", BM.to_c(gigan(), "gigan_stages")))
    assert used <= declared, used - declared


# ---- the ports ------------------------------------------------------------------------------------
@pytest.mark.parametrize("port", ["godzilla_le-1.16", "godzilla_pro-1.16"])
def test_the_godzilla_ports_name_the_battles_stop_start_and_resume(port):
    with open(os.path.join(SDK, "ports", port + ".port"), encoding="utf-8") as f:
        text = f.read()
    for name in ("battle_stop", "battle_started", "battle_clock", "roster_resume", "roster_cursor"):
        assert re.search(r"^site %s\s+0x[0-9a-f]{8} 0x[0-9a-f]{8} 0x[0-9a-f]{8}" % name, text, re.M), name
    for name, value in (("battle_stopped_at", "0x13"), ("battle_reason_at", "0x17"), ("battle_starts_at", "0x3c"),
                        ("battle_wins_at", "0x64"), ("battle_flags_at", "8"), ("battle_no_city_flag", "0x10"),
                        ("battle_total_at", "0xf0"), ("roster_city_battle_vec_at", "56"),
                        ("battle_own_stop_slots", "0x20")):
        assert re.search(r"^value %s\s+%s\b" % (name, value), text, re.M), name
    # the resume is the START's load after the city pick's pop: the same two words as the pick's
    start = re.search(r"^site roster_start\s+0x[0-9a-f]+ (0x[0-9a-f]+ 0x[0-9a-f]+)", text, re.M).group(1)
    resume = re.search(r"^site roster_resume\s+0x[0-9a-f]+ (0x[0-9a-f]+ 0x[0-9a-f]+)", text, re.M).group(1)
    assert start == resume == "0xe5903000 0xe5933020"


# ---- the desk -------------------------------------------------------------------------------------
def _cc():
    if os.name == "nt":
        pytest.skip("the desk harness needs an ELF linker (__start_pm_modes / __stop_pm_modes)")
    if sys.platform == "darwin":
        pytest.skip("the desk harness needs an ELF toolchain (section(\"pm_modes\"))")
    for c in ("gcc", "cc", "clang"):
        if shutil.which(c):
            return c
    pytest.skip("no host C compiler")


def play(tmp_path, program, *args, slug="gigan_stages"):
    cc = _cc()
    src = tmp_path / (slug + ".c")
    src.write_text(BM.to_c(program, slug), encoding="utf-8")
    exe = tmp_path / "harness"
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wextra", "-Wno-unused-parameter", "-I", SDK,
                        "-I", os.path.join(SDK, "examples"), "-o", str(exe),
                        os.path.join(SDK, "examples", "desk_harness.c"), str(src)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "warning" not in r.stderr.lower(), r.stderr
    r = subprocess.run([str(exe), "new_game"] + [str(a) for a in args], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_a_pick_plays_the_mode_and_its_win_gives_the_battle_back_won(tmp_path):
    out = play(tmp_path, gigan(), "pick", 2, "secs", 1, "shot", "Building", "shot", "Building", "secs", 2)
    assert "ROSTER CLAIM 2 GIGAN STAGES" in out
    assert "PICK 2 -> 1" in out
    assert "[GIGAN STAGES] START (a block): player 1" in out
    assert "[GIGAN STAGES] the battle it took the place of: WON" in out
    assert out.count("ROSTER OVER") == 1 and "ROSTER OVER WON" in out


def test_a_drain_loses_the_battle(tmp_path):
    out = play(tmp_path, gigan(), "pick", 2, "secs", 1, "shot", "Building", "ball_end", "secs", 12)
    assert "END (ball ended)" in out
    assert out.count("ROSTER OVER") == 1 and "ROSTER OVER lost" in out


def test_without_a_won_block_the_clock_wins_it(tmp_path):
    out = play(tmp_path, gigan(won_block=False, seconds=5), "pick", 2, "secs", 7)
    assert "END (time ran out)" in out
    assert "ROSTER OVER WON" in out


def test_with_a_won_block_the_clock_loses_it(tmp_path):
    out = play(tmp_path, gigan(seconds=5), "pick", 2, "secs", 7)
    assert "END (time ran out)" in out
    assert "ROSTER OVER lost" in out


def test_another_slot_is_not_taken_and_a_pick_while_it_runs_restarts_nothing(tmp_path):
    out = play(tmp_path, gigan(), "pick", 3, "pick", 2, "secs", 1, "pick", 2, "secs", 1)
    assert "PICK 3 -> -1" in out
    assert out.count("START (a block)") == 1
    assert "battle 2 picked while it runs - its end gives the pick back" in out


def test_a_pick_the_mode_cannot_start_is_given_back_lost(tmp_path):
    p = gigan()
    p["scripts"][0]["do"] = []                                      # nothing starts it
    out = play(tmp_path, p, "pick", 2, "secs", 1)
    assert "the battle pick started nothing - given back, a battle lost" in out
    assert "ROSTER OVER lost" in out

