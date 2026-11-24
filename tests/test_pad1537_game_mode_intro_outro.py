"""PAD-1537: an intro and an outro of your own for one of the game's own modes.
A tester: "For any built-in mode, allow users to independently assign an Intro (triggered when the mode starts) and/or an
Outro (triggered when the mode ends) ... play the accompanying sound ... ducking conflicting native audio".
- The runtime counts each of the game's modes starting (its START going ahead) and stopping (its STOP, any outcome; on a
  plain-C title only its completion): pm_game_mode_follow.
- A mode file's `starts_on with_game <id>` starts with the game's mode and ends with it: its start clip and sound are
  the intro, its end sound and clip the outro, the game's music turned down while either sound plays. It always stacks,
  as a layer.
- The form's Starts on > with the game's <mode> (its intro and outro).
"""
import os
import re

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP

SDK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "spike2_emu", "modes", "sdk")
PORTS = os.path.join(SDK, "ports")
GZ = "godzilla_le_1_16"
JET = 21                               # Godzilla's Jet Fighter Attack


def _src(name):
    with open(os.path.join(SDK, name), encoding="utf-8") as f:
        return f.read()


def _port(key):
    return MP.read_port(os.path.join(PORTS, key + ".port"))


def _intro(title=GZ, mode=JET):
    p = MP.profile(title)
    spec = MP.blank_spec(p, "JET INTRO")
    spec.starts_on, spec.with_mode = "with_game", mode
    spec.scoring_shots, spec.award, spec.seconds = [], 0, 0
    return p, spec


# ---- what the runtime can see, per build ---------------------------------------------------------------------------
def test_a_cpp_title_sees_every_mode_start_and_stop():
    follows = {i: (nm, e) for i, nm, e in MP._follows(_port("godzilla_le-1.16"))}
    assert follows[JET] == ("Jet Fighter Attack", "stop")
    assert all(e == "stop" for _nm, e in follows.values())


def test_a_plain_c_title_sees_an_end_only_when_completed():
    follows = MP._follows(_port("beatles-1.29"))
    assert follows
    ends = {e for _i, _nm, e in follows}
    assert "stop" not in ends
    done = {i for i, _nm in MP._done_modes(_port("beatles-1.29"))}
    assert all((e == "completed") == (i in done) for i, _nm, e in follows)


def test_every_proven_build_has_a_mode_to_follow():
    for key in MP.WITH_PROVEN:
        path = os.path.join(PORTS, key + ".port")
        assert os.path.isfile(path), key
        assert MP._follows(MP.read_port(path)), key


def test_an_unproven_build_says_why():
    why = dict(MP._with_cannot("not_a_build-0.00", "Nothing 0.00", _port("godzilla_le-1.16")))["with"]
    assert "not yet seen" in why
    assert "names none" in dict(MP._with_cannot("x", "X", {"site": {}, "data": {}, "value": {}, "text": {}}))["with"]


# ---- the mode file ---------------------------------------------------------------------------------------------------
def test_the_form_writes_starts_on_with_game_and_nothing_of_the_games_calls():
    p, spec = _intro()
    if not p.can("with"):
        pytest.skip(p.why_not("with"))
    assert MP.validate(spec) == []
    cfg = MP.runtime_cfg(spec, "jet_intro").splitlines()
    assert "starts_on      with_game %d" % JET in cfg
    assert "seconds        0" in cfg
    assert "game_modes     stack" in cfg and "layer          0" in cfg
    for gone in ("trigger ", "callout_end", "callout_count", "callout_at", "ends_on", "stack          no", "block "):
        assert not any(ln.startswith(gone) for ln in cfg), gone


def test_the_checks():
    p, spec = _intro()
    if not p.can("with"):
        pytest.skip(p.why_not("with"))
    spec.with_mode = 99
    assert "Pick the game's mode this one runs with." in MP.validate(spec)
    _p, spec = _intro()
    spec.seconds = -1
    assert "0 seconds" in " ".join(MP.validate(spec))
    _p, spec = _intro()                           # a mode of its own still needs its shots, a follower does not
    spec.starts_on = "shot"
    assert "Pick at least one shot that scores while it runs." in MP.validate(spec)


def test_a_follower_where_no_stop_is_seen_needs_a_clock():
    p = MP.profile(GZ)
    if not p.can("with"):
        pytest.skip(p.why_not("with"))
    spec = MP.blank_spec(p, "X")
    spec.starts_on, spec.with_mode, spec.scoring_shots, spec.award, spec.seconds = "with_game", JET, [], 0, 0
    fake = MP.replace(p, follows=tuple((i, nm, "clock") for i, nm, _e in p.follows))
    assert MP.with_ends(spec, fake) == "clock"
    assert MP.with_ends(spec, p) == "stop"


def test_a_title_that_cannot_starts_on_its_shot():
    p = MP.profile(GZ)
    spec = MP.blank_spec(p, "X")
    spec.starts_on, spec.with_mode = "with_game", JET
    cannot = MP.replace(p, cannot=tuple(p.cannot) + (("with", "no"),), follows=())
    assert "not on" in " ".join(MP._validate_starts_ends(spec, cannot))


def test_le_and_pro_map_the_mode_by_name():
    p, spec = _intro()
    pro = MP.profile("godzilla_pro_1_16")
    if not (p.can("with") and pro.can("with")):
        pytest.skip("not proven on both")
    out, _dropped = MP.retarget(spec, pro)
    names = {i: nm for i, nm, _e in pro.follows}
    assert names.get(out.with_mode) == "Jet Fighter Attack"


def test_a_follower_takes_no_start_shot():
    p, spec = _intro()
    assert MP.starts_on_with(spec)
    spec.start_shot = "Left ramp"
    assert not MP.starts_on_with(MP.blank_spec(p, "Y"))


# ---- the runtime and mode_file.c -------------------------------------------------------------------------------------
def test_the_runtime_counts_starts_and_stops():
    rt = _src("pad_mode_runtime.c")
    for want in ("static void gm_seen(unsigned id, int stop, const char *how)", "gm_seen(id, 0, \"its start\")",
                 "gm_seen(id, 0, \"its own start\")", "gm_seen(id, 1, r[1] ? \"completed\" : \"not completed\")",
                 "if (id < BLOCK_IDS && !block_obj[id]) gm_seen(id, 1, how);",
                 "int pm_game_mode_follow(unsigned id, unsigned *starts, unsigned *stops)",
                 "int pm_game_mode_stop(unsigned id, int won)", "gm_check_tick();",
                 "its START ran but did not start it - not a start", "int pm_clip_swap_next(const char *ours, unsigned ms)",
                 "if (!ci_film_swap(r))"):
        assert want in rt, want
    # a C++ title's START counts only once the mode runs for the player: entered, it is checked on the ticks after
    seen = rt[rt.index("static void gm_seen(unsigned id, int stop, const char *how)"):]
    seen = seen[:seen.index("gm_stops[id]++")]
    assert "gm_chk[id].starts = place_starts(block_obj[id], p);" in seen and "return;" in seen
    # every outcome of the STOP is seen now, the completions still only for a completed one
    stop = rt[rt.index("static void done_stop_seen"):]
    stop = stop[:stop.index("\n}\n") if "\n}\n" in stop else stop.index("\r\n}\r\n")]
    assert stop.index("gm_seen(id, 1") < stop.index("if (!r[1]) return;") < stop.index("done_mark(id, p, how);")
    h = _src("pad_mode.h")
    assert "int pm_game_mode_follow(unsigned id, unsigned *starts, unsigned *stops);" in h
    assert "int pm_game_mode_stop(unsigned id, int won);" in h
    desk = _src(os.path.join("examples", "desk_harness.c"))
    for call in ("pm_game_mode_follow", "pm_game_mode_stop"):
        assert re.search(r"^int %s\(" % call, desk, re.M), call


def test_mode_file_c_follows_the_games_mode():
    mf = _src("mode_file.c")
    for want in ('key_is(how, "with_game")', "cfg.start_with = 1;", "cfg.game_modes = GM_STACK;",
                 "if (!cfg.layer_1) cfg.layer_1 = 1;", "pm_game_mode_follow(cfg.with_id, &st, &sp);",
                 "with_tick();", "mode_end(why);", "with_duck_down(own_sounds[M->index].start",
                 "with_duck_down(own_sounds[M->index].end", "pm_sound_duck(with_duck.req[k], 0, MUSIC_DUCK_UP_MS);",
                 '"game_mode.start"', '"game_mode.stop"'):
        assert want in mf, want
    # its stop is looked at before its start: a mode the game stops and starts again in one tick starts again
    tick = mf[mf.index("static void with_tick(void)"):]
    assert tick.index("if (sp != M->with_stops)") < tick.index("if (st != M->with_starts)")


def test_the_form_offers_it():
    js = open(os.path.join(os.path.dirname(SDK), "..", "..", "..", "pinball_decryptor", "webui", "static", "js", "tabs",
                           "modes.js"), encoding="utf-8").read()
    assert 'value="with_game" label="with the game\'s"' in js
    assert "(its intro and outro)" in js
    from pinball_decryptor.webui.tabs import modes as tab
    src = open(tab.__file__, encoding="utf-8").read()
    assert '"with_game" if MP.starts_on_with(spec)' in src
    assert 'spec.with_mode = by_name.get(name, -1) if spec.starts_on == "with_game" else -1' in src


def test_the_game_mode_pages_shortcut_makes_a_valid_mode():
    p = MP.profile(GZ)
    if not p.can("with"):
        pytest.skip(p.why_not("with"))
    spec = MP.blank_spec(p, "JET FIGHTER ATTACK INTRO")   # what Intro and outro > Add an intro and outro... sets
    spec.starts_on, spec.with_mode = "with_game", JET
    spec.scoring_shots, spec.award, spec.seconds = [], 0, 0
    spec.screen = spec.lights = spec.countdown = False
    spec.game_modes, spec.clip, spec.clip_when = "stack", "none", "start"
    assert MP.validate(spec) == []
    cfg = MP.runtime_cfg(spec, "jet_fighter_attack_intro").splitlines()
    assert "starts_on      with_game 21" in cfg and "shots          0x00000000" in cfg
    assert not any(ln.startswith(("screen_", "light_", "callout_")) for ln in cfg)
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pinball_decryptor", "webui",
                            "tabs", "modes.py"), encoding="utf-8").read()
    for want in ("def intro_outro(self):", 'spec.starts_on, spec.with_mode = "with_game", f["id"]',
                 '"follow": self._follow_for(build.mode_name(mid), mid)'):
        assert want in src, want
