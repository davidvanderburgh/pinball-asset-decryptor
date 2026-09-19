#!/usr/bin/env python3
"""sound_census_read.py - read a sound_census.c run: which requests played, in which phase, for how long.

    sound_census_read.py <run dir or sound_census.log> [--map <requests.tsv>] [--check 1020,1133,...]
                         [--play-until <mark>] [--json <out.json>]

Reads sound_census.log (one line per request at the worker, MARK / FIRE / STOP / ACTIVE / CITY
lines) and, beside it, sound_census.chan (the 8 channels every 500 ms). Prints:

  * per phase (the span between two MARK lines), how many requests the worker saw and the
    ten most frequent, named from the sound_map.py TSV when --map is given;
  * every request seen in NORMAL PLAY - every phase before --play-until (default "controls",
    where the run starts firing requests itself), and after --resume-at when given - with its
    count;
  * from the channel dump, every (serial, request) a channel held: how long it held it
    against the record's stock length, so a request the game LOOPS holds longer than its
    record, and one the game stops holds shorter;
  * --check: for each listed request, SEEN or NEVER in normal play, and whether it is a
    city variant target (from the CITY dump).
"""
import argparse
import collections
import csv
import json
import os
import struct
import sys

CH_BYTES, Q_BYTES, HDR = 1568, 160, 12
REC = HDR + CH_BYTES + Q_BYTES


def load_map(path):
    if not path:
        return {}
    with open(path, encoding="utf-8") as f:
        return {int(r["req"]): r for r in csv.DictReader(f, delimiter="\t")}


def parse_log(path):
    events = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.rstrip("\n").split(" ")
            if len(parts) < 2 or not parts[0].isdigit():
                continue
            ms, kind = int(parts[0]), parts[1]
            events.append((ms, kind, parts[2:]))
    return events


def parse_chan(path):
    out = []
    if not os.path.exists(path):
        return out
    data = open(path, "rb").read()
    for off in range(0, len(data) - REC + 1, REC):
        magic, lo, hi = struct.unpack_from("<3I", data, off)
        if magic != 0x31484353:
            break
        ms = lo | (hi << 32)
        chans = []
        for c in range(8):
            base = off + HDR + c * 196
            serial, = struct.unpack_from("<I", data, base + 180)
            req, = struct.unpack_from("<H", data, base + 184)
            voices, bus = data[base + 188], data[base + 189]
            chans.append((serial, req, voices, bus))
        out.append((ms, chans))
    return out


def holds(chan):
    """[(req, serial, channel, first_ms, last_ms)] for every channel occupancy with a voice playing."""
    open_ = {}
    done = []
    for ms, chans in chan:
        for c, (serial, req, voices, _bus) in enumerate(chans):
            key = (c, serial, req)
            if voices:
                if key not in open_:
                    open_[key] = [ms, ms]
                open_[key][1] = ms
        for key in list(open_):
            c, serial, req = key
            cur = chans[c]
            if not (cur[2] and cur[0] == serial and cur[1] == req):
                first, last = open_.pop(key)
                done.append((req, serial, c, first, last))
    for (c, serial, req), (first, last) in open_.items():
        done.append((req, serial, c, first, last))
    return sorted(done, key=lambda h: h[3])


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run")
    ap.add_argument("--map")
    ap.add_argument("--check", default="")
    ap.add_argument("--play-until", default="controls")
    ap.add_argument("--resume-at", default="",
                    help="a MARK after which normal play counts again (a run that fires its controls "
                         "in attract, then plays games)")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    log = a.run if a.run.endswith(".log") else os.path.join(a.run, "sound_census.log")
    chanf = os.path.join(os.path.dirname(log), "sound_census.chan")
    names = load_map(a.map)
    events = parse_log(log)
    chan = parse_chan(chanf)

    def nm(req):
        r = names.get(req)
        if not r:
            return ""
        return "%s ch%s %ss" % (r.get("menu_name") or "-", r.get("chan"), r.get("seconds"))

    # phases
    phases, cur, t_cur = [], "boot", events[0][0] if events else 0
    counts = collections.Counter()
    play = collections.Counter()
    in_play = True
    city = {}
    fired = []
    for ms, kind, rest in events:
        if kind == "MARK":
            label = " ".join(rest)
            phases.append((cur, t_cur, ms, counts))
            cur, t_cur, counts = label, ms, collections.Counter()
            if label == a.play_until:
                in_play = False
            elif a.resume_at and label == a.resume_at:
                in_play = True
        elif kind == "R" and rest:
            req = int(rest[0])
            counts[req] += 1
            if in_play:
                play[req] += 1
        elif kind == "CITY":
            for kv in rest[1:]:
                if ":" in kv:
                    k, v = kv.split(":")
                    city[int(k)] = int(v)
        elif kind in ("FIRE", "STOP", "ACTIVE"):
            fired.append((ms, kind, " ".join(rest)))
    phases.append((cur, t_cur, events[-1][0] if events else t_cur, counts))

    print("== phases (%d worker calls in all)" % sum(sum(c.values()) for *_x, c in phases))
    for label, t0, t1, c in phases:
        top = ", ".join("%d x%d" % (r, n) for r, n in c.most_common(10))
        print("  %-18s %6.1f s  %4d calls  %3d requests  %s" % (label, (t1 - t0) / 1000.0, sum(c.values()), len(c), top))

    print("\n== every request in normal play (before MARK %s%s): %d distinct, %d calls"
          % (a.play_until, " and after MARK %s" % a.resume_at if a.resume_at else "", len(play), sum(play.values())))
    for req, n in sorted(play.items(), key=lambda kv: (-kv[1], kv[0])):
        print("  %5d x%-4d %s" % (req, n, nm(req)))

    hs = holds(chan)
    print("\n== channel holds (%d dumps, %d occupancies); longest per request, against its record"
          % (len(chan), len(hs)))
    best = {}
    for req, serial, c, first, last in hs:
        d = (last - first) / 1000.0 + 0.5
        if req not in best or d > best[req][0]:
            best[req] = (d, c, first, serial)
    for req, (d, c, first, serial) in sorted(best.items(), key=lambda kv: -kv[1][0])[:40]:
        stock = float(names[req]["seconds"]) if req in names and names[req].get("seconds") else None
        flag = ""
        if stock is not None and stock > 0:
            if d > stock + 1.5:
                flag = "HELD LONGER THAN ITS RECORD (loop?)"
            elif d < stock - 1.5:
                flag = "ended early (stopped?)"
        print("  req %5d ch%d serial %-6d held ~%6.1f s  stock %s  %s  %s"
              % (req, c, serial, d, "%.1f" % stock if stock is not None else "?", flag, nm(req)))

    if fired:
        print("\n== our triggers")
        for ms, kind, rest in fired:
            print("  %d %s %s" % (ms, kind, rest))
    if city:
        print("\n== city variants: %d (e.g. %s)" % (len(city), ", ".join("%d->%d" % kv for kv in list(city.items())[:8])))

    result = {}
    if a.check:
        print("\n== check")
        targets = set(city.values())
        for tok in a.check.split(","):
            if not tok.strip():
                continue
            req = int(tok)
            seen = play.get(req, 0)
            result[req] = {"seen_in_play": seen, "city_target": req in targets, "city_source": req in city}
            print("  %5d %-6s %s%s %s" % (req, "SEEN x%d" % seen if seen else "NEVER",
                                         " CITY-TARGET" if req in targets else "",
                                         " CITY-SOURCE" if req in city else "", nm(req)))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"play": dict(play), "check": result, "city": city,
                       "phases": [(p[0], p[1], p[2], dict(p[3])) for p in phases]}, f, indent=1)


if __name__ == "__main__":
    main(sys.argv[1:])
