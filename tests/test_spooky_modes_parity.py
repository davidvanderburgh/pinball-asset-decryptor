"""PAD-1424: Spooky modes to JJP parity - the start rules (start_on, start_after, start_score,
start_combo, start_once, start_count_reset) in the check and in the P-ROC runtime's mode logic
(a stand-in SkeletonGame); the Unity and Godot runtimes run the same rules (proven in the rig)."""
import importlib.util
import os
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODES = os.path.join(ROOT, "tools", "spooky_emu", "modes")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mk():
    return _load("pad_mkspkmodes_t1424", os.path.join(MODES, "mkspkmodes.py"))


def _folder(tmp_path, game, **mode):
    d = tmp_path / "modes"
    d.mkdir(exist_ok=True)
    (d / "title.cfg").write_text("game = %s\n" % game)
    (d / "1_a.mode").write_text("".join("%s = %s\n" % kv for kv in mode.items()))
    return str(d)


# ============================================================================ the check
@pytest.mark.parametrize("label,sw", [("rick_and_morty-2022.09.02", ("leftInlane", "rightInlane")),
                                      ("scooby_doo-2025.12.01.09", ("right_inlane", "left_inlane")),
                                      ("legends_of_tera-2025.10.08", ("inlane_left", "inlane_right"))])
def test_start_rules_check(mk, tmp_path, label, sw):
    port = mk.load_port(label)
    game = label.split("-")[0]
    ok = _folder(tmp_path, game, name="A", start_on="ball_start last_ball", start_after="any",
                 start_score="5000000", start_combo="%s %s" % sw, combo_seconds="4",
                 start_once="ball", start_count_reset="ball", shots=sw[0], points="1000")
    _m, problems = mk.check_modes(ok, port)
    assert problems == []
    # a mode with only a start rule needs no start switches
    _m, problems = mk.check_modes(_folder(tmp_path, game, start_score="1000000"), port)
    assert problems == []


def test_start_rule_problems(mk, tmp_path):
    port = mk.load_port("rick_and_morty-2022.09.02")
    _m, p = mk.check_modes(_folder(tmp_path, "rick_and_morty", shots="slingRight"), port)
    assert any("no start rule" in x for x in p)
    _m, p = mk.check_modes(_folder(tmp_path, "rick_and_morty", start_on="ball_starts"), port)
    assert any("not a start event" in x for x in p)
    _m, p = mk.check_modes(_folder(tmp_path, "rick_and_morty", start_combo="leftInlane"), port)
    assert any("two switches or more" in x for x in p)
    _m, p = mk.check_modes(_folder(tmp_path, "rick_and_morty", start_score="0"), port)
    assert any("start_score must be above 0" in x for x in p)
    _m, p = mk.check_modes(_folder(tmp_path, "rick_and_morty", start="leftInlane", start_once="always"), port)
    assert any("start_once must be one of" in x for x in p)
    _m, p = mk.check_modes(_folder(tmp_path, "rick_and_morty", start_after="NoSuchMode"), port)
    assert any("NoSuchMode" in x for x in p)


def test_start_events_a_title_cannot_see(mk, tmp_path):
    port = dict(mk.load_port("rick_and_morty-2022.09.02"), start_events=["ball_start", "first_ball"])
    _m, p = mk.check_modes(_folder(tmp_path, "rick_and_morty", start_on="ball_saved"), port)
    assert any("cannot see that event" in x and "ball_start, first_ball" in x for x in p)


# ============================================================================ the P-ROC runtime
class _Sw:
    def __init__(self, name, number=0):
        self.name, self.number = name, number


class _Player:
    def __init__(self):
        self.score, self.extra_balls = 0, 0


class _Mode(object):
    Game = 2

    def __init__(self, game, priority, mode_type=3):
        self.game, self.priority, self.mode_type = game, priority, mode_type
        self.handlers = []

    def add_switch_handler(self, name, event_type, delay, handler):
        self.handlers.append((name, event_type, handler))

    def mode_tick(self):
        return None


class GromflomiteBattle(object):
    pass


class _Game:
    def __init__(self):
        names = ["leftInlane", "rightInlane", "slingRight", "spinner", "shooterLane", "troughEject"]
        self.switches = [_Sw(n, i) for i, n in enumerate(names)]
        self.players = [_Player(), _Player()]
        self.current_player_index = 0
        self.game_tilted = False
        self.modes = []
        self.ball, self.balls_per_game = 1, 3
        self.trough = types.SimpleNamespace(num_balls_in_play=1)
        self.sound = types.SimpleNamespace(sounds={}, play_voice=lambda k: None, play=lambda k: None)

    def current_player(self):
        return self.players[self.current_player_index]

    def score(self, points):
        self.current_player().score += points
        return points


@pytest.fixture
def pm(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_MODES_LOG", str(tmp_path / "padmodes.log"))
    return _load("pad_padmodes_proc_t1424", os.path.join(MODES, "proc", "padmodes_proc.py"))


def _runtime(pm, tmp_path, monkeypatch, modes):
    d = tmp_path / "m"
    d.mkdir()
    (d / "title.cfg").write_text("game = rick_and_morty\n")
    for i, body in enumerate(modes):
        (d / ("%d_m.mode" % i)).write_text("seconds = 0\nshots = slingRight\npoints = 1000\n" + body)
    game = _Game()
    loaded, title = pm.load_modes(game, str(d))
    monkeypatch.setattr(pm, "panel_layer", lambda g, m, secs: None)
    clock = [1000.0]
    monkeypatch.setattr(pm.time, "time", lambda: clock[0])
    r = pm._runtime_class(_Mode)(game, loaded, title)
    r.clock = clock
    r.log = tmp_path / "padmodes.log"
    r.evt_game_starting()
    return r


def _tick(r, secs=0.2):
    r.clock[0] += secs
    r.mode_tick()


def test_proc_start_on_ball_events(pm, tmp_path, monkeypatch):
    r = _runtime(pm, tmp_path, monkeypatch, ["start_on = first_ball\n", "start_on = last_ball\n",
                                             "start_on = ball_start\nstart_count = 2\nstart_count_reset = ball\n",
                                             "start_on = ball_saved\n"])
    first, last, every, saved = r.pad_modes
    r.evt_ball_starting()
    assert first["running"] and not last["running"] and every["hits"] == 1 and not every["running"]
    r.evt_ball_ending((False, False))
    r.game.ball = 3
    r.evt_ball_starting()
    assert last["running"] and every["hits"] == 1          # reset each ball: never two
    r.evt_ball_ending((False, False))
    r.game.current_player().extra_balls = 1                # an extra ball to come: not the last
    r.evt_ball_starting()
    assert not last["running"]
    r.evt_ball_saved()
    assert saved["running"]


def test_proc_valid_playfield_and_combo(pm, tmp_path, monkeypatch):
    r = _runtime(pm, tmp_path, monkeypatch, ["start_on = valid_playfield\n",
                                             "start_combo = leftInlane rightInlane spinner\ncombo_seconds = 3\n"])
    vp, combo = r.pad_modes
    assert {h[0] for h in r.handlers} >= {"shooterLane", "troughEject", "leftInlane"}
    r.evt_ball_starting()
    r.pad_switch(_Sw("troughEject"))
    r.pad_switch(_Sw("shooterLane"))
    assert not vp["running"]
    r.pad_switch(_Sw("leftInlane"))
    assert vp["running"]
    r.clock[0] += 1
    r.pad_switch(_Sw("slingRight"))                         # another switch between: still a combo
    r.pad_switch(_Sw("rightInlane"))
    r.clock[0] += 4                                         # too slow
    r.pad_switch(_Sw("spinner"))
    assert not combo["running"]
    for n in ("leftInlane", "rightInlane", "spinner"):
        r.clock[0] += 2
        r.pad_switch(_Sw(n))
    assert combo["running"] and "start_combo made" in r.log.read_text()


def test_proc_score_extra_ball_multiball_end(pm, tmp_path, monkeypatch):
    r = _runtime(pm, tmp_path, monkeypatch, ["start_score = 50000\nstart_once = game\n", "start_on = extra_ball\n",
                                             "start_on = multiball_end\n"])
    score, extra, mbend = r.pad_modes
    r.evt_ball_starting()
    _tick(r)
    r.game.current_player().score = 60000
    _tick(r)
    assert score["running"]
    r.evt_ball_ending((False, False))
    r.evt_ball_starting()
    _tick(r)
    assert not score["running"]                             # once per player per game
    r.game.current_player().extra_balls = 1
    _tick(r)
    assert extra["running"]
    r.game.trough.num_balls_in_play = 2
    for _ in range(3):                                      # two balls for half a second: a multiball
        _tick(r, 0.3)
    r.game.trough.num_balls_in_play = 1
    _tick(r)
    assert mbend["running"]
    # the second player reaches it in the same game: their own once
    r.evt_ball_ending((False, False))
    r.game.current_player_index = 1
    r.evt_ball_starting()
    r.game.current_player().score = 70000
    _tick(r)
    _tick(r)
    assert not score["running"]                             # start_once = game: it ran this game


def test_proc_start_after_and_once(pm, tmp_path, monkeypatch):
    r = _runtime(pm, tmp_path, monkeypatch, ["start_after = GromflomiteBattle\nstart_once = ball\nseconds = 1\n"])
    m = r.pad_modes[0]
    r.evt_ball_starting()
    gm = GromflomiteBattle()
    r.game.modes = [gm, r]
    _tick(r)
    r.game.modes = [r]
    _tick(r)
    assert m["running"] and "start_after gromflomitebattle ended" in r.log.read_text()
    _tick(r, 1.5)
    assert not m["running"]
    r.game.modes = [gm, r]
    _tick(r)
    r.game.modes = [r]
    _tick(r)
    assert not m["running"]                                 # once a ball
    r.evt_ball_ending((False, False))
    r.evt_ball_starting()
    r.game.modes = [gm, r]
    _tick(r)
    gm.modeStarted = 0                                      # Alice Cooper: queued but not started
    _tick(r)
    assert m["running"]


def test_proc_nothing_starts_outside_a_ball(pm, tmp_path, monkeypatch):
    r = _runtime(pm, tmp_path, monkeypatch, ["start_on = ball_saved\n"])
    r.evt_ball_saved()                                      # before the first ball
    assert not r.pad_modes[0]["running"]


# ============================================================================ lamps, coils, balls (P-ROC)
class _Item(object):
    def __init__(self, name, log, pulse_ms=30):
        self.name, self.log, self.default_pulse_time = name, log, pulse_ms

    def pulse(self, ms=None):
        self.log.append(("pulse", self.name, ms))

    def patter(self, on_time=10, off_time=10, original_on_time=0, now=True):
        self.log.append(("patter", self.name, on_time, off_time))

    def disable(self):
        self.log.append(("disable", self.name))


class _Items(list):
    def __getattr__(self, n):
        for it in self:
            if it.name == n:
                return it
        raise AttributeError(n)


class _LEDs(object):
    def __init__(self, log):
        self.log = log

    def enable(self, name, priority=0, color=None):
        self.log.append(("led", name, priority, color))

    def run_script(self, name, script, priority=0, repeat=True, blend=False):
        self.log.append(("script", name, priority, [s["color"] for s in script], script[0]["time"]))

    def stop_script(self, name, priority=0):
        self.log.append(("stop_script", name, priority))

    def disable(self, name, priority=0):
        self.log.append(("led_off", name, priority))


def _lcb(pm, tmp_path, monkeypatch, body, title=""):
    r = _runtime(pm, tmp_path, monkeypatch, [body])
    g, log = r.game, []
    g.hw = log
    g.leds = _Items([_Item("rightRampTriangle", log), _Item("shootAgainRGBLeft", log)])
    g.LEDs = _LEDs(log)
    g.coils = _Items([_Item("knocker", log, 7), _Item("shipPost", log), _Item("diverter", log)])
    g.trough.add_balls = lambda n: (log.append(("add_balls", n)), setattr(g.trough, "num_balls_in_play",
                                                                         g.trough.num_balls_in_play + n))[0]
    g.enable_ball_saver = lambda num_balls_to_save=1, time=None, now=True, allow_multiple_saves=False: \
        log.append(("ball_save", num_balls_to_save, time))
    g.ball_save = types.SimpleNamespace(is_active=lambda: True, time_remaining=lambda: 3,
                                        disable=lambda: log.append(("ball_save_off",)))
    for m in r.pad_modes:
        m["holds_ok"] = "coil_holds = on" in title
    r.evt_ball_starting()
    return r, log


def test_proc_lamps_and_coils(pm, tmp_path, monkeypatch):
    r, log = _lcb(pm, tmp_path, monkeypatch,
                  "start = leftInlane\nseconds = 5\nlamps = rightRampTriangle shootAgainRGBLeft\nlamp_color = ff0000\n"
                  "lamp_blink = 2\ncoil_start = knocker 50\ncoil_shot = diverter\ncoil_complete = knocker 3\n"
                  "coil_hold = shipPost 1500 4\ncoil_hold_on = start\ncomplete = 2\n", title="coil_holds = on")
    r.pad_switch(_Sw("leftInlane"))
    assert ("script", "rightRampTriangle", pm.PRIORITY, ["ff0000", "000000"], 250) in log
    assert ("pulse", "knocker", 7) in log                   # 50 asked: only ever shorter than its own 7
    assert ("patter", "shipPost", 4, 28) in log
    _tick(r, 1.0)
    _tick(r, 0.6)
    assert ("disable", "shipPost") in log                   # its 1.5 s are up
    r.pad_switch(_Sw("slingRight"))
    assert ("pulse", "diverter", None) in log
    r.pad_switch(_Sw("slingRight"))
    assert ("pulse", "knocker", 3) in log and not r.pad_modes[0]["running"]
    assert ("led_off", "rightRampTriangle", pm.PRIORITY) in log and ("led_off", "shootAgainRGBLeft", pm.PRIORITY) in log


def test_proc_hold_needs_coil_holds_on(pm, tmp_path, monkeypatch):
    r, log = _lcb(pm, tmp_path, monkeypatch, "start = leftInlane\ncoil_hold = shipPost 1500\ncoil_hold_on = start\n")
    r.pad_switch(_Sw("leftInlane"))
    assert not [x for x in log if x[0] == "patter"] and "coil_holds = on" in r.log.read_text()


def test_proc_multiball_add_ball_ball_save(pm, tmp_path, monkeypatch):
    r, log = _lcb(pm, tmp_path, monkeypatch, "start = leftInlane\nmultiball = 3 5\nmultiball_on = spinner\n"
                                             "add_ball = rightInlane 1\nseconds = 20\n")
    m = r.pad_modes[0]
    r.pad_switch(_Sw("leftInlane"))
    assert m["running"] and not [x for x in log if x[0] == "add_balls"]     # waits for its multiball_on
    r.pad_switch(_Sw("spinner"))
    assert ("add_balls", 2) in log and ("ball_save", 2, 5) in log
    r.pad_switch(_Sw("rightInlane"))
    r.pad_switch(_Sw("rightInlane"))                        # up to once a run
    assert log.count(("add_balls", 1)) == 1
    _tick(r, 30)                                            # the clock stopped when the balls came
    assert m["running"]
    r.game.trough.num_balls_in_play = 1
    _tick(r, 1)
    _tick(r, 2.5)
    assert not m["running"] and "ended (one ball left)" in r.log.read_text()


def test_proc_ball_save_ends_with_the_mode(pm, tmp_path, monkeypatch):
    r, log = _lcb(pm, tmp_path, monkeypatch, "start = leftInlane\nball_save = 8\nseconds = 2\n")
    r.pad_switch(_Sw("leftInlane"))
    assert ("ball_save", 1, 8) in log
    for _ in range(3):                                      # a tick counts at most 1 s
        _tick(r, 1.0)
    assert ("ball_save_off",) in log


# ============================================================================ a mode's own files (P-ROC)
def test_proc_sound_file_and_music(pm, tmp_path, monkeypatch):
    r = _runtime(pm, tmp_path, monkeypatch, ["start = leftInlane\nseconds = 2\nsound_start = yay.ogg\n"
                                             "sound_channel = speech\nmusic = song.ogg\n"])
    g, log = r.game, []
    g.sound = types.SimpleNamespace(
        sounds={}, music={},
        register_sound=lambda k, path, is_voice=False: (log.append(("reg", k, os.path.basename(path), is_voice)),
                                                         g.sound.sounds.__setitem__(k, {})),
        register_music=lambda k, path: (log.append(("regm", k, os.path.basename(path))), g.sound.music.__setitem__(k, 1)),
        play_voice=lambda k: log.append(("voice", k)), play=lambda k: log.append(("sfx", k)),
        play_music=lambda k, loops=0: log.append(("music", k, loops)), stop_music=lambda: log.append(("stop_music",)))
    g.base = types.SimpleNamespace(music_track="base-loop",
                                   start_track=lambda t, loops=0: log.append(("track", t, loops)))
    r.evt_ball_starting()
    r.pad_switch(_Sw("leftInlane"))
    assert ("reg", "pad_sound_yay.ogg", "yay.ogg", True) in log and ("voice", "pad_sound_yay.ogg") in log
    assert ("music", "pad_music_song.ogg", -1) in log
    for _ in range(3):
        _tick(r, 1.0)
    assert log[-2:] == [("stop_music",), ("track", "base-loop", -1)]
