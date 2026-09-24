#!/usr/bin/env python3
"""lamp_watch.py - which playfield inserts are lit, by NAME, sampled from the emulator's LED block.

    lamp_watch.py log <padled> <port> <out.txt> [--every 100] [--stop FILE] [--max-s 3600]
                      [--names "LEFT RAMP,TOP SPINNER,..."]
        Samples the shim's decoded LED block (dump/padled, padled.h: magic 'PLED', val[16][96]
        at +20) every --every ms until --stop appears, and writes one line a sample: the epoch
        ms, then every insert whose levels CHANGED since the sample before as NAME=r,g,b (an
        insert of one light is NAME=v). Every 50th line is a FULL line with every insert.
        The inserts are the port's `lamp` lines (their comment says "I/O group G index I":
        group 6 is node board 8, group 7 node 9 on Godzilla, so node = group + 2, and the
        insert's lights are the channels from I on, one per light id). --names keeps only
        those (default: every insert the port ties to a shot, plus every TANK insert).
    lamp_watch.py now <out.txt> [--ms 1500]
        The inserts that were lit (any channel above 0) in the last --ms of a log, each with
        the share of samples it was lit in and its highest levels.
    lamp_watch.py report <out.txt> --from MS --to MS [--base-from MS --base-to MS]
        Per insert, the share of samples lit and the mean level inside a window of epoch ms,
        beside a baseline window: what a rule's start changed on the playfield.
    lamp_watch.py shots <port> [--mask 0x...]
        Which insert the port ties to each shot bit (a shot can light several).

A lit insert is a level above 0 in a SAMPLE: an insert that blinks is lit in some samples and
not in others, so a share of 0.3-0.7 is a blink, near 1 is solid. During a game every insert on
the Godzilla insert boards animates with the game's own light shows, so read a rule's lights as
a CHANGE against a baseline window (report), not as "lit or not" on its own.
Read-only on the block. Item 158.
"""
import argparse
import os
import re
import struct
import sys
import time

VAL_OFF, NODES, IDX, MAGIC = 20, 16, 96, 0x44454C50
LAMP_RE = re.compile(r"^lamp\s+([\d,]+)\s+(0x[0-9a-fA-F]+|\d+)\s+(.*?)\s+#\s*lamp\s+[\d+]+,\s*I/O group\s+(\d+)\s+index\s+(\d+)")


def port_lamps(port):
    """[(name, shot mask, node, first channel, width)] from a port's lamp lines."""
    out = []
    with open(port, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = LAMP_RE.match(line.strip())
            if not m:
                continue
            ids = [int(x) for x in m.group(1).split(",")]
            width = len([i for i in ids if i]) or 1
            out.append((m.group(3).strip(), int(m.group(2), 0), int(m.group(4)) + 2, int(m.group(5)), width))
    return out


def default_names(lamps):
    return [n for n, mask, *_ in lamps if mask or n.startswith("TANK")]


def cmd_log(a):
    lamps = port_lamps(a.port)
    if a.names:
        want = [s.strip().upper() for s in a.names.split(",") if s.strip()]
        lamps = [x for x in lamps if x[0].upper() in want]
    else:
        keep = set(default_names(lamps))
        lamps = [x for x in lamps if x[0] in keep]
    step = a.every / 1000.0
    t0 = time.monotonic()
    prev, n = {}, 0
    with open(a.out, "w", buffering=1) as f:
        f.write("# lamp_watch every %d ms from %s: %s\n" % (a.every, a.padled, "|".join(
            "%s@%d:%d+%d" % (name, node, ch, w) for name, _m, node, ch, w in lamps)))
        while time.monotonic() - t0 < a.max_s and not (a.stop and os.path.exists(a.stop)):
            try:
                with open(a.padled, "rb") as g:
                    b = g.read(VAL_OFF + NODES * IDX)
            except OSError:
                time.sleep(step)
                continue
            if len(b) < VAL_OFF + NODES * IDX or struct.unpack_from("<I", b, 0)[0] != MAGIC:
                time.sleep(step)
                continue
            cur = {}
            for name, _m, node, ch, w in lamps:
                cur[name] = ",".join(str(b[VAL_OFF + IDX * node + ch + k]) for k in range(w))
            full = n % 50 == 0
            items = [(k, v) for k, v in cur.items() if full or prev.get(k) != v]
            f.write("%d%s %s\n" % (int(time.time() * 1000), " FULL" if full else "",
                                   " ".join("%s=%s" % (k.replace(" ", "_"), v) for k, v in items)))
            prev, n = cur, n + 1
            time.sleep(step)
    return 0


def read_log(path):
    """[(ms, {name: (levels...)})] - the state after every sample."""
    state, out = {}, []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            try:
                ms = int(parts[0])
            except ValueError:
                continue
            for p in parts[1:]:
                if "=" not in p:
                    continue
                k, v = p.split("=", 1)
                state[k.replace("_", " ")] = tuple(int(x) for x in v.split(","))
            out.append((ms, dict(state)))
    return out


def window_stats(samples, t_from, t_to):
    win = [s for ms, s in samples if t_from <= ms <= t_to]
    stats = {}
    for s in win:
        for k, v in s.items():
            lit, tot, mx, sm = stats.get(k, (0, 0, (0,) * len(v), 0))
            stats[k] = (lit + (1 if max(v) > 0 else 0), tot + 1,
                        tuple(max(a, b) for a, b in zip(mx, v)), sm + sum(v) / float(len(v)))
    return len(win), stats


def cmd_now(a):
    samples = read_log(a.log)
    if not samples:
        print("no samples in %s" % a.log)
        return 1
    end = samples[-1][0]
    n, st = window_stats(samples, end - a.ms, end)
    lit = sorted(((k, v) for k, v in st.items() if v[0]), key=lambda kv: -kv[1][0])
    print("inserts lit in the last %d ms (%d samples): %s" % (a.ms, n, ", ".join(
        "%s %.0f%% max %s" % (k, 100.0 * v[0] / v[1], ",".join(map(str, v[2]))) for k, v in lit) or "none"))
    return 0


def cmd_report(a):
    samples = read_log(a.log)
    n, st = window_stats(samples, a.t_from, a.t_to)
    bn, bst = (window_stats(samples, a.base_from, a.base_to) if a.base_from is not None else (0, {}))
    print("window %d..%d ms: %d samples; baseline %s" % (a.t_from, a.t_to, n,
                                                         "%d samples" % bn if bn else "none"))
    print("%-26s %8s %8s   %8s %8s   %s" % ("insert", "lit", "mean", "base lit", "base mean", "max levels"))
    for k in sorted(st, key=lambda k: -(st[k][0] / max(st[k][1], 1))):
        lit, tot, mx, sm = st[k]
        b = bst.get(k)
        bl = "%7.0f%%" % (100.0 * b[0] / b[1]) if b else "       -"
        bm = "%8.1f" % (b[3] / b[1]) if b else "       -"
        print("%-26s %7.0f%% %8.1f   %s %s   %s" % (k, 100.0 * lit / tot, sm / tot, bl, bm, ",".join(map(str, mx))))
    return 0


def cmd_shots(a):
    lamps = port_lamps(a.port)
    for name, mask, node, ch, w in lamps:
        if not mask or (a.mask and not mask & a.mask):
            continue
        bits = [b for b in range(64) if mask >> b & 1]
        print("%-22s shot 0x%-12x bits %-10s node %d channel %d (+%d)" % (
            name, mask, ",".join(map(str, bits)), node, ch, w))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("log")
    p.add_argument("padled")
    p.add_argument("port")
    p.add_argument("out")
    p.add_argument("--every", type=int, default=100)
    p.add_argument("--stop")
    p.add_argument("--max-s", type=float, default=3600.0)
    p.add_argument("--names")
    p = sub.add_parser("now")
    p.add_argument("log")
    p.add_argument("--ms", type=int, default=1500)
    p = sub.add_parser("report")
    p.add_argument("log")
    p.add_argument("--from", dest="t_from", type=int, required=True)
    p.add_argument("--to", dest="t_to", type=int, required=True)
    p.add_argument("--base-from", type=int)
    p.add_argument("--base-to", type=int)
    p = sub.add_parser("shots")
    p.add_argument("port")
    p.add_argument("--mask", type=lambda s: int(s, 0))
    a = ap.parse_args(argv)
    return {"log": cmd_log, "now": cmd_now, "report": cmd_report, "shots": cmd_shots}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
