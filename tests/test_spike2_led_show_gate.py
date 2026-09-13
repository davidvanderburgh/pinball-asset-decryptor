"""hwshim.c's light-show gate, compiled out of the shim and driven by a clock.

THE GATE DECIDES WHETHER THE GAME IS PAST TECH ALERTS, and everything the rig
does unattended hangs off that one line of log: gamestate.sh greps it,
status.sh turns it into the app's State row, and autoattract.sh stops pressing
Service Back the moment it appears. It had gone wrong twice on evidence before
PAD-129 and had no test either time, which is why the rule now lives in a
function whose whole input is its arguments.

PAD-129's case is the second half of it. A Home Edition writes its one lamp
board about eleven times a second from boot and never changes a value -
jurassic_park_the_pin: 4260 writes, 20 indices, not one of them ever moves -
so a rate-only gate declared attract at 12.3 s over a machine that was still
sitting on its alerts screen, nothing ever pressed Service Back, and the nine
lamps the boot sweep lit stayed exactly as they were for the rest of the run.

AND THE MOVEMENT HALF IS A RATE, which is the part that needs its own numbers.
Once the shim decodes the insert boards' own show, both states move: parked on
the alerts screen for six minutes that card changes 54 lamp values in one
burst as the boards come up and then none at all, while attract runs about
1900 per 10 s. led_moving() is where that line is drawn, so it is tested here
against both sides of it.

The C here is EXTRACTED from hwshim.c, never copied into this file, so a change
to either rule that is not made to these expectations fails here.
"""
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
SHIM = os.path.join(RIG, "hwshim.c")

CC = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")

pytestmark = [
    pytest.mark.skipif(not os.path.isfile(SHIM), reason="rig not present"),
    pytest.mark.skipif(not CC, reason="no C compiler on this host"),
]

HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>

%s

/* argv[1..] are the lamp commands, each "<ms>:<moving>". Prints the verdict
 * and the window of every frame the gate had something to say about. */
int main(int argc, char **argv)
{
    int i;
    for (i = 1; i < argc; i++) {
        unsigned long now = strtoul(argv[i], 0, 10), window = 0;
        char *colon = argv[i];
        int moving, v;
        while (*colon && *colon != ':') colon++;
        moving = (*colon == ':') && colon[1] == '1';
        v = led_show_gate(now, moving, &window);
        if (v) printf("%%d@%%lu/%%lu ", v, now, window);
    }
    printf("\n");
    return 0;
}
"""


def _extract(name):
    """The source text of one static function, straight out of hwshim.c."""
    src = open(SHIM, encoding="utf-8", errors="replace").read()
    m = re.search(r"^static [^\n]*\b%s\(" % re.escape(name), src, re.M)
    assert m, "%s not found in hwshim.c - did it get renamed?" % name
    i = src.index("{", m.start())
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
        j += 1
    raise AssertionError("unbalanced braces reading %s" % name)


#: led_moving() reads the ring that led_val() fills, so the harness supplies
#: the ring itself - the SIZE comes out of the shim, because that constant is
#: the threshold this whole rule turns on.
MOVING_HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>

%s
static unsigned long led_move_at[LED_MOVE_RING];
static unsigned led_moves;

%s

/* argv[1] is the clock; argv[2..] are the times of moving lamp writes, in
 * order, as led_val() would have stamped them. */
int main(int argc, char **argv)
{
    unsigned long now = strtoul(argv[1], 0, 10);
    int i;
    for (i = 2; i < argc; i++) {
        led_move_at[led_moves %% LED_MOVE_RING] = strtoul(argv[i], 0, 10);
        led_moves++;
    }
    printf("%%d %%d %%d\n", led_moving(now), (int)led_moves, LED_MOVE_RING);
    return 0;
}
"""


def _extract_define(name):
    """`#define <name> <value>` as written in hwshim.c."""
    src = open(SHIM, encoding="utf-8", errors="replace").read()
    m = re.search(r"^#define\s+%s\s+(\d+)" % re.escape(name), src, re.M)
    assert m, "%s is not defined in hwshim.c any more" % name
    return m.group(0), int(m.group(1))


@pytest.fixture(scope="module")
def gate(tmp_path_factory):
    d = tmp_path_factory.mktemp("showgate")
    src = d / "gate.c"
    src.write_text(HARNESS % _extract("led_show_gate"), encoding="utf-8")
    exe = d / ("gate.exe" if os.name == "nt" else "gate")
    r = subprocess.run([CC, "-O1", "-o", str(exe), str(src)],
                       capture_output=True, text=True)
    assert r.returncode == 0, "the shim's own gate did not compile:\n" + r.stderr
    return str(exe)


@pytest.fixture(scope="module")
def moving(tmp_path_factory):
    d = tmp_path_factory.mktemp("ledmoving")
    src = d / "moving.c"
    define, _ = _extract_define("LED_MOVE_RING")
    src.write_text(MOVING_HARNESS % (define, _extract("led_moving")),
                   encoding="utf-8")
    exe = d / ("moving.exe" if os.name == "nt" else "moving")
    r = subprocess.run([CC, "-O1", "-o", str(exe), str(src)],
                       capture_output=True, text=True)
    assert r.returncode == 0, "led_moving did not compile:\n" + r.stderr
    return str(exe)


def _moving(moving, now, times):
    """(led_moving's answer, moves counted, the ring size the shim uses)."""
    r = subprocess.run([moving, str(now)] + [str(t) for t in times],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    a, b, c = r.stdout.split()
    return bool(int(a)), int(b), int(c)


def _run(gate, frames):
    """[(verdict, ms, window)] for a list of (ms, moving) lamp commands."""
    args = ["%d:%d" % (ms, bool(moving)) for ms, moving in frames]
    r = subprocess.run([gate] + args, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = []
    for tok in r.stdout.split():
        v, rest = tok.split("@")
        now, window = rest.split("/")
        out.append((int(v), int(now), int(window)))
    return out


def _sweep(start, count, step, period, rounds, moving=False):
    """A board refresh: `count` commands `step` ms apart, every `period` ms."""
    frames = []
    for r in range(rounds):
        base = start + r * period
        for i in range(count):
            frames.append((base + i * step, moving))
    return frames


#: jurassic_park_the_pin's shape, rounded off: a burst of twenty levels, then
#: the same twenty rewritten unchanged for as long as the machine is up. The
#: real card's boot bursts are faster than this (its own false announcement
#: read "30 lamp commands in 303 ms"); the period here is only wide enough to
#: keep the 30-command window comfortably inside three seconds, so that what
#: the test proves is the STILLNESS and not an accident of the rate.
STILL_REFRESH = _sweep(12000, 20, 15, 900, 200)


def test_a_still_refresh_never_announces(gate):
    """THE TICKET. The rate gate is met over and over; nothing is drawn; the
    gate must not claim the game has reached attract."""
    said = _run(gate, STILL_REFRESH)
    assert all(v != 1 for v, _, _ in said), (
        "a board refresh that never changes a lamp announced a light show: %s"
        % said)


def test_a_still_refresh_says_so_once(gate):
    """And it is not silent about it: the one case where the rate is there and
    the picture is not moving is exactly a machine parked on Tech Alerts, so
    the run's log names it - once, not 4000 times."""
    said = _run(gate, STILL_REFRESH)
    assert [v for v, _, _ in said] == [2], said
    verdict, now, window = said[0]
    assert now >= 12000 and 0 < window <= 3000, said


def test_a_moving_show_announces_at_the_rate(gate):
    """godzilla's shape: the same rate, with lamps actually changing. The gate
    must fire on the 31st command, within the first second."""
    frames = [(20000 + i * 25, True) for i in range(40)]
    said = _run(gate, frames)
    assert said and said[0][0] == 1, said
    assert said[0][1] <= 20000 + 31 * 25, "announced later than the 31st frame"
    assert said[0][2] <= 3000
    assert len([v for v, _, _ in said if v == 1]) == 1, "announced twice"


def test_the_still_window_keeps_sliding(gate):
    """A run that refreshes quietly for minutes and THEN starts a show must
    announce on the first moving frame, not thirty frames later: the sliding
    window has to keep its last thirty commands while the picture is still."""
    frames = list(STILL_REFRESH)
    show_at = frames[-1][0] + 900
    frames += [(show_at, True)]
    said = _run(gate, frames)
    assert (1, show_at) == (said[-1][0], said[-1][1]), said


def test_a_boot_burst_is_not_a_moving_picture(moving):
    """THE SECOND HALF OF THE TICKET. Parked on the alerts screen for six
    minutes, jurassic_park_the_pin changed 54 lamp values and star_wars_elg
    114, all of them as the boards came up. A burst that size must not read as
    a show, or the widened decoder puts the original bug straight back."""
    on, n, ring = _moving(moving, 15000, [12000 + i for i in range(114)])
    assert n == 114
    assert ring >= 200, (
        "the ring is %d, which is inside the burst the alerts screen itself "
        "produces (114 on star_wars_elg)" % ring)
    assert not on, "a 114-change boot burst counted as a moving picture"


def test_attract_rate_is_a_moving_picture(moving):
    """And the other side of the same line: in attract that card changes about
    1900 lamp values per 10 s, and the busiest three seconds measured across
    godzilla, turtles, batman and DnD run 508 to 1278. 508 in 3 s must read as
    a show."""
    on, n, _ = _moving(moving, 23000, [20000 + (i * 3000) // 508
                                       for i in range(508)])
    assert n == 508
    assert on, "attract's own measured rate did not read as a moving picture"


def test_moving_is_a_rate_and_not_a_count(moving):
    """The same number of changes spread over eight seconds is a machine
    ticking over, not a show."""
    on, _, ring = _moving(moving, 28000, [20000 + (i * 8000) // 508
                                          for i in range(508)])
    assert not on, "%d changes spread over 8 s counted as a show" % ring


def test_a_slow_trickle_never_announces(gate):
    """The rate half still stands on its own: lamp commands that move the
    picture but arrive at 5/s are the service menu's own trickle, not a show,
    and 30 of them take 6 s."""
    frames = [(20000 + i * 200, True) for i in range(60)]
    assert _run(gate, frames) == [], "a 5/s trickle announced a light show"


def test_a_menu_blip_does_not_fake_it(gate):
    """star_wars_le's trap, kept from the rule's own history: walking into the
    service menu emits a small lamp burst. Ten moving commands in 300 ms are
    not thirty in three seconds."""
    frames = [(30000 + i * 30, True) for i in range(10)]
    assert _run(gate, frames) == [], "a ten-command burst announced"
