#!/usr/bin/env python3
"""lightcheck.py <port> <led_io.txt> <before> <during1> <during2> <after> - a `light_all ff00ff` proof read off the shim's
LED view snapshots (dump/padled copies, padled.h: one value byte per node and LED index at 20 + 96 * node + index).
PAD-1555 (MODE_SDK.md "Lights on every title": item 164's rule, re-made for lightsjob.sh).

Every insert the port names (`lamp` lines) is looked up in the rig's led_io.txt by name: an RGB insert is its -R/-G/-B
channels, a single-colour one its own. Magenta: R >= 200, G <= 40, B >= 200; a single-colour insert lit: >= 200. Prints
`rgb a/b single c/d before e after f` (lit in BOTH during snapshots / addressed; lit in the before and after ones) and
the inserts not lit; exit 0 when every addressed RGB insert (or, on a title with none, every single one) is lit in both
and no more were before or after than the game's own lights explain (at most a third)."""
import re
import sys

HDR, IDX = 20, 96


def leds(path):
    out = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        w = line.split()
        if len(w) >= 3 and w[0].isdigit() and w[1].isdigit():
            name = re.split(r"\s{2,}", line.strip(), maxsplit=3)
            nm = name[2].strip() if len(name) > 2 else " ".join(w[2:])
            nm = re.sub(r"\s+-?\d+\s+-?\d+(\s+\S+)*$", "", nm).strip()
            out.setdefault(nm.upper(), []).append((int(w[0]), int(w[1])))
    return out


def lamps(port):
    names = []
    for line in open(port, encoding="utf-8"):
        m = re.match(r"^lamp\s+[\d,]+\s+\S+\s+(.+?)\s*(#|$)", line)       # an RGB insert: `lamp 82,83,84 ...`
        if m:
            names.append(m.group(1).strip().upper())
    return list(dict.fromkeys(names))


def val(snap, node, idx):
    o = HDR + IDX * node + idx
    return snap[o] if 0 <= node < 16 and 0 <= idx < IDX and o < len(snap) else 0


def main(argv):
    port, io, *snaps = argv
    shots = [open(s, "rb").read() for s in snaps]
    io_map = leds(io)
    rgb, single = {}, {}
    for n in lamps(port):
        ch = {c: io_map.get("%s-%s" % (n, c)) for c in "RGB"}
        if all(ch.values()):
            rgb[n] = {c: ch[c][0] for c in "RGB"}
        elif io_map.get(n):
            single[n] = io_map[n][0]

    def lit(snap, n):
        if n in rgb:
            r, g, b = (val(snap, *rgb[n][c]) for c in "RGB")
            return r >= 200 and g <= 40 and b >= 200
        return val(snap, *single[n]) >= 200
    before, d1, d2, after = shots
    want = rgb or single
    held = [n for n in want if lit(d1, n) and lit(d2, n)]
    pre = [n for n in want if lit(before, n)]
    post = [n for n in want if lit(after, n)]
    s_held = [n for n in single if lit(d1, n) and lit(d2, n)]
    r_held = [n for n in rgb if lit(d1, n) and lit(d2, n)]
    print("rgb %d/%d single %d/%d before %d after %d (of the %s)" % (len(r_held), len(rgb), len(s_held), len(single),
                                                                       len(pre), len(post), "rgb" if rgb else "single"))
    missing = [n for n in want if n not in held]
    if missing:
        print("not lit: " + ", ".join(missing[:20]))
    unplaced = [n for n in lamps(port) if n not in rgb and n not in single]
    if unplaced:
        print("not in led_io: %d (%s)" % (len(unplaced), ", ".join(unplaced[:8])))
    ok = want and not missing and len(pre) <= len(want) // 3 and len(post) <= len(want) // 3
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
