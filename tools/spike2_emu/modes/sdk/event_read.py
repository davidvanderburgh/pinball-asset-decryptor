#!/usr/bin/env python3
"""event_read.py - read event_probe.c's log: which event ids fired in which marked window.

    event_read.py event.log [--callers args.txt] [--id 0x34 ...] [--diff A B]

event_probe.c logs every registration on the game's event bus (`sub`), the first calls
of each id in a window (`disp`), and, at each mark, the closing window's per-id counts
(`window <label> <ms> ms: id=count ...`). This prints:

  1. every window with the ids that fired in it, leaving out the BACKGROUND ids (those
     firing in nearly every window, such as the tick's own two) so what a mark caused
     stands out;
  2. per id: the windows it fired in, its handlers and priorities (from `sub` and the
     table dump), and, with --callers, the functions that dispatch it statically
     (`armxref.py args <elf> <dispatch>` output);
  3. with --diff A B: ids in window A and not in B (a press and its control).

An id is named from this, never from its handlers' names: a drain tells the end of a
ball from the next ball's start by WHEN it fires (right after the drain, or ~10 s later).
"""
import argparse
import collections
import re
import sys

WINDOW = re.compile(r"^(\d+) window (\S+) (\d+) ms:(.*)$")
SUB = re.compile(r"^(\d+) sub id=0x([0-9a-f]+) handler=0x([0-9a-f]+) prio=(\d+) r0=0x([0-9a-f]+) lr=0x([0-9a-f]+) tid=(\d+)")
DISP = re.compile(r"^(\d+) disp id=0x([0-9a-f]+) arg=0x([0-9a-f]+) lr=0x([0-9a-f]+) tid=(\d+) p=(\d+) mask=0x([0-9a-f]+)")
TABLE = re.compile(r"^(\d+) table\(([^)]*)\) id=0x([0-9a-f]+):(.*)$")
ARGS = re.compile(r"^\s*(bl|b)\s+0x([0-9a-f]+)\s+fn 0x([0-9a-f?]+)(?: \((.*?)\))?\s+r0=0x([0-9a-f]+)")


def parse(path):
    windows, subs, disps, table = [], collections.defaultdict(list), collections.defaultdict(list), {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            m = WINDOW.match(line)
            if m:
                counts = {}
                for tok in m.group(4).split():
                    k, v = tok.split("=")
                    counts[int(k, 16)] = int(v)
                windows.append((m.group(2), int(m.group(3)), int(m.group(1)), counts))
                continue
            m = SUB.match(line)
            if m:
                subs[int(m.group(2), 16)].append((int(m.group(3), 16), int(m.group(4)), int(m.group(6), 16)))
                continue
            m = DISP.match(line)
            if m:
                disps[int(m.group(2), 16)].append((int(m.group(1)), int(m.group(3), 16), int(m.group(4), 16),
                                                   int(m.group(5)), int(m.group(6)), int(m.group(7), 16)))
                continue
            m = TABLE.match(line)
            if m and int(m.group(3), 16) not in table:
                table[int(m.group(3), 16)] = m.group(4).split()
    return windows, subs, disps, table


def callers(path):
    out = collections.defaultdict(list)
    if not path:
        return out
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = ARGS.match(line)
            if m:
                out[int(m.group(5), 16)].append("0x%s%s" % (m.group(3), " " + m.group(4) if m.group(4) else ""))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("log")
    ap.add_argument("--callers", help="armxref.py args output for the dispatch function")
    ap.add_argument("--id", action="append", default=[], help="show only these ids in section 2")
    ap.add_argument("--diff", nargs=2, action="append", default=[], metavar=("A", "B"))
    ap.add_argument("--background", type=float, default=0.8,
                    help="an id firing in at least this share of windows is background (0.8)")
    a = ap.parse_args(argv)
    windows, subs, disps, table = parse(a.log)
    stat = callers(a.callers)
    if not windows:
        print("no windows in %s (no marks consumed?)" % a.log)
    seen = collections.Counter()
    for _label, _ms, _at, counts in windows:
        seen.update(counts.keys())
    background = {i for i, n in seen.items() if windows and n >= a.background * len(windows)}
    print("== registrations: %d on %d ids; background ids (in >= %d%% of %d windows): %s" % (
        sum(len(v) for v in subs.values()), len(subs), int(a.background * 100), len(windows),
        " ".join("0x%02x" % i for i in sorted(background)) or "none"))
    print("\n== 1. windows")
    for label, dur, at, counts in windows:
        fg = ["%02x=%d" % (i, c) for i, c in sorted(counts.items()) if i not in background]
        bg = ["%02x=%d" % (i, counts[i]) for i in sorted(background) if i in counts]
        print("%-14s %6d ms @%7d  %s   [bg %s]" % (label, dur, at, " ".join(fg) or "-", " ".join(bg)))
    print("\n== 2. ids")
    want = {int(x, 0) for x in a.id}
    for i in sorted(set(seen) | set(subs) | set(want)):
        if want and i not in want:
            continue
        where = ["%s:%d" % (label, counts[i]) for label, _d, _a, counts in windows if i in counts]
        hs = subs.get(i, [])
        print("0x%02x (%3d)  windows %s" % (i, i, " ".join(where) or "never"))
        if hs:
            print("      handlers %s" % " ".join("0x%x/p%d" % (h, p) for h, p, _lr in hs))
        elif i in table:
            print("      table %s" % " ".join(table[i]))
        for t, arg, lr, tid, p, mask in disps.get(i, [])[:3]:
            print("      call @%d arg=0x%x lr=0x%x tid=%d player=%d mask=0x%04x" % (t, arg, lr, tid, p, mask))
        if stat.get(i):
            print("      dispatched from %s" % ", ".join(sorted(set(stat[i]))[:6]))
    for wa, wb in a.diff:
        ca = collections.Counter()
        cb = collections.Counter()
        for label, _d, _a, counts in windows:
            if label == wa:
                ca.update(counts)
            if label == wb:
                cb.update(counts)
        only = sorted(set(ca) - set(cb))
        print("\n== 3. in %s, not in %s: %s" % (wa, wb, " ".join("0x%02x=%d" % (i, ca[i]) for i in only) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
