#!/usr/bin/env python3
"""ledact.py - what the playfield LEDs are DOING, from dump/padled, and whether a window differs.

    ledact.py [seconds] [interval_ms] [--save FILE]
        per interval: levels changed, fade pulses, writes; then totals and busiest nodes.
        --save keeps, per window: each cell's change rate and MEAN LEVEL, and every fade
        pulse's shape (node, start, end, to) with how often it fired
    ledact.py --compare A.json B.json [C.json...]
        distances between windows, pair by pair: mean-level L1 over all cells, change-rate
        L1, and the fade shapes one window fired that the other never did. Take TWO
        baselines: their distance is the noise a show has to beat.
    ledact.py --footprint SHOW.json BASE1.json [BASE2.json...]
        cells and fade shapes seen in SHOW and in no baseline

WHAT FAILED, SO NOBODY USES IT AGAIN (item 125, 2026-09-15). Counting activity: a 10 s
game baseline read 52.8 level changes/s, and with tesla strike forced on 8.2/s - a show
REPLACES the ambient animation. And the set of cells that moved: two baselines and four
shows (356, 351, 95, 344) all moved the same 66 cells, because in a game every insert
on nodes 8 and 9 is already animating. A show changes HOW existing cells behave and
WHICH fade ranges fire, so that is what this compares.

The block (padled.h): gen at 8, val[16][96] at 20, fade_head at 2076, fade entries at
2080, stride 12 = {u32 ms; u8 node, start, end, from, to, rise, fall, pad}, ring of 96.
Read-only; runs inside WSL beside a live run.
"""
import json
import os
import struct
import sys
import time
from collections import Counter

VAL_OFF, NODES, IDX = 20, 16, 96
GEN_OFF, FADE_HEAD_OFF, FADE_OFF, FADE_STRIDE, FADE_RING = 8, 2076, 2080, 12, 96
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
    if len(b) < FADE_OFF + FADE_STRIDE * FADE_RING or struct.unpack_from("<I", b, 0)[0] != MAGIC:
        return None
    return b


def fades_since(b, old_head):
    head = struct.unpack_from("<I", b, FADE_HEAD_OFF)[0]
    n = min((head - old_head) & 0xFFFFFFFF, FADE_RING)
    out = []
    for k in range(n):
        o = FADE_OFF + FADE_STRIDE * ((head - n + k) % FADE_RING)
        _ms, node, start, end, _frm, to, _rise, _fall, _pad = struct.unpack_from("<IBBBBBBBB", b, o)
        out.append("%d:%d-%d>%d" % (node, start, end, to))
    return head, out


def measure(secs, step, save):
    path = led_path()
    b = sample(path)
    if b is None:
        print("no padled block at %s (is a run up?)" % path)
        return 2
    prev_val = b[VAL_OFF:VAL_OFF + NODES * IDX]
    head = struct.unpack_from("<I", b, FADE_HEAD_OFF)[0]
    gen = struct.unpack_from("<I", b, GEN_OFF)[0]
    t0 = time.monotonic()
    changes = [0] * (NODES * IDX)
    levels = [0] * (NODES * IDX)
    shapes = Counter()
    nsamp = tot_changed = tot_fades = tot_gen = 0
    while time.monotonic() - t0 < secs:
        time.sleep(step)
        b = sample(path)
        if b is None:
            print("padled went away")
            return 2
        val = b[VAL_OFF:VAL_OFF + NODES * IDX]
        changed = 0
        for i, (a, c) in enumerate(zip(prev_val, val)):
            levels[i] += c
            if a != c:
                changed += 1
                changes[i] += 1
        head, new = fades_since(b, head)
        shapes.update(new)
        g = struct.unpack_from("<I", b, GEN_OFF)[0]
        nsamp += 1
        tot_changed += changed
        tot_fades += len(new)
        tot_gen += (g - gen) & 0xFFFFFFFF
        gen = g
        prev_val = val
    el = time.monotonic() - t0
    per_node = [sum(changes[n * IDX:(n + 1) * IDX]) for n in range(NODES)]
    busiest = sorted(((c, n) for n, c in enumerate(per_node) if c), reverse=True)[:6]
    print("TOTAL over %.1f s: levels changed %d (%.1f/s), fade pulses %d (%.1f/s) in %d shapes, writes %d (%.0f/s)"
          % (el, tot_changed, tot_changed / el, tot_fades, tot_fades / el, len(shapes), tot_gen, tot_gen / el))
    print("busiest nodes (changes): " + ", ".join("node %d: %d" % (n, c) for c, n in busiest))
    if save:
        with open(save, "w") as f:
            json.dump({"seconds": el, "samples": nsamp, "fades": tot_fades, "writes": tot_gen,
                       "rate": {"%d.%d" % divmod(i, IDX): c / el for i, c in enumerate(changes) if c},
                       "mean": {"%d.%d" % divmod(i, IDX): v / nsamp for i, v in enumerate(levels) if v},
                       "shapes": {k: v / el for k, v in shapes.items()}}, f)
        print("saved", save)
    return 0


def load(p):
    return json.load(open(p))


def distance(a, b):
    keys_m = set(a["mean"]) | set(b["mean"])
    keys_r = set(a["rate"]) | set(b["rate"])
    dm = sum(abs(a["mean"].get(k, 0) - b["mean"].get(k, 0)) for k in keys_m)
    dr = sum(abs(a["rate"].get(k, 0) - b["rate"].get(k, 0)) for k in keys_r)
    only_a = sorted(set(a["shapes"]) - set(b["shapes"]))
    only_b = sorted(set(b["shapes"]) - set(a["shapes"]))
    return dm, dr, only_a, only_b


def compare(paths):
    w = [(os.path.basename(p), load(p)) for p in paths]
    print("%-18s %-18s %12s %12s %8s %8s" % ("A", "B", "mean-L1", "rate-L1", "shapesA", "shapesB"))
    for i in range(len(w)):
        for j in range(i + 1, len(w)):
            dm, dr, oa, ob = distance(w[i][1], w[j][1])
            print("%-18s %-18s %12.0f %12.1f %8d %8d" % (w[i][0], w[j][0], dm, dr, len(oa), len(ob)))
    return 0


def footprint(show, bases):
    s = load(show)
    bs = [load(b) for b in bases]
    shapes = sorted(k for k in s["shapes"] if all(k not in b["shapes"] for b in bs))
    cells = sorted(k for k in s["rate"] if all(k not in b["rate"] for b in bs))
    print("show %s: %d fade shapes in no baseline, %d cells in no baseline" % (os.path.basename(show), len(shapes), len(cells)))
    for k in shapes[:40]:
        print("  fade %-14s %.2f/s" % (k, s["shapes"][k]))
    for k in cells[:20]:
        print("  cell %-8s %.2f changes/s" % (k, s["rate"][k]))
    return 0


def main(argv):
    if argv and argv[0] == "--compare":
        return compare(argv[1:])
    if argv and argv[0] == "--footprint":
        return footprint(argv[1], argv[2:])
    save = None
    if "--save" in argv:
        k = argv.index("--save")
        save = argv[k + 1]
        argv = argv[:k] + argv[k + 2:]
    secs = float(argv[0]) if argv else 10.0
    step = (float(argv[1]) if len(argv) > 1 else 250.0) / 1000.0
    return measure(secs, step, save)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
