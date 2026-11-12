"""hwshim.c's playfield-TV playback position: batman's Bat Phone (PAD-1184).

A player on batman 66 (VPX): "Game starts and it tells you to shoot the bat
phone, but the mech hasn't rotated allowing you to so the hurry up cannot be
completed." On the rig, in about half of long games, the game turned the
turntable to the Bat Phone for the first hurry-up and never again.

Read out of batman 1.14: the turntable rule (0x2f97c) asks for POS. #2 while
a hurry-up runs UNLESS show 0x1c is current, and show 0x1c (0x2fa84) tells the
villain TV (node 24, cmd f2) to play 0x1e4..0x1f0 and then waits (0x4988e4)
until the TV's reported position - word0 of its f2 90 status reply, polled by
the channel layer at 0x498fe8 - leaves [0x1e4, 0x1f0). The shim echoed the
commanded 0x1e4 for ever, so the show only ended if something else
re-commanded the TV, and until then the game would not turn to the phone.

The shim now keeps the position a real board would report (lcd_play_note /
lcd_play_pos). This compiles those REAL functions out of hwshim.c with the
clock stubbed and feeds them batman's own frames. Worth failing on:

  * a play A..D that plays ONCE ends at D - at or past the end of the range,
    which is the only thing that releases the game's wait;
  * a seek holds still, a looping play wraps back to A and never reaches D;
  * a display nothing has commanded is "not known", so the old echo answers;
  * each display index keeps its own position.

Skipped where there is no C compiler; it runs in WSL, where the shim is built.
"""
import os
import re
import shutil
import struct
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIM = os.path.join(ROOT, "tools", "spike2_emu", "hwshim.c")
CC = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")

pytestmark = [
    pytest.mark.skipif(not os.path.isfile(SHIM), reason="rig not present"),
    pytest.mark.skipif(not CC, reason="no C compiler on this host"),
]


def _src():
    with open(SHIM, encoding="utf-8", errors="replace") as f:
        return f.read()


def _extract(name):
    src = _src()
    for c in re.finditer(r"^static [^\n]*\b%s\(" % re.escape(name), src, re.M):
        brace, semi = src.find("{", c.start()), src.find(";", c.start())
        if brace >= 0 and (semi < 0 or brace < semi):
            i, depth = brace, 0
            for j in range(i, len(src)):
                if src[j] == "{":
                    depth += 1
                elif src[j] == "}":
                    depth -= 1
                    if depth == 0:
                        return src[c.start():j + 1]
    raise AssertionError("%s not found in hwshim.c - did it get renamed?" % name)


def _state():
    m = re.search(r"^static struct \{\n[^}]*\} lcd_pl\[4\];$", _src(), re.M)
    assert m, "the lcd_pl declaration moved - update this test"
    return m.group(0)


HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
static unsigned long now_ms;
static unsigned long pad_ms(void) { return now_ms; }
%s
int main(int argc, char **argv)
{
    int a;
    for (a = 1; a < argc; a++) {
        const char *s = argv[a];
        if (s[0] == 't') {
            now_ms = strtoul(s + 1, 0, 10);
        } else if (s[0] == 'p') {
            unsigned idx = (unsigned)strtoul(s + 1, 0, 10);
            int k = lcd_play_known(idx);
            printf("P %%lu %%u %%d\n", now_ms, k ? lcd_play_pos(idx) : 0u, k);
        } else {
            unsigned char f[64];
            int n = 0;
            s++;
            while (s[0] && s[1] && n < 64) {
                char t[3] = { s[0], s[1], 0 };
                f[n++] = (unsigned char)strtoul(t, 0, 16);
                s += 2;
            }
            lcd_play_note(f, f[1], f[3]);
        }
    }
    return 0;
}
"""


@pytest.fixture(scope="module")
def cbin(tmp_path_factory):
    d = tmp_path_factory.mktemp("lcdpos")
    body = "\n".join([_extract("lcd_fps"), _extract("lcd_le32"), _state(),
                      _extract("lcd_play_pos"), _extract("lcd_play_known"),
                      _extract("lcd_play_note")])
    src = d / "lcd.c"
    src.write_text(HARNESS % body, encoding="utf-8")
    exe = d / ("lcd.exe" if os.name == "nt" else "lcd")
    r = subprocess.run([CC, "-O1", "-Wall", "-o", str(exe), str(src)],
                       capture_output=True, text=True)
    assert r.returncode == 0, "the shim's TV model did not compile:\n" + r.stderr
    return str(exe)


def _run(cbin, steps):
    r = subprocess.run([cbin] + steps, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [tuple(int(x) for x in ln.split()[1:])
            for ln in r.stdout.splitlines() if ln.startswith("P ")]


def _frame(sel, payload):
    """A cmd f2 frame as the game's builders lay it out: 0x80|node 24, the
    length byte (cmd..checksum), f2, the selector, the payload, a checksum."""
    body = bytes([0xf2, sel]) + payload + b"\0"
    return "f" + (bytes([0x98, len(body)]) + body).hex()


def seek(a, idx=0):
    return _frame(0x98 | idx, bytes([0]) + struct.pack("<I", a))


def verb(v, idx=0):
    return _frame(0x98 | idx, bytes([v]))


def play(a, d, rate=0x5000, idx=0):
    return _frame(0x98 | idx, bytes([0]) + struct.pack("<IIH", a, d, rate))


# batman 1.14's show 0x1c (0x2fa84): seek 0x1e4, then play 0x1e4..0x1f0 once
# (verb 2), with the rate word its channel layer sends (0x5000: no fps code
# the panel knows, so the model's 30 fps).
BATPHONE = [seek(0x1e4), verb(2), play(0x1e4, 0x1f0)]


def test_the_bat_phone_show_reaches_the_end_of_its_range(cbin):
    got = _run(cbin, ["t1000"] + BATPHONE + ["p0", "t1200", "p0", "t1399", "p0",
                                             "t1400", "p0", "t9000", "p0"])
    assert got == [(1000, 0x1e4, 1), (1200, 0x1e4 + 6, 1), (1399, 0x1e4 + 11, 1),
                   (1400, 0x1f0, 1), (9000, 0x1f0, 1)]
    # the game's wait (0x4988e4) ends when the position leaves [A, D)
    assert not (0x1e4 <= got[-1][1] < 0x1f0)


def test_a_seek_holds_still(cbin):
    assert _run(cbin, ["t0", seek(54), "p0", "t60000", "p0"]) == [(0, 54, 1), (60000, 54, 1)]


def test_a_looping_play_wraps_and_never_ends(cbin):
    got = _run(cbin, ["t0", verb(1), play(0x598, 0x59a, rate=43), "p0",
                      "t40", "p0", "t70", "p0", "t100000", "p0"])
    # 43 is the 30 fps code: one step every 33 ms, two positions, wrapping
    assert got == [(0, 0x598, 1), (40, 0x599, 1), (70, 0x598, 1), (100000, 0x598, 1)]


def test_nothing_commanded_is_not_known(cbin):
    """The old asset echo answers a display the model has not heard of."""
    assert _run(cbin, ["t0", "p0", verb(2), "p0"]) == [(0, 0, 0), (0, 0, 0)]


def test_hold_then_carry_on(cbin):
    # 30 fps: 334 ms is ten steps; held at 110 however long, then ten more
    got = _run(cbin, ["t0", verb(2), play(100, 200, rate=43), "t334", verb(4),
                      "t5000", "p0", verb(5), "t5334", "p0"])
    assert got == [(5000, 110, 1), (5334, 120, 1)]


def test_each_display_index_keeps_its_own(cbin):
    got = _run(cbin, ["t0", seek(7, idx=1), verb(2), play(10, 20, rate=43),
                      "t5000", "p0", "p1"])
    assert got == [(5000, 20, 1), (5000, 7, 1)]
