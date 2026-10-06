"""godzilla_le's building: a stepper the node board runs, and a mode's move of it (PAD-393).

hwshim.c's stepper model: the game configures the building's stepper (cmd 32, node 10 motor 0),
homes it (cmd 34), moves it by RELATIVE steps (cmd 31) and polls its status (cmd 38+motor: flags
0x02 moving, 0x04 homed). With the zero reply the game re-sent the home ~3600 times a run and never
got as far as a floor. This compiles the REAL functions out of hwshim.c (test_spike2_coil_motor's
extractor) with the switch write and the clock stubbed, and feeds them the frames godzilla_le 1.16
sent in the rig (PAD_NB_TRACE=1, 2026-10-05). What is worth failing on:

  * HOME IS ANSWERED: moving while it travels, then homed at position 0 with the home switch made.
  * A MOVE IS RELATIVE and timed by its distance; the far-end switch closes at the travel.
  * ONLY THE STEPPER FRAME CONFIGURES IT: a cmd 32 of another length, or one that names no inputs,
    leaves the node alone; PAD_STEPPER=0 answers nothing.

And pad_mode_runtime.c's building section (the decisions lifted verbatim, as the magnet test does):
its refusals and their order, the put-back on every end, and the port's sites against the game.
Emulator-proven separately (docs/plans/mode_coils.md, "The building").
"""
import os
import pathlib
import re
import shutil
import struct
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHIM = ROOT / "tools" / "spike2_emu" / "hwshim.c"
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
LE_PORT = SDK / "ports" / "godzilla_le-1.16.port"
LE_ELF = [os.environ.get("PAD_GODZILLA_LE_116_GAME", ""), r"C:\tmp\gzle116_stock.elf",
          "/mnt/c/tmp/gzle116_stock.elf"]

CC = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")
needs_cc = pytest.mark.skipif(not CC, reason="no C compiler on this host")

#: godzilla_le 1.16, node 10, as sent
CONFIG = "8a143200003a2041408800580200000a64007d00008800"    # up = input 0, down = input 1
HOME = "8a043400003e00"
TO_FLOOR0 = "8a1331006aff14050000b80b0000b80b000000002a00"   # -150 (unknown -> floor 0)
DOWN_7500 = "8a133100b4e214050000b80b0000b80b00000000fd00"   # -7500 (floor 0 -> 3)
UP_2500 = "8a133100c40914050000b80b0000b80b00000000c600"     # +2500 (floor 3 -> 2)
STATUS = "8a02383c07"

HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned long now_ms;
static unsigned long pad_ms(void) { return now_ms; }
static void logmsg(const char *s) { (void)s; }
static void motor_say(const char *s) { (void)s; }
static void motor_switch(unsigned nid, int bit, int made)
{
    printf("E %%lu %%u %%d %%d\n", now_ms, nid, bit, made ? 1 : 0);
}

%s

int main(int argc, char **argv)
{
    int a;
    for (a = 1; a < argc; a++) {
        const char *s = argv[a];
        if (s[0] == 't') {                  /* t<ms>:<node> - clock, then tick */
            char *e;
            now_ms = strtoul(s + 1, &e, 10);
            stepper_tick((unsigned)strtoul(e + 1, 0, 10));
        } else if (s[0] == 's') {           /* s<node> - a status poll, motor 0 */
            unsigned char p[5] = {0, 0, 0, 0, 0};
            int r = stepper_status((unsigned)strtoul(s + 1, 0, 10), 0, p);
            printf("S %%lu %%d %%d %%02x\n", now_ms, r, (short)(p[0] | (p[1] << 8)), p[4]);
        } else {                            /* f<hex> - a frame on the wire   */
            unsigned char f[64];
            int n = 0;
            s++;
            while (s[0] && s[1] && n < 64) {
                char t[3]; t[0] = s[0]; t[1] = s[1]; t[2] = 0;
                f[n++] = (unsigned char)strtoul(t, 0, 16);
                s += 2;
            }
            stepper_note(f, n);
        }
    }
    return 0;
}
"""


def _extract(src, name, where):
    m = None
    for c in re.finditer(r"^static [^\n]*\b%s\(" % re.escape(name), src, re.M):
        brace, semi = src.find("{", c.start()), src.find(";", c.start())
        if brace >= 0 and (semi < 0 or brace < semi):
            m = c
            break
    assert m, "%s not found in %s - did it get renamed?" % (name, where)
    depth, j = 0, src.index("{", m.start())
    while j < len(src):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[m.start():j + 1]
        j += 1
    raise AssertionError("unbalanced braces reading %s" % name)


@pytest.fixture(scope="module")
def sbin(tmp_path_factory):
    if not CC:
        pytest.skip("no C compiler on this host")
    src = SHIM.read_text(encoding="utf-8", errors="replace")
    state = re.search(r"^#define NB_STEPPERS.*?^static unsigned char nb_stepper_cfg\[64\];$", src, re.M | re.S)
    assert state, "the stepper state declarations moved - update this test"
    body = "\n".join([state.group(0)] + [_extract(src, n, "hwshim.c") for n in (
        "stepper_on", "stepper_env", "stepper_sps", "stepper_travel", "stepper_pos", "stepper_switches",
        "stepper_tick", "stepper_go", "stepper_note", "stepper_status")])
    d = tmp_path_factory.mktemp("stepper")
    (d / "stepper.c").write_text(HARNESS % body, encoding="utf-8")
    exe = d / ("stepper.exe" if os.name == "nt" else "stepper")
    r = subprocess.run([CC, "-O1", "-Wall", "-o", str(exe), str(d / "stepper.c")], capture_output=True, text=True)
    assert r.returncode == 0, "the shim's stepper did not compile:\n" + r.stderr
    return str(exe)


def _run(sbin, steps, **env):
    e = {k: v for k, v in os.environ.items() if not k.startswith("PAD_STEPPER")}
    e.update(env)
    r = subprocess.run([sbin] + [s if s[0] in "ts" else "f" + s for s in steps],
                       capture_output=True, text=True, env=e)
    assert r.returncode == 0, r.stderr
    edges = [tuple(int(x) for x in l.split()[1:]) for l in r.stdout.splitlines() if l.startswith("E ")]
    status = [(int(l.split()[1]), int(l.split()[2]), int(l.split()[3]), l.split()[4])
              for l in r.stdout.splitlines() if l.startswith("S ")]
    return edges, status


def test_home_is_answered(sbin):
    """It starts between the switches, half the travel out; homing takes 3750 steps at 5000 a second."""
    edges, st = _run(sbin, ["t0:10", CONFIG, "s10", "t100:10", HOME, "s10", "t849:10", "s10", "t850:10", "s10"])
    assert st == [(0, 1, -3750, "00"),          # configured: not homed, not moving
                  (100, 1, -3750, "02"),        # homing
                  (849, 1, -5, "02"),
                  (850, 1, 0, "04")]            # homed at 0
    assert (850, 10, 0, 1) in edges and not any(e[2] == 0 and e[3] == 1 and e[0] < 850 for e in edges)


def test_a_move_is_relative_and_timed(sbin):
    edges, st = _run(sbin, ["t0:10", CONFIG, HOME, "t750:10", TO_FLOOR0, "t780:10", "s10",
                            "t1000:10", DOWN_7500, "t2499:10", "s10", "t2500:10", "s10",
                            "t3000:10", UP_2500, "t3500:10", "s10"])
    assert st == [(780, 1, -150, "04"), (2499, 1, -7645, "06"), (2500, 1, -7650, "04"), (3500, 1, -5150, "04")]
    assert (2500, 10, 1, 1) in edges            # the far end at the travel
    assert (3000, 10, 1, 0) in edges            # and it leaves it on the next move
    assert (750, 10, 0, 0) in edges             # leaving home opens the home switch at once


def test_never_both_switches(sbin):
    edges, _ = _run(sbin, ["t0:10", CONFIG, HOME, "t750:10", DOWN_7500, "t1000:10", "t3000:10", HOME,
                           "t3500:10", "t5000:10"])
    made = set()
    for _ms, _nid, bit, level in edges:
        (made.add if level else made.discard)(bit)
        assert made != {0, 1}


def test_only_the_stepper_frame_configures(sbin):
    short = CONFIG[:-4]                         # a cmd 32 of another length
    no_inputs = CONFIG[:14] + "0000" + CONFIG[18:]
    for cfg in (short, no_inputs):
        edges, st = _run(sbin, ["t0:10", cfg, HOME, "s10", "t5000:10", "s10"])
        assert edges == [] and all(r == 0 for _t, r, _p, _f in st), cfg


def test_switched_off(sbin):
    edges, st = _run(sbin, ["t0:10", CONFIG, HOME, "s10", "t5000:10", "s10"], PAD_STEPPER="0")
    assert edges == [] and all(r == 0 for _t, r, _p, _f in st)


def test_home_down_swaps_the_switches(sbin):
    edges, _ = _run(sbin, ["t0:10", CONFIG, HOME, "t750:10"], PAD_STEPPER_HOME="down")
    assert (750, 10, 1, 1) in edges


# ---- the runtime's building section -------------------------------------------------------------

def _rt():
    return RUNTIME.read_text(encoding="utf-8")


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


@needs_cc
def test_the_refusals_and_their_order(tmp_path):
    src = _rt()
    code = "#include <stdio.h>\n" + "\n".join(re.findall(r"^#define MAGNET_\w+ .*$", src, re.M)) + "\n" + \
        _lift(src, "static const char *building_refusal(") + r"""
static unsigned long st[MAGNET_PER_MIN];
static void t(const char *label, int run, int game, int floor, int dis, int fault, int busy,
              unsigned long last, unsigned long now)
{
    const char *w = building_refusal(run, game, floor, 4, dis, fault, busy, last, now, st);
    printf("%s|%s\n", label, w ? w : "-");
}
int main(void)
{
    unsigned i;
    t("ok", 1, 1, 3, 0, 0, 0, 0, 100000);
    t("not_running", 0, 0, 9, 1, 1, 1, 99999, 100000);
    t("no_game", 1, 0, 9, 1, 1, 1, 99999, 100000);
    t("floor_4", 1, 1, 4, 1, 1, 1, 99999, 100000);
    t("floor_neg", 1, 1, -1, 1, 1, 1, 99999, 100000);
    t("disabled", 1, 1, 0, 1, 1, 1, 99999, 100000);
    t("faulted", 1, 1, 0, 0, 1, 1, 99999, 100000);
    t("busy", 1, 1, 0, 0, 0, 1, 99999, 100000);
    t("cool_2999", 1, 1, 0, 0, 0, 0, 97001, 100000);
    t("cool_3000", 1, 1, 0, 0, 0, 0, 97000, 100000);
    for (i = 0; i < MAGNET_PER_MIN; i++) st[i] = 50000 + i * 4000;
    t("six_in_a_minute", 1, 1, 0, 0, 0, 0, 0, 100000);
    t("first_now_old", 1, 1, 0, 0, 0, 0, 0, 110001);
    return 0;
}
"""
    (tmp_path / "t.c").write_text(code)
    r = subprocess.run([CC, "-std=gnu17", "-Wall", "-o", str(tmp_path / "t"), str(tmp_path / "t.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = subprocess.run([str(tmp_path / "t")], capture_output=True, text=True, timeout=30).stdout
    rows = dict(l.split("|", 1) for l in out.strip().splitlines())
    assert rows["ok"] == "-"
    assert rows["not_running"].startswith("only the running mode")
    assert rows["no_game"].startswith("no game is being played")
    assert rows["floor_4"] == rows["floor_neg"] == "no such floor"
    assert rows["disabled"].startswith("the operator has the building stepper disabled")
    assert rows["faulted"].startswith("the building's stepper has faulted")
    assert rows["busy"].startswith("the building is busy")
    assert rows["cool_2999"].startswith("the last move started less than 3 s ago")
    assert rows["cool_3000"] == "-"
    assert rows["six_in_a_minute"].startswith("six moves in the last minute")
    assert rows["first_now_old"] == "-"


def test_the_move_is_the_games_own_and_put_back_on_every_end():
    src = _rt()
    move = _lift(src, "int pm_building(")
    assert move.count("building_send(") == 1 and "coil_virtual(obj, 2)" in move and "coil_virtual(obj, 0)" in move
    assert len(re.findall(r"\bbuilding_send\(", src)) == 3, "its definition, the move and the put-back - nothing else"
    assert 'building_let_go("the mode ended")' in _lift(src, "void pm_end(void)")
    assert 'building_let_go("the ball ended")' in _lift(src, "static void on_ball_end(")
    assert "building_tick();" in _lift(src, "static void on_tick(")
    tick = _lift(src, "static void building_tick(")
    for why in ("the game ended or tilted", "no mode is running", "of its own", "still busy"):
        assert why in tick


def _word(b, va):
    e = struct.unpack_from("<I", b, 0x1c)[0]
    for i in range(struct.unpack_from("<H", b, 0x2c)[0]):
        t, off, v, _pa, fs = struct.unpack_from("<5I", b, e + 32 * i)
        if t == 1 and v <= va < v + fs:
            return struct.unpack_from("<I", b, va - v + off)[0]
    return None


def test_the_port_names_the_building():
    text = LE_PORT.read_text(encoding="utf-8")
    for site in ("building_move", "building_busy"):
        assert re.search(r"^site %s\s+0x[0-9a-f]{8} 0x[0-9a-f]{8} 0x[0-9a-f]{8}\s*$" % site, text, re.M), site
    assert re.search(r"^data building_stepper\s+0x007bbe64\s*$", text, re.M)
    for v, n in (("building_vptr", "0x64ff90"), ("building_at", "44"), ("building_target_at", "48"),
                 ("building_floors", "4")):
        assert re.search(r"^value %s\s+%s\s*$" % (v, n), text, re.M), v
    pro = (SDK / "ports" / "godzilla_pro-1.16.port").read_text(encoding="utf-8")
    assert "building_move" not in pro                       # a Pro has no building stepper


def test_the_sites_match_the_game_program():
    b = next((open(c, "rb").read() for c in LE_ELF if c and os.path.isfile(c)), None)
    if b is None:
        pytest.skip("no godzilla_le 1.16 game program here")
    text = LE_PORT.read_text(encoding="utf-8")
    for site in ("building_move", "building_busy"):
        a, w0, w1 = (int(x, 16) for x in re.search(r"^site %s\s+(\S+) (\S+) (\S+)" % site, text, re.M).groups())
        assert (_word(b, a), _word(b, a + 4)) == (w0, w1), site
    vt = int(re.search(r"^value building_vptr\s+(\S+)", text, re.M).group(1), 16)
    assert _word(b, vt) == 0x1dbdc0 and _word(b, vt + 8) == 0x1dbe10   # StepperMotor v[0] fault, v[2] disabled
