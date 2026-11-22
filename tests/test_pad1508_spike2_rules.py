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


# ============================================================================ the P-ROC runtime
def _parity():
    spec = importlib.util.spec_from_file_location(
        "parity_t1508", os.path.join(HERE, "tests", "test_spooky_modes_parity.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def proc(tmp_path, monkeypatch):
    par = _parity()
    monkeypatch.setenv("PAD_MODES_LOG", str(tmp_path / "padmodes.log"))
    pm = par._load("pad_padmodes_proc_t1508", os.path.join(par.MODES, "proc", "padmodes_proc.py"))

    def make(*modes):
        r = par._runtime(pm, tmp_path, monkeypatch, list(modes))
        r.evt_ball_starting()
        return r
    make.Sw = par._Sw
    return make


def _hit(r, Sw, *names):
    for n in names:
        r.pad_switch(Sw(n))


def test_proc_shot_points_ladder_end_shot_and_shot_sound_every(proc):
    r = proc("name = A\nstart = leftInlane\nshots = slingRight\npoints = 1000\nseconds = 30\n"
             "shot_points = spinner 3,000\npoints_ladder = rising\nend_shots = rightInlane\n"
             "sound_shot = se_hit\nsound_shot_every = 2\n")
    played = []
    r.game.sound.sounds["se_hit"] = {}
    r.game.sound.play = played.append
    a, = r.pad_modes
    _hit(r, proc.Sw, "leftInlane")
    assert a["running"]
    p = r.game.current_player()
    _hit(r, proc.Sw, "slingRight", "slingRight", "spinner")    # 1000, 2 x 1000, 3 x 3000
    assert p.score == 1000 + 2000 + 9000 and len(played) == 1  # the shot sound on the 2nd only
    _hit(r, proc.Sw, "rightInlane")
    assert not a["running"] and "ended (end shot rightInlane)" in r.log.read_text()


def test_proc_start_also_max_cooldown_and_needs(proc):
    r = proc("name = A\nstart = leftInlane\nstart_also = spinner 2\nstart_max = 2\ncooldown = 8\n"
             "seconds = 30\nend_shots = rightInlane\n",
             "name = B\nstart = slingRight\nstart_needs = A game\nseconds = 5\n")
    a, b = r.pad_modes
    _hit(r, proc.Sw, "slingRight")
    assert not b["running"] and "A has not run this game (start_needs)" in r.log.read_text()
    _hit(r, proc.Sw, "leftInlane", "spinner")
    assert not a["running"] and "waiting for 1 start_also" in r.log.read_text()
    _hit(r, proc.Sw, "spinner")
    assert a["running"]
    _hit(r, proc.Sw, "rightInlane")
    _hit(r, proc.Sw, "leftInlane")
    assert not a["running"] and "cooling down, 8 s left" in r.log.read_text()
    _hit(r, proc.Sw, "slingRight")
    assert b["running"]
    r.clock[0] += 9
    _hit(r, proc.Sw, "leftInlane", "spinner", "spinner")
    assert a["running"] and a["runs_game"] == 2
    _hit(r, proc.Sw, "rightInlane")
    r.clock[0] += 9
    _hit(r, proc.Sw, "leftInlane", "spinner", "spinner")
    assert not a["running"] and "started 2 time(s) this game, its start_max" in r.log.read_text()


def test_proc_sound_at_combo_without_a_time_limit_and_penalty(proc):
    r = proc("name = A\nstart = leftInlane\nseconds = 10\nsound_at = 5 se_hurry\nsound_at = 2 se_last\n"
             "penalty = spinner 5000\n",
             "name = C\nstart_combo = rightInlane slingRight\ncombo_seconds = 0\nseconds = 3\n")
    played = []
    r.game.sound.sounds.update(se_hurry={}, se_last={})
    r.game.sound.play = played.append
    a, c = r.pad_modes
    p = r.game.current_player()
    p.score = 3000
    _hit(r, proc.Sw, "leftInlane")
    _hit(r, proc.Sw, "spinner")
    assert p.score == 0 and "penalty shot spinner: -3000 (asked 5000)" in r.log.read_text()
    for _ in range(30):
        _tick(r)
    assert played == ["se_hurry"]
    for _ in range(25):
        _tick(r)
    assert played == ["se_hurry", "se_last"] and not a["running"]
    _hit(r, proc.Sw, "rightInlane")
    r.clock[0] += 60                                           # a minute between: still the combo
    _hit(r, proc.Sw, "slingRight")
    assert c["running"]


def _tick(r, secs=0.2):
    r.clock[0] += secs
    r.mode_tick()


def test_proc_repeated_lines_add_to_title_cfg(proc, tmp_path):
    r = proc("name = A\nstart = leftInlane\nshot_points = spinner 10\nshot_points = rightInlane 20\n")
    a, = r.pad_modes
    assert [pts for _sw, pts in a["shot_points"]] == [10, 20]
