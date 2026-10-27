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

#: dungeons_and_dragons_le 1.10, node 10, as sent (PAD-656): the dragon's two axes, configured and homed
#: once at boot. Left-right: byte 7 = 0x41 LR HOME, byte 8 = 0x40 LR AWAY; up-down: byte 7 = 0x42 UD HOME and
#: no byte 8. Both homed with direction 1 (godzilla's building with 0).
DND_UD_CONFIG = "8a143201c8e1004200a080500000000005007d00005200"
DND_UD_HOME = "8a043401013c00"
DND_LR_CONFIG = "8a14320000e1004140a080500000000005007d0000dc00"
DND_LR_HOME = "8a043400013d00"

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
        } else if (s[0] == 's') {           /* s<node>[:<motor>] - a status poll */
            unsigned char p[5] = {0, 0, 0, 0, 0};
            char *e;
            unsigned nid = (unsigned)strtoul(s + 1, &e, 10);
            int r = stepper_status(nid, *e == ':' ? (unsigned)strtoul(e + 1, 0, 10) : 0, p);
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
        "stepper_tick", "stepper_go", "stepper_ends", "stepper_note", "stepper_status")])
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


def test_dnd_dragon_axes_home_on_their_home_switches(sbin):
    """PAD-656: the one-switch up-down axis is a stepper too, and direction 1 homes each axis to byte 7's input,
    the one the game names HOME. Before, the up-down axis went unanswered (zero status for ever) and left-right
    homed onto LR AWAY: 'Dragon Jam - DEVICE MALFUNCTION'."""
    edges, st = _run(sbin, ["t0:10", DND_UD_CONFIG, DND_UD_HOME, DND_LR_CONFIG, DND_LR_HOME, "s10:1", "s10:0",
                            "t1000:10", "s10:1", "s10:0"])
    assert st == [(0, 1, -3750, "02"), (0, 1, -3750, "02"), (1000, 1, 0, "04"), (1000, 1, 0, "04")]
    made = {(nid, bit) for _ms, nid, bit, level in edges if level}
    assert made == {(10, 2), (10, 1)}           # UD HOME and LR HOME; never LR AWAY (input 0)


#: and the attract swing that follows (PAD_NB_TRACE=1, 2026-10-20): left-right +50, then up-down +69 and back
DND_LR_50 = "8a133100320090000000d0070000d00700000000c200"
DND_UD_UP = "8a133101450090010000d0070000d00700000000ad00"
DND_UD_DOWN = "8a133101bbff90000000d0070000d007000000003900"


def test_dnd_moves_are_positive_from_home(sbin):
    """The dragon's positions lie ABOVE home: +69 lifts the head off UD HOME and -69 brings it back on. (The
    building's stop at home, positions <= 0 only, held every dragon move at 0.)"""
    edges, st = _run(sbin, ["t0:10", DND_UD_CONFIG, DND_UD_HOME, DND_LR_CONFIG, DND_LR_HOME, "t1000:10",
                            DND_LR_50, DND_UD_UP, "t1100:10", "s10:0", "s10:1",
                            DND_UD_DOWN, "t1200:10", "s10:1"])
    assert st == [(1100, 1, 50, "04"), (1100, 1, 69, "04"), (1200, 1, 0, "04")]
    ud, level = [], None
    for ms, _nid, bit, lv in edges:             # the UD HOME input's changes
        if bit == 2 and lv != level:
            ud.append((ms, lv))
            level = lv
    assert ud == [(0, 0), (1000, 1), (1000, 0), (1200, 1)]   # between; homed; lifted; back on
    assert (1000, 10, 1, 0) in edges            # LR leaves LR HOME


#: james_bond_60th_le 1.11, node 6 motor 0 (PAD-656 sweep): one input, in byte 8; homed with direction 0, and its
#: moves are positive too - so the side of home is not the direction's, and the model stops at neither
BOND_CONFIG = "86143200c8ff7f004088004b000000000000000001da00"
BOND_HOME = "86043400004200"
BOND_60 = "861331003c0058020000e80300008813000000001a00"


def test_bond_60th_one_input_in_byte_8(sbin):
    edges, st = _run(sbin, ["t0:6", BOND_CONFIG, BOND_HOME, "t1000:6", "s6", BOND_60, "t1100:6", "s6"])
    assert st == [(1000, 1, 0, "04"), (1100, 1, 60, "04")]
    assert (1000, 6, 0, 1) in edges and (1000, 6, 0, 0) in edges   # home made, then left for +60


def test_direction_zero_homes_to_byte_8(sbin):
    """The same frames homed the other way: left-right to LR AWAY's input, up-down to the only input it has."""
    edges, _ = _run(sbin, ["t0:10", DND_UD_CONFIG, DND_UD_HOME[:8] + "00" + DND_UD_HOME[10:],
                           DND_LR_CONFIG, DND_LR_HOME[:8] + "00" + DND_LR_HOME[10:], "t1000:10"])
    assert {(nid, bit) for _ms, nid, bit, level in edges if level} == {(10, 2), (10, 0)}


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


@needs_cc
def test_the_lock_is_closed_while_one_of_ours_runs(tmp_path):
    """PAD-684 (David's Premium: a building lock lit before a mode of ours stayed open through it, balls locked, and
    the third lock's Godzilla Multiball - which our mode keeps from starting - never came: ball search). While one of
    ours runs, a building parked above floor 0 (floor 1: the lock lit) goes to 0, within the moves' own limits."""
    src = _rt()
    code = "#include <stdio.h>\n" + "\n".join(re.findall(r"^#define MAGNET_\w+ .*$", src, re.M)) + "\n" + \
        _lift(src, "static const char *building_close_why(") + r"""
static unsigned long st[MAGNET_PER_MIN];
static void t(const char *label, int run, int game, int aside, int back, int asked, int at, int to, int busy, int off,
              unsigned long last, unsigned long now)
{
    const char *w = building_close_why(run, game, aside, back, asked, at, to, busy, off, last, now, st);
    printf("%s|%s\n", label, w ? w : "-");
}
int main(void)
{
    unsigned i;
    t("lit", 1, 1, 0, 0, -1, 1, 1, 0, 0, 0, 100000);
    t("kept_closed", 1, 1, 0, 0, 0, 1, 1, 0, 0, 90000, 100000);
    t("no_mode", 0, 1, 0, 0, -1, 1, 1, 0, 0, 0, 100000);
    t("attract", 1, 0, 0, 0, -1, 1, 1, 0, 0, 0, 100000);
    t("games_mode", 1, 1, 1, 0, -1, 1, 1, 0, 0, 0, 100000);
    t("putting_back", 1, 1, 0, 1, -1, 1, 1, 0, 0, 0, 100000);
    t("its_own_floor", 1, 1, 0, 0, 3, 3, 3, 0, 0, 0, 100000);
    t("closed", 1, 1, 0, 0, -1, 0, 0, 0, 0, 0, 100000);
    t("moving", 1, 1, 0, 0, -1, 0, 1, 0, 0, 0, 100000);
    t("busy", 1, 1, 0, 0, -1, 1, 1, 1, 0, 0, 100000);
    t("off", 1, 1, 0, 0, -1, 1, 1, 0, 1, 0, 100000);
    t("cool", 1, 1, 0, 0, -1, 1, 1, 0, 0, 98000, 100000);
    for (i = 0; i < MAGNET_PER_MIN; i++) st[i] = 50000 + i * 4000;
    t("six", 1, 1, 0, 0, -1, 1, 1, 0, 0, 0, 100000);
    return 0;
}
"""
    (tmp_path / "t.c").write_text(code)
    r = subprocess.run([CC, "-std=gnu17", "-Wall", "-o", str(tmp_path / "t"), str(tmp_path / "t.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = subprocess.run([str(tmp_path / "t")], capture_output=True, text=True, timeout=30).stdout
    rows = dict(l.split("|", 1) for l in out.strip().splitlines())
    assert rows["lit"] == rows["kept_closed"] == "-"
    assert rows["no_mode"] == rows["attract"] == rows["games_mode"] == rows["putting_back"] == "not ours to close now"
    assert rows["its_own_floor"] == "the mode has it on a floor of its own"
    assert rows["closed"] == "closed already" and rows["moving"] == rows["busy"] == "moving"
    assert rows["off"].startswith("the stepper is off") and rows["cool"].startswith("the last move started")
    assert rows["six"].startswith("six moves")
    keep = _lift(src, "static void building_keep_closed(")
    assert "building_send(obj, 0);" in keep and "bld.home = at" in keep and "bld.ours = 0" in keep
    assert "building_keep_closed();" in _lift(src, "static void building_tick(")


@needs_cc
def test_the_game_does_not_raise_it_again_while_ours_keeps_it_closed(tmp_path):
    """PAD-733 (David's Premium, MELTDOWN: "we shouldn't have the building be going up and down over and over again
    that is dangerous because the ball can damage the building"): the lock lit, the game sent the building back up
    and the close sent it down again. While one of ours keeps it closed, the game's own moves above 0 are refused."""
    src = _rt()
    code = "#include <stdio.h>\n" + _lift(src, "static int building_raise_refused(") + r"""
static void t(const char *label, int sending, int run, int game, int aside, int closed, int back, int floor)
{
    printf("%s|%d\n", label, building_raise_refused(sending, run, game, aside, closed, back, floor));
}
int main(void)
{
    t("raise", 0, 1, 1, 0, 1, 0, 1);
    t("raise_3", 0, 1, 1, 0, 1, 0, 3);
    t("to_0", 0, 1, 1, 0, 1, 0, 0);
    t("ours", 1, 1, 1, 0, 1, 0, 1);
    t("no_mode", 0, 0, 1, 0, 1, 0, 1);
    t("attract", 0, 1, 0, 0, 1, 0, 1);
    t("games_mode", 0, 1, 1, 1, 1, 0, 1);
    t("not_closed", 0, 1, 1, 0, 0, 0, 1);
    t("putting_back", 0, 1, 1, 0, 1, 1, 1);
    return 0;
}
"""
    (tmp_path / "t.c").write_text(code)
    r = subprocess.run([CC, "-std=gnu17", "-Wall", "-o", str(tmp_path / "t"), str(tmp_path / "t.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = subprocess.run([str(tmp_path / "t")], capture_output=True, text=True, timeout=30).stdout
    rows = dict(l.split("|", 1) for l in out.strip().splitlines())
    assert rows["raise"] == rows["raise_3"] == "1"
    for k in ("to_0", "ours", "no_mode", "attract", "games_mode", "not_closed", "putting_back"):
        assert rows[k] == "0", k
    veto = _lift(src, "static int building_move_veto(")
    assert "bld.home >= 0 && bld.ours == 0" in veto and "r[0] != obj" in veto and "aside.kind" in veto
    send = _lift(src, "static void building_send(")
    assert send.index("bld_sending = 1") < send.index("fn(\"building_move\")") < send.index("bld_sending = 0")
    assert "hook_veto(fn(\"building_move\"), building_move_veto)" in _lift(src, "static void building_arm(")


def test_the_move_is_the_games_own_and_put_back_on_every_end():
    src = _rt()
    move = _lift(src, "int pm_building(")
    assert move.count("building_send(") == 1 and "coil_virtual(obj, 2)" in move and "coil_virtual(obj, 0)" in move
    assert len(re.findall(r"\bbuilding_send\(", src)) == 4, \
        "its definition, the move, the put-back and (PAD-684) the lock closed while ours runs - nothing else"
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
