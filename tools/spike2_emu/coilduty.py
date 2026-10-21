#!/usr/bin/env python3
"""coilduty.py <log> [node coil] - how long a drive really ran, from a run's [coildrive] lines (PAD-670).

Point it at a gzwatch.log (or a grep of its [coildrive] lines) from a run with PAD_COIL_PROBE=1 (hwshim.c). The
default drive is node 1 coil 0, the cabinet board's shaker motor on every Spike 2 title (PAD-474). A fire runs its
pulse + hold from its time, a later fire replaces what was left (as the board does), an OFF ends it. Prints the total,
the busiest 60 s, the longest unbroken run and each minute's running time.

Run it at real time (rigbatch --speed 1, or a plain watch.sh run): the lines' times are the wall's, the fires' lengths
the game's, so at 4x the two disagree."""
import re
import sys

FIRE = re.compile(r"\[coildrive\] (\d+) ms node (\d+) coil (\d+): "
                  r"pulse (\d+)/255 for (\d+) ms, hold (\d+)/255 for (\d+) ms")
OFF = re.compile(r"\[coildrive\] (\d+) ms node (\d+) coil (\d+): OFF")


def runs(lines, node=1, coil=0):
    """The drive's unbroken runs, [start, end] in the log's ms."""
    out, cur = [], None
    for ln in lines:
        m = FIRE.search(ln)
        if m and (int(m[2]), int(m[3])) == (node, coil):
            t, ms = int(m[1]), int(m[5]) + int(m[7])
            if cur and cur[1] > t:
                cur[1] = t + ms
            else:
                if cur:
                    out.append(cur)
                cur = [t, t + ms]
            continue
        m = OFF.search(ln)
        if m and (int(m[2]), int(m[3])) == (node, coil) and cur and cur[1] > int(m[1]):
            cur[1] = int(m[1])
    if cur:
        out.append(cur)
    return [r for r in out if r[1] > r[0]]


def on_in(rs, a, b):
    """ms the drive ran between a and b"""
    return sum(max(0, min(e, b) - max(s, a)) for s, e in rs)


def busiest(rs, window=60000):
    """(ms, start) of the busiest window: it starts at some run's start"""
    best = (0, rs[0][0] if rs else 0)
    for s, _e in rs:
        v = on_in(rs, s, s + window)
        if v > best[0]:
            best = (v, s)
    return best


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    node, coil = (int(argv[1]), int(argv[2])) if len(argv) > 2 else (1, 0)
    with open(argv[0], errors="replace") as f:
        rs = runs(f, node, coil)
    if not rs:
        print("node %d coil %d never ran" % (node, coil))
        return 1
    t0, t1 = rs[0][0], rs[-1][1]
    best, at = busiest(rs)
    lon = max(rs, key=lambda r: r[1] - r[0])
    print("node %d coil %d: %d runs over %.1f s, %.1f s running in all" % (node, coil, len(rs), (t1 - t0) / 1000,
                                                                          sum(e - s for s, e in rs) / 1000))
    print("busiest 60 s: %.2f s running, from %.1f s" % (best / 1000, (at - t0) / 1000))
    print("longest unbroken run: %.2f s, at %.1f s" % ((lon[1] - lon[0]) / 1000, (lon[0] - t0) / 1000))
    m = 0
    while t0 + m * 60000 < t1:
        print("  minute %d: %.2f s" % (m, on_in(rs, t0 + m * 60000, t0 + (m + 1) * 60000) / 1000))
        m += 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
