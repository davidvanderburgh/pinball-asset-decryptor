#!/usr/bin/env python3
"""stock_probe_read.py <mode.log> [--port <port>] [--names 0x80=Left spinner,...] [--state] [--awards] - what stock_probe.c saw.

Prints what the probe found and wrapped, then the run window by window (a window starts at each
`SP MARK` line): every START / STOP, every entry into a watched rule's shot handler with the
incoming shot and the rule's shot mask ("field"), lit shots and words BEFORE -> AFTER the handler,
and every award call with its value and caller. --state adds the 100 ms state changes, --awards
keeps award calls made while no watched rule was active (they are left out by default; an award a
START makes is logged just BEFORE its START line, and is kept).

Shot bits are named from --names first (bits a port only names in a comment, such as Godzilla's
spinners), then the port: its `shot` lines, then the insert its `lamp` lines tie to the bit
("lamp:LEFT SPINNER"), else "bit N". Item 158.
"""
import argparse
import re
import sys

LINE = re.compile(r"^\s*(\d+)\s+\[[^\]]*\]\s+SP\s+(.*)$")
LAMP_RE = re.compile(r"^lamp\s+[\d,]+\s+(0x[0-9a-fA-F]+|\d+)\s+(.*?)\s+#")


def port_names(port):
    shots, lamps = {}, {}
    if not port:
        return shots, lamps
    with open(port, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("shot "):
                parts = line.split(None, 2)
                if len(parts) == 3:
                    shots[int(parts[1], 0)] = parts[2].strip()
            m = LAMP_RE.match(line)
            if m and int(m.group(1), 0):
                lamps.setdefault(int(m.group(1), 0), []).append(m.group(2).strip())
    return shots, lamps


def namer(shots, lamps):
    def name(mask):
        if not mask:
            return "none"
        out, rest = [], mask
        for m, n in sorted(shots.items(), key=lambda kv: -bin(kv[0]).count("1")):
            if m and rest & m == m:
                out.append(n)
                rest &= ~m
        for b in range(64):
            if rest >> b & 1:
                ins = [n for m, ns in lamps.items() if m >> b & 1 for n in ns]
                out.append("lamp:%s" % "/".join(ins) if ins else "bit %d" % b)
        return "+".join(out)
    return name


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("log")
    ap.add_argument("--port")
    ap.add_argument("--names", default="")
    ap.add_argument("--state", action="store_true")
    ap.add_argument("--awards", action="store_true")
    a = ap.parse_args(argv)
    shots, lamps = port_names(a.port)
    for item in filter(None, (x.strip() for x in a.names.split(","))):
        mask, _eq, label = item.partition("=")
        shots[int(mask, 0)] = label.strip()
    name = namer(shots, lamps)
    active = set()
    held = []                      # awards seen while no rule ran: a START's own come just before it
    t_first = None
    for raw in open(a.log, encoding="utf-8", errors="replace"):
        m = LINE.match(raw)
        if not m:
            continue
        ms, rest = int(m.group(1)), m.group(2)
        t_first = ms if t_first is None else t_first
        head = rest.split(" ", 1)[0].rstrip(":")
        if head in ("ready", "watch", "award", "config", "REFUSED", "gamelit"):
            print("%9d  %s" % (ms, rest))
        elif head == "MARK":
            print("\n%9d  ==== %s" % (ms, rest[5:]))
        elif head in ("FORCE", "SYNTHETIC", "ball", "player", "event"):
            print("%9d  %s" % (ms, rest))
        elif head in ("START", "STOPPED"):
            f = rest.split()
            if head == "START":
                active.add(f[1])
                for hms, htext in held:
                    if ms - hms <= 5:
                        print("%9d    %s   (made by this START)" % (hms, htext))
                held = []
            print("%9d  %s" % (ms, rest))
        elif head == "STOP":
            f = rest.split()
            active.discard(f[1])
            print("%9d  %s" % (ms, rest))
        elif head == "shot":
            f = rest.split()
            mask = int(f[1], 16)
            print("%9d    switch shot 0x%x (%s)" % (ms, mask, name(mask)))
        elif head == "SHOT":
            sm = re.search(r"shot (0x[0-9a-f]+) x (\d+).*field (0x[0-9a-f]+) -> (0x[0-9a-f]+) lit (0x[0-9a-f]+) -> (?:\(inactive\) )?(0x[0-9a-f]+) active (-?\d+)(.*)$", rest)
            f = rest.split()
            if sm:
                shot, x, f0, f1, l0, l1, act, words = sm.groups()
                print("%9d    HANDLER %s %s: shot 0x%x (%s) x %s | field %s -> %s | lit %s (%s) -> %s (%s) | active %s |%s" % (
                    ms, f[1], f[2], int(shot, 16), name(int(shot, 16)), x, f0, f1, l0, name(int(l0, 16)),
                    l1, name(int(l1, 16)), act, words))
            else:
                print("%9d    %s" % (ms, rest))
        elif head == "STATE" and a.state:
            print("%9d    %s" % (ms, rest))
        elif head == "GAMELIT" and a.state:
            g = int(rest.split()[1], 16)
            print("%9d    game lit 0x%x (%s)" % (ms, g, name(g)))
        elif head == "AWARD":
            if active or a.awards:
                print("%9d    %s" % (ms, rest))
            else:
                held = [(hms, htext) for hms, htext in held if ms - hms <= 5] + [(ms, rest)]
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
