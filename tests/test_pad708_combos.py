"""PAD-708: combos as blocks - a When block for shots made one after another, each within N seconds of the last.

- Everywhere: the hat's checks and words, the values that go with it (the combos in a row, a combo's shots made so
  far), the C only calling what pad_mode.h declares and only carrying the combos' code when a program has one, the
  desk player (blocks_sim) judging combos as the C does, the script view and the rules sheet saying them.
- The desk harness (sdk/examples/desk_harness.c), where an ELF host C compiler is: the C made from a program played
  against the fake game - a combo in its window and out of it, in order and out of it, the chain, its lapse, an
  ordered combo's steps, a lit shot as a step, and the ball's end - with the desk player giving the same scores.
"""
import re

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import blocks_sim as BS
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_script as MS
from pinball_decryptor.plugins.stern import rules_sheet as RS

from tests.test_stern_block_modes import _header_calls, play, scores

GZ = MP.GODZILLA_PRO_1_15
SHOTS = [n for n, _m in GZ.shots]


def num(v):
    return {"k": "num", "v": v}


def times(a, b):
    return {"k": "op", "op": "*", "a": a, "b": b}


def plus(a, b):
    return {"k": "op", "op": "+", "a": a, "b": b}


def combo(shots, seconds=3, when="running", name=""):
    h = {"kind": "combo", "shots": list(shots), "seconds": seconds, "when": when}
    if name:
        h["name"] = name
    return h


def prog(scripts, seconds=60, **kw):
    out = {"name": "COMBO TEST", "seconds": seconds, "vars": [], "scripts": scripts, "game_modes": "stack"}
    out.update(kw)
    return out


START = {"hat": {"kind": "shot", "shot": "Building", "when": "idle"}, "do": [{"op": "start_mode"}]}


def ramps_prog():
    """Left ramp then Right ramp within 3 s scores 1,000 x the combos in a row."""
    return prog([START, {"hat": combo(["Left ramp", "Right ramp"]), "do": [
        {"op": "score", "points": times(num(1000), {"k": "combo_chain"})}]}])


def sim_scores(program, *args):
    """The desk player's scores for the harness's arguments (shot / ms / secs / ball_end)."""
    sim = BS.Sim(program)
    sim.advance(1000)
    args = list(args)
    while args:
        c = args.pop(0)
        if c == "shot":
            sim.shot(args.pop(0))
            sim.advance(50)
        elif c == "ms":
            sim.advance(int(args.pop(0)))
        elif c == "secs":
            sim.advance(int(float(args.pop(0)) * 1000))
        elif c == "ball_end":
            sim.new_ball()
    return [e[1] for e in sim.events if e[0] == "score" and e[1] > 0]


# ---- the program ---------------------------------------------------------------------------------
def test_the_hat_is_checked():
    ok = prog([START, {"hat": combo(["Left ramp", "lit", "*"], 2.5, name="RAMPS"), "do": []}])
    assert BM.problems(ok, SHOTS, GZ.events) == []
    bad = prog([START,
                {"hat": combo(["Left ramp"]), "do": []},
                {"hat": combo(["Left ramp", "Nowhere"], 0.1), "do": []},
                {"hat": combo(["Left ramp"] * 7, 3, when="sometimes"), "do": []},
                {"hat": combo(["Left ramp", "Right ramp"], name="9 bad"), "do": []},
                {"hat": combo(["Left ramp", "Right ramp"], name="TWIN"), "do": []},
                {"hat": combo(["Right ramp", "Left ramp"], name="twin"), "do": [
                    {"op": "score", "points": {"k": "combo_steps", "combo": "ELSEWHERE"}},
                    {"op": "score", "points": {"k": "combo_steps", "combo": ""}}]}])
    out = BM.problems(bad, SHOTS, GZ.events)
    assert "Script 2's combo needs two shots or more: one, then the next." in out
    assert "Script 3's combo shot 2 names Nowhere, a shot this card does not have." in out
    assert "Script 3's combo window must be 0.5 to 60 seconds." in out
    assert "Script 4's combo has 7 shots: 6 at most." in out
    assert "Script 4's When has no while." in out
    assert any(p.startswith("Script 5's combo name '9 bad' is not one") for p in out)
    assert "Two combos are called TWIN." in out
    assert ("Script 7 counts the shots of the combo ELSEWHERE, which no When block makes: give a combo that name."
            in out)
    assert "Script 7 counts the shots of a combo with none chosen." in out
    many = prog([START] + [{"hat": combo(["Left ramp", "Right ramp"]), "do": []}] * (BM.MAX_COMBOS + 1))
    assert "%d combos: %d at most." % (BM.MAX_COMBOS + 1, BM.MAX_COMBOS) in BM.problems(many, SHOTS)


def test_the_chain_with_no_combo_is_a_note():
    p = prog([START, {"hat": {"kind": "any_shot", "when": "running"}, "do": [
        {"op": "score", "points": times(num(10), {"k": "combo_chain"})}]}])
    assert BM.problems(p, SHOTS) == []
    assert any("No When block makes a combo" in n for n in BM.notes(p))
    assert not any("combo" in n for n in BM.notes(ramps_prog()))


def test_the_hat_in_words():
    assert BM.combo_words(combo(["Left ramp", "Right ramp"])) == \
        "when Left ramp, then Right ramp within 3 s, while the mode runs"
    assert BM.combo_words(combo(["lit", "*", "Big loop"], 2.5, when="any", name="TAG")) == \
        "when a lit shot, then any shot, then Big loop, each within 2.5 s (TAG), any time"
    c = BM.to_c(ramps_prog(), "blk")
    assert "/* script 2: when Left ramp, then Right ramp within 3 s, while the mode runs */" in c


def test_the_c_carries_combos_only_when_it_has_one_and_calls_only_the_header():
    plain = BM.to_c(prog([START, {"hat": {"kind": "any_shot", "when": "running"}, "do": [
        {"op": "score", "points": times(num(10), {"k": "combo_chain"})}]}]), "blk")
    assert "combo_ring" not in plain and "COMBO[" not in plain
    assert "score(((10LL) * 0LL));" in plain   # no combo: the chain is 0
    c = BM.to_c(prog([START, {"hat": combo(["Left ramp", "lit", "*"], name="R"), "do": [
        {"op": "score", "points": {"k": "combo_steps", "combo": "r"}}]}]), "blk")
    # Left ramp is S[1], after the Building; a step is up to 4 shots (-3: no more), -2 a lit shot, -1 any shot
    assert "{ 3, 3000u, 2, { { 1, -3, -3, -3 }, { -2, -3, -3, -3 }, { -1, -3, -3, -3 }, { -3, -3, -3, -3 }," in c
    assert "combo_made_so_far(0)" in c
    assert set(re.findall(r"\b(pm_[a-z_]+)\s*\(", c)) <= _header_calls()


def test_the_script_view_carries_a_combo_out_and_back():
    p = prog([START, {"hat": combo(["Left ramp", "lit"], 2.5, name="RAMPS"), "do": [
        {"op": "score", "points": plus({"k": "combo_chain"}, {"k": "combo_steps", "combo": "RAMPS"})}]}])
    text = MS.to_script(p)
    assert 'with on.combo(shots=["Left ramp", "lit"], seconds=2.5, when="running", name="RAMPS"):' in text
    assert "combo_chain() + combo_steps(combo=\"RAMPS\")" in text
    back = MS.from_script(text)
    assert back["scripts"] == BM.normalize(p)["scripts"]


# ---- the desk player (blocks_sim): the same rules as the C -----------------------------------------
def test_the_desk_player_makes_combos_as_the_c_does():
    p = ramps_prog()
    # the start shot, then: a combo (x1), a chain (x2: Left again then Right in its window), the window lapsed
    # (Left, 3.5 s, Right: none), out of order (Right then Left: none), and Left then Right a new chain from 1
    got = sim_scores(p, *RAMPS_RUN)
    assert got == RAMPS_SCORES


RAMPS_RUN = ("shot", "Building",
             "shot", "Left ramp", "ms", 1000, "shot", "Right ramp",
             "ms", 500, "shot", "Left ramp", "ms", 1000, "shot", "Right ramp",
             "ms", 4000, "shot", "Left ramp", "ms", 3500, "shot", "Right ramp",
             "ms", 4000, "shot", "Right ramp", "ms", 500, "shot", "Left ramp",
             "ms", 500, "shot", "Right ramp")
#: 1000 x 1, x 2; then 4 s pass: the chain lapsed; Left-(3.5 s)-Right is out of its window; a Right ramp alone
#: begins nothing, and the Left then Right after it is a combo again - the first of a new chain
RAMPS_SCORES = [1000, 2000, 1000]


def test_the_rules_sheet_says_a_combo_in_a_stage():
    p = prog([
        START,
        {"hat": {"kind": "mode_start"}, "do": [
            {"op": "light_shot", "shot": "Left ramp", "color": "#ffd000", "pattern": "blink"},
            {"op": "light_shot", "shot": "Right ramp", "color": "#ffd000", "pattern": "blink"}]},
        {"hat": combo(["Left ramp", "Right ramp"], 3), "do": [
            {"op": "score", "points": times(num(1000000), {"k": "combo_chain"})}]}])
    words = RS.blocks_rules(p)
    assert words["start"].startswith("Building")
    assert any("combo Left ramp, then Right ramp within 3 s" in line for line in words["stages"]), words


def test_an_idle_combo_that_starts_the_mode_is_its_start_rule():
    p = prog([{"hat": combo(["Left ramp", "Right ramp", "Big loop"], 3, when="idle"), "do": [{"op": "start_mode"}]},
              {"hat": {"kind": "any_shot", "when": "running"}, "do": [{"op": "score", "points": num(1000)}]}])
    words = RS.blocks_rules(p)
    assert words["start"] == "Combo Left ramp, then Right ramp, then Big loop, each within 3 s", words
    assert words["counts"] == [1, 1, 1]


# ---- the desk harness ------------------------------------------------------------------------------
def test_a_combo_in_its_window_and_in_order(tmp_path):
    out = play(tmp_path, ramps_prog(), *RAMPS_RUN)
    assert scores(out) == RAMPS_SCORES == sim_scores(ramps_prog(), *RAMPS_RUN)
    assert out.count("combo (1 in a row)") == 2 and out.count("combo (2 in a row)") == 1


def test_the_shot_that_starts_it_and_the_ones_before_are_not_its_combo(tmp_path):
    # a running combo: the Left ramp before the start, and the start shot, begin nothing; ramps made while the mode
    # is not running make no running combo; an idle one ("while it is not running") only then
    p = prog([
        {"hat": {"kind": "shot", "shot": "Right ramp", "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": combo(["Left ramp", "Right ramp"], 3, when="running"), "do": [{"op": "score", "points": num(7)}]},
        {"hat": combo(["Big loop", "Big loop"], 3, when="idle"), "do": [{"op": "log", "text": "IDLE COMBO"}]}])
    run = ("shot", "Big loop", "shot", "Big loop", "shot", "Left ramp", "shot", "Right ramp", "shot", "Big loop",
           "shot", "Big loop", "shot", "Left ramp", "shot", "Right ramp")
    out = play(tmp_path, p, *run)
    assert out.count("IDLE COMBO") == 1                  # before the start; none while it runs
    assert scores(out) == [7]
    assert sim_scores(p, *run) == [7]


def test_an_ordered_combo_counts_its_steps_and_its_first_shot_again_begins_it_again(tmp_path):
    # ramp -> loop -> ramp, each within 2 s: every shot scores 100 + 10 x its steps made so far (after the combo's
    # own script, which scores 5000)
    p = prog([START,
              {"hat": combo(["Left ramp", "Big loop", "Left ramp"], 2, name="RLR"), "do": [
                  {"op": "score", "points": num(5000)}]},
              {"hat": {"kind": "any_shot", "when": "running"}, "do": [
                  {"op": "score", "points": plus(num(100), times(num(10), {"k": "combo_steps", "combo": "RLR"}))}]}])
    run = ("shot", "Building", "ms", 500,
           "shot", "Left ramp", "ms", 500,                # 1
           "shot", "Left ramp", "ms", 500,                # its first shot again: it begins again, 1
           "shot", "Big loop", "ms", 500,                 # 2
           "shot", "Left ramp", "ms", 500,                # made: 5000, and its last ramp is 1 toward the next
           "shot", "Big loop", "ms", 2500,                # 2; then 2.5 s
           "shot", "Left ramp")                           # out of the loop's window: 1, no combo
    want = [110, 110, 120, 5000, 110, 120, 110]
    out = play(tmp_path, p, *run)
    assert scores(out) == want == sim_scores(p, *run)


def test_a_lit_shot_after_another_shots_between_and_a_dark_one_is_none(tmp_path):
    # King Caesar's TAG TEAM as one block: the Godzilla target lights the Left ramp; a lit shot made within 5 s of
    # the target is the combo, whatever the ball hits between (the Right ramp, never lit, neither makes nor breaks
    # it). The Left ramp held dark is not lit; nor is it once the combo has put its light out
    p = prog([START,
              {"hat": {"kind": "shot", "shot": "Godzilla target", "when": "running"}, "do": [
                  {"op": "light_shot", "shot": "Left ramp", "color": "#ffb000", "pattern": "chase"}]},
              {"hat": {"kind": "shot", "shot": "Maser target", "when": "running"}, "do": [
                  {"op": "light_shot", "shot": "Left ramp", "color": "#000000", "pattern": "off"}]},
              {"hat": combo(["Godzilla target", "lit"], 5), "do": [
                  {"op": "score", "points": num(2000000)}, {"op": "lights_off", "shot": "Left ramp"}]}])
    run = ("shot", "Building",
           "shot", "Godzilla target", "ms", 1000, "shot", "Right ramp", "shot", "Left ramp",   # the combo, light out
           "shot", "Left ramp",                                                              # not lit now: none
           "shot", "Godzilla target", "ms", 1000, "shot", "Maser target", "shot", "Left ramp",   # dark: none
           "ms", 6000, "shot", "Left ramp")                                                  # its window lapsed
    out = play(tmp_path, p, *run)
    assert scores(out) == [2000000] == sim_scores(p, *run)


def test_a_spinner_between_does_not_break_an_ordered_combo_and_the_window_does(tmp_path):
    p = prog([START, {"hat": combo(["Left ramp", "Big loop", "Right ramp"], 3), "do": [
        {"op": "score", "points": num(500)}]}])
    run = ("shot", "Building",
           "shot", "Left ramp", "shot", "Top spinner", "shot", "Top spinner", "shot", "Big loop",
           "shot", "Left spinner", "shot", "Right ramp",                     # made: the spinners do not matter
           "shot", "Left ramp", "shot", "Big loop", "ms", 3500, "shot", "Right ramp")   # the window lapsed
    out = play(tmp_path, p, *run)
    assert scores(out) == [500] == sim_scores(p, *run)


def test_a_step_of_one_of_several_shots():
    p = prog([START, {"hat": combo(["Godzilla target", ["Maser target", "Big loop"]], 20, name="TAG TEAM"),
                      "do": []}])
    assert BM.problems(p, SHOTS) == []
    assert BM.combo_words(p["scripts"][1]["hat"], when=False) ==         "when Godzilla target, then Maser target or Big loop within 20 s (TAG TEAM)"
    c = BM.to_c(p, "blk")
    assert "{ { 1, -3, -3, -3 }, { 2, 3, -3, -3 }," in c
    bad = prog([START, {"hat": combo(["Left ramp", ["Big loop", "lit"]]), "do": []},
                {"hat": combo(["Left ramp", ["Big loop", "Nowhere"]]), "do": []},
                {"hat": combo(["Left ramp", ["Big loop"] * 5]), "do": []}])
    out = BM.problems(bad, SHOTS)
    assert "Script 2's combo shot 2 is one of 1 to 4 shots of the card's." in out
    assert "Script 3's combo shot 2 names Nowhere, a shot this card does not have." in out
    assert "Script 4's combo shot 2 is one of 1 to 4 shots of the card's." in out


def test_one_of_several_shots_makes_the_step_and_no_other(tmp_path):
    # TAG TEAM: the Godzilla target, then a pop or the Mecha lane (here the Maser target or the Big loop) within 20 s;
    # the Godzilla target again only begins it again, and the Right ramp between is no step
    p = prog([START, {"hat": combo(["Godzilla target", ["Maser target", "Big loop"]], 20), "do": [
        {"op": "score", "points": times(num(1000), {"k": "combo_chain"})}]}])
    run = ("shot", "Building",
           "shot", "Godzilla target", "shot", "Godzilla target", "shot", "Right ramp", "shot", "Big loop",   # x1
           "shot", "Godzilla target", "ms", 2000, "shot", "Maser target",                                  # x2
           "shot", "Big loop")                                                                              # none
    out = play(tmp_path, p, *run)
    assert scores(out) == [1000, 2000] == sim_scores(p, *run)


def test_the_chain_ends_with_the_ball_and_with_the_mode(tmp_path):
    p = prog([START,
              {"hat": combo(["*", "*"], 3, when="any"), "do": [
                  {"op": "score", "points": times(num(1000), {"k": "combo_chain"})}]},
              {"hat": {"kind": "shot", "shot": "Maser target", "when": "running"}, "do": [{"op": "end_mode"}]}],
             ends_on_drain=False)
    run = ("shot", "Building", "shot", "Left ramp", "shot", "Right ramp",   # the start shot begins none; x1
           "shot", "Big loop",                                              # x2
           "ball_end", "shot", "Left ramp", "shot", "Right ramp",           # a new ball: none, then x1 again
           "shot", "Maser target",                                          # x2, and it ends: the chain with it
           "shot", "Building", "shot", "Left ramp", "shot", "Right ramp")   # started again: x1
    out = play(tmp_path, p, *run)
    assert scores(out) == [1000, 2000, 1000, 2000, 1000]
    assert sim_scores(p, *run) == scores(out)


def test_the_chain_counts_one_a_shot_however_many_combos_it_makes(tmp_path):
    p = prog([START,
              {"hat": combo(["Left ramp", "Right ramp"], 3), "do": [{"op": "score", "points": times(num(10), {"k": "combo_chain"})}]},
              {"hat": combo(["*", "*"], 3), "do": [{"op": "score", "points": times(num(1), {"k": "combo_chain"})}]}])
    run = ("shot", "Building", "shot", "Left ramp", "shot", "Right ramp", "shot", "Big loop")
    out = play(tmp_path, p, *run)
    # the Right ramp makes two combos: one more in a row (x1) for both; the Big loop one (any then any): x2
    assert scores(out) == [10, 1, 2] == sim_scores(p, *run)


def test_the_hud_counter_follows_the_chain(tmp_path):
    p = prog([START, {"hat": combo(["*", "*"], 2, name="TAG TEAM"), "do": []}],
             hud={"on": True, "line": "COMBOS", "counters": [{"label": "COMBO", "value": {"k": "combo_chain"}}, {}, {}]})
    assert BM.problems(p, SHOTS) == []
    c = BM.to_c(p, "blk")
    assert "hud_counter(0, combo_in_row(), 0, 0);" in c
    play(tmp_path, p, "shot", "Building", "shot", "Left ramp", "ms", 3000)
