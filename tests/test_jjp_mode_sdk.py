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
        if not fn.endswith(".json") or fn.endswith(".live.json"):     # live mode maps (jjpstock.py)
            continue
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


def test_a_lamp_group_is_a_lamp_name_too(tmp_path):
    # PAD-1350: `lamps` takes lp_* lamps or ls_* lamp groups (MODES.md); the checker knew only lamps
    mm = _load("mkjjpmodes")
    port = dict(PORT, lamp_groups=["ls_all"])
    folder = _folder(tmp_path, {"1.mode": "start = switch_target_jam\nlamps = lp_target_jam ls_all\n"})
    assert mm.check_modes(folder, port)[1] == []
    (tmp_path / "1.mode").write_text("start = switch_target_jam\nlamps = ls_nope\n")
    assert "lamps not in" in "\n".join(mm.check_modes(folder, port)[1])


def test_every_title_that_can_run_modes_has_a_starter_that_checks_clean():
    import json
    mm = _load("mkjjpmodes")
    ports = os.path.join(RIG, "modes", "ports")
    can = []
    for fn in sorted(os.listdir(ports)):
        if fn.endswith(".live.json"):                   # a running game's read (PAD-1351), not a title
            continue
        p = json.load(open(os.path.join(ports, fn), encoding="utf-8"))
        if not p["can_run_modes"]:
            continue
        label = fn[:-5]
        can.append(label)
        modes, problems = mm.check_modes(os.path.join(RIG, "modes", "examples", label), p)
        assert modes and problems == [], (label, problems)
        # the vtable slots the runtime uses, resolved the same on every title
        assert {k: p["mode_vtable"][k] for k in ("start", "end", "score", "tick")} == \
            {"start": 16, "end": 32, "score": 136, "tick": 168}, label
    assert len(can) == 9, can


def test_build_needs_no_prebuilt_runtime():
    # PAD-1350: left out, --so means "build it against the ISO's own glibc"
    mm = _load("mkjjpmodes")
    src = open(os.path.join(RIG, "mkjjpmodes.py"), encoding="utf-8").read()
    build_parser = src[src.index('sub.add_parser("build"'):src.index('sub.add_parser("inspect"')]
    assert 'add_argument("--so", help=' in build_parser and "default=SO_DEFAULT" not in build_parser
    assert "build_runtime(mnt + ROOT_LIBDIR" in src and mm.ROOT_LIBDIR == "/lib/x86_64-linux-gnu"
    assert "OBJ=\"${OUT%.so}.o\"" in open(os.path.join(RIG, "buildmods.sh"), encoding="utf-8").read()


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


def test_starter_lamp_is_the_one_at_the_start_shot():
    """PAD-1364: the starter's lamp shares the start switch's words, not just its last one
    (Hobbit's 'made' found nothing, Godfather's '1' found the map, Toy Story's 'target' a
    target across the playfield)."""
    jp = _load("jjpport")
    assert jp._lamp_for("ramp_left_made", ["lp_gi_jets_high", "lp_gi_ramp_left_low", "lp_orc"]) == "lp_gi_ramp_left_low"
    assert jp._lamp_for("u_target_1", ["lp_map_1", "lp_u_flasher_2", "lp_upper_target_2",
                                       "lp_gi_upper_target_1", "lp_upper_target_1"]) == "lp_upper_target_1"
    assert jp._lamp_for("jet_target", ["lp_target_left", "lp_jet_bot"]) == "lp_jet_bot"
    assert jp._lamp_for("target_tv", ["lp_gi_tv", "lp_target_jam"]) == "lp_gi_tv"
    assert jp._lamp_for("target_left", ["lp_inlane_left", "lp_song_target_left"]) == "lp_song_target_left"
    assert jp._lamp_for("target_away", ["lp_gi_jets", "lp_target_left_x"]) == ""   # only 'target': no lamp
    assert jp._lamp_for("target_away", ["lp_gi_skyline_1"]) == ""


def test_every_committed_port_has_its_starter_and_it_checks():
    """Every title in modes/ports that can run modes has a starter folder in modes/examples
    that passes check --port against it; a title that cannot has none (PAD-1337, PAD-1364)."""
    import glob
    import json
    mm = _load("mkjjpmodes")
    ports = sorted(p for p in glob.glob(os.path.join(RIG, "modes", "ports", "*.json"))
                   if not p.endswith(".live.json"))      # jjpstock.py live captures, not reports
    if not ports:
        pytest.skip("no port reports")
    names = {os.path.basename(p)[:-5] for p in ports}
    assert {"DialedIn-v02.02", "Hobbit-v04.02", "ToyStory-v02.04", "WizardOfOz-v08.02", "Avatar-v01.03"} <= names
    for p in ports:
        t = os.path.basename(p)[:-5]
        port = json.load(open(p, encoding="utf-8"))
        ex = os.path.join(RIG, "modes", "examples", t)
        if not port["can_run_modes"]:
            assert not os.path.isdir(ex), t
            continue
        assert port["missing_required"] == [], t
        _, problems = mm.check_modes(ex, port)
        assert problems == [], (t, problems)


# ------------------------------------------------------------------ USB mode stick (PAD-1349)
def _stick_inputs(tmp_path):
    mods = tmp_path / "mods"
    mods.mkdir()
    (mods / "title.cfg").write_text("game = GunsNRoses\n")
    (mods / "1_jam.mode").write_text("name = Jam Session\nstart = switch_target_jam\n")
    so = tmp_path / "jjpmodes.so"
    so.write_bytes(b"\x7fELF" + b"\0" * 60)
    return str(mods), str(so)


def test_stick_writes_runme_payload_and_sums(tmp_path):
    import hashlib
    mm = _load("mkjjpmodes")
    mods, so = _stick_inputs(tmp_path)
    out = tmp_path / "usb"
    assert mm.main(["stick", "--out", str(out), "--modes", mods, "--so", so]) == 0
    hot = out / "hotfix"
    runme = (hot / "runme.sh").read_bytes()
    assert b"\r" not in runme and b"@" not in runme.replace(b"@WRITTEN", b"")   # LF, every placeholder filled
    text = runme.decode()
    assert "ACTION=install" in text and "GAME=GunsNRoses" in text and "Jam Session" in text
    assert "'[ -r $JJPEDIR/scripts/padmodes.sh ] && . $JJPEDIR/scripts/padmodes.sh'" in text   # single-quoted
    sums = (hot / "padmodes.sha256").read_text().splitlines()
    assert len(sums) == 4                                      # so, title.cfg, the mode, build.json
    for ln in sums:
        h, rel = ln.split("  ", 1)
        assert hashlib.sha256((hot / rel).read_bytes()).hexdigest() == h
    assert (hot / "padmodes.sh").read_text() == mm.PADMODES_SH
    assert "Plus, Minus, Plus, Minus" in (out / "PADMODES_README.txt").read_text()


def test_stick_refuses_without_a_game_or_over_an_old_stick(tmp_path):
    mm = _load("mkjjpmodes")
    mods, so = _stick_inputs(tmp_path)
    out = str(tmp_path / "usb")
    assert mm.main(["stick", "--out", out, "--action", "off"]) == 2          # which game?
    assert mm.main(["stick", "--out", out, "--action", "off", "--game", "Wonka"]) == 0
    assert mm.main(["stick", "--out", out, "--action", "on", "--game", "Wonka"]) == 2   # exists
    assert mm.main(["stick", "--out", out, "--action", "on", "--game", "Wonka", "--force"]) == 0
    assert mm.main(["stick", "--out", out, "--action", "on", "--game", "W;rm"]) == 2


@pytest.mark.skipif(os.name == "nt" or not __import__("shutil").which("dash")
                    or not __import__("shutil").which("sha256sum"), reason="needs dash + sha256sum")
def test_stick_runme_installs_turns_off_on_and_removes_like_the_python_hook(tmp_path):
    import subprocess
    mm = _load("mkjjpmodes")
    mods, so = _stick_inputs(tmp_path)
    j = tmp_path / "J"
    (j / "scripts").mkdir(parents=True)
    (j / "GunsNRoses").mkdir()
    (j / "GunsNRoses" / "game").write_text("")
    (j / "scripts" / "rungame.sh").write_text(RUNGAME)
    off = tmp_path / "perm" / "padmodes.off"
    env = dict(os.environ, JJPEDIR=str(j), PAD_STICK_OFF=str(off), PAD_STICK_LOG=str(tmp_path / "log"))

    def run(*args):
        out = tmp_path / "usb"
        assert mm.main(["stick", "--out", str(out), "--force"] + list(args)) == 0
        return subprocess.run(["dash", str(out / "hotfix" / "runme.sh")], env=env).returncode

    off.parent.mkdir()
    off.write_text("")
    assert run("--modes", mods, "--so", so) == 0
    assert (j / "scripts" / "rungame.sh").read_text() == mm.hook_rungame_modes(RUNGAME)
    assert (j / "padmodes" / "modes" / "1_jam.mode").exists() and not off.exists()
    assert run("--modes", mods, "--so", so) == 0                # again: hooked once
    assert (j / "scripts" / "rungame.sh").read_text() == mm.hook_rungame_modes(RUNGAME)
    assert run("--action", "off", "--game", "GunsNRoses") == 0 and off.exists()
    assert run("--action", "on", "--game", "GunsNRoses") == 0 and not off.exists()
    assert run("--action", "off", "--game", "Wonka") == 1 and not off.exists()   # another title: nothing
    assert run("--action", "remove", "--game", "GunsNRoses") == 0
    assert (j / "scripts" / "rungame.sh").read_text() == RUNGAME
    assert not (j / "padmodes").exists() and not (j / "scripts" / "padmodes.sh").exists()
