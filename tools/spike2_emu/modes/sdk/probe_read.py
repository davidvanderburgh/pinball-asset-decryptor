#!/usr/bin/env python3
"""probe_read.py <probe.log> [switch_list.txt] - what call_probe.c saw after each mark, with arguments.

Marks are "<ms> mark <label>" lines written into the log from outside. A window runs from a
mark to the next one. For a numeric label (a switch id, pressed at least 300 ms after its
mark) calls sooner than 300 ms are listed apart: they belong to what came before. The
switch table, if given, names the ids. Sites the probe had already capped (MAX_LINES in
call_probe.c) show only their total at the top.
"""
import re
import sys
from collections import Counter, defaultdict

names = {}
if len(sys.argv) > 2:
    for line in open(sys.argv[2], encoding="utf-8", errors="replace"):
        f = line.split(None, 4)
        if len(f) == 5 and f[0].isdigit():
            names[f[0]] = f[4].strip()

events = []
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    f = line.split()
    if len(f) >= 3 and f[1] == "mark":
        events.append((int(f[0]), "mark", f[2], None))
    elif len(f) == 10 and f[0].isdigit():
        events.append((int(f[0]), "call", f[1], f[2:]))
events.sort(key=lambda e: e[0])
total = Counter(e[2] for e in events if e[1] == "call")
print("calls per site (whole run, capped at 60 by the probe):")
print("  " + ", ".join("%s %d" % kv for kv in total.most_common()))
print()

window, start = "boot", 0
by_window = defaultdict(list)
order = ["boot"]
for t, kind, what, args in events:
    if kind == "mark":
        window, start = what, t
        order.append(window)
        continue
    late = t - start < 300 and window.isdigit()
    by_window[(window, late)].append((t - start, what, args))

for w in order:
    for late in (True, False):
        calls = by_window.get((w, late), [])
        if not calls:
            continue
        label = "%s %s" % (w, names.get(w, ""))
        print("== %s%s: %d calls" % (label, " (BEFORE its press: the previous switch's)" if late else "", len(calls)))
        for dt, site, args in calls[:25]:
            print("   +%5d ms %-6s r0 %s r1 %s r2 %s r3 %s | sp %s %s %s %s" % (dt, site, *args))
