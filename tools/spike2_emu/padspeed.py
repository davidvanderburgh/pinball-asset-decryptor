#!/usr/bin/env python3
"""padspeed.py - run the emulated game's clock faster (or slower) than the wall's.

    padspeed.py                  the speed in effect, and the one asked for
    padspeed.py 4                ask for 4x; waits until the game has taken it up
    padspeed.py 1                back to real time
    padspeed.py 0.5              slow motion
    padspeed.py --when-up 4      wait until the game is past its boot, then ask
                                 (what watch.sh runs for PAD_SPEED=4)

PAD-484. David, 2026-10-09: "Need a way of sweeping a spike 2 image much much
faster" - PAD-420's sweep of the newest builds was 581 rig jobs and 52
rig-hours. Measured first: a hidden rig in a game costs about half a core, and
the game is WAITING, not starved - on a Tech Alerts screen, a ball saver, a
30 s mode. So the shim runs every clock the game reads, and every wait it
makes, k times fast (hwshim.c, "GAME SPEED"); this asks for k through the
shared switch block (padsw.h speed_req) and reads the answer (speed_now).

THE BOOT RUNS AT 1x and --when-up is why: a boot interleaves waits on the
game's clock with work bound to the wall (the validator reading the card, the
scene loading), and running the first fast reorders the two (UP_STATES says
how that ended). Once the game is in attract it has everything a game needs and
is waiting on its own clock - ball savers, a 30 s mode, a drain - and that is
the time this takes back.

The harness's own physical times follow: swpoke.py's press, plunge.py's coins
and lane, ballfeed.py's flight and way home, gamecheck.sh's gaps all read the
speed and shorten by the same k (padsw.game_sleep, padpath.sh pad_gsleep).
"""
import os
import struct
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import padsw

RIG = os.path.dirname(os.path.abspath(__file__))

#: THE STATE THAT MEANS THE BOOT IS DONE: attract - the game's own light show
#: running (gamestate.sh). NOT techalerts, which gamestate says from the video
#: bring-up probe at the very start of the boot. A boot is two kinds of work
#: interleaved: waits on the game's clock (the node bus probes, Tech Alerts) and
#: work bound to the wall (the validator reading the card, ~20 s of scene
#: loading through the card mount). Sped up from techalerts, Godzilla Pro 1.16
#: reached attract BEFORE its auto-loaded scenes were in - 39 s against the
#: scenes' 48-64 s - took a Start, and died on a null scene lookup
#: (game+0x526f0) four seconds into the game, every time. At 1x attract comes
#: after the loading, so from attract on the game has everything a game needs.
UP_STATES = ("attract",)


def parse_speed(text):
    """'4', '4x', 'x4', '0.5' -> 4.0 / 0.5. 0.1 .. 64, as the shim clamps."""
    t = text.strip().lower().strip("x")
    k = float(t)
    if not 0.1 <= k <= 64:
        raise ValueError("a speed is 0.1 .. 64, not %s" % text)
    return k


def show(m):
    asked = struct.unpack_from("<I", m, padsw.OFF_SPEED_REQ)[0]
    print("speed x%.3f%s" % (padsw.speed(m),
                             "" if not asked else " (asked x%.3f)" % (asked / 1000.0)))


def ask(m, k, wait=10.0):
    """Ask for k and wait for the shim's answer. 0 when it took it."""
    padsw.request_speed(m, k)
    end = time.monotonic() + wait
    want = int(round(k * 1000))
    while time.monotonic() < end:
        now = struct.unpack_from("<I", m, padsw.OFF_SPEED_NOW)[0] or 1000
        if now == want:
            print("speed x%.3f: the game took it up" % k)
            return 0
        time.sleep(0.05)
    print("speed x%.3f asked; the game has not taken it up in %.0f s (is it running?)"
          % (k, wait))
    return 1


def state():
    try:
        out = subprocess.run(["bash", os.path.join(RIG, "status.sh")],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""
    for line in out.splitlines():
        if line.startswith("state="):
            return line[6:].strip()
    return ""


def when_up(k, limit=900.0):
    """Wait for the game to reach its first screen, then ask for k."""
    t0 = time.monotonic()
    seen = False
    while time.monotonic() - t0 < limit:
        st = state()
        if st in UP_STATES:
            m = padsw.open_block()
            if m is not None:
                print("[speed] the game is up (%s) after %.0f s: asking x%.3f"
                      % (st, time.monotonic() - t0, k))
                sys.stdout.flush()
                rc = ask(m, k)
                m.close()
                return rc
        if st and st != "off":
            seen = True
        elif seen:
            print("[speed] the run ended before the game was up")
            return 1
        time.sleep(1.0)
    print("[speed] the game was not up after %.0f s; the run stays at 1x" % limit)
    return 1


def main(argv):
    if len(argv) > 1 and argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    if len(argv) > 2 and argv[1] == "--when-up":
        return when_up(parse_speed(argv[2]))
    m = padsw.open_block()
    if m is None:
        return 2
    try:
        if len(argv) > 1:
            return ask(m, parse_speed(argv[1]))
        show(m)
        return 0
    finally:
        m.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
