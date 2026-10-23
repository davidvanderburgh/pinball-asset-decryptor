"""PAD-611: the visual alternatives to the blocks are views of the SAME program - nothing is lost going to them.

tools/mode_views: mode_script (a blocks.json as typed text and back), describe (every block in words) and
render_views (the seven mockup views). Every block, hat and value the blocks have is turned out and back exactly, and
a block added to block_modes later fails here until the views know it.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools", "mode_views"))

import describe as D  # noqa: E402
import mode_script as MS  # noqa: E402
import render_views as RV  # noqa: E402
import showcase  # noqa: E402
from pinball_decryptor.plugins.stern import block_modes as BM  # noqa: E402


def num(v):
    return {"k": "num", "v": v}


#: one of every block there is (fields as the page's templates make them, modes_blocks.js stmtTemplates)
EVERY_BLOCK = [
    {"op": "start_mode"}, {"op": "end_mode"},
    {"op": "light_mode", "shot": "Right ramp", "insert": "MR. HENDERSON", "color": "#ffd000", "pattern": "blink"},
    {"op": "unlight_mode", "mode": ""}, {"op": "add_time", "seconds": num(5)}, {"op": "set_time", "seconds": num(10)},
    {"op": "multiball", "balls": 2, "save": 10}, {"op": "ball_save", "seconds": 15}, {"op": "game_wizard", "name": "Spectre", "how": "light"},
    {"op": "hold", "what": "magnet", "ms": num(2000)}, {"op": "scoop_hold", "ms": num(3000), "which": "next"},
    {"op": "let_go", "what": "*"}, {"op": "shield", "where": "toward"}, {"op": "building", "floor": "3"},
    {"op": "shake", "ms": num(500), "strength": "hard"}, {"op": "shake_game", "shake": "jackpot"},
    {"op": "score", "points": num(1000000)}, {"op": "set", "var": "combo", "value": num(0)},
    {"op": "change", "var": "combo", "by": num(1)}, {"op": "set_hits", "shot": "Left ramp", "value": num(0)},
    {"op": "timer_start", "timer": "window", "ms": num(5000)}, {"op": "timer_stop", "timer": "window"},
    {"op": "if", "cond": {"k": "running"}, "then": [{"op": "start_mode"}], "else": None},
    {"op": "if", "cond": None, "then": [], "else": []},
    {"op": "callout", "role": "ten_seconds"}, {"op": "words", "text": "JACKPOT", "value": None},
    {"op": "light_shot", "shot": "Left ramp", "color": "#ffd000", "pattern": "blink", "rate": num(200)},
    {"op": "lights_off", "shot": "*"}, {"op": "show", "show": "burst"}, {"op": "game_show", "name": "flashy"},
    {"op": "show", "show": "mine", "name": "Kaiju roar"},                                           # PAD-646
    {"op": "log", "text": ""}, {"op": "clip", "clip": "sever", "where": "full"},
    {"op": "sound", "sound": "roar", "fallback": None}, {"op": "music", "bed": "swamp"},   # PAD-658: a music bed
    {"op": "hud_text", "which": "line", "text": "SHOOT THE LIT SHOT", "value": None},
    {"op": "hud_counter", "counter": 1, "value": num(0), "sub": None}, {"op": "hud_gauge", "value": num(1)},
    {"op": "hud_progress", "value": num(7)},
    {"op": "hud_award", "text": "JACKPOT", "value": None, "sub": "", "seconds": 2},
]
#: one of every value and condition (modes_blocks.js valueTemplates / condTemplates), with the operators
EVERY_VALUE = [num(1000), {"k": "var", "name": "combo"}, {"k": "hits", "shot": "Left ramp"}, {"k": "scored"},
               {"k": "total"}, {"k": "secs_left"}, {"k": "timer_left", "timer": "window"}, {"k": "balls"},
               {"k": "player"}] + [{"k": "op", "op": o, "a": num(2), "b": {"k": "var", "name": "combo"}} for o in "+-*/"]
EVERY_COND = [{"k": "cmp", "op": o, "a": {"k": "secs_left"}, "b": num(3)} for o in BM.CMPS] + [
    {"k": "and", "a": {"k": "running"}, "b": {"k": "lit"}}, {"k": "or", "a": {"k": "stock"}, "b": {"k": "can_start"}},
    {"k": "not", "a": {"k": "running"}}, {"k": "running"}, {"k": "can_start"}, {"k": "lit"}, {"k": "stock"},
    {"k": "shields_away"}]
EVERY_HAT = [{"kind": "mode_start"}, {"kind": "mode_end"}, {"kind": "shot", "shot": "Left ramp", "when": "running"},
             {"kind": "any_shot", "when": "idle"},
             {"kind": "switch", "when": "idle"}, {"kind": "every", "seconds": 5}, {"kind": "seconds_left", "seconds": 10},
             {"kind": "ball_end"}, {"kind": "drain", "when": "running"},
             {"kind": "event", "event": "ball_saved", "when": "any"},
             {"kind": "timer_done", "timer": "window"},
             {"kind": "challenge", "challenge": "Ahoy Mr. Bond"}]                                  # PAD-615


def every_program():
    scripts = [{"hat": h, "do": list(EVERY_BLOCK) if i == 0 else [{"op": "log", "text": "x"}]}
               for i, h in enumerate(EVERY_HAT)]
    scripts.append({"hat": {"kind": "mode_start"}, "do": [{"op": "score", "points": v} for v in EVERY_VALUE]
                    + [{"op": "if", "cond": c, "then": [{"op": "end_mode"}], "else": None} for c in EVERY_COND]})
    return BM.normalize({"name": "EVERY BLOCK", "vars": [{"name": "combo", "reset": "mode"}],
                         "timers": [{"name": "window"}], "scripts": scripts})


def test_every_block_hat_and_value_is_covered():
    ops = {b["op"] for b in EVERY_BLOCK}
    assert ops == set(BM.STATEMENTS), "a block the views do not know: %s" % (set(BM.STATEMENTS) ^ ops)
    assert {h["kind"] for h in EVERY_HAT} == set(BM.HATS)
    assert [D.hat(h) for h in EVERY_HAT if D.hat(h).startswith("(")] == []     # every hat has words (PAD-615)
    assert {v["k"] for v in EVERY_VALUE} == set(BM.NUM_KINDS)
    assert {c["k"] for c in EVERY_COND} == set(BM.BOOL_KINDS)
    assert set(D.SAY) | {"if"} == set(BM.STATEMENTS)
    assert set(D.FAMILY) == set(BM.STATEMENTS)


@pytest.mark.parametrize("make", [showcase.program, every_program,
                                  lambda: BM.starter("NEW", [n for n, _m in BM.MP.GODZILLA_PRO_1_15.shots])])
def test_script_round_trip_is_exact(make):
    prog = make()
    assert MS.from_script(MS.to_script(prog)) == prog
    short = MS.to_script(prog, defaults=BM.normalize({}))
    assert BM.normalize(MS.from_script(short)) == prog
    assert len(short) < len(MS.to_script(prog))


def test_showcase_is_a_whole_mode():
    prog = showcase.program()
    assert BM.problems(prog, shots=list(showcase.SHOTS)) == []
    assert "static void on_shot(" in BM.to_c(prog, "ramp_frenzy")


def test_script_reads_like_code():
    text = MS.to_script(showcase.program(), defaults=BM.normalize({}))
    assert 'with on.shot(shot="Left ramp", when="idle"):\n    if hits(shot="Left ramp") >= 3:\n        start_mode()' in text
    assert "    score(points=500000 * combo)\n" in text
    assert "    else:\n        show(show=\"fizzle\")\n" in text


@pytest.mark.parametrize("block", [
    {"op": "add_time", "seconds": num(-5)},                     # a negative number
    {"op": "score", "points": 7},                               # a plain number where a value goes
    {"op": "multiball", "balls": num(2), "save": 10},           # a value where a plain number goes
    {"op": "if", "cond": {"k": "lit"}, "then": [], "else": []},  # an empty else, kept apart from none
    {"op": "if", "cond": {"k": "lit"}, "then": []},             # an If saved with no else at all
    {"op": "if", "cond": {"k": "lit"}, "then": [], "else": None, "note": 1},   # a key the page does not know
    {"op": "set", "var": "big combo", "value": {"k": "var", "name": "big combo"}},   # a variable with a space
    {"op": "set", "var": "lit", "value": {"k": "var", "name": "lit"}},             # one named like a condition
    {"op": "score", "points": {"k": "op", "op": "%", "a": num(1), "b": num(2)}},   # an operator there is not
    {"op": "score", "points": {"k": "hits", "shot": {"k": "num", "v": 1}}},        # a value in an odd place
    {"op": "log", "text": "quotes \" and \\ and é"},
    {"op": "if", "cond": {"k": "cmp", "op": "=", "a": {"k": "op", "op": "+", "a": num(1), "b": num(2)},
                          "b": {"k": "op", "op": "*", "a": num(3), "b": num(1)}},
     "then": [{"op": "if", "cond": {"k": "not", "a": {"k": "and", "a": {"k": "lit"}, "b": {"k": "running"}}},
               "then": [{"op": "end_mode"}], "else": [{"op": "start_mode"}]}], "else": None},
    {"op": "class", "x": 1},                                    # an op that is a Python word
    "not a block",
])
def test_odd_blocks_round_trip(block):
    prog = {"name": "ODD", "scripts": [{"hat": {"kind": "mode_start"}, "do": [block]}]}
    assert MS.from_script(MS.to_script(prog)) == prog


def test_odd_scripts_round_trip():
    prog = {"name": "ODD", "scripts": [
        {"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle", "extra": [1, 2]}, "do": []},
        {"hat": {"kind": "every", "seconds": 5}, "do": [], "note": "kept"},
        {"hat": {"kind": "shot", "shot": {"k": "num", "v": 1}}, "do": []},
        {"hat": {"kind": "for"}, "do": []}],
        "weird key": True}
    assert MS.from_script(MS.to_script(prog)) == prog


@pytest.mark.parametrize("text, where", [
    ("with on.shot(shot=\"Left ramp\"):\n    score(points=)\n", "line 2"),
    ("name = \"X\"\nprint(1)\n", "line 2"),
    ("with on.mode_start():\n    score(points=open('x'))\n", "line 2"),
    ("with on.mode_start():\n    x = 3\n", "line 2"),
])
def test_bad_script_says_where(text, where):
    with pytest.raises(MS.ScriptError, match=where):
        MS.from_script(text)


@pytest.mark.parametrize("view", RV.VIEWS)
@pytest.mark.parametrize("make", [showcase.program, every_program])
def test_every_view_draws_the_mode(view, make):
    prog = make()
    page = RV.RENDER[view](prog)
    assert prog["name"] in page and "<html>" in page
    if view in ("story", "cards", "graph", "playfield"):
        # every rule shows somewhere, by its words
        for b, _p in (x for s in prog["scripts"] for x in RV.walk(s["do"])):
            if view != "graph":
                assert RV.E(D.say(b)) in page, (view, b)
