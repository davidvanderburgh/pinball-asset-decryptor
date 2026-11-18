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
