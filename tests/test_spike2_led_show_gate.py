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

The C here is EXTRACTED from hwshim.c, never copied into this file, so a change
to the rule that is not made to these expectations fails here.
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
