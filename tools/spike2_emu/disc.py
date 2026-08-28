#!/usr/bin/env python3
"""disc.py [degrees] [ms] - spin james_bond_60th_le's ODDJOB DISC.

THE MECHANISM THIS EXISTS FOR. Bond's Oddjob disc is a large rotating platform,
and it is NOT a switch closure - there is nothing on the playfield to click and
nothing in the switch matrix to press, which is exactly how it was reported
(David, 2026-08-28: "I don't see the optos on the playfield or the switch
matrix for me to interact with"). It is read by an ABSOLUTE ANGLE SENSOR whose
value the game differentiates into "steps".

WHAT SAYS SO, all from the game's own binary:

    "SPIN TO UPDATE ANGLE" / "ANGLE: %s"    its service test's live readout
    "ANGLE SENSOR XYZ0" / "XYZ1" / "FS"     register names of an angle-sensor
    "ANGLE SENSOR ENABLE"                   IC, not a switch
    "ANGLE SENSOR 0".."ANGLE SENSOR 9"      ten bits of angle
    "Angle Sensor Weak" / "... Threshold"   magnet-weak and AGC status bits

    DISC SPIN DIFFICULTY
      "How much does it take the disc to spin to count as a step."
    DISC SENSITIVITY THRESHOLD
      "How many steps the disc will hold before reporting the value to the
       game.  Use to filter out playfield vibration movements."

A magnet-over-die rotary sensor (AS5600 and friends) reports exactly this
shape: an absolute angle word plus magnet-strength status. So "spinning the
disc" is not pressing anything - it is WALKING THE ANGLE WORD, and the game
counts the delta.

THE WIRE. Switch ids 98..107 are ANGLE SENSOR 0..9 on node 9 bits 32..41, and
they are ordinary entries in the switch block, so the existing script region
drives them - no shim change. id 108 is Weak and 109 is Threshold; both are
left alone, because 0 = "the magnet is fine" and inventing a fault is not this
tool's job.

  disc.py             one 360 degree revolution at the default rate
  disc.py 90          a quarter turn
  disc.py 720 8       two turns, 8 ms per step (a hard rip)
  disc.py -180        the other way

BIT ORDER IS ASSUMED, NOT MEASURED, and it is the one thing here that a run
could still contradict: id 98 is taken as bit 0. If it is the other way round a
ramp still MOVES the angle - every value still changes - so the disc still
spins and still counts; what would be wrong is the reported ANGLE matching the
degrees asked for. The service test's "ANGLE: %s" readout is what settles it,
and until someone reads that screen this tool says degrees and means steps.
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import padsw

#: Switch ids of the angle word, LSB first. See the header on bit order.
ANGLE_IDS = tuple(range(98, 108))

#: The word is 10 bits, so a full revolution is 1024 counts.
FULL_TURN = 1 << len(ANGLE_IDS)

#: Milliseconds between successive angle values. 12 ms is about 85 updates a
#: second, comfortably inside the node scan and fast enough that the game's own
#: "how much does it take to spin" filter sees continuous motion rather than a
#: series of jumps it might discard as vibration.
DEFAULT_MS = 12

#: Degrees of a whole turn, so the CLI can speak in degrees.
DEGREES = 360.0


def read_angle(m):
    """The angle word the game is currently being handed, 0..1023."""
    v = 0
    for bit, sw in enumerate(ANGLE_IDS):
        if padsw.merged(m, sw):
            v |= 1 << bit
    return v


def write_angle(m, value):
    """Publish one angle word. One bump for the whole word, not ten.

    All ten bits move as a unit or the game sees a value that never existed -
    ramping 0x0FF to 0x100 one bit at a time passes through 0x1FF, a jump of
    half a revolution, which is exactly the kind of spike the title's
    DISC SENSITIVITY THRESHOLD adjustment exists to reject.
    """
    value %= FULL_TURN
    for bit, sw in enumerate(ANGLE_IDS):
        m[padsw.OFF_SCR_HELD + sw] = 1 if value & (1 << bit) else 0
    padsw.bump(m)
    return value


def spin(m, degrees=DEGREES, ms=DEFAULT_MS, start=None):
    """Walk the angle through `degrees`, returning where it stopped."""
    counts = int(round(FULL_TURN * (degrees / DEGREES)))
    step = 1 if counts >= 0 else -1
    here = read_angle(m) if start is None else start
    for _ in range(abs(counts)):
        here = write_angle(m, here + step)
        time.sleep(ms / 1000.0)
    return here


def main():
    deg = float(sys.argv[1]) if len(sys.argv) > 1 else DEGREES
    ms = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_MS
    m = padsw.open_block()
    if m is None:
        return 1
    padsw.set_source("disc")
    was = read_angle(m)
    now = spin(m, deg, ms)
    print("angle %d -> %d (%.0f deg over %d counts at %g ms)"
          % (was, now, deg, int(round(FULL_TURN * deg / DEGREES)), ms))
    return 0


if __name__ == "__main__":
    sys.exit(main())
