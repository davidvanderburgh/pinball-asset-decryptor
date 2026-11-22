"""PAD-1508: Spike 2's mode rules carried over to the JJP/Spooky .mode key set - the JJP
check takes them and names every bad value, and the runtime reads the same keys and limits
(the runtime itself is proven on Wonka 03.03 in the emulator)."""
import importlib.util
import os
import re
import struct
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


# ============================================================================ the pinHeck runtime
# The compiled MIPS runtime (prebuilt/padheck_JET_V004.bin) against the stand-in Jetsons of
# test_spooky_modes_pinheck.py (Unicorn): every rule through the game's own score and lamps.
@pytest.fixture(scope="module")
def heck():
    pytest.importorskip("unicorn")
    spec = importlib.util.spec_from_file_location(
        "heck_t1508", os.path.join(HERE, "tests", "test_spooky_modes_pinheck.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ph = mod._load("t1508_pinheck", os.path.join(mod.PH_DIR, "pinheck.py"))
    mk = mod._load("t1508_mkspk", os.path.join(mod.MODES, "mkspkmodes.py"))
    return mod, ph, mk.load_port("jetsons-V004")


A = dict(file="1_a.mode", name="A", title="A", start="switch_20", start_also="switch_21 2", start_max="2",
         cooldown="8", shots="switch_10", shot_points="switch_11 3000", points="1000", points_ladder="rising",
         end_shots="switch_12", seconds="30", sound_at="25 EB0", sound_shot="C01", sound_shot_every="2",
         lamps="lamp_10 lamp_11 lamp_12", lamp_color="ffffff", lamp_pattern="chase", lamp_blink="2")
B = dict(file="2_b.mode", name="B", title="B", start="switch_40", start_needs="A game", seconds="6",
         lamps="lamp_20", lamp_color="ffffff", lamp_pattern="pulse", lamp_blink="1")
C = dict(file="3_c.mode", name="C", title="C", start_combo="switch_1 switch_2", combo_seconds="0", seconds="4")


def test_pinheck_runs_every_rule_on_the_compiled_runtime(heck):
    mod, ph, port = heck
    g = mod._game(ph, port, [dict(A), dict(B), dict(C)])
    t = ph.H.HOOKS["JET_V004"]
    lamp = lambda n: g.get8(t["lamp_ram"] + n)
    mod._ball(g)
    g.switch(40)                                           # B needs A this game: not counted
    g.switch(20)                                           # A's start shot: waits for start_also
    g.switch(21)
    assert "waiting for start_also" in g.log and "RULES" not in g.log
    s0 = g.score
    g.switch(21)
    assert "1_a: STARTED" in g.log
    g.switch(10); g.switch(10); g.switch(11)               # 1000, 2 x 1000, 3 x 3000
    assert g.score - s0 == 1000 + 2000 + 9000
    assert g.calls(1) == 1                                 # the shot sound on the 2nd shot only
    lit = set()
    for _ in range(24):                                    # the chase: one lamp at a time, 2 steps a second
        g.tick(250)
        lit.add((lamp(10) > 0, lamp(11) > 0, lamp(12) > 0))
    assert lit == {(True, False, False), (False, True, False), (False, False, True)}
    assert "seconds left 25" in g.log and "sound_at EB0" in g.log
    g.switch(12)                                           # the end shot
    assert "ended (end shot)" in g.log
    g.switch(20)
    assert "not counted: cooling down" in g.log
    g.switch(40)                                           # A ran: B starts, its lamp pulsing
    assert "2_b: STARTED" in g.log
    levels = set()
    for _ in range(20):
        g.tick(50)
        levels.add(lamp(20))
    assert len(levels) >= 4 and 0 in levels and max(levels) >= 7     # rising and falling to 8 of 8
    g.tick(6000)                                           # B times out
    g.switch(1)
    g.tick(7000)                                           # 7 s between: no time limit on C's combo
    g.switch(2)
    assert "3_c: STARTED" in g.log
    g.tick(5000)
    for _ in range(2):                                     # A again (cooldown long past), then start_max
        g.switch(20); g.switch(21); g.switch(21); g.switch(12)
    assert g.log.count("1_a: STARTED") == 2 and "started its start_max times this game" in g.log


def test_pinheck_packs_the_rules_after_the_parity_bytes(heck):
    _mod, ph, port = heck
    modes = [dict(A), dict(B), dict(C)]
    data = ph.pack_data(modes, port)
    a = ph.pack_mode(modes[0], port)
    assert len(a) == 352 and a[128 + (12 >> 3)] == 1 << (12 & 7)          # end_shots 12
    rules, every, smax, cool, pat, needs, sp_n, also_n = struct.unpack_from("<8B", a, 136)
    assert (rules, every, smax, cool, pat, needs, sp_n, also_n) == (1, 2, 2, 8, 4, 0, 1, 1)
    assert struct.unpack_from("<I", a, 148 + 8)[0] == 3000 and a[148 + (11 >> 3)] == 1 << (11 & 7)
    assert a[244 + 8] == 2 and struct.unpack_from("<H", a, 280)[0] == 25 and a[282:286] == b"EB0\0"
    assert modes[1]["_needs"] == 1 and data[:4] == b"PHM3"


# ============================================================================ inside / in_place_of (run 2)
class _Queue(list):
    """SkeletonGame's mode queue as far as in_place_of sees it: add() starts a game mode."""
    def add(self, mode):
        self.append(mode)


class AdventureRoy(object):
    pass


class AdventurePurge(object):
    pass


def test_proc_in_place_of_starts_ours_and_the_game_mode_never_runs(proc):
    import types
    r = proc("name = Roy\nin_place_of = AdventureRoy\nseconds = 10\nshots = slingRight\n")
    roy, = r.pad_modes
    assert "start_also" not in roy or True
    # the runtime was made over a plain list: give it the game's queue and hook it as join() does
    r.game.modes = _Queue()
    r.pad_hook_queue()
    r.game.modes.add(AdventurePurge())                    # another game mode: the game's as always
    assert [type(x).__name__ for x in r.game.modes] == ["AdventurePurge"] and not roy["running"]
    r.game.modes.add(AdventureRoy())
    assert roy["running"] and "AdventureRoy" not in [type(x).__name__ for x in r.game.modes]
    assert "the game's AdventureRoy held off - ours starts in its place" in r.log.read_text()
    r.pad_stop(roy, "done")
    r.ball_live = False                                   # between balls: the game's own runs
    r.game.modes.add(AdventureRoy())
    assert "AdventureRoy" in [type(x).__name__ for x in r.game.modes] and not roy["running"]


def test_proc_inside_starts_only_within_its_parent_and_ends_with_it(proc):
    r = proc("name = Outer\nstart = leftInlane\nseconds = 30\nend_shots = spinner\n",
             "name = Inner\nstart = rightInlane\ninside = Outer\nseconds = 30\n")
    outer, inner = r.pad_modes
    _hit(r, proc.Sw, "rightInlane")
    assert not inner["running"] and "it runs inside Outer, which is not running" in r.log.read_text()
    _hit(r, proc.Sw, "leftInlane", "rightInlane")
    assert outer["running"] and inner["running"]
    _hit(r, proc.Sw, "spinner")
    assert not outer["running"] and not inner["running"]
    assert "Inner: ended (the mode it runs inside ended)" in r.log.read_text()


@pytest.mark.parametrize("files,says", [
    ({"a__mode": "name = A\nstart = switch_target_tv\ninside = Nobody\n"}, "inside Nobody: no other mode"),
    ({"a__mode": "name = A\nstart = switch_target_tv\ninside = B\n",
      "b__mode": "name = B\nstart = switch_target_tv\ninside = A\n"}, "run inside each other in a ring"),
])
def test_spooky_check_names_a_bad_inside(tmp_path, files, says):
    spec = importlib.util.spec_from_file_location("mkspk_t1508b", os.path.join(HERE, "tools", "spooky_emu", "modes", "mkspkmodes.py"))
    mk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mk)
    for name, text in files.items():
        (tmp_path / name.replace("__", ".")).write_text(text.replace("switch_target_tv", "right_inlane"))
    (tmp_path / "title.cfg").write_text("game = scooby_doo\n")
    _, problems = mk.check_modes(str(tmp_path), mk.load_port("scooby_doo-2025.12.01.09"))
    assert says in "\n".join(problems), problems


def test_spooky_check_takes_in_place_of_only_where_the_runtime_sees_starts(tmp_path):
    spec = importlib.util.spec_from_file_location("mkspk_t1508c", os.path.join(HERE, "tools", "spooky_emu", "modes", "mkspkmodes.py"))
    mk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mk)
    (tmp_path / "title.cfg").write_text("game = x\n")
    (tmp_path / "a.mode").write_text("name = A\nin_place_of = AdventureRoy\n")
    _, problems = mk.check_modes(str(tmp_path), mk.load_port("rick_and_morty-2022.09.02"))
    assert problems == [], problems
    (tmp_path / "a.mode").write_text("name = A\nin_place_of = AdventureNobody\n")
    _, problems = mk.check_modes(str(tmp_path), mk.load_port("rick_and_morty-2022.09.02"))
    assert "not a game mode or Mode class of" in "\n".join(problems)
    (tmp_path / "a.mode").write_text("name = A\nstart = right_inlane\nin_place_of = SKILLSHOT\n")
    _, problems = mk.check_modes(str(tmp_path), mk.load_port("scooby_doo-2025.12.01.09"))
    assert "in_place_of is not on Scooby-Doo" in "\n".join(problems)


def test_jjp_check_takes_in_place_of_and_refuses_inside(mm, tmp_path):
    _, problems = _check(mm, tmp_path, a__mode="name = A\nin_place_of = cl_mode CandyLaneMode\n",
                         b__mode="name = B\nstart = switch_target_tv\ninside = A\n")
    text = "\n".join(problems)
    assert "a.mode" not in text and "inside cannot work on JJP" in text
    _, problems = _check(mm, tmp_path, a__mode="name = A\nin_place_of = any\n")
    assert "must name the game's modes" in "\n".join(problems)


def test_pinheck_inside_on_the_compiled_runtime(heck):
    mod, ph, port = heck
    g = mod._game(ph, port, [dict(file="1_o.mode", name="Outer", title="O", start="switch_20", seconds="30",
                                  end_shots="switch_12"),
                             dict(file="2_i.mode", name="Inner", title="I", start="switch_21", inside="Outer",
                                  seconds="30")])
    mod._ball(g)
    g.switch(21)
    assert "the mode it runs inside is not running" in g.log
    g.switch(20); g.switch(21)
    assert "1_o: STARTED" in g.log and "2_i: STARTED" in g.log
    g.switch(12)
    assert "2_i: ended (the mode it runs inside ended)" in g.log
