"""PAD-314: a mode started by shots made in ORDER, and one ended by any shot that does not score.

- ``starts_on sequence`` + ``trigger_seq <shots>`` lines in a mode file (tools/spike2_emu/modes/sdk/mode_file.c):
  the mode starts when one player makes those shots in that order, in one ball. A shot of the sequence out
  of turn starts the player over; ``trigger_seq_reset <shots>`` names more shots that do.
- mode_project: the ``start_sequence`` / ``sequence_reset_any`` fields, ``end_shot`` as "any shot that does
  not score", their checks, and the lines ``runtime_cfg`` writes for them.

The runtime half compiles mode_file.c for the HOST against test_spike2_mode_roster.py's stub of the SDK
calls, so it runs wherever an ELF C compiler is (skips otherwise).
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_spike2_mode_roster import _run, harness  # noqa: E402,F401  (harness is a fixture)

from pinball_decryptor.plugins.stern import mode_project as MP  # noqa: E402

# left ramp 0x1, right ramp 0x2, building 0x8; the targets 0x10 and 0x20 score
SEQ = ("name SNIPER\nstarts_on sequence\ntrigger_seq 0x1\ntrigger_seq 0x2\ntrigger_seq 0x1\ntrigger_seq 0x8\n"
       "seconds 5\nshots 0x30\naward 100\n")


def test_the_shots_in_order_start_it(harness, tmp_path):
    out = _run(harness, tmp_path, SEQ, "shot", "0x1", "shot", "0x2", "shot", "0x1", "shot", "0x8")
    assert "unknown key" not in out and "NOT VALID" not in out
    assert "starts on 4 shots in order" in out
    assert "SNIPER sequence 1 of 4 (player 1)" in out
    assert "SNIPER sequence 4 of 4 (player 1)" in out
    assert "SNIPER START (shot sequence)" in out


def test_a_shot_out_of_turn_starts_the_player_over(harness, tmp_path):
    out = _run(harness, tmp_path, SEQ, "shot", "0x1", "shot", "0x2", "shot", "0x8", "shot", "0x1", "shot", "0x8")
    assert "START" not in out
    assert "SNIPER sequence: 00000000_00000008 is not shot 3 of 4 - back to the start (player 1)" in out
    # the first shot of the sequence, made out of turn, counts as step 1 again
    out = _run(harness, tmp_path, SEQ, "shot", "0x1", "shot", "0x2", "shot", "0x2", "shot", "0x1",
               "shot", "0x2", "shot", "0x1", "shot", "0x8")
    assert "is not shot 3 of 4 - back to the start" in out
    assert "SNIPER START (shot sequence)" in out
    out = _run(harness, tmp_path, SEQ, "shot", "0x1", "shot", "0x2", "shot", "0x1", "shot", "0x1", "shot", "0x8")
    assert "START" not in out
    assert "is not shot 4 of 4 - back to 1 of the sequence, this shot (player 1)" in out


def test_a_shot_in_neither_list_is_ignored(harness, tmp_path):
    out = _run(harness, tmp_path, SEQ, "shot", "0x1", "shot", "0x100", "shot", "0x2", "shot", "0x100",
               "shot", "0x1", "shot", "0x8")
    assert "back to" not in out
    assert "SNIPER START (shot sequence)" in out


def test_the_reset_shots_start_the_player_over(harness, tmp_path):
    cfg = SEQ + "trigger_seq_reset 0x100\n"
    out = _run(harness, tmp_path, cfg, "shot", "0x1", "shot", "0x100", "shot", "0x2", "shot", "0x1", "shot", "0x8")
    assert "a shot in 00000000_00000100 out of turn starts the sequence over" in out
    assert "is not shot 2 of 4 - back to the start" in out
    assert "START" not in out
    out = _run(harness, tmp_path, cfg, "shot", "0x100", "shot", "0x1", "shot", "0x2", "shot", "0x1", "shot", "0x8")
    assert "SNIPER START (shot sequence)" in out


def test_the_end_of_a_ball_clears_the_progress(harness, tmp_path):
    out = _run(harness, tmp_path, SEQ, "shot", "0x1", "shot", "0x2", "shot", "0x1", "ball_end", "shot", "0x8")
    assert "START" not in out
    out = _run(harness, tmp_path, SEQ, "shot", "0x1", "shot", "0x2", "shot", "0x1", "ball_end", "shot", "0x1",
               "shot", "0x2", "shot", "0x1", "shot", "0x8")
    assert "SNIPER START (shot sequence)" in out


def test_each_player_keeps_their_own_progress(harness, tmp_path):
    out = _run(harness, tmp_path, SEQ, "shot", "0x1", "shot", "0x2", "shot", "0x1", "player", "2", "shot", "0x8")
    assert "START" not in out
    assert "SNIPER sequence 1 of 4 (player 1)" in out and "player 2" not in out.split("SNIPER sequence 3")[0]


def test_a_second_start_needs_the_whole_sequence_again(harness, tmp_path):
    out = _run(harness, tmp_path, SEQ, "shot", "0x1", "shot", "0x2", "shot", "0x1", "shot", "0x8", "tick", "400",
               "shot", "0x8", "shot", "0x1", "shot", "0x2", "shot", "0x1", "shot", "0x8")
    assert out.count("SNIPER START") == 2
    assert "SNIPER END (time ran out)" in out


def test_the_sequence_waits_for_its_other_shots(harness, tmp_path):
    cfg = SEQ + "trigger_also 0x40 1\n"
    out = _run(harness, tmp_path, cfg, "shot", "0x1", "shot", "0x2", "shot", "0x1", "shot", "0x8", "shot", "0x40")
    assert "SNIPER: its sequence is met - waiting for its other shots (player 1)" in out
    assert out.index("waiting for its other shots") < out.index("SNIPER START (shot sequence)")


def test_the_trigger_line_and_an_event_start_are_ignored_beside_a_sequence(harness, tmp_path):
    cfg = SEQ + "trigger 0x4 1\nstarts_on event ball_start\n"
    out = _run(harness, tmp_path, cfg, "shot", "0x4", "shot", "0x1", "shot", "0x2", "shot", "0x1", "shot", "0x8")
    assert "starts_on sequence: the trigger shots are ignored" in out
    assert out.count("SNIPER START") == 1 and "SNIPER START (shot sequence)" in out


def test_a_sequence_with_no_shots_is_not_valid(harness, tmp_path):
    cfg = "name SNIPER\nstarts_on sequence\nseconds 5\nshots 0x30\naward 100\n"
    out = _run(harness, tmp_path, cfg, "shot", "0x1")
    assert "NOT VALID, it needs seconds and a trigger_seq line" in out
    assert "START" not in out


def test_a_ninth_shot_is_skipped(harness, tmp_path):
    cfg = ("name SNIPER\nstarts_on sequence\n" + "".join("trigger_seq 0x%x\n" % (1 << i) for i in range(9))
           + "seconds 5\nshots 0x30\naward 100\n")
    out = _run(harness, tmp_path, cfg, "shot", "0x1")
    assert "trigger_seq: a mode has up to 8 shots in order - skipped" in out
    assert "starts on 8 shots in order" in out


def test_an_end_shot_mask_ends_it_on_any_of_its_shots(harness, tmp_path):
    """The tab's "any shot that does not score" is one end_shot mask: every shot in it ends the mode."""
    cfg = SEQ + "end_shot 0x1c8\n"
    out = _run(harness, tmp_path, cfg, "shot", "0x1", "shot", "0x2", "shot", "0x1", "shot", "0x8",
               "shot", "0x10", "shot", "0x40", "tick", "2")
    assert "SNIPER START (shot sequence)" in out
    assert "end shot 00000000_00000040: the mode ends on the next tick" in out
    assert "SNIPER END (end shot)" in out


# ---- mode_project: the fields, the file, the checks -----------------------------------------------------
def _sniper():
    spec = MP.ModeSpec(name="SNIPER", starts_on="sequence",
                       start_sequence=["Left ramp", "Right ramp", "Left ramp", "Right ramp", "Building"],
                       scoring_shots=["Left ramp", "Right ramp"])
    return spec


def _keys(text):
    out = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        k, _sp, v = line.partition(" ")
        out.setdefault(k, []).append(v.strip())
    return out


def test_a_sequence_start_replaces_the_trigger_line():
    spec = _sniper()
    assert MP.validate(spec) == []
    text = MP.runtime_cfg(spec, "sniper")
    keys = _keys(text)
    assert "trigger" not in keys
    assert text.splitlines()[2] == "starts_on      sequence"
    assert keys["trigger_seq"] == ["0x00100000", "0x00200000", "0x00100000", "0x00200000", "0x00400000"]
    assert "trigger_seq_reset" not in keys
    spec.sequence_reset_any = True
    keys = _keys(MP.runtime_cfg(spec, "sniper"))
    p = MP.GODZILLA_PRO_1_15
    others = [n for n, _m in p.shots if n not in p.switch_shots and n not in p.button_shots   # PAD-1403
              and n not in spec.start_sequence]
    assert keys["trigger_seq_reset"] == ["0x%08x" % p.mask(others)]
    assert p.mask(others) & p.mask(["Action button"]) == 0


def test_a_sequence_is_checked_against_the_title():
    spec = _sniper()
    spec.start_sequence = ["Left ramp"]
    assert "Pick at least two shots, in order, that start the mode." in MP.validate(spec)
    spec.start_sequence = ["Left ramp", "Snake"]
    assert "Godzilla Pro 1.15 has no shot called 'Snake' in the shots that start it." in MP.validate(spec)
    spec.start_sequence = ["Left ramp", "Right ramp"] * 5
    assert "A mode starts on at most 8 shots in order." in MP.validate(spec)
    spec.start_sequence = "Left ramp"
    assert "The shots that start the mode in order are a list of shot names." in MP.validate(spec)


def test_a_shot_start_writes_what_it_wrote_before_and_an_older_file_has_no_sequence():
    spec = MP.ModeSpec(name="X")
    before = MP.runtime_cfg(spec, "x")
    spec.start_sequence, spec.sequence_reset_any = ["Left ramp", "Right ramp"], True
    assert MP.runtime_cfg(spec, "x") == before            # only starts_on sequence uses them
    old = MP.ModeSpec.from_json({"format": 1, "name": "OLD"})
    assert old.start_sequence == [] and old.sequence_reset_any is False and old.starts_on == "shot"


def test_a_retarget_drops_the_sequence_shots_the_title_lacks():
    spec = _sniper()
    spec.start_sequence = ["Left ramp", "Right ramp", "Building", "Left ramp"]
    try:
        jaws = MP.profile("jaws_le_1_02")
    except MP.ModeProjectError:
        pytest.skip("no Jaws profile")
    new, dropped = MP.retarget(spec, jaws)
    assert "Building" in dropped
    assert new.start_sequence == [s for s in spec.start_sequence if s != "Building"]
    assert "Building is not a shot on %s, so it is left out of the shots that start the mode in order" % jaws.label \
        in MP.retarget_words(spec, new, dropped, jaws)


def test_any_shot_that_does_not_score_ends_it():
    spec = MP.ModeSpec(name="X", scoring_shots=["Left ramp", "Right ramp"], end_shot=MP.END_SHOT_OTHERS)
    assert MP.validate(spec) == []
    p = MP.GODZILLA_PRO_1_15
    keys = _keys(MP.runtime_cfg(spec, "x"))
    others = [n for n, _m in p.shots if n not in p.switch_shots and n not in p.button_shots   # PAD-1403
              and n not in spec.scoring_shots]
    assert keys["end_shot"] == ["0x%08x" % p.mask(others)]
    # the mode's own shots are not "other": a shot that adds a ball, the shot the balls come on
    spec.multiball, spec.add_ball_shot, spec.multiball_on_shot = True, "Maser target", "Action button"
    keys = _keys(MP.runtime_cfg(spec, "x"))
    assert keys["end_shot"] == ["0x%08x" % p.mask([n for n in others if n != "Maser target"])]
    # every shot scoring leaves nothing to end it on
    spec = MP.ModeSpec(name="X", scoring_shots=[n for n, _m in p.shots if n not in p.switch_shots and n not in p.button_shots],
                       end_shot=MP.END_SHOT_OTHERS)
    assert "Every shot scores, so no shot is left to end the mode." in MP.validate(spec)
    # a retarget keeps the choice: it names no shot
    new, dropped = MP.retarget(MP.ModeSpec(name="X", end_shot=MP.END_SHOT_OTHERS), MP.GODZILLA_PRO_1_15)
    assert new.end_shot == MP.END_SHOT_OTHERS and dropped == []


def test_any_of_a_list_of_shots_ends_it():
    """Ales's follow-up: a multi-select - end_shot as a list is one mask of every name in it."""
    p = MP.GODZILLA_PRO_1_15
    spec = MP.ModeSpec(name="X", end_shot=["Building", "Shield target left"])
    assert MP.validate(spec) == []
    assert _keys(MP.runtime_cfg(spec, "x"))["end_shot"] == ["0x%08x" % p.mask(["Building", "Shield target left"])]
    assert MP.end_shot_list(spec) == ["Building", "Shield target left"]
    assert MP.end_shot_list(MP.ModeSpec(name="X", end_shot="Building")) == ["Building"]
    assert MP.end_shot_list(MP.ModeSpec(name="X", end_shot=MP.END_SHOT_OTHERS)) == []
    spec.end_shot = ["Building", "Snake"]
    assert "Godzilla Pro 1.15 has no shot called 'Snake' to end the mode." in MP.validate(spec)
    spec.end_shot = []
    assert "Tick a shot that ends the mode, or pick (no shot)." in MP.validate(spec)
    assert not [ln for ln in MP.parameter_lines(MP.ModeSpec(name="X", end_shot=[]), "x", p) if "end_shot" in ln]
    spec.end_shot = ["Building", 3]
    assert "The shots that end the mode are a list of shot names." in MP.validate(spec)
    # a retarget drops the names the title lacks and says so
    try:
        jaws = MP.profile("jaws_le_1_02")
    except MP.ModeProjectError:
        pytest.skip("no Jaws profile")
    spec = MP.ModeSpec(name="X", end_shot=["Left ramp", "Building", "Godzilla target"])
    new, dropped = MP.retarget(spec, jaws)
    assert new.end_shot == ["Left ramp"] and {"Building", "Godzilla target"} <= set(dropped)
    assert "Building, Godzilla target are not on %s, so they are left out of the shots that end the mode early" \
        % jaws.label in MP.retarget_words(spec, new, dropped, jaws)


# ---- the P.S.: wrong shots cost points -------------------------------------------------------------------
PEN = ("name SNIPER\ntrigger 0x1 1\nseconds 5\nshots 0x30\naward 100\nshot_penalty 0x8 250\n"
       "shot_penalty 0x10 50\n")


def test_a_penalty_shot_takes_points_away_never_below_zero(harness, tmp_path):
    """The harness's pm_score_sub has a score of 300 to lose: the first hit takes 250, the second only 50."""
    out = _run(harness, tmp_path, PEN, "shot", "0x1", "shot", "0x8", "shot", "0x8", "shot", "0x10", "tick", "400")
    assert "unknown key" not in out
    assert "params: shot 00000000_00000008 takes 250 away" in out
    assert "params: shot 00000000_00000010 takes 50 away - but it scores, so it takes nothing" in out
    assert "penalty shot 00000000_00000008: -250 (asked 250), 250 lost" in out
    assert "penalty shot 00000000_00000008: -250 (asked 250), 500 lost" in out   # the stub takes up to 300 each time
    assert "penalty shot 00000000_00000010" not in out                           # it scores instead
    assert "shot 00000000_00000010: +100" in out
    assert "SNIPER END (time ran out): 1 shots, awarded 100, lost 500" in out


def test_a_penalty_shot_does_nothing_before_the_mode_or_after_its_end_shot(harness, tmp_path):
    out = _run(harness, tmp_path, PEN + "end_shot 0x40\n", "shot", "0x8", "shot", "0x1", "shot", "0x40", "shot", "0x8",
               "tick", "2")
    assert "penalty shot" not in out
    assert "SNIPER END (end shot)" in out


def test_minus_points_per_shot_become_a_penalty_line():
    p = MP.GODZILLA_PRO_1_15
    spec = MP.ModeSpec(name="X", shot_award=[["Building", -250000], ["Maser target", 5000000]])
    assert MP.validate(spec) == []
    keys = _keys(MP.runtime_cfg(spec, "x"))
    assert keys["shot_penalty"] == ["0x%08x 250000" % p.mask(["Building"])]
    assert keys["shot_award"] == ["0x%08x 5000000" % p.mask(["Maser target"])]
    spec.shot_award = [["Building", 0]]
    assert "Building's own points must be a whole number, not 0 (a minus number takes points away)." in MP.validate(spec)
    spec.shot_award = [["Left ramp", -1000]]
    assert "Left ramp scores, so it cannot take points away too: untick it under Shots that score." in MP.validate(spec)


def test_the_total_at_the_end_is_net_of_the_penalties(harness, tmp_path):
    """Ales (PAD-314 thread): 3 loops for 1M and 6 lanes at -500k showed TOTAL 3,000,000; he expected 0."""
    cfg = "name SNIPER\ntrigger 0x1 1\nseconds 5\nshots 0x30\naward 100\naward_ladder fixed\nshot_penalty 0x8 100\n"
    out = _run(harness, tmp_path, cfg, "shot", "0x1", "shot", "0x10", "shot", "0x10", "shot", "0x8", "shot", "0x8",
               "tick", "400")
    assert "SNIPER END (time ran out): 2 shots, awarded 200, lost 200, total 0," in out
    out = _run(harness, tmp_path, cfg, "shot", "0x1", "shot", "0x10", "shot", "0x8", "shot", "0x8", "tick", "400")
    assert "awarded 100, lost 200, total -100," in out
    out = _run(harness, tmp_path, cfg, "shot", "0x1", "shot", "0x10", "shot", "0x10", "tick", "400")
    assert "awarded 200, lost 0, total 200," in out
