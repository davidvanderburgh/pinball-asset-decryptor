"""PAD-614: a blocks mode's Rule cards, Story, Script, Shot table, Timeline and Node graph tabs, and the Playfield as
their shot picker (PAD-611's plan, steps 3-6).

* The Script tab's two calls: modes.blocks_script writes the page's program as text, modes.blocks_read_script reads
  typed text back to the program (normalized as blocks.json is), or says what is wrong and on which line; a misspelt
  block or trigger is an error on its line, not a block the mode cannot run.
* A mode written in C is read and saved by the editor on its Code page (modes.code_text / code_save).
* Each view round-trips the mode (David, 2026-10-18: switching tabs never converts anything): one of every block,
  hat, value and condition there is, edited through each view's own way of editing, comes back unchanged, with one
  history (Node, the page's core stubbed, as test_pad612 does).
* modes_views.js reads off the program what each view places where: a block in words (every one), the Story's
  boxes and arrows, the Shot table's cells, the Timeline's moments and rows, the Node graph's shared things.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import mode_script as MS
from tests.test_pad612_mode_views import _UI, _stage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")

sys.path.insert(0, os.path.join(ROOT, "tools", "mode_views"))
try:
    import showcase  # noqa: E402
finally:
    sys.path.pop(0)
from tests.test_pad611_mode_script import EVERY_BLOCK, every_program  # noqa: E402


# ------------------------------------------------------------ the Script's reader, in the app
def test_the_script_reader_moved_into_the_app_and_the_old_name_still_works():
    sys.path.insert(0, os.path.join(ROOT, "tools", "mode_views"))
    try:
        import mode_script as old
    finally:
        sys.path.pop(0)
    assert old is MS and old.to_script is MS.to_script


def test_a_misspelt_block_or_trigger_is_an_error_on_its_line():
    text = 'name = "X"\n\nwith on.mode_start():\n    score(points=5)\n    scor(points=5)\n'
    with pytest.raises(MS.ScriptError) as e:
        MS.from_script(text)
    assert e.value.line == 5 and "no block called scor()" in str(e.value)
    with pytest.raises(MS.ScriptError) as e:
        MS.from_script('with on.mode_strat():\n    pass\n')
    assert e.value.line == 1 and "on.mode_strat" in str(e.value)
    with pytest.raises(MS.ScriptError) as e:
        MS.from_script('with on.mode_start():\n    score(points=5\n')
    assert e.value.line == 2
    with pytest.raises(MS.ScriptError) as e:
        MS.from_script('with on.mode_start():\n    score(**x)\n')
    assert e.value.line == 2


def test_a_block_the_plain_form_does_not_name_is_kept_exactly():
    # an op or hat the app does not have (an older or a hand-edited blocks.json): written as block() / script(), so
    # it reads back exactly, and problems() names it as it always did
    prog = BM.normalize({"scripts": [{"hat": {"kind": "mode_start"}, "do": [{"op": "laser", "power": 3}]},
                                     {"hat": {"kind": "moon_rise"}, "do": []}]})
    text = MS.to_script(prog, defaults=BM.normalize({}))
    assert 'block({"op": "laser", "power": 3})' in text and "script({" in text
    assert BM.normalize(MS.from_script(text)) == prog


# ------------------------------------------------------------ the tab's calls
def test_blocks_script_and_read_script(tmp_path, monkeypatch):
    from tests.test_webui_modes import _project
    from tests.webui_harness import web_app
    from pinball_decryptor.core import preview
    monkeypatch.setattr(preview, "enabled", lambda feature: True)
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, tmp_path / "proj")
        for prog in (showcase.program(), every_program()):
            text = w.call("modes.blocks_script", prog)["text"]
            assert "format = " not in text                      # the settings at their defaults are left out
            assert w.call("modes.blocks_read_script", text) == {"program": prog}
        text = w.call("modes.blocks_script", showcase.program())["text"]
        bad = text.replace("score(points=5000000)", "score(points=5000000", 1)
        line = text[:text.index("score(points=5000000)")].count("\n") + 1
        got = w.call("modes.blocks_read_script", bad)
        assert got["line"] == line and "never closed" in got["error"] and "program" not in got
        got = w.call("modes.blocks_read_script", text.replace("start_mode()", "start_the_mode()", 1))
        assert "start_the_mode()" in got["error"] and got["line"] == text[:text.index("start_mode()")].count("\n") + 1
        assert w.call("modes.blocks_read_script", "")["program"] == BM.normalize({})
        assert "error" in w.call("modes.blocks_read_script", "x = [" * 200 + "]" * 200)


def test_a_c_mode_is_read_and_saved_by_its_editor(tmp_path, monkeypatch):
    from tests.test_webui_modes import _project, _svc
    from tests.webui_harness import web_app
    from pinball_decryptor.core import preview
    monkeypatch.setattr(preview, "enabled", lambda feature: True)
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, tmp_path / "proj")
        assert w.call("modes.code_text")["error"] == "No mode written in C is open."
        _svc(w)._opener = lambda path: None
        path = w.call("modes.new_code_mode", "Laser Show")
        got = w.call("modes.code_text")
        assert got["error"] == "" and got["text"] == open(path, encoding="utf-8").read() and "pad_mode" in got["text"]
        new = got["text"] + "\n/* PAD-614: edited in the app */\n"
        assert w.call("modes.code_save", new) == {"ok": True, "error": ""}
        assert open(path, encoding="utf-8", newline="").read() == new
        assert not os.path.exists(path + ".saving")
        assert w.call("modes.code_text")["text"] == new
        assert w.state("modes")["code"]["slug"] == "laser_show"


# ------------------------------------------------------------ the views (Node)
_VIEWS = r"""
const V = await import("./tabs/modes_views.js");
const B = await import("./tabs/modes_blocks.js");
const S = await import("./tabs/modes_script.js");
const [prog, blocks, shots] = JSON.parse(process.argv[2]);
const ch = { events: [{ name: "ball_saved", label: "the ball is saved" }], callouts: [{ role: "ten_seconds", label: "Ten seconds left" }] };
console.log(JSON.stringify({
  words: blocks.map((b) => V.stmtWords(b, ch)),
  family: V.FAMILY, stmtClass: B.STMT_CLASS,
  story: V.storyOf(prog), arrows: V.storyArrows(prog, ch),
  grid: V.shotGrid(prog, shots, ch),
  timeline: V.timelineOf(prog, ch),
  shared: V.sharedUses(prog),
  lines: V.ruleLines(prog.scripts[0].do, ch).slice(0, 3),
  py: S.colorLine('    score(points=500000 * combo)  # x', "py"),
  c: [0, 1, 2].map(((st) => (i) => S.colorLine(['int a = 0x1F; /* one', 'two */ return f("s");', '#include <x.h>'][i], "c", st))({})),
  hat: S.hatText({ kind: "shot", shot: "Left ramp", when: "idle" }),
  stmt: S.stmtText({ op: "score", points: { k: "num", v: 1000 } }),
}));
"""


def _node(tmp_path, script, *args):
    stubs = _stage(tmp_path, ("modes_blocks.js", "modes_playfield.js", "modes_views.js", "modes_rules.js",
                              "modes_script.js"))
    names = set().union(*stubs.values()) - {"useState", "useRef", "useEffect", "call", "html"}
    (tmp_path / "core" / "ui.js").write_text(_UI + "".join("export const %s = () => null;\n" % n for n in sorted(names)),
                                              encoding="utf-8")
    (tmp_path / "tabs" / "modes_dialogs.js").write_text("export const PlayButton = () => null;\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "run.js").write_text(script, encoding="utf-8")
    run = subprocess.run([NODE, str(tmp_path / "run.js")] + [json.dumps(a) for a in args], capture_output=True,
                         text=True, encoding="utf-8", timeout=60, cwd=str(tmp_path))
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@pytest.mark.skipif(NODE is None, reason="needs Node.js")
def test_the_views_read_the_program(tmp_path):
    prog = showcase.program()
    shots = list(showcase.SHOTS)
    got = _node(tmp_path, _VIEWS, [prog, EVERY_BLOCK, shots])
    # every block has words of its own (none falls through to "(op)"), and the families match the Blocks tab's
    assert [w for w in got["words"] if w.startswith("(")] == []
    assert got["words"][EVERY_BLOCK.index({"op": "callout", "role": "ten_seconds"})] == "Say “Ten seconds left”"
    assert got["family"] == got["stmtClass"] and set(got["family"]) == set(BM.STATEMENTS)
    # the Story: RAMP FRENZY waits for its Left ramps, runs its shots and clock, ends on the clock or the drain
    hats = [s["hat"] for s in prog["scripts"]]
    st = got["story"]
    assert [hats[i] for i in st["waiting"]] == [{"kind": "shot", "shot": "Left ramp", "when": "idle"}]
    assert {hats[i]["kind"] for i in st["running"]} == {"any_shot", "shot", "timer_done", "seconds_left"}
    assert [hats[i]["kind"] for i in st["start"]] == ["mode_start"] and [hats[i]["kind"] for i in st["end"]] == ["mode_end"]
    assert [hats[i]["kind"] for i in st["drain"]] == ["ball_end"] and st["any"] == []
    assert got["arrows"]["ins"] == [{"si": 0, "words": "When Left ramp is made, while it is not running, if hits of Left ramp ≥ 3"}]
    assert [o["words"] for o in got["arrows"]["outs"]] == ["The clock runs out (30 seconds)", "The ball drains"]
    # the Shot table: a row per shot (and Any shot), the Left ramp's rule while it waits, nothing on the Building
    rows = {r["key"]: r for r in got["grid"]["rows"]}
    assert [r["key"] for r in got["grid"]["rows"]][:len(shots)] == shots and "*any" in rows
    assert [hats[i]["shot"] for i in rows["Left ramp"]["cells"]["idle"]] == ["Left ramp"]
    assert rows["*any"]["cells"]["running"] and not rows["Building"]["used"]
    assert {hats[i]["kind"] for i in got["grid"]["others"]} == {"mode_start", "mode_end", "timer_done", "seconds_left", "ball_end"}
    # the Timeline: start at 0, 10 s left at 20, end at 30; no two clips of a lane on one another
    tl = got["timeline"]
    assert tl["seconds"] == 30 and sorted((m["t"], m["label"]) for m in tl["moments"]) == [
        (0, "It starts"), (20, "10 s left"), (30, "It ends")]
    lanes = {}
    for x in tl["clips"]:
        lanes.setdefault((x["lane"], x["row"]), []).append(x)
    assert all(len({x["t"] for x in same}) == len(same) for same in lanes.values())
    assert {"lights", "shows", "sound", "score"} <= {x["lane"] for x in tl["clips"]}
    assert any(x["cond"] and x["end"] for x in tl["clips"])                      # the rainbow / fizzle If
    # the Node graph: combo is set at the start and read by the any-shot rule; the window timer sets one off
    shared = {t["key"]: t for t in got["shared"]}
    assert {"var:combo", "var:jackpots", "timer:window", "hits:Left ramp"} <= set(shared)
    assert {u["how"] for u in shared["var:combo"]["uses"]} == {"sets", "reads"}
    assert "starts" in {u["how"] for u in shared["timer:window"]["uses"]}
    assert got["lines"][0] == {"depth": 0, "fam": "flow", "words": "If hits of Left ramp ≥ 3"}
    # the editor's colors and the Script's templates
    assert [(p["t"], p["c"]) for p in got["py"] if p["c"]] == [("score", "fn"), ("points", "ar"), ("500000", "nu"), ("# x", "cm")]
    c0, c1, c2 = got["c"]
    assert ("int", "kw") in [(p["t"], p["c"]) for p in c0] and c0[-1] == {"t": "/* one", "c": "cm"}
    assert c1[0] == {"t": "two */", "c": "cm"} and ('"s"', "st") in [(p["t"], p["c"]) for p in c1]
    assert c2 == [{"t": "#include <x.h>", "c": "pp"}]
    assert got["hat"] == 'with on.shot(shot="Left ramp", when="idle"):'
    assert got["stmt"] == ["score(points=1000)"]
    assert MS.from_script(got["hat"] + "\n    " + got["stmt"][0] + "\n")["scripts"][0]["do"] == [
        {"op": "score", "points": {"k": "num", "v": 1000}}]


_ROUND = r"""
const ui = await import("./core/ui.js");
const B = await import("./tabs/modes_blocks.js");
const V = await import("./tabs/modes_views.js");
const S = await import("./tabs/modes_script.js");
await import("./tabs/modes_rules.js");
const [prog, readBack, shots] = JSON.parse(process.argv[2]);
const c = { slug: "every", blocks: { program: prog, choices: { shots } } };
const pg = B.useModeProgram(c);
const ed = B.useEd(pg, c.blocks.choices);
const wait = () => new Promise((r) => setTimeout(r, 650));
const last = () => (ui.saved.length ? ui.saved.at(-1)[2] : null);
const out = {};
// Rule cards / Blocks: every block's every field set to what it holds is no edit at all
prog.scripts.forEach((sc, si) => {
  ed.set(["scripts", si, "hat"], JSON.parse(JSON.stringify(sc.hat)));
  sc.do.forEach((b, i) => Object.keys(b).forEach((k) => ed.set(["scripts", si, "do", i, k], JSON.parse(JSON.stringify(b[k])))));
});
await wait();
out.cardsNoop = ui.saved.length;
// Story: every rule a shot or an event sets off dragged to each box, then back where it was
const movable = prog.scripts.map((sc, si) => [sc, si]).filter(([sc]) => V.MOVABLE.has(sc.hat.kind));
movable.forEach(([sc, si]) => ["waiting", "running", "any"].forEach((box) => ed.set(["scripts", si, "hat", "when"], V.BOX_WHEN[box])));
movable.forEach(([sc, si]) => ed.set(["scripts", si, "hat", "when"], sc.hat.when));
await wait();
out.story = last();
// Shot table: a rule added in a cell, then the mode's Undo
const row = V.shotGrid(prog, shots).rows[0];
ed.addScript(V.cellHat(row, "idle"));
await wait();
out.tableAdded = last().scripts.at(-1);
pg.undo();
await wait();
out.tableUndone = last();
// Script: the text read back is the same program, so nothing changes; a typed change is one step, undone
out.scriptSame = S.applyProgram(pg, readBack, out.tableUndone);
const typed = JSON.parse(JSON.stringify(readBack));
typed.scripts[0].do[0] = { op: "score", points: { k: "num", v: 7 } };
out.scriptTyped = S.applyProgram(pg, typed, readBack);
await wait();
out.afterTyping = last().scripts[0].do[0];
pg.undo();
await wait();
out.final = last();
out.saves = ui.saved.length;
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="needs Node.js")
@pytest.mark.parametrize("make", [showcase.program, every_program])
def test_every_view_round_trips_the_mode(tmp_path, make):
    prog = make()
    read_back = BM.normalize(MS.from_script(MS.to_script(prog, defaults=BM.normalize({}))))
    assert read_back == prog
    shots = list(showcase.SHOTS)
    got = _node(tmp_path, _ROUND, [prog, read_back, shots])
    assert got["cardsNoop"] == 0                                    # nothing saved: no field changed
    assert got["story"] == prog
    assert got["tableAdded"] == {"hat": {"kind": "shot", "shot": shots[0], "when": "idle"}, "do": []}
    assert got["tableUndone"] == prog
    assert got["scriptSame"] is False and got["scriptTyped"] is True
    assert got["afterTyping"] == {"op": "score", "points": {"k": "num", "v": 7}}
    assert got["final"] == prog


_EXPORTS = r"""
const P = await import("./tabs/modes_playfield.js");
const B = await import("./tabs/modes_blocks.js");
const R = await import("./tabs/modes_rules.js");
const S = await import("./tabs/modes_script.js");
console.log(JSON.stringify({ rules: Object.keys(R).sort(), script: Object.keys(S).sort(),
  picker: B.pickers.shot === P.PickOnField }));
"""


@pytest.mark.skipif(NODE is None, reason="needs Node.js")
def test_the_views_and_the_shot_picker_are_wired(tmp_path):
    got = _node(tmp_path, _EXPORTS)
    assert got["rules"] == ["NodeGraphView", "RuleCardsView", "ShotTableView", "StoryView", "TimelineView"]
    assert {"ScriptView", "CodeView", "CodeEditor", "CEditor", "applyProgram"} <= set(got["script"])
    assert got["picker"] is True                       # every view's shot lists get the playfield beside them
    src = open(os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs", "modes.js"), encoding="utf-8").read()
    pages = src[src.index("const BLOCKS_PAGES"):src.index("function BlocksPane")]
    assert [p for p in ("Blocks", "Rule cards", "Story", "Playfield", "Shot table", "Timeline", "Node graph", "Script",
                        "C it makes") if '"%s"' % p in pages] == ["Blocks", "Rule cards", "Story", "Playfield",
                                                                  "Shot table", "Timeline", "Node graph", "Script",
                                                                  "C it makes"]
