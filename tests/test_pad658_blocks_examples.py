"""PAD-658: whole modes made of BLOCKS for Godzilla - the four new ones (KING CAESAR, KUMONGA, MINILLA, KAMACURAS) and
the eleven C modes rebuilt in blocks - and what the blocks gained on the way. PAD-691: none of them is in the app; they
are the block compiler's test material, in tests/mode_examples/blocks (the C ones in tests/mode_examples/c).

- Everywhere: every example JSON is the program its Python writes, fit to build on Godzilla Premium/LE 1.16 (no
  problem on its card), its clips and sounds each named by its recipe from a film the recipes know, each rebuild says
  what it lost; Premium/LE and Pro get the same new modes; added to a project without its media it plays the game's
  own callouts in their place.
- The Godzilla ports name the right scoop and the top of the Mecha lane as switch shots.
- The desk harness (an ELF host compiler): every example plays its own scenarios (make_examples.py --desk), and the
  generator's new pieces - a counter's label from a block, an ending title in the place of "<NAME> TOTAL", the shot
  a lit mode starts on being that alone, a Light block after the end doing nothing.
"""
import json
import os
import re
import subprocess
import sys

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import code_modes as CM
from pinball_decryptor.plugins.stern import mode_project as MP

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk")
EXDIR = os.path.join(ROOT, "tests", "mode_examples", "blocks")
CDIR = os.path.join(ROOT, "tests", "mode_examples", "c")
sys.path.insert(0, EXDIR)
import examples as BX  # noqa: E402
import make_examples as ME  # noqa: E402

NEW = ("king_caesar", "kumonga", "minilla", "kamacuras")
REBUILT = ("ghidorah_heads", "oxygen_destroyer", "maser_barrage", "final_wars", "anguirus_assist", "meltdown",
           "godzilla_angry", "spacegodzilla", "kiryu", "biollante", "destoroyah")


def _example(slug):
    return next(e for e in BX.EXAMPLES if e["slug"] == slug)


def _c_examples():
    """The C modes' entries in film_recipes.json (name, slug, source, recipe)."""
    with open(os.path.join(CDIR, "film_recipes.json"), encoding="utf-8") as f:
        return json.load(f)["examples"]


# ---- the examples ---------------------------------------------------------------------------------------------
def test_every_example_is_there_and_every_c_example_is_rebuilt():
    slugs = [e["slug"] for e in BX.EXAMPLES]
    assert set(NEW) | set(REBUILT) <= set(slugs)
    assert sorted(set(REBUILT)) == sorted(e["slug"] for e in _c_examples())     # every C example, once
    assert all(os.path.isfile(os.path.join(CDIR, e["source"])) for e in _c_examples())
    assert slugs[:4] == list(NEW)                                               # the new ones first


@pytest.mark.parametrize("slug", NEW + REBUILT)
def test_an_example_is_its_python_and_builds_on_godzilla_le(slug):
    with open(os.path.join(EXDIR, slug + ".json"), encoding="utf-8") as f:
        shipped = json.load(f)
    assert shipped == json.loads(json.dumps(ME.build(slug))), "the JSON is not what its Python writes: make_examples.py"
    assert ME.check(shipped) == []
    p = shipped["program"]
    assert BM.problems(p, **BM.card_checks(MP.profile("godzilla_le_1_16"))) == []
    assert "godzilla_le" in shipped["titles"]
    if shipped["based_on"]:
        assert shipped["based_on"] == slug + ".c" or slug == "kamacuras"
        assert shipped["lost"] or slug == "kamacuras", "a rebuild says what it lost"
        assert all(isinstance(t, str) and t.strip() and "—" not in t and "–" not in t
                   for t in shipped["lost"])


@pytest.mark.parametrize("slug", REBUILT)
def test_a_rebuild_keeps_its_c_examples_name_clock_and_cues(slug):
    ex = _example(slug)
    c = next((e for e in _c_examples() if e["name"] == ex["name"]), None)
    assert c is not None and c["slug"] == slug
    r = c["recipe"]
    # every cue of its C's, with the same pick (round 2's stages add cues of their own)
    for kind in ("clips", "calls"):
        for cue, pick in (r.get(kind) or {}).items():
            assert ex["recipe"][kind].get(cue) == pick, (kind, cue)


def test_premium_and_pro_get_the_same_new_modes():
    """Premium/LE and Pro get the same new modes (a Pro's spinner on the shield ramp is its Right spinner, and it has
    no shield platform to turn); each builds once adapted to the card."""
    le = MP.profile("godzilla_le_1_16")
    assert all(BX.fits(BX.example(n), le) for n in BX.example_names("godzilla_le"))
    assert {BX.example(n)["slug"] for n in BX.example_names("godzilla_le")} == set(NEW) | set(REBUILT)
    pro = MP.profile("godzilla_pro_1_16")
    built = {BX.example(n)["slug"] for n in BX.example_names("godzilla_pro") if BX.fits(BX.example(n), pro)}
    assert set(NEW) <= built
    kumonga = BX.adapt(_example("kumonga"), pro)
    shots = {(s["hat"] or {}).get("shot") for s in kumonga["scripts"]}
    assert "Right spinner" in shots and "Shield ramp spinner" not in shots
    assert not any(b.get("op") == "shield" for s in kumonga["scripts"] for b in BM._walk(s["do"]))
    assert any(b.get("op") == "shield" for s in BX.adapt(_example("kumonga"), le)["scripts"] for b in BM._walk(s["do"]))
    assert BX.example_names("jaws_le") == []


# ---- the ports' switch shots -----------------------------------------------------------------------------------
def test_the_le_port_names_the_scoop_and_the_top_of_the_mecha_lane():
    p = MP.profile("godzilla_le_1_16")
    shots = dict(p.shots)
    assert shots["Right scoop"] == 0x0100000000000000 and shots["Mecha exit top"] == 0x0200000000000000
    port = MP.read_port(os.path.join(SDK, "ports", "godzilla_le-1.16.port"))
    assert (53, 0x0100000000000000, "Right scoop") in port["switch"]
    assert (50, 0x0200000000000000, "Mecha exit top") in port["switch"]
    with open(os.path.join(SDK, "examples", "desk_harness.c"), encoding="utf-8") as f:
        harness = f.read()
    assert '{ "Right scoop", 0x0100000000000000ull }' in harness
    assert '{ "Mecha exit top", 0x0200000000000000ull }' in harness


# ---- adding one ---------------------------------------------------------------------------------------------
def test_without_its_films_it_plays_the_games_callouts(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    slug = BX.add_example(str(project), "KING CAESAR")
    assert slug == "king_caesar" and BX.example_films(BX.example("KING CAESAR")) == ["mg74"]
    prog = BM.load(str(project), slug)
    assert prog["clips"] == [] and prog["sounds"] == [] and prog["music"] == ""
    ops = {b.get("op") for s in prog["scripts"] for b in BM._walk(s["do"])}
    assert "clip" not in ops and "sound" not in ops
    folder = MP.mode_folder(str(project), slug)
    assert BM.problems(prog, folder=folder, **BM.card_checks(MP.profile("godzilla_le_1_16"))) == []
    assert os.path.isfile(os.path.join(folder, slug + ".c")) and os.path.isfile(os.path.join(folder, BM.KIT_FILE))
    with pytest.raises(BM.BlocksError, match="already in this project"):
        BX.add_example(str(project), "KING CAESAR")
    # a sound block with a fallback callout keeps it
    p = BX.without_media({"scripts": [{"hat": {"kind": "mode_start"}, "do": [
        {"op": "sound", "sound": "x", "fallback": "time_up"},
        {"op": "if", "cond": {"k": "running"}, "then": [{"op": "clip", "clip": "y", "where": "full"}],
         "else": [{"op": "sound", "sound": "z", "fallback": ""}]}]}]})
    assert p["scripts"][0]["do"] == [{"op": "callout", "role": "time_up"},
                                     {"op": "if", "cond": {"k": "running"}, "then": [], "else": []}]


# ---- the desk ---------------------------------------------------------------------------------------------------
def _cc():
    if os.name == "nt":
        pytest.skip("the desk harness needs an ELF linker (__start_pm_modes / __stop_pm_modes)")
    if sys.platform == "darwin":
        pytest.skip("the desk harness needs an ELF toolchain")
    import shutil
    for c in ("gcc", "cc", "clang"):
        if shutil.which(c):
            return c
    pytest.skip("no host C compiler")


@pytest.mark.parametrize("slug", NEW + REBUILT)
def test_an_example_plays_its_desk_scenarios(slug, tmp_path, monkeypatch, capsys):
    _cc()
    assert ME.desk([slug], [ME.build(slug)]) == 0, capsys.readouterr().out


def _play(tmp_path, program, *args, slug="blk"):
    cc = _cc()
    src = tmp_path / (slug + ".c")
    src.write_text(BM.to_c(program, slug), encoding="utf-8")
    exe = tmp_path / "harness"
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wextra", "-Wno-unused-parameter", "-I", SDK,
                        "-I", os.path.join(SDK, "examples"), "-o", str(exe),
                        os.path.join(SDK, "examples", "desk_harness.c"), str(src)], capture_output=True, text=True)
    assert r.returncode == 0 and "warning" not in r.stderr.lower(), r.stderr
    return subprocess.run([str(exe), "new_game"] + [str(a) for a in args], capture_output=True, text=True,
                          timeout=60).stdout


def _hud_prog(**kw):
    num = lambda v: {"k": "num", "v": v}                            # noqa: E731
    p = {"name": "TEST MODE", "seconds": 20, "game_modes": "stack", "vars": [{"name": "n", "reset": "game"}],
         "timers": [{"name": "late"}],
         "hud": {"on": True, "line": "GO", "counters": [{"label": "ONE", "sub": "A"}, {"label": "TWO", "sub": "B"},
                                                         {"label": "", "sub": ""}]},
         "scripts": [
             {"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [
                 {"op": "change", "var": "n", "by": num(1)},
                 {"op": "light_mode", "shot": "Right ramp", "color": "#00ff00", "pattern": "blink", "insert": ""}]},
             {"hat": {"kind": "shot", "shot": "Right ramp", "when": "idle"}, "do": [
                 {"op": "change", "var": "n", "by": num(100)}]},
             {"hat": {"kind": "mode_start"}, "do": [
                 {"op": "hud_counter", "counter": 1, "value": {"k": "var", "name": "n"}, "sub": "SEEN", "label": "COUNT"}]},
             {"hat": {"kind": "shot", "shot": "Building", "when": "running"}, "do": [
                 {"op": "timer_start", "timer": "late", "ms": num(2000)}, {"op": "end_mode"}]},
             {"hat": {"kind": "timer_done", "timer": "late"}, "do": [
                 {"op": "light_shot", "shot": "Big loop", "color": "#ff0000", "pattern": "solid"}]},
             {"hat": {"kind": "mode_end"}, "do": [
                 {"op": "hud_text", "which": "title", "text": "IT IS OVER", "value": None},
                 {"op": "hud_text", "which": "line", "text": "FOR NOW", "value": None}]},
         ]}
    p.update(kw)
    return p


def test_a_counters_label_an_ending_title_a_lit_start_and_a_light_after_the_end(tmp_path):
    out = _play(tmp_path, _hud_prog(), "shot", "Left ramp", "ms", 500, "shot", "Right ramp", "secs", 1,
                "shot", "Building", "secs", 5)
    assert "[TEST MODE] START (its lit shot)" in out
    # the shot its light started it on is that alone: n counted the Left ramp once, not the Right ramp's 100
    assert "WORDS PadMode_blk_Hud_C1_Label: COUNT" in out and "WORDS PadMode_blk_Hud_C1_Value: 1" in out
    assert "WORDS PadMode_blk_Hud_C1_Sub: SEEN" in out
    assert "WORDS PadMode_blk_Hud_Title: IT IS OVER" in out and "WORDS PadMode_blk_Hud_Line: FOR NOW" in out
    assert "TEST MODE TOTAL" not in out
    assert "LAMP BIG LOOP" not in out                        # the timer ran on after the end: no light held
    assert "lamps held 0" in out
    # with no ending title it is "<NAME> TOTAL", as before
    p = _hud_prog()
    p["scripts"] = [s for s in p["scripts"] if s["hat"]["kind"] != "mode_end"]
    out = _play(tmp_path, p, "trigger", "blk.start", "secs", 1, "shot", "Building", "secs", 1)
    assert "WORDS PadMode_blk_Hud_Title: TEST MODE TOTAL" in out


def test_the_label_is_checked_and_reaches_the_c():
    p = _hud_prog()
    p["scripts"][2]["do"][0]["label"] = "X" * 17
    assert any("counter's words of more than 16 letters" in t for t in BM.problems(p))
    src = BM.to_c(_hud_prog(), "blk")
    assert 'hud_counter(0, ' in src and '"SEEN", "COUNT");' in src
    assert re.search(r"if \(!was_on && run\.on\) return;", src)


# ---- more music beds (PAD-658: a soundtrack per multiball) ------------------------------------------------------
def test_more_beds_ride_through_the_build_and_the_assets_file(tmp_path):
    folder = tmp_path / "modes" / "gz"
    folder.mkdir(parents=True)
    for f in ("music.wav", "music_swamp.wav"):
        (folder / f).write_bytes(b"RIFF")
    spec = CM.CodeAssets(name="GZ", music="music.wav", beds={"swamp": "music_swamp.wav"})
    assert CM.validate(spec, str(folder)) == []
    assert "more music beds need its own music first" in " ".join(
        CM.validate(CM.CodeAssets(name="GZ", beds={"swamp": "music_swamp.wav"}), str(folder)))
    wants = CM.sound_wants(str(tmp_path), [("gz", spec)])
    assert [(w["key"], w["music"]) for w in wants] == [("music", True), ("music:swamp", True)]
    used = [{"slug": "gz", "key": "music", "request": 125, "sid": 610},
            {"slug": "gz", "key": "music:swamp", "request": 125, "sid": 611}]
    text = CM.runtime_text("gz", spec, None, own_sounds=used)
    assert "music  125 610" in text and "bed    swamp 611" in text
    swapped = [{"slug": "gz", "key": "music", "request": 125, "sid": 610},
               {"slug": "gz", "key": "music:swamp", "request": 125, "stock_key": "00" * 8, "our_key": "11" * 8}]
    assert "swap   125 %s %s music:swamp" % ("00" * 8, "11" * 8) in CM.runtime_text("gz", spec, None, own_sounds=swapped)


def test_past_the_titles_bed_sids_a_bed_is_swapped_in(tmp_path):
    """Godzilla LE 1.16 has 12 bed sids; the 13th music rides the carrier swapped in (no ceiling)."""
    from pinball_decryptor.plugins.stern import mode_write as MW
    code = []
    for k in range(14):
        folder = tmp_path / "modes" / ("m%d" % k)
        folder.mkdir(parents=True)
        (folder / "music.wav").write_bytes(b"RIFF")
        code.append(("m%d" % k, CM.CodeAssets(name="M%d" % k, music="music.wav")))
    logs = []
    out = MW.choose_code_sounds(str(tmp_path), code, (True, ""), MP.profile("godzilla_le_1_16"),
                                log=lambda m, *a: logs.append(m))
    music = [o for o in out if o["music"]]
    assert len(music) == 14
    assert sum(1 for o in music if o.get("sid")) == 12 and sum(1 for o in music if o.get("swap")) == 2
    assert all(o["request"] == 125 for o in music)
    assert sum("swapped in at run time" in m for m in logs) == 2


def test_a_play_the_music_block_switches_the_bed(tmp_path):
    cc = _cc()
    p = {"name": "TEST MODE", "seconds": 20, "game_modes": "stack", "music": "music.wav",
         "beds": [{"name": "swamp", "file": "music_swamp.wav"}],
         "scripts": [{"hat": {"kind": "shot", "shot": "Left ramp", "when": "running"}, "do": [{"op": "music", "bed": "swamp"}]},
                     {"hat": {"kind": "shot", "shot": "Right ramp", "when": "running"}, "do": [{"op": "music", "bed": ""}]},
                     {"hat": {"kind": "shot", "shot": "Building", "when": "running"}, "do": [{"op": "music", "bed": "nope"}]}]}
    assert any("music bed nope, which the mode does not have" in t for t in BM.problems(p))
    p["scripts"].pop()
    assert BM.problems(p) == []
    dump = tmp_path / "dump"
    dump.mkdir()
    (dump / "bd.assets").write_text("name T\nmusic 125 610\nbed swamp 611\n", encoding="utf-8")
    src = tmp_path / "bd.c"
    src.write_text(BM.to_c(p, "bd"), encoding="utf-8")
    exe = tmp_path / "h"
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wextra", "-Wno-unused-parameter", "-I", SDK, "-I",
                        os.path.join(SDK, "examples"), "-o", str(exe), os.path.join(SDK, "examples", "desk_harness.c"),
                        str(src)], capture_output=True, text=True)
    assert r.returncode == 0 and "warning" not in r.stderr.lower(), r.stderr
    out = subprocess.run([str(exe), "new_game", "trigger", "bd.start", "secs", "1", "shot", "Left ramp", "secs", "1",
                          "shot", "Right ramp", "secs", "1"], capture_output=True, text=True, timeout=60,
                         env=dict(os.environ, HARNESS_DUMP=str(dump))).stdout
    assert "music 125 switches to the bed swamp (sound id 611)" in out
    assert "music 125 switches to its own bed (sound id 610)" in out
    assert re.search(r"SID 125 611\n.*\n\s*\d+ SOUND 125", out) or out.count("SOUND 125") >= 3
    # without its own media the block is dropped with the rest
    assert all(b.get("op") != "music" for s in BX.without_media(p)["scripts"] for b in BM._walk(s["do"]))


def test_every_example_fits_the_glass():
    card = os.environ.get("PAD_FIT_CARD", r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
    if not os.path.isfile(card):
        pytest.skip("no Godzilla LE 1.16 card here to read the game's font from")
    import hud_fit
    font = hud_fit.font_from_card(card)
    bad = {ex["slug"]: hud_fit.check(font, ex) for ex in BX.EXAMPLES}
    assert not {k: v for k, v in bad.items() if v}


def test_the_pro_gets_alternate_rules_where_its_layout_differs():
    """A Pro 1.16 has no centre shield, calls the shield-ramp spinner its Right spinner, has no platform, building,
    Mechagodzilla magnet or bridge, and not every Premium light show or insert: an example's title_alt says what the
    Pro does instead, and what the Pro cannot do at all is left out."""
    pro, le = MP.profile("godzilla_pro_1_16"), MP.profile("godzilla_le_1_16")
    num = {"k": "num", "v": 1}
    ex = {"name": "ALT", "slug": "alt", "titles": ["godzilla_le", "godzilla_pro"],
          "title_alt": {"godzilla_pro": {"shots": {"Shield ramp spinner": "Right spinner", "Shield target center": None},
                                         "shows": {"Insert chase": "Glow"}, "inserts": {"GODZILLA SPOT": "MASER FLASH"}}},
          "program": BM.normalize({"name": "ALT", "seconds": 30, "game_modes": "block", "scripts": [
              {"hat": {"kind": "shot", "shot": "Shield ramp spinner", "when": "idle"}, "do": [
                  {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": {"k": "hits", "shot": "Shield ramp spinner"}, "b": num},
                   "then": [{"op": "start_mode"}], "else": None}]},
              {"hat": {"kind": "shot", "shot": "Shield target center", "when": "running"}, "do": [{"op": "score", "points": num}]},
              {"hat": {"kind": "mode_start"}, "do": [
                  {"op": "shield", "where": "toward"}, {"op": "building", "floor": "2"},
                  {"op": "hold", "what": "mg_magnet", "ms": {"k": "num", "v": 500}}, {"op": "hold", "what": "magnet", "ms": {"k": "num", "v": 500}},
                  {"op": "game_show", "name": "Insert chase"}, {"op": "game_show", "name": "Playfield wave"},
                  {"op": "light_shot", "insert": "GODZILLA SPOT", "color": "#ffffff", "pattern": "solid"},
                  {"op": "light_shot", "shot": "Shield target center", "color": "#ffffff", "pattern": "solid"}]}]})}
    p = BX.adapt(ex, pro)
    hats = [s["hat"].get("shot") for s in p["scripts"]]
    assert hats == ["Right spinner", None]                                   # the centre shield's script is gone
    assert p["scripts"][0]["do"][0]["cond"]["a"]["shot"] == "Right spinner"   # its hits too
    start = p["scripts"][1]["do"]
    assert [b["op"] for b in start] == ["hold", "game_show", "light_shot"]
    assert start[0]["what"] == "magnet" and start[1]["name"] == "Glow" and start[2]["insert"] == "MASER FLASH"
    assert BM.problems(p, **BM.card_checks(pro)) == []
    assert BX.adapt(ex, le) == ex["program"]                                # Premium/LE: as written
    assert BX.fits(ex, pro) and BX.fits(ex, le)
