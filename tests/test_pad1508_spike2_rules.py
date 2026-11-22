"""PAD-1508: Spike 2's mode rules carried over to the JJP/Spooky .mode key set - the JJP
check takes them and names every bad value, and the runtime reads the same keys and limits
(the runtime itself is proven on Wonka 03.03 in the emulator)."""
import importlib.util
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(HERE, "tools", "jjp_emu")
PORT = {"title": "Wonka", "switches": ["switch_target_bank_1", "switch_target_bank_2", "switch_target_tv",
                                       "switch_ramp_left_made", "switch_target_factory"],
        "lamps": ["lp_gi_tv"], "sounds": ["se_Fanfare_GT_1", "se_Fanfare_Jackpot"], "fonts": [], "game_modes": []}


@pytest.fixture(scope="module")
def mm():
    sys.path.insert(0, RIG)
    try:
        spec = importlib.util.spec_from_file_location("mkjjpmodes_t1508", os.path.join(RIG, "mkjjpmodes.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(RIG)
    return mod


def _check(mm, tmp_path, **files):
    for name, text in files.items():
        (tmp_path / name.replace("__", ".")).write_text(text)
    return mm.check_modes(str(tmp_path), PORT)


GOOD = ("name = Rules A\nstart = switch_target_bank_1\nstart_also = switch_target_bank_2 2\n"
        "start_also = switch_target_tv\nstart_max = 2\ncooldown = 8\nshots = switch_target_tv\n"
        "shot_points = switch_ramp_left_made 3,000,000\nshot_points = switch_target_factory 500000\n"
        "points_ladder = rising\nend_shots = switch_target_factory\nseconds = 30\n"
        "sound_at = 25 se_Fanfare_GT_1\nsound_at = 10 hurry.wav\nsound_shot = se_Fanfare_Jackpot\n"
        "sound_shot_every = 2\nlamps = lp_gi_tv\nlamp_pattern = chase\ncombo_seconds = 0\n")


def test_every_spike2_rule_checks_clean_and_repeats_keep_every_line(mm, tmp_path):
    (tmp_path / "hurry.wav").write_bytes(b"RIFF")
    modes, problems = _check(mm, tmp_path, a__mode=GOOD,
                             b__mode="name = Rules B\nstart = switch_target_tv\nstart_needs = Rules A ball\n")
    assert problems == []
    a = modes[0]
    assert a["start_also"].split("\n") == ["switch_target_bank_2 2", "switch_target_tv"]
    assert a["shot_points"].split("\n") == ["switch_ramp_left_made 3,000,000", "switch_target_factory 500000"]
    assert a["sound_at"].split("\n") == ["25 se_Fanfare_GT_1", "10 hurry.wav"]


@pytest.mark.parametrize("line,says", [
    ("shot_points = switch_target_tv", "shot_points must be <switches> <points>"),
    ("shot_points = switch_typo 100", "not in Wonka: switch_typo"),
    ("points_ladder = steep", "points_ladder must be one of fixed, rising"),
    ("lamp_pattern = disco", "lamp_pattern must be one of solid, blink, pulse, chase"),
    ("start_also = switch_target_tv 0", "count must be 1-99"),
    ("sound_at = soon se_Fanfare_GT_1", "sound_at must be <seconds left> <sound>"),
    ("sound_at = 5 se_nothing", "se_nothing"),
    ("sound_at = 20 se_Fanfare_GT_1", "the mode runs 20 s, so it would never play"),
    ("sound_at = 5 missing.ogg", "there is no missing.ogg in the mode folder"),
    ("start_needs = Nobody", "start_needs Nobody: no other mode in the folder has that name"),
    ("penalty = switch_target_tv 1000", "cannot work on JJP: the game's engine has no call that takes points away"),
    ("cooldown = a while", "cooldown must be a whole number"),
])
def test_each_bad_value_is_named(mm, tmp_path, line, says):
    _, problems = _check(mm, tmp_path, a__mode="start = switch_target_bank_1\n%s\n" % line)
    assert says in "\n".join(problems), problems


def test_start_also_wants_a_start_line_and_repeats_have_a_limit(mm, tmp_path):
    many = "".join("sound_at = %d se_Fanfare_GT_1\n" % s for s in range(1, 10))
    _, problems = _check(mm, tmp_path, a__mode="start_on = ball_start\nstart_also = switch_target_tv\n" + many)
    text = "\n".join(problems)
    assert "start_also adds to start, and there is no start line" in text
    assert "more than 8 sound_at lines" in text


def test_runtime_reads_the_rules_with_the_checkers_limits(mm):
    src = open(os.path.join(RIG, "jjpmodes.c"), encoding="utf-8").read()
    limits = {k: int(re.search(r"#define MAX_%s (\d+)" % k, src).group(1)) for k in ("SP", "ALSO", "AT")}
    assert mm.REPEATABLE == {"shot_points": limits["SP"], "start_also": limits["ALSO"], "sound_at": limits["AT"]}
    for word in ("solid", "blink", "pulse", "chase"):
        assert '!strcmp(v, "%s")' % word in src
    # combo_seconds 0 = no time limit; a cooldown is timed from the end the runtime saw
    assert "m->combo_ms > 0 && t - m->combo_t > m->combo_ms" in src
    assert "m->ended_at = now_ms() | 1" in src
