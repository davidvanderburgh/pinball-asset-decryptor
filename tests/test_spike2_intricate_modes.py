"""Item 152: the INTRICATE example modes (tools/spike2_emu/modes/sdk/examples/).

Three layers, each skipping cleanly where its tools are missing:

- Static checks, everywhere: every mode file registers one mode, names its screen after its own
  folder, uses only shots the Godzilla Premium 1.16 port names and only calls pad_mode.h declares,
  and its words (screen lines, the README) carry no em or en dashes.
- The ARM build (build_mode.sh), where arm-linux-gnueabihf-gcc and bash are: each mode alone, and
  all five together with mode_file.c, the way the card carries them.
- The desk harness (examples/desk_harness.c), where an ELF host C compiler is: every mode played
  through its start, its phases, its success path and its failure paths against a fake game.
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

SDK = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk"
EX = SDK / "examples"
MODES = ["ghidorah_heads", "oxygen_destroyer", "maser_barrage", "final_wars", "anguirus_assist"]
NAMES = {"ghidorah_heads": "KING GHIDORAH", "oxygen_destroyer": "OXYGEN DESTROYER",
         "maser_barrage": "MASER BARRAGE", "final_wars": "FINAL WARS", "anguirus_assist": "ANGUIRUS"}
PREMIUM_PORT = SDK / "ports" / "godzilla_le-1.16.port"


def _src(slug):
    return (EX / (slug + ".c")).read_text(encoding="utf-8")


def _port_shots(path):
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"shot\s+0x[0-9a-fA-F]+\s+(.+?)\s*$", line)
        if m:
            out.add(m.group(1))
    return out


# ---- static checks (every platform) -----------------------------------------------------------
@pytest.mark.parametrize("slug", MODES)
def test_each_mode_registers_one_mode_named_for_its_folder(slug):
    src = _src(slug)
    assert len(re.findall(r"^PM_REGISTER\(", src, re.M)) == 1
    assert '#define FOLDER             "%s"' % slug in src
    assert '#define MODE_NAME          "%s"' % NAMES[slug] in src
    assert '#define SCREEN_NODE "PadMode_" FOLDER "_Screen"' in src
    assert '#define SCREEN_TEXT "PadMode_" FOLDER "_Screen.PadMode_" FOLDER "_Screen_Words"' in src


@pytest.mark.parametrize("slug", MODES)
def test_every_shot_a_mode_names_is_in_the_premium_port(slug):
    shots = _port_shots(PREMIUM_PORT)
    named = set(re.findall(r'"((?:Left|Right) ramp|Building|Godzilla target|Maser target|Powerline \w+|'
                           r'Shield target \w+|Big loop|Skill shot)"', _src(slug)))
    assert named, slug
    assert named <= shots, named - shots


def test_only_calls_the_header_declares():
    declared = set(re.findall(r"\b(pm_\w+)\s*\(", (SDK / "pad_mode.h").read_text(encoding="utf-8")))
    for f in MODES + ["intricate_kit"]:
        path = EX / (f + (".h" if f == "intricate_kit" else ".c"))
        used = set(re.findall(r"\b(pm_\w+)\s*\(", path.read_text(encoding="utf-8")))
        assert used <= declared, (f, used - declared)


def test_no_libc_call_a_mode_may_not_make():
    banned = re.compile(r"\b(malloc|calloc|realloc|free|printf|fopen|sleep|usleep|pthread_\w+|system)\s*\(")
    for f in MODES:
        assert not banned.search(_src(f)), f
    assert not banned.search((EX / "intricate_kit.h").read_text(encoding="utf-8"))


def _strings(text):
    return re.findall(r'"((?:[^"\\\n]|\\.)*)"', text)


def test_no_em_or_en_dash_in_what_a_player_or_a_reader_sees():
    for f in MODES:
        for s in _strings(_src(f)):
            assert "\u2014" not in s and "\u2013" not in s, (f, s)
    readme = (EX / "README.md").read_text(encoding="utf-8")
    assert "\u2014" not in readme and "\u2013" not in readme


def test_every_line_a_mode_writes_on_its_screen_is_short():
    # the words sit on one line under the panel; the film pack's longest proven line is 16
    # characters ("3,000,000 A SHOT"); keep every fixed line and every format to 22
    for f in MODES:
        src = _src(f)
        for m in re.finditer(r'kit_screen_(?:flash|note)\(&screen, \d+, "([^"]*)"\)', src):
            assert len(m.group(1)) <= 22, (f, m.group(1))
        for m in re.finditer(r'pm_snprintf\((?:a|b|line), sizeof (?:a|b|line), "([^"]*)"', src):
            shown = re.sub(r"%(?:l?l?u|d|s)", "", m.group(1))
            assert len(shown) <= 20, (f, m.group(1))


def test_the_readme_has_a_rules_sheet_for_every_mode():
    readme = (EX / "README.md").read_text(encoding="utf-8")
    for slug in MODES:
        assert "`%s.c`" % slug in readme, slug
        assert NAMES[slug] in readme, slug
    for word in ("How to start it", "How it ends", "How often"):
        assert word in readme


# ---- the ARM build ---------------------------------------------------------------------------------
def _arm():
    if os.name == "nt":
        pytest.skip("build_mode.sh runs under bash with arm-linux-gnueabihf-gcc (WSL or Linux)")
    if not shutil.which("bash") or not shutil.which("arm-linux-gnueabihf-gcc"):
        pytest.skip("no arm-linux-gnueabihf-gcc here")


@pytest.mark.parametrize("slug", MODES)
def test_each_mode_builds_alone_with_build_mode_sh(slug, tmp_path):
    _arm()
    out = tmp_path / (slug + ".so")
    r = subprocess.run(["bash", str(SDK / "build_mode.sh"), "-o", str(out), str(EX / (slug + ".c"))],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "warning" not in (r.stdout + r.stderr).lower()
    assert out.stat().st_size > 0


def test_all_five_build_into_one_object_with_mode_file_c(tmp_path):
    _arm()
    out = tmp_path / "mode.so"
    r = subprocess.run(["bash", str(SDK / "build_mode.sh"), "-o", str(out)]
                       + [str(EX / (s + ".c")) for s in MODES] + [str(SDK / "mode_file.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "warning" not in (r.stdout + r.stderr).lower()
    nm = shutil.which("arm-linux-gnueabihf-nm")
    if nm:
        syms = subprocess.run([nm, str(out)], capture_output=True, text=True).stdout
        # the pack's shared state is ONE object each, however many files include the kit
        for name in ("kit_ledger", "kit_running", "kit_screen_up"):
            assert len(re.findall(r"\s%s$" % name, syms, re.M)) == 1, name


# ---- the desk harness --------------------------------------------------------------------------------
def _cc():
    if os.name == "nt":
        pytest.skip("the desk harness needs an ELF linker (__start_pm_modes / __stop_pm_modes)")
    if sys.platform == "darwin":
        pytest.skip("the desk harness needs an ELF toolchain (section(\"pm_modes\"))")
    for c in ("gcc", "cc", "clang"):
        if shutil.which(c):
            return c
    pytest.skip("no host C compiler")


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    cc = _cc()
    exe = tmp_path_factory.mktemp("intricate") / "harness"
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wextra", "-Wno-unused-parameter", "-I", str(SDK), "-o", str(exe),
                        str(EX / "desk_harness.c")] + [str(EX / (s + ".c")) for s in MODES],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "warning" not in r.stderr.lower(), r.stderr
    return exe


def play(harness, *args):
    r = subprocess.run([str(harness)] + [str(a) for a in args], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def lines(out, mode):
    return [ln for ln in out.splitlines() if "[%s]" % mode in ln]


def has(out, mode, text):
    return any(text in ln for ln in lines(out, mode))


def scored(out, since_text, mode):
    """the SCORE lines between a mode's START and its END"""
    total, on = 0, False
    for ln in out.splitlines():
        if "[%s] START" % mode in ln:
            on = True
        elif "[%s] END" % mode in ln:
            on = False
        elif on and " SCORE +" in ln:
            total += int(re.search(r"SCORE \+(\d+)", ln).group(1))
    return total


def end_total(out, mode):
    m = re.search(r"\[%s\] END \(.*total (\d+)" % re.escape(mode), out)
    return int(m.group(1))


POWERLINES = ["shot", "Powerline left", "shot", "Powerline center", "shot", "Powerline right"]


def test_ghidorah_is_won_head_by_head_and_the_maser_lands_the_super_jackpot(harness):
    out = play(harness, *POWERLINES, "secs", 1,
               "shot", "Left ramp", "shot", "Right ramp", "shot", "Powerline left", "secs", 1,
               "shot", "Building", "shot", "Powerline center", "secs", 1,
               "shot", "Right ramp", "shot", "Powerline right", "secs", 2, "shot", "Maser target", "secs", 8)
    g = "KING GHIDORAH"
    assert has(out, g, "START (three powerlines)")
    assert has(out, g, "Left ramp: LEFT HEAD -2 (health 1) +2000000")
    assert has(out, g, "Right ramp: glancing blow on RIGHT HEAD (lit: LEFT HEAD) +250000")
    assert has(out, g, "LEFT HEAD SEVERED (1 of 3): +5000000, +10 s on the clock")
    assert has(out, g, "MIDDLE HEAD SEVERED (2 of 3): +10000000, +10 s on the clock")
    assert has(out, g, "RIGHT HEAD SEVERED (3 of 3): +15000000")
    assert has(out, g, "FINAL BLOW: Maser target lit for 15 s")
    assert has(out, g, "SUPER JACKPOT: Maser target with 13 s left, +33000000")
    assert has(out, g, "END (super jackpot): WON, 3 of 3 heads severed")
    assert end_total(out, g) == scored(out, "", g) == 2000000 + 250000 + 1000000 + 5000000 + 3000000 + 10000000 \
        + 3000000 + 15000000 + 33000000
    assert "WORDS PadMode_ghidorah_heads_Screen_Words: GHIDORAH DEFEATED" in out
    assert "SHOW PadMode_ghidorah_heads_Screen 0" in out.split("[KING GHIDORAH] END")[1]   # hidden after the total


def test_ghidorah_regrows_a_head_left_alone_turns_and_escapes_on_time(harness):
    out = play(harness, *POWERLINES, "secs", 1, "shot", "Left ramp", "secs", 12, "secs", 60)
    g = "KING GHIDORAH"
    assert has(out, g, "the lit head moves: LEFT HEAD -> MIDDLE HEAD")
    assert has(out, g, "LEFT HEAD REGROWS: health 2")
    assert has(out, g, "END (time ran out): not won, 0 of 3 heads severed")
    assert "CALLOUT 1295" in out
    assert "GHIDORAH ESCAPES" in out


def test_ghidorah_final_blow_missed_is_an_escape(harness):
    out = play(harness, *POWERLINES, "secs", 1,
               "shot", "Left ramp", "shot", "Powerline left", "secs", 1, "shot", "Building", "shot", "Powerline center",
               "secs", 1, "shot", "Right ramp", "shot", "Powerline right", "secs", 17)
    assert has(out, "KING GHIDORAH", "END (the final blow was not made): not won, 3 of 3 heads severed")


def test_ghidorah_waits_for_the_games_own_battle_and_runs_once_a_ball(harness):
    # ANGUIRUS joined that battle; when it ends, its total has 4 s on the screen first (item 157)
    out = play(harness, "battle", 1, *POWERLINES, "secs", 1, "battle", 0, "secs", 5, "shot", "Powerline left", "secs", 1,
               "trigger", "ghidorah_heads.stop", *POWERLINES, "ball_end", "secs", 1, *POWERLINES, "secs", 1,
               "trigger", "ghidorah_heads.stop", "ball_end", "secs", 1, *POWERLINES)
    g = "KING GHIDORAH"
    assert has(out, g, "not started (three powerlines): a battle is running")
    assert has(out, g, "START (three powerlines): player 1, 50 s, heads 3/3/3, lit LEFT HEAD, start 1 this game")
    assert has(out, g, "not counted - it already ran this ball")
    assert has(out, g, "start 2 this game")
    assert has(out, g, "not counted - it already ran twice this game")


def test_a_target_hit_twelve_times_in_a_second_pays_at_most_four_times(harness):
    rapid = []
    for _ in range(12):
        rapid += ["raw", "0x1", "raw", "0x100000", "ms", 83]          # Left ramp, 12 times in 1 s
    out = play(harness, "event", "skill_shot", "secs", 1, *rapid, "secs", 1)
    steps = [ln for ln in lines(out, "MASER BARRAGE") if "step 1 Left ramp" in ln]
    assert len(steps) == 1                                            # counted once; the rest out of order
    assert len([ln for ln in lines(out, "MASER BARRAGE") if "counted once" in ln]) >= 8
    out = play(harness, *POWERLINES, "secs", 1, *rapid, "secs", 1)
    hits = [ln for ln in lines(out, "KING GHIDORAH") if "Left ramp: LEFT HEAD" in ln]
    assert 1 <= len(hits) <= 4
    assert scored(out, "", "KING GHIDORAH") <= 4 * 2000000 + 5000000


def test_oxygen_destroyer_collects_holds_off_and_delivers_double(harness):
    gt = ["shot", "Godzilla target", "ms", 400]
    out = play(harness, *gt, *gt, *gt, "secs", 5, *gt, "secs", 2, "shot", "Left ramp", "secs", 3,
               "shot", "Right ramp", "secs", 7)
    o = "OXYGEN DESTROYER"
    assert has(out, o, "Godzilla target 3 of 3 (player 1)")
    assert has(out, o, "START (Godzilla target)")
    assert has(out, o, "hold-off 1 of 3, the value is back to")
    m = re.search(r"COLLECTED at Left ramp: (\d+) \(asked (\d+)\)", out)
    collected = int(m.group(1))
    assert 13000000 < collected < 16500000
    assert has(out, o, "SUPER JACKPOT at Right ramp: +%d" % (2 * collected))
    assert has(out, o, "END (super jackpot): WON, collected %d, total %d" % (collected, 3 * collected))


def test_oxygen_destroyer_is_lost_when_the_value_runs_out_and_cools_down(harness):
    gt = ["shot", "Godzilla target", "ms", 400]
    out = play(harness, *gt, *gt, *gt, "secs", 26, *gt)
    o = "OXYGEN DESTROYER"
    assert has(out, o, "END (the value ran out before it was collected): not won, collected 0, total 0")
    assert "CALLOUT 1291" in out and "CALLOUT 1287 0" in out and "CALLOUT 1295" in out
    assert has(out, o, "not counted - cooling down")
    assert "WORDS PadMode_oxygen_destroyer_Screen_Words: LOST" in out


def test_oxygen_destroyer_super_jackpot_missed_keeps_what_was_collected(harness):
    gt = ["shot", "Godzilla target", "ms", 400]
    out = play(harness, *gt, *gt, *gt, "secs", 1, "shot", "Left ramp", "secs", 13)
    collected = int(re.search(r"COLLECTED at Left ramp: (\d+)", out).group(1))
    assert has(out, "OXYGEN DESTROYER", "END (the super jackpot ran out): not won, collected %d, total %d"
               % (collected, collected))


def test_maser_barrage_starts_on_the_skill_shot_event_and_its_chain_breaks(harness):
    out = play(harness, "event", "skill_shot", "secs", 1,
               "shot", "Right ramp", "shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 1, "shot", "Building",
               "secs", 1, "shot", "Left ramp", "secs", 7,
               "shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 1, "shot", "Building", "secs", 50)
    b = "MASER BARRAGE"
    assert has(out, b, "START (skill shot)")
    assert has(out, b, "Right ramp: out of order (next is Left ramp) - no effect")
    assert has(out, b, "BARRAGE 1: jackpot +5000000 (x1); multiplier -> x2")
    assert has(out, b, "step 1 Left ramp: +2000000 (x2)")
    assert has(out, b, "CHAIN BROKEN: no Right ramp within 6000 ms (was x2)")
    assert has(out, b, "BARRAGE 2: jackpot +5000000 (x1)")
    assert has(out, b, "END (time ran out): 2 barrage(s), best x2, 1 chain(s) broken")


def test_maser_barrage_holds_a_skill_shot_while_another_mode_runs_and_also_starts_on_the_maser(harness):
    out = play(harness, *POWERLINES, "secs", 1, "event", "skill_shot", "secs", 2,
               "trigger", "ghidorah_heads.stop", "secs", 1)
    assert has(out, "MASER BARRAGE", "skill shot held for 15 s: KING GHIDORAH is running")
    assert has(out, "MASER BARRAGE", "START (skill shot, held)")
    out = play(harness, "shot", "Maser target", "ms", 300, "shot", "Maser target", "ms", 300, "shot", "Maser target",
               "secs", 1, "event", "skill_shot")
    assert has(out, "MASER BARRAGE", "START (Maser target)")


def test_final_wars_lights_from_the_other_three_and_is_played_phase_by_phase(harness):
    out = play(harness, "shot", "Building", "secs", 1,
               *POWERLINES, "secs", 1, "trigger", "ghidorah_heads.stop", "secs", 1,
               "trigger", "oxygen_destroyer.start", "trigger", "oxygen_destroyer.stop", "secs", 1,
               "event", "skill_shot", "secs", 1, "trigger", "maser_barrage.stop", "secs", 9,
               "shot", "Building", "secs", 1,
               "shot", "Left ramp", "shot", "Shield target left", "secs", 1, "shot", "Right ramp", "shot", "Big loop",
               "secs", 1)
    f = "FINAL WARS"
    assert out.index("FINAL WARS IS LIT") < out.index("[FINAL WARS] START")
    assert has(out, f, "FINAL WARS IS LIT for player 1 (3 of 3 played, 0 won)")
    assert "WORDS PadMode_final_wars_Screen_Words: FINAL WARS IS LIT" in out
    assert has(out, f, "START (Building): player 1")
    assert has(out, f, "PHASE 1 (INVASION): 25 s")
    assert has(out, f, "ADD TIME: Shield target left +3 s (1 of 3 this phase)")
    assert has(out, f, "phase 1: Big loop +3000000, 0 left")
    lit = re.findall(r"PHASE 2 \(MONSTER X\): 25 s, lit (.+)$", out, re.M)
    assert lit


def _monster_x(harness, prefix):
    """play phase 2 by reading which target the harness says is lit, like the emulator run does"""
    args = list(prefix)
    for _ in range(3):
        out = play(harness, *args)
        m = re.findall(r"(?:lit|moves .*?->) (Powerline left|Powerline center|Powerline right|Godzilla target)\s*$",
                       out, re.M)
        args += ["shot", m[-1], "secs", 1]
    return args


def test_final_wars_moving_target_and_the_wizard_shot(harness):
    prefix = ["trigger", "final_wars.light", "secs", 8, "shot", "Building", "secs", 1,
              "shot", "Left ramp", "shot", "Right ramp", "shot", "Big loop", "ms", 500]
    args = _monster_x(harness, prefix) + ["shot", "Building", "secs", 8]
    out = play(harness, *args)
    f = "FINAL WARS"
    assert has(out, f, "phase 2: MONSTER X hit at") and has(out, f, "3 of 3, +15000000")
    assert has(out, f, "PHASE 3 (GHIDORAH): 20 s")
    assert has(out, f, "WIZARD JACKPOT: Building with")
    assert has(out, f, "END (wizard jackpot): WON in phase 3")
    assert "GODZILLA WINS" in out


def test_final_wars_waits_for_the_games_multiball_and_a_phase_clock_ends_it(harness):
    out = play(harness, "trigger", "final_wars.light", "secs", 8, "multiball", 1, "shot", "Building", "secs", 1,
               "multiball", 0, "shot", "Building", "secs", 27)
    f = "FINAL WARS"
    assert has(out, f, "not started (Building): a multiball is running - still lit")
    assert has(out, f, "END (a phase's clock ran out): not won in phase 1")
    assert "THE XILIENS WIN" in out


def test_final_wars_lights_when_two_are_won(harness):
    gt = ["shot", "Godzilla target", "ms", 400]
    out = play(harness, *gt, *gt, *gt, "secs", 1, "shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 8,
               "event", "skill_shot", "secs", 1, "shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 1,
               "shot", "Building", "secs", 1, "trigger", "maser_barrage.stop", "secs", 2)
    assert has(out, "FINAL WARS", "FINAL WARS IS LIT for player 1 (2 of 3 played, 2 won)")


def test_anguirus_joins_the_games_battle_charges_rolls_and_leaves_with_it(harness):
    out = play(harness, "battle", 1, "secs", 1, "shot", "Shield target left", "shot", "Shield target left",
               "secs", 1, "shot", "Shield target center", "shot", "Shield target right", "secs", 1,
               "shot", "Big loop", "secs", 2, "shot", "Big loop", "secs", 2, "shot", "Big loop", "secs", 7,
               "battle", 0, "secs", 1)
    a = "ANGUIRUS"
    assert has(out, a, "START (the game's battle began)")
    assert has(out, a, "Shield target left: that spike is already charged") or has(out, a, "counted once")
    assert has(out, a, "ROLL LIT: Big loop for 4000000")
    assert has(out, a, "ROLLING ATTACK 1 at Big loop: +4000000")
    assert has(out, a, "ROLLING ATTACK 2 at Big loop: +8000000")
    assert has(out, a, "ROLLING ATTACK 3 at Big loop: +16000000")
    assert has(out, a, "the roll is over")
    assert has(out, a, "END (the game's battle ended): 3 charge(s), 3 rolling attack(s), total 29500000")


def test_one_pack_mode_at_a_time_and_a_new_screen_replaces_the_last_total(harness):
    gt = ["shot", "Godzilla target", "ms", 400]
    out = play(harness, *POWERLINES, "secs", 1, *gt, *gt, *gt, "trigger", "ghidorah_heads.stop", "ms", 500, *gt)
    assert has(out, "OXYGEN DESTROYER", "not started: KING GHIDORAH is running")
    assert has(out, "OXYGEN DESTROYER", "START (Godzilla target)")
    after = out.split("[KING GHIDORAH] END")[1]
    assert "SHOW PadMode_ghidorah_heads_Screen 0" in after.split("[OXYGEN DESTROYER] START")[0]


@pytest.mark.parametrize("start", [POWERLINES, ["event", "skill_shot"], ["trigger", "final_wars.light", "secs", 8,
                                                                              "shot", "Building"]])
def test_a_drain_ends_the_mode_with_its_total(harness, start):
    out = play(harness, *start, "secs", 2, "ball_end", "secs", 1)
    assert re.search(r"\] END \(ball ended\)", out), out[-2000:]


def test_the_final_wars_note_waits_for_another_modes_total_to_go(harness):
    out = play(harness, "trigger", "final_wars.light", "trigger", "oxygen_destroyer.start", "secs", 9,
               "trigger", "oxygen_destroyer.stop", "secs", 9)
    end_ms = int(re.search(r"^\s*(\d+) \[OXYGEN DESTROYER\] END", out, re.M).group(1))
    note = re.search(r"^\s*(\d+) WORDS PadMode_final_wars_Screen_Words: FINAL WARS IS LIT", out, re.M)
    assert note, "the note never showed"
    assert int(note.group(1)) >= end_ms + 5900      # after OXYGEN DESTROYER's total (6 s), not over it
    hidden = re.search(r"^\s*(\d+) SHOW PadMode_oxygen_destroyer_Screen 0", out.split("[OXYGEN DESTROYER] END")[1], re.M)
    assert hidden and int(hidden.group(1)) <= int(note.group(1))


# ---- the modes' OWN clip, music and calls (pad_mode_assets.h) ------------------------------------------------
# What the build would carry for each mode, as the <folder>.assets file Write puts beside mode.so. The desk
# harness reads it from $HARNESS_DUMP (the rig's /dump) and prints every sound call; the game's own music is
# request 67 at priority 1, the music carrier request 125.
ASSETS = {
    "ghidorah_heads": ("KING GHIDORAH", 618, {"sever": 1251, "regrow": 1249, "won": 1133, "lost": 1020}),
    "oxygen_destroyer": ("OXYGEN DESTROYER", 105, {"collect": 1170, "won": 1188, "lost": 945}),
    "maser_barrage": ("MASER BARRAGE", 576, {"barrage": 1174, "broken": 1186, "won": 1192, "lost": 1172}),
    "final_wars": ("FINAL WARS", 555, {"phase1": 1076, "phase2": 1190, "won": 1247, "lost": 1129}),
    "anguirus_assist": ("ANGUIRUS", 357, {"spike": 1197, "roll": 972, "won": 1281, "lost": 1259}),
}


def test_every_mode_reads_its_own_assets_through_the_sdk_header():
    for slug in MODES:
        src = _src(slug)
        assert '#include "pad_mode_assets.h"' in src
        assert "static struct pa_assets own = { .folder = FOLDER };" in src
        assert src.count("pa_tick(&own);") == 1 and src.count("pa_load(&own);") == 1
        assert "pa_start(&own)" in src and "pa_end(&own)" in src
        for cue in ASSETS[slug][2]:
            assert '"%s"' % cue in src, (slug, cue)


@pytest.fixture
def dump(tmp_path):
    d = tmp_path / "dump"
    d.mkdir()
    for slug, (name, bed, calls) in ASSETS.items():
        text = ["# test", "name   %s" % name, "clip   start PadMode_%s_Clip" % slug, "music  125 %d" % bed]
        text += ["call   %s %d 1500 %d" % (cue, req, 3 if cue in ("spike", "roll") else 4)
                 for cue, req in calls.items()]
        (d / (slug + ".assets")).write_text("\n".join(text) + "\n")
    return str(d)


def play_own(harness, dump_dir, *args):
    env = dict(os.environ, HARNESS_DUMP=dump_dir)
    r = subprocess.run([str(harness)] + [str(a) for a in args], capture_output=True, text=True, timeout=60,
                       env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _at(out, text):
    m = re.search(r"^\s*(\d+) %s" % re.escape(text), out, re.M)
    return int(m.group(1)) if m else None


def test_ghidorah_plays_its_music_clip_and_calls_and_gives_the_music_back(harness, dump):
    out = play_own(harness, dump, *POWERLINES, "secs", 1,
                   "shot", "Left ramp", "shot", "Powerline left", "secs", 12,
                   "trigger", "ghidorah_heads.stop", "secs", 2)
    start = _at(out, "[KING GHIDORAH] START")
    assert _at(out, "SID 125 618") == start and _at(out, "FADE 67 250") == start
    assert 250 <= _at(out, "SOUND 125") - start <= 300                 # after the game's music has faded
    assert 480 <= _at(out, "CLIP PadMode_ghidorah_heads_Clip") - start <= 520
    assert "PRIO 1251 4 0" in out and "PRIO 125 1 0" in out            # no steal flag on any of ours
    assert _at(out, "SOUND 1251") is not None                          # the head severed
    assert "own sound: call 1251 stopped - its own sound is over" in out
    end = _at(out, "[KING GHIDORAH] END")
    assert _at(out, "FADE 125 400") == end
    back = out[out.index("[KING GHIDORAH] END"):]
    assert "SID 125 0" in back and "SOUND 67" in back                  # the game's music plays again
    assert "the game's music 67 is playing again" in back


def test_ghidorah_escapes_on_its_own_lost_call_not_the_games_time_up(harness, dump):
    out = play_own(harness, dump, *POWERLINES, "secs", 52)
    assert "own sound: call lost (1020) played" in out and "CALLOUT 1295" not in out
    # without its assets file it falls back to the game's own voice
    out = play(harness, *POWERLINES, "secs", 52)
    assert "CALLOUT 1295" in out and "SOUND 1020" not in out
    assert "own assets: no ghidorah_heads.assets" in out


def test_ghidorah_regrow_and_super_jackpot_calls(harness, dump):
    out = play_own(harness, dump, *POWERLINES, "secs", 1, "shot", "Powerline left", "secs", 11)
    assert "LEFT HEAD REGROWS" in out and "own sound: call regrow (1249) played" in out
    out = play_own(harness, dump, *POWERLINES, "secs", 1,
                   "shot", "Left ramp", "shot", "Right ramp", "shot", "Powerline left", "secs", 1,
                   "shot", "Building", "shot", "Powerline center", "secs", 1,
                   "shot", "Right ramp", "shot", "Powerline right", "secs", 2, "shot", "Maser target", "secs", 3)
    assert out.count("own sound: call sever (1251) played") >= 2
    assert "own sound: call won (1133) played" in out


def test_oxygen_destroyer_collect_won_and_lost_calls(harness, dump):
    gt = ["shot", "Godzilla target", "ms", 400]
    out = play_own(harness, dump, *gt, *gt, *gt, "secs", 2, "shot", "Left ramp", "secs", 3, "shot", "Right ramp",
                   "secs", 3)
    assert "SID 125 105" in out and "CLIP PadMode_oxygen_destroyer_Clip" in out
    assert "own sound: call collect (1170) played" in out and "own sound: call won (1188) played" in out
    out = play_own(harness, dump, *gt, *gt, *gt, "secs", 26)
    assert "own sound: call lost (945) played" in out and "CALLOUT 1295" not in out


def test_maser_barrage_barrage_broken_and_end_calls(harness, dump):
    out = play_own(harness, dump, "event", "skill_shot", "secs", 1,
                   "shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 1, "shot", "Building",
                   "secs", 1, "shot", "Left ramp", "secs", 7, "secs", 40)
    assert "own sound: call barrage (1174) played" in out
    assert "own sound: call broken (1186) played" in out
    assert "own sound: call won (1192) played" in out and "call lost (1172)" not in out
    out = play_own(harness, dump, "event", "skill_shot", "secs", 42)
    assert "own sound: call lost (1172) played" in out


def test_final_wars_plays_a_call_for_each_phase_won_and_its_end(harness, dump):
    prefix = ["trigger", "final_wars.light", "secs", 8, "shot", "Building", "secs", 1,
              "shot", "Left ramp", "shot", "Right ramp", "shot", "Big loop", "ms", 500]
    args = _monster_x(harness, prefix) + ["shot", "Building", "secs", 8]
    out = play_own(harness, dump, *args)
    assert "SID 125 555" in out
    assert "own sound: call phase1 (1076) played" in out
    assert "own sound: call phase2 (1190)" in out
    assert "own sound: call won (1247)" in out
    out = play_own(harness, dump, "trigger", "final_wars.light", "secs", 8, "shot", "Building", "secs", 27)
    assert "own sound: call lost (1129) played" in out


def test_anguirus_spike_roll_and_leave_calls(harness, dump):
    out = play_own(harness, dump, "battle", 1, "secs", 1, "shot", "Shield target left", "secs", 2,
                   "shot", "Shield target center", "secs", 2, "shot", "Shield target right", "secs", 1,
                   "shot", "Big loop", "secs", 2, "battle", 0, "secs", 1)
    assert "SID 125 357" in out and "CLIP PadMode_anguirus_assist_Clip" in out
    assert out.count("own sound: call spike (1197) played") == 3 and "PRIO 1197 3 0" in out
    assert "own sound: call roll (972) played" in out
    assert "own sound: call won (1281) played" in out
    out = play_own(harness, dump, "battle", 1, "secs", 2, "battle", 0, "secs", 1)
    assert "own sound: call lost (1259) played" in out


def test_a_repeating_call_still_sounding_is_skipped_not_cut(harness, dump):
    out = play_own(harness, dump, "battle", 1, "secs", 1, "shot", "Shield target left", "ms", 300,
                   "shot", "Shield target center", "secs", 2)
    assert "own sound: call spike (1197) skipped - its previous play still sounds" in out
    assert "STOP 1197" not in out


def test_a_call_played_again_while_it_still_sounds_starts_over(harness, dump):
    # two heads severed a second apart: the engine would not restart a request that still plays (the
    # showcase run's third sever was silent), so the first play is faded and the call plays again
    out = play_own(harness, dump, *POWERLINES, "secs", 1,
                   "shot", "Left ramp", "shot", "Right ramp", "shot", "Powerline left", "secs", 1,
                   "shot", "Building", "shot", "Powerline center", "shot", "Powerline right", "secs", 3)
    assert "own sound: call sever (1251) starts over - its previous play is faded out first" in out
    over = _at(out, "[KING GHIDORAH] own sound: call sever (1251) starts over")
    assert _at(out, "FADE 1251 30") == over
    again = re.findall(r"^\s*(\d+) SOUND 1251$", out, re.M)
    assert len(again) >= 2 and any(over < int(t) <= over + 150 for t in again)


def test_the_newest_event_speaks_over_the_modes_own_previous_call(harness, dump):
    # the roll comes a second after the third spike: the spike is the mode's own, so it is faded for
    # the roll (the showcase run dropped the roll after waiting on its own spike)
    out = play_own(harness, dump, "battle", 1, "secs", 1, "shot", "Shield target left", "secs", 2,
                   "shot", "Shield target center", "secs", 2, "shot", "Shield target right", "secs", 1,
                   "shot", "Big loop", "secs", 2, "battle", 0, "secs", 1)
    assert ("own sound: call roll (972) waits 70 ms - this mode's own call 1197 is faded out first "
            "(the newest event speaks)") in out
    assert "own sound: call roll (972) played (after waiting for the voice bus)" in out
    assert "NOT played" not in out


# ---- item 157: the playfield's INSERTS and the DISPLAY PRIORITY each mode sets --------------------------------
# The harness prints every insert held ("LAMP <name> <rrggbb> <pattern> <ms> <mode>"), handed back ("LAMP OFF"),
# the display priority ("DISPLAY <p> <mode>") and, last, how many inserts and which priority are still held.
PRO_PORT = SDK / "ports" / "godzilla_pro-1.15.port"


def _port_lamps(path):
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"lamp\s+[\d,]+\s+(?:0x[0-9a-fA-F]+|\d+)\s+(.+?)(?:\s+#.*)?$", line)
        if m:
            names.add(m.group(1).strip())
    return names


def test_every_insert_a_mode_names_is_in_both_godzilla_ports():
    kit = (EX / "intricate_kit.h").read_text(encoding="utf-8")
    named = set()
    for f in MODES:
        src = _src(f)
        named |= set(re.findall(r'kit_lamps_name\(&lamps, "([^"]+)"', src))
        named |= set(re.findall(r'#define \w+_INSERTS\w*\s+"([^"]+)"', src))
    names = {n.strip() for group in named for n in group.split(",")}
    assert names == {"MASER READY"}, names       # everything else is lit through its SHOT, on any port
    for port in (PREMIUM_PORT, PRO_PORT):
        assert names <= _port_lamps(port), (port.name, names - _port_lamps(port))
    assert "KIT_LAMP_PRIORITY 200" in kit


def test_each_mode_takes_its_display_priority_first_and_ends_on_the_tilt():
    for f in MODES:
        src = _src(f)
        assert ".event = on_event" in src and "kit_is_tilt(id)" in src, f
        assert "kit_lamps_off(&lamps)" in src, f
        if f == "anguirus_assist":
            continue                                  # it holds a priority only for its moments (below)
        start = src[src.index("static int start("):]
        begin = start.index("kit_begin(MODE_NAME)")
        disp = start.index("kit_display(")
        assert begin < disp < start.index("kit_screen_show(") and disp < start.index("sound(CUE_START)"), f
    assert "kit_display(KIT_DISPLAY_WIZARD)" in _src("final_wars")
    kit = (EX / "intricate_kit.h").read_text(encoding="utf-8")
    assert "#define KIT_DISPLAY_MODE    180" in kit and "#define KIT_DISPLAY_WIZARD  190" in kit
    assert kit.index("pm_display_priority(0)") < kit.index("    pm_end();")     # given up before pm_end


def _lamp(out, name, mode=None):
    """(ms, rgb, pattern, period) of every LAMP line for an insert"""
    rows = re.findall(r"^\s*(\d+) LAMP %s ([0-9a-f]{6}) (\w+) (\d+) (.+)$" % re.escape(name), out, re.M)
    return [(int(t), rgb, pat, int(ms)) for t, rgb, pat, ms, who in rows if mode is None or who == mode]


def _released(out, name):
    return [int(t) for t in re.findall(r"^\s*(\d+) LAMP OFF %s " % re.escape(name), out, re.M)]


def _all_back(out):
    return "END lamps held 0, display priority 0" in out


def test_ghidorah_lights_the_lit_heads_inserts_gold_with_its_health_and_the_regrowing_head_green(harness):
    out = play(harness, *POWERLINES, "secs", 1, "shot", "Left ramp", "secs", 8, "lamps", "secs", 5)
    g = "KING GHIDORAH"
    start = _at(out, "[KING GHIDORAH] START")
    assert _at(out, "DISPLAY 180 KING GHIDORAH") <= start
    assert (start, "ffaa00", "solid", 0) in _lamp(out, "LEFT RAMP", g)          # full health: solid gold
    assert (start, "ffaa00", "solid", 0) in _lamp(out, "POWERLINE LEFT", g)
    hit = _at(out, "[KING GHIDORAH] Left ramp: LEFT HEAD -2")
    assert (hit, "ffaa00", "blink", 180) in _lamp(out, "LEFT RAMP", g)          # 1 health: a fast blink
    moved = _at(out, "[KING GHIDORAH] the lit head moves: LEFT HEAD -> MIDDLE HEAD")
    assert (moved, "00ff3c", "pulse", 1200) in _lamp(out, "LEFT RAMP", g)        # wounded, left alone: green
    assert (moved, "ffaa00", "solid", 0) in _lamp(out, "BUILDING", g)
    assert (moved, "ffaa00", "solid", 0) in _lamp(out, "POWERLINE CENTER", g)
    assert re.search(r"HELD RIGHT RAMP", out) is None                          # a full head not lit: the game's
    assert has(out, g, "lights: shot 0x10100000 00ff3c pulse 1200; shot 0x20400000 ffaa00 solid")


def test_ghidorah_final_blow_flashes_the_maser_and_every_insert_goes_back_when_it_ends(harness):
    out = play(harness, *POWERLINES, "secs", 1,
               "shot", "Left ramp", "shot", "Powerline left", "secs", 1, "shot", "Building", "shot", "Powerline center",
               "secs", 1, "shot", "Right ramp", "shot", "Powerline right", "secs", 11, "shot", "Maser target", "secs", 2)
    final = _at(out, "[KING GHIDORAH] FINAL BLOW")
    for name in ("MASER", "MASER READY"):
        assert (final, "ffffff", "blink", 150) in _lamp(out, name)
        assert any(t > final for t, _c, p, ms in _lamp(out, name) if ms == 80)   # its last 5 s: faster
    for name in ("RIGHT RAMP", "POWERLINE RIGHT"):
        assert final in _released(out, name)                                     # the heads are gone
    end = _at(out, "[KING GHIDORAH] END (super jackpot)")
    assert end in _released(out, "MASER") and end in _released(out, "MASER READY")
    assert _at(out, "DISPLAY 0 KING GHIDORAH") == end and _all_back(out)


def test_oxygen_destroyer_collect_insert_blinks_faster_as_the_value_falls_then_the_super_flashes(harness):
    gt = ["shot", "Godzilla target", "ms", 400]
    out = play(harness, *gt, *gt, *gt, "secs", 23, "shot", "Left ramp", "secs", 10, "shot", "Right ramp", "secs", 1)
    o = "OXYGEN DESTROYER"
    start = _at(out, "[OXYGEN DESTROYER] START")
    assert _at(out, "DISPLAY 180 OXYGEN DESTROYER") <= start
    steps = [(c, p, ms) for _t, c, p, ms in _lamp(out, "LEFT RAMP", o)]
    assert steps[:4] == [("00ff3c", "blink", 700), ("ffc800", "blink", 400), ("ff0000", "blink", 200),
                         ("ff0000", "blink", 100)], steps                          # green, yellow, red, a flicker
    assert (start, "ffffff", "pulse", 1000) in _lamp(out, "MAGNA GRAB", o)        # a hold-off is left
    collected = _at(out, "[OXYGEN DESTROYER] COLLECTED")
    assert collected in _released(out, "LEFT RAMP") and collected in _released(out, "MAGNA GRAB")
    assert (collected, "ffffff", "blink", 150) in _lamp(out, "RIGHT RAMP", o)
    assert any(ms == 80 for _t, _c, _p, ms in _lamp(out, "RIGHT RAMP", o))        # its last 3 s
    assert _at(out, "[OXYGEN DESTROYER] END (super jackpot)") in _released(out, "RIGHT RAMP")
    assert _all_back(out)


def test_oxygen_destroyer_hold_off_insert_goes_out_when_none_are_left(harness):
    gt = ["shot", "Godzilla target", "ms", 400]
    out = play(harness, *gt, *gt, *gt, "secs", 1, *gt, *gt, *gt, "secs", 1)
    third = [int(t) for t in re.findall(r"^\s*(\d+) \[OXYGEN DESTROYER\] Godzilla target: hold-off 3 of 3", out, re.M)]
    assert third and any(third[0] <= t <= third[0] + 50 for t in _released(out, "MAGNA GRAB"))
    assert _lamp(out, "LEFT RAMP")                                                # still lit: collect it


def test_maser_barrage_lights_the_next_shot_bright_the_rest_dim_and_the_window_by_blink_speed(harness):
    out = play(harness, "event", "skill_shot", "secs", 1, "shot", "Left ramp", "secs", 7, "secs", 1)
    m = "MASER BARRAGE"
    start = _at(out, "[MASER BARRAGE] START")
    assert _at(out, "DISPLAY 180 MASER BARRAGE") <= start
    assert (start, "005aff", "solid", 0) in _lamp(out, "LEFT RAMP", m)            # next, no window yet
    assert (start, "001e5a", "solid", 0) in _lamp(out, "RIGHT RAMP", m)           # the rest of the chain, dim
    assert (start, "001e5a", "solid", 0) in _lamp(out, "BUILDING", m)
    step = _at(out, "[MASER BARRAGE] step 1 Left ramp")
    assert (step, "001e5a", "solid", 0) in _lamp(out, "LEFT RAMP", m)
    blinks = [(t - step, ms) for t, c, p, ms in _lamp(out, "RIGHT RAMP", m) if p == "blink"]
    assert [ms for _d, ms in blinks] == [500, 250, 100], blinks                    # the 7 s window closing
    assert 2700 <= blinks[1][0] <= 2900 and 4800 <= blinks[2][0] <= 5000
    broken = _at(out, "[MASER BARRAGE] CHAIN BROKEN")
    assert (broken, "005aff", "solid", 0) in _lamp(out, "LEFT RAMP", m)           # back to the start
    assert (broken, "001e5a", "solid", 0) in _lamp(out, "RIGHT RAMP", m)


def test_final_wars_lit_building_pulses_only_while_no_mode_of_ours_runs_and_not_between_balls(harness):
    out = play(harness, "trigger", "final_wars.light", "secs", 1, "trigger", "oxygen_destroyer.start", "secs", 1,
               "trigger", "oxygen_destroyer.stop", "secs", 1, "ball_end", "secs", 1, "event", "ball_start", "secs", 1)
    f = "FINAL WARS"
    lit = _at(out, "[FINAL WARS] FINAL WARS IS LIT")
    pulses = [t for t, c, p, ms in _lamp(out, "BUILDING", f) if (c, p, ms) == ("ffaa00", "pulse", 1000)]
    offs = _released(out, "BUILDING")
    oxy, oxy_end, ball_end = (_at(out, "[OXYGEN DESTROYER] START"), _at(out, "[OXYGEN DESTROYER] END"),
                              _at(out, ">> ball_end"))
    assert len(pulses) == 3 and lit <= pulses[0] < oxy                           # lit: the Building says so
    assert any(oxy <= t <= oxy + 20 for t in offs)                                # another mode runs: dark
    assert oxy_end <= pulses[1] <= oxy_end + 20                                   # back after it
    assert ball_end in offs and pulses[2] > _at(out, ">> event ball_start")       # dark between balls


def test_final_wars_lights_each_phases_shots_the_moving_target_and_the_wizard_shot(harness):
    prefix = ["trigger", "final_wars.light", "secs", 8, "shot", "Building", "secs", 1, "shot", "Left ramp", "secs", 1]
    out = play(harness, *prefix)
    f = "FINAL WARS"
    start = _at(out, "[FINAL WARS] START")
    assert _at(out, "DISPLAY 190 FINAL WARS") <= start
    for name in ("LEFT RAMP", "RIGHT RAMP", "BIG LOOP"):
        assert (start, "ff5000", "blink", 700) in _lamp(out, name, f)
    for name in ("SHIELD LEFT", "SHIELD CENTER", "SHIELD RIGHT"):
        assert (start, "00ff3c", "pulse", 1200) in _lamp(out, name, f)            # add time is left
    assert _at(out, "[FINAL WARS] phase 1: Left ramp") in _released(out, "LEFT RAMP")   # saved: the game's
    args = _monster_x(harness, prefix + ["shot", "Right ramp", "shot", "Big loop", "ms", 500])
    out = play(harness, *args, "secs", 1)
    targets = {"Powerline left": "POWERLINE LEFT", "Powerline center": "POWERLINE CENTER",
               "Powerline right": "POWERLINE RIGHT", "Godzilla target": "MAGNA GRAB"}
    for t, where in re.findall(r"^\s*(\d+) \[FINAL WARS\] (?:PHASE 2 .*lit|phase 2: MONSTER X moves.*->) (.+)$", out, re.M):
        assert (int(t), "aa00ff", "blink", 150) in _lamp(out, targets[where], f), (t, where)
    p3 = _at(out, "[FINAL WARS] PHASE 3")
    assert any(t == p3 and c == "ffaa00" and p == "blink" for t, c, p, ms in _lamp(out, "BUILDING", f))


def test_anguirus_lights_the_shields_as_a_charge_meter_and_the_big_loop_for_the_roll(harness):
    out = play(harness, "battle", 1, "secs", 1, "shot", "Shield target left", "secs", 1,
               "shot", "Shield target center", "shot", "Shield target right", "secs", 3, "battle", 0, "secs", 1)
    a = "ANGUIRUS"
    start = _at(out, "[ANGUIRUS] START")
    for name in ("SHIELD LEFT", "SHIELD CENTER", "SHIELD RIGHT"):
        assert (start, "ff5000", "blink", 400) in _lamp(out, name, a)             # still to charge
    left = _at(out, "[ANGUIRUS] spike charged at Shield target left")
    assert (left, "ff5000", "solid", 0) in _lamp(out, "SHIELD LEFT", a)           # charged
    lit = _at(out, "[ANGUIRUS] ROLL LIT")
    assert (lit, "00e6ff", "blink", 400) in _lamp(out, "BIG LOOP", a)
    assert any(ms == 200 for _t, _c, _p, ms in _lamp(out, "BIG LOOP", a))         # the roll window closing
    over = _at(out, "[ANGUIRUS] END (the game's battle ended)")
    for name in ("SHIELD LEFT", "SHIELD CENTER", "SHIELD RIGHT", "BIG LOOP"):
        assert over in _released(out, name)                                       # at once, with the battle


def test_anguirus_yields_the_screen_to_the_battle_and_speaks_in_moments(harness, dump):
    out = play_own(harness, dump, "battle", 1, "covered", 1, "secs", 4, "covered", 0, "secs", 13,
                   "shot", "Shield target left", "secs", 4, "battle", 0, "covered", 1, "secs", 3, "covered", 0, "secs", 5)
    start = _at(out, "[ANGUIRUS] START")
    assert _at(out, "DISPLAY 180 ANGUIRUS") == start                               # held at once, to see the battle
    entrance = _at(out, "[ANGUIRUS] ENTRANCE")
    uncovered = _at(out, ">> covered 0")
    assert uncovered + 1000 <= entrance <= uncovered + 1100                        # its start screen over, then 1 s
    assert _at(out, "CLIP PadMode_anguirus_assist_Clip") >= entrance              # its clip waited for that
    assert _at(out, "SID 125 357") == entrance                                     # and so did its music
    back = [int(t) for t in re.findall(r"^\s*(\d+) DISPLAY 0 ANGUIRUS", out, re.M)]
    assert back[0] == entrance + 11500 or abs(back[0] - entrance - 11500) <= 20    # clip + 3 s of panel, then yields
    spike = _at(out, "[ANGUIRUS] spike charged at Shield target left")
    again = [int(t) for t in re.findall(r"^\s*(\d+) DISPLAY 180 ANGUIRUS", out, re.M)]
    assert spike in again and any(abs(t - spike - 3000) <= 20 for t in back)      # a 3 s moment
    ended = _at(out, "[ANGUIRUS] END (the game's battle ended)")
    shown = _at(out, "[ANGUIRUS] the total was shown")
    uncovered = [int(t) for t in re.findall(r"^\s*(\d+) >> covered 0", out, re.M)][-1]
    assert ended < uncovered and uncovered + 3950 <= shown <= uncovered + 4050     # after the battle's own total
    assert _all_back(out)


def test_anguirus_total_gives_way_when_another_mode_of_ours_asks_to_start(harness):
    out = play(harness, "battle", 1, "secs", 1, "battle", 0, "secs", 1, "covered", 1, *POWERLINES, "secs", 1,
               "covered", 0, "shot", "Powerline left", "secs", 1)
    assert has(out, "ANGUIRUS", "KING GHIDORAH asked to start: the total gives way")
    assert has(out, "KING GHIDORAH", "START (three powerlines)")                   # its next start shot
    assert _at(out, "[ANGUIRUS] the total was shown") < _at(out, "[KING GHIDORAH] START")


@pytest.mark.parametrize("start,mode", [
    (POWERLINES, "KING GHIDORAH"),
    (["shot", "Godzilla target", "ms", 400] * 3, "OXYGEN DESTROYER"),
    (["event", "skill_shot"], "MASER BARRAGE"),
    (["trigger", "final_wars.light", "secs", 8, "shot", "Building"], "FINAL WARS"),
    (["battle", 1], "ANGUIRUS"),
])
@pytest.mark.parametrize("ending", ["ball_end", "tilt"])
def test_a_drain_or_a_tilt_hands_every_insert_and_the_display_back_at_once(harness, start, mode, ending):
    end_cmd = ["ball_end"] if ending == "ball_end" else ["event", "tilt"]
    out = play(harness, *start, "secs", 2, *end_cmd, "ms", 20)
    why = "ball ended" if ending == "ball_end" else "tilted"
    t = _at(out, "[%s] END (%s)" % (mode, why))
    assert t is not None, out[-1500:]
    assert _at(out, "[%s] lights: all handed back to the game" % mode) == t
    assert "END lamps held 0" in out                                                # nothing left lit
    assert re.search(r"^\s*%d DISPLAY (0 %s|released %s)" % (t, re.escape(mode), re.escape(mode)), out, re.M) \
        or "display priority 0" in out.splitlines()[-1]
