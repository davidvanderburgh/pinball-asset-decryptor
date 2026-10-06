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
    # PAD-398: a program that says nothing runs alone (block); these tests were written for one beside the
    # game's modes, so they say so unless a test asks otherwise (game_modes=None: the program says nothing)
    out = {"name": "TEST MODE", "seconds": seconds, "vars": [dict(v) for v in vars],
           "scripts": scripts, "game_modes": "stack"}
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


def test_the_game_modes_choice_loads_as_saved_or_as_cannot_start():
    # PAD-373; PAD-398 (David, 2026-10-05: "we should ONLY be in those modes unless explicitly noted"): a program
    # that says nothing runs alone - the game's modes cannot start and none of its features count
    p = BM.normalize(prog([], game_modes=None))
    assert p["game_modes"] == "block" and p["block_modes"] == [] and p["keep_rules"] == []
    src = BM.to_c(p, "blk")
    assert "#define GAME_MODES       2" in src and '#define KEEP_RULES       ""' in src
    assert "pm_block_rules_keep_names(KEEP_RULES);" in src
    p = BM.normalize(prog([], game_modes="block", keep_rules=["Cities", " Bridge ", 5, "a,b", ""]))
    assert p["keep_rules"] == ["Cities", "Bridge"]
    assert '#define KEEP_RULES       "Cities, Bridge"' in BM.to_c(p, "blk")
    assert "#define GAME_MODES       0" in BM.to_c(prog([], game_modes="stack"), "blk")
    p = BM.normalize(prog([], game_modes="block", block_modes=[23, 21, 21, 200, -1, "7", True]))
    assert p["game_modes"] == "block" and p["block_modes"] == [21, 23]
    src = BM.to_c(p, "blk")
    assert "#define GAME_MODES       2" in src
    assert "BLOCK_IDS[2] = {21, 23};" in src and "#define BLOCK_N          2" in src
    assert BM.normalize(prog([], game_modes="later"))["game_modes"] == "block"
    assert "#define GAME_MODES       1" in BM.to_c(prog([], game_modes="give_way"), "blk")


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
    p["game_modes"] = "block"                         # PAD-373: and what holding the game's modes off calls
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
@pytest.mark.parametrize("which", ["starter", "own clips and sounds", "light shows"])   # PAD-374, PAD-376
def test_the_starter_builds_with_build_mode_sh(tmp_path, which):
    if os.name == "nt":
        pytest.skip("build_mode.sh runs under bash with arm-linux-gnueabihf-gcc (WSL or Linux)")
    if not shutil.which("bash") or not shutil.which("arm-linux-gnueabihf-gcc"):
        pytest.skip("no arm-linux-gnueabihf-gcc here")
    src = tmp_path / "ramp_frenzy.c"
    program = {"starter": lambda: BM.starter("RAMP FRENZY", SHOTS), "own clips and sounds": _media_prog,
               "light shows": _lights_prog}[which]()
    program.update(game_modes="block", block_modes=[21, 23])      # PAD-373
    src.write_text(BM.to_c(program, "ramp_frenzy"), encoding="utf-8")
    out = tmp_path / "mode.so"
    r = subprocess.run(["bash", os.path.join(SDK, "build_mode.sh"), "-o", str(out), str(src),
                        os.path.join(SDK, "mode_file.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "warning" not in (r.stdout + r.stderr).lower()
    # PAD-377: two modes sharing a variable, a timer, the priority and the multiball wait, in ONE object
    final = prog([{"hat": {"kind": "shot", "shot": "Big loop", "when": "idle"}, "do": [
        {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": {"k": "var", "name": "maser won"}, "b": num(1)},
         "then": [{"op": "start_mode"}], "else": None}]}],
        vars=[{"name": "maser won", "reset": "game", "shared": True}], name="FINAL WARS", priority=190)
    srcs = []
    for slug, p in (("maser", _maser()), ("final", final)):
        srcs.append(tmp_path / (slug + ".c"))
        srcs[-1].write_text(BM.to_c(p, slug), encoding="utf-8")
    r = subprocess.run(["bash", os.path.join(SDK, "build_mode.sh"), "-o", str(out)] + [str(s) for s in srcs]
                       + [os.path.join(SDK, "mode_file.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "warning" not in (r.stdout + r.stderr).lower()
    nm = shutil.which("arm-linux-gnueabihf-nm")
    if nm:
        syms = subprocess.run([nm, str(out)], capture_output=True, text=True).stdout
        assert len(re.findall(r"\bpad_shared_maser_won$", syms, re.M)) == 1   # one value for both


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


# ---- PAD-377: what the kit gives a mode in C ---------------------------------------------------------
def _maser():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
    import shot_pad377
    return shot_pad377.maser_program()


def test_shared_variables_timers_and_the_start_options_are_checked():
    assert BM.problems(_maser(), shots=SHOTS) == []
    p = prog([{"hat": {"kind": "timer_done", "timer": "nope"}, "do": [
        {"op": "timer_start", "timer": "w", "ms": num(0)}, {"op": "timer_stop", "timer": ""},
        {"op": "score", "points": {"k": "timer_left", "timer": "gone"}}]}],
        vars=[{"name": "won", "reset": "mode", "shared": True}, {"name": "a b", "shared": True, "reset": "game"},
              {"name": "a_b", "shared": True, "reset": "game"}],
        timers=[{"name": "w"}, {"name": "W"}, {"name": "9x"}])
    out = BM.problems(p)
    assert any("won is shared" in t and "each ball or each game" in t for t in out)
    assert "Two variables are called a_b." in out                     # one shared value: pad_shared_a_b
    assert "Two timers are called W." in out
    assert any("timer's name '9x'" in t for t in out)
    assert any("names a timer that is not there" in t for t in out)  # the hat's, and the value's
    assert any("has no timer chosen" in t for t in out)
    assert any("1 to %d milliseconds" % BM.TIMER_MAX_MS in t for t in out)
    # shared is per name, whatever the case or a space for a _
    assert BM.shared_ident("Maser Won") == BM.shared_ident("maser_won") == "pad_shared_maser_won"
    n = BM.normalize({"priority": 999, "wait_multiball": 1})
    assert n["priority"] == BM.PRIORITY_MAX and n["wait_multiball"] is True and n["timers"] == []
    assert BM.normalize({})["priority"] == 0 and BM.normalize({})["wait_multiball"] is False
    assert BM.starter("X", SHOTS)["wait_multiball"] is True            # as the examples do
    assert any("never runs" in t for t in BM.notes(prog([{"hat": {"kind": "timer_done", "timer": "w"}, "do": []}],
                                                        timers=[{"name": "w"}])))


def test_the_kit_parts_only_call_what_the_header_declares():
    src = BM.to_c(_maser(), "maser")
    used = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", src))
    assert used <= _header_calls(), used - _header_calls()
    assert '__attribute__((weak, visibility("hidden"))) long long pad_shared_maser_won[5];' in src
    assert "#define DISPLAY_PRIORITY 180" in src and "#define WAITS_OUT_MULTIBALL 1" in src


def play_many(tmp_path, programs, *args):
    """Several blocks modes built into ONE object, as a card's are, played together."""
    cc = _cc()
    srcs = []
    for slug, program in programs.items():
        src = tmp_path / (slug + ".c")
        src.write_text(BM.to_c(program, slug), encoding="utf-8")
        srcs.append(str(src))
    exe = tmp_path / "harness"
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wextra", "-Wno-unused-parameter", "-I", SDK,
                        "-o", str(exe), os.path.join(SDK, "examples", "desk_harness.c")] + srcs,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "warning" not in r.stderr.lower(), r.stderr
    r = subprocess.run([str(exe), "new_game"] + [str(a) for a in args], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _at_any(out, pattern):
    return int(re.search(r"^\s*(\d+) .*%s" % pattern, out, re.M).group(1))


def test_maser_barrages_chain_window_is_milliseconds_and_shrinks(tmp_path):
    # MASER BARRAGE's chain (sdk/examples/maser_barrage.c) in blocks: a 7000 ms window after the
    # Left ramp, the Building inside it a barrage (x2, the window 1000 ms shorter), outside it the
    # chain breaks; started by 3 Maser target hits
    out = play(tmp_path, _maser(), "shot", "Maser target", "shot", "Maser target", "shot", "Maser target",
               "shot", "Left ramp", "ms", 6800, "shot", "Building",          # 6.85 s: inside 7 s
               "shot", "Left ramp", "ms", 5900, "shot", "Building",          # 5.95 s: inside 6 s -> x3
               "shot", "Left ramp", "ms", 5100, "shot", "Building",          # 5.15 s: past 5 s
               slug="maser")
    assert "START (a block)" in out
    assert scores(out) == [1000000, 5000000, 2000000, 10000000, 3000000]   # the last Building pays nothing
    broke = _at_any(out, r"\[MASER BARRAGE\] CHAIN BROKEN")
    third = [int(m) for m in re.findall(r"^\s*(\d+) >> shot Left ramp", out, re.M)][2]
    # the window ran out 5000 ms after the third Left ramp, to a tick (a shot is seen the tick after)
    assert 5000 <= broke - third <= 5000 + 34, broke - third
    assert "DISPLAY 180 MASER BARRAGE" in out


def test_a_shared_variable_lights_one_mode_from_another(tmp_path):
    # FINAL WARS lit by the ledger: it starts only once MASER BARRAGE has been won this game
    final = prog([
        {"hat": {"kind": "shot", "shot": "Big loop", "when": "idle"}, "do": [
            {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": {"k": "var", "name": "Maser won"}, "b": num(1)},
             "then": [{"op": "start_mode"}], "else": [{"op": "log", "text": "not lit"}]}]},
        {"hat": {"kind": "mode_start"}, "do": [{"op": "score", "points": {"k": "op", "op": "*", "a": num(1000),
            "b": {"k": "var", "name": "maser_played"}}}]},
    ], vars=[{"name": "Maser won", "reset": "game", "shared": True},
             {"name": "maser_played", "reset": "game", "shared": True}], name="FINAL WARS", seconds=0)
    win = ["shot", "Maser target"] * 3 + ["shot", "Left ramp", "shot", "Building"]
    out = play_many(tmp_path, {"maser": _maser(), "final": final},
                    "shot", "Big loop", *win, "ball_end", "shot", "Big loop",
                    "game_over", "secs", 1, "new_game", "secs", 1, "shot", "Big loop")
    assert out.count("[FINAL WARS] not lit") == 2                 # before the barrage, and in the next game
    assert out.count("[FINAL WARS] START (a block)") == 1
    assert 1000 in scores(out)                                   # "maser played" read across too
    assert out.index("[FINAL WARS] START") > out.index("[MASER BARRAGE] END")


def test_a_start_waits_out_a_multiball_and_the_next_one_after_it_starts_it(tmp_path):
    p = prog([
        {"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [
            {"op": "if", "cond": {"k": "can_start"}, "then": [{"op": "log", "text": "can"}],
             "else": [{"op": "log", "text": "cannot"}]},
            {"op": "start_mode"}]},
    ], seconds=0, wait_multiball=True)
    out = play(tmp_path, p, "balls", 2, "shot", "Left ramp", "multiball", 1, "balls", 1, "shot", "Left ramp",
               "multiball", 0, "shot", "Left ramp")
    assert out.count("] cannot\n") == 2 and out.count("] can\n") == 1
    assert out.count("still ready") == 1                          # said once in 10 s, not at every shot
    assert out.count("START (a block)") == 1
    assert out.index("START (a block)") > out.index(">> multiball 0")
    # without the option a multiball does not stop it
    p["wait_multiball"] = False
    out = play(tmp_path, p, "balls", 2, "shot", "Left ramp")
    assert "START (a block)" in out and "] can\n" in out


def test_the_display_priority_is_held_while_it_runs_and_back_at_a_drain(tmp_path):
    p = prog([{"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [{"op": "start_mode"}]}],
             seconds=5, priority=190)
    out = play(tmp_path, p, "shot", "Left ramp", "secs", 6, "shot", "Left ramp", "secs", 1, "ball_end")
    assert out.count("DISPLAY 190 TEST MODE") == 2
    assert "END (time ran out)" in out and "END (ball ended)" in out
    # the clock running out keeps it for the total on its screen; a drain gives it back at once
    assert _at_any(out, "DISPLAY lingers TEST MODE 3000 ms") == _at_any(out, r"END \(time ran out\)")
    assert _at_any(out, "DISPLAY 0 TEST MODE") == _at_any(out, r"END \(ball ended\)") == _at_any(out, ">> ball_end")
    assert "DISPLAY" not in play(tmp_path, dict(p, priority=0), "shot", "Left ramp", "secs", 6)
# ---- PAD-374: the mode's own clips and sounds ------------------------------------------------------
def _media_prog(**kw):
    """KING GHIDORAH's way with its own assets, in blocks: an intro full screen and a loop behind
    the HUD when it starts, a clip behind the HUD and a call on a shot, a call (else the game's
    Time is up) at the end."""
    return prog([
        {"hat": {"kind": "shot", "shot": "Building", "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "mode_start"}, "do": [{"op": "clip", "clip": "intro", "where": "full"},
                                               {"op": "clip", "clip": "loop", "where": "loop"}]},
        {"hat": {"kind": "shot", "shot": "Left ramp", "when": "running"}, "do": [
            {"op": "clip", "clip": "sever", "where": "behind"}, {"op": "sound", "sound": "sever"}]},
        {"hat": {"kind": "mode_end"}, "do": [{"op": "sound", "sound": "lost", "fallback": "time_up"},
                                             {"op": "clip", "clip": "won", "where": "full"}]},
    ], seconds=10,
        clips=[{"name": "intro", "file": "intro.mp4"}, {"name": "loop", "file": "loop.mp4"},
               {"name": "sever", "file": "sever.mp4"}, {"name": "won", "file": "won.mp4"}],
        sounds=[{"name": "sever", "file": "sever.wav", "priority": 4},
                {"name": "lost", "file": "lost.wav", "priority": 3}],
        music="music.wav", **kw)


def _media_files(folder):
    for f in ("intro.mp4", "loop.mp4", "sever.mp4", "won.mp4", "sever.wav", "lost.wav", "music.wav"):
        with open(os.path.join(folder, f), "wb") as fh:
            fh.write(b"x")


def test_own_clips_and_sounds_ride_in_assets_json_as_a_code_modes(tmp_path):
    project = _card(tmp_path)
    slug, _path = BM.new_blocks_mode(project, "Heads", shots=SHOTS)
    folder = MP.mode_folder(project, slug)
    _media_files(folder)
    BM.save(project, slug, _media_prog())
    spec = CM.load(project, slug)
    assert spec.clips == {"intro": "intro.mp4", "loop": "loop.mp4", "sever": "sever.mp4", "won": "won.mp4"}
    assert spec.calls == {"sever": {"wav": "sever.wav", "priority": 4}, "lost": {"wav": "lost.wav", "priority": 3}}
    assert spec.music == "music.wav" and spec.has_assets()
    assert CM.validate(spec, folder) == []
    # what Write asks the sound bank for, and the file it puts beside mode.so
    wants = CM.sound_wants(project, [(slug, spec)])
    assert [w["key"] for w in wants] == ["music", "call:sever", "call:lost"]
    carried = [{"slug": slug, "key": "music", "request": 125, "sid": 618},
               {"slug": slug, "key": "call:sever", "request": 1251, "ms": 1500}]
    text = CM.runtime_text(slug, spec, GZ, own_sounds=carried, clip=True)
    assert "clip   intro PadMode_heads_Intro" in text and "clip   won PadMode_heads_Won" in text
    assert "music  125 618" in text and "call   sever 1251 1500 4" in text
    assert "call   lost" not in text                     # not carried: the block says Time is up
    # taken out of the blocks, taken out of the assets
    p = BM.load(project, slug)
    p["clips"], p["sounds"], p["music"] = [], [], ""
    BM.save(project, slug, p)
    spec = CM.load(project, slug)
    assert spec.clips == {} and spec.calls == {} and spec.music == ""


def test_own_clip_and_sound_problems_and_notes(tmp_path):
    p = _media_prog()
    assert BM.problems(p, SHOTS) == []
    folder = str(tmp_path)
    got = BM.problems(p, SHOTS, folder=folder)
    assert "The clip intro's file intro.mp4 is not in the mode's folder: pick it again." in got
    assert "Its music music.wav is not in the mode's folder: pick it again." in got
    _media_files(folder)
    assert BM.problems(p, SHOTS, folder=folder) == []
    bad = _media_prog()
    bad["clips"].append({"name": "Intro!", "file": "x.mp4"})
    bad["sounds"].append({"name": "sever", "file": "", "priority": 9})
    bad["scripts"][2]["do"] += [{"op": "clip", "clip": "roar", "where": "full"},
                                {"op": "clip", "clip": "", "where": "up"},
                                {"op": "sound", "sound": "nope", "fallback": "shout"}]
    got = BM.problems(bad, SHOTS)
    assert any(t.startswith("A clip's name 'Intro!' is not one") for t in got)
    assert "Two sounds are called sever." in got
    assert "The sound sever has no file: pick one." in got and "The sound sever's priority is 1 to 7." in got
    assert ("Script 3 plays the clip roar, which the mode does not have: add it under Its own clips and "
            "sounds.") in got
    assert "Script 3 plays a clip with none chosen." in got and "Script 3 plays a clip with no where." in got
    assert "Script 3 plays the sound nope, which the mode does not have: add it under Its own clips and sounds." in got
    assert "Script 3 falls back on a callout that is not one." in got
    many = _media_prog()
    many["clips"] = [{"name": "c%d" % i, "file": "c.mp4"} for i in range(BM.MAX_CLIPS + 1)]
    assert "13 clips of its own: 12 at most." in BM.problems(many, SHOTS)
    # once behind the HUD needs a loop to play in
    noloop = _media_prog()
    noloop["scripts"][1]["do"] = noloop["scripts"][1]["do"][:1]
    assert any(t.startswith("A clip behind the HUD, once, plays in the place of the mode's loop")
               for t in BM.notes(noloop))
    assert not any("behind the HUD" in t for t in BM.notes(_media_prog()))


def test_media_names_come_from_the_files():
    assert BM.media_name("King Ghidorah - Sever!") == "king_ghidorah_s"
    assert BM.media_name("01 roar") == "s_01_roar"
    assert BM.media_name("roar", taken=["roar", "ROAR_2"]) == "roar_3"
    assert BM.media_name("") == "sound"
    assert BM.media_name("a" * 20, taken=["a" * 15]) == "a" * 13 + "_2"
    for n in ("king_ghidorah_s", "s_01_roar", "roar_3", "a" * 13 + "_2"):
        assert BM.MEDIA_RE.match(n)


def test_the_c_plays_its_own_through_the_sdk_header_and_only_when_it_has_some():
    plain = BM.to_c(BM.starter("RAMP FRENZY", SHOTS), "ramp_frenzy")
    assert "pad_mode_assets.h" not in plain and "pa_" not in plain
    src = BM.to_c(_media_prog(), "heads")
    assert '#include "pad_mode_assets.h"' in src
    assert 'static struct pa_assets own = { .folder = "heads" };' in src
    assert src.count("pa_load(&own);") >= 2 and "own_tick();" in src and "pa_end(&own);" in src
    assert "pa_start(" not in src                       # no name starts a clip on its own
    assert 'clip_full("intro");' in src and 'clip_loop("loop");' in src and 'clip_behind("sever");' in src
    assert 'if (!sound("lost")) pm_callout(pm_callout_id("time_up"));' in src
    assert '    sound("sever");' in src
    used = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", src))
    assert used <= _header_calls(), used - _header_calls()
    # a name that is not one never reaches the C
    p = _media_prog()
    p["scripts"][2]["do"].append({"op": "sound", "sound": 'x"); evil("'})
    assert "evil" not in BM.to_c(p, "heads")


def _assets(tmp_path, slug, program, carried):
    """The <slug>.assets Write would put beside mode.so for this program, in a dump folder."""
    project = _card(tmp_path / "proj")
    os.makedirs(MP.mode_folder(project, slug))
    _media_files(MP.mode_folder(project, slug))
    BM.save(project, slug, program)
    spec = CM.load(project, slug)
    dump = tmp_path / "dump"
    dump.mkdir()
    own = [dict(u, slug=slug) for u in carried]
    (dump / (slug + ".assets")).write_text(CM.runtime_text(slug, spec, GZ, own_sounds=own, clip=True))
    return str(dump)


def _at(out, pattern):
    m = re.search(r"^\s*(\d+) " + pattern, out, re.M)
    assert m, pattern
    return int(m.group(1))


def test_own_clips_and_sounds_play_where_the_blocks_say(tmp_path, monkeypatch):
    _cc()
    dump = _assets(tmp_path, "blk", _media_prog(), [
        {"key": "music", "request": 125, "sid": 618}, {"key": "call:sever", "request": 1251, "ms": 1500}])
    monkeypatch.setenv("HARNESS_DUMP", dump)
    out = play(tmp_path, _media_prog(), "shot", "Building", "secs", 1, "shot", "Left ramp", "secs", 12)
    start = _at(out, r"\[TEST MODE\] START")
    assert "own assets: /dump/blk.assets" in out
    # its music: the game's (67) fades, the carrier plays its own bed
    assert _at(out, "FADE 67 250") >= start and "SID 125 618" in out and _at(out, "SOUND 125") >= start
    # the intro full screen half a second later, then the loop behind the HUD
    intro = _at(out, "CLIP PadMode_blk_Intro")
    assert 500 <= intro - start <= 600
    assert _at(out, "BACKDROP PadMode_blk_Loop") >= intro
    # the shot: a clip behind the HUD once, and its own call
    ramp = _at(out, "BACKDROP ONCE PadMode_blk_Sever")
    assert ramp > intro and _at(out, "SOUND 1251") >= ramp
    # the end: no "lost" call was carried, so the game's Time is up; the won clip full screen;
    # the loop off and the music faded
    end = _at(out, r"\[TEST MODE\] END \(time ran out\)")
    assert _at(out, "CALLOUT 1295") <= end
    assert "own sound lost: the build carried none" in out
    assert _at(out, "BACKDROP OFF") <= end + 20
    assert _at(out, "FADE 125 400") <= end + 20
    assert 500 <= _at(out, "CLIP PadMode_blk_Won") - end <= 600


def test_without_its_file_the_blocks_still_play_the_games_own(tmp_path, monkeypatch):
    _cc()
    dump = tmp_path / "empty"
    dump.mkdir()
    monkeypatch.setenv("HARNESS_DUMP", str(dump))
    out = play(tmp_path, _media_prog(), "shot", "Building", "secs", 1, "shot", "Left ramp", "secs", 12)
    assert "no blk.assets" in out
    assert "CLIP " not in out and "BACKDROP" not in out and "SOUND " not in out
    assert "CALLOUT 1295" in out and "END (time ran out)" in out


def test_a_loop_asked_for_while_idle_and_once_without_a_loop_say_why(tmp_path, monkeypatch):
    _cc()
    p = _media_prog()
    p["scripts"][1]["do"] = [{"op": "clip", "clip": "sever", "where": "behind"}]
    p["scripts"].append({"hat": {"kind": "any_shot", "when": "idle"}, "do": [
        {"op": "clip", "clip": "loop", "where": "loop"}]})
    dump = _assets(tmp_path, "blk", p, [])
    monkeypatch.setenv("HARNESS_DUMP", dump)
    out = play(tmp_path, p, "shot", "Left ramp", "shot", "Building", "secs", 1)
    assert "own clip loop: not looped behind the HUD - the mode is not running" in out
    # the start's clip behind the HUD comes before the Building's idle script asks for the loop
    once = _at(out, r"\[TEST MODE\] own clip sever: not played behind the HUD - no clip of its own loops there")
    assert "BACKDROP ONCE" not in out and _at(out, "BACKDROP PadMode_blk_Loop") >= once


# ---- PAD-373: the game's own modes while it runs ------------------------------------------------------
GATE = [{"hat": {"kind": "shot", "shot": "Building", "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "shot", "shot": "Maser target", "when": "running"}, "do": [{"op": "score", "points": num(5)}]}]


def test_may_start_runs_beside_the_games_modes(tmp_path):
    out = play(tmp_path, prog(GATE, seconds=0), "battle", 1, "shot", "Building", "shot", "Maser target",
               "timed", 1, "secs", 1, "shot", "Maser target")
    assert "START (a block)" in out and scores(out) == [5, 5]
    assert "] END (" not in out and "BLOCK" not in out


def test_give_way_waits_for_the_games_mode_and_ends_when_one_begins(tmp_path):
    out = play(tmp_path, prog(GATE, seconds=0, game_modes="give_way"),
               "battle", 1, "shot", "Building", "battle", 0, "balls", 2, "shot", "Building", "balls", 1,
               "shot", "Building", "shot", "Maser target", "timed", 1, "secs", 0.5, "shot", "Maser target")
    assert "not started (a block): a battle is running" in out
    assert out.count("START (a block)") == 1                     # the third Building: none running
    assert "gives way - one of the game's modes starting ends it" in out
    assert "END (the game's own mode began)" in out
    assert scores(out) == [5]                                     # the Maser after it ended pays nothing
    assert "BLOCK" not in out


def test_block_holds_the_ticked_modes_off_while_it_runs(tmp_path):
    out = play(tmp_path, prog(GATE, seconds=2, game_modes="block", block_modes=[23, 21]),
               "shot", "Building", "secs", 3)
    assert re.search(r"BLOCKLIST 21 23 TEST MODE\n\s*\d+ KEEPRULES_NAMED none TEST MODE\n\s*\d+ BLOCK 1 TEST MODE", out)
    assert "END (time ran out)" in out
    assert out.index("END (time ran out)") > out.index("BLOCK 0 TEST MODE")   # given back as it ends
    # none ticked: the port's checked defaults
    out = play(tmp_path, prog(GATE, seconds=0, game_modes="block"), "shot", "Building", "multiball", 1, "secs", 0.5)
    assert "BLOCKLIST defaults TEST MODE" in out
    assert "END (the game's own mode began)" in out and "BLOCK 0 TEST MODE" in out   # a multiball still ends it


def test_its_own_multiball_is_not_the_game_beginning_one(tmp_path):
    p = prog(GATE + [{"hat": {"kind": "mode_start"}, "do": [{"op": "multiball", "balls": 2, "save": 0}]}],
             seconds=0, game_modes="block")
    # the runtime counts two balls in play as a multiball: the mode's own does not end it, but once
    # it is down to one ball, a multiball of the game's does
    out = play(tmp_path, p, "shot", "Building", "multiball", 1, "secs", 1, "shot", "Maser target",
               "balls", 1, "secs", 0.5, "shot", "Maser target")
    assert "MULTIBALL 2 balls" in out and scores(out) == [5]
    assert "END (the game's own mode began)" in out


def test_start_mode_now_does_not_wait_for_the_games_mode(tmp_path, monkeypatch):
    dump = tmp_path / "dump"
    dump.mkdir()
    monkeypatch.setenv("HARNESS_DUMP", str(dump))
    out = play(tmp_path, prog(GATE, seconds=0, game_modes="give_way"), "timed", 1, "shot", "Building",
               "trigger", "blk.start", "secs", 1)
    assert "not started (a block): a stock mode is running" in out
    assert "START (trigger file)" in out


# ---- PAD-376: light shows, and a lit shot's pace ----------------------------------------------------
def _step(fx, ms, a, b, at="center", rate=0, gi="keep"):
    return {"fx": fx, "ms": ms, "a": a, "b": b, "at": at, "rate": rate, "gi": gi}


#: KING GHIDORAH's start show (ghidorah_heads.c SHOW_START), built step by step in a block
GHIDORAH_START = [_step("bolts", 1500, "#ffb000", "#000000", "center", 190, "dark"),
                  _step("strobe", 500, "#ffffff", "#ffb000", "center", 60, "flash"),
                  _step("burst", 800, "#ffb000", "#ff4000", "top", 0, "dark"),
                  _step("fade", 400, "#ff4000", "#000000", "center")]


def _lights_prog():
    return prog([{"hat": {"kind": "mode_start"}, "do": [
        {"op": "show", "show": "own", "steps": GHIDORAH_START}, _light("Building", rate={"k": "secs_left"}),
        _light("Left ramp", "hurry")]},
        {"hat": {"kind": "mode_end"}, "do": [{"op": "show", "show": "fizzle"}, {"op": "lights_off", "shot": "*"}]}])


def _light(shot, pattern="blink", rate=None, color="#ffb000"):
    b = {"op": "light_shot", "shot": shot, "color": color, "pattern": pattern}
    if rate is not None:
        b["rate"] = num(rate) if isinstance(rate, int) else rate
    return b


def test_light_show_and_pace_problems():
    def probs(*blocks):
        return BM.problems(prog([{"hat": {"kind": "mode_start"}, "do": list(blocks)}]), SHOTS)
    assert probs({"op": "show", "show": "lightning"}, _light("Building", rate=250),
                 _light("Building", "hurry"), {"op": "show", "show": "own", "steps": GHIDORAH_START}) == []
    assert any("no light show" in t or "none chosen" in t for t in probs({"op": "show", "show": "nope"}))
    assert any("with no steps" in t for t in probs({"op": "show", "show": "own", "steps": []}))
    bad = [_step("warp", 100, "#ffffff", "#000000"), _step("burst", 10, "#ffffff", "#000000"),
           _step("burst", 100, "white", "#000000"), _step("burst", 100, "#ffffff", "#000000", at="moon"),
           _step("spin", 100, "#ffffff", "#000000", rate=9000), _step("spin", 100, "#ffffff", "#000000", gi="x")]
    said = " ".join(probs({"op": "show", "show": "own", "steps": bad}))
    for words in ("step 1, has no pattern", "step 2, lasts 50 to 10000 ms", "step 3, has a colour missing",
                  "step 4, has no place", "step 5, has a pace of 0 to 2000", "step 6, says nothing"):
        assert words in said, words
    eleven = {"op": "show", "show": "own", "steps": [GHIDORAH_START[0]] * 11}
    assert any("11 steps: 10 at most" in t for t in probs(eleven))
    assert any("pace of 20 to 5000 ms" in t for t in probs(_light("Building", rate=5)))
    assert any("empty number slot" in t for t in probs(_light("Building", rate={"k": "nope"})))
    # a solid light's pace is not asked for
    assert probs(_light("Building", "solid", rate=5)) == []
    # a hurrying blink with no clock blinks at an even pace: a note, not a problem
    p = prog([{"hat": {"kind": "mode_start"}, "do": [_light("Building", "hurry")]}], seconds=0)
    assert any("faster as time runs out" in t for t in BM.notes(p))


def test_the_light_show_c_only_calls_what_the_header_declares_and_only_when_used():
    p = prog([{"hat": {"kind": "mode_start"}, "do": [
        {"op": "show", "show": "own", "steps": GHIDORAH_START}, {"op": "show", "show": "rainbow"},
        _light("Building", rate={"k": "secs_left"}), _light("Left ramp", "hurry"),
        {"op": "lights_off", "shot": "Building"}, {"op": "lights_off", "shot": "*"}]}])
    src = BM.to_c(p, "blk")
    used = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", src))
    assert used <= _header_calls(), used - _header_calls()
    assert "static const struct fx_step SHOW_0[] = {" in src and "SHOW_1[]" in src
    assert "{ FX_BOLTS, 1500, 0xffb000u, 0x000000u, 150, 330, 190, GI_DARK }" in src
    assert 'show_start(SHOW_1, 3, "rainbow");' in src
    assert "light(0, 0xffb000u, PM_LAMP_BLINK, (long long)secs_left(), 0);" in src
    assert "light(1, 0xffb000u, PM_LAMP_BLINK, 0LL, 1);" in src
    plain = BM.to_c(BM.starter("RAMP FRENZY", SHOTS), "ramp_frenzy")
    assert "show_tick" not in plain and "fx_colour" not in plain and "#define SHOWING 0" in plain


def test_king_ghidoras_start_show_and_a_blink_that_quickens_in_blocks(tmp_path, monkeypatch):
    # KING GHIDORAH (ghidorah_heads.c) in blocks: its start show, step by step; the Building lit
    # blinking every 500 ms, 250 ms with 10 s left and 100 ms with 4 s left; a ready-made show at the end
    _cc()
    monkeypatch.setenv("HARNESS_PLACES", "1")
    p = prog([
        {"hat": {"kind": "shot", "shot": "Building", "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "mode_start"}, "do": [{"op": "show", "show": "own", "steps": GHIDORAH_START},
                                               _light("Building", rate=500)]},
        {"hat": {"kind": "seconds_left", "seconds": 10}, "do": [_light("Building", rate=250)]},
        {"hat": {"kind": "seconds_left", "seconds": 4}, "do": [_light("Building", rate=100)]},
        {"hat": {"kind": "mode_end"}, "do": [{"op": "show", "show": "rainbow"}]},
    ], seconds=15)
    out = play(tmp_path, p, "shot", "Building", "secs", 22)
    start = _at(out, r"\[TEST MODE\] START")
    assert "show its own: 4 step(s) over 18 placed inserts, 2 GI string(s)" in out
    # the show has the playfield: the Building's light waits for it to end (3.2 s), then comes on
    over = _at(out, r"\[TEST MODE\] show its own: over")
    assert 3200 <= over - start <= 3250
    lit = [(int(t), ms) for t, ms in re.findall(r"^\s*(\d+) LAMP BUILDING ffb000 blink (\d+)", out, re.M)]
    assert [ms for _t, ms in lit] == ["500", "250", "100"], lit
    assert lit[0][0] - over <= 20
    assert 4950 <= lit[1][0] - start <= 5100 and 10950 <= lit[2][0] - start <= 11100
    end = _at(out, r"\[TEST MODE\] END \(time ran out\)")
    assert _at(out, r"\[TEST MODE\] show rainbow: 3 step\(s\)") - end <= 20
    assert 3100 <= _at(out, r"\[TEST MODE\] show rainbow: over") - end <= 3150
    assert int(re.search(r"END paints (\d+)", out).group(1)) > 200      # it painted, step after step
    assert "END lamps held 0" in out                                   # and handed every insert back


def test_a_blink_that_hurries_follows_the_clock_and_a_light_again_is_left_alone(tmp_path):
    p = prog([
        {"hat": {"kind": "event", "event": "skill_shot", "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "mode_start"}, "do": [_light("Left ramp", "hurry", color="#ff0000")]},
        {"hat": {"kind": "every", "seconds": 1}, "do": [_light("Right ramp", rate=300)]},
        {"hat": {"kind": "shot", "shot": "Left ramp", "when": "running"}, "do": [
            {"op": "lights_off", "shot": "Left ramp"}]},
    ], seconds=30)
    out = play(tmp_path, p, "event", "skill_shot", "secs", 29.5, "shot", "Left ramp", "secs", 2)
    start = _at(out, r"\[TEST MODE\] START")
    hurry = [(int(t) - start, ms) for t, ms in re.findall(r"^\s*(\d+) LAMP LEFT RAMP ff0000 blink (\d+)", out, re.M)]
    assert [ms for _t, ms in hurry] == ["700", "400", "200", "100"], hurry
    assert 9950 <= hurry[1][0] <= 10100 and 19950 <= hurry[2][0] <= 20100 and 26950 <= hurry[3][0] <= 27100
    assert out.count("LAMP RIGHT RAMP ffb000 blink 300") == 1           # lit again each second: sent once
    assert "LAMP OFF LEFT RAMP" in out and "END lamps held 0" in out


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
    # a HUD with no priority of its own takes a mode's 180 (PAD-377's choice wins when made)
    assert re.search(r"#define DISPLAY_PRIORITY 180\b", src) and "pm_end_holding(ENDING_MS)" in src
    p = maser_hud()
    p["priority"] = 190
    assert re.search(r"#define DISPLAY_PRIORITY 190\b", BM.to_c(p, "maser"))
    p["hud"]["on"] = False
    p["priority"] = 0
    assert re.search(r"#define DISPLAY_PRIORITY 0\b", BM.to_c(p, "maser"))


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


def test_the_hud_with_a_light_show_and_its_own_clips_builds_and_plays(tmp_path, monkeypatch):
    # PAD-375 beside PAD-374 and PAD-376: the HUD's kit, the light-show engine and the assets header
    # in one mode's C, without a name meeting another
    _cc()
    p = _media_prog()
    p["hud"] = maser_hud()["hud"]
    p["vars"] = [{"name": "step"}, {"name": "mult"}, {"name": "barrages"}]
    p["scripts"].append({"hat": {"kind": "mode_start"}, "do": [
        {"op": "show", "show": "own", "steps": GHIDORAH_START},
        {"op": "hud_award", "text": "GO", "value": None, "sub": "", "seconds": 2}]})
    assert BM.problems(p, SHOTS) == []
    src = BM.to_c(p, "blk")
    assert '#include "intricate_kit.h"' in src and '#include "pad_mode_assets.h"' in src
    dump = _assets(tmp_path, "blk", p, [{"key": "music", "request": 125, "sid": 618}])
    monkeypatch.setenv("HARNESS_DUMP", dump)
    out = play(tmp_path, p, "shot", "Building", "secs", 1, "ball_end", "secs", 1)
    start = _at(out, r"\[TEST MODE\] START")
    assert "SHOW PadMode_blk_Hud 1" in out and "Hud_Award: GO" in out
    assert _at(out, "CLIP PadMode_blk_Intro") >= start
    assert "show its own: 4 step(s)" in out
    t = _at(out, ">> ball_end")
    assert re.search(r"^\s*%d SHOW PadMode_blk_Hud 0" % t, out, re.M)
    assert "END lamps held 0, display priority 0" in out


def test_a_hud_mode_that_gives_way_takes_its_hud_down_when_a_game_mode_begins(tmp_path):
    # PAD-373's give_way beside the HUD: one of the game's modes beginning ends it at once, its HUD
    # and display given back in the same tick (the kit's kit_game_began), no TOTAL left over the game's
    p = maser_hud()
    p["game_modes"] = "give_way"
    out = play(tmp_path, p, "shot", "Maser target", "secs", 1, "battle", 1, "secs", 1, slug="maser")
    end = _at(out, r"\[TEST MODE\] END \(the game's own mode began\)")
    assert re.search(r"^\s*%d SHOW PadMode_maser_Hud 0" % end, out, re.M)
    assert re.search(r"^\s*%d DISPLAY 0 TEST MODE" % end, out, re.M)
    # nothing of its HUD is written after that tick
    assert all(int(t) <= end for t in re.findall(r"^\s*(\d+) WORDS PadMode_maser_Hud", out, re.M))
