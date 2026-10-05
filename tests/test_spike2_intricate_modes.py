"""Item 152: the INTRICATE example modes (tools/spike2_emu/modes/sdk/examples/), MELTDOWN (hud-layers), and the
five Lyman Sheats modes (PAD-379: GODZILLA ANGRY, SPACEGODZILLA, KIRYU, BIOLLANTE, DESTOROYAH).

Three layers, each skipping cleanly where its tools are missing:

- Static checks, everywhere: every mode file registers one mode, drives a HUD named after its own
  folder (no centre panel any more), uses only shots the Godzilla Premium 1.16 port names and only
  calls pad_mode.h declares, and its words (HUD texts, the README) carry no em or en dashes.
- The ARM build (build_mode.sh), where arm-linux-gnueabihf-gcc and bash are: each mode alone, and
  all six together with mode_file.c, the way the card carries them.
- The desk harness (examples/desk_harness.c), where an ELF host C compiler is: every mode played
  through its start, its phases, its success path and its failure paths against a fake game. What a
  mode shows is read off the harness's WORDS lines for its HUD texts (PadMode_<folder>_Hud_Title,
  _Line, _Award, _AwardSub, _C1.._C3 _Label/_Value/_Sub, _Timer_Num, _Gauge_Label).
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

SDK = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk"
EX = SDK / "examples"
MODES = ["ghidorah_heads", "oxygen_destroyer", "maser_barrage", "final_wars", "anguirus_assist", "meltdown",
         "godzilla_angry", "spacegodzilla", "kiryu", "biollante", "destoroyah"]
NAMES = {"ghidorah_heads": "KING GHIDORAH", "oxygen_destroyer": "OXYGEN DESTROYER",
         "maser_barrage": "MASER BARRAGE", "final_wars": "FINAL WARS", "anguirus_assist": "ANGUIRUS",
         "meltdown": "MELTDOWN", "godzilla_angry": "GODZILLA ANGRY", "spacegodzilla": "SPACEGODZILLA",
         "kiryu": "KIRYU", "biollante": "BIOLLANTE", "destoroyah": "DESTOROYAH"}
#: PAD-379: the five modes after Lyman Sheats' rule sets
LYMAN = ["godzilla_angry", "spacegodzilla", "kiryu", "biollante", "destoroyah"]
PREMIUM_PORT = SDK / "ports" / "godzilla_le-1.16.port"


def _src(slug):
    return (EX / (slug + ".c")).read_text(encoding="utf-8")


def _port_shots(path):
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"(?:shot|switch\s+\d+)\s+0x[0-9a-fA-F]+\s+(.+?)\s*$", line)
        if m:
            out.add(m.group(1))
    return out


def commas(v):
    return "{:,}".format(v)


def kit_short(v):
    """intricate_kit.h's kit_short: a value that fits a HUD counter (950,000 / 4.25M / 42.5M / 425M)"""
    if v < 1000000:
        return commas(v)
    if v < 10000000:
        return "%d.%02dM" % (v // 1000000, v % 1000000 // 10000)
    if v < 100000000:
        return "%d.%dM" % (v // 1000000, v % 1000000 // 100000)
    return "%dM" % (v // 1000000)


# ---- static checks (every platform) -----------------------------------------------------------
@pytest.mark.parametrize("slug", MODES)
def test_each_mode_registers_one_mode_named_for_its_folder(slug):
    src = _src(slug)
    assert len(re.findall(r"^PM_REGISTER\(", src, re.M)) == 1
    assert '#define FOLDER             "%s"' % slug in src
    assert '#define MODE_NAME          "%s"' % NAMES[slug] in src
    assert ".name = MODE_NAME," in src
    # hud-layers: the HUD at the glass's edges is found by the mode's folder (PadMode_<folder>_Hud)
    assert "static struct kit_hud hud = { .slug = FOLDER };" in src
    assert "kit_hud_tick(&hud);" in src
    # no centre panel any more
    assert "kit_screen" not in src and "_Screen" not in src


@pytest.mark.parametrize("slug", MODES)
def test_every_shot_a_mode_names_is_in_the_premium_port(slug):
    shots = _port_shots(PREMIUM_PORT)
    named = set(re.findall(r'"((?:Left|Right) ramp|Building|Godzilla target|Maser target|Powerline \w+|'
                           r'Shield target \w+|Big loop|Skill shot|Left spinner|Top spinner|Shield ramp spinner|'
                           r'Pop bumper|Action button)"', _src(slug)))
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


def test_all_the_modes_build_into_one_object_with_mode_file_c(tmp_path):
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
        for name in ("kit_ledger", "kit_running", "kit_hud_up", "pa_music"):
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


def _harness_source():
    """desk_harness.c, checked for the two things the six HUD modes need from the fake game: room in its
    fake scene (one mode's HUD asks for about 42 nodes: the group, 4 texts, the badge, 9 counter texts, the
    gauge and 12 pips' two pictures) and the Premium port's Left spinner (0x200), which OXYGEN DESTROYER
    starts on. A harness without them shows up here rather than as a mode that silently shows nothing."""
    src = (EX / "desk_harness.c").read_text(encoding="utf-8")
    cap = re.search(r"static struct fake_node nodes\[(\d+)\];", src)
    assert cap and int(cap.group(1)) >= len(MODES) * 42, "desk_harness.c: the fake scene cannot hold every HUD"
    assert '{ "Left spinner", 0x200ull }' in src
    return src


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    cc = _cc()
    d = tmp_path_factory.mktemp("intricate")
    exe = d / "harness"
    (d / "desk_harness.c").write_text(_harness_source(), encoding="utf-8")
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wextra", "-Wno-unused-parameter", "-I", str(SDK), "-o", str(exe),
                        str(d / "desk_harness.c")] + [str(EX / (s + ".c")) for s in MODES],
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


def hud(out, slug, field):
    """(ms, words) of every write to one of the mode's HUD texts: Title, Line, Award, AwardSub,
    C1_Label .. C3_Sub, Timer_Num, Gauge_Label. A text is hidden by writing a space."""
    return [(int(t), w) for t, w in
            re.findall(r"^\s*(\d+) WORDS PadMode_%s_Hud_%s: (.*)$" % (re.escape(slug), field), out, re.M)]


def hud_said(out, slug, field, words):
    return any(w == words for _t, w in hud(out, slug, field))


def hud_at(out, slug, field, words):
    """ms of the first time the HUD text showed `words`, or None"""
    for t, w in hud(out, slug, field):
        if w == words:
            return t
    return None


def _soon(ms, t):
    """`ms` is a tick or two after `t`: a HUD text is written at the start of the mode's next tick, and a
    counter the mode recomputes in that tick's own update shows one tick later (33 ms)"""
    return ms is not None and t <= ms <= t + 40


def hud_next(out, slug, field, t):
    """what the HUD text showed on the tick after `t`, or None when it was not written then"""
    for ms, w in hud(out, slug, field):
        if ms >= t:
            return w if _soon(ms, t) else None
    return None


def _at(out, text):
    m = re.search(r"^\s*(\d+) %s" % re.escape(text), out, re.M)
    return int(m.group(1)) if m else None


def _hid(out, slug):
    """ms of every time the mode's whole HUD group was hidden"""
    return [int(t) for t in re.findall(r"^\s*(\d+) SHOW PadMode_%s_Hud 0$" % re.escape(slug), out, re.M)]


POWERLINES = ["shot", "Powerline left", "shot", "Powerline center", "shot", "Powerline right"]
#: PAD-371: MASER BARRAGE starts on the Maser target x3 in one ball (no longer on the skill shot)
MASER3 = ["shot", "Maser target", "ms", 300, "shot", "Maser target", "ms", 300, "shot", "Maser target"]
SPINS = ["shot", "Left spinner"] * 25                # OXYGEN DESTROYER: 25 spins of the Left spinner
GT = ["shot", "Godzilla target", "ms", 300]          # the captive ball, past the 250 ms debounce
MELTDOWN_START = GT * 11                             # 10 make MELTDOWN ready, the 11th starts it


def test_ghidorah_is_won_head_by_head_and_the_maser_lands_the_super_jackpot(harness):
    out = play(harness, *POWERLINES, "secs", 1,
               "shot", "Left ramp", "shot", "Right ramp", "shot", "Powerline left", "secs", 1,
               "shot", "Building", "shot", "Powerline center", "secs", 1,
               "shot", "Right ramp", "shot", "Powerline right", "secs", 2, "shot", "Maser target", "secs", 11)
    g, s = "KING GHIDORAH", "ghidorah_heads"
    assert has(out, g, "START (three powerlines)")
    assert has(out, g, "Left ramp: LEFT HEAD -2 (health 1) +2000000")
    assert has(out, g, "Right ramp: glancing blow on RIGHT HEAD (lit: LEFT HEAD) +250000")
    assert has(out, g, "LEFT HEAD SEVERED (1 of 3): +5000000, +10 s on the clock")
    assert has(out, g, "MIDDLE HEAD SEVERED (2 of 3): +10000000, +10 s on the clock")
    assert has(out, g, "RIGHT HEAD SEVERED (3 of 3): +15000000")
    assert has(out, g, "FINAL BLOW: Maser target lit for 15 s")
    assert has(out, g, "SUPER JACKPOT: Maser target with 13 s left, +33000000")
    assert has(out, g, "END (super jackpot): WON, 3 of 3 heads severed")
    total = 2000000 + 250000 + 1000000 + 5000000 + 3000000 + 10000000 + 3000000 + 15000000 + 33000000
    assert end_total(out, g) == scored(out, "", g) == total
    # the HUD: the heads' health across the top, the lit one marked, what to shoot above the score panel
    assert hud_said(out, s, "Title", "KING GHIDORAH") and hud_said(out, s, "Line", "SHOOT THE LEFT HEAD")
    assert hud_said(out, s, "C1_Label", "LEFT HEAD") and hud_said(out, s, "C3_Label", "RIGHT HEAD")
    assert hud_said(out, s, "C1_Sub", ">> LIT <<") and hud_said(out, s, "C1_Value", "1")
    assert hud_said(out, s, "Award", "LEFT HEAD SEVERED") and hud_said(out, s, "AwardSub", "5,000,000   +10 SECONDS")
    assert hud_said(out, s, "C1_Value", "X") and hud_said(out, s, "C1_Sub", "SEVERED")
    assert hud_said(out, s, "Line", "SHOOT THE MIDDLE HEAD") and hud_said(out, s, "Timer_Num", "59")   # +10 s
    assert hud_said(out, s, "Line", "FINAL BLOW: SHOOT THE MASER") and hud_said(out, s, "C2_Value", "35.0M")
    # the total: the title says who won, the award line the total, 10 s, then the HUD goes
    end = _at(out, "[KING GHIDORAH] END")
    assert hud_next(out, s, "Title", end) == "GHIDORAH DEFEATED"
    assert _soon(hud_at(out, s, "Award", commas(total)), end)
    assert hud_said(out, s, "AwardSub", "KING GHIDORAH TOTAL")
    assert any(end + 9950 <= t <= end + 10050 for t in _hid(out, s))


def test_ghidorah_regrows_a_head_left_alone_turns_and_escapes_on_time(harness):
    out = play(harness, *POWERLINES, "secs", 1, "shot", "Left ramp", "secs", 12, "secs", 60)
    g, s = "KING GHIDORAH", "ghidorah_heads"
    assert has(out, g, "the lit head moves: LEFT HEAD -> MIDDLE HEAD")
    assert has(out, g, "LEFT HEAD REGROWS: health 2")
    assert has(out, g, "END (time ran out): not won, 0 of 3 heads severed")
    assert "CALLOUT 1295" in out
    moved = _at(out, "[KING GHIDORAH] the lit head moves: LEFT HEAD -> MIDDLE HEAD")
    assert hud_next(out, s, "Line", moved) == "SHOOT THE MIDDLE HEAD"
    assert hud_said(out, s, "Award", "LEFT HEAD REGROWS")
    assert hud_said(out, s, "Title", "GHIDORAH ESCAPES")


def test_ghidorah_final_blow_missed_is_an_escape(harness):
    out = play(harness, *POWERLINES, "secs", 1,
               "shot", "Left ramp", "shot", "Powerline left", "secs", 1, "shot", "Building", "shot", "Powerline center",
               "secs", 1, "shot", "Right ramp", "shot", "Powerline right", "secs", 17)
    assert has(out, "KING GHIDORAH", "END (the final blow was not made): not won, 3 of 3 heads severed")
    assert hud_said(out, "ghidorah_heads", "Title", "GHIDORAH ESCAPES")


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


def test_ghidorah_counts_the_powerlines_on_its_hud_until_it_starts(harness):
    out = play(harness, "shot", "Powerline left", "secs", 1, "shot", "Powerline right", "secs", 3)
    s = "ghidorah_heads"
    first = _at(out, "[KING GHIDORAH] powerlines 1 of 3")
    assert _soon(hud_at(out, s, "Award", "POWERLINES 1 OF 3"), first)
    assert hud_said(out, s, "Award", "POWERLINES 2 OF 3") and hud_said(out, s, "AwardSub", "KING GHIDORAH")
    second = _at(out, "[KING GHIDORAH] powerlines 2 of 3")
    assert any(second + 1950 <= t <= second + 2050 for t in _hid(out, s))    # a note, then hidden again
    assert not has(out, "KING GHIDORAH", "START")


def test_a_target_hit_twelve_times_in_a_second_pays_at_most_four_times(harness):
    rapid = []
    for _ in range(12):
        rapid += ["raw", "0x1", "raw", "0x100000", "ms", 83]          # Left ramp, 12 times in 1 s
    out = play(harness, *MASER3, "secs", 1, *rapid, "secs", 1)
    steps = [ln for ln in lines(out, "MASER BARRAGE") if "step 1 Left ramp" in ln]
    assert len(steps) == 1                                            # counted once; the rest out of order
    assert len([ln for ln in lines(out, "MASER BARRAGE") if "counted once" in ln]) >= 8
    out = play(harness, *POWERLINES, "secs", 1, *rapid, "secs", 1)
    hits = [ln for ln in lines(out, "KING GHIDORAH") if "Left ramp: LEFT HEAD" in ln]
    assert 1 <= len(hits) <= 4
    assert scored(out, "", "KING GHIDORAH") <= 4 * 2000000 + 5000000


def test_oxygen_destroyer_starts_on_25_left_spinner_spins_and_not_on_the_godzilla_target(harness):
    o, s = "OXYGEN DESTROYER", "oxygen_destroyer"
    out = play(harness, *SPINS[:48], "secs", 1, *GT, *GT, *GT, "secs", 1, "shot", "Left spinner", "secs", 1)
    assert has(out, o, "Left spinner 5 of 25 (player 1)") and has(out, o, "Left spinner 20 of 25 (player 1)")
    assert hud_said(out, s, "Award", "24 SPINS TO GO") and hud_said(out, s, "Award", "1 SPIN TO GO")
    assert hud_said(out, s, "AwardSub", "OXYGEN DESTROYER")
    starts = [int(t) for t in re.findall(r"^\s*(\d+) \[OXYGEN DESTROYER\] START", out, re.M)]
    gts = [int(t) for t in re.findall(r"^\s*(\d+) >> shot Godzilla target", out, re.M)]
    spins = [int(t) for t in re.findall(r"^\s*(\d+) >> shot Left spinner", out, re.M)]
    assert len(starts) == 1 and len(spins) == 25
    assert starts[0] == spins[-1] > max(gts)                  # three captive ball hits did not start it
    assert has(out, o, "Left spinner 25 of 25 (player 1)") and has(out, o, "START (the left spinner)")
    # a spinner shot is many spins at once: every dispatch counts, no debounce
    out = play(harness, *(["raw", "0x200"] * 25), "ms", 50)
    assert has(out, o, "Left spinner 25 of 25") and has(out, o, "START (the left spinner)")
    assert "counted once" not in out


def test_oxygen_destroyer_collects_holds_off_and_delivers_double(harness):
    out = play(harness, *SPINS, "secs", 5, *GT, "secs", 2, "shot", "Left ramp", "secs", 3,
               "shot", "Right ramp", "secs", 11)
    o, s = "OXYGEN DESTROYER", "oxygen_destroyer"
    assert has(out, o, "Left spinner 25 of 25 (player 1)")
    assert has(out, o, "START (the left spinner)")
    assert has(out, o, "Godzilla target: hold-off 1 of 3, the value is back to")
    m = re.search(r"COLLECTED at Left ramp: (\d+) \(asked (\d+)\)", out)
    collected = int(m.group(1))
    assert 13000000 < collected < 16500000
    assert has(out, o, "SUPER JACKPOT at Right ramp: +%d" % (2 * collected))
    assert has(out, o, "END (super jackpot): WON, collected %d, total %d" % (collected, 3 * collected))
    # the HUD: the falling value as the big counter, then the super jackpot, then the total
    assert hud_said(out, s, "Title", "OXYGEN DESTROYER") and hud_said(out, s, "C2_Label", "HURRY-UP")
    assert hud_said(out, s, "C2_Sub", "3 HOLD-OFFS LEFT") and hud_said(out, s, "C2_Sub", "2 HOLD-OFFS LEFT")
    assert hud_said(out, s, "Award", "HELD OFF") and hud_said(out, s, "Gauge_Label", "OXYGEN")
    assert hud_said(out, s, "Award", "COLLECTED")
    assert hud_said(out, s, "AwardSub", "SUPER %s AT THE RIGHT RAMP" % commas(2 * collected))
    assert hud_said(out, s, "Line", "SUPER JACKPOT: SHOOT THE RIGHT RAMP")
    assert hud_said(out, s, "C1_Value", kit_short(collected)) and hud_said(out, s, "C2_Value", kit_short(2 * collected))
    assert hud_said(out, s, "Title", "GODZILLA IS GONE") and hud_said(out, s, "Award", commas(3 * collected))
    assert hud_said(out, s, "AwardSub", "OXYGEN DESTROYER TOTAL")


def test_oxygen_destroyer_is_lost_when_the_value_runs_out_and_cools_down(harness):
    out = play(harness, *SPINS, "secs", 26, *SPINS[:4])
    o, s = "OXYGEN DESTROYER", "oxygen_destroyer"
    assert has(out, o, "END (the value ran out before it was collected): not won, collected 0, total 0")
    assert "CALLOUT 1291" in out and "CALLOUT 1287 0" in out and "CALLOUT 1295" in out
    assert has(out, o, "Left spinner: not counted - cooling down")
    end = _at(out, "[OXYGEN DESTROYER] END")
    assert hud_next(out, s, "Title", end) == "THE OXYGEN IS GONE"
    assert _soon(hud_at(out, s, "Award", "0"), end)


def test_oxygen_destroyer_super_jackpot_missed_keeps_what_was_collected(harness):
    out = play(harness, *SPINS, "secs", 1, "shot", "Left ramp", "secs", 13)
    collected = int(re.search(r"COLLECTED at Left ramp: (\d+)", out).group(1))
    assert has(out, "OXYGEN DESTROYER", "END (the super jackpot ran out): not won, collected %d, total %d"
               % (collected, collected))
    s = "oxygen_destroyer"
    assert hud_said(out, s, "Title", "OXYGEN DESTROYER") and hud_said(out, s, "Award", commas(collected))


def test_maser_barrage_starts_at_the_maser_target_and_its_chain_breaks(harness):
    out = play(harness, *MASER3, "secs", 1,
               "shot", "Right ramp", "shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 1, "shot", "Building",
               "secs", 1, "shot", "Left ramp", "secs", 7,
               "shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 1, "shot", "Building", "secs", 50)
    b, s = "MASER BARRAGE", "maser_barrage"
    assert has(out, b, "START (Maser target)")
    assert has(out, b, "Right ramp: out of order (next is Left ramp) - no effect")
    assert has(out, b, "BARRAGE 1: jackpot +5000000 (x1); multiplier -> x2")
    assert has(out, b, "step 1 Left ramp: +2000000 (x2)")
    assert has(out, b, "CHAIN BROKEN: no Right ramp within 6000 ms (was x2)")
    assert has(out, b, "BARRAGE 2: jackpot +5000000 (x1)")
    assert has(out, b, "END (time ran out): 2 barrage(s), best x2, 1 chain(s) broken")
    # the HUD: the next shot above the score panel, the multiplier, the window, the barrages
    assert hud_said(out, s, "Line", "SHOOT THE LEFT RAMP") and hud_said(out, s, "Line", "SHOOT THE BUILDING")
    assert hud_said(out, s, "C1_Value", "X1") and hud_said(out, s, "C1_Value", "X2")
    assert hud_said(out, s, "C1_Sub", "JACKPOT 10M")
    assert hud_said(out, s, "C2_Label", "WINDOW") and hud_said(out, s, "C2_Sub", "NO CLOCK YET")
    assert hud_said(out, s, "Award", "BARRAGE JACKPOT") and hud_said(out, s, "AwardSub", "5,000,000   NOW X2")
    assert hud_said(out, s, "Award", "CHAIN BROKEN") and hud_said(out, s, "C3_Sub", "CHAIN BROKEN")
    assert hud_said(out, s, "Title", "MASER BARRAGE TOTAL") and hud_said(out, s, "Line", "2 BARRAGES  -  BEST X2")
    assert hud_said(out, s, "Award", commas(end_total(out, b)))


def test_maser_barrage_starts_on_the_maser_target_never_on_the_skill_shot(harness):
    """PAD-371 (David): "I want the maser [barrage] not to start on skillshots"."""
    out = play(harness, "event", "skill_shot", "secs", 2)
    assert "[MASER BARRAGE] START" not in out and "skill shot held" not in out
    out = play(harness, "shot", "Maser target", "ms", 300, "shot", "Maser target", "ms", 300, "shot", "Maser target",
               "secs", 1)
    assert has(out, "MASER BARRAGE", "START (Maser target)")
    assert hud_said(out, "maser_barrage", "Award", "MASER 1 OF 3") and hud_said(out, "maser_barrage", "Award", "MASER 2 OF 3")


def test_a_step_that_counts_puts_a_short_clock_back_to_ten_seconds(harness):
    """PAD-371 (David): "when you make one of the shots the timer if it is currently less than 10 seconds it should
    reset back to 10 seconds" - a step in order does; an out-of-order shot does nothing, as before."""
    out = play(harness, *MASER3, "secs", 33, "shot", "Right ramp", "secs", 1, "shot", "Left ramp", "secs", 12)
    b = "MASER BARRAGE"
    assert has(out, b, "Right ramp: out of order (next is Left ramp) - no effect")
    assert has(out, b, "step 1 Left ramp") and has(out, b, "clock back to 10 s")
    start, top, end = (out.index(t) for t in ("[MASER BARRAGE] START", "clock back to 10 s", "[MASER BARRAGE] END (time ran out)"))
    assert start < top < end
    # without the step the clock would have run out at 40 s; with it, the mode is still up at 40 s
    assert "END (time ran out)" not in play(harness, *MASER3, "secs", 33, "shot", "Left ramp", "secs", 8)
    assert "clock back" not in play(harness, *MASER3, "secs", 2, "shot", "Left ramp", "secs", 1)   # 38 s left: no change


def test_final_wars_lights_from_the_other_three_and_is_played_phase_by_phase(harness):
    # MASER BARRAGE's total is on the HUD for 10 s after its stop: FINAL WARS IS LIT shows after it
    out = play(harness, "shot", "Building", "secs", 1,
               *POWERLINES, "secs", 1, "trigger", "ghidorah_heads.stop", "secs", 1,
               "trigger", "oxygen_destroyer.start", "trigger", "oxygen_destroyer.stop", "secs", 1,
               *MASER3, "secs", 1, "trigger", "maser_barrage.stop", "secs", 11,
               "shot", "Building", "secs", 1,
               "shot", "Left ramp", "shot", "Shield target left", "secs", 1, "shot", "Right ramp", "shot", "Big loop",
               "secs", 1)
    f, s = "FINAL WARS", "final_wars"
    assert out.index("FINAL WARS IS LIT") < out.index("[FINAL WARS] START")
    assert has(out, f, "FINAL WARS IS LIT for player 1 (3 of 3 played, 0 won)")
    note = hud_at(out, s, "Award", "FINAL WARS IS LIT")
    assert note and note < _at(out, "[FINAL WARS] START") and hud_said(out, s, "AwardSub", "SHOOT THE BUILDING")
    assert has(out, f, "START (Building): player 1")
    assert has(out, f, "PHASE 1 (INVASION): 25 s")
    assert has(out, f, "ADD TIME: Shield target left +3 s (1 of 3 this phase)")
    assert has(out, f, "phase 1: Big loop +3000000, 0 left")
    lit = re.findall(r"PHASE 2 \(MONSTER X\): 25 s, lit (.+)$", out, re.M)
    assert lit
    # the HUD: the phase, the cities still to save, the add-time; then MONSTER X
    assert hud_said(out, s, "Title", "GODZILLA: FINAL WARS")
    assert hud_said(out, s, "C1_Value", "1") and hud_said(out, s, "C1_Sub", "INVASION")
    assert hud_said(out, s, "Line", "SAVE  LEFT RAMP  RIGHT RAMP  BIG LOOP")
    assert hud_said(out, s, "Line", "SAVE  RIGHT RAMP  BIG LOOP")
    assert hud_said(out, s, "C3_Value", "3") and hud_said(out, s, "C3_Value", "2")        # an add-time used
    assert hud_said(out, s, "Award", "PHASE 2: MONSTER X") and hud_said(out, s, "C1_Sub", "MONSTER X")
    says = {"Powerline left": "POWERLINE L", "Powerline center": "POWERLINE C", "Powerline right": "POWERLINE R",
            "Godzilla target": "GODZILLA"}
    assert hud_said(out, s, "Line", "HIT MONSTER X AT %s" % says[lit[0]])


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
    f, s = "FINAL WARS", "final_wars"
    assert has(out, f, "phase 2: MONSTER X hit at") and has(out, f, "3 of 3, +15000000")
    assert has(out, f, "PHASE 3 (GHIDORAH): 20 s")
    assert has(out, f, "WIZARD JACKPOT: Building with")
    assert has(out, f, "END (wizard jackpot): WON in phase 3")
    assert hud_said(out, s, "C2_Value", "1/3") and hud_said(out, s, "C2_Value", "2/3")
    assert hud_said(out, s, "C1_Value", "3") and hud_said(out, s, "Line", "WIZARD SHOT: THE BUILDING")
    assert hud_said(out, s, "Title", "GODZILLA WINS") and hud_said(out, s, "AwardSub", "FINAL WARS TOTAL")
    assert hud_said(out, s, "Award", commas(end_total(out, f)))


def test_final_wars_waits_for_the_games_multiball_and_a_phase_clock_ends_it(harness):
    out = play(harness, "trigger", "final_wars.light", "secs", 8, "multiball", 1, "shot", "Building", "secs", 1,
               "multiball", 0, "shot", "Building", "secs", 27)
    f = "FINAL WARS"
    assert has(out, f, "not started (Building): a multiball is running - still lit")
    assert has(out, f, "END (a phase's clock ran out): not won in phase 1")
    assert hud_said(out, "final_wars", "Title", "THE XILIENS WIN")


def test_final_wars_lights_when_two_are_won(harness):
    out = play(harness, *SPINS, "secs", 1, "shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 8,
               *MASER3, "secs", 1, "shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 1,
               "shot", "Building", "secs", 1, "trigger", "maser_barrage.stop", "secs", 2)
    assert has(out, "OXYGEN DESTROYER", "END (super jackpot): WON")
    assert has(out, "MASER BARRAGE", "END (trigger file): 1 barrage(s)")
    assert has(out, "FINAL WARS", "FINAL WARS IS LIT for player 1 (2 of 3 played, 2 won)")


def test_anguirus_joins_the_games_battle_charges_rolls_and_leaves_with_it(harness):
    out = play(harness, "battle", 1, "secs", 1, "shot", "Shield target left", "shot", "Shield target left",
               "secs", 1, "shot", "Shield target center", "shot", "Shield target right", "secs", 1,
               "shot", "Big loop", "secs", 2, "shot", "Big loop", "secs", 2, "shot", "Big loop", "secs", 7,
               "battle", 0, "secs", 1)
    a, s = "ANGUIRUS", "anguirus_assist"
    assert has(out, a, "START (the game's battle began)")
    assert has(out, a, "Shield target left: that spike is already charged") or has(out, a, "counted once")
    assert has(out, a, "ROLL LIT: Big loop for 4000000")
    assert has(out, a, "ROLLING ATTACK 1 at Big loop: +4000000")
    assert has(out, a, "ROLLING ATTACK 2 at Big loop: +8000000")
    assert has(out, a, "ROLLING ATTACK 3 at Big loop: +16000000")
    assert has(out, a, "the roll is over")
    assert has(out, a, "END (the game's battle ended): 3 charge(s), 3 rolling attack(s), total 29500000")
    # the battle keeps its own title and line: ANGUIRUS writes only a space there, its gauge and its moments
    assert {w for _t, w in hud(out, s, "Title")} == {" "} and {w for _t, w in hud(out, s, "Line")} == {" "}
    assert hud_said(out, s, "Gauge_Label", "SPIKES") and hud_said(out, s, "Gauge_Label", "ROLLING!")
    assert hud_said(out, s, "Award", "ANGUIRUS JOINS") and hud_said(out, s, "Award", "ROLLING ATTACK LIT")
    assert hud_said(out, s, "Award", "ROLLING ATTACK 3") and hud_said(out, s, "AwardSub", "16,000,000")
    assert hud_said(out, s, "Award", "29,500,000") and hud_said(out, s, "AwardSub", "ANGUIRUS TOTAL")


def test_one_pack_mode_at_a_time_and_a_new_hud_replaces_the_last_total(harness):
    out = play(harness, *POWERLINES, "secs", 1, *SPINS, "trigger", "ghidorah_heads.stop", "ms", 500,
               "shot", "Left spinner")
    assert has(out, "OXYGEN DESTROYER", "not started: KING GHIDORAH is running")
    assert has(out, "OXYGEN DESTROYER", "START (the left spinner)")
    end = _at(out, "[KING GHIDORAH] END")
    start = _at(out, "[OXYGEN DESTROYER] START")
    assert _soon(hud_at(out, "ghidorah_heads", "AwardSub", "KING GHIDORAH TOTAL"), end)     # its total was up
    assert start in _hid(out, "ghidorah_heads")                                              # and gave way at once
    assert not any(end < t < start for t in _hid(out, "ghidorah_heads"))
    # while KING GHIDORAH ran, the spins wrote nothing on OXYGEN DESTROYER's HUD (the notes are polite)
    first_spin = _at(out, ">> shot Left spinner")
    assert not any(first_spin <= t < start for t, _w in hud(out, "oxygen_destroyer", "Award"))


@pytest.mark.parametrize("start", [POWERLINES, [*MASER3], ["trigger", "final_wars.light", "secs", 8,
                                                                              "shot", "Building"], MELTDOWN_START])
def test_a_drain_ends_the_mode_with_its_total(harness, start):
    out = play(harness, *start, "secs", 2, "ball_end", "secs", 1)
    assert re.search(r"\] END \(ball ended\)", out), out[-2000:]


def test_the_final_wars_note_waits_for_another_modes_total_to_go(harness):
    out = play(harness, "trigger", "final_wars.light", "trigger", "oxygen_destroyer.start", "secs", 9,
               "trigger", "oxygen_destroyer.stop", "secs", 12)
    end_ms = int(re.search(r"^\s*(\d+) \[OXYGEN DESTROYER\] END", out, re.M).group(1))
    note = hud_at(out, "final_wars", "Award", "FINAL WARS IS LIT")
    assert note, "the note never showed"
    assert note >= end_ms + 9900      # after OXYGEN DESTROYER's total (10 s), not over it
    hidden = [t for t in _hid(out, "oxygen_destroyer") if t > end_ms]
    assert hidden and hidden[0] <= note


# ---- the modes' OWN clip, music and calls (pad_mode_assets.h) ------------------------------------------------
# What the build would carry for each mode, as the <folder>.assets file Write puts beside mode.so. The desk
# harness reads it from $HARNESS_DUMP (the rig's /dump) and prints every sound call; the game's own music is
# request 67 at priority 1, the music carrier request 125. MELTDOWN's requests are the harness's own numbers.
ASSETS = {
    "ghidorah_heads": ("KING GHIDORAH", 618, {"sever": 1251, "regrow": 1249, "won": 1133, "lost": 1020}),
    "oxygen_destroyer": ("OXYGEN DESTROYER", 105, {"collect": 1170, "won": 1188, "lost": 945}),
    "maser_barrage": ("MASER BARRAGE", 576, {"barrage": 1174, "broken": 1186, "won": 1192, "lost": 1172}),
    "final_wars": ("FINAL WARS", 555, {"phase1": 1076, "phase2": 1190, "won": 1247, "lost": 1129}),
    "anguirus_assist": ("ANGUIRUS", 357, {"spike": 1197, "roll": 972, "won": 1281, "lost": 1259}),
    "meltdown": ("MELTDOWN", 590, {"lit": 1203, "jackpot": 1205, "cool": 1207, "heat": 1209, "critical": 1211,
                                   "meltdown": 1213, "won": 1215, "lost": 1217, "add": 1219}),
    "godzilla_angry": ("GODZILLA ANGRY", 600, {"rage": 1301, "angry": 1303, "lock": 1305, "baby": 1307,
                                               "jackpot": 1309, "super": 1311,
                                               "won": 1313, "lost": 1315}),
    "spacegodzilla": ("SPACEGODZILLA", 610, {"lit": 1321, "lock": 1323, "jackpot": 1325, "tower": 1327,
                                             "super": 1329, "add": 1331,
                                             "won": 1333, "lost": 1335}),
    "kiryu": ("KIRYU", 620, {"charge": 1341, "ready": 1343, "fire": 1345, "overheat": 1347, "won": 1349, "lost": 1351}),
    "biollante": ("BIOLLANTE", 630, {"cut": 1361, "collect": 1363, "beast": 1365, "won": 1367, "lost": 1369}),
    "destoroyah": ("DESTOROYAH", 640, {"kill": 1381, "escape": 1383, "wave": 1385, "boss": 1387, "won": 1389, "lost": 1391}),
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


def _assets_text(slug, clips):
    name, bed, calls = ASSETS[slug]
    text = ["# test", "name   %s" % name] + ["clip   %s %s" % (cue, clip) for cue, clip in clips]
    text += ["music  125 %d" % bed]
    text += ["call   %s %d 1500 %d" % (cue, req, 3 if cue in ("spike", "roll") else 4) for cue, req in calls.items()]
    return "\n".join(text) + "\n"


@pytest.fixture
def dump(tmp_path):
    d = tmp_path / "dump"
    d.mkdir()
    for slug in ASSETS:
        (d / (slug + ".assets")).write_text(_assets_text(slug, [("start", "PadMode_%s_Clip" % slug)]))
    return str(d)


def _recipe_clips():
    """{slug: [cue, ...]}: the clips each example's film recipe cuts (examples/film_recipes.json)"""
    data = json.loads((EX / "film_recipes.json").read_text(encoding="utf-8"))
    return {ex["slug"]: sorted(ex["recipe"].get("clips", {})) for ex in data["examples"]}


def _clip(slug, cue):
    return "PadMode_%s_%s" % (slug, cue[:1].upper() + cue[1:])


@pytest.fixture
def dump_clips(tmp_path):
    """the .assets files as the hud-layers build writes them: a clip per CUE (intro, loop, events, ends)"""
    d = tmp_path / "dump_clips"
    d.mkdir()
    for slug, cues in _recipe_clips().items():
        (d / (slug + ".assets")).write_text(_assets_text(slug, [(c, _clip(slug, c)) for c in cues]))
    return str(d)


def play_own(harness, dump_dir, *args):
    env = dict(os.environ, HARNESS_DUMP=dump_dir)
    r = subprocess.run([str(harness)] + [str(a) for a in args], capture_output=True, text=True, timeout=60,
                       env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _key(n):
    return "%016x" % n


def _swaps_run(harness, d, lines):
    d.mkdir()
    (d / "meltdown.assets").write_text("\n".join(lines) + "\n")
    return play_own(harness, str(d), *(GT * 10), "secs", 1, *GT, "secs", 2, "trigger", "meltdown.heat=75",
                    "secs", 2, "trigger", "meltdown.stop", "secs", 2)


def test_every_call_swaps_in_its_own_record_past_the_old_four(harness, tmp_path):
    """hud-layers: a mode reads up to PA_SWAPS_MAX swap lines (4 dropped MELTDOWN's other calls on
    the swap titles, which then played the carrier's own line), and picks each call's swap by its
    CUE: one carrier can hold several sounds, each its own record."""
    name, bed, calls = ASSETS["meltdown"]
    lines = ["name   %s" % name, "music  125 %d" % bed]
    lines += ["swap   %d %s %s call:%s" % (req, _key(1), _key(req), cue) for cue, req in calls.items()]
    lines += ["call   %s %d 1500 4" % (cue, req) for cue, req in calls.items()]
    out = _swaps_run(harness, tmp_path / "swaps", lines)
    order = list(calls.values())
    played = sorted({int(r) for r in re.findall(r"^\s*\d+ SOUND (\d+)$", out, re.M) if int(r) in order})
    assert len(played) >= 2, out[-2000:]
    assert [r for r in played if order.index(r) >= 4], played        # a call past the fourth swap line
    for r in played:
        assert re.search(r"SWAP %d p\d+ \d+ %s$" % (r, _key(r)), out, re.M), r


def test_a_swap_is_picked_by_its_cue_and_an_untagged_one_still_reads(harness, tmp_path):
    name, bed, calls = ASSETS["meltdown"]
    lit, lost = calls["lit"], calls["critical"]     # "lost": the critical call, as before the tag
    lines = ["name   %s" % name, "music  125 %d" % bed,
             "swap   %d %s %s call:heat" % (lit, _key(1), _key(0xbad)),      # another cue's, same request
             "swap   %d %s %s call:lit" % (lit, _key(1), _key(0x11)),
             "swap   %d %s %s" % (lost, _key(1), _key(0x22)),               # as before the tag: its one sound
             "call   lit %d 1500 4" % lit, "call   critical %d 1500 4" % lost]
    out = _swaps_run(harness, tmp_path / "tags", lines)
    assert re.search(r"SWAP %d p\d+ \d+ %s$" % (lit, _key(0x11)), out, re.M), out[-2000:]
    assert not re.search(r"SWAP %d p\d+ \d+ %s$" % (lit, _key(0xbad)), out, re.M)
    assert re.search(r"SWAP %d p\d+ \d+ %s$" % (lost, _key(0x22)), out, re.M)


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
    out = play_own(harness, dump, *SPINS, "secs", 2, "shot", "Left ramp", "secs", 3, "shot", "Right ramp",
                   "secs", 3)
    assert "SID 125 105" in out and "CLIP PadMode_oxygen_destroyer_Clip" in out
    assert "own sound: call collect (1170) played" in out and "own sound: call won (1188) played" in out
    out = play_own(harness, dump, *SPINS, "secs", 26)
    assert "own sound: call lost (945) played" in out and "CALLOUT 1295" not in out


def test_maser_barrage_barrage_broken_and_end_calls(harness, dump):
    out = play_own(harness, dump, *MASER3, "secs", 1,
                   "shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 1, "shot", "Building",
                   "secs", 1, "shot", "Left ramp", "secs", 7, "secs", 40)
    assert "own sound: call barrage (1174) played" in out
    assert "own sound: call broken (1186) played" in out
    assert "own sound: call won (1192) played" in out and "call lost (1172)" not in out
    out = play_own(harness, dump, *MASER3, "secs", 42)
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


def test_meltdown_lit_jackpot_cool_meltdown_and_super_calls(harness, dump):
    out = play_own(harness, dump, *MELTDOWN_START, "secs", 1, "shot", "Left ramp", "secs", 1,
                   "shot", "Shield target left", "secs", 1, "trigger", "meltdown.heat=99", "secs", 1,
                   "shot", "Building", "secs", 1)
    assert "SID 125 590" in out
    for cue, req in (("lit", 1203), ("jackpot", 1205), ("cool", 1207), ("meltdown", 1213), ("won", 1215)):
        assert "own sound: call %s (%d)" % (cue, req) in out, cue


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


# ---- hud-layers: clips by CUE - the intro full screen, the loop BEHIND the HUD, events, the ending ----------------
# Each flow: (how it starts and ends, the mode, the event cue it plays behind the HUD, the ending's cue).
CLIP_FLOWS = {
    "ghidorah_heads": (POWERLINES + ["secs", 1, "shot", "Left ramp", "shot", "Powerline left", "secs", 1,
                                     "trigger", "ghidorah_heads.stop", "secs", 1], "KING GHIDORAH", "sever", "lost"),
    "oxygen_destroyer": (SPINS + ["secs", 1, "shot", "Left ramp", "secs", 1, "trigger", "oxygen_destroyer.stop",
                                  "secs", 1], "OXYGEN DESTROYER", "collect", "lost"),
    "maser_barrage": ([*MASER3, "secs", 1, "shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 1,
                       "shot", "Building", "secs", 1, "trigger", "maser_barrage.stop", "secs", 1],
                      "MASER BARRAGE", "barrage", "won"),
    "final_wars": (["trigger", "final_wars.light", "secs", 8, "shot", "Building", "secs", 1, "shot", "Left ramp",
                    "shot", "Right ramp", "shot", "Big loop", "secs", 1, "trigger", "final_wars.stop", "secs", 1],
                   "FINAL WARS", "phase", "lost"),
    "meltdown": (MELTDOWN_START + ["secs", 1, "shot", "Left ramp", "secs", 1, "trigger", "meltdown.stop", "secs", 1],
                 "MELTDOWN", "jackpot", "lost"),
    "anguirus_assist": (["battle", 1, "secs", 2, "shot", "Shield target left", "shot", "Shield target center",
                         "shot", "Shield target right", "secs", 1, "battle", 0, "secs", 6], "ANGUIRUS", None, "lost"),
    "godzilla_angry": (["trigger", "godzilla_angry.light", "secs", 1, "shot", "Building", "secs", 1,
                        "shot", "Godzilla target", "secs", 1, "trigger", "godzilla_angry.stop", "secs", 1],
                       "GODZILLA ANGRY", "lock", "lost"),
    "spacegodzilla": (["trigger", "spacegodzilla.start", "secs", 1, "shot", "Left ramp", "secs", 1,
                       "trigger", "spacegodzilla.stop", "secs", 1], "SPACEGODZILLA", "jackpot", "lost"),
    "kiryu": (["trigger", "kiryu.start", "secs", 1, "trigger", "kiryu.charge=105", "secs", 1, "trigger", "kiryu.stop",
               "secs", 1], "KIRYU", "ready", "lost"),
    "biollante": (["trigger", "biollante.start", "secs", 1, "shot", "Shield target left", "shot", "Shield target center",
                   "shot", "Shield target right", "secs", 1, "trigger", "biollante.stop", "secs", 1],
                  "BIOLLANTE", "collect", "lost"),
    "destoroyah": (["trigger", "destoroyah.start", "secs", 4, "shot", "Powerline left", "shot", "Powerline center",
                    "shot", "Powerline right", "secs", 1, "trigger", "destoroyah.stop", "secs", 1],
                   "DESTOROYAH", "kill", "lost"),
}


def test_every_example_has_a_clip_flow_and_a_recipe_with_an_intro():
    clips = _recipe_clips()
    assert set(CLIP_FLOWS) == set(MODES) == set(clips)
    for slug in MODES:
        assert "intro" in clips[slug] and "won" in clips[slug] and "lost" in clips[slug], slug
        if CLIP_FLOWS[slug][2]:
            assert CLIP_FLOWS[slug][2] in clips[slug], slug


@pytest.mark.parametrize("slug", MODES)
def test_start_plays_the_intro_then_asks_for_the_loop_behind_the_hud(harness, dump_clips, slug):
    flow, mode, event, ending = CLIP_FLOWS[slug]
    cues = _recipe_clips()[slug]
    out = play_own(harness, dump_clips, *flow)
    begun = _at(out, "[%s] %s" % (mode, "ENTRANCE" if slug == "anguirus_assist" else "START"))
    assert begun is not None, out[-2000:]
    intro = _at(out, "CLIP " + _clip(slug, "intro"))
    assert intro is not None and 480 <= intro - begun <= 520                  # full screen, half a second in
    if "loop" in cues:
        assert _at(out, "BACKDROP " + _clip(slug, "loop")) == intro           # then its loop behind the HUD
        assert has(out, mode, "own clip loop %s behind the HUD: asked" % _clip(slug, "loop"))
    else:
        assert "BACKDROP" not in out                                          # ANGUIRUS keeps the battle's own
    if event:
        once = _at(out, "BACKDROP ONCE " + _clip(slug, event))
        assert once is not None and once > intro                              # an event: once, behind the HUD
        assert has(out, mode, "own clip %s (%s) behind the HUD" % (event, _clip(slug, event)))
    if slug == "final_wars":
        assert _at(out, "BACKDROP " + _clip(slug, "loop2")) is not None       # phase 2's own world
    over = _at(out, "[%s] %s" % (mode, "the total was shown" if slug == "anguirus_assist" else "END"))
    assert _at(out, "CLIP " + _clip(slug, ending)) == over                    # the ending, full screen
    if "loop" in cues:
        assert _at(out, "BACKDROP OFF") == over                               # the city again


@pytest.mark.parametrize("slug", MODES)
def test_without_its_assets_a_mode_plays_no_clip_and_asks_for_no_backdrop(harness, slug):
    # the desk harness carries no .assets files unless HARNESS_DUMP names them: nothing to play
    flow, mode, _event, _ending = CLIP_FLOWS[slug]
    out = play(harness, *flow)
    assert has(out, mode, "END")
    assert "CLIP " not in out and "BACKDROP" not in out


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
        assert begin < disp < start.index("kit_hud_begin(") and disp < start.index("sound(CUE_START)"), f
    assert "kit_display(KIT_DISPLAY_WIZARD)" in _src("final_wars")
    # MELTDOWN, a multiball of ours, holds the wizard's priority - and only once the game has served its balls
    melt = _src("meltdown")
    melt = melt[melt.index("static int start("):]
    assert "kit_display(KIT_DISPLAY_WIZARD)" in melt
    assert melt.index("kit_begin(MODE_NAME)") < melt.index("pm_multiball_start(") < melt.index("kit_display(")
    refused = melt[melt.index("pm_multiball_start("):melt.index("kit_display(")]
    assert "kit_end();" in refused                   # refused: our begin is given back, no display held
    kit = (EX / "intricate_kit.h").read_text(encoding="utf-8")
    assert "#define KIT_DISPLAY_MODE    180" in kit and "#define KIT_DISPLAY_WIZARD  190" in kit
    assert kit.index("pm_display_priority(0)") < kit.index("    pm_end();")     # given up before pm_end


def _lamp(out, name, mode=None):
    """(ms, rgb, pattern, period) of every LAMP line for an insert"""
    rows = re.findall(r"^\s*(\d+) LAMP %s ([0-9a-f]{6}) (\w+) (\d+) (.+)$" % re.escape(name), out, re.M)
    return [(int(t), rgb, pat, int(ms)) for t, rgb, pat, ms, who in rows if mode is None or who == mode]


def _changes(rows):
    """the (rgb, pattern, period) an insert went through, each once in a row: a light show's end hands every
    insert back and the mode holds its own again, the same as before"""
    out = []
    for _t, c, p, ms in rows:
        if not out or out[-1] != (c, p, ms):
            out.append((c, p, ms))
    return out


def _released(out, name):
    return [int(t) for t in re.findall(r"^\s*(\d+) LAMP OFF %s " % re.escape(name), out, re.M)]


def _all_back(out):
    return "END lamps held 0, display priority 0" in out


ENDING_MS = 10000     # a natural end keeps the display hold this long: the ending clip, then the total


def _ending_back(out, mode, end):
    """a natural end: the hold stays for the mode's ending (pm_end_holding), then goes back to the game"""
    back = _at(out, "DISPLAY released %s (its ending is over)" % mode)
    return (_at(out, "DISPLAY lingers %s %d ms" % (mode, ENDING_MS)) == end and back is not None
            and end + ENDING_MS <= back <= end + ENDING_MS + 20)


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
               "secs", 1, "shot", "Right ramp", "shot", "Powerline right", "secs", 11, "shot", "Maser target", "secs", 11)
    final = _at(out, "[KING GHIDORAH] FINAL BLOW")
    for name in ("MASER", "MASER READY"):
        assert (final, "ffffff", "blink", 150) in _lamp(out, name)
        assert any(t > final for t, _c, p, ms in _lamp(out, name) if ms == 80)   # its last 5 s: faster
    for name in ("RIGHT RAMP", "POWERLINE RIGHT"):
        assert final in _released(out, name)                                     # the heads are gone
    end = _at(out, "[KING GHIDORAH] END (super jackpot)")
    assert end in _released(out, "MASER") and end in _released(out, "MASER READY")
    assert _ending_back(out, "KING GHIDORAH", end) and _all_back(out)


def test_a_mode_started_during_anothers_ending_takes_the_display_at_once(harness):
    out = play(harness, *POWERLINES, "secs", 1, "trigger", "ghidorah_heads.stop", "secs", 2, *SPINS, "secs", 1)
    end = _at(out, "[KING GHIDORAH] END")
    assert _at(out, "DISPLAY lingers KING GHIDORAH %d ms" % ENDING_MS) == end
    start = _at(out, "[OXYGEN DESTROYER] START")
    assert start is not None and end < start < end + ENDING_MS                 # not refused by the ending
    assert _at(out, "DISPLAY released KING GHIDORAH (another mode began)") == start
    assert _at(out, "DISPLAY 180 OXYGEN DESTROYER") == start


def test_a_drain_right_after_a_natural_end_gives_the_ending_hold_up(harness):
    out = play(harness, *POWERLINES, "secs", 1, "trigger", "ghidorah_heads.stop", "secs", 2, "ball_end", "ms", 20)
    assert _at(out, "DISPLAY lingers KING GHIDORAH %d ms" % ENDING_MS) is not None
    assert _at(out, "DISPLAY 0 KING GHIDORAH") == _at(out, ">> ball_end")


def test_oxygen_destroyer_collect_insert_blinks_faster_as_the_value_falls_then_the_super_flashes(harness):
    out = play(harness, *SPINS, "secs", 23, "shot", "Left ramp", "secs", 10, "shot", "Right ramp", "secs", 11)
    o = "OXYGEN DESTROYER"
    start = _at(out, "[OXYGEN DESTROYER] START")
    assert _at(out, "DISPLAY 180 OXYGEN DESTROYER") <= start
    steps = _changes(_lamp(out, "LEFT RAMP", o))
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
    out = play(harness, *SPINS, "secs", 1, *GT, *GT, *GT, "secs", 1)
    third = [int(t) for t in re.findall(r"^\s*(\d+) \[OXYGEN DESTROYER\] Godzilla target: hold-off 3 of 3", out, re.M)]
    assert third and any(third[0] <= t <= third[0] + 50 for t in _released(out, "MAGNA GRAB"))
    assert _lamp(out, "LEFT RAMP")                                                # still lit: collect it


def test_maser_barrage_lights_the_next_shot_bright_the_rest_dim_and_the_window_by_blink_speed(harness):
    out = play(harness, *MASER3, "secs", 1, "shot", "Left ramp", "secs", 7, "secs", 1)
    m = "MASER BARRAGE"
    start = _at(out, "[MASER BARRAGE] START")
    assert _at(out, "DISPLAY 180 MASER BARRAGE") <= start
    assert (start, "005aff", "solid", 0) in _lamp(out, "LEFT RAMP", m)            # next, no window yet
    assert (start, "001e5a", "solid", 0) in _lamp(out, "RIGHT RAMP", m)           # the rest of the chain, dim
    assert (start, "001e5a", "solid", 0) in _lamp(out, "BUILDING", m)
    step = _at(out, "[MASER BARRAGE] step 1 Left ramp")
    assert (step, "001e5a", "solid", 0) in _lamp(out, "LEFT RAMP", m)
    blinks = [(t - step, c, p, ms) for t, c, p, ms in _lamp(out, "RIGHT RAMP", m) if p == "blink" and t >= step]
    assert [ms for _c, _p, ms in _changes(blinks)] == [500, 250, 100], blinks      # the 7 s window closing
    first = {}
    for d, _c, _p, ms in blinks:
        first.setdefault(ms, d)
    assert 2700 <= first[250] <= 2900 and 4800 <= first[100] <= 5000
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


@pytest.mark.parametrize("start,mode,prio", [
    (POWERLINES, "KING GHIDORAH", 180),
    (SPINS, "OXYGEN DESTROYER", 180),
    ([*MASER3], "MASER BARRAGE", 180),
    (["trigger", "final_wars.light", "secs", 8, "shot", "Building"], "FINAL WARS", 190),
    (["battle", 1], "ANGUIRUS", 180),
    (MELTDOWN_START, "MELTDOWN", 190),
    (["trigger", "godzilla_angry.light", "secs", 1, "shot", "Building"], "GODZILLA ANGRY", 180),
    (["trigger", "spacegodzilla.start", "secs", 1], "SPACEGODZILLA", 190),
    (["raw", "0x20000"] * 30, "KIRYU", 180),
    (["shot", "Left ramp", "ms", 300] * 6, "BIOLLANTE", 180),
    (["raw", "0x2000"] * 30 + ["secs", 2], "DESTOROYAH", 180),          # its first aggregate, 2.5 s in
])
@pytest.mark.parametrize("ending", ["ball_end", "tilt"])
def test_a_drain_or_a_tilt_hands_every_insert_and_the_display_back_at_once(harness, start, mode, prio, ending):
    end_cmd = ["ball_end"] if ending == "ball_end" else ["event", "tilt"]
    out = play(harness, *start, "secs", 2, *end_cmd, "ms", 20)
    begun = _at(out, "[%s] START" % mode)
    held = _at(out, "DISPLAY %d %s" % (prio, mode))
    assert begun is not None and held is not None and held <= begun               # its priority, before its start
    why = "ball ended" if ending == "ball_end" else "tilted"
    t = _at(out, "[%s] END (%s)" % (mode, why))
    assert t is not None, out[-1500:]
    assert _at(out, "[%s] lights: all handed back to the game" % mode) == t
    assert "END lamps held 0" in out                                                # nothing left lit
    assert re.search(r"^\s*%d DISPLAY (0 %s|released %s)" % (t, re.escape(mode), re.escape(mode)), out, re.M) \
        or "display priority 0" in out.splitlines()[-1]
    # PAD-301: the mode's HUD (its total) goes down with it: the game's end-of-ball bonus or the tilt has the
    # screen, and a total kept up for its seconds sat on the bonus screen's words on a machine
    slug = {name: slug for slug, name in NAMES.items()}[mode]
    assert t in _hid(out, slug), out[-1500:]


# ---- MELTDOWN: a multiball of our own (hud-layers) ----------------------------------------------------------
def _jackpots(out):
    """(ms, shot, heart, paid, multiplier, core%) of every MELTDOWN jackpot"""
    rows = re.findall(r"^\s*(\d+) \[MELTDOWN\] JACKPOT \d+ at (.+?)( \(THE HEART\))?: \+(\d+) \(x(\d+), the core (\d+)%\)$",
                      out, re.M)
    return [(int(t), shot, bool(h), int(p), int(x), int(c)) for t, shot, h, p, x, c in rows]


def test_meltdown_ten_captive_ball_hits_make_it_ready_and_the_next_starts_a_three_ball_multiball(harness):
    s = "meltdown"
    out = play(harness, *(GT * 10), "secs", 4, *GT, "secs", 1)
    hits = [int(t) for t in re.findall(r"^\s*(\d+) >> shot Godzilla target", out, re.M)]
    assert len(hits) == 11
    for k in range(1, 11):
        assert has(out, "MELTDOWN", "captive ball %d of 10 (player 1)" % k)
    for left in range(1, 10):                                          # each hit says how many are left
        assert hud_said(out, s, "Award", "%d MORE FOR MELTDOWN" % left)
    ready = _at(out, "[MELTDOWN] MELTDOWN IS READY for player 1")
    assert ready == hits[9]
    assert _soon(hud_at(out, s, "Award", "MELTDOWN IS READY"), ready)
    assert hud_said(out, s, "AwardSub", "HIT THE CAPTIVE BALL")
    start = _at(out, "[MELTDOWN] START")
    assert start == hits[10]                                           # the eleventh hit, not the tenth
    assert _at(out, "MULTIBALL 3 balls, save 15 s") == start
    assert _at(out, "DISPLAY 190 MELTDOWN") == start
    assert has(out, "MELTDOWN", "START (the captive ball, MELTDOWN ready): player 1, 3 balls, ball save 15 s, core 25%")
    # the HUD: the core, the jackpot's value and the jackpots across the top, the CORE gauge on the right
    assert hud_next(out, s, "Title", start) == "BURNING GODZILLA"
    assert hud_said(out, s, "Award", "MELTDOWN MULTIBALL")
    assert hud_said(out, s, "C1_Label", "CORE") and hud_said(out, s, "C1_Value", "25%") and hud_said(out, s, "C1_Sub", "STABLE")
    assert hud_said(out, s, "C2_Label", "JACKPOT") and hud_said(out, s, "C2_Value", "2.00M")
    assert hud_said(out, s, "C2_Sub", "X1 HEAT") and hud_said(out, s, "C3_Value", "0")
    assert hud_said(out, s, "Gauge_Label", "CORE")
    assert hud_said(out, s, "C1_Value", "26%")                          # it rises by itself, 1% a second


def test_meltdown_waits_for_the_games_own_multiball_still_ready(harness):
    out = play(harness, *(GT * 10), "multiball", 1, *GT, "multiball", 0, *GT, "secs", 1)
    assert has(out, "MELTDOWN", "not started (the captive ball, MELTDOWN ready): a multiball is running - still ready")
    assert len(re.findall(r"MULTIBALL 3 balls", out)) == 1
    refused = _at(out, "[MELTDOWN] not started")
    assert refused < _at(out, ">> multiball 0") <= _at(out, "[MELTDOWN] START")    # the next hit after it


READY_PULSE = "[MELTDOWN] lights: shot 0x80000 ff1400 pulse 700"   # the MAGNA GRAB insert, red


def test_meltdown_ready_pulses_the_magna_grab_insert_red_and_hands_it_back(harness):
    out = play(harness, *(GT * 10), "secs", 2, "multiball", 1, "secs", 2, "multiball", 0, "secs", 2, *GT, "secs", 1)
    ready = _at(out, "[MELTDOWN] MELTDOWN IS READY for player 1")
    pulses = [int(t) for t in re.findall(r"^\s*(\d+) %s$" % re.escape(READY_PULSE), out, re.M)]
    assert len(pulses) == 2 and ready <= pulses[0] <= ready + 1100, pulses    # lit when ready (the 1 s poll) ...
    offs = [int(t) for t in re.findall(r"^\s*(\d+) \[MELTDOWN\] lights: none held$", out, re.M)]
    busy, free = _at(out, ">> multiball 1"), _at(out, ">> multiball 0")
    assert any(busy <= t < free for t in offs)                                # ... dark under the game's multiball
    assert free <= pulses[1]                                                  # ... lit again after it
    start = _at(out, "[MELTDOWN] START")
    assert any(t == start for t in offs)                                      # handed back as it starts


def test_meltdown_leaves_the_captive_ball_alone_while_another_of_our_modes_runs(harness):
    out = play(harness, *SPINS, "secs", 1, *(GT * 3), "secs", 1)
    assert _at(out, "[OXYGEN DESTROYER] START") is not None
    assert not has(out, "MELTDOWN", "captive ball")                           # OXYGEN's hold-offs, not counted
    assert not hud_said(out, "meltdown", "Award", "9 MORE FOR MELTDOWN")


@pytest.mark.parametrize("heat,mult,level", [(30, 1, None), (45, 2, "HOT"), (75, 3, "CRITICAL"),
                                             (92, 5, "IMMINENT")])
def test_meltdown_jackpot_pays_the_base_times_the_heat_multiplier_and_heats_the_core(harness, heat, mult, level):
    s = "meltdown"
    out = play(harness, *MELTDOWN_START, "secs", 1, "trigger", "meltdown.heat=%d" % heat, "shot", "Right ramp",
               "secs", 1)
    if level:
        assert has(out, "MELTDOWN", "the core is %s (%d%%): jackpots x%d" % (level, heat, mult))
        award = "MELTDOWN IMMINENT" if level == "IMMINENT" else level
        assert hud_said(out, s, "Award", award) and hud_said(out, s, "C1_Sub", level)
    (t, shot, heart, paid, x, core), = _jackpots(out)
    assert shot == "Right ramp" and x == mult and core >= heat
    assert paid == 2000000 * mult * (2 if heart else 1)                # the HEART pays double
    assert scored(out, "", "MELTDOWN") == paid
    assert hud_said(out, s, "Award", "HEART JACKPOT" if heart else "JACKPOT") and hud_said(out, s, "AwardSub", commas(paid))
    assert hud_said(out, s, "C2_Sub", "X%d HEAT" % mult)
    # and heats the core: 4% (8% for the heart) on top of where it was
    after = hud_next(out, s, "C1_Value", t)
    hotter = core + (8 if heart else 4)
    assert after in ("%d%%" % min(hotter, 100), "%d%%" % min(hotter + 1, 100)), after
    assert hud_said(out, s, "C3_Value", "1") and hud_said(out, s, "C3_Sub", "SUPER " + kit_short(2 * paid))


def test_meltdown_a_shield_is_a_cadmium_missile_that_cools_the_core(harness):
    s = "meltdown"
    out = play(harness, *MELTDOWN_START, "secs", 1, "trigger", "meltdown.heat=50", "secs", 1,
               "shot", "Shield target center", "secs", 1)
    m = re.search(r"^\s*(\d+) \[MELTDOWN\] CADMIUM at Shield target center: the core (\d+)% -> (\d+)%$", out, re.M)
    assert m and int(m.group(2)) - int(m.group(3)) == 12
    t = int(m.group(1))
    assert hud_next(out, s, "C1_Value", t) == "%s%%" % m.group(3)
    assert hud_said(out, s, "Award", "CADMIUM MISSILE") and hud_said(out, s, "AwardSub", "THE CORE COOLS")
    assert scored(out, "", "MELTDOWN") == 0                           # cooling pays nothing
    # the shields pulse ice blue while the core is above 40%: cooled under it, they go back to the game
    heated = _at(out, "[MELTDOWN] heat trigger")
    assert any(_soon(tt, heated) and (c, p, ms) == ("78d2ff", "pulse", 900)
               for tt, c, p, ms in _lamp(out, "SHIELD CENTER", "MELTDOWN"))
    assert any(t <= tt <= t + 20 for tt in _released(out, "SHIELD CENTER"))


def test_meltdown_at_100_percent_the_building_is_the_super_jackpot_twice_the_jackpots_paid(harness):
    s = "meltdown"
    out = play(harness, *MELTDOWN_START, "secs", 1, "shot", "Left ramp", "secs", 1, "shot", "Big loop", "secs", 1,
               "trigger", "meltdown.heat=99", "secs", 1, "shot", "Building", "secs", 1)
    paid = sum(p for _t, _s, _h, p, _x, _c in _jackpots(out))
    assert len(_jackpots(out)) == 2 and paid >= 4000000
    heated = _at(out, "[MELTDOWN] heat trigger: the core")
    assert has(out, "MELTDOWN", "the core is IMMINENT (99%): jackpots x5")
    melt = _at(out, "[MELTDOWN] MELTDOWN: the core is at 100%")
    assert heated <= melt <= heated + 520                             # a tick later it reaches 100%
    assert has(out, "MELTDOWN", "the Building is the super jackpot for 20 s: %d" % (2 * paid))
    assert hud_said(out, s, "Title", "MELTDOWN!") and hud_said(out, s, "Line", "SHOOT THE BUILDING: MELTDOWN SUPER JACKPOT")
    assert hud_said(out, s, "C1_Value", "100%") and hud_said(out, s, "C2_Value", kit_short(2 * paid))
    assert hud_said(out, s, "Timer_Num", "20")                        # the MELTDOWN badge counts its 20 s
    assert any(melt <= t <= melt + 20 and (c, p, ms) == ("ffffff", "blink", 120)     # only the Building, strobing
               for t, c, p, ms in _lamp(out, "BUILDING", "MELTDOWN"))
    assert not [row for row in _lamp(out, "LEFT RAMP", "MELTDOWN") if melt <= row[0] < _at(out, ">> shot Building")]
    shot = _at(out, "[MELTDOWN] MELTDOWN SUPER JACKPOT")
    assert has(out, "MELTDOWN", "MELTDOWN SUPER JACKPOT: +%d (asked %d)" % (2 * paid, 2 * paid))
    assert _soon(hud_at(out, s, "Award", "MELTDOWN SUPER JACKPOT"), shot)
    assert hud_said(out, s, "AwardSub", commas(2 * paid))
    assert scored(out, "", "MELTDOWN") == 3 * paid
    # Junior absorbs it: the core back to 25%, the jackpot base up by 500,000
    assert hud_next(out, s, "C1_Value", shot) == "25%"
    assert hud_said(out, s, "C2_Value", "2.50M")


def test_meltdown_missed_the_core_blows_back_to_50_percent(harness):
    s = "meltdown"
    out = play(harness, *MELTDOWN_START, "secs", 1, "trigger", "meltdown.heat=99", "secs", 21)
    assert has(out, "MELTDOWN", "the MELTDOWN super jackpot ran out: the core blows - back to 50%")
    blown = _at(out, "[MELTDOWN] the MELTDOWN super jackpot ran out")
    assert _soon(hud_at(out, s, "Award", "THE CORE BLOWS"), blown)
    assert hud_next(out, s, "C1_Value", blown) == "50%"
    assert has(out, "MELTDOWN", "START") and not has(out, "MELTDOWN", "END")     # the multiball goes on


def test_meltdown_ends_when_one_ball_is_left_after_the_ball_save_and_its_grace(harness):
    s = "meltdown"
    out = play(harness, *MELTDOWN_START, "secs", 1, "balls", 1, "secs", 31)
    start = _at(out, "[MELTDOWN] START")
    end = _at(out, "[MELTDOWN] END (one ball left)")
    assert end is not None
    assert 15000 + 3000 + 2000 <= end - start <= 15000 + 3000 + 2000 + 50       # the ball save, 3 s, then 2 s
    assert has(out, "MELTDOWN", "END (one ball left): 0 jackpot(s), 0 meltdown(s) survived")
    assert _ending_back(out, "MELTDOWN", end) and _all_back(out)
    assert hud_next(out, s, "Title", end) == "MELTDOWN TOTAL"
    assert hud_said(out, s, "Line", "0 JACKPOTS  -  0 MELTDOWNS SURVIVED") and hud_said(out, s, "Award", "0")
    # one ball left during the ball save does not end it
    out = play(harness, *MELTDOWN_START, "secs", 1, "balls", 1, "secs", 17)
    assert not has(out, "MELTDOWN", "END")


# ---- what the HUD is given fits it ------------------------------------------------------------------------------
# The HUD's texts are laid out for these widths (the card build, mode_hud.py): a counter's big value in 200 px,
# its label and sub-label, the award line, the title, and the instruction line above the score panel. The award's
# smaller line sits under the award as wide as the instruction line. Measured from what each mode WRITES in full
# runs of its flows, not from its source.
# ---- PAD-379: the Lyman Sheats modes' flows ------------------------------------------------------------------------
GA = "GODZILLA ANGRY"
GA_LIGHT = ["trigger", "godzilla_angry.light", "secs", 1]
#: the Building starts the chase; then ADONOA ISLAND, YOKKAICHI, OSAKA, KYOTO and MAKUHARI, a lock each
GA_CHASE = ["shot", "Building", "secs", 1, "shot", "Godzilla target", "secs", 1,
            "shot", "Left ramp", "shot", "Right ramp", "secs", 1, "shot", "Maser target", "secs", 1,
            "shot", "Big loop", "shot", "Building", "secs", 1, "shot", "Godzilla target", "secs", 1,
            "shot", "Left ramp", "shot", "Right ramp", "shot", "Building", "shot", "Big loop", "secs", 1,
            "shot", "Maser target", "secs", 1,
            "shot", "Left ramp", "shot", "Right ramp", "shot", "Big loop", "shot", "Building",
            "shot", "Powerline center", "secs", 1, "shot", "Godzilla target", "secs", 1]
GA_JP = ["shot", "Left ramp", "ms", 300, "shot", "Right ramp", "ms", 300, "shot", "Big loop", "ms", 300,
         "shot", "Building", "ms", 300]
SG = "SPACEGODZILLA"
SG_LOOP = ["shot", "Big loop", "ms", 300]
SG_FIRST = ["shot", "Shield target left", "ms", 300] + SG_LOOP * 3
SG_SECOND = (["shot", "Shield target center", "ms", 300] + SG_LOOP) * 3
SG_THIRD = (["shot", "Shield target right", "ms", 300, "shot", "Shield target left", "ms", 300] + SG_LOOP) * 3
SG_TOWERS_DOWN = ["shot", "Left ramp", "ms", 300, "shot", "Building", "ms", 300, "shot", "Right ramp", "ms", 300] * 2
KIRYU_SPINS = ["raw", "0x20000"] * 30
BIO_RAMPS = ["shot", "Left ramp", "ms", 300] * 6
BIO_BANKS = ["shot", "Slingshot", "shot", "Slingshot", "shot", "Shield target left", "shot", "Shield target center",
             "shot", "Shield target right", "ms", 300, "shot", "Slingshot", "shot", "Powerline left",
             "shot", "Powerline center", "shot", "Powerline right", "ms", 300]
DE_FAR = ["shot", "Powerline left", "shot", "Powerline center", "shot", "Powerline right"]
DE_NEAR = ["shot", "Left ramp", "shot", "Right ramp", "shot", "Big loop", "shot", "Building"]
DE_CLOSE = ["shot", "Maser target", "shot", "Shield target left", "shot", "Shield target center",
            "shot", "Shield target right", "shot", "Godzilla target"]


HUD_LIMITS = {"Value": 10, "Label": 16, "Sub": 16, "Gauge_Label": 16, "Award": 24, "Title": 24, "Line": 44,
              "AwardSub": 44}
# Longer than the HUD's width today (reported with the rework; take a line out when its mode is fixed).
KNOWN_TOO_LONG = []


def _limit_of(field):
    return HUD_LIMITS[field.split("_", 1)[1]] if re.match(r"C\d_", field) else HUD_LIMITS.get(field)


def test_every_text_a_mode_writes_on_its_hud_fits(harness):
    wizard = _monster_x(harness, ["trigger", "final_wars.light", "secs", 8, "shot", "Building", "secs", 1,
                                  "shot", "Left ramp", "shot", "Shield target left", "shot", "Right ramp",
                                  "shot", "Big loop", "ms", 500]) + ["shot", "Building", "secs", 11]
    barrages = []
    for _ in range(5):
        barrages += ["shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 1, "shot", "Building", "secs", 1]
    flows = [
        POWERLINES[:4] + ["secs", 3] + POWERLINES + ["secs", 1, "shot", "Left ramp", "shot", "Right ramp",
                                                     "shot", "Powerline left", "secs", 1, "shot", "Building",
                                                     "shot", "Powerline center", "secs", 1, "shot", "Right ramp",
                                                     "shot", "Powerline right", "secs", 2, "shot", "Maser target",
                                                     "secs", 11],
        POWERLINES + ["secs", 1, "shot", "Left ramp", "secs", 12, "secs", 60],
        SPINS[:30] + ["secs", 2] + SPINS + ["secs", 5, *GT, *GT, *GT, *GT, "secs", 2, "shot", "Left ramp", "secs", 3,
                                            "shot", "Right ramp", "secs", 11],
        SPINS + ["secs", 27],
        ["shot", "Maser target", "ms", 300, "shot", "Maser target", "secs", 3, "shot", "Maser target", "secs", 1]
        + barrages + ["shot", "Left ramp", "secs", 8, "secs", 60],
        wizard,
        ["trigger", "final_wars.light", "secs", 8, "shot", "Building", "secs", 27, "secs", 11],
        ["battle", 1, "secs", 2, "shot", "Shield target left", "secs", 1, "shot", "Shield target center", "secs", 1,
         "shot", "Shield target right", "secs", 1, "shot", "Big loop", "secs", 2, "shot", "Big loop", "secs", 2,
         "shot", "Big loop", "secs", 7, "battle", 0, "secs", 12],
        MELTDOWN_START + ["secs", 1, "shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 1, "shot", "Big loop",
                          "secs", 1, "shot", "Building", "secs", 1, "shot", "Shield target left", "secs", 1, *GT,
                          "trigger", "meltdown.heat=45", "trigger", "meltdown.heat=75", "trigger", "meltdown.heat=92",
                          "shot", "Left ramp", "secs", 1, "trigger", "meltdown.heat=99", "secs", 1,
                          "shot", "Building", "secs", 1, "trigger", "meltdown.heat=99", "secs", 22,
                          "balls", 1, "secs", 25],
        # PAD-379
        ["raw", "0x1"] * 760 + ["secs", 2] + GA_LIGHT + GA_CHASE + ["shot", "Building", "secs", 3] + GA_JP
        + ["secs", 20, "balls", 1, "secs", 25],
        GA_LIGHT + ["shot", "Building", "secs", 1, "shot", "Godzilla target", "secs", 32, "balls", 1, "secs", 25],
        SG_FIRST + ["secs", 2] + SG_TOWERS_DOWN + ["secs", 1, "shot", "Big loop", "secs", 2, "trigger",
                                                    "spacegodzilla.stop", "secs", 12, "balls", 1] + SG_SECOND
        + ["secs", 1, "shot", "Shield target left", "secs", 22, "balls", 1, "secs", 12],
        KIRYU_SPINS + ["secs", 1, "trigger", "kiryu.charge=215", "secs", 14, "trigger", "kiryu.charge=105", "secs", 1,
                       "shot", "Godzilla target", "secs", 16],
        BIO_RAMPS + ["secs", 1] + BIO_BANKS * 3 + ["secs", 4, "shot", "Building", "secs", 12],
        ["trigger", "destoroyah.start", "secs", 4] + DE_FAR + ["secs", 25, "trigger", "destoroyah.boss", "secs", 2,
                                                              "shot", "Building", "ms", 400, "shot", "Building", "ms",
                                                              400, "shot", "Building", "secs", 12],
    ]
    seen = {}                                     # (slug, field) -> every text written
    for flow in flows:
        out = play(harness, *flow)
        for slug, field, words in re.findall(r"^\s*\d+ WORDS PadMode_(\w+?)_Hud_(\w+): (.*)$", out, re.M):
            seen.setdefault((slug, field), set()).add(words)
    for slug in MODES:
        fields = {f for (s, f) in seen if s == slug}
        assert {"Award", "AwardSub"} <= fields, (slug, fields)       # every mode played its flow on its HUD
    too_long, known = [], set()
    for (slug, field), texts in sorted(seen.items()):
        cap = _limit_of(field)
        if cap is None:
            continue                                                 # the badge's "%02d"
        for words in sorted(texts):
            if len(words) <= cap:
                continue
            kind = field.split("_", 1)[1] if re.match(r"C\d_", field) else field
            hit = [k for k in KNOWN_TOO_LONG if k[0] == slug and k[1] == kind and re.fullmatch(k[2], words)]
            if hit:
                known.add(hit[0])
            else:
                too_long.append((slug, field, words, len(words), cap))
    assert not too_long, too_long
    assert known == set(KNOWN_TOO_LONG), set(KNOWN_TOO_LONG) - known     # fixed: take it off the list

# ---- PAD-347: isolated - our modes keep to themselves --------------------------------------------------------
# David's Premium, 2026-10-03: during the game's JET FIGHTER ATTACK one of ours wrote its words in the very places
# the game's mode writes its own, and OXYGEN DESTROYER started during the game's multiball. Stacked with their words
# aside it was better, but (2026-10-04) "still a bit too much overlap with other modes. i'd prefer to try them
# isolated from other ones." `timed 1` is one of the game's modes that is neither a battle nor a multiball.
STACK_STARTS = [
    ("ghidorah_heads", POWERLINES),
    ("oxygen_destroyer", SPINS),
    ("maser_barrage", [*MASER3]),
    ("final_wars", ["trigger", "final_wars.light", "secs", 8, "shot", "Building"]),
    ("meltdown", MELTDOWN_START),
    ("godzilla_angry", ["trigger", "godzilla_angry.light", "secs", 1, "shot", "Building"]),
    ("spacegodzilla", ["shot", "Shield target left", "ms", 300] + ["shot", "Big loop", "ms", 300] * 3),
    ("kiryu", ["raw", "0x20000"] * 30),
    ("biollante", ["shot", "Left ramp", "ms", 300] * 6),
    ("destoroyah", ["raw", "0x2000"] * 30),
]


@pytest.mark.parametrize("busy", ["timed", "battle", "multiball"])
@pytest.mark.parametrize("slug,start", STACK_STARTS, ids=[s for s, _ in STACK_STARTS])
def test_a_mode_ends_the_moment_one_of_the_games_modes_begins(harness, slug, start, busy):
    out = play(harness, *start, "secs", 4, busy, 1, "secs", 1)
    began = _at(out, ">> %s 1" % busy)
    mode = NAMES[slug]
    assert _at(out, "[%s] START" % mode) < began, out[-2000:]
    t = _at(out, "[%s] END (the game's own mode began)" % mode)
    assert t is not None and began <= t <= began + 40, out[-2000:]
    assert t in _hid(out, slug)                                              # its words go in the same tick
    assert _at(out, "[%s] lights: all handed back to the game" % mode) == t
    if busy != "battle":                                  # ANGUIRUS joins a battle of the game's and lights the shields
        assert "END lamps held 0" in out


@pytest.mark.parametrize("slug,start", STACK_STARTS, ids=[s for s, _ in STACK_STARTS])
def test_a_mode_runs_to_its_own_end_when_the_game_starts_nothing(harness, slug, start):
    out = play(harness, *start, "secs", 4)
    assert not has(out, NAMES[slug], "the game's own mode began")


def test_the_huds_second_badge_slot_is_named_as_the_kit_finds_it():
    from pinball_decryptor.plugins.stern import mode_hud
    names = mode_hud.hud_names("maser_barrage")
    assert names["Timer2"] == "PadMode_maser_barrage_Hud_Timer2"
    assert names["Timer2_Num"] == "PadMode_maser_barrage_Hud_Timer2_Num"
    kit = (EX / "intricate_kit.h").read_text(encoding="utf-8")
    assert '".PadMode_%s_Hud_Timer2"' in kit and '".PadMode_%s_Hud_Timer2.PadMode_%s_Hud_Timer2_Num"' in kit
    assert mode_hud.TIMER2_DY - mode_hud.TIMER_DY == 109.0                   # the stock badges' slot pitch


MASER_X3 = ["shot", "Maser target", "ms", 300] * 3


@pytest.mark.parametrize("busy", [("multiball", 1, 0, ">> multiball 0"), ("balls", 2, 1, ">> balls in play 1"),
                                  ("battle", 1, 0, ">> battle 0"), ("timed", 1, 0, ">> timed 0")],
                         ids=["games_multiball", "two_balls", "games_battle", "games_timed_mode"])
@pytest.mark.parametrize("mode,qualify,again", [
    ("KING GHIDORAH", POWERLINES, ["shot", "Powerline left"]),
    ("OXYGEN DESTROYER", SPINS, ["shot", "Left spinner"]),
    ("MASER BARRAGE", MASER_X3, ["shot", "Maser target"]),
    ("GODZILLA ANGRY", ["trigger", "godzilla_angry.light", "secs", 1, "shot", "Building"], ["shot", "Building"]),
    ("KIRYU", ["raw", "0x20000"] * 30, ["raw", "0x20000"]),
    ("BIOLLANTE", ["shot", "Left ramp", "ms", 300] * 6, ["shot", "Right ramp"]),
    ("DESTOROYAH", ["raw", "0x2000"] * 30, ["raw", "0x2000"]),
], ids=["ghidorah", "oxygen", "maser", "godzilla_angry", "kiryu", "biollante", "destoroyah"])
def test_a_single_ball_mode_waits_out_the_games_modes_still_ready(harness, busy, mode, qualify, again):
    cmd, on, off, over = busy
    # two qualifying shots after it: after a battle ANGUIRUS shows its total, which gives way to the first
    out = play(harness, cmd, on, *qualify, cmd, off, "secs", 1, *again, "secs", 1, *again, "secs", 1)
    waited = _at(out, "[%s] not started" % mode)
    assert waited is not None, out[-2000:]
    assert has(out, mode, "is running - still ready")
    begun = _at(out, "[%s] START" % mode)
    assert begun is not None and begun > _at(out, over), out[-2000:]   # the shot after it


# ---- PAD-353: a display of the game's is never held back; the HUD keeps its words off it --------------------
def test_a_modes_words_wait_while_a_display_of_the_games_has_the_screen(harness):
    """The Magna-Grab's screen waited for a mode's hold and Godzilla kept its magnet on (PAD-353): the game's
    displays now play as they come, so while one has the screen the mode's middle words are blank, its badge
    stays, and its words are back when the display is gone."""
    s = "maser_barrage"
    out = play(harness, *MASER3, "secs", 4, "covered", 1, "secs", 1, "covered", 0, "secs", 1)
    on, off = _at(out, ">> covered 1"), _at(out, ">> covered 0")

    def last(field, t):
        said = [w for ms, w in hud(out, s, field) if ms <= t]
        return said[-1] if said else None

    assert last("Title", on) == "MASER BARRAGE" and last("C1_Value", on) not in (None, " ")
    assert has(out, "MASER BARRAGE", "hud maser_barrage: its words wait while a display of the game's has the screen")
    for field in ("Title", "Line", "Award", "AwardSub", "C1_Label", "C1_Value", "C2_Value", "C3_Value"):
        assert last(field, off) == " ", field
    timer = re.findall(r"^\s*(\d+) SHOW PadMode_%s_Hud\.PadMode_%s_Hud_Timer 0$" % (s, s), out, re.M)
    assert not [t for t in timer if on <= int(t) <= off]                     # the badge at the edge stays
    assert any(on <= ms <= off for ms, _w in hud(out, s, "Timer_Num"))       # and keeps counting
    assert has(out, "MASER BARRAGE", "hud maser_barrage: its words are back")
    assert hud_next(out, s, "Title", off) == "MASER BARRAGE"


# ---- PAD-347: an isolated mode BLOCKS the game's modes while it runs, unless its assets file says give_way ------
@pytest.mark.parametrize("slug,start", STACK_STARTS, ids=[s for s, _ in STACK_STARTS])
def test_an_isolated_mode_blocks_the_games_modes_from_its_start_to_its_end(harness, slug, start):
    mode = NAMES[slug]
    out = play(harness, *start, "secs", 2, "ball_end", "ms", 20)
    begun = _at(out, "[%s] START" % mode)
    on = _at(out, "BLOCK 1 %s" % mode)
    assert on is not None and on <= begun, out[-2000:]                       # before anything of its own
    assert has(out, mode, "isolated: blocks the game's modes the port lets it refuse while it runs")
    ended = _at(out, "[%s] END (ball ended)" % mode)
    off = _at(out, "BLOCK 0 %s" % mode)
    assert ended is not None and off is not None and off <= ended + 20, out[-2000:]


def test_game_modes_give_way_in_its_assets_file_means_it_blocks_nothing(harness, tmp_path):
    d = tmp_path / "dump_gw"
    d.mkdir()
    (d / "maser_barrage.assets").write_text("name MASER BARRAGE\ngame_modes give_way\n")
    out = play_own(harness, str(d), *MASER3, "secs", 2, "ball_end", "ms", 20)
    assert _at(out, "[MASER BARRAGE] START") is not None
    assert "BLOCK 1 MASER BARRAGE" not in out
    assert has(out, "MASER BARRAGE", "isolated: gives way - one of the game's modes starting ends it")


# ---- PAD-379: GODZILLA ANGRY - EHoH's Gappa Angry: a RAGE meter of every switch, a chase in staged locks ----------
def _ga_super(out):
    """5,000,000 and 10,000 for every switch of the chase (each shot dispatches 0x1 first)"""
    start, baby = _at(out, "[GODZILLA ANGRY] START"), _at(out, "[GODZILLA ANGRY] BABY FOUND")
    shots = [int(t) for t in re.findall(r"^\s*(\d+) >> shot ", out, re.M)]
    return 5000000 + 10000 * len([t for t in shots if start < t <= baby])


def test_godzilla_angry_every_switch_fills_the_rage_meter_and_level_five_lights_the_building(harness):
    s = "godzilla_angry"
    out = play(harness, "secs", 1, *(["raw", "0x1", "tick", 1] * 749), "secs", 1, "raw", "0x1", "secs", 3)
    for lv, award in ((1, 1000000), (2, 1500000), (3, 2000000), (4, 2500000), (5, 3000000)):
        assert has(out, GA, "RAGE LEVEL %d of 5 (player 1): +%d" % (lv, award)), lv
    assert not has(out, GA, "RAGE LEVEL 6")
    lit = _at(out, "[GODZILLA ANGRY] GODZILLA IS ANGRY for player 1: the Building starts the chase")
    assert lit > _at(out, "[GODZILLA ANGRY] RAGE LEVEL 4 of 5")              # the 750th switch (100+125+150+175+200)
    assert len(re.findall(r"SCORE \+", out)) == 5
    # the meter on the glass: RAGE n/5 on the right edge's gauge, then ANGRY! full, notes in the award line
    for lv in range(1, 6):
        assert hud_said(out, s, "Gauge_Label", "RAGE %d/5" % lv), lv
    assert hud_said(out, s, "Gauge_Label", "ANGRY!") and hud_said(out, s, "Award", "GODZILLA IS ANGRY!")
    assert hud_said(out, s, "AwardSub", "SHOOT THE BUILDING")
    # the BUILDING pulses red once the light show of GODZILLA IS ANGRY is over
    pulse = _at(out, "[GODZILLA ANGRY] lights: shot 0x400000 ff0a00 pulse 700")
    assert pulse is not None and pulse > _at(out, "[GODZILLA ANGRY] show angry: over")


def test_godzilla_angry_the_meter_counts_a_quarter_at_a_time_on_the_award_line(harness):
    s = "godzilla_angry"
    out = play(harness, "secs", 1, *(["raw", "0x1", "ms", 20] * 51), "secs", 3)
    assert has(out, GA, "rage 1: 25 of 100 switch hits (player 1)") and has(out, GA, "rage 1: 50 of 100")
    assert hud_said(out, s, "Award", "75 MORE FOR RAGE 1") and hud_said(out, s, "Award", "50 MORE FOR RAGE 1")
    assert hud_said(out, s, "AwardSub", "GODZILLA IS GETTING ANGRY")
    # the gauge fills a pip at a time: 12 pips for the level's 100 hits
    on = re.findall(r"SHOW PadMode_godzilla_angry_Hud\.PadMode_godzilla_angry_Hud_Gauge\.PadMode_godzilla_angry_Hud_G(\d+)_On 1",
                    out)
    assert {int(k) for k in on} == set(range(1, 7))                       # 51 of 100: six of twelve


@pytest.mark.parametrize("busy,on,off", [("balls", 2, 1), ("multiball", 1, 0)], ids=["two_balls", "games_multiball"])
def test_godzilla_angry_rage_does_not_count_in_a_multiball(harness, busy, on, off):
    out = play(harness, "secs", 1, busy, on, "secs", 1, *(["raw", "0x1"] * 150), "secs", 1, busy, off, "secs", 1,
               *(["raw", "0x1"] * 100), "secs", 1)
    level = _at(out, "[GODZILLA ANGRY] RAGE LEVEL 1 of 5")
    assert level is not None and level > _at(out, ">> %s %s" % ("balls in play" if busy == "balls" else busy, off))
    assert not has(out, GA, "RAGE LEVEL 2")
    hidden = [t for t in _hid(out, "godzilla_angry") if t > _at(out, ">> %s %s" % (
        "balls in play" if busy == "balls" else busy, on))]
    assert hidden, "the meter stays on the glass during a multiball"


def test_godzilla_angry_rage_does_not_count_after_a_tilt_until_the_next_ball(harness):
    out = play(harness, "secs", 1, "event", "tilt", "secs", 1, *(["raw", "0x1"] * 150), "secs", 1, "ball_end",
               "secs", 1, *(["raw", "0x1"] * 100), "secs", 1)
    assert _at(out, "[GODZILLA ANGRY] RAGE LEVEL 1 of 5") > _at(out, ">> ball_end")


def test_godzilla_angry_chase_five_places_five_locks_baby_found_and_a_six_ball_multiball(harness):
    s = "godzilla_angry"
    out = play(harness, *GA_LIGHT, *GA_CHASE, "shot", "Building", "secs", 3, *GA_JP, "secs", 20, "balls", 1, "secs", 8)
    start = _at(out, "[GODZILLA ANGRY] START")
    assert has(out, GA, "START (the Building, GODZILLA ANGRY lit): player 1, place 1 (ADONOA ISLAND), 0 lock(s)")
    assert _at(out, "BALL SAVE 5 s") == start and _at(out, "DISPLAY 180 GODZILLA ANGRY") <= start
    assert has(out, GA, "LOCK 1 at Godzilla target (ADONOA ISLAND): +1000000")
    assert has(out, GA, "YOKKAICHI: Left ramp +1000000") and has(out, GA, "YOKKAICHI: Right ramp +1025000")
    assert has(out, GA, "LOCK IS LIT at Maser target")
    assert has(out, GA, "LOCK 2 at Maser target (YOKKAICHI): +2100000")       # twice 500,000 +500,000 +2 x 25,000
    assert has(out, GA, "LOCK 3 at Godzilla target (OSAKA)") and has(out, GA, "LOCK 4 at Maser target (KYOTO)")
    assert has(out, GA, "MAKUHARI: Powerline center +2600000")
    assert has(out, GA, "LOCK 5 at Godzilla target (MAKUHARI)")
    assert has(out, GA, "BABY: the Building is BABY FOUND for 30 s")
    assert has(out, GA, "BABY FOUND: SUPER JACKPOT +%d (switches built it)" % _ga_super(out))
    baby = _at(out, "[GODZILLA ANGRY] BABY FOUND")
    assert _at(out, "MULTIBALL 6 balls, save 15 s") == baby and _at(out, "DISPLAY 190 GODZILLA ANGRY") == baby
    assert len(re.findall(r"\[GODZILLA ANGRY\] BABY JACKPOT 1 at ", out)) == 1
    assert re.search(r"\[GODZILLA ANGRY\] \w[\w ]*: \+500000, BABY x2", out)
    babies = len(re.findall(r"\[GODZILLA ANGRY\] BABY JACKPOT \d+ at ", out))
    assert babies >= 1
    assert has(out, GA, "END (one ball left): the multiball after BABY FOUND, 5 lock(s), %d baby jackpot(s)" % babies)
    assert has(out, GA, "the RAGE meter starts again for player 1: RAGE 1 at 125 hits")
    assert end_total(out, GA) == scored(out, "", GA)
    # the glass: the place and what to shoot, the locks, the jackpot and the super across the top, the clock
    assert hud_next(out, s, "Title", start) == "GODZILLA ANGRY!"
    assert hud_said(out, s, "Line", "LOCK IS LIT AT THE CAPTIVE BALL")
    assert hud_said(out, s, "Line", "YOKKAICHI: LEFT RAMP, RIGHT RAMP") and hud_said(out, s, "Line", "YOKKAICHI: RIGHT RAMP")
    assert hud_said(out, s, "Line", "OSAKA: BIG LOOP, BUILDING") and hud_said(out, s, "Line", "MAKUHARI: 5 LIT SHOTS TO GO")
    assert hud_said(out, s, "Line", "SHOOT THE BUILDING: BABY IS THERE")
    assert hud_said(out, s, "C1_Value", "5/5") and hud_said(out, s, "C3_Label", "SUPER")
    assert hud_said(out, s, "Award", "SUPER JACKPOT") and hud_said(out, s, "Title", "ANGRY MULTIBALL")
    assert hud_said(out, s, "Gauge_Label", "LOCKS") and hud_said(out, s, "Gauge_Label", "MULTIPLIER")
    assert hud_next(out, s, "Title", _at(out, "[GODZILLA ANGRY] END")) == "GODZILLA AND BABY"
    # the lights: the lock white and blinking, the place's shots red, BABY green over the orange jackpots
    assert "[GODZILLA ANGRY] lights: shot 0x80000 ffffff blink 700" in out
    assert "[GODZILLA ANGRY] lights: shot 0x300000 ff0a00 solid" in out
    assert re.search(r"\[GODZILLA ANGRY\] lights: shot 0x[0-9a-f]+ ff5000 solid; shot 0x[0-9a-f]+ 00ff3c blink 200", out)


def test_godzilla_angry_the_clock_running_out_turns_the_locks_into_a_smaller_multiball(harness):
    out = play(harness, *GA_LIGHT, "shot", "Building", "secs", 1, "shot", "Godzilla target", "secs", 32,
               "balls", 1, "secs", 25)
    assert has(out, GA, "YOKKAICHI's clock ran out with 1 lock(s): they become a 2-ball multiball")
    out_mb = _at(out, "MULTIBALL 2 balls, save 15 s")
    assert out_mb is not None and out_mb == _at(out, "[GODZILLA ANGRY] ANGRY MULTIBALL (the clock ran out): 2 balls")
    assert has(out, GA, "END (one ball left): a smaller multiball, 1 lock(s)")
    assert hud_said(out, "godzilla_angry", "Award", "THE LOCKS BREAK LOOSE")


def test_godzilla_angry_a_drain_mid_chase_keeps_the_place_and_its_locks_for_the_next_ball(harness):
    s = "godzilla_angry"
    out = play(harness, *GA_LIGHT, "shot", "Building", "secs", 1, "shot", "Godzilla target", "secs", 1,
               "shot", "Left ramp", "shot", "Right ramp", "secs", 1, "shot", "Maser target", "secs", 1, "ball_end",
               "secs", 2, "shot", "Building", "secs", 2)
    assert has(out, GA, "END (ball ended): the chase, 2 lock(s)")
    assert has(out, GA, "START (the Building, GODZILLA ANGRY lit): player 1, place 3 (OSAKA), 2 lock(s)")
    assert hud_said(out, s, "Award", "THE TRAIL AGAIN") and hud_said(out, s, "AwardSub", "OSAKA")


def test_godzilla_angry_with_no_lock_the_trail_goes_cold_and_the_building_starts_it_again(harness):
    out = play(harness, *GA_LIGHT, "shot", "Building", "secs", 32, "shot", "Building", "secs", 1)
    assert has(out, GA, "the trail goes cold at ADONOA ISLAND: still angry, the Building starts the chase again")
    assert has(out, GA, "END (the trail went cold)")
    assert len(re.findall(r"\[GODZILLA ANGRY\] START", out)) == 2
    assert "MULTIBALL" not in out


def test_godzilla_angry_a_lit_shot_puts_a_short_clock_back_to_fifteen(harness):
    out = play(harness, *GA_LIGHT, "shot", "Building", "secs", 1, "shot", "Godzilla target", "secs", 20,
               "shot", "Left ramp", "secs", 1)
    assert has(out, GA, "the clock back up to 15 s")


# ---- PAD-379: SPACEGODZILLA - lock lighting that gets harder each time, supers worth the sum ----------------------
def test_spacegodzilla_locks_get_harder_to_light_each_multiball(harness):
    stop = ["secs", 2, "trigger", "spacegodzilla.stop", "secs", 12, "balls", 1, "secs", 1]
    out = play(harness, *SG_FIRST, *stop, *SG_SECOND, *stop, *SG_THIRD, "secs", 2)     # each 1.5 s after its crystal
    assert has(out, SG, "Shield target left: every lock is lit (3) for player 1")
    for k in (1, 2, 3):
        assert has(out, SG, "CRYSTAL %d PLANTED at Big loop (player 1): +%d" % (k, 250000 * k))
    starts = re.findall(r"\[SPACEGODZILLA\] START \(the third crystal\): player 1, ([\w. ]+), 3 balls", out)
    assert starts == ["CRYSTAL TOWERS", "M.O.G.U.E.R.A.", "SPACE BEAST"]
    assert has(out, SG, "Shield target center: a lock is lit (1 lit, 0 planted) for player 1")
    assert has(out, SG, "Shield target right: 1 of 2 for the next lock (player 1)")
    assert has(out, SG, "Shield target left: a lock is lit (1 lit, 0 planted) for player 1")
    assert len(re.findall(r"MULTIBALL 3 balls, save 15 s", out)) == 3
    assert hud_said(out, "spacegodzilla", "Award", "LOCKS ARE LIT") and hud_said(out, "spacegodzilla", "Award",
                                                                                 "CRYSTAL 2 PLANTED")


def test_spacegodzilla_towers_fall_the_super_is_the_sum_and_adds_a_ball(harness):
    s = "spacegodzilla"
    out = play(harness, "trigger", "spacegodzilla.start", "secs", 1, *SG_TOWERS_DOWN, "secs", 1, *SG_LOOP, "secs", 2,
               "shot", "Left ramp", "secs", 1, "balls", 1, "secs", 25)
    for k, v in enumerate((1000000, 1100000, 1200000, 1300000, 1400000, 1500000), 1):
        assert re.search(r"\[SPACEGODZILLA\] JACKPOT %d at [\w ]+: \+%d, the tower " % (k, v), out), k
    assert has(out, SG, "SUPER JACKPOT lit at Big loop for 20 s (every tower down): 7500000")
    assert has(out, SG, "SUPER JACKPOT 1 at Big loop: +7500000 (the sum of 6 jackpots)")
    assert "ADD-A-BALL 1, save 10 s" in out and has(out, SG, "the super adds a ball (1)")
    assert has(out, SG, "the crystal towers grow back: 3 jackpots each")
    assert has(out, SG, "END (one ball left): CRYSTAL TOWERS, 7 jackpot(s), 1 super(s), 1 ball(s) added")
    assert hud_said(out, s, "Award", "LEFT RAMP TOWER FALLS") and hud_said(out, s, "Line", "SUPER JACKPOT: SHOOT THE BIG LOOP")
    assert hud_next(out, s, "Title", _at(out, "[SPACEGODZILLA] END")) == "SPACEGODZILLA FALLS"
    assert "[SPACEGODZILLA] lights: shot 0x100000 be28ff blink 300; shot 0x400000 be28ff solid; shot 0x200000 be28ff solid" in out


def test_spacegodzilla_moguera_shields_raise_every_jackpot(harness):
    stop = ["secs", 2, "trigger", "spacegodzilla.stop", "secs", 12, "balls", 1, "secs", 1]
    out = play(harness, *SG_FIRST, *stop, *SG_SECOND, "secs", 2, "shot", "Shield target left", "ms", 300,
               "shot", "Left ramp", "secs", 1)
    assert has(out, SG, "spiral grenade at Shield target left: the jackpot base 1750000")
    assert re.search(r"\[SPACEGODZILLA\] JACKPOT 1 at Left ramp: \+1750000, the tower cracks", out)


def test_spacegodzilla_nothing_lights_or_locks_during_a_multiball_and_a_full_set_waits_for_the_games_mode(harness):
    out = play(harness, "balls", 2, "secs", 1, *SG_FIRST, "balls", 1, "secs", 1, *SG_LOOP)
    assert not has(out, SG, "every lock is lit") and not has(out, SG, "CRYSTAL")
    out = play(harness, "shot", "Shield target left", "ms", 300, *(SG_LOOP * 2), "timed", 1, "secs", 1, *SG_LOOP,
               "secs", 2, "timed", 0, "secs", 1, *SG_LOOP, "secs", 1)
    assert has(out, SG, "not started (the third crystal): one of the game's modes is running - still ready") or \
        has(out, SG, "not started (the third crystal): a stock mode is running - still ready")
    started = _at(out, "[SPACEGODZILLA] START")
    assert started is not None and started > _at(out, ">> timed 0")
    assert has(out, SG, "START (the Big loop, three crystals planted)")


# ---- PAD-379: KIRYU - charge the Absolute Zero, fire it or push your luck ---------------------------------------
def test_kiryu_starts_on_thirty_mechagodzilla_spins_then_forty(harness):
    out = play(harness, *(["raw", "0x20000", "tick", 1] * 30), "secs", 1, "trigger", "kiryu.stop", "secs", 12,
               *(["raw", "0x20000"] * 39),
               "secs", 1, "raw", "0x20000", "secs", 1)
    starts = [int(t) for t in re.findall(r"^\s*(\d+) \[KIRYU\] START", out, re.M)]
    assert len(starts) == 2
    assert has(out, "KIRYU", "START (the Mechagodzilla spinner): player 1, 40 s") and has(out, "KIRYU", "next time 40 spins")
    assert has(out, "KIRYU", "Shield ramp spinner 40 of 40 (player 1)")
    assert hud_said(out, "kiryu", "Award", "29 SPINS TO KIRYU") and hud_said(out, "kiryu", "Award", "1 SPIN TO KIRYU")


def test_kiryu_charges_on_lit_shots_and_fires_at_the_captive_ball(harness):
    s = "kiryu"
    charge = ["shot", "Left ramp", "ms", 300, "shot", "Right ramp", "ms", 300, "shot", "Building", "ms", 300,
              "shot", "Big loop", "ms", 300, "shot", "Maser target", "ms", 300, "shot", "Shield target left", "ms", 300,
              "shot", "Shield target center", "ms", 300, "shot", "Shield target right", "ms", 300,
              "shot", "Left ramp", "ms", 300]
    out = play(harness, *KIRYU_SPINS, "secs", 1, *charge, "secs", 1, "shot", "Godzilla target", "secs", 5)
    assert has(out, "KIRYU", "Left ramp: +750000, charge +15%") and has(out, "KIRYU", "Maser target: +750000, charge +10%")
    assert has(out, "KIRYU", "the charge passes 100% (Left ramp): x1")
    fired = re.search(r"\[KIRYU\] ABSOLUTE ZERO fired \(the captive ball\): x1 at 109%, \+(\d+)", out)
    assert fired and int(fired.group(1)) == 10000000 + (9 * 750000) // 4
    end = _at(out, "[KIRYU] END (fired)")
    assert end - _at(out, "[KIRYU] ABSOLUTE ZERO fired") == 4000          # the shot's moment, then the ending
    assert has(out, "KIRYU", "END (fired): FIRED, the charge 109%, 0 vent(s)")
    assert hud_said(out, s, "Award", "ABSOLUTE ZERO READY") and hud_said(out, s, "Line", "FIRE: THE CAPTIVE BALL  -  OR CHARGE ON")
    assert hud_said(out, s, "C1_Value", "109%") and hud_said(out, s, "C3_Sub", "X2 AT 200%")
    assert hud_next(out, s, "Title", end) == "KIRYU WINS"
    assert "[KIRYU] lights: shot 0x1388700000 8cdcff solid; shot 0x1000000000080000 ffffff blink 300" in out


def test_kiryu_overheats_from_two_hundred_percent_and_vents_the_charge(harness):
    out = play(harness, "trigger", "kiryu.start", "secs", 1, "trigger", "kiryu.charge=215", "secs", 14,
               "trigger", "kiryu.charge=305", "secs", 1, "raw", "0x1000000000000000", "secs", 6)
    assert has(out, "KIRYU", "OVERHEATING: 12 s to fire") and has(out, "KIRYU", "KIRYU VENTS: the reactor ran too hot at 215%")
    assert has(out, "KIRYU", "the charge passes 300% (trigger file): x3")
    assert has(out, "KIRYU", "ABSOLUTE ZERO fired (the action button): x3 at 305%, +30000000")
    assert hud_said(out, "kiryu", "Line", "OVERHEATING! FIRE NOW") and hud_said(out, "kiryu", "Gauge_Label", "OVERHEAT")
    assert hud_said(out, "kiryu", "Award", "KIRYU VENTS")


@pytest.mark.parametrize("charge,fired", [(150, True), (60, False)], ids=["ready_fires_itself", "not_ready_is_lost"])
def test_kiryu_the_clock_running_out(harness, charge, fired):
    out = play(harness, "trigger", "kiryu.start", "secs", 1, "trigger", "kiryu.charge=%d" % charge, "secs", 45)
    if fired:
        assert has(out, "KIRYU", "the clock ran out at 150%: Kiryu fires on its own, x1, no bonus")
        assert has(out, "KIRYU", "ABSOLUTE ZERO fired (the clock ran out): x1 at 150%, +10000000")
        assert has(out, "KIRYU", "END (fired): FIRED")
    else:
        assert has(out, "KIRYU", "END (time ran out): not fired, the charge 60%")


# ---- PAD-379: BIOLLANTE - a switch frenzy whose sap jackpot the vine banks collect -------------------------------
def test_biollante_starts_on_six_ramps_then_eight(harness):
    out = play(harness, *BIO_RAMPS, "secs", 1, "trigger", "biollante.stop", "secs", 12,
               *(["shot", "Right ramp", "ms", 300] * 8), "secs", 1)
    assert len(re.findall(r"\[BIOLLANTE\] START \(the ramps\)", out)) == 2
    assert has(out, "BIOLLANTE", "ramps 8 of 8 (player 1)") and has(out, "BIOLLANTE", "next time 8 ramps")
    assert hud_said(out, "biollante", "Award", "5 RAMPS TO BIOLLANTE")


def test_biollante_every_switch_feeds_the_sap_three_banks_bring_the_beast_and_the_final_blow(harness):
    s = "biollante"
    out = play(harness, *BIO_RAMPS, "secs", 1, *(BIO_BANKS * 2), "secs", 1,
               "shot", "Shield target left", "shot", "Shield target center", "shot", "Shield target right", "secs", 2,
               "shot", "Building", "secs", 12)
    # the first bank: two slingshots and the three shield vines are five switches at 100,000
    assert has(out, "BIOLLANTE", "VINES CUT: THE SHIELD VINES, the SAP JACKPOT x1: +500000 (the sap was 500000)")
    # the second: a slingshot and three powerline vines at 125,000 (a bank cut)
    assert has(out, "BIOLLANTE", "VINES CUT: THE POWERLINE VINES, the SAP JACKPOT x2: +1000000 (the sap was 500000)")
    assert has(out, "BIOLLANTE", "BEAST FORM: the Building is the final blow for 20 s")
    collects = [int(v) for v in re.findall(r"\[BIOLLANTE\] VINES CUT: .*?: \+(\d+)", out)]
    assert len(collects) == 3
    assert has(out, "BIOLLANTE", "FINAL BLOW at Building: +%d" % sum(collects))
    assert has(out, "BIOLLANTE", "END (the final blow): WON")
    assert end_total(out, "BIOLLANTE") == scored(out, "", "BIOLLANTE")
    assert hud_said(out, s, "Award", "SAP JACKPOT X2") and hud_said(out, s, "Title", "BIOLLANTE BEAST")
    assert hud_said(out, s, "C3_Value", "125K") and hud_said(out, s, "C1_Value", "2/3")
    assert hud_next(out, s, "Title", _at(out, "[BIOLLANTE] END")) == "BIOLLANTE IS FREE"
    assert "[BIOLLANTE] lights: shot 0x400000 ffaa00 blink 700" in out


def test_biollante_a_vine_puts_a_short_clock_back_to_fifteen_and_the_pop_bumper_gives_a_second(harness):
    out = play(harness, *BIO_RAMPS, "secs", 30, "shot", "Shield target left", "secs", 1)
    assert has(out, "BIOLLANTE", "the clock back up to 15 s")
    out = play(harness, *BIO_RAMPS, "secs", 30, *(["shot", "Pop bumper"] * 5), "secs", 14)
    assert not has(out, "BIOLLANTE", "END")                                     # 10 s left + 5 pops: still on
    out = play(harness, *BIO_RAMPS, "secs", 30, *(["shot", "Pop bumper"] * 5), "secs", 16)
    assert has(out, "BIOLLANTE", "END (time ran out): not won")


# ---- PAD-379: DESTOROYAH - TWD's Horde: the aggregates advance, closer kills pay more -------------------------------
def test_destoroyah_starts_on_thirty_center_spins(harness):
    out = play(harness, *(["raw", "0x2000"] * 30), "secs", 1)
    assert has(out, "DESTOROYAH", "START (the center spinner): player 1, 3 waves, 3 city hits allowed; next time 40 spins")


def test_destoroyah_an_aggregate_advances_far_near_close_and_hits_the_city(harness):
    out = play(harness, "trigger", "destoroyah.start", "secs", 4, "secs", 21, "secs", 2)
    came = _at(out, "[DESTOROYAH] an aggregate comes over the top at")
    assert came is not None
    adv = [int(t) for t in re.findall(r"^\s*(\d+) \[DESTOROYAH\] an aggregate advances to [\w ]+ \((?:NEAR|CLOSE)", out, re.M)]
    assert adv and adv[0] - came == 7000
    assert has(out, "DESTOROYAH", "an aggregate got through at") and has(out, "DESTOROYAH", "the city is hit (1 of 3)")
    assert hud_said(out, "destoroyah", "Award", "THE CITY IS HIT") and hud_said(out, "destoroyah", "AwardSub", "2 HITS LEFT")
    out = play(harness, "trigger", "destoroyah.start", "secs", 60)
    assert has(out, "DESTOROYAH", "the city is hit (3 of 3)") and has(out, "DESTOROYAH", "END (the city fell): not won")
    assert hud_next(out, "destoroyah", "Title", _at(out, "[DESTOROYAH] END")) == "DESTOROYAH WINS"


def test_destoroyah_a_kill_pays_more_the_closer_it_is(harness):
    out = play(harness, "trigger", "destoroyah.start", "secs", 4, *DE_FAR, "secs", 2)
    assert re.search(r"\[DESTOROYAH\] KILL 1 of 3 at Powerline \w+ \(FAR, x1\): \+1000000", out)
    out = play(harness, "trigger", "destoroyah.start", "secs", 11.5, *DE_NEAR, "secs", 1)
    assert re.search(r"\[DESTOROYAH\] KILL 1 of 3 at [\w ]+ \(NEAR, x2\): \+2000000", out)
    out = play(harness, "trigger", "destoroyah.start", "secs", 18.5, *DE_CLOSE, "secs", 1)
    assert re.search(r"\[DESTOROYAH\] KILL 1 of 3 at [\w ]+ \(CLOSE, x4\): \+4000000", out)
    assert "[DESTOROYAH] lights: shot 0x" in out


def test_destoroyah_a_cleared_wave_pays_every_kill_again_and_the_perfect_form_pays_them_all(harness):
    s = "destoroyah"
    wave1 = ["secs", 4] + DE_FAR + ["secs", 2] + DE_FAR + ["secs", 2] + DE_FAR
    out = play(harness, "trigger", "destoroyah.start", *wave1, "secs", 2, "trigger", "destoroyah.boss", "secs", 2,
               "shot", "Building", "ms", 400, "shot", "Building", "ms", 400, "shot", "Building", "secs", 12)
    assert has(out, "DESTOROYAH", "WAVE 1 CLEARED: the WAVE SUPER +3000000")
    assert has(out, "DESTOROYAH", "WAVE 2: 4 kills, advancing every 6000 ms")
    assert has(out, "DESTOROYAH", "PERFECT FORM hit 3 of 3: +5000000")
    kills = sum(int(v) for v in re.findall(r"\[DESTOROYAH\] KILL \d+ of \d+ at .*: \+(\d+)", out))
    assert has(out, "DESTOROYAH", "DESTOROYAH DEFEATED: SUPER JACKPOT +%d (every kill again)" % kills)
    assert has(out, "DESTOROYAH", "END (the perfect form defeated): WON")
    assert hud_said(out, s, "Award", "WAVE 1 CLEARED") and hud_said(out, s, "Title", "PERFECT DESTOROYAH")
    assert hud_next(out, s, "Title", _at(out, "[DESTOROYAH] END")) == "DESTOROYAH DEFEATED"


# ---- PAD-379: the pack's kit, its METER ----------------------------------------------------------------------------
def test_a_meter_gives_way_to_another_modes_note_and_comes_back(harness):
    """kit_hud_meter (GODZILLA ANGRY's rage) is the politest thing on the glass: KING GHIDORAH's qualification note
    takes the place at once, and the meter is back when the note is gone."""
    out = play(harness, "secs", 1, *(["raw", "0x1"] * 10), "secs", 1, "shot", "Powerline left", "secs", 3)
    note = hud_at(out, "ghidorah_heads", "Award", "POWERLINES 1 OF 3")
    assert note is not None
    gone = [t for t in _hid(out, "godzilla_angry") if t <= note + 20]
    assert gone, "the meter did not give way"
    back = re.findall(r"^\s*(\d+) SHOW PadMode_godzilla_angry_Hud 1$", out, re.M)
    assert any(int(t) > note + 1900 for t in back), "the meter did not come back"
