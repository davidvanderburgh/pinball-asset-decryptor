"""Headless tests for the JJP mode SDK (PAD-1337): the mode-file checker and the
rungame.sh hook in mkjjpmodes.py, the runtime's keys staying in step with the
checker's, and jjpport.py's Mode vtable resolution (folded virtuals)."""
import importlib.util
import json
import os
import re
import struct
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(HERE, "tools", "jjp_emu")


def _load(name):
    path = os.path.join(RIG, name + ".py")
    if not os.path.exists(path):
        pytest.skip(f"tools/jjp_emu/{name}.py not present")
    sys.path.insert(0, RIG)
    try:
        spec = importlib.util.spec_from_file_location(name + "_undertest", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(RIG)
    return mod


RUNGAME = """#!/bin/dash
export JJPEDIR='/jjpe/gen1'
. $JJPEDIR/setenv.sh
chmod +x $JJPEDIR/scripts/runonce.sh
$JJPEDIR/scripts/runonce.sh

while true
do
  $GAMEDIR/game
done
"""

PORT = {"title": "Guns N' Roses", "switches": ["switch_target_jam", "switch_orbit_left_hi"],
        "lamps": ["lp_target_jam"], "sounds": ["se_cheer"], "fonts": ["font_slash_solo_mode_timer"],
        "game_modes": []}


def _folder(tmp_path, files):
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    return str(tmp_path)


def test_hook_goes_after_runonce_once_and_strips_clean():
    mm = _load("mkjjpmodes")
    hooked = mm.hook_rungame_modes(RUNGAME)
    lines = hooked.split("\n")
    at = lines.index("$JJPEDIR/scripts/runonce.sh")
    assert lines[at + 3] == "[ -r $JJPEDIR/scripts/padmodes.sh ] && . $JJPEDIR/scripts/padmodes.sh"
    assert mm.hook_rungame_modes(hooked) == hooked            # idempotent
    assert mm.strip_modes_hook(hooked) == RUNGAME


def test_hook_sits_beside_a_multiboot_hook():
    mm = _load("mkjjpmodes")
    multi = RUNGAME.replace("$JJPEDIR/scripts/runonce.sh\n",
                            "$JJPEDIR/scripts/runonce.sh\n\n# PAD multi-boot: a boot menu\n"
                            "[ -x $JJPEDIR/scripts/padselect.sh ] && $JJPEDIR/scripts/padselect.sh\n")
    hooked = mm.hook_rungame_modes(multi)
    assert "padselect.sh ] && $JJPEDIR/scripts/padselect.sh" in hooked
    assert mm.has_modes_hook(hooked) and mm.strip_modes_hook(hooked) == multi


def test_hook_refuses_a_rungame_it_does_not_know():
    mm = _load("mkjjpmodes")
    with pytest.raises(mm.Refused):
        mm.hook_rungame_modes(RUNGAME.replace("$JJPEDIR/scripts/runonce.sh\n", ""))


def test_padmodes_sh_honours_the_off_switch_and_appends_to_ld_preload():
    mm = _load("mkjjpmodes")
    assert "[ ! -e /jjpe/perm/padmodes.off ]" in mm.PADMODES_SH
    assert 'LD_PRELOAD="${LD_PRELOAD:+$LD_PRELOAD }$JJPEDIR/padmodes/jjpmodes.so"' in mm.PADMODES_SH
    assert "JJP_MODS_DIR=$JJPEDIR/padmodes/modes" in mm.PADMODES_SH


def test_check_passes_a_good_folder_and_names_every_problem(tmp_path):
    mm = _load("mkjjpmodes")
    good = _folder(tmp_path, {
        "title.cfg": "game = GunsNRoses\nfont_timer = font_slash_solo_mode_timer\n",
        "1_jam.mode": "name = Jam\nstart = switch_target_jam\npoints = 1,000,000  # a shot\n"
                      "lamps = lp_target_jam\nlamp_color = ff2000\ngame_modes = end\nsound_shot = se_cheer\n",
    })
    modes, problems = mm.check_modes(good, PORT)
    assert problems == [] and modes[0]["name"] == "Jam" and modes[0]["points"] == "1,000,000"
    (tmp_path / "2_bad.mode").write_text("start = switch_typo\nseconds = soon\nlamp_color = red\n"
                                         "game_modes = maybe\ningame_state = 5\nwobble = 1\n")
    _, problems = mm.check_modes(good, PORT)
    text = "\n".join(problems)
    assert "2_bad.mode:1: start not in Guns N' Roses: switch_typo" in text
    assert "seconds must be a whole number" in text
    assert "lamp_color must be rrggbb hex" in text
    assert "game_modes must be one of hold, pause, end, ignore" in text
    assert "ingame_state belongs in title.cfg" in text
    assert "unknown key wobble" in text


def test_check_wants_a_start_rule(tmp_path):
    mm = _load("mkjjpmodes")
    _, problems = mm.check_modes(_folder(tmp_path, {"a.mode": "name = A\n"}))
    assert problems == ["a.mode: no start rule (start, start_on, start_after, start_score or start_combo):"
                        " the mode would never start"]


def test_start_rules_alone_start_a_mode(tmp_path):
    """PAD-1354: a mode may start on a game event, a game mode ending, a score or a combo
    instead of a start switch."""
    mm = _load("mkjjpmodes")
    port = dict(PORT, hooks={h: True for h in mm.START_EVENTS.values()})
    d = _folder(tmp_path, {
        "1.mode": "start_on = ball_start multiball_end\nshots = switch_target_jam\nstart_once = ball\n",
        "2.mode": "start_after = any\nshots = switch_target_jam\nstart_count = 2\nstart_count_reset = ball\n",
        "3.mode": "start_score = 50,000,000\nshots = switch_target_jam\n",
        "4.mode": "start_combo = switch_target_jam switch_orbit_left_hi\ncombo_seconds = 4\n",
    })
    _, problems = mm.check_modes(d, port)
    assert problems == []


def test_start_rule_problems_are_named(tmp_path):
    mm = _load("mkjjpmodes")
    port = dict(PORT, hooks=dict({h: True for h in mm.START_EVENTS.values()}, HookLastBall_=False))
    d = _folder(tmp_path, {
        "1.mode": "start_on = ball_start tilt\n",
        "2.mode": "start_on = last_ball\n",
        "3.mode": "start_combo = switch_target_jam\n",
        "4.mode": "start_score = 0\n",
        "5.mode": "start = switch_target_jam\nstart_once = always\nstart_count_reset = never\n",
    })
    text = "\n".join(mm.check_modes(d, port)[1])
    assert "1.mode:1: start_on tilt: not a start event" in text
    assert "2.mode:1: start_on last_ball: Guns N' Roses has no HookLastBall_ hook" in text
    assert "3.mode: start_combo needs two switches or more" in text
    assert "4.mode: start_score must be above 0" in text
    assert "start_once must be one of no, ball, game" in text
    assert "start_count_reset must be one of game, ball" in text


def test_runtime_start_events_match_the_checker_and_the_port_report():
    """The start_on words and their hook lists are one table in jjpmodes.c (EVENTS),
    mkjjpmodes.py (START_EVENTS) and jjpport.py (RULE_HOOKS)."""
    mm, jp = _load("mkjjpmodes"), _load("jjpport")
    src = open(os.path.join(RIG, "jjpmodes.c"), encoding="utf-8").read()
    body = src[src.index("EVENTS[] = {"):src.index("#define NEVENTS")]
    runtime = re.findall(r'\{ "([a-z_]+)", "(Hook[A-Za-z]+_)" \}', body)
    assert runtime == list(mm.START_EVENTS.items())
    assert set(h for _, h in runtime) <= set(jp.RULE_HOOKS)
    for h in ("HookGameStart_", "HookBallStart_", "HookScore_") + jp.TICK_HOOKS:
        assert 'hook_add("%s"' % h in src


def test_port_finds_hook_lists_by_their_mangled_names():
    """jjpport.rule_hooks reads Hook<HookX_, Arg>::list globals the way jjpmodes.c
    hook_list finds them: _ZN4HookI<len><name>...E4listE, 16 bytes."""
    jp = _load("jjpport")

    class E:
        syms = {"_ZN4HookI14HookBallStart_vE4listE": (0x10, 16),
                "_ZN4HookI10HookScore_P17hook_score_data_tE4listE": (0x20, 16),
                "_ZN4HookI14HookBallStart_vE11master_linkE": (0x30, 24),
                "_ZN4HookI15HookLampRender_vE4listE": (0x40, 8),
                "_Z22score_get_player_scorei": (0x50, 55), "_Z23game_flow_get_player_upv": (0x60, 59)}
    h = jp.rule_hooks(E())
    assert h["HookBallStart_"] and h["HookScore_"] and not h["HookLampRender_"] and not h["HookLastBall_"]
    sr = jp.start_rules(E(), h)
    assert sr["can_start_on_rules"] is False and sr["start_on"] == [] and sr["start_combo"] is True
    h["HookUpdate_"] = True
    sr = jp.start_rules(E(), h)
    assert sr["can_start_on_rules"] and sr["start_on"] == ["ball_start"] and sr["start_score"]


def test_every_title_that_runs_modes_offers_the_start_rules():
    """The shipped port reports: every title that can run modes has every hook list
    (read off each title's own game binary, PAD-1354)."""
    jp = _load("jjpport")
    ports = os.path.join(RIG, "modes", "ports")
    seen = 0
    for fn in sorted(os.listdir(ports)):
        with open(os.path.join(ports, fn)) as f:
            p = json.load(f)
        if not p["can_run_modes"]:
            continue
        seen += 1
        assert p["start_rules"]["can_start_on_rules"], fn
        assert all(p["hooks"][h] for h in jp.RULE_HOOKS), fn
    assert seen >= 6


def test_every_key_the_runtime_reads_is_a_key_the_checker_knows():
    mm = _load("mkjjpmodes")
    src = open(os.path.join(RIG, "jjpmodes.c"), encoding="utf-8").read()
    body = src[src.index("static void apply_kv("):src.index("static int load_file(")]
    runtime = set(re.findall(r'!strcmp\(k, "([a-z_]+)"\)', body))
    assert runtime == set(mm.KEYS) | set(mm.TITLE_KEYS)


class _StubElf:
    """Enough of jjpelf.GameElf for mode_vtable: a _ZTV4Mode laid out like GnR's, where
    is_timer_paused shares its body with another class's hook and the start and total
    choreo hooks are one body."""

    def __init__(self):
        self.syms, words = {}, [0, 0x1111]
        fns = {"_ZN4Mode5startEv": 0x10, "_ZN4Mode3endEv": 0x20, "_ZN4Mode8set_timeEi": 0x28,
               "_ZN4Mode10is_runningEv": 0x48, "_ZN4Mode15score_and_totalEy": 0x88,
               "_ZN4Mode14hook_tick_workEi": 0xa8}
        empty, false_ = 0x9000, 0x9100
        slots = [0x5000 + i for i in range(24)]
        for name, off in fns.items():
            slots[off // 8] = 0x6000 + off
            self.syms[name] = (0x6000 + off, 8)
        slots[0x38 // 8] = false_
        slots[0xb0 // 8] = slots[0xb8 // 8] = empty
        self.syms["_ZN4Mode15is_timer_pausedEv"] = (false_, 8)
        self.syms["_ZN4Mode25hook_do_mode_start_choreoEv"] = (empty, 8)
        self.syms["_ZN4Mode25hook_do_mode_total_choreoEv"] = (empty, 8)
        words += slots
        self.blob = struct.pack("<%dQ" % len(words), *words)
        self.syms["_ZTV4Mode"] = (0x100000, len(self.blob))

    def addr(self, n):
        return self.syms[n][0]

    def read(self, a, n):
        return self.blob[a - 0x100000:a - 0x100000 + n]


def test_vtable_resolution_tells_folded_virtuals_apart():
    jp = _load("jjpport")
    vt = jp.mode_vtable(_StubElf())
    assert vt == {"start": 0x10, "end": 0x20, "set_time": 0x28, "is_running": 0x48, "timer_paused": 0x38,
                  "score": 0x88, "tick": 0xa8, "start_choreo": 0xb0, "total_choreo": 0xb8}


class _MemElf:
    """A sparse address space for jjpport.hold: typeinfos and vtables at chosen addresses."""

    def __init__(self):
        self.syms, self.mem = {}, {}

    def put(self, name, a, words):
        self.syms[name] = (a, 8 * len(words))
        for i, w in enumerate(words):
            self.mem[a + 8 * i] = struct.pack("<Q", w)

    def addr(self, n):
        return self.syms[n][0]

    def read(self, a, n):
        out = b""
        while len(out) < n:
            base = a + len(out) - (a + len(out)) % 8
            out += self.mem.get(base, b"\0" * 8)[(a + len(out)) - base:]
        return out[:n]


def test_hold_finds_mode_and_multiball_classes_up_the_typeinfo_chain():
    """PAD-1348: the classes game_modes = hold gates, found the way jjpmodes.c finds them in
    the game: single-inheritance bases at +16, multiple-inheritance {base, offset} from +24."""
    jp = _load("jjpport")
    e = _MemElf()
    SI, VMI = 0x7000, 0x7100            # libstdc++'s typeinfo vtables (outside the game)
    e.put("_ZTI4Mode", 0x1000, [SI - 0, 0x9000])
    e.put("_ZTI13MultiballRule", 0x1100, [SI, 0x9010])
    e.put("_ZTI5Other", 0x1200, [SI, 0x9020])
    e.put("_ZTI9AwardMode", 0x1300, [SI, 0x9030, 0x1000])                  # : Mode
    e.put("_ZTI8HurryUp", 0x1400, [SI, 0x9040, 0x1300])                    # : AwardMode : Mode
    e.put("_ZTI7LockMB", 0x1500, [VMI, 0x9050, (2 << 32), 0x1200, 0, 0x1100, 0x802])  # : Other, MultiballRule
    e.put("_ZTI6Plain", 0x1600, [SI, 0x9060, 0x1200])                      # : Other
    fn = {"_ZN4Mode5startEv": 0x5010, "_ZN4Mode7restartEv": 0x5018,
          "_ZN13MultiballRule5startEv": 0x5110, "_ZN13MultiballRule7restartEv": 0x5118}
    for n, a in fn.items():
        e.syms[n] = (a, 8)
    e.put("_ZTV4Mode", 0x2000, [0, 0x1000, 0x5000, 0x5008, 0x5010, 0x5018])
    e.put("_ZTV13MultiballRule", 0x2100, [0, 0x1100] + [0x6100 + 8 * i for i in range(17)] + [0x5110, 0x5118])
    for i, (cls, ti) in enumerate([("9AwardMode", 0x1300), ("8HurryUp", 0x1400), ("7LockMB", 0x1500),
                                   ("6Plain", 0x1600)]):
        e.put("_ZTV" + cls, 0x3000 + 0x100 * i, [0, ti, 1, 2, 3, 4])
    h = jp.hold(e)
    assert h["can_hold"] is True
    assert h["slots"] == {"mode_start": 0x10, "mode_restart": 0x18,
                          "multiball_start": 0x88, "multiball_restart": 0x90}
    assert h["mode_classes"] == 3          # Mode itself, AwardMode, HurryUp
    assert h["multiball_classes"] == ["13MultiballRule", "7LockMB"]


def test_runtime_policies_match_the_checker():
    """game_modes values jjpmodes.c reads are the ones mkjjpmodes.py accepts (hold is the default)."""
    mm = _load("mkjjpmodes")
    src = open(os.path.join(RIG, "jjpmodes.c"), encoding="utf-8").read()
    body = src[src.index('!strcmp(k, "game_modes")'):src.index('!strcmp(k, "hold_multiballs")')]
    assert set(re.findall(r'!strcmp\(v, "([a-z]+)"\)', body)) | {"hold"} == set(dict(mm.KEYS)["game_modes"])
    assert "m->game_modes = POLICY_HOLD; m->hold_multiballs = 1;" in src
