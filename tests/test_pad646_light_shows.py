"""PAD-646: the light-show editor - a mode's own named light shows, made on the Modes tab's Light shows page.

A mode keeps its shows in blocks.json (``shows``: [{name, steps, repeat}]), a Run the light show block runs one by
name from any rule, and the page plays a show on the playfield picture with the C engine's arithmetic mirrored in JS.
Here: the program side (normalize, problems, notes, the C, the script text), the engine's new parts in the desk
harness (a show run twice, one running until the mode ends, blending in), the JS preview agreeing with the C colour
for colour (node + a host C compiler), and the wiring of the tab and the block.
"""

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM, mode_script as MS
from tests import test_stern_block_modes as T

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs")
NODE = shutil.which("node")
num = T.num


def _step(fx, ms, a, b, at="center", rate=0, gi="keep", **kw):
    st = {"fx": fx, "ms": ms, "a": a, "b": b, "at": at, "rate": rate, "gi": gi}
    st.update(kw)
    return st


ROAR = [_step("strobe", 400, "#ffffff", "#ff3000", "center", 55, "flash"),
        _step("spiral_out", 400, "#40a0ff", "#001030", "xy", 0, "dark", x=120, y=200, blend=150),
        _step("fade", 400, "#40a0ff", "#000000", "center", 0, "keep", blend=200)]
LOOP = [_step("ripple", 500, "#00e0ff", "#002030", "center", 120, "dark")]
OUTRO = [_step("fade_in", 400, "#ffb000", "#000000", "center", 0, "dark"), _step("solid", 400, "#ffb000", "#000000")]


def _prog(seconds=8, end_show=True):
    scripts = [
        {"hat": {"kind": "shot", "shot": "Building", "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "mode_start"}, "do": [{"op": "show", "show": "mine", "name": "Kaiju roar"}]},
        {"hat": {"kind": "seconds_left", "seconds": 5}, "do": [{"op": "show", "show": "mine", "name": "Loop"}]},
        {"hat": {"kind": "shot", "shot": "Left ramp", "when": "running"}, "do": [{"op": "show", "show": "mine", "name": "Kaiju roar"}]},
    ]
    if end_show:
        scripts.append({"hat": {"kind": "mode_end"}, "do": [{"op": "show", "show": "mine", "name": "Outro"}]})
    p = T.prog(scripts, seconds=seconds)
    p["shows"] = [{"name": "Kaiju roar", "steps": ROAR, "repeat": 2}, {"name": "Loop", "steps": LOOP, "repeat": 0},
                  {"name": "Outro", "steps": OUTRO, "repeat": 1}]
    return p


# ---- the program ----------------------------------------------------------------------------------------
def test_normalize_keeps_the_shows_and_drops_what_is_not_one():
    p = BM.normalize({"shows": [{"name": " Kaiju roar ", "steps": ROAR, "repeat": "3"}, {"name": "x", "steps": "no"},
                                "nope", {"name": "Loop", "steps": [1, LOOP[0]], "repeat": 99}]})
    assert [s["name"] for s in p["shows"]] == ["Kaiju roar", "Loop"]
    assert p["shows"][0]["repeat"] == 3 and p["shows"][1]["repeat"] == BM.REPEAT_MAX
    assert p["shows"][1]["steps"] == LOOP
    assert BM.normalize({})["shows"] == []
    assert BM.show_named(p, "kaiju ROAR")["name"] == "Kaiju roar" and BM.show_named(p, "Nope") is None


def test_problems_name_what_is_wrong_in_a_show():
    p = _prog()
    assert BM.problems(p, T.SHOTS) == []
    p["shows"] += [{"name": "", "steps": []}, {"name": "kaiju roar", "steps": ROAR},
                   {"name": "Bad", "steps": [_step("burst", 100, "#fff", "#000000", "xy", x=-1, y=5, blend=99999),
                                             _step("warp", 100, "#ffffff", "#000000")]},
                   {"name": "Too*many", "steps": ROAR}]
    p["scripts"][1]["do"].append({"op": "show", "show": "mine", "name": "Nope"})
    p["scripts"][1]["do"].append({"op": "show", "show": "mine"})
    said = BM.problems(p, T.SHOTS)
    for words in ("Light show 4 has no name", "The light show 4 has no steps", "Two of the mode's light shows are called 'kaiju roar'",
                  "'Bad', step 1, has a color missing", "'Bad', step 1, centers on a point of its own that is not on the picture",
                  "'Bad', step 1, blends in over 0 to 10000 ms", "'Bad', step 2, has no pattern",
                  "'Too*many''s name is not one", "runs the light show 'Nope', which the mode does not have",
                  "runs a light show of the mode's with none chosen"):
        assert any(words in t for t in said), (words, said)
    # the old forms still pass as they are
    old = T.prog([{"hat": {"kind": "mode_start"}, "do": [{"op": "show", "show": "burst"},
                                                         {"op": "show", "show": "own", "steps": ROAR}]}])
    assert BM.problems(old, T.SHOTS) == []


def test_notes_say_which_show_no_rule_runs_and_a_looping_show_started_at_the_end():
    p = _prog()
    p["shows"].append({"name": "Spare", "steps": ROAR, "repeat": 1})
    p["scripts"][-1]["do"] = [{"op": "show", "show": "mine", "name": "Loop"}]
    notes = BM.notes(p)
    assert any("No block runs the light show 'Spare' yet" in t for t in notes)
    assert any("'Loop' runs over and over until the mode ends, and When the mode ends starts it" in t for t in notes)
    assert not any("'Kaiju roar'" in t for t in notes)


def test_the_c_keeps_one_table_per_show_with_its_blend_point_and_repeat():
    src = BM.to_c(_prog(), "blk")
    assert src.count("static const struct fx_step SHOW_") == 3          # Kaiju roar, Loop, Outro: not one per block
    assert src.count('show_start(SHOW_0, 3, "Kaiju roar", 2);') == 2     # the start and the Left ramp share a table
    assert 'show_start(SHOW_1, 1, "Loop", 0);' in src and 'show_start(SHOW_2, 2, "Outro", 1);' in src
    assert "{ FX_SPIRAL_OUT, 400, 0x40a0ffu, 0x001030u, 120, 200, 0, GI_DARK, 150 },   /* a spiral outwards, at a point of its own */" in src
    assert "{ FX_FADE_OUT, 400, 0x40a0ffu, 0x000000u, 150, 330, 0, GI_KEEP, 200 }" in src
    assert "struct fx_step { int fx; unsigned ms, a, b; int x, y; unsigned rate; int gi; unsigned blend; };" in src
    assert "    show_last_pass();" in src and "show.forever" in src
    used = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", src))
    assert used <= T._header_calls(), used - T._header_calls()
    plain = BM.to_c(BM.starter("RAMP FRENZY", T.SHOTS), "ramp_frenzy")
    assert "show_last_pass" not in plain and "#define SHOWING 0" in plain
    # a show the mode has that no block runs makes no table (an unused table is a compiler warning)
    p = _prog()
    p["shows"].append({"name": "Spare", "steps": ROAR, "repeat": 1})
    assert BM.to_c(p, "blk").count("static const struct fx_step SHOW_") == 3


def test_the_script_text_carries_the_shows_and_reads_back_the_same():
    p = BM.normalize(_prog())
    text = MS.to_script(p, defaults=BM.normalize({}))
    assert "shows = [" in text and '"name": "Kaiju roar"' in text and '"blend": 150' in text
    assert 'show(show="mine", name="Kaiju roar")' in text
    assert BM.normalize(MS.from_script(text)) == p


def test_show_choices_offer_the_editor_what_it_needs():
    ch = BM.show_choices()
    grouped = [k for _g, keys in ch["fx_groups"] for k in keys]
    assert sorted(grouped) == sorted(BM.FX) and len(grouped) == len(set(grouped))
    assert {"spiral_out", "spiral_in", "ripple", "bounce", "fade_in", "solid"} <= set(BM.FX)
    assert ch["place_xy"]["center"] == [150, 330] and "xy" not in ch["place_xy"]
    assert [k for k, _l in ch["places"]][-1] == "xy"
    assert ch["limits"] == {"steps": 32, "shows": 24, "repeat": 10, "ms": [50, 10000], "rate": 2000, "name": 24}
    assert {"spiral", "spiral_in", "fade_up", "left", "right", "ripples", "scanner"} <= {s["key"] for s in ch["shows"]}
    for s in ch["shows"]:                                 # every ready-made show is a show the checker accepts
        p = T.prog([{"hat": {"kind": "mode_start"}, "do": [{"op": "show", "show": "mine", "name": "X"}]}])
        p["shows"] = [{"name": "X", "steps": s["steps"], "repeat": 1}]
        assert BM.problems(p, T.SHOTS) == [], s["key"]


# ---- the engine, in the desk harness --------------------------------------------------------------------
def test_the_harness_runs_a_show_twice_then_one_until_the_mode_ends(tmp_path, monkeypatch):
    T._cc()
    monkeypatch.setenv("HARNESS_PLACES", "1")
    out = T.play(tmp_path, _prog(), "shot", "Building", "secs", 12)
    start = T._at(out, r"\[TEST MODE\] START")
    assert "show Kaiju roar: 3 step(s) over 36 placed inserts, 2 GI string(s), 2 times" in out
    over = T._at(out, r"\[TEST MODE\] show Kaiju roar: over")
    assert 2400 <= over - start <= 2450                   # three 400 ms steps, twice
    loop = T._at(out, r"\[TEST MODE\] show Loop: 1 step\(s\) over 36 placed inserts, 2 GI string\(s\), until the mode ends")
    assert 2950 <= loop - start <= 3050                   # 5 s left of 8
    end = T._at(out, r"\[TEST MODE\] END \(time ran out\)")
    assert "show Loop: over" not in out                   # the end's own show took its place
    assert T._at(out, r"\[TEST MODE\] show Outro: 2 step\(s\)") - end <= 20
    assert 800 <= T._at(out, r"\[TEST MODE\] show Outro: over") - end <= 850
    assert int(re.search(r"END paints (\d+)", out).group(1)) > 200
    assert "END lamps held 0" in out
    # with no show at the end, the looping one finishes the pass it is in and hands the inserts back
    out = T.play(tmp_path, _prog(end_show=False), "shot", "Building", "secs", 12)
    end = T._at(out, r"\[TEST MODE\] END \(time ran out\)")
    over = T._at(out, r"\[TEST MODE\] show Loop: over")
    assert 0 <= over - end <= 520
    assert "END lamps held 0" in out


# ---- the preview's engine agrees with the C's --------------------------------------------------------------
_POINTS = [(150, 330), (0, 0), (300, 600), (10, 590), (290, 5), (77, 333), (150, 100), (151, 331), (149, 329),
           (200, 450), (60, 200), (240, 480), (150, 560), (120, 200), (30, 30), (270, 580)]
_TIMES = [0, 1, 37, 150, 299, 300, 500, 777, 999]


def _c_driver():
    c = BM._SHOW_C
    helpers = c[:c.index("/* PAD-646: repeat = how many")]
    colour = c[c.index("/* the color of the insert"):c.index("/* every tick while the show runs")]
    steps = ",\n".join("    { %s, 1000, 0xff8040u, 0x102030u, 150, 330, 120, GI_DARK, 300 }" % cname for cname, _w in BM.FX.values())
    return "\n".join([
        "#include <stdio.h>",
        "#define PM_RGB(r, g, b) ((((unsigned)(r) & 255u) << 16) | (((unsigned)(g) & 255u) << 8) | ((unsigned)(b) & 255u))",
        "\n".join(BM._show_decls([])), helpers, colour,
        "static const struct fx_step STEPS[] = {\n%s\n};" % steps,
        "static const struct fx_step PREV = { FX_BURST, 700, 0x20ff80u, 0x000000u, 100, 400, 0, GI_KEEP, 0 };",
        "int main(void) {",
        "    static const int pts[][2] = { %s };" % ", ".join("{ %d, %d }" % p for p in _POINTS),
        "    static const unsigned times[] = { %s };" % ", ".join(str(t) for t in _TIMES),
        "    unsigned s, t, k;",
        "    show.prev = &PREV;",
        "    for (s = 0; s < sizeof(STEPS) / sizeof(STEPS[0]); s++)",
        "        for (t = 0; t < sizeof(times) / sizeof(times[0]); t++)",
        "            for (k = 0; k < sizeof(pts) / sizeof(pts[0]); k++) {",
        "                show.seed = 12345u;",
        "                printf(\"%06x\\n\", fx_blend(&STEPS[s], pts[k][0], pts[k][1], (int)k, times[t]));",
        "            }",
        "    return 0;",
        "}", ""])


def _js_driver():
    with open(os.path.join(JS_DIR, "modes_lightshows.js"), encoding="utf-8") as f:
        src = f.read()
    engine = src[src.index("const i32 ="):src.index("// A step as the C's table row holds it")].replace("export ", "")
    return "\n".join([
        engine,
        "const KEYS = %s;" % json.dumps(list(BM.FX)),
        "const PTS = %s, TIMES = %s;" % (json.dumps(_POINTS), json.dumps(_TIMES)),
        "const prev = { fx: 'burst', ms: 700, a: 0x20ff80, b: 0, x: 100, y: 400, rate: 0, gi: 'keep', blend: 0 };",
        "const out = [];",
        "for (const fx of KEYS) { const st = { fx, ms: 1000, a: 0xff8040, b: 0x102030, x: 150, y: 330, rate: 120, gi: 'dark', blend: 300 };",
        "  for (const t of TIMES) PTS.forEach(([x, y], k) => { const S = { seed: 12345 }; out.push(fxBlend(st, prev, x, y, k, t, S).toString(16).padStart(6, '0')); }); }",
        "console.log(out.join('\\n'));", ""])


def _node_run(tmp_path, text):
    """The driver's output under Node: the Linux node, or (under WSL, where the C compiler is) Windows' node.exe
    on a file it can reach."""
    node = NODE or shutil.which("node.exe")
    if node is None:
        pytest.skip("needs Node.js")
    if node.lower().endswith(".exe") and os.path.isdir("/mnt/c/tmp"):
        import tempfile
        d = tempfile.mkdtemp(prefix="pad646-", dir="/mnt/c/tmp")
        path = os.path.join(d, "fx.mjs")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        win = subprocess.run(["wslpath", "-w", path], capture_output=True, text=True, check=True).stdout.strip()
        try:
            return subprocess.run([node, win], capture_output=True, text=True, check=True).stdout.split()
        finally:
            shutil.rmtree(d, ignore_errors=True)
    (tmp_path / "fx.mjs").write_text(text, encoding="utf-8")
    return subprocess.run([node, str(tmp_path / "fx.mjs")], capture_output=True, text=True, check=True).stdout.split()


def test_the_preview_paints_every_insert_the_color_the_c_paints(tmp_path):
    cc = T._cc()
    (tmp_path / "fx.c").write_text(_c_driver(), encoding="utf-8")
    r = subprocess.run([cc, "-std=gnu17", "-o", str(tmp_path / "fx"), str(tmp_path / "fx.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    want = subprocess.run([str(tmp_path / "fx")], capture_output=True, text=True, check=True).stdout.split()
    got = _node_run(tmp_path, _js_driver())
    n = len(BM.FX) * len(_TIMES) * len(_POINTS)
    assert len(want) == n and len(got) == n
    bad = [(i, w, g) for i, (w, g) in enumerate(zip(want, got)) if w != g]
    assert not bad, bad[:10]
    assert len(set(want)) > 100                            # the patterns paint, not one colour over and over


# ---- the wiring --------------------------------------------------------------------------------------------
def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_the_tab_the_block_and_the_words_know_the_modes_own_shows():
    js = _read("pinball_decryptor", "webui", "static", "js", "tabs", "modes_lightshows.js")
    for key in BM.FX:
        assert 'case "%s"' % key in js, key                 # the preview knows every pattern the C has
    modes = _read("pinball_decryptor", "webui", "static", "js", "tabs", "modes.js")
    assert 'import { LightShowsView } from "./modes_lightshows.js";' in modes
    assert '["shows", "Light shows",' in modes
    blocks = _read("pinball_decryptor", "webui", "static", "js", "tabs", "modes_blocks.js")
    assert 'group: "The mode\'s own (Light shows)"' in blocks and "const SHOW_STEPS = %d;" % BM.SHOW_STEPS in blocks
    views = _read("pinball_decryptor", "webui", "static", "js", "tabs", "modes_views.js")
    assert "Run the mode's light show" in views
    sys.path.insert(0, os.path.join(ROOT, "tools", "mode_views"))
    try:
        import describe as D
    finally:
        sys.path.pop(0)
    assert D.SAY["show"]({"op": "show", "show": "mine", "name": "Kaiju roar"}) == "Light show: the mode's Kaiju roar"
    assert D.SAY["show"]({"op": "show", "show": "burst"}) == "Light show: A burst of gold"


# ---- PAD-767: the GI dark until the mode ends -----------------------------------------------------------------
def _gi_prog(with_show):
    start = [{"op": "gi", "gi": "dark"}] + ([{"op": "show", "show": "mine", "name": "Kaiju roar"}] if with_show else [])
    p = T.prog([
        {"hat": {"kind": "shot", "shot": "Building", "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "mode_start"}, "do": start},
        {"hat": {"kind": "shot", "shot": "Left ramp", "when": "running"}, "do": [{"op": "gi", "gi": "game"}]},
    ], seconds=8)
    if with_show:
        p["shows"] = [{"name": "Kaiju roar", "steps": ROAR, "repeat": 1}]
    return p


def test_a_gi_block_is_checked_and_says_what_it_does():
    p = _gi_prog(False)
    assert not BM.problems(p)
    p["scripts"][1]["do"][0]["gi"] = "dim"
    assert any("sets the GI" in m for m in BM.problems(p))


def test_the_gi_stays_dark_until_the_mode_ends_with_or_without_a_show(tmp_path, monkeypatch):
    """David, MELTDOWN: "it would be cooler if the lights stayed off for the whole mode instead of just the first
    10 seconds" - the shows' GI steps were the only dark; a GI block holds it to the end and gives it back"""
    T._cc()
    monkeypatch.setenv("HARNESS_PLACES", "1")
    for with_show in (False, True):
        out = T.play(tmp_path, _gi_prog(with_show), "shot", "Building", "secs", 12)
        start = T._at(out, r"\[TEST MODE\] START")
        assert T._at(out, r"\[TEST MODE\] GI: 2 string\(s\) dark until the mode ends") - start <= 20
        end = T._at(out, r"\[TEST MODE\] END \(time ran out\)")
        assert 0 <= T._at(out, r"\[TEST MODE\] GI: the mode is over - the game's again") - end <= 40
        paints = int(re.search(r"END paints (\d+)", out).group(1))           # only changes count
        assert paints == 2 if not with_show else paints > 200     # both strings held dark once; or a show over them
        assert "END lamps held 0" in out
    # a GI block that gives it back
    out = T.play(tmp_path, _gi_prog(False), "shot", "Building", "secs", 1, "shot", "Left ramp", "secs", 1)
    assert "GI: the game's again" in out and "GI: the mode is over" not in out
