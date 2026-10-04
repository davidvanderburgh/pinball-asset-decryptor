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
                        "-o", str(exe), os.path.join(SDK, "examples", "desk_harness.c"), str(src)],
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


def _at(out, pattern):
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
    broke = _at(out, r"\[MASER BARRAGE\] CHAIN BROKEN")
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
    assert _at(out, "DISPLAY lingers TEST MODE 3000 ms") == _at(out, r"END \(time ran out\)")
    assert _at(out, "DISPLAY 0 TEST MODE") == _at(out, r"END \(ball ended\)") == _at(out, ">> ball_end")
    assert "DISPLAY" not in play(tmp_path, dict(p, priority=0), "shot", "Left ramp", "secs", 6)
