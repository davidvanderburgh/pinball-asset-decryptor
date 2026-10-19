"""PAD-621 (luvthatapex, James Bond LE): "when mini wizard modes are started at the right ramp, the up post holds the ball
so the player can see the beginning mode movie clip, then ball is released, timer starts". A mode of ours may do the
same: James Bond LE/Pro 1.06's right return up post is a held coil (the game's own command on it, its object taken
while it holds), and a hold may make the mode's clock wait until it lets go (`coil_hold <name> <ms> wait`; the
blocks' Hold "its clock waits until it lets go"). Emulator-proven on the stock LE and Pro cards
(mode_project.HELD_COILS_PROVEN).

What is worth failing on:
  * THE POST COMES DOWN WHEN LET GO: it is a Device-framework object that its own update OFFs and its own tick raises
    (a pending raise, 1875 ticks, when the game wants the ball held) unless a process controls it; a hold takes it,
    and clears that countdown and pending raise before giving it back, so the give's own update lowers it.
  * THE CLOCK WAITS ONLY WHILE THE HOLD HOLDS, and never at a challenge's start (that ball is in the shooter lane).
  * THE PORT LINES ARE THE GAME PROGRAM'S: the framework's take and give, the object its static initializer builds,
    the adjustments and the flag by the program's own names.
"""
import os
import pathlib
import re
import struct

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import mode_project as MP

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
BOND = ("james_bond_le-1.06", "james_bond_pro-1.06")


def _lift(src, signature):
    i = src.index(signature)
    while src.find(";", i) < src.find("{", i):
        i = src.index(signature, i + 1)
    depth = 0
    for k in range(src.index("{", i), len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError("unbalanced braces after " + signature)


# ---- the runtime -------------------------------------------------------------------------------
def test_a_post_with_a_countdown_of_its_own_is_lowered_when_given_back():
    src = RUNTIME.read_text(encoding="utf-8")
    clear = _lift(src, "static void coil_clear_countdown(const struct held_coil *c)\n{")
    assert '"%s_left"' in clear and '"%s_pending"' in clear
    proc = _lift(src, "static void magnet_proc(")
    assert "int has_obj = coil_controlled(c);" in proc
    give = proc[proc.index("coil_clear_countdown(c);"):]
    assert give.index("coil_clear_countdown(c);") < give.index('coil_call(c, "give")')


def test_a_long_hold_runs_to_the_games_own_longest_only():
    src = RUNTIME.read_text(encoding="utf-8")
    hold = _lift(src, "int pm_coil_hold(")
    assert hold.index("magnet_plan(ms, coil_drive(c, 0)") < hold.index("long_hold(c, ms, &cmd);")
    long = _lift(src, "static void long_hold(")
    assert "if (top <= MAGNET_MAX_MS || ms <= MAGNET_MAX_MS) return;" in long and "if (ms > top) ms = top;" in long
    assert "cmd->hold_ms = ms - cmd->draw_ms;" in long


def test_the_games_no_hold_flag_refuses_a_hold():
    src = RUNTIME.read_text(encoding="utf-8")
    no = _lift(src, "static const char *coil_no_hold(")
    assert '"%s_no_hold_flag"' in no and "game_flag((unsigned)id) != 1" in no
    hold = _lift(src, "int pm_coil_hold(")
    assert hold.index("magnet_refusal(") < hold.index("coil_no_hold(c)") < hold.index("magnet_plan(")


def test_the_interpreter_waits_its_clock_for_a_wait_hold():
    src = (SDK / "mode_file.c").read_text(encoding="utf-8")
    line = _lift(src, "static int coil_line(")
    assert 'cfg.coil_wait[n] = key_is(a, "wait") != 0;' in line
    at = _lift(src, "static void coils_at(")
    assert "if (held && cfg.coil_wait[i]) run.clock_wait = i + 1;" in at
    assert at.index("run.at_ball_start") < at.index("pm_coil_hold(")       # a challenge's ball: no hold at all
    waits = _lift(src, "static int clock_waits(")
    assert "pm_coil_holding(cfg.coil_name[run.clock_wait - 1])" in waits
    tick = _lift(src, "static void on_tick(")
    assert tick.index("if (clock_waits(M)) return;") < tick.index("if (run.ticks_left) run.ticks_left--;")
    start = _lift(src, "static void mode_start(")
    assert start.index("run.clock_wait = 0;") < start.index('run.at_ball_start = name_is(why, "challenge pick");') \
        < start.index("coils_at(M, 0);")


# ---- the ports and the game programs ---------------------------------------------------------------
@pytest.mark.parametrize("key", BOND)
def test_the_bond_ports_name_the_post(key):
    port = MP.read_port(str(SDK / "ports" / ("%s.port" % key)))
    assert port["text"]["held_coils"].split()[-1] == "right_return_up"
    adj = 183 if "_le" in key else 178
    assert port["text"]["right_return_up_drive"].split("#")[0].split() == ["8", "7", "255", "64", "a%d" % adj]
    v = port["value"]
    assert (v["right_return_up_ctl"], v["right_return_up_devoff"], v["right_return_up_off_slot"]) == (0x10, 18, 3)
    assert (v["right_return_up_left"], v["right_return_up_pending"]) == (0x20, 0x24)
    assert v["right_return_up_max_ms"] == MP.COIL_LONGEST_MS and v["right_return_up_no_hold_flag"] == 166
    assert {"right_return_up_take", "right_return_up_give"} <= set(port["site"])
    assert "coil_take" not in port["site"]                   # the gate keeps its own route: only the post is taken


def _elf(key):
    return next((p for p in (os.environ.get("PAD_BOND_%s_106_ELF" % key.split("_")[2].split("-")[0].upper(), ""),
                             r"C:\tmp\PAD-420\elf\%s.elf" % key, "/mnt/c/tmp/PAD-420/elf/%s.elf" % key)
                 if p and os.path.isfile(p)), None)


@pytest.mark.parametrize("key", BOND)
def test_the_post_lines_match_the_game_program_when_it_is_here(key):
    """The framework's take (free when +0x10 is 0, then the current process there) and give (+0x10 cleared); the object
    the one BottomLaneUpPost's static initializer builds; AD_BOTTOM_LANE_UP_POST_POWER and flag 166
    FG_MODES_DO_NOT_HOLD_BALL by the program's own name tables."""
    elf = _elf(key)
    if not elf:
        pytest.skip("%s's game program is not here" % key)
    b = open(elf, "rb").read()
    port = MP.read_port(str(SDK / "ports" / ("%s.port" % key)))

    def word(addr):                         # the program's first PT_LOAD is at 0x8000, file offset 0
        return struct.unpack_from("<I", b, addr - 0x8000)[0]

    def refs(value):
        return [m.start() + 0x8000 for m in re.finditer(re.escape(struct.pack("<I", value)), b) if m.start() % 4 == 0]

    def cstr(addr):
        o = addr - 0x8000
        return b[o:b.index(b"\0", o)].decode("latin1")

    for site in ("right_return_up_take", "right_return_up_give"):
        addr, w0, w1 = port["site"][site]
        assert (word(addr), word(addr + 4)) == (w0, w1), site
    take, give = port["site"]["right_return_up_take"][0], port["site"]["right_return_up_give"][0]
    assert 0xe1d031b0 in [word(a) for a in range(take - 0x5c, take, 4)]      # ldrh r3, [r0, #0x10]: free?
    assert word(give + 0x10) == 0xe1c051b0                                    # strh r5, [r0, #0x10]: given back
    # the object: BottomLaneUpPost's static initializer builds it at base + 0x70 (`movw/movt r4, base` ...
    # `str r3, [r4, #0x70]`, r3 the class's vtable from its literal pool)
    name = b.index(b"16BottomLaneUpPost\0") + 0x8000
    vt = refs(refs(name)[0] - 4)[0] + 4
    base = port["data"]["right_return_up_obj"] - 0x70
    movw = 0xe3004000 | ((base & 0xffff) >> 12 << 16) | (base & 0xfff)
    movt = 0xe3404000 | ((base >> 16) >> 12 << 16) | ((base >> 16) & 0xfff)
    assert any(all(w in [word(a) for a in range(lit - 0x200, lit, 4)] for w in (movw, movt, 0xe5843070))
               for lit in refs(vt))
    assert word(word(vt + 4 * 3)) == 0xe1d000b4                               # v[3]: ldrh r0, [r0, #4] (its adj)

    def table_index(entry_name):
        slot = refs(b.index(entry_name.encode() + b"\0") + 0x8000)[0]
        first = slot
        while cstr(word(first - 4)).startswith(entry_name[:3]):
            first -= 4
        return (slot - first) // 4

    assert table_index("AD_BOTTOM_LANE_UP_POST_POWER") == int(port["text"]["right_return_up_drive"].split()[4][1:])
    assert table_index("FG_MODES_DO_NOT_HOLD_BALL") == port["value"]["right_return_up_no_hold_flag"]


# ---- the app ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("key", BOND)
def test_the_profile_offers_the_post_up_to_the_games_own_14_s(key):
    p = MP.profile(key.replace("-", "_").replace(".", "_"))
    assert ("right_return_up", "Right return up post") in p.held_coils
    assert MP.coil_max_ms(p, "right_return_up") == 14000 and MP.coil_max_ms(p, "gate") == MP.COIL_MAX_MS
    spec = MP.blank_spec(p, name="POST")
    spec.coil_holds = [["right_return_up", 14000, "", True]]
    assert MP.validate_coils(spec, p) == []
    spec.coil_holds = [["right_return_up", 14001, ""]]
    assert any("The Right return up post holds 0.1 to 14 seconds." in x for x in MP.validate_coils(spec, p))
    spec.coil_holds = [["gate", 6000, ""]]
    assert any("holds 0.1 to 5 seconds." in x for x in MP.validate_coils(spec, p))


def test_a_wait_row_writes_the_wait_word_and_round_trips(tmp_path):
    p = MP.profile("james_bond_le_1_06")
    spec = MP.blank_spec(p, name="POST")
    spec.coil_holds = [["right_return_up", 6000, "", True], ["gate", 2000, ""]]
    assert MP.coil_lines(spec, p) == ["coil_hold      right_return_up 6000 wait", "coil_hold      gate 2000"]
    project = tmp_path / "proj"
    project.mkdir()
    slug, _ = MP.new_mode(str(project), spec=MP.ModeSpec(name="POST", coil_holds=spec.coil_holds))
    assert MP.load(str(project / "modes" / slug / "mode.json")).coil_holds == spec.coil_holds


def _post_prog(clock="wait", challenge=False):
    start = {"hat": {"kind": "challenge", "challenge": "Crab Key"}} if challenge else \
        {"hat": {"kind": "shot", "shot": "Right ramp exit", "when": "idle"}}
    return {"name": "POST", "seconds": 30, "vars": [], "game_modes": "block", "scripts": [
        dict(start, do=[{"op": "start_mode"}]),
        {"hat": {"kind": "mode_start"}, "do": [
            {"op": "hold", "what": "right_return_up", "ms": {"k": "num", "v": 6000}, "clock": clock}]}]}


def test_the_hold_block_waits_its_clock_and_is_checked():
    mechs = {"right_return_up": "Right return up post"}
    assert BM.problems(_post_prog(), mechs=mechs, hold_caps={"right_return_up": 14000}) == []
    assert "Script 2 holds it: the clock runs or waits." in BM.problems(_post_prog(clock="later"), mechs=mechs)
    long = _post_prog()
    long["scripts"][1]["do"][0]["ms"] = {"k": "num", "v": 9000}
    assert BM.problems(long, mechs=mechs, hold_caps={"right_return_up": 14000}) == []
    assert "Script 2 holds it 100 to 5000 ms." in BM.problems(long, mechs=mechs)      # no longer limit named
    src = BM.to_c(_post_prog(), "post")
    assert 'hold_wait("right_return_up", (6000LL));' in src
    assert "if (RUN_SECONDS && !clock_held()) {" in src
    assert "clock_hold = 0;                   /* PAD-621 */" in src
    assert "if (ms > 14000) ms = 14000;" in src                          # the runtime keeps each one's own limit
    assert 'hold("right_return_up", (6000LL));' in BM.to_c(_post_prog(clock=""), "post")


def test_a_challenge_start_holds_nothing_at_the_shooter_lane():
    src = BM.to_c(_post_prog(challenge=True), "post")
    body = src[src.index("if (challenge_picked) {"):]
    assert body.index("ball_starting = 1;") < body.index("ball_starting = 0;")
    hold = _lift(src, "UNUSED static void hold_wait(")
    assert hold.index("if (ball_starting)") < hold.index("pm_coil_hold(")


def test_the_docs_name_the_wait_and_the_post():
    doc = (SDK / "MODE_PARAMETERS.md").read_text(encoding="utf-8")
    assert "`<name> <ms> [mask] [wait]`" in doc
    sdk = (SDK / "MODE_SDK.md").read_text(encoding="utf-8")
    assert "`value <name>_pending`" in sdk and "coil_hold right_return_up" in sdk


# ---- the interpreter on the host (Linux: the harness needs an ELF linker) ----------------------------------
HOLD_EXTRA = r"""
static int holding;
static int (*ch_claimed[32])(unsigned);
int pm_coil_hold(const char *n, unsigned ms) { printf("HOLD %s %u\n", n, ms); holding = 1; return 1; }
int pm_coil_holding(const char *n) { return holding; }
int pm_challenge_claim(unsigned slot, int (*f)(unsigned)) { if (slot >= 5) return 0; ch_claimed[slot] = f; return 1; }
void pm_challenge_release(unsigned slot) { if (slot < 32) ch_claimed[slot] = 0; }
const char *pm_challenge_name(unsigned slot) { return slot < 5 ? "Ahoy Mr. Bond" : 0; }
"""


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    import subprocess
    from tests import test_spike2_mode_roster as R
    cc = R._cc()
    d = tmp_path_factory.mktemp("posthold")
    text = R.HARNESS.replace("int main(int argc, char **argv)", HOLD_EXTRA + "\nint main(int argc, char **argv)")
    text = text.replace('''        } else if (!strcmp(argv[k], "ball_end")) {''', '''        } else if (!strcmp(argv[k], "letgo")) {
            holding = 0;
            printf("LETGO\\n");
        } else if (!strcmp(argv[k], "chpick")) {
            unsigned s = (unsigned)atoi(argv[++k]);
            printf("CHPICK %u -> %d\\n", s, ch_claimed[s] ? ch_claimed[s](s) : -1);
        } else if (!strcmp(argv[k], "ball_end")) {''')
    assert "letgo" in text and "chpick" in text
    (d / "harness.c").write_text(text)
    stubs, _names = R.weak_stubs((SDK / "pad_mode.h").read_text(encoding="utf-8"))
    (d / "weak_stubs.c").write_text(stubs)
    for std in ("-std=gnu2x", "-std=gnu17"):
        r = subprocess.run([cc, std, "-w", "-I", str(SDK), "-c", "-o", str(d / "weak_stubs.o"), str(d / "weak_stubs.c")],
                           capture_output=True, text=True)
        if r.returncode == 0:
            break
    assert r.returncode == 0, r.stderr
    exe = d / "harness"
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wno-unused-parameter", "-I", str(SDK), "-o", str(exe),
                        str(d / "harness.c"), str(SDK / "mode_file.c"), str(d / "weak_stubs.o")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return exe


def _run(harness, tmp_path, cfg, *args):
    from tests import test_spike2_mode_roster as R
    return R._run(harness, tmp_path, cfg, *args)


POST = "name POST\ntrigger 0x4 1\nseconds 10\nshots 0x1\naward 1000\ncoil_hold right_return_up 6000%s\n"


def test_a_wait_hold_stops_the_clock_until_it_lets_go(harness, tmp_path):
    out = _run(harness, tmp_path, POST % " wait", "shot", "0x4", "tick", "900", "letgo", "tick", "900")
    assert "HOLD right_return_up 6000" in out
    assert "POST: right_return_up 6000 ms as it starts - holding, its clock waits until it lets go" in out
    held, after = out.split("LETGO", 1)
    assert "POST END" not in held                               # 15 s held: the 10 s clock never moved
    assert after.index("POST: the right_return_up let go - its clock runs, 10 s") < after.index("POST END (time ran out)")


def test_without_wait_the_clock_runs_while_it_holds(harness, tmp_path):
    out = _run(harness, tmp_path, POST % "", "shot", "0x4", "tick", "900")
    assert "HOLD right_return_up 6000" in out and "its clock waits" not in out
    assert "POST END (time ran out)" in out


def test_a_challenge_ball_is_not_held(harness, tmp_path):
    cfg = "name POST\nchallenge 1\nseconds 10\nshots 0x1\naward 1000\ncoil_hold right_return_up 6000 wait\n"
    out = _run(harness, tmp_path, cfg, "chpick", "1", "tick", "2", "tick", "700")
    assert "POST START (challenge pick)" in out and "HOLD " not in out
    assert "right_return_up - no hold, it started as the ball starts (the ball is in the shooter lane)" in out
    assert "POST END (time ran out)" in out


# ---- the blocks on the desk harness (Linux) ---------------------------------------------------------------
def _desk_prog(clock):
    return {"name": "POST", "seconds": 10, "vars": [], "game_modes": "stack", "scripts": [
        {"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "mode_start"}, "do": [
            {"op": "hold", "what": "right_return_up", "ms": {"k": "num", "v": 6000}, "clock": clock}]}]}


def test_the_blocks_clock_waits_for_the_hold_on_the_desk(tmp_path):
    from tests import test_stern_block_modes as T
    out = T.play(tmp_path, _desk_prog("wait"), "shot", "Left ramp", "secs", 12)
    assert "HOLD right_return_up 6000 ms" in out and "hold right_return_up: its clock waits until it lets go" in out
    assert "hold right_return_up: let go - its clock runs" in out
    assert "END (time ran out)" not in out                         # 12 s on: 6 held, 6 of its 10 run
    out = T.play(tmp_path, _desk_prog("wait"), "shot", "Left ramp", "secs", 17)
    assert "END (time ran out)" in out
    out = T.play(tmp_path, _desk_prog(""), "shot", "Left ramp", "secs", 12)  # no wait: the 10 s ran under the hold
    assert "END (time ran out)" in out and "its clock waits" not in out
