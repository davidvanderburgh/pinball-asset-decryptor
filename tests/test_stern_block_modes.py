"""PAD-232: a mode made of BLOCKS (plugins/stern/block_modes.py).

Three layers, each skipping cleanly where its tools are missing:

- Everywhere: the program's checks, its save and load, the C it makes (only calls pad_mode.h
  declares, the folder's own triggers and names, strings that cannot break out of a literal or a
  comment), and a blocks mode riding through Duplicate, Copy to and Edit as C as a code mode.
- The ARM build (build_mode.sh), where arm-linux-gnueabihf-gcc and bash are.
- The desk harness (sdk/examples/desk_harness.c), where an ELF host C compiler is: programs
  played against the fake game, checking what they start, score, say, light and end.
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import code_modes as CM
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_tryit as MT

SDK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu", "modes", "sdk")
GZ = MP.GODZILLA_PRO_1_15
SHOTS = [n for n, _m in GZ.shots]


def num(v):
    return {"k": "num", "v": v}


def prog(scripts, vars=(), seconds=30, **kw):
    out = {"name": "TEST MODE", "seconds": seconds, "vars": [dict(v) for v in vars],
           "scripts": scripts}
    out.update(kw)
    return out


def _header_calls():
    with open(os.path.join(SDK, "pad_mode.h"), encoding="utf-8") as f:
        return set(re.findall(r"\b(pm_[a-z_]+)\s*\(", f.read()))


# ---- the program ---------------------------------------------------------------------------------
def test_the_starter_is_a_whole_mode_on_the_cards_shots():
    p = BM.starter("RAMP FRENZY", SHOTS)
    assert BM.problems(p, SHOTS, GZ.events) == []
    assert BM.notes(p) == []
    assert p["scripts"][0]["hat"] == {"kind": "shot", "shot": "Left ramp", "when": "idle"}
    assert BM.summary(p) == "6 scripts, 10 blocks, runs 30 seconds"


def test_a_starter_with_no_shots_known_asks_for_them():
    p = BM.starter("X", ())
    assert any("has no shot chosen" in t for t in BM.problems(p))


def test_problems_name_what_is_missing():
    p = prog([
        {"hat": {"kind": "shot", "shot": "Moon ramp", "when": "idle"}, "do": [
            {"op": "if", "cond": None, "then": [{"op": "set", "var": "nope", "value": num(1)}]},
            {"op": "score", "points": {"k": "op", "op": "+", "a": num(1.5), "b": None}},
            {"op": "light_shot", "shot": "Left ramp", "color": "red", "pattern": "blink"},
            {"op": "fly"}]},
        {"hat": {"kind": "event", "event": "earthquake", "when": "any"}, "do": []},
        {"hat": {}, "do": []},
    ], vars=[{"name": "9lives"}, {"name": "a"}, {"name": "A"}])
    got = " | ".join(BM.problems(p, SHOTS, GZ.events))
    for words in ("names Moon ramp, a shot this card does not have",
                  "has an If with no condition",
                  "sets a variable that is not there",
                  "not a whole number",
                  "has an empty number slot",
                  "lights a shot in no colour",
                  "a block this version does not know",
                  "which this card's game does not report",
                  "Script 3 starts with no When block",
                  "'9lives' is not one",
                  "Two variables are called A"):
        assert words in got, words


def test_without_a_card_no_shot_is_refused_for_its_name():
    p = prog([{"hat": {"kind": "shot", "shot": "Moon ramp", "when": "any"}, "do": []}])
    assert BM.problems(p) == []


def test_notes_do_not_stop_a_build():
    p = prog([{"hat": {"kind": "seconds_left", "seconds": 5}, "do": [
        {"op": "words", "text": "HI", "value": None}]}], seconds=0, ends_on_drain=False)
    notes = " | ".join(BM.notes(p))
    assert "No block starts the mode yet" in notes
    assert "Nothing ends this mode" in notes
    assert "seconds-left, add-time and set-the-clock blocks do nothing" in notes
    assert "tick Its own screen" in notes
    assert BM.problems(p) == []


def test_the_clock_blocks_take_a_value_and_an_old_number_still_loads():
    # PAD-372: Add seconds held a plain number before; it loads as a number value
    old = BM.normalize(prog([{"hat": {"kind": "mode_start"}, "do": [
        {"op": "if", "cond": {"k": "running"}, "then": [{"op": "add_time", "seconds": 5}]}]}]))
    assert old["scripts"][0]["do"][0]["then"][0]["seconds"] == num(5)
    assert BM.problems(old) == []
    p = prog([{"hat": {"kind": "mode_start"}, "do": [
        {"op": "add_time", "seconds": {"k": "op", "op": "*", "a": {"k": "var", "name": "n"}, "b": num(2)}},
        {"op": "set_time", "seconds": {"k": "secs_left"}},
        {"op": "set_time", "seconds": None},
        {"op": "set_time", "seconds": num(-1)},
        {"op": "add_time", "seconds": num(BM.SECONDS_MAX + 1)}]}], vars=[{"name": "n"}])
    got = BM.problems(p)
    assert "Script 1 has an empty number slot." in got
    assert "Script 1 sets the clock: 0 to %d seconds." % BM.SECONDS_MAX in got
    assert "Script 1 adds a time: %d to %d seconds." % (-BM.SECONDS_MAX, BM.SECONDS_MAX) in got
    assert len(got) == 3
    src = BM.to_c(p, "clk")
    assert "add_time((V[0][P()] * (2LL)));" in src
    assert "set_time((long long)secs_left());" in src


def test_limits_on_size_and_depth():
    deep = {"op": "start_mode"}
    for _ in range(BM.MAX_DEPTH + 2):
        deep = {"op": "if", "cond": {"k": "running"}, "then": [deep]}
    p = prog([{"hat": {"kind": "mode_start"}, "do": [deep]}])
    assert any("nested more than" in t for t in BM.problems(p))
    many = prog([{"hat": {"kind": "mode_start"}, "do": [{"op": "end_mode"}] * (BM.MAX_BLOCKS + 1)}])
    assert any("blocks: %d at most" % BM.MAX_BLOCKS in t for t in BM.problems(many))


# ---- the C -----------------------------------------------------------------------------------------
def test_the_c_only_calls_what_the_header_declares():
    p = BM.starter("RAMP FRENZY", SHOTS)
    p["scripts"].append({"hat": {"kind": "event", "event": "skill_shot", "when": "any"}, "do": [
        {"op": "multiball", "balls": 3, "save": 10}, {"op": "words", "text": "X", "value": {"k": "total"}},
        {"op": "lights_off", "shot": "*"}, {"op": "lights_off", "shot": "Left ramp"},
        {"op": "callout", "id": 1291}, {"op": "if", "cond": {"k": "stock"}, "then": [], "else": []},
        {"op": "score", "points": {"k": "balls"}}]})
    src = BM.to_c(p, "ramp_frenzy")
    used = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", src))
    assert used <= _header_calls(), used - _header_calls()
    for libc in ("malloc", "printf", "strcpy", "memcpy", "fopen"):
        assert not re.search(r"(?<![a-z_])%s\s*\(" % libc, src), libc


def test_the_c_carries_the_folders_names_and_triggers():
    src = BM.to_c(BM.starter("RAMP FRENZY", SHOTS), "ramp_frenzy")
    assert src.startswith("/* ramp_frenzy.c - RAMP FRENZY, a mode made of blocks")
    assert '#define MODE_NAME        "RAMP FRENZY"' in src
    assert '"PadMode_ramp_frenzy_Screen"' in src
    assert 'pm_trigger("ramp_frenzy.start")' in src and 'pm_trigger("ramp_frenzy.stop")' in src
    assert "PM_REGISTER(ramp_frenzy_mode);" in src
    # a folder starting with a digit is not a C name
    assert "PM_REGISTER(m_2ball_mode);" in BM.to_c(BM.starter("2 BALL", SHOTS), "2ball")


def test_words_cannot_break_out_of_a_string_or_a_comment():
    evil = 'x"); pm_score_add(1, 99); /* */ ??= \\ é'
    p = prog([{"hat": {"kind": "shot", "shot": 'Left "ramp" */', "when": "any"}, "do": [
        {"op": "log", "text": evil}, {"op": "words", "text": evil, "value": None}]}],
        vars=[{"name": "ok"}], name='BAD "NAME" */')
    src = BM.to_c(p, "bad")
    assert "??=" not in src                                             # no trigraph survives
    assert '#define MODE_NAME        "BAD \'NAME\' */"' in src            # the title loses its quotes
    body = re.sub(r'"(?:[^"\\]|\\.)*"', '""', src)                      # every literal emptied ...
    assert "pm_score_add(1, 99)" not in body                            # ... and none escaped it
    comments = re.findall(r"/\*.*?\*/", body, re.S)
    assert all("*/" not in c[2:-2] for c in comments)


def test_a_shot_that_starts_the_mode_is_not_also_one_while_it_runs():
    src = BM.to_c(BM.starter("RAMP FRENZY", SHOTS), "ramp_frenzy")
    assert "was_on = run.on" in src
    assert "(was_on && (shot & named))" in src


# ---- the project -----------------------------------------------------------------------------------
def _card(tmp_path, name="proj"):
    """A scratch project for a Godzilla Pro 1.15 card (the image itself is not there)."""
    project = str(tmp_path / name)
    os.makedirs(project)
    card = "godzilla_pro-1_15_0.raw"
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, card), "input_name": card}, f)
    return project


def test_a_blocks_mode_is_a_code_mode_with_its_blocks(tmp_path):
    project = _card(tmp_path)
    slug, path = BM.new_blocks_mode(project, "Ramp Frenzy", shots=SHOTS)
    assert slug == "ramp_frenzy" and path.endswith(os.path.join("ramp_frenzy", "ramp_frenzy.c"))
    assert CM.code_slugs(project) == ["ramp_frenzy"]
    assert MT.list_all(project) == [("ramp_frenzy", "code", "Ramp Frenzy")]
    assert BM.is_blocks(project, slug)
    p = BM.load(project, slug)
    with open(path, encoding="utf-8") as f:
        assert f.read() == BM.to_c(p, slug)
    spec = CM.load(project, slug)
    assert spec.name == "Ramp Frenzy" and spec.screen is False and not spec.has_assets()
    # an edit writes the blocks and the C again, and the assets follow its name and screen
    p["name"] = "RAMPAGE"
    p["screen"] = True
    BM.save(project, slug, p)
    with open(path, encoding="utf-8") as f:
        assert '"RAMPAGE"' in f.read()
    spec = CM.load(project, slug)
    assert spec.name == "RAMPAGE" and spec.screen is True
    # a second one with the same name gets a folder of its own
    assert BM.new_blocks_mode(project, "Ramp Frenzy", shots=SHOTS)[0] == "ramp_frenzy_2"


def test_duplicate_and_copy_to_write_the_c_for_the_new_folder(tmp_path):
    project = _card(tmp_path)
    slug, _path = BM.new_blocks_mode(project, "Ramp Frenzy", shots=SHOTS)
    new_slug, new_path = MT.duplicate_code_mode(project, slug)
    assert new_slug == "ramp_frenzy_copy"
    p = BM.load(project, new_slug)
    assert p["name"] == "Ramp Frenzy COPY"
    with open(new_path, encoding="utf-8") as f:
        assert f.read() == BM.to_c(p, new_slug)
    # Copy to a project that has the folder already: it lands as another slug
    dest = _card(tmp_path, "dest")
    BM.new_blocks_mode(dest, "Ramp Frenzy", shots=SHOTS)
    MP.copy_modes(project, dest, slugs=[slug])
    moved = [s for s in CM.code_slugs(dest) if s != "ramp_frenzy"]
    assert len(moved) == 1
    with open(os.path.join(MP.mode_folder(dest, moved[0]), moved[0] + ".c"), encoding="utf-8") as f:
        text = f.read()
    assert 'pm_trigger("%s.start")' % moved[0] in text
    assert text == BM.to_c(BM.load(dest, moved[0]), moved[0])


def test_edit_as_c_keeps_the_c_and_puts_the_blocks_away(tmp_path):
    project = _card(tmp_path)
    slug, path = BM.new_blocks_mode(project, "Ramp Frenzy", shots=SHOTS)
    with open(path, encoding="utf-8") as f:
        before = f.read()
    BM.detach(project, slug)
    assert not BM.is_blocks(project, slug)
    assert os.path.isfile(BM.blocks_path(project, slug) + ".bak")
    with open(path, encoding="utf-8") as f:
        assert f.read() == before
    assert BM.regenerate(project, slug) is False


def test_a_newer_or_broken_blocks_file_is_refused(tmp_path):
    project = _card(tmp_path)
    slug, _path = BM.new_blocks_mode(project, "Ramp Frenzy", shots=SHOTS)
    with open(BM.blocks_path(project, slug), "w", encoding="utf-8") as f:
        f.write('{"format": 99}')
    with pytest.raises(BM.BlocksError, match="newer version"):
        BM.load(project, slug)
    with open(BM.blocks_path(project, slug), "w", encoding="utf-8") as f:
        f.write("{not json")
    with pytest.raises(BM.BlocksError, match="not JSON"):
        BM.load(project, slug)


# ---- the ARM build ---------------------------------------------------------------------------------
def test_the_starter_builds_with_build_mode_sh(tmp_path):
    if os.name == "nt":
        pytest.skip("build_mode.sh runs under bash with arm-linux-gnueabihf-gcc (WSL or Linux)")
    if not shutil.which("bash") or not shutil.which("arm-linux-gnueabihf-gcc"):
        pytest.skip("no arm-linux-gnueabihf-gcc here")
    src = tmp_path / "ramp_frenzy.c"
    src.write_text(BM.to_c(BM.starter("RAMP FRENZY", SHOTS), "ramp_frenzy"), encoding="utf-8")
    out = tmp_path / "mode.so"
    r = subprocess.run(["bash", os.path.join(SDK, "build_mode.sh"), "-o", str(out), str(src),
                        os.path.join(SDK, "mode_file.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "warning" not in (r.stdout + r.stderr).lower()


# ---- the desk harness ------------------------------------------------------------------------------
def _cc():
    if os.name == "nt":
        pytest.skip("the desk harness needs an ELF linker (__start_pm_modes / __stop_pm_modes)")
    if sys.platform == "darwin":
        pytest.skip("the desk harness needs an ELF toolchain (section(\"pm_modes\"))")
    for c in ("gcc", "cc", "clang"):
        if shutil.which(c):
            return c
    pytest.skip("no host C compiler")


def play(tmp_path, program, *args, slug="blk"):
    cc = _cc()
    src = tmp_path / (slug + ".c")
    src.write_text(BM.to_c(program, slug), encoding="utf-8")
    exe = tmp_path / "harness"
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wextra", "-Wno-unused-parameter", "-I", SDK,
                        "-I", os.path.join(SDK, "examples"), "-o", str(exe), os.path.join(SDK, "examples", "desk_harness.c"), str(src)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "warning" not in r.stderr.lower(), r.stderr
    r = subprocess.run([str(exe), "new_game"] + [str(a) for a in args], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def scores(out):
    return [int(x) for x in re.findall(r"SCORE \+(\d+)", out)]


def test_the_starter_plays_start_to_finish(tmp_path):
    out = play(tmp_path, BM.starter("RAMP FRENZY", SHOTS),
               "shot", "Left ramp", "shot", "Left ramp", "shot", "Left ramp",
               "shot", "Right ramp", "shot", "Building", "secs", 36)
    assert "[RAMP FRENZY] START (a block): player 1" in out
    assert "LAMP RIGHT RAMP ffd000 blink 500 RAMP FRENZY" in out
    # the start shot pays nothing; scripts run top to bottom, so the Right ramp pays the combo
    # (500k) and then its jackpot (5M), and the Building the combo again (1M)
    assert scores(out) == [500000, 5000000, 1000000]
    assert "CALLOUT 1291" in out                                     # ten seconds left
    assert "END (time ran out): 3 scores, total 6500000" in out
    end = int(re.search(r"^\s*(\d+) \[RAMP FRENZY\] END", out, re.M).group(1))
    assert 36000 <= end <= 36200                                     # 30 s + the jackpot's 5 s
    assert "lamps held 0" in out


def test_conditions_nest_and_variables_are_per_player_and_reset(tmp_path):
    p = prog([
        {"hat": {"kind": "any_shot", "when": "any"}, "do": [{"op": "change", "var": "hits", "by": num(1)}]},
        {"hat": {"kind": "shot", "shot": "Building", "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "shot", "shot": "Maser target", "when": "running"}, "do": [
            {"op": "if", "cond": {"k": "and",
                                  "a": {"k": "cmp", "op": ">=", "a": {"k": "var", "name": "hits"}, "b": num(3)},
                                  "b": {"k": "not", "a": {"k": "stock"}}},
             "then": [{"op": "score", "points": {"k": "op", "op": "*", "a": {"k": "var", "name": "hits"},
                                                  "b": num(1000)}}],
             "else": [{"op": "score", "points": num(7)}]}]},
    ], vars=[{"name": "hits", "reset": "ball"}], seconds=0)
    out = play(tmp_path, p, "shot", "Building", "shot", "Maser target", "shot", "Maser target",
               "battle", 1, "shot", "Maser target", "battle", 0, "shot", "Maser target",
               "ball_end", "shot", "Building", "shot", "Maser target")
    # hits 2 -> else 7; hits 3 -> 3000; battle on -> else 7; hits 5 -> 5000; after the drain the
    # count starts again at 0: Building (1), Maser (2) -> else 7
    assert scores(out) == [7, 3000, 7, 5000, 7]
    assert "END (ball ended)" in out


def test_every_seconds_left_events_add_time_and_end_blocks(tmp_path):
    p = prog([
        {"hat": {"kind": "event", "event": "skill_shot", "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "every", "seconds": 2}, "do": [{"op": "score", "points": {"k": "secs_left"}}]},
        {"hat": {"kind": "seconds_left", "seconds": 3}, "do": [{"op": "callout", "role": "time_up"}]},
        {"hat": {"kind": "shot", "shot": "Left ramp", "when": "running"}, "do": [
            {"op": "add_time", "seconds": -3}]},
        {"hat": {"kind": "mode_end"}, "do": [{"op": "end_mode"}, {"op": "log", "text": "bye"}]},
    ], seconds=10)
    out = play(tmp_path, p, "event", "skill_shot", "secs", 4.05, "shot", "Left ramp", "secs", 5)
    assert "START (a block)" in out
    # every 2 s: 8 left, then 6 left; the ramp takes 3 s off (3 left at 4 s): 3 s is the
    # callout, and at 6 s one second is left
    assert scores(out)[:2] == [8, 6]
    assert "CALLOUT 1295" in out
    assert "[TEST MODE] bye" in out and "END (time ran out)" in out   # End in When it ends: no loop


def test_set_the_clock_puts_a_short_clock_back_up_and_add_takes_a_value(tmp_path):
    # MASER BARRAGE's rule (PAD-371) in blocks: a Maser target with under 10 s left puts the clock
    # back to 10 s, and the "ten seconds" call is not said again; Add seconds adds a variable's value
    p = prog([
        {"hat": {"kind": "event", "event": "skill_shot", "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "shot", "shot": "Maser target", "when": "running"}, "do": [
            {"op": "if", "cond": {"k": "cmp", "op": "<", "a": {"k": "secs_left"}, "b": num(10)},
             "then": [{"op": "set_time", "seconds": num(10)}], "else": None}]},
        {"hat": {"kind": "shot", "shot": "Left ramp", "when": "running"}, "do": [
            {"op": "set", "var": "bonus", "value": num(3)},
            {"op": "add_time", "seconds": {"k": "op", "op": "*", "a": {"k": "var", "name": "bonus"}, "b": num(2)}}]},
        {"hat": {"kind": "seconds_left", "seconds": 10}, "do": [{"op": "callout", "role": "ten_seconds"}]},
        {"hat": {"kind": "seconds_left", "seconds": 5}, "do": [{"op": "callout", "role": "time_up"}]},
    ], vars=[{"name": "bonus"}], seconds=15)
    # 15 s clock: at 6.5 s (8.5 left, the ten-second call said) the Maser target puts it to 10;
    # at 7 s (9.5 left) the Left ramp adds 3 x 2 = 6 (15.5 left); it runs out 15.5 s later
    out = play(tmp_path, p, "event", "skill_shot", "secs", 6.5, "shot", "Maser target",
               "secs", 0.5, "shot", "Left ramp", "secs", 20)
    assert out.count("CALLOUT 1291") == 2              # at 10 left, and counting down again; not at the put-back
    assert out.count("CALLOUT 1295") == 1              # 5 left, once: only after the clock came down to it
    end = int(re.search(r"^\s*(\d+) \[TEST MODE\] END \(time ran out\)", out, re.M).group(1))
    start = int(re.search(r"^\s*(\d+) \[TEST MODE\] START", out, re.M).group(1))
    assert 22400 <= end - start <= 22600               # 7 s + 15.5 s
    # a Maser target with 10 s or more left leaves the clock alone
    out = play(tmp_path, p, "event", "skill_shot", "secs", 1, "shot", "Maser target", "secs", 20)
    end = int(re.search(r"^\s*(\d+) \[TEST MODE\] END \(time ran out\)", out, re.M).group(1))
    start = int(re.search(r"^\s*(\d+) \[TEST MODE\] START", out, re.M).group(1))
    assert 14900 <= end - start <= 15100


def test_the_tabs_start_and_end_triggers_reach_it(tmp_path, monkeypatch):
    dump = tmp_path / "dump"
    dump.mkdir()
    monkeypatch.setenv("HARNESS_DUMP", str(dump))
    p = prog([{"hat": {"kind": "mode_start"}, "do": [{"op": "score", "points": num(42)}]}], seconds=0)
    out = play(tmp_path, p, "trigger", "blk.start", "secs", 1, "trigger", "blk.stop", "secs", 1)
    assert "START (trigger file)" in out and "END (trigger file)" in out
    assert scores(out) == [42]


# ---- PAD-375: the HUD -------------------------------------------------------------------------------
def var(n):
    return {"k": "var", "name": n}


def maser_hud():
    """MASER BARRAGE's chain in blocks, with its HUD as the example's (film_recipes.json): the
    multiplier, barrages and points along the top, the MASER badge, a CHAIN gauge of three."""
    return prog([
        {"hat": {"kind": "shot", "shot": "Maser target", "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "mode_start"}, "do": [{"op": "set", "var": "mult", "value": num(1)}]},
        {"hat": {"kind": "shot", "shot": "Left ramp", "when": "running"}, "do": [
            {"op": "set", "var": "step", "value": num(1)},
            {"op": "hud_text", "which": "line", "text": "NOW THE RIGHT RAMP", "value": None}]},
        {"hat": {"kind": "shot", "shot": "Right ramp", "when": "running"}, "do": [
            {"op": "set", "var": "step", "value": num(2)},
            {"op": "hud_text", "which": "line", "text": "NOW THE BUILDING", "value": None}]},
        {"hat": {"kind": "shot", "shot": "Building", "when": "running"}, "do": [
            {"op": "if", "cond": {"k": "cmp", "op": "=", "a": var("step"), "b": num(2)}, "then": [
                {"op": "score", "points": {"k": "op", "op": "*", "a": num(1000000), "b": var("mult")}},
                {"op": "change", "var": "barrages", "by": num(1)},
                {"op": "change", "var": "mult", "by": num(1)},
                {"op": "set", "var": "step", "value": num(0)},
                {"op": "hud_counter", "counter": 2, "value": var("barrages"), "sub": "COMPLETED"},
                {"op": "hud_award", "text": "BARRAGE", "value": var("barrages"), "sub": "MULTIPLIER UP",
                 "seconds": 2}], "else": None}]},
    ], vars=[{"name": "step", "reset": "mode"}, {"name": "mult", "reset": "mode"},
             {"name": "barrages", "reset": "mode"}], seconds=20,
        hud={"on": True, "line": "LEFT RAMP  >  RIGHT RAMP  >  BUILDING",
             "counters": [{"label": "MULTIPLIER", "sub": "MAX X5", "value": var("mult")},
                          {"label": "BARRAGES", "sub": ""},
                          {"label": "POINTS", "sub": "THIS MODE", "value": {"k": "total"}}],
             "timer": {"on": True, "label": "MASER", "icon": "maser"},
             "gauge": {"on": True, "label": "CHAIN", "kind": "diamond", "count": 3, "color": "#008cff",
                       "value": var("step")}})


def test_the_hud_is_the_examples_hud_in_the_assets_file(tmp_path):
    p = maser_hud()
    assert BM.problems(p, SHOTS) == [] and BM.notes(p) == []
    assert BM.hud_spec(p, "maser") == {
        "title": "TEST MODE", "line": "LEFT RAMP  >  RIGHT RAMP  >  BUILDING",
        "counters": [["MULTIPLIER", "0", "MAX X5"], ["BARRAGES", "0", " "], ["POINTS", "0", "THIS MODE"]],
        "timer": {"label": "MASER", "icon": "maser"},
        "gauge": {"label": "CHAIN", "kind": "diamond", "count": 3, "colours": [[0, 140, 255]]}}
    # an unlabelled counter at the end is not built, one in the middle is left empty; the badge
    # says the mode's name with no label of its own; no gauge unless ticked
    q = prog([], hud={"on": True, "counters": [{}, {"label": "B"}], "timer": {}})
    assert BM.hud_spec(q) == {"title": "TEST MODE", "line": " ", "counters": [[], ["B", "0", " "]],
                              "timer": {"label": "TEST MODE", "icon": "xilien"}}
    assert BM.hud_spec(prog([])) == {}
    # saved: the assets file carries it (the build draws it) and the kit sits beside the C
    project = _card(tmp_path)
    slug, path = BM.new_blocks_mode(project, "Maser", shots=SHOTS)
    folder = MP.mode_folder(project, slug)
    assert not os.path.isfile(os.path.join(folder, BM.KIT_FILE))
    BM.save(project, slug, p)
    assert CM.load(project, slug).hud == BM.hud_spec(p, slug)
    with open(os.path.join(folder, BM.KIT_FILE), encoding="utf-8") as f, \
            open(os.path.join(SDK, "examples", BM.KIT_FILE), encoding="utf-8") as g:
        assert f.read() == g.read()
    with open(path, encoding="utf-8") as f:
        assert '#include "intricate_kit.h"' in f.read()
    # switched off: no HUD in the assets, and the C no longer includes the kit
    p["hud"]["on"] = False
    BM.save(project, slug, p)
    assert CM.load(project, slug).hud == {}
    with open(path, encoding="utf-8") as f:
        assert "intricate_kit.h" not in f.read()


def test_the_hud_blocks_are_checked_and_noted():
    bad = prog([{"hat": {"kind": "mode_start"}, "do": [
        {"op": "hud_text", "which": "middle", "text": "X" * 41, "value": None},
        {"op": "hud_counter", "counter": 4, "value": None},
        {"op": "hud_award", "text": "A", "value": None, "sub": "", "seconds": 11}]}],
        hud={"on": True, "counters": [{"label": "A", "value": {"k": "var", "name": "nope"}}]})
    probs = BM.problems(bad)
    assert any("title or line" in t for t in probs)
    assert any("more than 40 letters" in t for t in probs)
    assert any("1, 2 or 3" in t for t in probs)
    assert any("1 to 10 seconds" in t for t in probs)
    assert any("HUD's counter 1 uses a variable that is not there" in t for t in probs)
    # HUD blocks with the HUD off, a counter with no label, a gauge switched off, a badge with no clock
    off = prog([{"hat": {"kind": "mode_start"}, "do": [{"op": "hud_gauge", "value": num(1)}]}])
    assert any("tick Its HUD" in t for t in BM.notes(off))
    on = prog([{"hat": {"kind": "mode_start"}, "do": [
        {"op": "hud_gauge", "value": num(1)}, {"op": "hud_counter", "counter": 2, "value": num(1)},
        {"op": "start_mode"}]}], seconds=0, ends_on_drain=True, hud={"on": True})
    words = " ".join(BM.notes(on))
    assert "counter 2, which has no label" in words and "gauge, which is switched off" in words
    assert "timer badge counts the mode's clock, and it has none" in words
    # the HUD blocks with the HUD off write nothing but a comment
    assert "kit_hud" not in BM.to_c(off, "off") and "/* hud_gauge: the mode has no HUD */" in BM.to_c(off, "off")


def test_the_hud_c_calls_only_the_header_and_the_kit():
    src = BM.to_c(maser_hud(), "maser")
    used = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", src))
    assert used <= _header_calls(), used - _header_calls()
    with open(os.path.join(SDK, "examples", BM.KIT_FILE), encoding="utf-8") as f:
        kit = set(re.findall(r"\b(kit_[a-z_]+)\s*\(", f.read()))
    kit_used = set(re.findall(r"\b(kit_[a-z_]+)\s*\(", src))
    assert kit_used and kit_used <= kit, kit_used - kit
    assert 'static struct kit_hud hud = { .slug = "maser" };' in src
    assert "pm_display_priority(180)" in src and "pm_end_holding(3000u)" in src


def test_the_hud_builds_with_build_mode_sh(tmp_path):
    if os.name == "nt":
        pytest.skip("build_mode.sh runs under bash with arm-linux-gnueabihf-gcc (WSL or Linux)")
    if not shutil.which("bash") or not shutil.which("arm-linux-gnueabihf-gcc"):
        pytest.skip("no arm-linux-gnueabihf-gcc here")
    src = tmp_path / "maser.c"
    src.write_text(BM.to_c(maser_hud(), "maser"), encoding="utf-8")
    shutil.copyfile(os.path.join(SDK, "examples", BM.KIT_FILE), str(tmp_path / BM.KIT_FILE))
    out = tmp_path / "mode.so"
    r = subprocess.run(["bash", os.path.join(SDK, "build_mode.sh"), "-o", str(out), str(src),
                        os.path.join(SDK, "mode_file.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "warning" not in (r.stdout + r.stderr).lower()


def _hud_words(out, piece):
    """Every value written to one piece of the HUD, in order."""
    return re.findall(r"WORDS PadMode_\w+?_Hud_%s: (.*)$" % piece, out, re.M)


def test_the_hud_follows_the_blocks_and_ends_with_the_total(tmp_path):
    out = play(tmp_path, maser_hud(), "shot", "Maser target", "shot", "Left ramp", "shot", "Right ramp",
               "shot", "Building", "secs", 3, "secs", 20, slug="maser")
    assert "SHOW PadMode_maser_Hud 1" in out and "DISPLAY 180 TEST MODE" in out
    assert _hud_words(out, "Title")[0] == "TEST MODE"
    assert _hud_words(out, "Line")[:3] == ["LEFT RAMP  >  RIGHT RAMP  >  BUILDING", "NOW THE RIGHT RAMP",
                                           "NOW THE BUILDING"]
    # the multiplier follows its variable; barrages is set by its block, with its own line
    assert _hud_words(out, "C1_Label")[0] == "MULTIPLIER" and _hud_words(out, "C1_Value")[:2] == ["1", "2"]
    assert _hud_words(out, "C2_Value")[:2] == ["0", "1"] and "COMPLETED" in _hud_words(out, "C2_Sub")
    assert "1.00M" in _hud_words(out, "C3_Value")         # short enough for the counter (kit_short)
    # the award for its two seconds, the badge counting the clock, the chain gauge lit 1, 2, then 0
    award = _hud_words(out, "Award")
    assert award[:3] == [" ", "BARRAGE 1", " "]
    assert "MULTIPLIER UP" in _hud_words(out, "AwardSub")
    timer = _hud_words(out, "Timer_Num")
    assert timer[0] == "20" and "10" in timer
    lit = re.findall(r"SHOW \S+_Hud_G(\d)_On 1", out)
    assert lit[:2] == ["1", "2"]
    # time up: the TOTAL for three seconds, then hidden
    assert "TEST MODE TOTAL" in _hud_words(out, "Title") and "1,000,000" in award
    end = int(re.search(r"^\s*(\d+) \[TEST MODE\] END \(time ran out\)", out, re.M).group(1))
    hidden = [int(t) for t in re.findall(r"^\s*(\d+) SHOW PadMode_maser_Hud 0", out, re.M)]
    assert any(2950 <= t - end <= 3050 for t in hidden), (end, hidden)
    assert "display priority 0" in out


def test_the_hud_steps_aside_for_the_games_modes_and_displays(tmp_path):
    p = maser_hud()
    p["screen"] = True
    out = play(tmp_path, p, "shot", "Maser target", "secs", 1, "battle", 1, "secs", 1,
               "covered", 1, "secs", 1, "covered", 0, "battle", 0, "secs", 1, "ball_end", "secs", 1, slug="maser")
    # a battle: its lines into the award line, the counters blank, the badge one slot down, its screen hidden
    assert "aside for a battle - its lines in the award line" in out
    aside = out[out.index(">> battle 1"):out.index(">> covered 1")]
    assert "Hud_Award: TEST MODE" in aside and "Hud_AwardSub: LEFT RAMP  >  RIGHT RAMP  >  BUILDING" in aside
    assert "Hud_C1_Value:  " in aside and "_Hud_Timer2 1" in aside and "_Hud_Timer 0" in aside
    assert "SHOW PadMode_maser_Screen 0" in aside
    # under a display of the game's: its words blank, the edges stay
    covered = out[out.index(">> covered 1"):out.index(">> covered 0")]
    assert "its words wait while a display of the game's has the screen" in covered
    assert "Hud_Award:  " in covered and "_Hud_Gauge 0" not in covered
    # both over: back in its places, its screen back
    back = out[out.index(">> battle 0"):out.index(">> ball_end")]
    assert "back in its places" in back and "Hud_C1_Label: MULTIPLIER" in back
    assert "SHOW PadMode_maser_Screen 1" in back
    # a drain: down at once, the display given back in the same tick
    drain = out[out.index(">> ball_end"):]
    t = int(re.search(r"^\s*(\d+) >> ball_end", out, re.M).group(1))
    assert re.search(r"^\s*%d SHOW PadMode_maser_Hud 0" % t, drain, re.M)
    assert re.search(r"^\s*%d DISPLAY 0 TEST MODE" % t, drain, re.M)


def test_an_award_before_the_mode_runs_is_a_note(tmp_path):
    p = maser_hud()
    p["scripts"].append({"hat": {"kind": "shot", "shot": "Big loop", "when": "idle"}, "do": [
        {"op": "hud_award", "text": "MASER", "value": {"k": "hits", "shot": "Big loop"}, "sub": "",
         "seconds": 2}]})
    out = play(tmp_path, p, "shot", "Big loop", "secs", 3, slug="maser")
    note = out[out.index(">> shot Big loop"):]
    assert "Hud_Award: MASER 1" in note and "Hud_AwardSub: TEST MODE" in note
    assert "SHOW PadMode_maser_Hud 1" in note and "SHOW PadMode_maser_Hud 0" in note
    assert "Hud_Title:  " in note                  # a note is the award line alone
