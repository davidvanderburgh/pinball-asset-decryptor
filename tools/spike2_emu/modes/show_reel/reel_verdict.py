#!/usr/bin/env python3
"""PAD-1476: the show reel's verdict for one build - which of the game's mode shows lit the playfield on their own.

    reel_verdict.py <reel dir of one build (led.txt, mode.log)> [--write]

For each show: the LED view's changes per second and the lamps lit while it played (0.3-2.8 s after its "on" line)
against the 2.5 s gap before it. LIT when 6 or more lamps more are lit, or the changes run 1.25 times faster. Godzilla
LE 1.16 (2026-11-20): the 7 that lit added 10 to 64 lamps (210, 214-217, 249, 319); the 15 that did not stayed within
3 lamps of the gap (Hedorah's 211 checks that Hedorah runs, and stops at once). A REFUSED show (a show of the game's
own of a higher priority was playing) is not lit. --write puts the lit ones in the build's port (port_show_numbers.py
lit), the directory's name being the port's key.
"""
import os
import re
import subprocess
import sys

LAMPS, RATIO = 6, 1.25


def verdict(d):
    rows, ons = [], []
    for ln in open(os.path.join(d, "led.txt"), errors="replace"):
        p = ln.split(" ", 2)
        if len(p) < 3:
            continue
        if p[1] == "LOG":
            m = re.search(r"show reel: #(\d+) on", p[2])
            if m:
                ons.append((int(p[0]), int(m.group(1)), "REFUSED" in p[2]))
        elif p[1] != "DRV":
            q = ln.split()
            rows.append((int(q[0]), int(q[1]), int(q[2])))

    def win(a, b):
        r = [x for x in rows if a <= x[0] < b]
        return sum(x[1] for x in r) * 1000.0 / max(1, b - a), sum(x[2] for x in r) / max(1, len(r))

    out = []
    for t, n, refused in ons:
        bc, bl = win(t - 2500, t)
        ac, al = win(t + 300, t + 2800)
        ratio = ac / bc if bc else (9.9 if ac else 1.0)
        lit = not refused and (al - bl >= LAMPS or ratio >= RATIO)
        out.append((n, "REFUSED" if refused else "lit" if lit else "dark", bc, ac, ratio, bl, al))
    return out


def main(argv):
    d = argv[1].rstrip("/\\")
    rows = verdict(d)
    for n, v, bc, ac, ratio, bl, al in rows:
        print("#%-4d %-7s led %8.1f -> %8.1f /s (x%.2f)  lit %6.1f -> %6.1f" % (n, v, bc, ac, ratio, bl, al))
    lit = sorted(n for n, v, *_r in rows if v == "lit")
    print("lit (%d of %d): %s" % (len(lit), len(rows), " ".join(map(str, lit))))
    if "--write" in argv:
        if not rows:
            sys.exit("no reel lines: nothing written")
        tool = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "port_show_numbers.py")
        subprocess.check_call([sys.executable, tool, "lit", os.path.basename(d)] + [str(n) for n in lit])


if __name__ == "__main__":
    main(sys.argv)
