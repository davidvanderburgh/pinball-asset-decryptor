"""PAD-392: a mode turns Godzilla Premium/LE's shield targets toward the player - the runtime's limits, its
keeping and its put-back, the mode file's line, the model, the tab and the blocks, at the desk. Emulator-proven
on the stock Premium/LE 1.16 card (MODE_SDK.md "The shield platform"; ``mode_project.SHIELD_PROVEN``).

What is worth failing on:
  * THE LIMITS ARE THE RUNTIME'S: only the running mode, in a game, never while one of the game's own modes
    or multiballs runs, 1.5 s between moves, 12 a minute - in that order of reasons.
  * THE GAME IS NEVER FOUGHT: the platform is kept only while the game's own shield feature (the port's
    `text shield_rule`) sees no shots; while it counts, the game turns the platform back about 2 s after every
    move (emulator), and the mode turns it once. So the app refuses a mode that asks for the shield while
    the game's modes may start or with that feature kept counting.
  * EVERY END PUTS IT BACK: the mode, the ball, the game or a tilt - unless the game has turned it since.
  * THE MOVE IS THE GAME'S OWN: the motor's go-to, called from the move and the put-back only.
"""
import os
import pathlib
import re
import shutil
import subprocess
from dataclasses import replace

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import mode_project as MP

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
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


# ---- the runtime ---------------------------------------------------------------------------
@needs_cc
def test_the_refusals_and_their_order(tmp_path):
    src = _rt()
    code = "#include <stdio.h>\n" + "\n".join(re.findall(r"^#define SHIELD_\w+ .*$", src, re.M)) + "\n" + \
        _lift(src, "static const char *shield_refusal(") + r"""
static unsigned long st[SHIELD_PER_MIN];
static void t(const char *label, int run, int game, int theirs, unsigned long last, unsigned long now)
{
    const char *w = shield_refusal(run, game, theirs, last, now, st);
    printf("%s|%s\n", label, w ? w : "-");
}
int main(void)
{
    unsigned i;
    t("ok", 1, 1, 0, 0, 100000);
    t("not_running", 0, 0, 1, 99999, 100000);
    t("no_game", 1, 0, 1, 99999, 100000);
    t("theirs", 1, 1, 1, 99999, 100000);
    t("cool_1499", 1, 1, 0, 98501, 100000);
    t("cool_1500", 1, 1, 0, 98500, 100000);
    for (i = 0; i < SHIELD_PER_MIN; i++) st[i] = 50000 + i * 4000;
    t("twelve_in_a_minute", 1, 1, 0, 0, 100000);
    t("first_now_old", 1, 1, 0, 0, 110001);
    return 0;
}
"""
    (tmp_path / "t.c").write_text(code)
    r = subprocess.run([CC, "-std=gnu17", "-Wall", "-o", str(tmp_path / "t"), str(tmp_path / "t.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = subprocess.run([str(tmp_path / "t")], capture_output=True, text=True, timeout=30).stdout
    rows = dict(line.split("|", 1) for line in out.strip().splitlines())
    assert rows["ok"] == "-"
    assert rows["not_running"].startswith("only the running mode")
    assert rows["no_game"].startswith("no game is being played")
    assert rows["theirs"].startswith("one of the game's own modes or multiballs is running")
    assert rows["cool_1499"].startswith("the last move started less than 1.5 s ago")
    assert rows["cool_1500"] == "-"
    assert rows["twelve_in_a_minute"].startswith("twelve moves in the last minute")
    assert rows["first_now_old"] == "-"


def test_the_move_is_the_games_own_and_put_back_on_every_end():
    src = _rt()
    calls = re.findall(r'fn\("shield_move"\)\)\(obj, ', src)
    assert len(calls) == 2, "the move and the put-back - nothing else drives the motor"
    assert "shield_go(obj, where)" in _lift(src, "int pm_shield(int where)")
    assert 'shield_let_go("the mode ended")' in _lift(src, "void pm_end(void)")
    assert 'shield_let_go("the ball ended")' in _lift(src, "static void on_ball_end(")
    assert "shield_tick();" in _lift(src, "static void on_tick(")
    tick = _lift(src, "static void shield_tick(")
    for why in ("the game ended or tilted", "no mode is running"):
        assert why in tick
    back = _lift(src, "static void shield_putback(")
    assert "of its own" in back and "pm_aside()" in back


def test_it_is_kept_only_while_the_games_shield_feature_sees_no_shots():
    src = _rt()
    counts = _lift(src, "static int shield_rule_counts(")
    assert 'pm_port_text("shield_rule")' in counts and "block_rules_keep" in counts and "block_owner" in counts
    tick = _lift(src, "static void shield_tick(")
    assert tick.index("shield_rule_counts()") < tick.index("shield_go(obj, shd.keep)")
    assert "SHIELD_BACK_MS" in tick


def test_the_games_return_to_rest_waits_only_while_the_mode_has_the_shield():
    """PAD-409: the motor's own pass (every ~3 s it sends the platform to the game's resting place) is skipped
    only for the shield motor, only while a mode of ours has moved it and runs, never while one of the game's
    modes or multiballs has the stage; letting go ends the hold at once, before the put-back."""
    src = _rt()
    veto = _lift(src, "static int shield_update_veto(")
    for need in ("shd.hold", "r[0] != obj", "!running", "pm_aside()"):
        assert need in veto, need
    assert "hook_veto(fn(\"shield_update\"), shield_update_veto)" in _lift(src, "static void shield_arm(")
    assert "shd.hold = 1;" in _lift(src, "static unsigned shield_go(")
    let_go = _lift(src, "static void shield_let_go(")
    assert let_go.index("shd.hold = 0;") < let_go.index("putback_why = why")
    text = (SDK / "ports" / "godzilla_le-1.16.port").read_text(encoding="utf-8")
    assert re.search(r"^site shield_update\s+0x001da978 0xe301316a 0xe340307d\s*$", text, re.M)


@pytest.mark.parametrize("elf", [os.environ.get("PAD_GODZILLA_LE_116_GAME", ""), r"C:\tmp\gzle116_stock.elf",
                                 "/mnt/c/tmp/gzle116_stock.elf"])
def test_the_hooked_pass_is_the_shield_motors_own_in_the_game_program(elf):
    """The site is slot 0 of the vtable the port checks the motor's object against, and its words are the game's."""
    import struct
    if not elf or not os.path.isfile(elf):
        pytest.skip("game program not present: %s" % elf)
    b = open(elf, "rb").read()
    phoff, phnum = struct.unpack_from("<I", b, 0x1c)[0], struct.unpack_from("<H", b, 0x2c)[0]
    segs = [struct.unpack_from("<8I", b, phoff + i * 32) for i in range(phnum)]

    def word(va):
        for t, off, v, _pa, fs, _ms, _fl, _al in segs:
            if t == 1 and v <= va < v + fs:
                return struct.unpack_from("<I", b, off + va - v)[0]
        raise AssertionError(hex(va))
    text = (SDK / "ports" / "godzilla_le-1.16.port").read_text(encoding="utf-8")
    vptr = int(re.search(r"^value shield_motor_vptr\s+(0x[0-9a-f]+)", text, re.M).group(1), 16)
    assert word(vptr) == 0x1da978
    assert (word(0x1da978), word(0x1da97c)) == (0xe301316a, 0xe340307d)


def test_the_port_names_the_feature_that_turns_it_back():
    text = (SDK / "ports" / "godzilla_le-1.16.port").read_text(encoding="utf-8")
    rule = re.search(r"^text shield_rule\s+(.+?)\s*$", text, re.M).group(1)
    assert re.search(r"^text block_rule_name_\d+\s+%s\s*$" % re.escape(rule), text, re.M), rule


# ---- the mode file -------------------------------------------------------------------------
def _harness(tmp_path_factory):
    from tests.test_spike2_mode_aside import BLOCK_STUBS, _build
    anchor = next(new for _old, new in BLOCK_STUBS if "pm_block_game_modes" in new)
    tail = anchor[anchor.index("int pm_block_game_modes"):]
    stubs = BLOCK_STUBS + [(tail, tail + "\nint pm_shield_keep(int where) "
                            "{ printf(\"SHIELDKEEP %d at %lu\\n\", where, now_ms); return 1; }")]
    return _build(tmp_path_factory, stubs, "shield")


@pytest.fixture(scope="module")
def harness_shield(tmp_path_factory):
    return _harness(tmp_path_factory)


def _run(harness, tmp_path, cfg, *args):
    from tests.test_spike2_mode_aside import _run as run
    return run(harness, tmp_path, cfg, *args)


RUSH = ("name RUSH\ntrigger 0x08000000 1\nseconds 20\nshots 0x00300000\naward 1000000\n"
        "screen_node PadMode_rush_Screen\nscreen_text PadMode_rush_Screen.PadMode_rush_Screen_Words\n")


def test_shield_toward_turns_it_once_the_starting_ball_is_clear(harness_shield, tmp_path):
    out = _run(harness_shield, tmp_path, RUSH + "shield toward\n", "shot", "0x08000000", "tick", "60")
    assert "the shield targets face the player while it runs" in out and "RUSH START" in out
    assert "SHIELDKEEP" not in out                        # ~1 s in: the ball that started it is still near
    out = _run(harness_shield, tmp_path, RUSH + "shield toward\n", "shot", "0x08000000", "tick", "100")
    keep = [ln for ln in out.splitlines() if ln.startswith("SHIELDKEEP")]
    assert len(keep) == 1 and keep[0].startswith("SHIELDKEEP 2 ")
    assert "the shield targets turn toward the player - kept there while it runs" in out


def test_no_line_turns_nothing_and_another_word_is_refused(harness_shield, tmp_path):
    out = _run(harness_shield, tmp_path, RUSH, "shot", "0x08000000", "tick", "200")
    assert "SHIELDKEEP" not in out
    out = _run(harness_shield, tmp_path, RUSH + "shield sideways\n", "shot", "0x08000000", "tick", "200")
    assert 'shield takes toward - "sideways" ignored' in out and "SHIELDKEEP" not in out


# ---- the model, the tab, the blocks --------------------------------------------------------
LE = MP.profile_from_port(str(SDK / "ports" / "godzilla_le-1.16.port"))
PRO = MP.profile_from_port(str(SDK / "ports" / "godzilla_pro-1.16.port"))
UNPROVEN = replace(LE, key="godzilla_le_1_16_shieldnot",
                   cannot=tuple(LE.cannot) + MP._shield_cannot("godzilla_le-9.99", LE.label,
                                                                 MP.read_port(str(SDK / "ports" /
                                                                                  "godzilla_le-1.16.port"))))


@pytest.fixture(autouse=True)
def _titles(monkeypatch):
    for p in (LE, PRO, UNPROVEN):
        monkeypatch.setitem(MP.PROFILES, p.key, p)


def _spec(p, **kw):
    spec = MP.blank_spec(p)
    for k, v in kw.items():
        setattr(spec, k, v)
    return spec


def _key(spec, key):
    return [line.split(None, 1)[1] for line in MP.runtime_cfg(spec, "sh").splitlines()
            if line and not line.startswith("#") and line.split(None, 1)[0] == key]


def test_only_the_premium_le_can_and_the_rest_say_why():
    assert LE.can("shield") and LE.shield_rule == "Mechagodzilla Shield"
    assert not PRO.can("shield") and "Godzilla Pro 1.16" in PRO.why_not("shield")
    assert not MP.GODZILLA_PRO_1_15.can("shield")
    assert "has not yet seen a mode of yours turn it in the emulator" in UNPROVEN.why_not("shield")


def test_every_shipped_build_gets_a_verdict_with_the_game_named():
    for key, p in MP.profiles(MP.PORTS_DIR).items():
        if "%s-%s" % (p.game_dir, p.version) in MP.SHIELD_PROVEN:
            assert p.can("shield"), key
        else:
            assert not p.can("shield") and p.label in p.why_not("shield"), key


def test_the_line_and_its_refusals():
    assert MP.ModeSpec().shield is False and not _key(_spec(LE), "shield")
    assert _key(_spec(LE, shield=True), "shield") == ["toward"]
    assert MP.validate_shield(_spec(LE, shield=True), LE) == []
    stack = MP.validate_shield(_spec(LE, shield=True, game_modes="stack"), LE)
    assert stack == ["The shield targets stay toward the player only while the game's modes cannot start: "
                     "otherwise the game's own Mechagodzilla Shield feature turns them back."]
    kept = MP.validate_shield(_spec(LE, shield=True, keep_rules=["Mechagodzilla Shield"]), LE)
    assert kept == ["The shield targets stay toward the player only while Mechagodzilla Shield does not keep "
                    "counting: it turns them back."]
    assert MP.validate_shield(_spec(LE, shield=True, keep_rules=["Bridge"]), LE) == []
    spec = _spec(PRO)
    spec.shield = True
    assert MP.validate_shield(spec, PRO) == ["Turning the shield targets is not on Godzilla Pro 1.16 yet "
                                             "(Mode says why)."]
    assert MP.shield_lines(spec, PRO) == []
    from pinball_decryptor.webui.tabs.modes import problem_pages
    assert problem_pages(stack) == problem_pages(kept) == ["mode"]


def test_a_new_mode_on_a_pro_has_it_off_and_the_field_round_trips(tmp_path):
    assert MP.blank_spec(PRO).shield is False
    project = tmp_path / "proj"
    project.mkdir()
    slug, _ = MP.new_mode(str(project), spec=MP.ModeSpec(name="SHIELDS", shield=True))
    assert MP.load(str(project / "modes" / slug / "mode.json")).shield is True
    assert "shield" in MP.MODEL_FIELDS


def test_blocks_turn_it_and_are_refused_where_the_game_would_turn_it_back():
    prog = {"name": "SHIELDS", "seconds": 30, "vars": [], "scripts": [
        {"hat": {"kind": "mode_start"}, "do": [{"op": "start_mode"}, {"op": "shield", "where": "toward"}]},
        {"hat": {"kind": "seconds_left", "seconds": 10}, "do": [{"op": "shield", "where": "leave"}]}]}
    assert BM.problems(prog, shield="Mechagodzilla Shield") == []
    assert BM.problems(dict(prog, game_modes="stack"), shield="Mechagodzilla Shield") == [
        "The shield targets stay turned only while the game's modes cannot start: otherwise the game's own "
        "Mechagodzilla Shield feature turns them back."]
    assert BM.problems(dict(prog, keep_rules=["Mechagodzilla Shield"]), shield="Mechagodzilla Shield") == [
        "The shield targets stay turned only while Mechagodzilla Shield does not keep counting: it turns them back."]
    assert BM.problems(prog, shield=False) == [
        "Script 1 turns the shield targets, which a mode cannot do on this card's game.",
        "Script 2 turns the shield targets, which a mode cannot do on this card's game."]
    bad = {**prog, "scripts": [{"hat": {"kind": "mode_start"}, "do": [{"op": "shield", "where": "up"}]}]}
    assert "Script 1 turns the shield targets: toward the player, away, or where they are." in BM.problems(bad)
    c = BM.to_c(BM.normalize(prog), "shields")
    assert "shield(PM_SHIELD_TOWARD);" in c and "shield(0);" in c and "pm_shield_keep(where)" in c


def test_the_blocks_c_builds_with_build_mode_sh(tmp_path):
    if os.name == "nt":
        pytest.skip("build_mode.sh runs under bash with arm-linux-gnueabihf-gcc (WSL or Linux)")
    if not shutil.which("bash") or not shutil.which("arm-linux-gnueabihf-gcc"):
        pytest.skip("no arm-linux-gnueabihf-gcc here")
    prog = {"name": "SHIELDS", "seconds": 30, "vars": [], "scripts": [
        {"hat": {"kind": "mode_start"}, "do": [{"op": "shield", "where": "toward"}]},
        {"hat": {"kind": "seconds_left", "seconds": 10}, "do": [{"op": "shield", "where": "away"}]}]}
    (tmp_path / "shields.c").write_text(BM.to_c(BM.normalize(prog), "shields"), encoding="utf-8")
    r = subprocess.run(["bash", str(SDK / "build_mode.sh"), "-o", str(tmp_path / "mode.so"),
                        str(tmp_path / "shields.c"), str(SDK / "mode_file.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "warning" not in (r.stdout + r.stderr).lower()


def test_the_docs_name_the_key_the_field_and_the_call():
    doc = (SDK / "MODE_PARAMETERS.md").read_text(encoding="utf-8")
    for name in ("shield", "pm_shield_keep"):
        assert re.search(r"`%s(?:[ (][^`]*)?`" % re.escape(name), doc), name
    sdk = (SDK / "MODE_SDK.md").read_text(encoding="utf-8")
    assert "**The limits, and keeping it turned (PAD-392).**" in sdk
    limits = (SDK / "MODE_LIMITS.md").read_text(encoding="utf-8")
    assert "| Turn the shield targets toward the player |" in limits and "Turn the shield or move" not in limits


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
            assert st["form"]["shield"] is False and not st["dis"]["shield"] and "shield" not in st["reasons"]
            assert st["profile"]["shield_rule"] == "Mechagodzilla Shield"
            path = proj / "modes" / slug / "mode.json"
            w.call("ui.set", "modes", "f:shield", True)
            assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("shield") is True)
            assert _wait(w, lambda: w.state("modes")["status"] == "Ready to build.")
            w.call("ui.set", "modes", "f:game_modes", "stack")
            assert _wait(w, lambda: "the game's own Mechagodzilla Shield feature turns them back"
                         in w.state("modes")["status"])
            assert w.state("modes")["fix_pages"] == ["mode"]
            w.call("modes.new_blocks_mode", "Shields")
            ch = w.state("modes")["code"]["blocks"]["choices"]
            assert ch["shield_off"] == "" and ch["shield_feature"] == "Mechagodzilla Shield"
        proj = _card_project(tmp_path / "pro", "godzilla_pro-1_16_0.raw")
        with web_app(tmp_path, mfr="stern") as w:
            _project(w, proj)
            w.call("modes.new")
            st = w.state("modes")
            assert st["dis"]["shield"] and "Godzilla Pro 1.16" in st["reasons"]["shield"]
            w.call("modes.new_blocks_mode", "Shields")
            ch = w.state("modes")["code"]["blocks"]["choices"]
            assert ch["shield_off"].startswith("Not on this game: The app has not found a shield platform on Godzilla Pro")
    finally:
        preview.enabled = old
