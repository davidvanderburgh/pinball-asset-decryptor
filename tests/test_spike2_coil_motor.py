"""hwshim.c's coil-run motor: jaws_le's shark (PAD-256).

The shark is not a board motor. A plain coil output (SHARK MOTOR UP/DOWN, node
9 index 0) turns a cam one way round, and the game hands the board a coil RULE
- cmd 41, byte 30 = the input that STOPS the coil (SHARK UP-MAG SW, input 12,
or SHARK DOWN-MAG SW, input 13) - then runs it with a short cmd 40 and waits
up to 10 s for that switch. Nothing moved the switches, so from Start the rig
ran the shark 10 s of every 12.5, for ever.

hwshim.c now plays the cam: coil_motor_note() reads the rule and the run off
the wire, coil_motor_tick() closes the stop switch after the travel time. This
compiles those REAL functions out of hwshim.c (test_spike2_node_motor's
extractor - the text is never copied here) with the switch write and the clock
stubbed, and feeds them the frames jaws_le 1.02 sent (rig 2 trace,
2026-09-28). What is worth failing on:

  * THE STOP INPUT IS BYTE 30, and only on a rule with no FIRING input (byte
    26). The same title's RIGHT POP BUMPER rule carries its switch in byte 26;
    a rule with both - a switch-fired coil held until a second switch - is not
    a motor, and playing it would close a switch no ball touched.
  * THE SWITCH IT LEAVES OPENS AT ONCE, the one it runs to closes after the
    travel time. UP and DOWN made together is a shark in two places.
  * THE BOARD RE-INIT RE-SENDS THE RULE every ~0.7 s (PAD-249). A re-send is
    not a new move, and neither is a second run while the first is travelling.
  * A RULE CLEARED BEFORE ARRIVAL IS THE COIL OFF: nothing arrives.
  * PAD_COIL_MOTOR=0 moves nothing, which is the comparison run's switch.
"""
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIM = os.path.join(ROOT, "tools", "spike2_emu", "hwshim.c")

CC = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")

pytestmark = [
    pytest.mark.skipif(not os.path.isfile(SHIM), reason="rig not present"),
    pytest.mark.skipif(not CC, reason="no C compiler on this host"),
]

#: jaws_le 1.02, node 9, as sent (PAD_NB_TRACE=1, 2026-09-28).
RULE_UP = ("893141005ae803000000000000000000000000000000000000000000"
           "00004c000000000000000000000000000000000000007400")       # stop on 12
RULE_DOWN = ("893141005ae803000000000000000000000000000000000000000000"
             "00004d000000000000000000000000000000000000007300")     # stop on 13
CLEAR = "89314100" + "00" * 46 + "0500"                              # rule gone
RUN = "890340003400"                                                 # short 40
#: its RIGHT POP BUMPER rule, coil 3: fired by input 29 (byte 26), no stop
POP = ("89314103ff0300000000000000001800000000000000000000005d00"
       "000000000000000000000000000000000000000000008b00")
#: the shark's rule with a FIRING input added at byte 26 (input 29) - a coil
#: fired by one switch and held until another, which is not a motor
BOTH = RULE_UP[:52] + "5d" + RULE_UP[54:]
#: the 14-byte fire frame on the same coil - coil_publish()'s, not a run
FIRE14 = "890b4000ff000000000000002d00"

HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned long now_ms;
static unsigned long pad_ms(void) { return now_ms; }
static void logmsg(const char *s) { (void)s; }
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
            coil_motor_tick((unsigned)strtoul(e + 1, 0, 10));
        } else {                            /* f<hex> - a frame on the wire   */
            unsigned char f[64];
            int n = 0;
            s++;
            while (s[0] && s[1] && n < 64) {
                char t[3]; t[0] = s[0]; t[1] = s[1]; t[2] = 0;
                f[n++] = (unsigned char)strtoul(t, 0, 16);
                s += 2;
            }
            coil_motor_note(f, n);
        }
    }
    return 0;
}
"""


def _src():
    return open(SHIM, encoding="utf-8", errors="replace").read()


def _extract(name):
    """One static function's DEFINITION, brace-counted out of hwshim.c (the
    same reading as test_spike2_node_motor's; a prototype is skipped)."""
    src = _src()
    m = None
    for c in re.finditer(r"^static [^\n]*\b%s\(" % re.escape(name), src, re.M):
        brace, semi = src.find("{", c.start()), src.find(";", c.start())
        if brace >= 0 and (semi < 0 or brace < semi):
            m = c
            break
    assert m, "%s not found in hwshim.c - did it get renamed?" % name
    depth, j = 0, src.index("{", m.start())
    while j < len(src):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[m.start():j + 1]
        j += 1
    raise AssertionError("unbalanced braces reading %s" % name)


def _state():
    src = _src()
    m = re.search(r"^#define COIL_MOTOR_IDX.*?^static unsigned char coil_motor_any\[.*?;$",
                  src, re.M | re.S)
    assert m, "the coil motor state declarations moved - update this test"
    return m.group(0)


@pytest.fixture(scope="module")
def cbin(tmp_path_factory):
    d = tmp_path_factory.mktemp("coilmotor")
    body = chr(10).join([_state(), _extract("motor_ms"), _extract("motor_say"),
                         _extract("coil_motor_on"), _extract("coil_motor_tick"),
                         _extract("coil_motor_note")])
    src = d / "coilmotor.c"
    src.write_text(HARNESS % body, encoding="utf-8")
    exe = d / ("coilmotor.exe" if os.name == "nt" else "coilmotor")
    r = subprocess.run([CC, "-O1", "-Wall", "-o", str(exe), str(src)],
                       capture_output=True, text=True)
    assert r.returncode == 0, "the shim's coil motor did not compile:\n" + r.stderr
    return str(exe)


def _run(cbin, steps, **env):
    """The switch edges the model makes, as (ms, node, input, made)."""
    e = dict(os.environ)
    e.pop("PAD_COIL_MOTOR", None)
    e.pop("PAD_MOTOR_MS", None)
    e.update(env)
    r = subprocess.run([cbin] + ["f" + s if not s.startswith("t") else s for s in steps],
                       capture_output=True, text=True, env=e)
    assert r.returncode == 0, r.stderr
    return [tuple(int(x) for x in line.split()[1:])
            for line in r.stdout.splitlines() if line.startswith("E ")]


def test_run_closes_the_rules_stop_switch(cbin):
    """UP-MAG (input 12) closes 600 ms after the run, not a millisecond early."""
    edges = _run(cbin, ["t1000:9", RULE_UP, RUN, "t1599:9", "t1600:9"])
    assert edges == [(1600, 9, 12, 1)]


def test_down_opens_up_then_makes_down(cbin):
    edges = _run(cbin, ["t0:9", RULE_UP, RUN, "t600:9", CLEAR,
                        "t5000:9", RULE_DOWN, RUN, "t5599:9", "t5600:9"])
    assert edges == [(600, 9, 12, 1),       # up
                     (5000, 9, 12, 0),      # the cam leaves UP at once
                     (5600, 9, 13, 1)]      # and reaches DOWN after the travel


def test_never_up_and_down_together(cbin):
    steps = ["t0:9"]
    t = 0
    for rule in (RULE_UP, RULE_DOWN) * 3:
        steps += [rule, RUN, "t%d:9" % (t + 300), "t%d:9" % (t + 700), CLEAR]
        t += 1000
        steps.append("t%d:9" % t)
    made = set()
    for _ms, _nid, bit, level in _run(cbin, steps):
        (made.add if level else made.discard)(bit)
        assert made != {12, 13}


def test_re_sends_are_not_new_moves(cbin):
    """The board re-init re-sends the rule every ~0.7 s; a second run while
    travelling must not restart the clock either."""
    edges = _run(cbin, ["t0:9", RULE_DOWN, RUN, "t300:9", RULE_DOWN, RUN,
                        "t599:9", "t600:9", RULE_DOWN, "t1300:9", RULE_DOWN, RUN,
                        "t5000:9"])
    assert edges == [(600, 9, 13, 1)]


def test_rule_cleared_before_arrival_is_the_coil_off(cbin):
    edges = _run(cbin, ["t0:9", RULE_UP, RUN, "t300:9", CLEAR, "t5000:9"])
    assert edges == []


def test_only_the_short_run_on_a_stop_rule_moves_it(cbin):
    assert _run(cbin, ["t0:9", RUN, "t5000:9"]) == []                 # no rule
    assert _run(cbin, ["t0:9", RULE_UP, FIRE14, "t5000:9"]) == []     # 14-byte fire
    assert _run(cbin, ["t0:9", POP, "890340033100","t5000:9"]) == []  # pop rule


def test_a_switch_fired_rule_is_not_a_motor(cbin):
    assert _run(cbin, ["t0:9", BOTH, RUN, "t5000:9"]) == []


def test_off_switch(cbin):
    assert _run(cbin, ["t0:9", RULE_UP, RUN, "t5000:9"], PAD_COIL_MOTOR="0") == []


def test_travel_time_is_pad_motor_ms(cbin):
    edges = _run(cbin, ["t0:9", RULE_UP, RUN, "t249:9", "t250:9"], PAD_MOTOR_MS="250")
    assert edges == [(250, 9, 12, 1)]


#: PAD-1239: rush_le 1.19, node 9 coil 0 TROUGH LOCK, as sent (PAD_NB_TRACE=1,
#: rig 1, 2026-11-13) - pulse ff 3 ticks, HOLD 0x50 300 ticks (byte 7), and
#: byte 30 = 0x80|0x40|16, SIDE SCOOP OPTO. The game re-sends it with a short
#: 40 every ~258 ms while it waits for a ball to cross the opto.
RUSH_LOCK = ("89314100ff0300502c01000000000000000000000000000000000000"
             "0000d000000000000000000000000000000000000000b600")
#: the same title's topper (node 12 coil 0), which IS a motor: 1000 ticks, no
#: hold, byte 30 = 0x40|4
RUSH_TOPPER = ("8c31410046e803000000000000000000000000000000000000000000"
               "000044000000000000000000000000000000000000008d00")


def test_a_held_coil_its_switch_lets_go_is_not_a_motor(cbin):
    """PAD-1239: played as a motor, SIDE SCOOP OPTO closed 600 ms after the
    ball landed on LOWER SIDE SCOOP and stayed closed - the game never kicked
    and called it SIDE SCOOP DEVICE MALFUNCTION. The switch is the ball's."""
    steps = ["t0:9"]
    for t in range(0, 5000, 258):
        steps += [RUSH_LOCK, RUN, "t%d:9" % t]
    assert _run(cbin, steps + ["t9000:9"]) == []
    # either sign alone is enough: a hold power, or 0x80 on the stop byte
    hold_only = RUSH_LOCK[:60] + "50" + RUSH_LOCK[62:]
    flag_only = RUSH_LOCK[:14] + "00" + RUSH_LOCK[16:]
    for f in (hold_only, flag_only):
        assert _run(cbin, ["t0:9", f, RUN, "t5000:9"]) == []
    # and the title's real motor still runs to its stop
    assert _run(cbin, ["t0:12", RUSH_TOPPER, "8c0340000000", "t600:12"]) == [(600, 12, 4, 1)]


def test_a_motor_rule_turning_into_a_held_one_stops_the_run(cbin):
    edges = _run(cbin, ["t0:9", RULE_UP, RUN, "t300:9", RUSH_LOCK, "t5000:9"])
    assert edges == []
