"""`cmd 70` carries a 16-bit level, and both decoders have to read both bytes.

PAD-125. The shim read `p[4]` alone for the whole life of this rig and nothing
caught it, because the two titles it was measured on - godzilla_pro and
turtles_pro - only ever send this command to CLEAR a lamp, and the low byte of
0x0000 is 0 whichever half you read. A HOME EDITION drives its entire attract
picture through it: jurassic_park_the_pin 1.05 holds nine lamps up and seven of
them carry a low byte of 0x00, so the virtual playfield drew two of nine, at
2/255 and 3/255. That is the ticket ("only 2 static LEDs lit in attract mode")
and these are the frames off its own wire.

Two things are pinned here:
  * THE LEVELS THEMSELVES, against the captured frames and the ladder they
    walk. A change to the full-scale constant that makes BACKPANEL FLASH stop
    reading as full brightness fails on a real frame, not on a made-up one.
  * THE TWO IMPLEMENTATIONS ARE TWINS. hwshim.c's led_level70 is compiled out
    of the real source file - never copied into this test - and run against
    leddecode.level70 over the same bytes, the same standing rule
    test_spike2_led_wide_twins.py holds the swelf grammar to.
"""
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")

sys.path.insert(0, RIG)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

#: Real `cmd 70` frames off node 8, captured with PAD_NB_LOG raised on
#: jurassic_park_the_pin 1.05 (2026-09-10, PAD-125). Every lamp the game holds
#: up in attract, plus one of the clear sweep's zeros. The last column is what
#: the lamp is called in the title's own device table.
PIN_FRAMES = [
    ("880570110004ee00", 17, 0x0400, "LEFT RAMP H"),
    ("880570120004ed00", 18, 0x0400, "LEFT RAMP RESCUE"),
    ("880570130004ec00", 19, 0x0400, "BRACHIOSAURUS MODE"),
    ("880570140004eb00", 20, 0x0400, "2X"),
    ("8805701c0207de00", 28, 0x0702, "STEGOSAURUS MODE"),
    ("8805701d0005e100", 29, 0x0500, "PTERANODON MODE"),
    ("8805701e0005e000", 30, 0x0500, "DOUBLE SCORE"),
    ("880570260008d500", 38, 0x0800, "BACKPANEL FLASH"),
    ("880570270303d600", 39, 0x0303, "GALLIMIMUS MODE"),
    ("8805702e0000d500", 46, 0x0000, "SPINO ARROW"),
]

#: Every distinct value seen on the wire across both Home Editions, 10728
#: writes on nodes 8 and 12. The high byte walks 0..8 and stops, which is the
#: whole evidence for 0x800 being full brightness.
LADDER = (0x0000, 0x0200, 0x0303, 0x0400, 0x0500,
          0x0600, 0x0700, 0x0702, 0x0800)


def _level(v):
    import leddecode
    return leddecode.level70(v & 0xFF, v >> 8)


def test_the_two_bytes_are_one_little_endian_field():
    """The low byte alone is what the shim used to read, and it is not it."""
    import leddecode
    # 0x0400 and 0x0800 differ only in the HIGH byte, and they are different
    # brightnesses; both have a low byte of zero, which used to read as OFF.
    assert leddecode.level70(0x00, 0x04) != leddecode.level70(0x00, 0x08)
    assert leddecode.level70(0x00, 0x04) > 0
    assert leddecode.level70(0x00, 0x08) > 0


def test_a_clear_is_still_a_clear():
    """godzilla_pro and turtles_pro send nothing else; they must not move."""
    assert _level(0x0000) == 0


def test_full_scale_is_0x800():
    assert _level(0x0800) == 255
    assert _level(0x0400) == 127                 # half
    assert _level(0x0200) == 63                  # a quarter


def test_anything_past_full_scale_clamps_rather_than_wraps():
    """A wrap here would render a title's brightest lamp as its darkest."""
    for v in (0x0801, 0x0fff, 0x8000, 0xffff):
        assert _level(v) == 255


def test_the_ladder_is_monotonic():
    """Eight rungs in, eight brightnesses out, in order.

    0x0700 and 0x0702 are DELIBERATELY allowed to collapse: they are two parts
    in 2048 apart and cannot survive a trip through an 8-bit plane, which is
    why the rungs are counted by high byte and not by raw value.
    """
    levels = [_level(v) for v in LADDER]
    assert levels == sorted(levels)
    rungs = {v >> 8: _level(v) for v in LADDER}
    assert len(set(rungs.values())) == len(rungs) == 8


@pytest.mark.parametrize("frame,idx,v16,name", PIN_FRAMES,
                         ids=[f[3] for f in PIN_FRAMES])
def test_the_pin_attract_frames(frame, idx, v16, name):
    """Every lamp The Pin holds up in attract, off its own wire."""
    import leddecode
    b = bytes.fromhex(frame)
    assert len(b) == 8 and b[2] == 0x70
    assert b[3] == idx
    assert b[4] | (b[5] << 8) == v16
    lit = leddecode.level70(b[4], b[5]) > 0
    assert lit == (v16 != 0), "%s: %#06x must read as %s" % (
        name, v16, "lit" if v16 else "off")


def test_nine_of_the_pins_lamps_light_where_two_did():
    """The ticket, as a number. The old reading was `lo` and it gave two."""
    import leddecode
    frames = [bytes.fromhex(f[0]) for f in PIN_FRAMES]
    now = sum(1 for b in frames if leddecode.level70(b[4], b[5]))
    was = sum(1 for b in frames if b[4])
    assert (was, now) == (2, 9)


# ---- THE TWO IMPLEMENTATIONS ARE TWINS ----------------------------------

HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>

%s

int main(int argc, char **argv)
{
    unsigned v = (unsigned)strtoul(argv[1], 0, 16);
    printf("%%u\n", led_level70(v & 0xff, v >> 8));
    return 0;
}
"""


@pytest.fixture(scope="module")
def cbin(tmp_path_factory):
    twins = pytest.importorskip("test_spike2_led_wide_twins")
    if not twins.CC:
        pytest.skip("no C compiler on this host")
    d = tmp_path_factory.mktemp("level70")
    src = d / "twin.c"
    src.write_text(HARNESS % twins._extract("led_level70"), encoding="utf-8")
    exe = d / ("twin.exe" if os.name == "nt" else "twin")
    r = subprocess.run([twins.CC, "-O1", "-o", str(exe), str(src)],
                       capture_output=True, text=True)
    assert r.returncode == 0, "the shim's own reader did not compile:\n" + r.stderr
    return str(exe)


def test_c_and_python_agree_on_every_value(cbin):
    """The ladder, the boundaries either side of full scale, and the ends."""
    import leddecode
    args = [cbin]
    mismatch = []
    for v in list(LADDER) + [0, 1, 0x7ff, 0x800, 0x801, 0xfff, 0x1000, 0xffff]:
        r = subprocess.run(args + ["%04x" % v], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        c = int(r.stdout.strip())
        p = leddecode.level70(v & 0xFF, v >> 8)
        if c != p:
            mismatch.append((hex(v), c, p))
    assert not mismatch, "C and Python disagree: %s" % mismatch
