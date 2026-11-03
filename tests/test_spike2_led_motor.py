"""hwshim.c's LED-class motor: beatles' spinning record (PAD-965).

The record has no coil. Its device records are two LEDs on node 8 (MOTOR A0
DRIVER, output 4; MOTOR A1 DRIVER, output 5), and the game runs it with node
cmd 50 - `50 04 05 ff` on, `50 04 05 00` off - 15 ms before every burst of
MAGNET-RECORD, never in a lamp frame. Nothing read cmd 50, so outputs 4 and 5
stayed 0 in the LED plane, the Visual Pinball table's record never turned, and
the ball the magnet caught dropped down the middle.

This compiles the REAL led_val() and led_motor_publish() out of hwshim.c
(test_spike2_coil_motor's extractor; the text is never copied here) over a
stand-in LED plane and feeds them the frames beatles 1.29 sent (rig 3 trace,
2026-11-03). What is worth failing on:

  * cmd 50 RUNS THE MOTOR: output A carries the speed, B is held at 0 - one
    side of the bridge driven, which the table reads as the record turning.
  * THE LAMP FRAMES CANNOT STOP IT. A lamp write to a driven output keeps the
    motor's level; once cmd 50 stops it, the lamp frames own the cell again.
  * Only cmd 50 does this: a lamp frame or another command on the same node
    leaves the outputs to the lamps.
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

#: beatles 1.29, node 8, as sent (PAD_NB_TRACE=1, 2026-11-03)
RUN = "8805500405ff1b00"
STOP = "8805500405001a00"
#: a 14-byte coil fire on the same node - not a motor
FIRE = "880b4004ff000000000000002a00"

HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct plane { unsigned char val[16][96]; unsigned char seen[16][96]; };
static struct plane plane_mem;
static struct plane *led_shm = &plane_mem;
static unsigned led_shm_len = 8192;
#define LED_MOVE_RING 200
static unsigned long led_move_at[LED_MOVE_RING];
static unsigned led_moves;
static unsigned long pad_ms(void) { return 0; }
static void logmsg(const char *s) { (void)s; }
static void led_seen(unsigned node, unsigned idx) { led_shm->seen[node][idx] = 1; }

%s

int main(int argc, char **argv)
{
    int a;
    for (a = 1; a < argc; a++) {
        const char *s = argv[a];
        if (s[0] == 'l') {                  /* l<node>:<idx>:<v> - a lamp write */
            char *e;
            unsigned node = (unsigned)strtoul(s + 1, &e, 10);
            unsigned idx = (unsigned)strtoul(e + 1, &e, 10);
            led_val(node, idx, (unsigned char)strtoul(e + 1, 0, 10));
        } else if (s[0] == 'p') {           /* p - print node 8, outputs 4 and 5 */
            printf("P %%u %%u\n", led_shm->val[8][4], led_shm->val[8][5]);
        } else {                            /* f<hex> - a frame on the wire   */
            unsigned char f[64];
            int n = 0;
            s++;
            while (s[0] && s[1] && n < 64) {
                char t[3]; t[0] = s[0]; t[1] = s[1]; t[2] = 0;
                f[n++] = (unsigned char)strtoul(t, 0, 16);
                s += 2;
            }
            led_motor_publish(f, n);
        }
    }
    return 0;
}
"""


def _src():
    return open(SHIM, encoding="utf-8", errors="replace").read()


def _extract(name):
    """One static function's DEFINITION, brace-counted out of hwshim.c (the
    same reading as test_spike2_coil_motor's; a prototype is skipped)."""
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


@pytest.fixture(scope="module")
def cbin(tmp_path_factory):
    d = tmp_path_factory.mktemp("ledmotor")
    state = re.search(r"^static unsigned char led_motor_out\[16\]\[96\];$", _src(), re.M)
    assert state, "the LED motor state declaration moved - update this test"
    body = chr(10).join([state.group(0), _extract("led_val"), _extract("led_motor_publish")])
    src = d / "ledmotor.c"
    src.write_text(HARNESS % body, encoding="utf-8")
    exe = d / ("ledmotor.exe" if os.name == "nt" else "ledmotor")
    r = subprocess.run([CC, "-O1", "-Wall", "-o", str(exe), str(src)],
                       capture_output=True, text=True)
    assert r.returncode == 0, "the shim's LED motor did not compile:\n" + r.stderr
    return str(exe)


def _run(cbin, steps):
    """Outputs 4 and 5 of node 8 at each `p`."""
    r = subprocess.run([cbin] + [s if s[0] in "lp" else "f" + s for s in steps],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [tuple(int(x) for x in line.split()[1:])
            for line in r.stdout.splitlines() if line.startswith("P ")]


def test_cmd_50_runs_and_stops_the_record(cbin):
    assert _run(cbin, ["p", RUN, "p", STOP, "p"]) == [(0, 0), (255, 0), (0, 0)]


def test_lamp_frames_cannot_stop_a_running_motor(cbin):
    got = _run(cbin, [RUN, "l8:4:0", "l8:5:0", "p", "l8:5:200", "p",
                      STOP, "l8:4:9", "p"])
    # B is a lamp cell like any other (the game never lights it); A keeps the
    # speed until cmd 50 stops it, and then the lamps own it again
    assert got == [(255, 0), (255, 200), (9, 0)]


def test_only_cmd_50_drives_the_outputs(cbin):
    assert _run(cbin, [FIRE, "p", "l8:4:7", "p"]) == [(0, 0), (7, 0)]
