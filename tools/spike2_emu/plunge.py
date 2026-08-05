#!/usr/bin/env python3
"""plunge.py [start|plunge|reset] - move a virtual ball the way the machine does.

There is no ball, so "plunging" means telling the game the switch story a real
plunge tells:

  the ball leaves the trough      one held trough switch OPENS   (66..71)
  it arrives in the shooter lane  Shooter Lane CLOSES            (62)
  the player plunges              Shooter Lane OPENS             (62)

  start   pulse the Start button (36). The game then fires the trough eject
          itself, so run `plunge` a moment later to give it the ball.
  plunge  the three steps above, on the lowest-numbered trough ball still held.
  reset   put six balls back in the trough and shut the coin door - the
          machine-at-rest set, same as swinit.py.

TROUGH SWITCHES ARE LATCHED, NOT PULSED, which is the whole reason this is a
script and not three swpoke calls: a ball sitting in the trough holds its switch
closed for as long as it is there. swpoke.py pulses and would put the ball back.

The order matters and is not arbitrary: open the trough switch BEFORE closing
the shooter lane. A real ball cannot be in both places, and the game's ball
accounting notices.
"""
import mmap
import struct
import sys
import time

PATH = "/home/david/spike2root/dump/padsw"
MAGIC = 0x53444150
OFF_GEN, OFF_HELD = 4, 8

START, SHOOTER, TROUGH_JAM = 36, 62, 72
TROUGH = (71, 70, 69, 68, 67, 66)        # Trough 1..6; 1 is nearest the eject
REST = (33,) + TROUGH                    # coin door shut, six balls loaded

#: Long enough for the game's own ball-search and switch debounce to see each
#: step as a separate event rather than one glitch.
STEP_S = 0.45
LANE_S = 1.2


def _open():
    f = open(PATH, "r+b")
    m = mmap.mmap(f.fileno(), 4096)
    if struct.unpack_from("<I", m, 0)[0] != MAGIC:
        print("bad magic - is the emulator running?")
        return None
    return m


def _set(m, sw, val):
    m[OFF_HELD + sw] = 1 if val else 0
    struct.pack_into("<I", m, OFF_GEN,
                     struct.unpack_from("<I", m, OFF_GEN)[0] + 1)
    m.flush()


def do_start(m):
    _set(m, START, 1)
    time.sleep(0.15)
    _set(m, START, 0)
    print("Start pressed")


def do_plunge(m):
    ball = next((s for s in TROUGH if m[OFF_HELD + s]), None)
    if ball is None:
        print("no ball in the trough - run `plunge.py reset` first")
        return 1
    _set(m, ball, 0)
    print("trough switch %d opened (ball out)" % ball)
    time.sleep(STEP_S)
    _set(m, SHOOTER, 1)
    print("shooter lane closed (ball waiting)")
    time.sleep(LANE_S)
    _set(m, SHOOTER, 0)
    print("shooter lane opened (ball launched)")
    return 0


def do_reset(m):
    for s in range(1, 256):
        m[OFF_HELD + s] = 0
    for s in REST:
        m[OFF_HELD + s] = 1
    struct.pack_into("<I", m, OFF_GEN,
                     struct.unpack_from("<I", m, OFF_GEN)[0] + 1)
    m.flush()
    print("six balls in the trough, coin door shut")


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "plunge"
    m = _open()
    if m is None:
        return 1
    rc = 0
    if what == "start":
        do_start(m)
    elif what == "reset":
        do_reset(m)
    else:
        rc = do_plunge(m)
    m.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
