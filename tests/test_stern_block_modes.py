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
from pinball_decryptor.plugins.stern import blocks_sim as BS
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
                  "lights a shot in no color",
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
@pytest.mark.parametrize("which", ["starter", "own clips and sounds", "light shows", "lights by name"])   # PAD-598
def test_the_starter_builds_with_build_mode_sh(tmp_path, which):
    if os.name == "nt":
        pytest.skip("build_mode.sh runs under bash with arm-linux-gnueabihf-gcc (WSL or Linux)")
    if not shutil.which("bash") or not shutil.which("arm-linux-gnueabihf-gcc"):
        pytest.skip("no arm-linux-gnueabihf-gcc here")
    src = tmp_path / "ramp_frenzy.c"
    program = {"starter": lambda: BM.starter("RAMP FRENZY", SHOTS), "own clips and sounds": _media_prog,
               "light shows": _lights_prog, "lights by name": _lights_by_name_prog}[which]()
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
                        "-I", os.path.join(SDK, "examples"),           # PAD-658: modes with a HUD (the kit)
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
    # PAD-680: through the multiball its idle scripts run on (they count, note and show); only the start waits it out
    assert out.count("] cannot\n") == 2 and out.count("] can\n") == 1
    assert out.count("START (a block)") == 1
    assert out.index("START (a block)") > out.index(">> multiball 0")
    # without the option a multiball does not stop it
    p["wait_multiball"] = False
    out = play(tmp_path, p, "balls", 2, "shot", "Left ramp")
    assert "START (a block)" in out and "] can\n" in out


def test_the_display_priority_is_held_while_it_runs_and_back_at_a_drain(tmp_path):
    p = prog([{"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [{"op": "start_mode"}]}],
             seconds=5, priority=190)
    out = play(tmp_path, p, "shot", "Left ramp", "secs", 6, "shot", "Left ramp", "secs", 1, "ball_end", "secs", 1)
    assert out.count("DISPLAY 190 TEST MODE") == 2
    assert "END (time ran out)" in out and "END (ball ended)" in out
    # the clock running out keeps it for the total on its screen
    assert _at_any(out, "DISPLAY lingers TEST MODE 3000 ms") == _at_any(out, r"END \(time ran out\)")
    # PAD-622: so does a drain, for its TOTAL as long as the game's own mini-wizards show theirs, the end of ball waiting
    drain = _at_any(out, ">> ball_end")
    assert _at_any(out, "DISPLAY lingers TEST MODE 6000 ms") == _at_any(out, r"END \(ball ended\)") == drain
    assert 5900 <= _at_any(out, r"DISPLAY released TEST MODE") - drain <= 6100
    assert 5900 <= _at_any(out, "BALL END goes on") - drain <= 6100
    # a tilted ball gives it back at once, as before
    out = play(tmp_path, p, "shot", "Left ramp", "secs", 1, "tilt", "ball_end", "secs", 1)
    assert _at_any(out, "DISPLAY 0 TEST MODE") == _at_any(out, r"END \(ball ended\)") == _at_any(out, "BALL END goes on")
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


def test_a_clip_asked_as_it_ends_keeps_its_total_after_it(tmp_path, monkeypatch):
    """PAD-733 (David, v29: "when the final mode video plays the scene text plays after that but only for a very
    brief portion of a second"): KING CAESAR's final blow asked its clip and then ended - its TOTAL's 3 s ran out under
    the clip. And at a drain the end of ball waited 6 s, 5.7 of them the lost clip. Either way the clip now comes
    first and the TOTAL has its 3 s after it, as at a clock's end with a clip in When the mode ends."""
    _cc()

    def prog_(**kw):        # no start clip: the harness's clips play until stopped, so one would count here
        q = _media_prog(priority=180, **kw)
        q["scripts"][1]["do"] = q["scripts"][1]["do"][1:]
        return q

    p = prog_()
    p["scripts"][2]["do"] = [{"op": "clip", "clip": "sever", "where": "full"}, {"op": "end_mode"}]
    p["scripts"][3]["do"] = p["scripts"][3]["do"][:1]                      # When the mode ends plays no clip
    dump = _assets(tmp_path, "blk", p, [])
    monkeypatch.setenv("HARNESS_DUMP", dump)
    out = play(tmp_path, p, "shot", "Building", "secs", 1, "shot", "Left ramp", "secs", 12)
    end = _at(out, r"\[TEST MODE\] END \(a block\)")
    assert _at(out, "DISPLAY lingers TEST MODE 10000 ms") == end          # 3000 + the clip's 7000
    assert 500 <= _at(out, "CLIP PadMode_blk_Sever") - end <= 600
    # at a drain: the end of ball waits for the clip and then the TOTAL's 3 s
    hud = dict(BM.normalize({})["hud"], on=True)
    out = play(tmp_path, prog_(hud=hud), "shot", "Building", "secs", 2, "ball_end", "secs", 12)
    drain = _at(out, ">> ball_end")
    assert _at(out, "BALL END HOLD 10000 TEST MODE") == drain
    assert 500 <= _at(out, "CLIP PadMode_blk_Won") - drain <= 600
    assert 9900 <= _at(out, "BALL END goes on") - drain <= 10100
    # without a clip at its end, the drain's 6 s as before
    q = prog_(hud=hud)
    q["scripts"][3]["do"] = q["scripts"][3]["do"][:1]
    out = play(tmp_path, q, "shot", "Building", "secs", 2, "ball_end", "secs", 8)
    assert _at(out, "BALL END HOLD 6000 TEST MODE") == _at(out, ">> ball_end")


def test_take_the_extra_balls_away_only_while_more_than_one_is_up(tmp_path):
    """PAD-733 (David, MINILLA: "just kill the flippers and show that the mode is ended, then instead of ending the ball,
    give a ball back in the plunger lane"): the block asks the runtime to drain to one ball (pm_drain_to_one) when its
    multiball still has more than one ball up as the mode ends; with one ball nothing is asked."""
    p = prog([{"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [{"op": "start_mode"}]},
              {"hat": {"kind": "mode_start"}, "do": [{"op": "multiball", "balls": 2, "save": 0}]},
              {"hat": {"kind": "shot", "shot": "Building", "when": "running"}, "do": [{"op": "end_mode", "won": True}]},
              {"hat": {"kind": "mode_end"}, "do": [{"op": "drain_to_one"}]}], seconds=30)
    assert BM.problems(p, SHOTS) == []
    assert "if (run.on && pm_balls_in_play() > 1 && !pm_drain_to_one())" in BM.to_c(p, "blk")
    out = play(tmp_path, p, "shot", "Left ramp", "secs", 2, "shot", "Building", "secs", 1)
    assert _at_any(out, "DRAIN TO ONE") == _at_any(out, r"END \(a block\)")
    out = play(tmp_path, p, "shot", "Left ramp", "secs", 2, "balls", 1, "shot", "Building", "secs", 1)
    assert "DRAIN TO ONE" not in out and "END (a block)" in out


def test_a_loop_asked_as_it_ends_goes_behind_its_total(tmp_path, monkeypatch):
    """PAD-733 (David: MINILLA "it doesn't make sense to go from summer to winter and back during the mode"): his
    winter fall played full screen, then the TOTAL showed over the mode's sunny loop again. A clip looped in When the
    mode ends now goes behind its TOTAL in the loop's place (after the full-screen clip); without one, the loop as
    before."""
    _cc()
    p = _media_prog(priority=180, hud=dict(BM.normalize({})["hud"], on=True))
    p["scripts"][3]["do"].append({"op": "clip", "clip": "sever", "where": "loop"})
    dump = _assets(tmp_path, "blk", p, [])
    monkeypatch.setenv("HARNESS_DUMP", dump)
    out = play(tmp_path, p, "shot", "Building", "secs", 12)
    end = _at(out, r"\[TEST MODE\] END \(time ran out\)")
    assert _at(out, "BACKDROP PadMode_blk_Sever") == end
    assert "own clip sever (PadMode_blk_Sever) behind its TOTAL" in out and "not looped" not in out
    assert 500 <= _at(out, "CLIP PadMode_blk_Won") - end <= 600              # the full-screen clip first, as ever
    q = _media_prog(priority=180, hud=dict(BM.normalize({})["hud"], on=True))
    out = play(tmp_path, q, "shot", "Building", "secs", 12)
    assert "BACKDROP PadMode_blk_Sever" not in out and "behind its TOTAL" not in out


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
    assert "not started" in out                                  # PAD-680: the battle's Building counts, then waits
    assert out.count("START (a block)") == 1                     # the third Building: none running
    assert "gives way - one of the game's modes starting ends it" in out
    assert "END (the game's own mode began)" in out
    assert scores(out) == [5]                                     # the Maser after it ended pays nothing
    assert "BLOCK" not in out


# ---- PAD-675/680: counting through the game's modes, starting after them; a switch hit counts -----------------
COUNT = [{"hat": {"kind": "shot", "shot": "Building", "when": "idle"}, "do": [
    {"op": "change", "var": "n", "by": num(1)},
    {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": {"k": "var", "name": "n"}, "b": num(2)},
     "then": [{"op": "start_mode"}], "else": None}]}]
NV = [{"name": "n", "reset": "game"}]


def test_a_mode_that_waits_the_games_modes_out_counts_through_one_and_starts_after_it(tmp_path):
    # David's machine (PAD-680): with nothing counted in a battle, and on Godzilla one runs most of a ball, no mode
    # ever showed its progress. Two Buildings in the battle count (the start waits it out); after it, one starts it
    out = play(tmp_path, prog(COUNT, NV, seconds=5, game_modes="block"),
               "battle", 1, "shot", "Building", "shot", "Building", "secs", 1, "battle", 0, "secs", 1,
               "shot", "Building", "secs", 1)
    assert "still ready" in out
    assert out.count("START (a block)") == 1 and out.index("START (a block)") > out.index(">> battle 0")
    out = play(tmp_path, prog(COUNT, NV, seconds=5, game_modes="block"),
               "battle", 1, "shot", "Building", "battle", 0, "secs", 1, "shot", "Building", "shot", "Building")
    assert out.count("START (a block)") == 1


def test_a_mode_that_stacks_still_counts_through_the_games_modes(tmp_path):
    out = play(tmp_path, prog(COUNT, NV, seconds=5), "battle", 1, "shot", "Building", "shot", "Building")
    assert "START (a block)" in out


def test_a_lit_mode_is_dark_while_the_games_mode_runs(tmp_path):
    lit = [{"hat": {"kind": "shot", "shot": "Building", "when": "idle"}, "do": [
        {"op": "light_mode", "shot": "Left ramp", "color": "#ff0000", "pattern": "blink"}]}]
    out = play(tmp_path, prog(lit, seconds=5, game_modes="block"),
               "shot", "Building", "secs", 1, "battle", 1, "secs", 1, "battle", 0, "secs", 1)
    seq = [ln.split(None, 1)[1] for ln in out.splitlines() if "LEFT RAMP" in ln or ">> battle" in ln]
    assert seq == ["LAMP LEFT RAMP ff0000 blink 500 TEST MODE", ">> battle 1", "LAMP OFF LEFT RAMP TEST MODE",
                   ">> battle 0", "LAMP LEFT RAMP ff0000 blink 500 TEST MODE"]


def test_a_switch_hit_counts_toward_a_start(tmp_path):
    sw = [{"hat": {"kind": "switch", "when": "idle"}, "do": [
        {"op": "change", "var": "n", "by": num(1)},
        {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": {"k": "var", "name": "n"}, "b": num(50)},
         "then": [{"op": "start_mode"}], "else": None}]}]
    out = play(tmp_path, prog(sw, NV, seconds=5, game_modes="block"), "switches", 49, "secs", 1)
    assert "START" not in out
    out = play(tmp_path, prog(sw, NV, seconds=5, game_modes="block"), "switches", 48, "shot", "Building", "secs", 1,
               "shot", "Left ramp")
    assert "START (a block)" in out                  # a shot is its switch's hit too


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
    assert "not started" in out                                  # PAD-680: the Building counts, its start waits
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
    for words in ("step 1, has no pattern", "step 2, lasts 50 to 10000 ms", "step 3, has a color missing",
                  "step 4, has no place", "step 5, has a pace of 0 to 2000", "step 6, says nothing"):
        assert words in said, words
    many = {"op": "show", "show": "own", "steps": [GHIDORAH_START[0]] * (BM.SHOW_STEPS + 1)}   # PAD-646: 32 now
    assert any("%d steps: %d at most" % (BM.SHOW_STEPS + 1, BM.SHOW_STEPS) in t for t in probs(many))
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
    assert "{ FX_BOLTS, 1500, 0xffb000u, 0x000000u, 150, 330, 190, GI_DARK, 0 }" in src
    assert 'show_start(SHOW_1, 3, "rainbow", 1);' in src
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
    assert "show its own: 4 step(s) over 36 placed inserts, 2 GI string(s)" in out
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
    # PAD-690: no timer, but the progress panel wears its badge: its label and icon go as "badge"
    r = prog([], hud={"on": True, "timer": {"on": False, "label": "", "icon": "rose"}})
    assert BM.hud_spec(r)["badge"] == {"label": "TEST MODE", "icon": "rose"} and "timer" not in BM.hud_spec(r)
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
    # PAD-680: an app whose kit alone changed gives it to the mode before a build, its C unchanged
    with open(os.path.join(folder, BM.KIT_FILE), "w", encoding="utf-8") as f:
        f.write("/* an older app's kit */\n")
    assert BM.refresh(project) == []
    with open(os.path.join(folder, BM.KIT_FILE), encoding="utf-8") as f, \
            open(os.path.join(SDK, "examples", BM.KIT_FILE), encoding="utf-8") as g:
        assert f.read() == g.read()
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
    assert re.search(r"#define DISPLAY_PRIORITY 180\b", src) and "pm_end_holding(ENDING_HOLD_MS + total_due" in src
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
    assert award[:3] == [" ", "BARRAGE", " "]                 # PAD-658: the words big, the number under them
    assert "1  -  MULTIPLIER UP" in _hud_words(out, "AwardSub")
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
    # a drain: its TOTAL as long as the game's own mini-wizards show theirs, the end of ball waiting (PAD-622); then
    # down, the display given back as the end of ball goes on
    drain = out[out.index(">> ball_end"):]
    t = int(re.search(r"^\s*(\d+) >> ball_end", out, re.M).group(1))
    on = _at_any(out, "BALL END goes on")
    assert 5900 <= on - t <= 6100
    assert "Hud_Title: TEST MODE TOTAL" in drain
    assert [x for x in map(int, re.findall(r"^\s*(\d+) SHOW PadMode_maser_Hud 0", drain, re.M)) if t < x <= on + 40]
    assert 5900 <= _at_any(drain, r"DISPLAY (0|released) TEST MODE") - t <= 6100


def test_an_award_before_the_mode_runs_is_a_note(tmp_path):
    p = maser_hud()
    p["scripts"].append({"hat": {"kind": "shot", "shot": "Big loop", "when": "idle"}, "do": [
        {"op": "hud_award", "text": "MASER", "value": {"k": "hits", "shot": "Big loop"}, "sub": "",
         "seconds": 2}]})
    out = play(tmp_path, p, "shot", "Big loop", "secs", 3, slug="maser")
    note = out[out.index(">> shot Big loop"):]
    # PAD-680: a note is in the award line, in the middle, as the code modes' were (PAD-658 had it in the title place)
    assert "Hud_Award: MASER" in note and "Hud_AwardSub: 1  -  TEST MODE" in note
    assert "SHOW PadMode_maser_Hud 1" in note and "SHOW PadMode_maser_Hud 0" in note
    assert "Hud_Title: MASER" not in note


def test_keep_at_least_puts_the_clock_up_only_when_it_is_under(tmp_path):
    """PAD-658 (David: "successful shots reset the countdown timer to 15 seconds (if it's below 15)"): Keep at least N
    seconds on the clock - one block, the clock up to N when under it, left alone when over it."""
    p = maser_hud()                                     # its clock: 20 s
    p["scripts"].append({"hat": {"kind": "shot", "shot": "Big loop", "when": "running"}, "do": [
        {"op": "set_time", "seconds": num(15), "at_least": True}]})
    src = BM.to_c(p, "maser")
    assert "if (run.on && RUN_SECONDS && secs_left() < ((15LL))) set_time((15LL));" in src
    out = play(tmp_path, p, "shot", "Maser target", "secs", 2, "shot", "Big loop", "secs", 8, "shot", "Big loop",
               "secs", 1, slug="maser")
    first = _hud_words(out[out.index(">> shot Big loop"):], "Timer_Num")[0]
    assert first in ("18", "17")                            # 18 s left: left alone
    assert _hud_words(out[out.rindex(">> shot Big loop"):], "Timer_Num")[0] == "15"   # 10 s left: up to 15


def test_a_note_shows_at_once_over_a_display_of_the_games(tmp_path):
    """PAD-680 (David, after PAD-658's notes waited out the game's displays: "i almost never saw on-screen progress
    towards modes"): the game puts a screen up for nearly every shot, so a note shows at once, over it, for its time."""
    p = maser_hud()
    p["scripts"].append({"hat": {"kind": "shot", "shot": "Big loop", "when": "idle"}, "do": [
        {"op": "hud_award", "text": "MASER", "value": {"k": "hits", "shot": "Big loop"}, "sub": "",
         "seconds": 2}]})
    out = play(tmp_path, p, "covered", 1, "shot", "Big loop", "secs", 4, "covered", 0, "secs", 3, slug="maser")
    under = out[out.index(">> shot Big loop"):out.index(">> covered 0")]
    assert "its words wait while a display" not in under
    assert "Hud_Award: MASER" in under
    shot = _at(out, ">> shot Big loop")
    hidden = [int(t) for t in re.findall(r"^\s*(\d+) SHOW PadMode_maser_Hud 0", under, re.M)]
    assert hidden and 1900 <= hidden[0] - shot <= 2100, (shot, hidden)


def test_a_clip_behind_the_hud_as_the_mode_ends_plays_full_screen(tmp_path, monkeypatch):
    """PAD-658 (run meltdown_r4: the game's screen showed, not the clip): the loop ends with the mode, so a clip
    behind the HUD in When the mode ends plays full screen."""
    _cc()
    p = _media_prog()
    p["scripts"][3]["do"][1]["where"] = "behind"
    assert any(t.startswith("A clip behind the HUD in When the mode ends plays full screen") for t in BM.notes(p))
    dump = _assets(tmp_path, "blk", p, [])
    monkeypatch.setenv("HARNESS_DUMP", dump)
    out = play(tmp_path, p, "shot", "Building", "secs", 12)
    end = _at(out, r"\[TEST MODE\] END \(time ran out\)")
    assert "own clip won: the mode is ending - played full screen, not behind the HUD" in out
    assert "BACKDROP ONCE PadMode_blk_Won" not in out
    assert 500 <= _at(out, "CLIP PadMode_blk_Won") - end <= 600


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
    t = _at(out, "BALL END goes on")                        # PAD-622: after its TOTAL at the drain
    assert t - _at(out, ">> ball_end") >= 5900
    assert [x for x in map(int, re.findall(r"^\s*(\d+) SHOW PadMode_blk_Hud 0", out, re.M)) if t - 100 <= x <= t + 40]
    assert "END lamps held 0, display priority 0" in out


def _hud_media_prog():
    p = _media_prog()
    p["hud"] = maser_hud()["hud"]
    p["vars"] = [{"name": "step"}, {"name": "mult"}, {"name": "barrages"}]
    return p


def test_the_loop_stays_behind_the_total_it_holds(tmp_path, monkeypatch):
    """PAD-658 (run meltdown_r4, md_16_end: MELTDOWN TOTAL over the live city's RAID and TANKS labels): the mode's loop
    stays behind its TOTAL while the TOTAL holds the screen, and goes with it."""
    _cc()
    p = _hud_media_prog()
    monkeypatch.setenv("HARNESS_DUMP", _assets(tmp_path, "blk", p, []))
    out = play(tmp_path, p, "shot", "Building", "secs", 22)
    end = _at(out, r"\[TEST MODE\] END \(time ran out\)")
    assert 0 <= _at(out, "BACKDROP KEPT behind TEST MODE's ending") - end <= 20
    off = _at(out, r"BACKDROP OFF \(its ending is over\)")
    assert 9900 <= off - end <= 10100                    # the won clip full screen: the TOTAL held 7 s more
    hidden = [int(t) for t in re.findall(r"^\s*(\d+) SHOW PadMode_blk_Hud 0", out, re.M)]
    assert any(abs(t - off) <= 40 for t in hidden), (off, hidden)


def test_a_drain_takes_the_loop_with_its_total(tmp_path, monkeypatch):
    _cc()
    p = _hud_media_prog()
    monkeypatch.setenv("HARNESS_DUMP", _assets(tmp_path, "blk", p, []))
    out = play(tmp_path, p, "shot", "Building", "secs", 2, "ball_end", "secs", 8)
    on = _at(out, "BALL END goes on")
    assert abs(_at(out, "BACKDROP OFF") - on) <= 40


def _noting_prog():
    p = maser_hud()
    p["scripts"].append({"hat": {"kind": "shot", "shot": "Big loop", "when": "idle"}, "do": [
        {"op": "change", "var": "loops", "by": num(1)},
        {"op": "hud_award", "text": "LOOPS", "value": var("loops"), "sub": "TO GO", "seconds": 3}]})
    p["vars"].append({"name": "loops", "reset": "game"})
    return p


def test_a_note_asked_for_in_the_games_battle_shows_at_once(tmp_path):
    """PAD-680 (David's card: no "3 more for KING KONG" - the game's own modes had the middle 39% of a game, and PAD-390
    held every note through them): a note shows at once during the game's battles and modes too, as before PAD-390."""
    out = play(tmp_path, _noting_prog(), "battle", 1, "secs", 0.5, "shot", "Big loop", "secs", 4,
               "shot", "Big loop", "secs", 1, "battle", 0, "secs", 1)
    battle = out[out.index(">> battle 1"):out.index(">> battle 0")]
    assert "Hud_AwardSub: 1  -  TO GO" in battle and "Hud_AwardSub: 2  -  TO GO" in battle
    assert "its note waits" not in out and "SHOW PadMode_blk_Hud 1" in battle


def test_a_progress_note_also_stands_on_the_progress_panel(tmp_path):
    """PAD-680 (David's Premium: the game's timed modes held the middle 39% of a game and every note waited or
    went): a mode's latest note stands on the pack's progress panel (PadMode_Progress, built into the HUD scene)
    as one line, its number after it, until the mode starts; the panel is down during the game's battles and
    while one of ours runs, and a game over clears it. PAD-733 (David: "these HUD indicators need to duck when in
    super train loops"): down while any mode of the game's runs, a timed one as a battle."""
    out = play(tmp_path, _noting_prog(), "shot", "Big loop", "secs", 4, "shot", "Big loop", "secs", 1,
               "battle", 1, "secs", 1, "battle", 0, "secs", 1, "timed", 1, "secs", 1, "timed", 0, "secs", 1,
               "shot", "Maser target", "secs", 1)
    assert "progress panel found: 16 badge slot(s)" in out
    assert "SHOW PadMode_Progress.PadMode_Progress_S1.PadMode_Progress_S1_blk 0" in out[:out.index(">> shot Big loop")]     # its badges hidden at the find
    first = out[out.index(">> shot Big loop"):out.rindex(">> shot Big loop")]
    assert "SHOW PadMode_Progress.PadMode_Progress_S1.PadMode_Progress_S1_blk 1" in first and "WORDS PadMode_Progress_S1_Num: 1" in first
    assert "SHOW PadMode_Progress 1" in first
    assert "WORDS PadMode_Progress_S1_Num: 2" in out[out.rindex(">> shot Big loop"):]   # its badge, its newest note
    battle = out[out.index(">> battle 1"):out.index(">> battle 0")]
    assert "SHOW PadMode_Progress 0" in battle and "progress panel down for now" in battle
    assert "SHOW PadMode_Progress 1" in out[out.index(">> battle 0"):out.index(">> timed 1")]
    timed = out[out.index(">> timed 1"):out.index(">> timed 0")]
    assert "SHOW PadMode_Progress 0" in timed and "progress panel down for now" in timed
    assert "SHOW PadMode_Progress 1" in out[out.index(">> timed 0"):out.index(">> shot Maser target")]
    started = out[out.index(">> shot Maser target"):]
    assert "START (a block)" in started and "SHOW PadMode_Progress 0" in started
    assert "SHOW PadMode_Progress.PadMode_Progress_S1.PadMode_Progress_S1_blk 0" in started and "WORDS PadMode_Progress_S1_Num:  " in started


def test_the_progress_panel_number_follows_every_hit_with_no_note(tmp_path):
    """PAD-690 (David: KING CAESAR's badge "only updating every 5 ... all values on the hud indicators need to update
    live"): a Progress panel block puts the count on the mode's badge at once, with no note in the middle."""
    p = maser_hud()
    p["scripts"].append({"hat": {"kind": "shot", "shot": "Big loop", "when": "idle"}, "do": [
        {"op": "change", "var": "loops", "by": num(1)},
        {"op": "hud_progress", "value": {"k": "op", "op": "-", "a": num(10), "b": var("loops")}}]})
    p["vars"].append({"name": "loops", "reset": "game"})
    assert BM.problems(p, SHOTS) == []
    out = play(tmp_path, p, "shot", "Big loop", "secs", 1, "shot", "Big loop", "secs", 1, "shot", "Big loop", "secs", 1)
    for n in (9, 8, 7):
        assert "WORDS PadMode_Progress_S1_Num: %d" % n in out
    assert "Hud_Award" not in out[out.index(">> shot Big loop"):]                   # no note
    # a mode with its own corner meter stays off the panel (its meter says it)
    assert "if (run.on || HUD_METER) return;" in BM.to_c(p, "blk")


def test_a_ball_save_block_asks_the_runtime_for_one(tmp_path):
    """PAD-690 (David: GODZILLA ANGRY's drain with locks "ended the game immediately"; the C kept a ball save of its own
    from the first lock): a Ball save block asks pm_ball_save while the mode runs."""
    p = maser_hud()
    p["scripts"].append({"hat": {"kind": "mode_start"}, "do": [{"op": "ball_save", "seconds": 15}]})
    assert BM.problems(p, SHOTS) == []
    assert BM.problems(dict(p, scripts=p["scripts"] + [{"hat": {"kind": "mode_start"}, "do": [
        {"op": "ball_save", "seconds": 500}]}]), SHOTS) != []
    out = play(tmp_path, p, "shot", "Maser target", "secs", 2)
    start = out[out.index("START"):]
    assert re.search(r"BALL ?SAVE 15", start, re.I), start[:600]


def test_a_ball_in_the_trough_is_a_hat_of_its_own(tmp_path):
    """PAD-690: When a ball goes into the trough - the port's Trough switch shot (PAD-416, code modes only until now),
    the moment a ball drains even when a ball save serves it back; a card with no trough says so."""
    p = maser_hud()
    p["scripts"].append({"hat": {"kind": "drain", "when": "running"}, "do": [{"op": "log", "text": "IN THE TROUGH"}]})
    le, pro = BM.card_checks(MP.profile("godzilla_le_1_16")), BM.card_checks(MP.profile("godzilla_pro_1_16"))
    assert le["drain"] and not pro["drain"]
    assert not [x for x in BM.problems(p, **le) if "trough" in x]
    assert [x for x in BM.problems(p, **pro) if "trough" in x]
    c = BM.to_c(p, "blk")
    assert '"Trough"' in c and "IN THE TROUGH" in c


def test_every_note_under_a_display_of_the_games_shows_at_once(tmp_path):
    """PAD-680 (emulator, the same shots on the 2026-10-07 code-mode card and on the blocks card: a note after 8 of 15
    shots against 4): each note shows at once over the game's shot screen, the second as the first."""
    out = play(tmp_path, _noting_prog(), "covered", 1, "shot", "Big loop", "secs", 4, "covered", 0, "secs", 1,
               "covered", 1, "shot", "Big loop", "secs", 1, "covered", 0, "secs", 1)
    first = out[out.index(">> shot Big loop"):out.index(">> covered 0")]
    second = out[out.rindex(">> covered 1"):out.rindex(">> covered 0")]
    assert "Hud_AwardSub: 1  -  TO GO" in first and "Hud_AwardSub: 2  -  TO GO" in second
    assert "its words wait while a display" not in out


def test_a_note_shows_over_the_modes_loop(tmp_path, monkeypatch):
    """PAD-658 (run bedfix_pro_r1, bf_ready_c: HE JOINS THE NEXT BATTLE over the live city's TANKS 0/10): a note shows
    over the mode's own loop, as the game's feedback screens show over a clip of theirs; it goes with the note, and a
    start on it keeps it as the run's own."""
    _cc()
    p = _hud_media_prog()
    p["scripts"].append({"hat": {"kind": "shot", "shot": "Big loop", "when": "idle"}, "do": [
        {"op": "hud_award", "text": "READY", "value": None, "sub": "", "seconds": 2}]})
    assert "#define COVER_CLIP \"loop\"" in BM.to_c(p, "blk")
    assert "note_loop" not in BM.to_c(_media_prog(), "blk")            # no HUD: no note
    monkeypatch.setenv("HARNESS_DUMP", _assets(tmp_path, "blk", p, []))
    out = play(tmp_path, p, "shot", "Big loop", "secs", 4)
    assert "own clip loop (PadMode_blk_Loop) behind its note" in out
    assert 1900 <= _at(out, "BACKDROP OFF") - _at(out, "BACKDROP PadMode_blk_Loop") <= 2100
    # the mode started while its note shows: the loop is its run's now, never taken away between
    out = play(tmp_path, p, "shot", "Big loop", "secs", 0.5, "shot", "Building", "secs", 3)
    assert "BACKDROP PadMode_blk_Loop" in out and "BACKDROP OFF" not in out
    assert "[TEST MODE] START" in out


def test_with_no_loop_its_start_clip_covers_its_note_and_its_total(tmp_path, monkeypatch):
    """PAD-658 (run loopfix_r1, lf_an_note_b: ANGUIRUS IS READY over TANKS - he has no loop of his own): a mode with no
    clip over and over shows its notes and its TOTAL over the first clip it starts with."""
    _cc()
    p = _hud_media_prog()
    p["scripts"][1]["do"] = p["scripts"][1]["do"][:1]                   # its intro, and no loop
    p["scripts"].append({"hat": {"kind": "shot", "shot": "Big loop", "when": "idle"}, "do": [
        {"op": "hud_award", "text": "READY", "value": None, "sub": "", "seconds": 2}]})
    assert "#define COVER_CLIP \"intro\"" in BM.to_c(p, "blk")
    monkeypatch.setenv("HARNESS_DUMP", _assets(tmp_path, "blk", p, []))
    out = play(tmp_path, p, "shot", "Big loop", "secs", 3, "shot", "Building", "secs", 14)
    assert "own clip intro (PadMode_blk_Intro) behind its note" in out
    end = _at(out, r"\[TEST MODE\] END \(time ran out\)")
    assert "own clip intro (PadMode_blk_Intro) behind its TOTAL" in out
    assert 0 <= _at(out, "BACKDROP KEPT behind TEST MODE's ending") - end <= 20


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


# ---- PAD-395: the mechanisms (the magnet, the scoop, the Premium's held coils) ----------------------------
def _coil_prog(**kw):
    return prog([
        {"hat": {"kind": "shot", "shot": "Slingshot", "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "mode_start"}, "do": [{"op": "scoop_hold", "ms": num(5000), "which": "next"}]},
        {"hat": {"kind": "shot", "shot": "Godzilla target", "when": "running"}, "do": [
            {"op": "hold", "what": "magnet", "ms": num(2000)}]},
        {"hat": {"kind": "shot", "shot": "Left ramp", "when": "running"}, "do": [
            {"op": "hold", "what": "bridge", "ms": {"k": "op", "op": "*", "a": num(3), "b": num(1000)}}]},
        {"hat": {"kind": "shot", "shot": "Building", "when": "running"}, "do": [{"op": "let_go", "what": "*"}]},
        {"hat": {"kind": "shot", "shot": "Maser target", "when": "running"}, "do": [
            {"op": "hold", "what": "mg_magnet", "ms": {"k": "var", "name": "long"}}]},
    ], vars=[{"name": "long", "reset": "mode"}], seconds=0, **kw)


def test_the_mechanism_blocks_are_checked_against_the_runtimes_limits_and_the_game():
    mechs = {"magnet": "magnet", "mg_magnet": "Mechagodzilla magnet", "bridge": "bridge"}
    assert BM.problems(_coil_prog(), mechs=mechs, scoop=True) == []
    assert BM.problems(_coil_prog()) == []                       # no card: no game to check against
    p = prog([{"hat": {"kind": "mode_start"}, "do": [
        {"op": "hold", "what": "magnet", "ms": num(6000)}, {"op": "hold", "what": "", "ms": num(1000)},
        {"op": "hold", "what": "bridge", "ms": num(50)}, {"op": "scoop_hold", "ms": num(20000), "which": "next"},
        {"op": "scoop_hold", "ms": num(1000), "which": "all of them"}, {"op": "let_go", "what": ""}]}])
    got = BM.problems(p, mechs={"magnet": "magnet"}, scoop=False)
    assert got == [
        "Script 1 holds it 100 to 5000 ms.",
        "Script 1 holds a mechanism with none chosen.",
        "Script 1 holds the bridge, which a mode cannot hold on this card's game.",
        "Script 1 holds a ball in the scoop, which a mode cannot do on this card's game.",
        "Script 1 holds a ball 100 to 10000 ms.",
        "Script 1 holds a ball in the scoop: the next one or every one.",
        "Script 1 lets go of nothing chosen."]
    assert BM.HOLD_MAX_MS == MP.COIL_MAX_MS == MP.MAGNET_MAX_MS and BM.SCOOP_MAX_MS == MP.SCOOP_MAX_MS
    # a hold where the mode is not running does nothing: said, not refused
    idle = prog([{"hat": {"kind": "mode_end"}, "do": [{"op": "hold", "what": "magnet", "ms": num(1000)}]}])
    assert any("held only while the mode runs" in n for n in BM.notes(idle))
    assert not any("held only while" in n for n in BM.notes(_coil_prog()))


def test_the_mechanism_c_calls_only_the_header_and_only_when_a_block_holds():
    src = BM.to_c(_coil_prog(), "coils")
    used = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", src))
    assert used <= _header_calls(), used - _header_calls()
    assert {"pm_coil_hold", "pm_coil_release", "pm_scoop_hold", "pm_scoop_holding"} <= used
    assert 'hold("magnet", (2000LL));' in src and "scoop_hold((5000LL), 1);" in src and "let_go_all();" in src
    # every coil a block names is let go by Let go of everything; nothing fires a coil by number
    lets = re.search(r"static void let_go_all\(void\)\n\{(.*?)\n\}", src, re.S).group(1)
    assert [m for m in re.findall(r'pm_coil_release\("(\w+)"\)', lets)] == ["magnet", "bridge", "mg_magnet"]
    # PAD-621: the C clamps a hold to the longest any mechanism allows (Bond's right return up post, 14 s); the
    # runtime keeps each one's own limit (5 s for these)
    assert "if (ms > 14000) ms = 14000;" in src and "if (ms > 10000) ms = 10000;" in src
    assert "pm_coil_hold" not in BM.to_c(BM.starter("RAMP FRENZY", SHOTS), "ramp_frenzy")
    assert "scoop_tick" not in BM.to_c(BM.starter("RAMP FRENZY", SHOTS), "ramp_frenzy")


def test_the_mechanisms_build_with_build_mode_sh(tmp_path):
    if os.name == "nt":
        pytest.skip("build_mode.sh runs under bash with arm-linux-gnueabihf-gcc (WSL or Linux)")
    if not shutil.which("bash") or not shutil.which("arm-linux-gnueabihf-gcc"):
        pytest.skip("no arm-linux-gnueabihf-gcc here")
    src = tmp_path / "coils.c"
    src.write_text(BM.to_c(_coil_prog(), "coils"), encoding="utf-8")
    out = tmp_path / "mode.so"
    r = subprocess.run(["bash", os.path.join(SDK, "build_mode.sh"), "-o", str(out), str(src)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "warning" not in (r.stdout + r.stderr).lower()


def test_the_blocks_hold_the_magnet_the_bridge_and_the_next_ball_in_the_scoop(tmp_path):
    out = play(tmp_path, _coil_prog(),
               "shot", "Slingshot", "scoop", "secs", 6, "scoop",
               "shot", "Godzilla target", "shot", "Godzilla target", "secs", 3,
               "shot", "Godzilla target", "secs", 3.5, "shot", "Godzilla target",
               "shot", "Left ramp", "ms", 500, "shot", "Building",
               "shot", "Maser target", "ball_end")
    assert "START (a block)" in out
    # the next ball in the scoop is held 5 s and kicked; the one after it is kicked at once
    assert re.search(r"SCOOP ball held 5000 ms\n(?:.*\n)*?\s*\d+ SCOOP KICK after 50\d\d ms \(its time ran out\)", out)
    assert "SCOOP KICK at once (no hold)" in out
    assert re.search(r"SCOOP HOLD 0 TEST MODE", out)
    # the magnet: held 2 s, a hit mid-hold refused, one 3 s after refused (within 3 s of its end), then held
    assert out.count("HOLD magnet 2000 ms TEST MODE") == 2
    assert "HOLD magnet refused - a hold is already on" in out
    assert "HOLD magnet refused - within 3 s of the last" in out
    assert re.search(r"LET GO magnet after 20\d\d ms \(its time ran out\)", out)
    # the bridge for a value (3 x 1000), let go early by Let go of everything
    assert "HOLD bridge 3000 ms TEST MODE" in out
    assert re.search(r"LET GO bridge after 5\d\d ms \(the mode let go\)", out)
    # a variable of 0 is clamped up to the runtime's least, and the drain ends it and lets go
    assert "HOLD mg_magnet 100 ms TEST MODE" in out
    assert "END (ball ended)" in out


def test_holding_every_ball_in_the_scoop_and_a_game_with_no_mechanisms(tmp_path, monkeypatch):
    p = _coil_prog()
    p["scripts"][1]["do"][0]["which"] = "every"
    p["scripts"][1]["do"][0]["ms"] = num(20000)                 # past the cap: the runtime's 10 s
    out = play(tmp_path, p, "shot", "Slingshot", "scoop", "secs", 11, "scoop", "secs", 1, "shot", "Building")
    assert out.count("SCOOP ball held 10000 ms") == 2               # every ball, at most 10 s
    assert re.search(r"SCOOP KICK after \d+ ms \(the mode let go\)", out)   # Let go of everything
    monkeypatch.setenv("HARNESS_COILS", "none")
    out = play(tmp_path, _coil_prog(), "shot", "Slingshot", "scoop", "shot", "Godzilla target")
    assert "hold magnet: refused" in out and "scoop: no hold on this game" in out
    assert "HOLD magnet" not in out and "SCOOP KICK at once (no hold)" in out


# ---- PAD-413: its total gives way when another of our modes begins ------------------------------------------------
def test_its_screens_total_gives_way_when_another_mode_begins(tmp_path):
    """David's Premium, 2026-10-06: another mode began during an ending and both modes' words shared the glass.
    A blocks mode's own screen keeps its TOTAL a few seconds after the end; another of our modes beginning
    (here one in C with no screen of its own) hides it on the next tick."""
    from tests.test_spike2_intricate_modes import PLAIN_MODE
    cc = _cc()
    p = prog([{"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [{"op": "start_mode"}]}],
             seconds=2, screen=True, priority=180)
    (tmp_path / "blk.c").write_text(BM.to_c(p, "blk"), encoding="utf-8")
    (tmp_path / "plain.c").write_text(PLAIN_MODE, encoding="utf-8")
    exe = tmp_path / "harness"
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wextra", "-Wno-unused-parameter", "-I", SDK,
                        "-I", os.path.join(SDK, "examples"), "-o", str(exe), os.path.join(SDK, "examples", "desk_harness.c"),
                        str(tmp_path / "blk.c"), str(tmp_path / "plain.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    def run(*args):
        r = subprocess.run([str(exe), "new_game"] + [str(a) for a in args], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        return r.stdout

    def hides(out, after):
        return [int(t) for t in re.findall(r"^\s*(\d+) SHOW PadMode_blk_Screen 0$", out, re.M) if int(t) >= after]

    alone = run("shot", "Left ramp", "secs", 3, "secs", 5)
    end = _at_any(alone, r"END \(time ran out\)")
    assert "gives way" not in alone and hides(alone, end)[0] - end >= 2900       # its total stays its time
    out = run("shot", "Left ramp", "secs", 3, "trigger", "plain.start", "secs", 1)
    began = _at_any(out, r"\[PLAIN\] START")
    assert _at_any(out, r"END \(time ran out\)") < began
    assert "[TEST MODE] its total gives way - another mode began" in out
    assert hides(out, began) and hides(out, began)[0] - began <= 40              # the next tick


# ---- PAD-503: the mode lit at a shot, as the game lights one of its mini-wizards ------------------------------------
LIT = {"op": "light_mode", "shot": "Right ramp", "insert": "MASER READY", "color": "#ffd000", "pattern": "blink"}


def _lit_prog(**kw):
    """Lit by the skill shot (a film done, on Bond); its Right ramp pays while it runs."""
    return prog([{"hat": {"kind": "event", "event": "skill_shot", "when": "any"}, "do": [dict(LIT)]},
                 {"hat": {"kind": "shot", "shot": "Right ramp", "when": "running"},
                  "do": [{"op": "score", "points": num(1000)}]},
                 {"hat": {"kind": "ball_end"}, "do": [
                     {"op": "if", "cond": {"k": "lit"}, "then": [{"op": "log", "text": "still lit"}], "else": None}]}],
                **dict({"seconds": 5}, **kw))


def test_light_the_mode_at_a_shot_is_checked():
    """A Bond owner's own mini-wizards for the two films without one (PAD-503): lit at the Right ramp with the film's
    villain, as the game's four are. The shot, the insert (any the card's game names), the colour and the pattern."""
    p = _lit_prog()
    assert BM.problems(p, SHOTS, GZ.events, inserts=["MASER READY", "RIGHT RAMP"]) == []
    assert not any("No block starts the mode" in n for n in BM.notes(p))       # the lit shot starts it
    assert BM.problems(p, SHOTS, GZ.events, inserts=[]) == []      # no insert a mode can light here: lit without it
    bad = prog([{"hat": {"kind": "event", "event": "skill_shot", "when": "any"}, "do": [
        dict(LIT, shot="Moon ramp", insert="BLOFELD", color="gold", pattern="hurry"),
        dict(LIT, insert=["A"]), dict(LIT, insert="X" * 40)]}])
    assert BM.problems(bad, SHOTS, GZ.events, inserts=["MASER READY"]) == [
        "Script 1's Light the mode at names Moon ramp, a shot this card does not have.",
        "Script 1 lights the mode in no color.",
        "Script 1 lights the mode in no pattern.",
        "Script 1 lights the insert BLOFELD, which this card's game does not have.",
        "Script 1 lights an insert that is not one."]                       # both: said once
    # a mode with no such block makes the C it always made: no lit-at code in it
    assert "lit_" not in BM.to_c(BM.starter("RAMP FRENZY", SHOTS), "ramp_frenzy")


def test_the_lit_c_only_calls_what_the_header_declares():
    src = BM.to_c(_lit_prog(), "lit")
    used = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", src))
    assert used <= _header_calls(), used - _header_calls()
    assert '{ 0, "MASER READY", 0xffd000u, PM_LAMP_BLINK, 500u, "", 0x000000u },   /* Right ramp */' in src
    # the same block twice is one row; "the mode is lit" with no such block is never lit
    two = prog([{"hat": {"kind": "event", "event": "skill_shot", "when": "any"}, "do": [dict(LIT), dict(LIT)]}])
    assert BM.to_c(two, "lit").count("PM_LAMP_BLINK, 500u, ") == 1
    asked = prog([{"hat": {"kind": "ball_end"}, "do": [
        {"op": "if", "cond": {"k": "lit"}, "then": [{"op": "log", "text": "x"}], "else": None}]}])
    assert "static int lit_now(void) { return 0; }" in BM.to_c(asked, "asked")


BOND_VILLAINS = "DR. NO-RIGHT RAMP,ROSA KLEBB,GOLDFINGER-RIGHT RAMP,LARGO,BLOFELD,MR. HENDERSON"


def test_a_lit_mode_cycles_several_inserts_and_holds_one_solid_as_the_games_own():
    """The Bond owner (PAD-521): their own mini-wizards should look like the game's own - while one is qualified the
    Right ramp's villain inserts cycle and the film's insert is solid. Light the mode at names several inserts (a chase
    runs across them, as pm_lamp_set takes a list) and one more held solid in its own colour."""
    ok = prog([{"hat": {"kind": "event", "event": "skill_shot", "when": "any"}, "do": [
        dict(LIT, insert=BOND_VILLAINS, pattern="chase", solid="Y.O.L.T.", solid_color="#ffffff")]}])
    bond = BOND_VILLAINS.split(",") + ["Y.O.L.T.", "RIGHT RAMP ARROW"]
    assert BM.problems(ok, SHOTS, GZ.events, inserts=bond) == []
    assert BM.lit_inserts(" A, B ,A,, ") == ["A", "B"] and BM.lit_inserts("") == [] and BM.lit_inserts(3) is None
    src = BM.to_c(ok, "lit")
    assert ('{ 0, "%s", 0xffd000u, PM_LAMP_CHASE, 150u, "Y.O.L.T.", 0xffffffu },   /* Right ramp */' % BOND_VILLAINS
            in src)
    assert "pm_lamp_set(LIT_AT[k].solid, LIT_AT[k].solid_rgb, PM_LAMP_SOLID, 0);" in src
    assert "pm_lamp_release(LIT_AT[k].solid);" in src
    bad = prog([{"hat": {"kind": "event", "event": "skill_shot", "when": "any"}, "do": [
        dict(LIT, insert=",".join("I%d" % i for i in range(9)), solid="FILM, TWO"),
        dict(LIT, solid="NOPE"), dict(LIT, solid="Y.O.L.T.", solid_color="white")]}])
    assert BM.problems(bad, SHOTS, GZ.events, inserts=bond + ["MASER READY"] + ["I%d" % i for i in range(9)]) == [
        "Script 1 lights more than 8 inserts.",
        "Script 1 holds an insert solid that is not one.",
        "Script 1 holds the insert NOPE solid, which this card's game does not have.",
        "Script 1 holds an insert solid in no color."]


def test_a_lit_mode_chases_its_inserts_and_holds_the_solid_one_on_the_harness(tmp_path):
    lit = dict(LIT, insert="MASER READY,TANK 2,HEAT RAY", pattern="chase", solid="SKILL SHOT", solid_color="#ffffff")
    p = prog([{"hat": {"kind": "event", "event": "skill_shot", "when": "any"}, "do": [lit]}], seconds=5)
    out = play(tmp_path, p, "event", "skill_shot", "secs", 0.2, "lamps", "shot", "Right ramp", "secs", 0.2, "lamps")
    held = re.findall(r"HELD (RIGHT RAMP|MASER READY|TANK 2|HEAT RAY|SKILL SHOT|none)( \w+ \w+)?", out)
    assert [h for h, _c in held] == ["RIGHT RAMP", "MASER READY", "SKILL SHOT", "TANK 2", "HEAT RAY", "none"]
    assert "LAMP MASER READY ffd000 chase 150 TEST MODE" in out and "LAMP SKILL SHOT ffffff solid 0 TEST MODE" in out
    assert "START (its lit shot): player 1" in out
    assert "LAMP OFF SKILL SHOT TEST MODE" in out and "LAMP OFF HEAT RAY TEST MODE" in out


def test_the_bond_le_offers_its_villains_inserts():
    p = MP.profile("james_bond_le_1_06")
    assert {"BLOFELD", "MR. HENDERSON", "LARGO", "ROSA KLEBB", "RIGHT RAMP ARROW"} <= set(p.inserts)
    assert "Right ramp exit opto" in [n for n, _m in p.shots] and p.wizard_shot == "Right ramp"


BOND_CHAPTERS = ["Dr No's Lair", "Orient Express", "Oddjob Battles Bond", "Cut Bond in Half", "Mr Osato",
                 "Professor Dent", "Mr Wint & Mr Kidd", "Feeding Frenzy", "Fiona Volpe", "Under Water Fight",
                 "Training Grounds", "Diamond Death Ray"]


@pytest.mark.parametrize("key", ["james_bond_le_1_06", "james_bond_pro_1_06"])
def test_both_bonds_can_hold_off_the_games_henchman_and_villain_modes(key):
    """PAD-526: an owner wanted none of the game's modes to start during theirs, the henchman and villain modes too.
    The LE 1.06 offered its twelve (the story's chapters, ids 16..27); the Pro 1.06 offered none, though its program
    has the same chapter table (0x629018) and the same starts. Both now tick them by default, each refused with 0."""
    p = MP.profile(key)
    names = {i: n for i, n, _on in p.game_modes}
    assert [names.get(i) for i in range(16, 28)] == BOND_CHAPTERS
    assert all(on for i, _n, on in p.game_modes if i >= 16)               # ticked: held off unless unticked
    port = open(os.path.join(SDK, "ports", key.replace("_1_06", "-1.06") + ".port"), encoding="utf-8").read()
    assert all(re.search(r"^value block_ret_%d\s+0$" % i, port, re.M) for i in range(16, 28))


@pytest.mark.parametrize("key", ["james_bond_le_1_06", "james_bond_pro_1_06"])
def test_both_bonds_can_hold_off_jetpack_and_bird_one_multiball(key):
    """PAD-578: an owner's mode was killed by Jetpack Multiball, started mid-mode; Bird One Multiball the same. A
    multiball's start is never refused (balls held for it), so each is the game's own LOCK-OPEN check instead (ids
    28, 29), refused with 0 - the lock closed as the game closes it for its own gadget modes - ticked by default."""
    p = MP.profile(key)
    names = {i: n for i, n, _on in p.game_modes}
    assert (names.get(28), names.get(29)) == ("Jetpack Multiball", "Bird One Multiball")
    assert all(on for i, _n, on in p.game_modes if i in (28, 29))
    port = open(os.path.join(SDK, "ports", key.replace("_1_06", "-1.06") + ".port"), encoding="utf-8").read()
    assert all(re.search(r"^value block_ret_%d\s+0$" % i, port, re.M) for i in (28, 29))
    # the sites are c_port_tool's LOCKS, each opening `push {r3, lr}; bl <the game's in-the-way check>`
    tool = open(os.path.join(SDK, "cstarts", "c_port_tool.py"), encoding="utf-8").read()
    for i in (28, 29):
        addr, w0, w1 = re.search(r"^site block_start_%d\s+(0x\w+) (0x\w+) (0x\w+)$" % i, port, re.M).groups()
        assert w0 == "0xe92d4008" and int(w1, 16) >> 24 == 0xEB
        assert '("%s", 0x%x)' % (names[i], int(addr, 16)) in tool


def test_a_mode_lit_at_a_shot_starts_from_it_ball_after_ball_and_per_player(tmp_path):
    out = play(tmp_path, _lit_prog(),
               "shot", "Right ramp",                                # not lit yet: nothing
               "event", "skill_shot", "secs", 0.2, "lamps",          # lit for player 1
               "ball_end", "secs", 0.2, "lamps",                     # still lit the next ball
               "player", 2, "secs", 0.2, "lamps", "shot", "Right ramp",   # player 2 is not lit
               "player", 1, "secs", 0.2, "lamps",
               "shot", "Right ramp", "lamps",                        # starts it, and the light goes out
               "shot", "Right ramp", "secs", 6,                      # pays while it runs; its clock ends it
               "secs", 0.2, "lamps", "shot", "Right ramp")           # not lit again: nothing
    assert out.count("[TEST MODE] lit at Right ramp for player 1") == 1
    held = re.findall(r"HELD (RIGHT RAMP|MASER READY|none)", out)
    assert held == ["RIGHT RAMP", "MASER READY", "RIGHT RAMP", "MASER READY", "none", "RIGHT RAMP", "MASER READY",
                    "none", "none"]
    assert "LAMP RIGHT RAMP ffd000 blink 500 TEST MODE" in out and "LAMP MASER READY ffd000 blink 500 TEST MODE" in out
    assert out.count("START (") == 1 and "START (its lit shot): player 1" in out
    assert out.index("START (its lit shot)") > out.index("HELD none")       # player 2's shot started nothing
    assert scores(out) == [1000]                                     # the shot that starts it pays nothing
    assert "END (time ran out)" in out and "still lit" in out
    assert "lamps held 0" in out


def test_a_lit_mode_waits_lit_while_the_game_is_busy_and_a_new_game_puts_it_out(tmp_path):
    out = play(tmp_path, _lit_prog(game_modes="give_way"),
               "event", "skill_shot", "battle", 1, "shot", "Right ramp", "secs", 0.2, "lamps",   # in the way: stays lit
               "battle", 0, "shot", "Right ramp")                                                # now it starts
    assert re.search(r"not started \(its lit shot\): .+ is running - still ready", out)
    # PAD-675 (David's machine: a lit mode's inserts flashed through a battle): its light is dark while it waits
    assert re.findall(r"HELD (RIGHT RAMP|MASER READY|none)", out) == ["none"]
    assert out.count("START (its lit shot)") == 1 and out.index("START (its lit shot)") > out.index(">> battle 0")
    out = play(tmp_path, _lit_prog(), "event", "skill_shot", "secs", 0.2, "game_over", "secs", 0.2, "lamps",
               "new_game", "secs", 0.2, "shot", "Right ramp")
    assert "HELD none" in out and "START (" not in out


def test_a_hold_in_play_is_not_a_new_game(tmp_path):
    """The Bond owner, on v1.169.0: Diamonds Are Forever lit their mode while the mode that won its last part still ran,
    and once that mode was over the Right ramp was dark. James Bond holds play at the end of each of its modes and
    multiballs (mode mask busy bits 0x202: pm_in_game() is 0 for a moment), and the blocks took pm_in_game() rising
    for a new game - the light, the "each game" values and the timers were wiped. A new game is the SDK's witness
    now (player 1's score back to 0, or pm_in_game() rising while it is 0)."""
    p = _lit_prog(vars=[{"name": "films", "reset": "game"}], timers=[{"name": "window"}])
    p["scripts"][0]["do"] += [{"op": "change", "var": "films", "by": num(1)},
                              {"op": "timer_start", "timer": "window", "ms": num(4000)}]
    p["scripts"] += [{"hat": {"kind": "mode_start"}, "do": [
                         {"op": "score", "points": {"k": "op", "op": "*", "a": {"k": "var", "name": "films"},
                                                    "b": num(7)}}]},
                     {"hat": {"kind": "timer_done", "timer": "window"}, "do": [{"op": "log", "text": "window over"}]}]
    out = play(tmp_path, p, "points", 250000, "event", "skill_shot", "secs", 0.2,
               "hold", 2.5, "secs", 0.2, "lamps",           # the game's mode is won: play held, then on
               "secs", 2, "shot", "Right ramp")
    assert re.findall(r"HELD (RIGHT RAMP|MASER READY|none)", out) == ["RIGHT RAMP", "MASER READY"]
    assert "START (its lit shot): player 1" in out
    assert 7 in scores(out)                                         # films was still 1
    assert "[TEST MODE] window over" in out                         # the timer ran on
    # a real new game still puts the light out (player 1's score back to 0)
    out = play(tmp_path, p, "points", 250000, "event", "skill_shot", "secs", 0.2, "game_over", "secs", 0.2,
               "new_game", "secs", 0.2, "lamps", "shot", "Right ramp")
    assert "HELD none" in out and "START (" not in out


def test_a_lit_mode_waits_out_the_games_own_modes_as_its_mini_wizards_do(tmp_path):
    """The Bond owner's next game (PAD-503): Mr Osato, a henchman mode of the game's, completed You Only Live Twice and
    lit their mode; the game's own mini-wizards do not start while such a mode runs (its check 0x110b90), and the port's
    flags do not show it, so a Right ramp in the middle of Mr Osato started theirs. The lit shot waits on the game's own
    check (pm_game_wizard_way), whatever the mode says about the game's modes ("may start" here)."""
    out = play(tmp_path, _lit_prog(), "event", "skill_shot", "way", 0, "shot", "Right ramp", "secs", 0.2, "lamps",
               "way", 1, "shot", "Right ramp")
    assert "not started (its lit shot): one of the game's own modes is in its way - still lit" in out
    assert re.findall(r"HELD (RIGHT RAMP|MASER READY|none)", out) == ["none"]        # PAD-556: its light waits too
    assert out.count("START (its lit shot)") == 1 and out.index("START (its lit shot)") > out.index(">> way 1")
    # a Start the mode that gives way waits on it too; one that runs beside the game's modes does not
    p = prog([{"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [{"op": "start_mode"}]}],
             seconds=5, game_modes="give_way")
    out = play(tmp_path, p, "way", 0, "shot", "Left ramp", "way", 1, "shot", "Left ramp")
    assert "still ready" in out                                  # PAD-680: the shot counts, its start waits
    assert out.count("START (a block)") == 1 and out.index("START (a block)") > out.index(">> way 1")
    out = play(tmp_path, dict(p, game_modes="stack"), "way", 0, "shot", "Left ramp")
    assert "START (a block)" in out


def test_a_lit_mode_chases_only_once_the_games_own_mode_is_over(tmp_path):
    """The Bond owner (PAD-556): Blofeld, the game's villain mode, won You Only Live Twice's last part, and the villain
    inserts began to rove at once - though the mode cannot start until Blofeld is over, and the game's own mini-wizards
    rove only then. While the game's own check says something is in the way, only the solid insert (the film's) is
    held; the shot and the chase come once it is clear, and go again if the game's next mode gets in the way."""
    lit = dict(LIT, insert="MASER READY,TANK 2,HEAT RAY", pattern="chase", solid="SKILL SHOT", solid_color="#ffffff")
    p = prog([{"hat": {"kind": "event", "event": "skill_shot", "when": "any"}, "do": [lit]}], seconds=5)
    out = play(tmp_path, p, "way", 0, "event", "skill_shot", "secs", 0.2, "lamps",      # film won mid-Blofeld
               "way", 1, "secs", 0.2, "lamps",                                          # Blofeld over: it roves
               "way", 0, "secs", 0.2, "lamps",                                          # the game's next mode
               "way", 1, "secs", 0.2, "shot", "Right ramp")
    held = re.findall(r"HELD (RIGHT RAMP|MASER READY|TANK 2|HEAT RAY|SKILL SHOT|none)", out)
    assert held == ["SKILL SHOT",
                    "RIGHT RAMP", "MASER READY", "SKILL SHOT", "TANK 2", "HEAT RAY",
                    "SKILL SHOT"]
    assert out.index("LAMP MASER READY ffd000 chase 150") > out.index(">> way 1")
    assert "LAMP OFF MASER READY TEST MODE" in out
    assert "START (its lit shot): player 1" in out


def test_a_lit_mode_claims_its_shot_while_it_would_start_there(tmp_path):
    """The owner on v1.169.3: film done, the ramp lit, the film's last mode played out - and the Right ramp started one
    of the game's villains, again and again. On James Bond the Right ramp is where the game starts its henchman and
    villain modes, and the game handles a shot before the modes hear of it, so the lit mode always found one running.
    It claims its shot now (pm_lit_claim) while it would start there: the runtime then holds the game's own starts off
    while the game handles that switch (proven on the rig; MODE_SDK.md). The claim follows the mode's own state."""
    out = play(tmp_path, _lit_prog(), "secs", 0.2, "event", "skill_shot", "secs", 0.2, "way", 0, "secs", 0.2,
               "way", 1, "secs", 0.2, "shot", "Right ramp", "secs", 0.2)
    # lit; the game's own mode in the way; clear again; it started
    assert re.findall(r"LITCLAIM (\w+) TEST MODE", out) == ["200000", "0", "200000", "0"]
    assert "START (its lit shot)" in out


# ---- PAD-521: the game's own status bar (James Bond: the coloured bar under the TV) ---------------------------------
def test_the_bar_is_off_unless_ticked_and_keeps_a_colour():
    p = BM.normalize({"name": "X"})
    assert p["bar"] == {"on": False, "color": "#00c040"}
    assert BM.normalize({"bar": {"on": 1, "color": "blue"}})["bar"] == {"on": True, "color": "#00c040"}
    assert "pm_status_bar" not in BM.to_c(BM.starter("RAMP FRENZY", SHOTS), "ramp_frenzy")
    src = BM.to_c(prog([], bar={"on": True, "color": "#1060ff"}), "blk")
    assert "#define BAR_RGB          0x1060ffu" in src
    used = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", src))
    assert used <= _header_calls(), used - _header_calls()


def test_the_bar_shows_the_name_and_its_clock_then_the_total_then_goes(tmp_path):
    """The Bond owner (PAD-521): the game's own mini-wizards show their name in a coloured bar under the TV, the clock
    draining along it, kept through the total. Started, it is full; the clock runs it down; at the end it is full again
    for the total's 3 s, then given back. A drain keeps it through its TOTAL, the end of ball waiting (PAD-622)."""
    p = prog([{"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [{"op": "start_mode"}]}],
             seconds=4, bar={"on": True, "color": "#00c040"}, name="YOLT WIZARD")
    out = play(tmp_path, p, "shot", "Left ramp", "secs", 2, "secs", 2.5, "secs", 3.5)
    bars = re.findall(r"^\s*(\d+) STATUSBAR (-?\d+|OFF) ?(\w*)", out, re.M)
    pcts = [int(b[1]) for b in bars if b[1] not in ("OFF",)]
    running = [x for x in pcts if x >= 0]
    assert pcts[0] == 100 and pcts[-1] == -1                           # full at the start; full (no wipe) at the end
    assert running == sorted(running, reverse=True) and min(running) <= 5   # it drained with the clock
    assert bars[-1][1] == "OFF"
    end = _at_any(out, r"END \(time ran out\)")
    off = int(bars[-1][0])
    assert 2900 <= off - end <= 3200                                   # through the total
    assert "STATUSBAR 100 00c040 YOLT WIZARD" in out
    out = play(tmp_path, p, "shot", "Left ramp", "secs", 1, "ball_end", "secs", 0.2)
    bars = re.findall(r"^\s*(\d+) STATUSBAR (-?\d+|OFF)", out, re.M)
    assert bars[-1][1] == "OFF" and 0 <= int(bars[-1][0]) - _at_any(out, "BALL END goes on") <= 40
    assert int(bars[-1][0]) - _at_any(out, r"END \(ball ended\)") >= 5900
    out = play(tmp_path, p, "shot", "Left ramp", "secs", 1, "tilt", "ball_end", "secs", 0.2)   # a tilt: at once
    bars = re.findall(r"^\s*(\d+) STATUSBAR (-?\d+|OFF)", out, re.M)
    assert bars[-1][1] == "OFF" and int(bars[-1][0]) - _at_any(out, r"END \(ball ended\)") <= 40


def test_the_bar_can_fill_with_a_value_out_of_another():
    """PAD-721: the Bond owner wanted the bar to fill as shots are made, as the game's own mini-wizards fill theirs
    (10-12 shots each), not drain with the clock. Ticked, it fills with the shots the mode has scored out of 10 unless
    said; an emptied slot stays empty for problems to name; the clock is the bar's as ever without it."""
    assert BM.normalize({"bar": {"on": 1, "fill": "value"}})["bar"] == {
        "on": True, "color": "#00c040", "fill": "value", "value": {"k": "scored"}, "of": {"k": "num", "v": 10}}
    assert "fill" not in BM.normalize({"bar": {"on": 1, "fill": "clock"}})["bar"]
    p = prog([], bar={"on": True, "fill": "value", "value": None, "of": {"k": "num", "v": 12}})
    assert any("The bar's value has an empty number slot" in t for t in BM.problems(p, SHOTS, GZ.events))
    p = prog([], vars=[{"name": "hits", "reset": "mode"}], timers=[{"name": "window"}],
             bar={"on": True, "fill": "value", "value": {"k": "var", "name": "nope"}, "of": {"k": "num", "v": 12}})
    assert any("The bar's value uses a variable that is not there" in t for t in BM.problems(p, SHOTS, GZ.events))
    assert "#define BAR_FILLS 0" in BM.to_c(prog([], bar={"on": True}), "blk")


def test_the_bar_fills_as_shots_are_made_and_stays_through_the_total(tmp_path):
    """PAD-721: 4 shots of 4: empty at the start, a quarter a shot, full at the last, and kept as it was (not the
    clock's full bar) through its total. A value naming a timer builds too (the bar's C comes after timer_left)."""
    p = prog([{"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [{"op": "start_mode"}]},
              {"hat": {"kind": "shot", "shot": "Right ramp", "when": "running"},
               "do": [{"op": "score", "points": {"k": "num", "v": 1000}}]}],
             seconds=20, name="YOLT WIZARD",
             bar={"on": True, "color": "#00c040", "fill": "value", "value": {"k": "scored"}, "of": {"k": "num", "v": 4}})
    out = play(tmp_path, p, "shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 1, "shot", "Right ramp",
               "secs", 1, "shot", "Right ramp", "secs", 1, "shot", "Right ramp", "secs", 1, "shot", "Right ramp",
               "secs", 25)
    pcts = [int(b) for b in re.findall(r"^\s*\d+ STATUSBAR (-?\d+) ", out, re.M)]
    assert pcts[0] == 0 and 100 in pcts
    seen = [x for i, x in enumerate(pcts) if not i or x != pcts[i - 1]]
    assert seen == [0, 25, 50, 75, 100], seen                          # never past full, never the clock's -1
    assert re.findall(r"^\s*\d+ STATUSBAR (\S+)", out, re.M)[-1] == "OFF"
    p["timers"] = [{"name": "window"}]
    p["bar"]["value"] = {"k": "timer_left", "timer": "window"}
    play(tmp_path, p, "secs", 1)


def test_the_bar_fills_with_its_progress_shot_alone(tmp_path):
    """PAD-721 round 2: the owner's mini-wizards score on drops and other shots too, but only the Right ramp is
    progress; "times it has scored" filled the bar on every one. Hits of a shot since it started counts that shot
    alone, made while it runs (not the shot that started it), from none at each start."""
    p = prog([{"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [{"op": "start_mode"}]},
              {"hat": {"kind": "shot", "shot": "Right ramp", "when": "any"},
               "do": [{"op": "score", "points": {"k": "num", "v": 1000}}]},
              {"hat": {"kind": "shot", "shot": "Building", "when": "running"},
               "do": [{"op": "score", "points": {"k": "num", "v": 500}}]}],
             seconds=20, name="YOLT WIZARD",
             bar={"on": True, "fill": "value", "value": {"k": "mode_hits", "shot": "Right ramp"},
                  "of": {"k": "num", "v": 4}})
    assert BM.problems(p, SHOTS, GZ.events) == []
    out = play(tmp_path, p, "shot", "Right ramp", "shot", "Left ramp", "secs", 1, "shot", "Building", "secs", 1,
               "shot", "Right ramp", "secs", 1, "shot", "Building", "shot", "Building", "secs", 1,
               "shot", "Right ramp", "secs", 1)
    pcts = [int(b) for b in re.findall(r"^\s*\d+ STATUSBAR (-?\d+) ", out, re.M)]
    seen = [x for i, x in enumerate(pcts) if not i or x != pcts[i - 1]]
    assert seen == [0, 25, 50], seen        # the Right ramp before it started and the Buildings move nothing
    sim = BS.Sim(BM.normalize(p))
    for s in ("Right ramp", "Left ramp", "Building", "Right ramp", "Right ramp"):
        sim.shot(s)
    assert sim.val({"k": "mode_hits", "shot": "Right ramp"}) == 2 and sim.val({"k": "hits", "shot": "Right ramp"}) == 3


def test_only_a_title_whose_port_names_the_bar_offers_it():
    assert MP.profile("james_bond_le_1_06").status_bar is True
    assert MP.profile("godzilla_le_1_16").status_bar is False


# ---- PAD-521: its own screen as words alone, over the game's video ---------------------------------------------------
def test_words_alone_is_a_screen_style_and_reaches_the_assets(tmp_path):
    assert BM.normalize({})["screen_style"] == "panel"
    assert BM.normalize({"screen_style": "words"})["screen_style"] == "words"
    assert BM.normalize({"screen_style": "big"})["screen_style"] == "panel"
    project = str(tmp_path)
    slug, _c = BM.new_blocks_mode(project, "YOLT WIZARD")
    BM.save(project, slug, BM.normalize({"name": "YOLT WIZARD", "screen": True, "screen_style": "words",
                                         "scripts": []}))
    from pinball_decryptor.plugins.stern import code_modes as CM, mode_assets as MA
    spec = CM.load(project, slug)
    assert spec.screen_style == "words"
    scr = MA.code_screen(project, slug, spec)
    assert scr["words"] == "YOLT WIZARD" and scr["words_rgba"] == (1.0, 1.0, 1.0, 1.0)
    assert scr["art_rgba"].shape == (200, 920, 4) and not scr["art_rgba"].any()   # clear: no panel
    assert (scr["x"], scr["y"]) == MA.WORDS_AT and scr["words_scale"] == 2.0
    BM.save(project, slug, BM.normalize({"name": "YOLT WIZARD", "screen": True, "scripts": []}))
    assert CM.load(project, slug).screen_style == ""                               # the panel again


def test_words_alone_show_the_name_then_a_line_then_the_total(tmp_path):
    """The Bond owner (PAD-521): the game letters a mode's name over its intro and its TOTAL over its end picture, and
    shows nothing of the kind in between. Words alone: the name at the start for 4 s, a Words block's line for 3 s,
    the TOTAL at the end for 3 s - each then hidden."""
    p = prog([{"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [{"op": "start_mode"}]},
              {"hat": {"kind": "shot", "shot": "Right ramp", "when": "running"},
               "do": [{"op": "score", "points": num(500)}, {"op": "words", "text": "JACKPOT"}]}],
             seconds=12, screen=True, screen_style="words")
    out = play(tmp_path, p, "shot", "Left ramp", "secs", 5, "shot", "Right ramp", "secs", 12)
    shows = [(int(t), int(on)) for t, on in re.findall(r"^\s*(\d+) SHOW PadMode_blk_Screen (\d)$", out, re.M)]
    start = _at_any(out, r"START \(a block\)")
    shot = _at_any(out, r"WORDS PadMode_blk_Screen_Words: JACKPOT")
    end = _at_any(out, r"END \(time ran out\)")
    on_at = [t for t, on in shows if on]
    off_at = [t for t, on in shows if not on]
    assert any(abs(t - start) <= 40 for t in on_at)
    assert any(3900 <= t - start <= 4100 for t in off_at)                         # the name, 4 s
    assert any(abs(t - shot) <= 40 for t in on_at) and any(2900 <= t - shot <= 3100 for t in off_at)
    # PAD-574: the TOTAL as the game's own modes end: its two screens under the bar, the words screen hidden
    assert re.search(r"WORDS PadMode_blk_Total_Words: 500", out) and re.search(r"WORDS PadMode_blk_TotalName_Words: TOTAL", out)
    assert not re.search(r"WORDS PadMode_blk_Screen_Words: TOTAL", out)
    tot = [(int(t), int(on)) for t, on in re.findall(r"^\s*(\d+) SHOW PadMode_blk_Total (\d)$", out, re.M)]
    assert any(abs(t - end) <= 40 for t, on in tot if on) and any(2900 <= t - end <= 3200 for t, on in tot if not on)
    assert any(abs(t - end) <= 40 for t in off_at)
    # the panel stays up all along, as ever
    out = play(tmp_path, dict(p, screen_style="panel"), "shot", "Left ramp", "secs", 6)
    assert not [t for t, on in re.findall(r"^\s*(\d+) SHOW PadMode_blk_Screen (\d)$", out, re.M) if on == "0"
                and int(t) > 100]


# ---- PAD-574: an Award on its own screen, and the TOTAL after it ---------------------------------------------------
def _award(**kw):
    """The Bond owner's ending (PAD-574): the last Right ramp scores, awards its SUPER JACKPOT and ends the mode; When
    the mode ends awards TOTAL and its points. No HUD: the Awards go on its own screen."""
    return prog([{"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [{"op": "start_mode"}]},
                 {"hat": {"kind": "shot", "shot": "Right ramp", "when": "running"},
                  "do": [{"op": "score", "points": num(700)},
                         {"op": "hud_award", "text": "SUPER JACKPOT", "value": num(3500), "sub": "", "seconds": 2},
                         {"op": "end_mode"}]},
                 {"hat": {"kind": "mode_end"},
                  "do": [{"op": "hud_award", "text": "TOTAL", "value": {"k": "total"}, "sub": "", "seconds": 2}]}],
                seconds=30, screen=True, **kw)


def test_an_award_ending_the_mode_shows_then_the_next_then_the_total(tmp_path):
    out = play(tmp_path, _award(screen_style="words"), "shot", "Left ramp", "secs", 2, "shot", "Right ramp", "secs", 10)
    end = _at_any(out, r"END \(a block\)")
    # PAD-709: words alone: each Award's number large under the bar (its words small over it), not over the video
    assert abs(_at_any(out, r"WORDS PadMode_blk_Points_Words: 3,500") - end) <= 40
    assert abs(_at_any(out, r"WORDS PadMode_blk_TotalName_Words: SUPER JACKPOT") - end) <= 40
    assert 1900 <= _at_any(out, r"WORDS PadMode_blk_Points_Words: 700") - end <= 2100          # its own turn, 2 s on
    assert not re.search(r"WORDS PadMode_blk_Screen_Words: (SUPER JACKPOT|TOTAL)", out)
    assert 3900 <= _at_any(out, r"WORDS PadMode_blk_Total_Words: 700") - end <= 4100            # then the TOTAL
    pts = [(int(t), int(on)) for t, on in re.findall(r"^\s*(\d+) SHOW PadMode_blk_Points (\d)$", out, re.M)]
    assert pts[-1][1] == 0 and 3900 <= pts[-1][0] - end <= 4100                              # gone for the TOTAL
    tot = [(int(t), int(on)) for t, on in re.findall(r"^\s*(\d+) SHOW PadMode_blk_Total (\d)$", out, re.M)]
    assert any(3900 <= t - end <= 4100 for t, on in tot if on) and any(6900 <= t - end <= 7200 for t, on in tot if not on)
    assert "has no HUD" not in BM.to_c(_award(screen_style="words"), "blk")
    assert BM.problems(_award(screen_style="words")) == [] and not [t for t in BM.notes(_award(screen_style="words")) if "HUD" in t]
    # PAD-622: a drain while they wait: the end of ball waits them out (the game's own mini-wizards' way), then they go
    out = play(tmp_path, _award(screen_style="words"), "shot", "Left ramp", "secs", 2, "shot", "Right ramp",
               "ball_end", "secs", 6)
    end, on = _at_any(out, r"END \(a block\)"), _at_any(out, "BALL END goes on")
    assert 1900 <= _at_any(out, r"WORDS PadMode_blk_Points_Words: 700") - end <= 2100
    assert 3900 <= _at_any(out, r"WORDS PadMode_blk_Total_Words: 700") - end <= 4100
    assert 6900 <= on - end <= 7100
    tot = [(int(t), int(on)) for t, on in re.findall(r"^\s*(\d+) SHOW PadMode_blk_Total (\d)$", out, re.M)]
    assert tot[-1][1] == 0 and 0 <= tot[-1][0] - on <= 40
    # a tilted ball: nothing of it stays
    out = play(tmp_path, _award(screen_style="words"), "shot", "Left ramp", "secs", 2, "shot", "Right ramp",
               "tilt", "ball_end", "secs", 6)
    assert not re.search(r"WORDS PadMode_blk_Total_Words", out)
    pts = re.findall(r"^\s*(\d+) SHOW PadMode_blk_Points (\d)$", out, re.M)
    assert pts[-1][1] == "0" and int(pts[-1][0]) - _at_any(out, ">> ball_end") <= 40
    # PAD-709: a card built before the bar's number: the Awards over the video, as PAD-574 made them
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("HARNESS_NO_NODE", "_Points")
        out = play(tmp_path, _award(screen_style="words"), "shot", "Left ramp", "secs", 2, "shot", "Right ramp", "secs", 10)
    end = _at_any(out, r"END \(a block\)")
    assert abs(_at_any(out, r"WORDS PadMode_blk_Screen_Words: SUPER JACKPOT 3,500") - end) <= 40
    assert 1900 <= _at_any(out, r"WORDS PadMode_blk_Screen_Words: TOTAL 700") - end <= 2100
    assert 3900 <= _at_any(out, r"WORDS PadMode_blk_Total_Words: 700") - end <= 4100


# ---- PAD-709: a scored number under the bar, large, as the game's own mini-wizards show a shot's -------------------
def _scored(**kw):
    """The Bond owner's mini-wizard (PAD-709): each Right ramp scores 1,000,000 and a Words block shows it; the info line
    shows the super jackpot under the bar."""
    return prog([{"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [{"op": "start_mode"}]},
                 {"hat": {"kind": "mode_start"}, "do": [{"op": "set", "var": "superjackpot", "value": num(18000000)}]},
                 {"hat": {"kind": "shot", "shot": "Right ramp", "when": "running"},
                  "do": [{"op": "score", "points": num(1000000)}, {"op": "words", "text": "", "value": num(1000000)}]},
                 {"hat": {"kind": "shot", "shot": "Building", "when": "running"},
                  "do": [{"op": "words", "text": "JACKPOT", "value": num(2500000)}]}],
                vars=[{"name": "superjackpot", "reset": "mode"}], seconds=10, screen=True,
                info={"on": True, "text": "SUPER JACKPOT", "value": var("superjackpot")}, **dict({"screen_style": "words"}, **kw))


def test_a_scored_number_goes_under_the_bar_not_over_the_video(tmp_path):
    """The Bond owner (PAD-709): the game's own mini-wizards pop a scored shot's points up large under the bar; his own
    put them over the movie. Now a Words block's number, while a words-alone mode runs, shows on its own screen under
    the bar for 3 s with the info line (SUPER JACKPOT = ...) hidden meanwhile, then the line comes back; its words, if
    any, go small over it on the TOTAL's word line. Nothing of it over the video; its name still is, at its start."""
    out = play(tmp_path, _scored(), "shot", "Left ramp", "secs", 5, "shot", "Right ramp", "secs", 4,
               "shot", "Building", "secs", 6)
    start, shot = _at_any(out, r"START \(a block\)"), _at_any(out, r">> shot Right ramp")
    assert abs(_at_any(out, r"WORDS PadMode_blk_Screen_Words: TEST MODE") - start) <= 40       # its name, as ever
    assert abs(_at_any(out, r"WORDS PadMode_blk_Points_Words: 1,000,000") - shot) <= 40
    assert not re.search(r"WORDS PadMode_blk_Screen_Words: .*\d", out)                       # no number over the video
    pts = [(int(t), int(on)) for t, on in re.findall(r"^\s*(\d+) SHOW PadMode_blk_Points (\d)$", out, re.M)]
    info = [(int(t), int(on)) for t, on in re.findall(r"^\s*(\d+) SHOW PadMode_blk_Info (\d)$", out, re.M)]
    assert any(abs(t - shot) <= 40 for t, on in pts if on) and any(2900 <= t - shot <= 3100 for t, on in pts if not on)
    assert any(abs(t - shot) <= 40 for t, on in info if not on)                              # the line makes way...
    assert any(2900 <= t - shot <= 3200 for t, on in info if on)                             # ...and comes back
    # its words small over the number, on the TOTAL's word line; gone with it
    jp = _at_any(out, r">> shot Building")
    assert abs(_at_any(out, r"WORDS PadMode_blk_Points_Words: 2,500,000") - jp) <= 40
    assert abs(_at_any(out, r"WORDS PadMode_blk_TotalName_Words: JACKPOT") - jp) <= 40
    names = [(int(t), int(on)) for t, on in re.findall(r"^\s*(\d+) SHOW PadMode_blk_TotalName (\d)$", out, re.M)]
    end = _at_any(out, r"END \(time ran out\)")
    assert any(abs(t - jp) <= 40 for t, on in names if on) and any(abs(t - end) <= 40 for t, on in names if not on)
    # the mode's end takes a number still up with it: the TOTAL in its place
    out = play(tmp_path, _scored(), "shot", "Left ramp", "secs", 9, "shot", "Right ramp", "secs", 4)
    end = _at_any(out, r"END \(time ran out\)")
    pts = [(int(t), int(on)) for t, on in re.findall(r"^\s*(\d+) SHOW PadMode_blk_Points (\d)$", out, re.M)]
    assert pts[-1] == (end, 0) and abs(_at_any(out, r"WORDS PadMode_blk_Total_Words: 1,000,000") - end) <= 40
    # under a display of the game's: out of its way, back after it
    out = play(tmp_path, _scored(), "shot", "Left ramp", "secs", 5, "shot", "Right ramp", "covered", 1, "secs", 1,
               "covered", 0, "secs", 3)
    pts = [int(on) for _t, on in re.findall(r"^\s*(\d+) SHOW PadMode_blk_Points (\d)$", out, re.M)]
    assert pts[-3:] == [0, 1, 0]
    # a card built before it: over the video, as before
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("HARNESS_NO_NODE", "_Points")
        out = play(tmp_path, _scored(), "shot", "Left ramp", "secs", 5, "shot", "Right ramp", "secs", 4)
    assert re.search(r"WORDS PadMode_blk_Screen_Words: 1,000,000", out)
    # a panel keeps its words on itself
    out = play(tmp_path, _scored(screen_style="panel"), "shot", "Left ramp", "secs", 5, "shot", "Right ramp", "secs", 4)
    assert re.search(r"WORDS PadMode_blk_Screen_Words: 1,000,000", out) and "PadMode_blk_Points" not in out
    assert "POINTS_NODE" not in BM.to_c(_scored(screen_style="panel"), "blk")
    src = BM.to_c(_scored(), "blk")
    used = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", src))
    assert used <= _header_calls(), used - _header_calls()


def test_a_words_screen_builds_its_scored_number_under_the_bar(tmp_path):
    project = str(tmp_path)
    slug, _c = BM.new_blocks_mode(project, "BOND VS SUMO")
    BM.save(project, slug, BM.normalize({"name": "BOND VS SUMO", "screen": True, "screen_style": "words", "scripts": []}))
    from pinball_decryptor.plugins.stern import mode_assets as MA
    prof = MP.profile("james_bond_le_1_06")
    names = MP.asset_names(slug)
    assert names["points_node"] == "PadMode_%s_Points" % slug
    got = {s["name"]: s for s in MA._code_screens(project, [(slug, CM.load(project, slug))], prof)}
    pts = got[names["points_node"]]
    h, w = pts["art_rgba"].shape[:2]
    cx, cy = prof.info_at
    assert pts["words"] == " " and not pts["art_rgba"].any()                  # built blank: the mode writes it
    assert (pts["x"] + w / 2.0, pts["y"] + h / 2.0) == (cx, cy + MA.POINTS_DY)
    assert pts["words_scale"] == MA.POINTS_SCALE > got[names["total_node"]]["words_scale"]   # larger than the TOTAL
    assert names["points_text"] == names["points_node"] + "." + pts["words_name"]
    # laid out in the Scenes editor (its points_layout), as its screen and its info line are
    spec = CM.load(project, slug)
    spec.points_layout = {"y": 560.0, "words_scale": 5.0}
    CM.save(project, slug, spec)
    BM.save(project, slug, BM.normalize({"name": "BOND VS SUMO", "screen": True, "screen_style": "words", "scripts": []}))
    spec = CM.load(project, slug)
    assert spec.points_layout == {"y": 560.0, "words_scale": 5.0}             # a blocks save keeps it
    pts = {s["name"]: s for s in MA._code_screens(project, [(slug, spec)], prof)}[names["points_node"]]
    assert pts["y"] == 560.0 and pts["words_scale"] == 5.0 and pts["x"] == cx - w / 2.0
    BM.save(project, slug, BM.normalize({"name": "BOND VS SUMO", "screen": True, "scripts": []}))      # a panel: none
    assert names["points_node"] not in {s["name"] for s in MA._code_screens(project, [(slug, CM.load(project, slug))], prof)}


def test_a_drain_while_it_runs_shows_its_total_and_the_end_of_ball_waits(tmp_path):
    """PAD-622 (the Bond owner): a drain in one of the game's own mini-wizards shows its TOTAL before the bonus; his
    own modes went straight on. Now a drain ends it as its clock would - TOTAL under the bar, the bar kept - and the
    game's end of ball waits the 6 s the game's own TOTAL shows (measured: Goldfinger's Jackpot, LE 1.06)."""
    p = prog([{"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [{"op": "start_mode"}]},
              {"hat": {"kind": "shot", "shot": "Right ramp", "when": "running"}, "do": [{"op": "score", "points": num(500)}]}],
             seconds=30, screen=True, screen_style="words", bar={"on": True, "color": "#00c040"})
    out = play(tmp_path, p, "shot", "Left ramp", "secs", 5, "shot", "Right ramp", "secs", 1, "ball_end", "secs", 2)
    drain, on = _at_any(out, ">> ball_end"), _at_any(out, "BALL END goes on")
    assert _at_any(out, r"END \(ball ended\): 1 scores, total 500") == drain
    assert _at_any(out, "BALL END HOLD 6000 TEST MODE") == drain
    assert _at_any(out, r"WORDS PadMode_blk_Total_Words: 500") == drain
    assert 5900 <= on - drain <= 6100
    tot = [(int(t), int(v)) for t, v in re.findall(r"^\s*(\d+) SHOW PadMode_blk_Total (\d)$", out, re.M)]
    assert (drain, 1) in tot and tot[-1][1] == 0 and 0 <= tot[-1][0] - on <= 40
    assert 0 <= _at_any(out, "STATUSBAR OFF") - on <= 40                       # the bar through it, as the game's
    # a tilted ball, or a mode the drain does not end: no wait
    out = play(tmp_path, p, "shot", "Left ramp", "secs", 2, "tilt", "ball_end", "secs", 1)
    assert "BALL END HOLD" not in out and _at_any(out, "BALL END goes on") == _at_any(out, ">> ball_end")
    out = play(tmp_path, dict(p, ends_on_drain=False), "shot", "Left ramp", "secs", 2, "ball_end", "secs", 1)
    assert "BALL END HOLD" not in out and "END (ball ended)" not in out
    # with a HUD, its TOTAL there for the same 6 s
    out = play(tmp_path, dict(p, screen=False, hud=dict(BM.normalize({})["hud"], on=True)),
               "shot", "Left ramp", "secs", 2, "ball_end", "secs", 1)
    assert 5900 <= _at_any(out, "BALL END goes on") - _at_any(out, ">> ball_end") <= 6100


def test_an_award_on_a_panel_and_with_no_screen(tmp_path):
    out = play(tmp_path, _award(screen_style="panel"), "shot", "Left ramp", "secs", 2, "shot", "Right ramp", "secs", 8)
    end = _at_any(out, r"END \(a block\)")
    assert abs(_at_any(out, r"WORDS PadMode_blk_Screen_Words: SUPER JACKPOT 3,500") - end) <= 40
    totals = [int(t) - end for t in re.findall(r"^\s*(\d+) WORDS PadMode_blk_Screen_Words: TOTAL 700$", out, re.M)]
    assert len(totals) == 2 and 1900 <= totals[0] <= 2100 and 3900 <= totals[1] <= 4100   # its Award, then the TOTAL
    assert "PadMode_blk_Total" not in out                                     # a panel keeps its TOTAL on itself
    off = dict(_award(), screen=False)
    assert "/* hud_award: the mode has no HUD */" in BM.to_c(off, "off")
    assert any("An Award shows on its HUD or its own screen" in t for t in BM.notes(off))


def test_a_words_screen_builds_its_total_where_the_game_puts_its_own(tmp_path):
    project = str(tmp_path)
    slug, _c = BM.new_blocks_mode(project, "BON APPETIT")
    BM.save(project, slug, BM.normalize({"name": "BON APPETIT", "screen": True, "screen_style": "words", "scripts": []}))
    from pinball_decryptor.plugins.stern import code_modes as CM, mode_assets as MA, mode_project as MP
    spec = CM.load(project, slug)
    prof = MP.profile("james_bond_le_1_06")
    names = MP.asset_names(slug)
    got = {s["name"]: s for s in MA._code_screens(project, [(slug, spec)], prof)}
    word, number = got[names["total_name_node"]], got[names["total_node"]]
    cx, cy = prof.info_at
    for s, dy in ((word, MA.TOTAL_NAME_DY), (number, MA.TOTAL_DY)):
        h, w = s["art_rgba"].shape[:2]
        assert s["words"] == " " and not s["art_rgba"].any()               # built blank: the mode writes them
        assert (s["x"] + w / 2.0, s["y"] + h / 2.0) == (cx, cy + dy)
    assert number["words_scale"] > word["words_scale"]
    assert names["total_text"] == names["total_node"] + "." + number["words_name"]
    BM.save(project, slug, BM.normalize({"name": "BON APPETIT", "screen": True, "scripts": []}))      # a panel: none
    assert names["total_node"] not in {s["name"] for s in MA._code_screens(project, [(slug, CM.load(project, slug))], prof)}


# ---- PAD-547: an info line under its name ("SUPER JACKPOT = 53,200,000") --------------------------------------------
def _jackpot(info=None, **kw):
    """A Bond owner's mini-wizard (PAD-547): each Right ramp grows the super jackpot by 1,000 while it runs, and its info
    line follows it."""
    return prog([{"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [{"op": "start_mode"}]},
                 {"hat": {"kind": "mode_start"}, "do": [{"op": "set", "var": "superjackpot", "value": num(5000)}]},
                 {"hat": {"kind": "shot", "shot": "Right ramp", "when": "running"},
                  "do": [{"op": "change", "var": "superjackpot", "by": num(1000)}]}],
                vars=[{"name": "superjackpot", "reset": "mode"}], seconds=6,
                info=info if info is not None else {"on": True, "text": "SUPER JACKPOT", "value": var("superjackpot")},
                **kw)


def test_the_info_line_is_off_unless_ticked_and_needs_words_or_a_value():
    assert BM.normalize({})["info"] == {"on": False, "text": "", "value": None}
    assert BM.normalize({"info": {"on": 1, "text": "  super jackpot ", "value": 3}})["info"] == {
        "on": True, "text": "super jackpot", "value": None}
    assert "INFO_NODE" not in BM.to_c(BM.starter("RAMP FRENZY", SHOTS), "ramp_frenzy")
    assert BM.problems(_jackpot(), SHOTS, GZ.events) == []
    assert any("info line has no words" in m for m in BM.problems(_jackpot({"on": True}), SHOTS, GZ.events))
    bad = BM.problems(_jackpot({"on": True, "text": "X", "value": var("nope")}), SHOTS, GZ.events)
    assert any(m.startswith("The info line uses a variable that is not there") for m in bad), bad
    src = BM.to_c(_jackpot(), "blk")
    assert '#define INFO_NODE    "PadMode_blk_Info"' in src
    assert '#define INFO_FORMAT  "SUPER JACKPOT = %s"' in src
    assert '#define INFO_FORMAT  "100%% = %s"' in BM.to_c(_jackpot({"on": True, "text": "100%", "value": num(1)}), "blk")
    assert '#define INFO_FORMAT  "SHOOT THE RAMP"' in BM.to_c(_jackpot({"on": True, "text": "SHOOT THE RAMP"}), "blk")
    used = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", src))
    assert used <= _header_calls(), used - _header_calls()


def test_the_info_line_follows_its_value_while_it_runs_then_goes(tmp_path):
    """The Bond owner (PAD-547): the game's own mini-wizards show SUPER JACKPOT = <value> under the bar, growing as shots
    are made. Hidden until the mode starts; shown at its start with the value; written again only when it changes;
    hidden at its end (time up) and at once at a drain."""
    out = play(tmp_path, _jackpot(), "secs", 1, "shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 0.5,
               "shot", "Right ramp", "secs", 1, "secs", 5)
    shows = [(int(t), int(on)) for t, on in re.findall(r"^\s*(\d+) SHOW PadMode_blk_Info (\d)$", out, re.M)]
    words = re.findall(r"^\s*(\d+) WORDS PadMode_blk_Info_Words: (.*)$", out, re.M)
    start = _at_any(out, r"START \(a block\)")
    end = _at_any(out, r"END \(time ran out\)")
    assert shows[0][1] == 0 and shows[0][0] < start                   # found and hidden before it ran
    assert [w for _t, w in words] == ["SUPER JACKPOT = 5,000", "SUPER JACKPOT = 6,000", "SUPER JACKPOT = 7,000"]
    assert abs(int(words[0][0]) - start) <= 40
    assert [on for t, on in shows if t >= start] == [1, 0] and abs(shows[-1][0] - end) <= 40
    out = play(tmp_path, _jackpot(), "secs", 1, "shot", "Left ramp", "secs", 1, "ball_end", "secs", 0.2)
    shows = re.findall(r"^\s*(\d+) SHOW PadMode_blk_Info (\d)$", out, re.M)
    assert shows[-1][1] == "0" and int(shows[-1][0]) - _at_any(out, r"END \(ball ended\)") <= 40


def test_the_info_line_reaches_the_assets_and_goes_where_the_port_says(tmp_path):
    from pinball_decryptor.plugins.stern import mode_assets as MA
    project = str(tmp_path)
    slug, _c = BM.new_blocks_mode(project, "DAF WIZARD")
    BM.save(project, slug, BM.normalize(dict(_jackpot(), name="DAF WIZARD")))
    spec = CM.load(project, slug)
    assert spec.info_line is True
    bond, gz = MP.profile("james_bond_le_1_06"), MP.profile("godzilla_le_1_16")
    assert bond.info_at == (679.0, 510.0) and gz.info_at == ()
    scr = MA._code_screens(project, [(slug, spec)], bond)[-1]
    names = MP.asset_names(slug)
    assert scr["name"] == names["info_node"] == "PadMode_%s_Info" % slug
    assert scr["words_name"] == "PadMode_%s_Info_Words" % slug and scr["words_rgba"] == (1.0, 1.0, 1.0, 1.0)
    w, h = MA.INFO_ART
    assert scr["art_rgba"].shape == (h, w, 4) and not scr["art_rgba"].any()     # clear: the words alone
    assert (scr["x"] + w / 2.0, scr["y"] + h / 2.0) == (679.0, 510.0)          # its middle on the port's place
    scr = MA._code_screens(project, [(slug, spec)], gz)[-1]
    assert (scr["x"] + w / 2.0, scr["y"] + h / 2.0) == MA.INFO_AT_DEFAULT      # a port that names none
    BM.save(project, slug, BM.normalize(dict(_jackpot({"on": False}), name="DAF WIZARD")))
    spec = CM.load(project, slug)
    assert spec.info_line is False
    assert not [s for s in MA._code_screens(project, [(slug, spec)], bond) if s["name"] == names["info_node"]]


# ---- PAD-600: one target qualified at a time - Set the hits of, Put out the light of ---------------------------------
TARGETS = ["Powerline left", "Powerline center", "Powerline right", "Big loop"]


def _say_hits(shot, most):
    """Blocks that write "hits N" in the log: a shot's hits as this mode sees them, 0 to ``most``."""
    return [{"op": "if", "cond": {"k": "cmp", "op": "=", "a": {"k": "hits", "shot": shot}, "b": num(k)},
             "then": [{"op": "log", "text": "hits %d" % k}], "else": None} for k in range(most + 1)]


def _target_mode(n):
    """The Beatles owner's (PAD-600): mode n lit at its target by 3 hits of it; the other targets' hits back to 0 and
    their modes' lights out, so only one is ready at a time (Batman's villains). In TARGET 2 the Building writes the
    hits of the first target as it sees them, so a test can read the count across modes."""
    me = TARGETS[n - 1]
    others = [t for t in TARGETS if t != me]
    then = [{"op": "light_mode", "shot": me, "insert": "", "color": "#00c040", "pattern": "pulse"}]
    then += [{"op": "set_hits", "shot": t, "value": num(0)} for t in others]
    then += [{"op": "unlight_mode", "mode": "t%d" % (TARGETS.index(t) + 1)} for t in others]
    scripts = [{"hat": {"kind": "shot", "shot": me, "when": "idle"}, "do": [
        {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": {"k": "hits", "shot": me}, "b": num(3)}, "then": then}]}]
    if n == 2:
        scripts.append({"hat": {"kind": "shot", "shot": "Building", "when": "any"}, "do": _say_hits(TARGETS[0], 4)})
    return prog(scripts, name="TARGET %d" % n, seconds=5)


def test_set_the_hits_and_put_out_the_light_are_checked():
    p = _target_mode(1)
    assert BM.problems(p, SHOTS, GZ.events, modes=["t1", "t2", "t3", "t4"]) == []
    assert BM.problems(p, SHOTS, GZ.events) == []                  # no project known: any slug is taken
    bad = prog([{"hat": {"kind": "mode_start"}, "do": [
        {"op": "set_hits", "shot": "Moon ramp", "value": num(0)}, {"op": "set_hits", "shot": "Building", "value": None},
        {"op": "unlight_mode", "mode": "Not A Slug"}, {"op": "unlight_mode", "mode": "gone"},
        {"op": "unlight_mode", "mode": ""}]}])
    assert BM.problems(bad, SHOTS, GZ.events, modes=["t1"]) == [
        "Script 1's Set the hits of names Moon ramp, a shot this card does not have.",
        "Script 1 has an empty number slot.",
        "Script 1 puts out the light of a mode that is not one.",
        "Script 1 puts out the light of a mode that is not in this project (gone): pick it again."]
    src = BM.to_c(p, "t1")
    used = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", src))
    assert used <= _header_calls(), used - _header_calls()
    assert '__attribute__((weak, visibility("hidden"))) long long pad_hits_powerline_center[5];' in src
    assert '__attribute__((weak, visibility("hidden"))) int pad_lit_t1[5];' in src           # its own light
    assert '__attribute__((weak, visibility("hidden"))) int pad_lit_t2[5];' in src           # another's
    assert "static const struct pm_mode t1_mode" in src or "PM_REGISTER(" in src
    assert "pad_hits_" not in re.search(r"static const struct pm_mode (\w+)", src).group(1)
    # this mode's own light put out with no Light the mode at block: nothing to put out
    own = prog([{"hat": {"kind": "mode_start"}, "do": [{"op": "unlight_mode", "mode": ""}]}])
    assert "static void unlight_mode(void) { }" in BM.to_c(own, "own")
    # a mode that never sets or reads hits makes the C it always made
    assert "pad_hits_" not in BM.to_c(_lit_prog(), "lit") and "hits_of" not in BM.to_c(_lit_prog(), "lit")


def test_only_one_target_is_qualified_at_a_time_across_modes(tmp_path):
    """Four modes built together as a card's are: the target that qualifies takes the others' hits back and puts
    their lights out; a target hit after that counts from 0 again, for its own mode too."""
    modes = {"t%d" % n: _target_mode(n) for n in (1, 2, 3, 4)}
    hit = lambda t, k=1: ["shot", t] * k + ["secs", 0.1]                 # noqa: E731
    out = play_many(tmp_path, modes,
                    *hit("Powerline left", 3), "lamps",                 # TARGET 1 lit
                    *hit("Powerline center", 2), *hit("Building"),      # hits of target 1 as TARGET 2 sees them: 3
                    *hit("Powerline center"), "lamps",                  # TARGET 2 lit, TARGET 1 out, its hits 0
                    *hit("Building"),                                   # ... as TARGET 2 sees them: 0
                    *hit("Powerline left"), *hit("Building"),           # 1: not lit again, not started
                    *hit("Powerline left", 2), "lamps",                 # 3: TARGET 1 lit again, TARGET 2 out
                    *hit("Powerline left"))                             # its lit shot starts it
    assert re.findall(r"\[TARGET 2\] (hits \d)", out) == ["hits 3", "hits 0", "hits 1"]
    held = re.findall(r"HELD (POWERLINE LEFT|POWERLINE CENTER|none)", out)
    assert held == ["POWERLINE LEFT", "POWERLINE CENTER", "POWERLINE LEFT"], held
    assert out.count("[TARGET 1] START (its lit shot)") == 1
    assert "[TARGET 2] START" not in out
    assert "[TARGET 2] put out the light of t1 for player 1" in out          # mode.log says who put it out
    assert "[TARGET 1] put out the light of t2 for player 1" in out
    assert "LAMP OFF POWERLINE LEFT TARGET 1" in out and "LAMP OFF POWERLINE CENTER TARGET 2" in out


def test_set_hits_counts_from_the_value_and_a_new_ball_clears_it(tmp_path):
    p = prog([{"hat": {"kind": "shot", "shot": "Left ramp", "when": "any"}, "do": [
                  {"op": "set_hits", "shot": "Right ramp", "value": num(5)}]},
              {"hat": {"kind": "shot", "shot": "Building", "when": "any"}, "do": _say_hits("Right ramp", 6) + [
                  {"op": "set_hits", "shot": "Right ramp", "value": num(-4)}]}])
    out = play(tmp_path, p, "shot", "Right ramp", "shot", "Left ramp", "shot", "Right ramp", "shot", "Building",
               "shot", "Building", "shot", "Left ramp", "ball_end", "shot", "Right ramp", "shot", "Building")
    # 5 set, one more hit: 6; then -4 reads as 0 (never below); a ball ending puts it back to its own count: 1
    assert re.findall(r"\[TEST MODE\] (hits \d)", out) == ["hits 6", "hits 0", "hits 1"]


def test_the_four_target_modes_build_into_one_object_with_one_count_and_one_light_each(tmp_path):
    if os.name == "nt":
        pytest.skip("build_mode.sh runs under bash with arm-linux-gnueabihf-gcc (WSL or Linux)")
    if not shutil.which("bash") or not shutil.which("arm-linux-gnueabihf-gcc"):
        pytest.skip("no arm-linux-gnueabihf-gcc here")
    srcs = []
    for n in (1, 2, 3, 4):
        srcs.append(tmp_path / ("t%d.c" % n))
        srcs[-1].write_text(BM.to_c(_target_mode(n), "t%d" % n), encoding="utf-8")
    out = tmp_path / "mode.so"
    r = subprocess.run(["bash", os.path.join(SDK, "build_mode.sh"), "-o", str(out)] + [str(s) for s in srcs]
                       + [os.path.join(SDK, "mode_file.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "warning" not in (r.stdout + r.stderr).lower()
    nm = shutil.which("arm-linux-gnueabihf-nm")
    if nm:
        syms = subprocess.run([nm, str(out)], capture_output=True, text=True).stdout
        for sym in ("pad_hits_powerline_left", "pad_hits_big_loop", "pad_lit_t1", "pad_lit_t4"):
            assert len(re.findall(r"\b%s$" % sym, syms, re.M)) == 1, sym     # one for all four modes


# ---- PAD-598: a Light block lights one of the game's own lights by name (an insert, a GI string, a flasher) --------
# An owner lit their mode at Target 4 with RINGO SPINNER pulsing, and wanted that insert to change as the mode started;
# the Light block could only pick a shot. It picks a shot's lights or one of the game's lights (the port's lamp lines).
def _lights_by_name_prog():
    return prog([{"hat": {"kind": "event", "event": "skill_shot", "when": "any"}, "do": [dict(LIT)]},
                 {"hat": {"kind": "mode_start"}, "do": [_light_insert("MASER READY"), _light_insert("HEAT RAY", "hurry")]},
                 {"hat": {"kind": "mode_end"}, "do": [{"op": "lights_off", "insert": "HEAT RAY"}]}])


def _light_insert(name, pattern="solid", color="#ff2000"):
    return {"op": "light_shot", "insert": name, "color": color, "pattern": pattern, "rate": None}


def test_a_light_block_names_one_of_the_games_lights_and_is_checked():
    lamps = ["MASER READY", "RIGHT RAMP", "LOWER PLAYFIELD GI 1"]
    p = prog([{"hat": {"kind": "mode_start"}, "do": [
        _light_insert("MASER READY"), _light_insert("LOWER PLAYFIELD GI 1", "blink"),
        {"op": "lights_off", "insert": "MASER READY"}, {"op": "lights_off", "shot": "*"}]}])
    assert BM.problems(p, SHOTS, GZ.events, inserts=lamps) == []
    assert BM.problems(p, SHOTS, GZ.events) == []                       # no list of the game's lights: not checked
    bad = prog([{"hat": {"kind": "mode_start"}, "do": [
        _light_insert("MOON"), {"op": "lights_off", "insert": "A,B"}, dict(_light_insert("MASER READY"), color="red")]}])
    assert BM.problems(bad, SHOTS, GZ.events, inserts=lamps) == [
        "Script 1 names the light MOON, which this card's game does not have.",
        "Script 1 lights an insert that is not one.",
        "Script 1 lights a shot in no color."]
    # a game with no lights a mode can hold: none can be named
    assert BM.problems(prog([{"hat": {"kind": "mode_start"}, "do": [_light_insert("MASER READY")]}]),
                       SHOTS, GZ.events, inserts=[]) == [
        "Script 1 names the light MASER READY, which this card's game does not have."]


def test_a_light_block_on_one_of_the_games_lights_holds_it_by_name_in_the_c():
    p = prog([{"hat": {"kind": "mode_start"}, "do": [
        _light_insert("MASER READY", "pulse"), {"op": "light_shot", "shot": "Building", "color": "#00ff00",
                                                "pattern": "solid"},
        _light_insert("HEAT RAY", "blink"), {"op": "lights_off", "insert": "MASER READY"}]}])
    src = BM.to_c(p, "blk")
    used = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", src))
    assert used <= _header_calls(), used - _header_calls()
    assert 'LAMP_NAMES[2] = {"MASER READY", "HEAT RAY"};' in src and "#define N_LIGHTS  (N_SHOTS + 2)" in src
    assert "light(N_SHOTS + 0, 0xff2000u, PM_LAMP_PULSE, 1600LL, 0);" in src
    assert "light(0, 0x00ff00u, PM_LAMP_SOLID, 0LL, 0);" in src             # the shot keeps its own slot
    assert "unlight(N_SHOTS + 0);" in src
    plain = BM.to_c(BM.starter("RAMP FRENZY", SHOTS), "ramp_frenzy")
    assert "#define N_LIGHTS  (N_SHOTS + 0)" in plain and "LAMP_NAMES[1] = {0};" in plain


def test_a_light_block_lights_one_off_held_dark(tmp_path):
    """PAD-601: a Light block may light an insert "off": held dark, its color and pace ignored (Hand back lets the
    game's own light show through instead)."""
    off = dict(_light_insert("RINGO SPINNER", "off"), color="", rate={"k": "num", "v": 5})
    p = prog([{"hat": {"kind": "mode_end"}, "do": [off, {"op": "light_shot", "shot": "Building", "pattern": "off"}]}])
    assert BM.problems(p, SHOTS, GZ.events, inserts=["RINGO SPINNER"]) == []
    src = BM.to_c(p, "blk")
    assert "light(N_SHOTS + 0, 0x000000u, PM_LAMP_SOLID, 0LL, 0);" in src
    assert len(re.findall(r"light\([^;]*, 0x000000u, PM_LAMP_SOLID, 0LL, 0\);", src)) == 2   # the shot's too
    assert BM.normalize(p)["scripts"][0]["do"][0]["pattern"] == "off"


def test_the_insert_a_mode_is_lit_with_changes_as_it_starts_on_the_harness(tmp_path):
    """The owner's case: lit at the Right ramp with MASER READY pulsing; When the mode starts lights MASER READY solid
    red. Starting puts the lit light out, and MASER READY stays the mode's, red, until it ends: then the game has it."""
    lit = dict(LIT, pattern="pulse", color="#40c040")
    p = prog([{"hat": {"kind": "event", "event": "skill_shot", "when": "any"}, "do": [lit]},
              {"hat": {"kind": "mode_start"}, "do": [_light_insert("MASER READY")]},
              {"hat": {"kind": "shot", "shot": "Building", "when": "running"},
               "do": [{"op": "lights_off", "insert": "MASER READY"}]}], seconds=5)
    out = play(tmp_path, p, "event", "skill_shot", "secs", 0.2, "lamps",       # lit: pulsing green
               "shot", "Right ramp", "secs", 0.5, "lamps",                     # started: red, solid, and held
               "secs", 1, "lamps",
               "shot", "Building", "secs", 0.2, "lamps",                       # handed back by name
               "secs", 6)
    held = re.findall(r"HELD (RIGHT RAMP|MASER READY|none)(?: (\w+) (\w+))?", out)
    assert held[:2] == [("RIGHT RAMP", "40c040", "pulse"), ("MASER READY", "40c040", "pulse")]
    assert held[2:] == [("MASER READY", "ff2000", "solid"), ("MASER READY", "ff2000", "solid"), ("none", "", "")]
    assert "START (its lit shot): player 1" in out
    assert "LAMP MASER READY ff2000 solid 0 TEST MODE" in out and "LAMP OFF MASER READY TEST MODE" in out
    assert "lamps held 0" in out


def test_a_light_held_by_name_comes_back_after_a_light_show_and_goes_at_the_end_on_the_harness(tmp_path, monkeypatch):
    _cc()
    monkeypatch.setenv("HARNESS_PLACES", "1")
    p = prog([{"hat": {"kind": "event", "event": "skill_shot", "when": "idle"}, "do": [{"op": "start_mode"}]},
              {"hat": {"kind": "mode_start"}, "do": [_light_insert("HEAT RAY", "blink"), {"op": "show", "show": "burst"}]}],
             seconds=5)
    out = play(tmp_path, p, "event", "skill_shot", "secs", 6)
    sent = re.findall(r"^\s*\d+ LAMP HEAT RAY ff2000 blink (\d+)", out, re.M)
    assert len(sent) == 2 and sent[0] == sent[1]                        # lit, then again once the show is over
    assert "END lamps held 0" in out


def rage_meter():
    """PAD-658: GODZILLA ANGRY's RAGE meter in blocks (David: "we somehow lost our godzilla rage meter in the top right
    of the HUD. it should always be shown (whenever the HUD is shown)"): a corner bar that follows a percent, shown
    while the mode is not running too."""
    return prog([
        {"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [
            {"op": "change", "var": "rage", "by": num(25)}]},
        {"hat": {"kind": "shot", "shot": "Building", "when": "idle"}, "do": [{"op": "start_mode"}]},
    ], vars=[{"name": "rage", "reset": "game"}], seconds=5,
        hud={"on": True, "line": "SHOOT THE BUILDING", "counters": [{"label": "RAGE", "value": var("rage")}],
             "timer": {"on": False},
             "gauge": {"on": True, "kind": "bar", "count": 20, "words": ["GODZILLA", "RAGE"], "full": "ANGRY!",
                       "meter": True, "value": var("rage")}})


def test_a_corner_meter_shows_before_its_mode_starts_and_hides_while_another_mode_runs(tmp_path):
    p = rage_meter()
    assert BM.problems(p, SHOTS) == []
    assert BM.hud_spec(p, "rage")["gauge"] == {"label": " ", "kind": "bar", "count": 20, "icon": "rage",
                                               "words": ["GODZILLA", "RAGE"]}
    src = BM.to_c(p, "rage")
    assert '.slug = "rage", .beside = 1' in src and "#define HUD_METER  1" in src
    other = maser_hud()
    out = play_many(tmp_path, {"rage": p, "maser": other},
                    "secs", 1, "shot", "Left ramp", "secs", 1, "shot", "Left ramp", "secs", 1,
                    "shot", "Maser target", "secs", 2,                         # the other mode runs: its HUD up
                    "shot", "Left ramp", "secs", 1, "shot", "Left ramp", "secs", 22,   # nothing counts; it times out
                    "shot", "Left ramp", "secs", 1, "shot", "Left ramp", "secs", 1,
                    "shot", "Building", "secs", 7)                             # the rage mode itself
    # in a game, before anything: the bar at 0%, then 25%, 50%
    assert _hud_words(out, "Gauge_Label")[:3] == ["0%", "25%", "50%"]
    gauge = re.compile(r"SHOW \S*PadMode_rage_Hud_Gauge (\d)")
    assert "SHOW PadMode_rage_Hud 1" in out and gauge.findall(out)[0] == "1"
    during = out[out.index(">> shot Maser target"):out.index("] END (time ran out)")]
    after = out[out.index("] END (time ran out)"):out.index(">> shot Building")]
    # PAD-675: the other mode runs alone - the bar is taken down and counts nothing; after it, it fills on to ANGRY!
    assert "SHOW PadMode_maser_Hud 1" in during and "SHOW PadMode_rage_Hud 0" in during
    assert "75%" not in _hud_words(during, "Gauge_Label")
    assert "75%" in _hud_words(after, "Gauge_Label") and "ANGRY!" in _hud_words(after, "Gauge_Label")
    # its own mode: the bar stays up and full until its end
    mine = out[out.index(">> shot Building"):]
    assert "0" not in gauge.findall(mine[:mine.index("] END")])
