"""PAD-1401: several of a maker's own modes at once - a base and layers over it.

- Everywhere: a blocks program's With my other modes choice (normalize, the checks, the C it makes), and the
  runtime's layer calls declared in pad_mode.h and defined in the runtime and the desk harness.
- The desk harness (an ELF host C compiler: WSL or Linux): a base mode with layers over it, played against
  the fake game - shots go top-down and a layer can keep them, an insert a layer holds stays its while the
  base lights it and is the base's again after, a layer lives inside its parent, a wizard stands the ones
  under it still.
"""
import os
import re
import shutil
import subprocess
import sys

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM

SDK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu", "modes", "sdk")
CALLS = ("pm_begin_layer", "pm_layer_top", "pm_paused", "pm_layers", "pm_mode_running_named",
         "pm_shot_claim", "pm_shot_taken")


def num(v):
    return {"k": "num", "v": v}


def mode(name, start_shot, seconds, points, light=None, **kw):
    """A small blocks mode: started by `start_shot` while idle, every shot while it runs pays `points`,
    and it lights the Right ramp in `light` (an "#rrggbb") as it starts."""
    scripts = [
        {"hat": {"kind": "shot", "shot": start_shot, "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "any_shot", "when": "running"}, "do": [{"op": "score", "points": num(points)}]},
    ]
    if light:
        scripts.append({"hat": {"kind": "mode_start"}, "do": [
            {"op": "light_shot", "shot": "Right ramp", "color": light, "pattern": "solid"}]})
    out = {"name": name, "seconds": seconds, "game_modes": "stack", "ends_on_drain": True, "scripts": scripts}
    out.update(kw)
    return out


# ---- everywhere ----------------------------------------------------------------------------------------------

def test_a_program_runs_alone_unless_it_says_layer():
    p = BM.normalize({"name": "A"})
    assert p["layer"] is False and p["inside"] == "" and p["layer_priority"] == BM.LAYER_PRIORITY
    assert p["layer_pause"] is False and p["layer_takes_shots"] is False
    p = BM.normalize({"name": "B", "inside": "FUTURE", "layer_priority": 999})
    assert p["layer"] is True                                  # a mode inside another runs over it
    assert p["layer_priority"] == 255
    assert BM.normalize({"layer_priority": "x"})["layer_priority"] == BM.LAYER_PRIORITY


def test_the_checks_refuse_a_whole_game_layer_and_a_mode_inside_itself():
    out = BM.problems(BM.normalize({"name": "FUTURE", "game_modes": "own_game", "layer": True, "scripts": []}))
    assert any("whole game" in s and "cannot run over them too" in s for s in out)
    out = BM.problems(BM.normalize({"name": "STORM", "inside": "storm", "scripts": []}))
    assert any("cannot run inside itself" in s for s in out)
    assert not any("inside" in s or "whole game" in s for s in BM.problems(BM.normalize({"name": "X", "scripts": []})))


def test_the_c_begins_a_layer_or_the_base():
    alone = BM.to_c(mode("FUTURE", "Left ramp", 60, 1000), "future")
    assert "#define LAYER            0" in alone and "#define INSIDE           \"\"" in alone
    assert "pm_begin_layer(LAYER_PRIORITY, LAYER_FLAGS) : pm_begin()" in alone
    c = BM.to_c(mode("STORM", "Right ramp", 10, 7, layer=True, layer_priority=20, layer_pause=True,
                     layer_takes_shots=True, inside="FUTURE"), "storm")
    assert "#define LAYER            1" in c
    assert "#define LAYER_PRIORITY   20u" in c
    assert "#define LAYER_FLAGS      PM_LAYER_PAUSE_BELOW" in c
    assert "#define TAKES_SHOTS      1" in c
    assert "#define INSIDE           \"FUTURE\"" in c
    assert "if (pm_paused()) return;" in c and "pm_shot_claim()" in c
    # the whole game is the base: its layer choice is not carried into the C
    own = BM.to_c(mode("WHOLE", "Left ramp", 0, 1, game_modes="own_game", layer=True), "whole")
    assert "#define LAYER            0" in own


def test_the_layer_calls_are_declared_and_defined():
    h = open(os.path.join(SDK, "pad_mode.h"), encoding="utf-8").read()
    rt = open(os.path.join(SDK, "pad_mode_runtime.c"), encoding="utf-8").read()
    desk = open(os.path.join(SDK, "examples", "desk_harness.c"), encoding="utf-8").read()
    assert "#define PM_LAYER_PAUSE_BELOW" in h
    for call in CALLS:
        assert re.search(r"\b%s\(" % call, h), call
        assert re.search(r"^(int|void) %s\(" % call, rt, re.M), call
        assert re.search(r"^(int|void) %s\(" % call, desk, re.M), call


# ---- the desk harness ------------------------------------------------------------------------------------------

def _cc():
    if os.name == "nt":
        pytest.skip("the desk harness needs an ELF linker (__start_pm_modes / __stop_pm_modes)")
    if sys.platform == "darwin":
        pytest.skip("the desk harness needs an ELF toolchain (section(\"pm_modes\"))")
    for c in ("gcc", "cc", "clang"):
        if shutil.which(c):
            return c
    pytest.skip("no host C compiler")


def play(tmp_path, programs, *args):
    """Every program (slug -> program) built into one harness with the fake game, then played."""
    cc = _cc()
    srcs = []
    for slug, program in programs.items():
        src = tmp_path / (slug + ".c")
        src.write_text(BM.to_c(program, slug), encoding="utf-8")
        srcs.append(str(src))
    exe = tmp_path / "harness"
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wextra", "-Wno-unused-parameter", "-I", SDK,
                        "-I", os.path.join(SDK, "examples"), "-o", str(exe),
                        os.path.join(SDK, "examples", "desk_harness.c")] + srcs, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "warning" not in r.stderr.lower(), r.stderr
    r = subprocess.run([str(exe), "new_game"] + [str(a) for a in args], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def scores(out):
    return [int(x) for x in re.findall(r"SCORE \+(\d+)", out)]


def test_a_layer_takes_the_shots_and_the_light_then_gives_them_back(tmp_path):
    out = play(tmp_path, {
        "future": mode("FUTURE", "Left ramp", 60, 1000, light="#0000ff"),
        "storm": mode("STORM", "Right ramp", 10, 7, light="#ff0000", layer=True, layer_priority=20,
                      layer_takes_shots=True, inside="FUTURE"),
    }, "shot", "Right ramp",                   # STORM lives inside FUTURE: not yet
       "shot", "Left ramp",                    # FUTURE starts
       "shot", "Right ramp",                   # FUTURE scores; STORM starts over it
       "shot", "Left ramp", "shot", "Building",   # STORM's alone
       "secs", 11,                             # STORM's clock runs out
       "shot", "Left ramp")                    # FUTURE's again
    assert "not started (" in out and "it runs inside FUTURE, which is not running" in out
    assert "LAYER BEGIN STORM 20 (2 run)" in out
    assert "LAMP RIGHT RAMP 0000ff solid" in out
    assert re.search(r"LAMP RIGHT RAMP ff0000 solid \d+ STORM", out)
    # FUTURE the shot STORM started on, STORM alone the two while it ran (FUTURE's 1000 is not paid), FUTURE again
    assert scores(out) == [1000, 7, 7, 1000]
    assert "[STORM] END (time ran out): 2 scores, total 14" in out
    assert "LAYER END STORM (1 run)" in out
    assert "LAMP BACK RIGHT RAMP 0000ff FUTURE" in out


def test_a_layer_inside_another_ends_with_it(tmp_path):
    out = play(tmp_path, {
        "future": mode("FUTURE", "Left ramp", 5, 1000),
        "storm": mode("STORM", "Right ramp", 60, 7, layer=True, inside="FUTURE"),
    }, "shot", "Left ramp", "shot", "Right ramp", "secs", 6)
    assert "LAYER BEGIN STORM" in out
    assert re.search(r"\[STORM\] END \(the mode it runs inside ended\)", out)


def test_a_wizard_stands_the_modes_under_it_still(tmp_path):
    out = play(tmp_path, {
        "future": mode("FUTURE", "Left ramp", 20, 1000),
        "phoenix": mode("PHOENIX", "Building", 5, 3, layer=True, layer_priority=50, layer_pause=True),
    }, "shot", "Left ramp",                    # FUTURE starts: 20 s
       "secs", 2, "shot", "Building",          # PHOENIX starts over it for 5 s, FUTURE waits
       "shot", "Right ramp",                   # PHOENIX's; FUTURE is standing still
       "secs", 30)
    assert "LAYER BEGIN PHOENIX 50 pause" in out
    # FUTURE was paid for the Building that started PHOENIX (before it began), then only PHOENIX scores
    assert scores(out) == [1000, 3]
    start = int(re.search(r"^\s*(\d+) \[FUTURE\] START", out, re.M).group(1))
    end = int(re.search(r"^\s*(\d+) \[FUTURE\] END \(time ran out\)", out, re.M).group(1))
    assert 24500 <= end - start <= 25500       # its 20 s, and the 5 s it stood still


def test_two_modes_that_run_alone_are_still_one_at_a_time(tmp_path):
    out = play(tmp_path, {
        "future": mode("FUTURE", "Left ramp", 30, 1000),
        "other": mode("OTHER", "Right ramp", 30, 5),
    }, "shot", "Left ramp", "shot", "Right ramp")
    assert "[FUTURE] START" in out and "[OTHER] START" not in out   # its shot waits while FUTURE runs
    assert scores(out) == [1000]
    assert "LAYER" not in out


# ---- form modes: mode_file.c's runners --------------------------------------------------------------------------
# The mode files' harness (tests/test_spike2_mode_roster.py) with the runtime's layers as the runtime keeps them: the
# base on pm_begin, layers on pm_begin_layer, the calls made as a runner after pm_as, and a shot delivered to the
# running layers' runners top-down before the object itself.

FORM_LAYERS = r'''
static const struct pm_mode *cur;
void pm_as(const struct pm_mode *m) { if (m) cur = m; }
static struct { const struct pm_mode *m; unsigned prio, flags; char as[40]; } lay[8];
static int n_lay;
static char base_as[40];
static int lay_of(const struct pm_mode *m) { int i; for (i = 0; i < n_lay; i++) if (lay[i].m == m) return i; return -1; }
static long rank_of(const struct pm_mode *m) { int i = lay_of(m); return i < 0 ? 0 : 1 + (long)lay[i].prio; }
static const struct pm_mode *base_m, *name_for;
static char name_next[40];
int pm_begin(void) { if (lay_of(cur) >= 0) return 1; if (running_mode || c_mode) return 0; running_mode = 1; base_m = cur; return 1; }
void pm_end(void)
{
    int i = lay_of(cur), j;
    if (i < 0) { running_mode = 0; base_as[0] = 0; return; }
    printf("LAYER END %s\n", lay[i].as);
    for (j = i + 1; j < n_lay; j++) lay[j - 1] = lay[j];
    n_lay--;
}
int pm_begin_layer(unsigned prio, unsigned flags)
{
    if (lay_of(cur) >= 0) return 1;
    lay[n_lay].m = cur, lay[n_lay].prio = prio, lay[n_lay].flags = flags, lay[n_lay].as[0] = 0;
    if (name_for == cur) snprintf(lay[n_lay].as, 40, "%s", name_next);
    name_for = 0;
    n_lay++;
    printf("LAYER BEGIN %s %u%s\n", lay[n_lay - 1].as, prio, flags & PM_LAYER_PAUSE_BELOW ? " pause" : "");
    return 1;
}
void pm_running_name(const char *n)
{
    int i = lay_of(cur);
    if (i < 0 && !(running_mode && cur == base_m)) { name_for = cur; snprintf(name_next, 40, "%s", n); return; }
    snprintf(i >= 0 ? lay[i].as : base_as, 40, "%s", n);
}
int pm_layers(void) { return n_lay; }
int pm_layer_top(void) { int i; long r = rank_of(cur); for (i = 0; i < n_lay; i++) if (rank_of(lay[i].m) > r) return 0; return 1; }
int pm_paused(void)
{
    int i; long r = rank_of(cur);
    for (i = 0; i < n_lay; i++) if ((lay[i].flags & PM_LAYER_PAUSE_BELOW) && rank_of(lay[i].m) > r) return 1;
    return 0;
}
int pm_mode_running_named(const char *n)
{
    int i;
    if (running_mode && !strcasecmp(base_as, n)) return 1;
    for (i = 0; i < n_lay; i++) if (!strcasecmp(lay[i].as, n)) return 1;
    return 0;
}
static long claim = -1;
static int delivering;
void pm_shot_claim(void) { long r = rank_of(cur); if (delivering && r > claim) claim = r; }
int pm_shot_taken(void) { return delivering && claim > rank_of(cur); }
static void deliver(const struct pm_mode *m, uint64_t mask)
{
    const struct pm_mode *o[8];
    int n = 0, i, j;
    for (i = 0; i < n_lay; i++) o[n++] = lay[i].m;
    for (i = 1; i < n; i++)
        for (j = i; j > 0 && rank_of(o[j]) > rank_of(o[j - 1]); j--) { const struct pm_mode *t = o[j]; o[j] = o[j - 1]; o[j - 1] = t; }
    claim = -1;
    delivering = 1;
    for (i = 0; i < n; i++) if (o[i]->shot) { cur = o[i]; o[i]->shot(mask); }
    cur = m;
    m->shot(mask);
    delivering = 0;
}
int main(int argc, char **argv)'''


def _form_harness(tmp_path):
    from tests import test_spike2_mode_roster as R
    cc = R._cc()
    src = R.HARNESS.replace(
        '''int pm_begin(void) { if (running_mode || c_mode) return 0; running_mode = 1; return 1; }
void pm_end(void) { running_mode = 0; }''', "").replace(
        "int main(int argc, char **argv)", FORM_LAYERS, 1).replace(
        "m->shot(strtoull(argv[++k], 0, 0));", "deliver(m, strtoull(argv[++k], 0, 0));").replace(
        "m->tick();", "cur = m, m->tick();").replace("m->ball_end();", "cur = m, m->ball_end();").replace(
        "m->init();", "cur = m, m->init();")
    assert "deliver(m," in src and "int pm_begin_layer" in src
    (tmp_path / "harness.c").write_text("#include <strings.h>\n" + src)
    stubs, _names = R.weak_stubs(open(os.path.join(SDK, "pad_mode.h"), encoding="utf-8").read())
    (tmp_path / "weak_stubs.c").write_text(stubs)
    for std in ("-std=gnu2x", "-std=gnu17"):
        r = subprocess.run([cc, std, "-w", "-I", SDK, "-c", "-o", str(tmp_path / "weak_stubs.o"),
                            str(tmp_path / "weak_stubs.c")], capture_output=True, text=True)
        if r.returncode == 0:
            break
    assert r.returncode == 0, r.stderr
    exe = tmp_path / "harness"
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wno-unused-parameter", "-I", SDK, "-o", str(exe),
                        str(tmp_path / "harness.c"), os.path.join(SDK, "mode_file.c"), str(tmp_path / "weak_stubs.o")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return exe, R


FUTURE = "name FUTURE\ngame_modes stack\ntrigger 0x2 1\nseconds 60\nshots 0x6\naward 1000\naward_ladder fixed\n"
STORM = ("name STORM\ngame_modes stack\ntrigger 0x4 1\nseconds 10\nshots 0x6\naward 7\naward_ladder fixed\n"
         "layer 20 shots\ninside FUTURE\n")


def test_a_form_mode_runs_as_a_layer_over_the_base(tmp_path):
    exe, R = _form_harness(tmp_path)
    out = R._run(exe, tmp_path, FUTURE, "tick", "3",
                 "shot", "0x4",                 # STORM lives inside FUTURE: not yet
                 "shot", "0x2",                 # FUTURE starts
                 "shot", "0x4",                 # FUTURE pays; STORM starts over it
                 "shot", "0x2",                 # STORM alone: it keeps the shots
                 "tick", "620",                 # STORM's 10 s
                 "shot", "0x2",                 # FUTURE's again
                 mode1=STORM)
    assert "STORM not started (trigger shot): it runs inside FUTURE, which is not running" in out
    assert "LAYER BEGIN STORM 20" in out
    pays = re.findall(r"shot 00000000_0000000[24]: \+(\d+)", out)
    assert pays == ["1000", "7", "1000"], out
    assert "LAYER END STORM" in out
    assert re.search(r"STORM END \(time ran out\)", out)
    assert out.index("LAYER END STORM") < out.rindex("+1000")


def test_a_form_layer_ends_with_the_mode_it_runs_inside(tmp_path):
    exe, R = _form_harness(tmp_path)
    short = FUTURE.replace("seconds 60", "seconds 3")
    out = R._run(exe, tmp_path, short, "tick", "3", "shot", "0x2", "shot", "0x4", "tick", "240", mode1=STORM)
    assert "LAYER BEGIN STORM 20" in out
    assert re.search(r"FUTURE END \(time ran out\)", out)
    assert re.search(r"STORM END \(the mode it runs inside ended\)", out)


def test_a_form_wizard_stands_the_base_still(tmp_path):
    exe, R = _form_harness(tmp_path)
    wizard = "name PHOENIX\ngame_modes stack\ntrigger 0x4 1\nseconds 5\nshots 0x6\naward 3\naward_ladder fixed\nlayer 50 pause\n"
    out = R._run(exe, tmp_path, FUTURE.replace("seconds 60", "seconds 10"), "tick", "3",
                 "shot", "0x2", "shot", "0x4", "shot", "0x2", "tick", "620", mode1=wizard)
    assert "LAYER BEGIN PHOENIX 50 pause" in out
    pays = re.findall(r"shot 00000000_0000000[24]: \+(\d+)", out)
    assert pays == ["1000", "3"], out             # FUTURE stood still: the 0x2 is PHOENIX's alone
    assert "PHOENIX END (time ran out)" in out
    assert not re.search(r"FUTURE END", out)       # 10 s, of which 5 stood still: not over after 10.3 s


# ---- the form: its fields, the mode file's lines, the checks -----------------------------------------------------

def test_a_form_mode_writes_its_layer_and_inside_lines():
    from pinball_decryptor.plugins.stern import mode_project as MP
    p = MP.profile("uncanny_xmen_le_0_98")
    s = MP.blank_spec(p, "STORM")
    assert MP.layer_lines(s) == [] and not any(l.startswith(("layer", "inside")) for l in MP.runtime_cfg(s, "storm").splitlines())
    s.layer, s.layer_priority, s.layer_pause, s.layer_shots, s.inside = True, 20, True, True, "FUTURE"
    assert MP.layer_lines(s) == ["layer          20 pause shots", "inside         FUTURE"]
    lines = MP.runtime_cfg(s, "storm").splitlines()
    assert "layer          20 pause shots" in lines and "inside         FUTURE" in lines
    assert MP.validate_layer(s) == []
    s.inside = "storm"
    assert MP.validate_layer(s) == ["It cannot run inside itself."]
    s.inside, s.layer_priority = "", 300
    assert MP.validate_layer(s) == ["Its layer's priority is a whole number from 0 to 255."]
    w = MP.blank_spec(p, "UNCANNY")
    w.game_modes, w.layer = "own_game", True
    assert MP.layer_lines(w) == []                 # the whole game is the base
    assert "cannot run over them too" in MP.validate_layer(w)[0]


def test_the_layer_lines_parse_in_mode_file_c():
    src = open(os.path.join(SDK, "mode_file.c"), encoding="utf-8").read()
    assert 'key_is(line, "layer")' in src and 'key_is(line, "inside")' in src
    assert 'key_is(a, "pause")' in src and 'key_is(a, "shots")' in src
    assert "pm_begin_layer(cfg.layer_1 - 1" in src
