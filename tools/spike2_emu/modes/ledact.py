#!/usr/bin/env python3
"""ledact.py [seconds] [interval_ms] - how much the playfield LEDs are DOING, from dump/padled.

A light show is change: levels moving and fade pulses firing. This samples the shim's
padled block (padled.h: gen at 8, val[16][96] at 20, fade_head at 2076) and prints,
per interval, how many (node, index) levels changed and how many fade pulses the
wire carried, then the totals and the busiest nodes.

THE NUMBERS ONLY MEAN SOMETHING AGAINST A CONTROL. Attract and a game in progress
animate the lamps all the time, so a window with a show is judged against a window
without one, taken the same way on the same run. Validated on a labelled example
before it judged a mode of ours: a baseline window against the window after tesla
strike is forced on (item 125, MODE_API.md).

Read-only; runs inside WSL beside a live run.
"""
import os
import struct
import sys
import time

VAL_OFF, NODES, IDX = 20, 16, 96
GEN_OFF, FADE_HEAD_OFF = 8, 2076
MAGIC = 0x44454C50


def led_path():
    if os.environ.get("PAD_LED"):
        return os.environ["PAD_LED"]
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        import padpath
        d = padpath.dump()
        if d:
            return os.path.join(d, "padled")
    except Exception:
        pass
    return "/home/david/spike2root/dump/padled"


def sample(path):
    with open(path, "rb") as f:
        b = f.read(4096)
    if len(b) < 2080 or struct.unpack_from("<I", b, 0)[0] != MAGIC:
        return None
    return (struct.unpack_from("<I", b, GEN_OFF)[0], b[VAL_OFF:VAL_OFF + NODES * IDX],
            struct.unpack_from("<I", b, FADE_HEAD_OFF)[0])


def main(argv):
    secs = float(argv[0]) if argv else 10.0
    step = (float(argv[1]) if len(argv) > 1 else 250.0) / 1000.0
    path = led_path()
    prev = sample(path)
    if prev is None:
        print("no padled block at %s (is a run up?)" % path)
        return 2
    t0 = time.monotonic()
    tot_changed = tot_fades = tot_gen = 0
    per_node = [0] * NODES
    while time.monotonic() - t0 < secs:
        time.sleep(step)
        cur = sample(path)
        if cur is None:
            print("padled went away")
            return 2
        changed = 0
        for i, (a, c) in enumerate(zip(prev[1], cur[1])):
            if a != c:
                changed += 1
                per_node[i // IDX] += 1
        fades = (cur[2] - prev[2]) & 0xFFFFFFFF
        gen = (cur[0] - prev[0]) & 0xFFFFFFFF
        tot_changed += changed
        tot_fades += fades
        tot_gen += gen
        print("t=%5.2f  levels changed %4d  fade pulses %3d  writes %5d" % (time.monotonic() - t0, changed, fades, gen))
        prev = cur
    el = time.monotonic() - t0
    busiest = sorted(((n, k) for k, n in enumerate(per_node) if n), reverse=True)[:6]
    print("TOTAL over %.1f s: levels changed %d (%.1f/s), fade pulses %d (%.1f/s), writes %d (%.0f/s)"
          % (el, tot_changed, tot_changed / el, tot_fades, tot_fades / el, tot_gen, tot_gen / el))
    print("busiest nodes (changes): " + ", ".join("node %d: %d" % (k, n) for n, k in busiest))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
