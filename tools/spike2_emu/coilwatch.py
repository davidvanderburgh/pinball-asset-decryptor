"""Watch every coil counter in dump/padled and print each one that moves.

WHY A COUNTER AND NOT A LEVEL: hwshim's coil_publish() bumps a per-(node,index)
byte for every fire frame it decodes. A coil is addressed for tens of
milliseconds, so a level would be missed about half the time at any sane poll
rate; a counter cannot be missed, only coalesced. Same argument ballfeed makes.

WHY THIS EXISTS SEPARATELY FROM ballfeed: ballfeed asks device_xy.txt which
(node, index) the trough eject is, and turtles_pro's table has 0 records, so it
has no address to watch. This watches ALL of them and lets the GAME say which
one it is - the eject is whatever fires when a game starts with a full trough,
and the auto plunger is whatever fires when the action button is pressed with a
ball in the lane.

    python3 coilwatch.py [seconds] [poll_ms]
"""
import os
import sys
import time

PATH = os.path.expanduser("~/spike2root/dump/padled")
COIL_OFF = 1556
N = 512

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
poll = (float(sys.argv[2]) if len(sys.argv) > 2 else 50.0) / 1000.0


def read():
    with open(PATH, "rb") as f:
        return f.read()[COIL_OFF:COIL_OFF + N]


prev = read()
t0 = time.monotonic()
sys.stdout.write("[coil] watching %d counters for %.0f s\n" % (N, secs))
sys.stdout.flush()
while time.monotonic() - t0 < secs:
    time.sleep(poll)
    cur = read()
    if cur == prev:
        continue
    for i in range(N):
        if cur[i] != prev[i]:
            sys.stdout.write("[coil] %7.2fs offset %3d  %3d -> %3d\n"
                             % (time.monotonic() - t0, i, prev[i], cur[i]))
    sys.stdout.flush()
    prev = cur
sys.stdout.write("[coil] done\n")
