"""PAD-414: a mode shakes the cabinet's shaker motor (Godzilla Premium/LE) - the runtime's limits, the game's own
shakes, the mode file's lines, the model, the tab and the blocks, at the desk. Emulator-proven on the stock
Premium/LE 1.16 card (MODE_SDK.md "The shaker"; ``mode_project.SHAKER_PROVEN``).

What is worth failing on:
  * ONLY THROUGH THE GAME'S OWN SHAKE: the operator's SHAKER MOTOR setting always applies (off = nothing), the
    runtime never forces it, and the stop is the game's own.
  * THE LIMITS ARE THE RUNTIME'S: the running mode, in a game, the setting on, not over the game's own shake or
    one of the mode's, 20 shakes and 15 s a minute - in that order of reasons; never longer than the game's own
    longest shake at that strength.
  * EVERY END STOPS IT, except the mode's ending shake (pm_shake_outlast), which a ball end, game end or tilt
    still stops.
  * THE GAME'S SHAKES ARE THE GAME'S: the port's `text shake_<name>` steps, read from its program.
"""
import os
import pathlib
import re
import shutil
import struct
import subprocess

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import mode_project as MP

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORT = SDK / "ports" / "godzilla_le-1.16.port"
CC = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")
needs_cc = pytest.mark.skipif(not CC, reason="no C compiler on this host")


def _lift(src, signature):
    """A function's text, brace-matched from its signature (a prototype is skipped)."""
    i = src.index(signature)
    while src.find(";", i) < src.find("{", i):
        i = src.index(signature, i + 1)
    depth = 0
    for k in range(src.index("{", i), len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError("unbalanced braces after " + signature)


def _rt():
    return RUNTIME.read_text(encoding="utf-8")


def _port_text(name):
    m = re.search(r"^text %s\s+(.+?)\s*$" % re.escape(name), PORT.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def _compile_run(tmp_path, code):
    (tmp_path / "t.c").write_text(code)
    r = subprocess.run([CC, "-std=gnu17", "-Wall", "-o", str(tmp_path / "t"), str(tmp_path / "t.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return subprocess.run([str(tmp_path / "t")], capture_output=True, text=True, timeout=30).stdout


# ---- the runtime ---------------------------------------------------------------------------
@needs_cc
def test_the_refusals_and_their_order(tmp_path):
    src = _rt()
    code = "#include <stdio.h>\n" + "\n".join(re.findall(r"^#define SHAKE_\w+ .*$", src, re.M)) + "\n" + \
        _lift(src, "static const char *shake_refusal(") + r"""
static unsigned long st[SHAKE_PER_MIN];
static unsigned on[SHAKE_PER_MIN];
static void t(const char *label, int run, int game, unsigned setting, int theirs, unsigned long ours, unsigned ms,
              unsigned long now)
{
    const char *w = shake_refusal(run, game, setting, theirs, ours, ms, now, st, on);
    printf("%s|%s\n", label, w ? w : "-");
}
int main(void)
{
    unsigned i;
    t("ok", 1, 1, 4, 0, 0, 500, 100000);
    t("not_running", 0, 0, 0, 1, 100500, 500, 100000);
    t("no_game", 1, 0, 0, 1, 100500, 500, 100000);
    t("setting_off", 1, 1, 0, 1, 100500, 500, 100000);
    t("ours_runs", 1, 1, 1, 1, 100500, 500, 100000);
    t("ours_ended", 1, 1, 1, 0, 100000, 500, 100000);
    t("theirs", 1, 1, 1, 1, 0, 500, 100000);
    st[0] = 90000, on[0] = 14600;
    t("on_time_full", 1, 1, 4, 0, 0, 500, 100000);
    t("on_time_fits", 1, 1, 4, 0, 0, 400, 100000);
    t("on_time_old", 1, 1, 4, 0, 0, 500, 150001);
    for (i = 0; i < SHAKE_PER_MIN; i++) st[i] = 50000 + i * 2000, on[i] = 100;
    t("twenty_in_a_minute", 1, 1, 4, 0, 0, 100, 100000);
    return 0;
}
"""
    rows = dict(line.split("|", 1) for line in _compile_run(tmp_path, code).strip().splitlines())
    assert rows["ok"] == "-"
    assert rows["not_running"].startswith("only the running mode")
    assert rows["no_game"].startswith("no game is being played")
    assert rows["setting_off"].startswith("the operator has the shaker switched off")
    assert rows["ours_runs"].startswith("a shake of the mode's is still running")
    assert rows["ours_ended"] == "-"
    assert rows["theirs"].startswith("one of the game's own shakes is running")
    assert rows["on_time_full"].startswith("the mode has shaken the cabinet for 15 s")
    assert rows["on_time_fits"] == "-"
    assert rows["on_time_old"] == "-"
    assert rows["twenty_in_a_minute"].startswith("twenty shakes in the last minute")


@needs_cc
def test_a_game_shake_is_read_in_order_and_clamped_to_the_games_own_longest(tmp_path):
    src = _rt()
    code = "#include <stdio.h>\n" + "\n".join(re.findall(r"^#define SHAKE_\w+ .*$", src, re.M)) + "\n" + \
        "struct shake_step { unsigned at, ms, strength; };\n" + \
        _lift(src, "static unsigned shake_parse(") + r"""
static const unsigned top[SHAKE_STRENGTHS] = { 1000, 1000, 5000, 5000 };
static void t(const char *label, const char *line)
{
    struct shake_step s[SHAKE_STEPS];
    unsigned n = shake_parse(line, top, s, SHAKE_STEPS), i;
    printf("%s|%u", label, n);
    for (i = 0; i < n; i++) printf(" %u:%u:%u", s[i].at, s[i].ms, s[i].strength);
    printf("\n");
}
int main(void)
{
    t("jackpot", "0:500:0");
    t("mb", "266:334:2 633:100:2 1600:500:2 2560:1000:2 4000:5000:2");
    t("too_long_hard", "0:3000:0");
    t("too_short", "0:20:3");
    t("no_such_strength", "0:500:4");
    t("out_of_order", "500:100:0 100:100:0");
    t("junk", "0:500");
    t("none", "");
    return 0;
}
"""
    rows = dict(line.split("|", 1) for line in _compile_run(tmp_path, code).strip().splitlines())
    assert rows["jackpot"] == "1 0:500:0"
    assert rows["mb"] == "5 266:334:2 633:100:2 1600:500:2 2560:1000:2 4000:5000:2"
    assert rows["too_long_hard"] == "1 0:1000:0"
    assert rows["too_short"] == "1 0:100:3"
    for bad in ("no_such_strength", "out_of_order", "junk", "none"):
        assert rows[bad] == "0", bad


def test_only_the_games_own_shake_drives_the_motor_and_never_forced():
    src = _rt()
    sec = src[src.index("/* ---- the shaker (PAD-414)"):src.index("/* ---- the game's own rules: a shot that COUNTS AS")]
    assert sec.count('fn("shake")') == 2                      # the send, and the arm's log line
    assert '(ms, strength, 0)' in _lift(sec, "static unsigned shake_send(")          # force 0: never forced
    assert 'fn("coil_fire")' not in sec                          # never the raw coil
    assert sec.count('fn("shake_stop")') == 1 and 'fn("shake_stop")' in _lift(sec, "static void shake_let_go(")
    # a strength the game does not use, or a time past its own longest at that strength, never reaches it
    shake = _lift(sec, "int pm_shake(")
    assert "strength >= SHAKE_STRENGTHS" in shake and "shk.max_ms[strength]" in shake
    begin = _lift(sec, "static int shake_begin(")
    assert "shake_setting()" in begin and "shake_refusal(pm_running(), pm_in_game()" in begin


def test_every_end_stops_it_except_the_modes_ending_shake():
    src = _rt()
    assert "if (!running) shake_mode_ended();" in _lift(src, "void pm_end(void)")
    assert 'shake_let_go("the ball ended");' in _lift(src, "static void on_ball_end(")
    tick = _lift(src, "static void shake_tick(")
    assert 'shake_let_go("the game ended or tilted")' in tick           # a tilt or game end: always
    assert "!running && !shk.outlast" in tick                            # the mode's end: unless it outlasts
    ended = _lift(src, "static void shake_mode_ended(")
    assert "shk.outlast" in ended and 'shake_let_go("the mode ended")' in ended
    # the outlast mark ends with the shake: any let-go and any new shake clear it
    assert "shk.outlast = 0;" in _lift(src, "static void shake_let_go(")
    assert "shk.outlast = 0;" in _lift(src, "static int shake_begin(")
    assert "shake_tick();" in _lift(src, "static void on_tick(") and "shake_arm();" in src


def test_a_stop_cuts_only_the_shake_the_mode_sent():
    """The game's own shake (one asked for since, longer) is left to run; ours is stopped with the game's stop."""
    let_go = _lift(_rt(), "static void shake_let_go(")
    assert "shk.sent_until > now && left <= shk.sent_until - now + 50ul" in let_go
    assert "the shake running now is the game's own, left to run" in let_go


# ---- the port, against the game's program ----------------------------------------------------
@pytest.fixture(scope="module")
def elf():
    return os.environ.get("PAD_GZLE116_ELF", r"C:\tmp\gzle116_stock.elf")


def _word(b, va):
    phoff, phnum = struct.unpack_from("<I", b, 0x1c)[0], struct.unpack_from("<H", b, 0x2c)[0]
    for i in range(phnum):
        t, off, v, _pa, fs, _ms, _fl, _al = struct.unpack_from("<8I", b, phoff + i * 32)
        if t == 1 and v <= va < v + fs:
            return struct.unpack_from("<I", b, off + va - v)[0]
    raise AssertionError(hex(va))


def test_the_ports_tables_are_the_games_own(elf):
    if not elf or not os.path.isfile(elf):
        pytest.skip("game program not present: %s" % elf)
    b = open(elf, "rb").read()
    # the setting's longest shake (0x6487f4) and the strengths' powers (0x648808)
    setting = [_word(b, 0x6487f4 + 4 * i) for i in range(5)]
    assert setting == [int(x) for x in _port_text("shake_setting_ms").split()]
    powers = _word(b, 0x648808)
    assert [powers >> (8 * i) & 0xff for i in range(4)] == [51, 36, 31, 23]
    # the shake reads adjustment 335 and fires drive 7
    text = PORT.read_text(encoding="utf-8")
    assert re.search(r"^value shake_adj\s+335\b", text, re.M) and re.search(r"^value shake_drive\s+7\b", text, re.M)
    assert _word(b, 0x189a60) == 0xe300014f                              # movw r0, #335 (the adjustment)
    assert _word(b, 0x189ae0) == 0xe3a00007                              # mov r0, #7 (the drive)


def test_the_games_shakes_fit_its_own_longest():
    top = [int(x) for x in _port_text("shake_max_ms").split()]
    assert top == [1000, 1000, 5000, 5000]
    p = MP.profile("godzilla_le_1_16")
    assert [n for n, _l in p.shakes] == ["hit", "big_hit", "jackpot", "rumble", "multiball_start"]
    for name, _label in p.shakes:
        steps = [tuple(int(x) for x in s.split(":")) for s in _port_text("shake_" + name).split()]
        assert steps == sorted(steps), name
        for _at, ms, strength in steps:
            assert 100 <= ms <= top[strength], name
    assert _port_text("shake_jackpot") == "0:500:0"


# ---- the mode file -------------------------------------------------------------------------
def _harness(tmp_path_factory):
    from tests.test_spike2_mode_aside import BLOCK_STUBS, _build
    anchor = next(new for _old, new in BLOCK_STUBS if "pm_block_game_modes" in new)
    tail = anchor[anchor.index("int pm_block_game_modes"):]
    stubs = BLOCK_STUBS + [(tail, tail + (
        "\nint pm_shake(unsigned ms, unsigned strength) { printf(\"SHAKE %u %u at %lu\\n\", ms, strength, now_ms); "
        "return 1; }"
        "\nint pm_shake_game(const char *name) { printf(\"SHAKEGAME %s at %lu\\n\", name, now_ms); return 1; }"
        "\nvoid pm_shake_outlast(void) { printf(\"OUTLAST at %lu\\n\", now_ms); }"))]
    return _build(tmp_path_factory, stubs, "shaker")


@pytest.fixture(scope="module")
def harness_shaker(tmp_path_factory):
    return _harness(tmp_path_factory)


def _run(harness, tmp_path, cfg, *args):
    from tests.test_spike2_mode_aside import _run as run
    return run(harness, tmp_path, cfg, *args)


QUAKE = ("name QUAKE\ntrigger 0x08000000 1\nseconds 2\nshots 0x00100000\naward 1000\n"
         "screen_node PadMode_quake_Screen\nscreen_text PadMode_quake_Screen.PadMode_quake_Screen_Words\n")


@needs_cc
def test_start_shot_and_end_shakes(harness_shaker, tmp_path):
    cfg = QUAKE + "shake start 1500 2\nshake shot game jackpot 0x00100000\nshake end 1000 3\n"
    out = _run(harness_shaker, tmp_path, cfg, "shot", "0x08000000", "tick", "30", "shot", "0x00100000",
               "tick", "30", "shot", "0x00200000", "tick", "200")
    lines = [ln for ln in out.splitlines() if ln.startswith(("SHAKE", "OUTLAST"))]
    assert [ln.split(" at ")[0] for ln in lines] == ["SHAKE 1500 2", "SHAKEGAME jackpot", "SHAKE 1000 3", "OUTLAST"]
    assert '"QUAKE": 3 shake line(s)' in out
    end = out.index("SHAKE 1000 3")
    assert out.index("OUTLAST") > end and "QUAKE END" in out[end:]       # marked before the end, then the end


@needs_cc
def test_bad_shake_lines_are_logged_and_ignored(harness_shaker, tmp_path):
    cfg = QUAKE + "shake sideways 500 0\nshake start\nshake shot 300 0\nshake start game hit\n"
    out = _run(harness_shaker, tmp_path, cfg, "shot", "0x08000000", "tick", "30")
    assert 'shake takes start, shot or end - "sideways 500 0" ignored' in out
    assert 'shake needs a time or `game <name>` - "shake start" ignored' in out
    assert 'shake shot needs a shot mask - "shake shot 300 0" ignored' in out
    assert [ln.split(" at ")[0] for ln in out.splitlines() if ln.startswith("SHAKE")] == ["SHAKEGAME hit"]


# ---- the model -----------------------------------------------------------------------------
def test_only_the_premium_le_can_and_the_rest_say_why():
    assert MP.profile("godzilla_le_1_16").can("shaker")
    assert "shakes its cabinet" in MP.profile("godzilla_pro_1_16").why_not("shaker")
    assert "shaker" in MP.PARTS


def test_the_lines_and_the_refusals():
    p = MP.profile("godzilla_le_1_16")
    spec = MP.ModeSpec(name="QUAKE", title=p.key, start_shot="Maser target", scoring_shots=["Left ramp"])
    spec.shakes = [["start", 1500, 2, ""], ["shot", "jackpot", 0, "Left ramp"], ["end", 1000, 3, ""]]
    assert MP.validate(spec) == []
    assert MP.shake_lines(spec, p) == ["shake          start 1500 2", "shake          shot game jackpot 0x00100000",
                                       "shake          end 1000 3"]
    assert [ln for ln in MP.runtime_cfg(spec, "quake").splitlines() if ln.startswith("shake")] == \
        MP.shake_lines(spec, p)
    spec.shakes = [["start", 3000, 0, ""]]
    assert MP.validate(spec) == ["A hard shake lasts 0.1 to 1 seconds: the game's own longest at that strength."]
    spec.shakes = [["start", 3000, 3, ""], ["shot", "earthquake", 0, "Nowhere"], ["sometime", 500, 9, ""]]
    got = MP.validate(spec)
    assert "Godzilla Premium/LE 1.16 has no shake of its own called 'earthquake'." in got
    assert "Godzilla Premium/LE 1.16 has no shot called 'Nowhere' to shake the cabinet on." in got
    assert "A shake comes as the mode starts, on a shot, or as it ends." in got
    assert any(g.startswith("A shake's strength is 0 hard, 1 strong") for g in got)
    spec.shakes = [["start", 500, 0, ""]] * 5
    assert "A mode shakes the cabinet at most 4 ways." in MP.validate(spec)


def test_a_new_mode_on_a_pro_has_it_off_and_the_field_round_trips(tmp_path):
    pro = MP.profile("godzilla_pro_1_16")
    spec = MP.ModeSpec(name="QUAKE", title="godzilla_le_1_16", shakes=[["start", 500, 0, ""]])
    MP._switch_off_what_it_cannot(spec, pro)
    assert spec.shakes == []
    spec = MP.ModeSpec(name="QUAKE", shakes=[["shot", "jackpot", 0, "Left ramp"]])
    assert MP.ModeSpec.from_json(spec.to_json()).shakes == [["shot", "jackpot", 0, "Left ramp"]]
    ex = dict(MP.examples_for(MP.profile("godzilla_le_1_16")))["MECHAGODZILLA"]
    assert ex.shakes == [["start", "multiball_start", 0, ""], ["shot", "jackpot", 0, "Godzilla target"]]
    assert MP.validate(ex) == []


# ---- blocks --------------------------------------------------------------------------------
SHAKER = {"shakes": ["hit", "big_hit", "jackpot", "rumble", "multiball_start"], "max": [1000, 1000, 5000, 5000]}


def _prog():
    return {"name": "QUAKE", "seconds": 30, "vars": [], "scripts": [
        {"hat": {"kind": "mode_start"}, "do": [{"op": "shake", "ms": {"k": "num", "v": 800}, "strength": "hard"}]},
        {"hat": {"kind": "shot", "shot": "Left ramp", "when": "running"},
         "do": [{"op": "shake_game", "shake": "jackpot"}]},
        {"hat": {"kind": "mode_end"}, "do": [{"op": "shake", "ms": {"k": "num", "v": 1000}, "strength": "soft"}]}]}


def test_blocks_shake_and_are_refused_where_they_cannot():
    prog = _prog()
    assert BM.problems(prog, shaker=SHAKER) == []
    assert BM.problems(prog, shaker=False) == [
        "Script %d shakes the cabinet, which a mode cannot do on this card's game." % n for n in (1, 2, 3)]
    bad = {**prog, "scripts": [{"hat": {"kind": "mode_start"}, "do": [
        {"op": "shake", "ms": {"k": "num", "v": 3000}, "strength": "hard"},
        {"op": "shake", "ms": {"k": "num", "v": 300}, "strength": "wild"},
        {"op": "shake_game", "shake": "earthquake"}, {"op": "shake_game", "shake": ""}]}]}
    got = BM.problems(bad, shaker=SHAKER)
    assert "Script 1 shakes the cabinet with a hard shake for 100 to 1000 ms." in got
    assert "Script 1 shakes the cabinet: hard, strong, medium or soft." in got
    assert "Script 1 plays the game's earthquake shake, which this card's game does not have." in got
    assert "Script 1 plays none of the game's shakes." in got
    c = BM.to_c(BM.normalize(prog), "quake")
    assert "shake((800LL), 0);" in c and 'shake_game("jackpot");' in c and "shake((1000LL), 3);" in c
    assert "else if (ending) pm_shake_outlast();" in c          # a shake in When the mode ends runs out


def test_the_blocks_c_builds_with_build_mode_sh(tmp_path):
    if os.name == "nt":
        pytest.skip("build_mode.sh runs under bash with arm-linux-gnueabihf-gcc (WSL or Linux)")
    if not shutil.which("bash") or not shutil.which("arm-linux-gnueabihf-gcc"):
        pytest.skip("no arm-linux-gnueabihf-gcc here")
    (tmp_path / "quake.c").write_text(BM.to_c(BM.normalize(_prog()), "quake"), encoding="utf-8")
    r = subprocess.run(["bash", str(SDK / "build_mode.sh"), "-o", str(tmp_path / "mode.so"),
                        str(tmp_path / "quake.c"), str(SDK / "mode_file.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "warning" not in (r.stdout + r.stderr).lower()


def test_the_docs_name_the_key_the_field_and_the_calls():
    doc = (SDK / "MODE_PARAMETERS.md").read_text(encoding="utf-8")
    for name in ("shake", "shakes", "pm_shake", "pm_shake_game", "pm_shake_outlast", "PM_CAN_SHAKER"):
        assert re.search(r"`%s(?:[ (][^`]*)?`" % re.escape(name), doc), name
    assert "## The shaker (Godzilla Premium/LE, PAD-414)" in (SDK / "MODE_SDK.md").read_text(encoding="utf-8")
    assert "| Shake the cabinet |" in (SDK / "MODE_LIMITS.md").read_text(encoding="utf-8")


# ---- the Modes tab -------------------------------------------------------------------------
def test_the_tab_offers_it_on_the_premium_le_and_greys_it_on_a_pro(tmp_path):
    import json
    from tests.test_webui_modes import _card_project, _project, _wait
    from tests.webui_harness import web_app
    from pinball_decryptor.core import preview
    old = preview.enabled
    preview.enabled = lambda feature: feature == "modes"
    try:
        proj = _card_project(tmp_path / "le", "godzilla_le-1_16_0.raw")
        with web_app(tmp_path, mfr="stern") as w:
            _project(w, proj)
            slug = w.call("modes.new")
            st = w.state("modes")
            assert st["form"]["shake_on_start"] is False and not st["dis"]["shaker"]
            assert "game:jackpot" in [o["value"] for o in st["profile"]["shakes"]]
            assert st["profile"]["shake_max"] == [1000, 1000, 5000, 5000]
            path = proj / "modes" / slug / "mode.json"
            w.call("ui.set", "modes", "f:shake_on_start", True)
            w.call("ui.set", "modes", "f:shake_what_start", "game:multiball_start")
            assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("shakes")
                         == [["start", "multiball_start", 0, ""]])
            w.call("ui.set", "modes", "f:shake_on_end", True)
            w.call("ui.set", "modes", "f:shake_what_end", "hard")
            w.call("ui.set", "modes", "f:shake_s_end", "3")
            assert _wait(w, lambda: "A hard shake lasts 0.1 to 1 seconds" in w.state("modes")["status"])
            assert w.state("modes")["fix_pages"] == ["mode"]
            w.call("ui.set", "modes", "f:shake_s_end", "0.8")
            assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("shakes")
                         == [["start", "multiball_start", 0, ""], ["end", 800, 0, ""]])
            assert _wait(w, lambda: w.state("modes")["status"] == "Ready to build.")
            w.call("modes.new_blocks_mode", "Quake")
            ch = w.state("modes")["code"]["blocks"]["choices"]
            assert ch["shaker_off"] == "" and "jackpot" in [s["name"] for s in ch["shakes"]]
        proj = _card_project(tmp_path / "pro", "godzilla_pro-1_16_0.raw")
        with web_app(tmp_path, mfr="stern") as w:
            _project(w, proj)
            w.call("modes.new")
            st = w.state("modes")
            assert st["dis"]["shaker"] and "Godzilla Pro 1.16" in st["reasons"]["shaker"]
            w.call("modes.new_blocks_mode", "Quake")
            ch = w.state("modes")["code"]["blocks"]["choices"]
            assert ch["shaker_off"].startswith("Not on this game: The app has not found how Godzilla Pro 1.16 shakes")
    finally:
        preview.enabled = old
