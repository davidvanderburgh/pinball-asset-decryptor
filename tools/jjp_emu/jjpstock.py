#!/usr/bin/env python3
"""What a RUNNING JJP game shows about its own modes, for .stock files (PAD-1351).

The game's code and its shot table are ciphertext in the file until the game runs,
and its mode globals get their class (vtable) only when their constructors run.  So
the names a .stock file uses - each mode global (Wonka 03.03: cl_mode is Candy Lane)
and each shot (ramp_left, target_tv, ...) - are read off a live game, read-only,
through /proc/<pid>/mem, exactly as jjpmodes.c reads them in the game:

    jjpstock.py live --elf <title>.elf --out modes/ports/<title>.live.json

jjpport.py --live folds that file into the title's port report, and
`mkjjpmodes.py check --port` then checks a .stock file's mode and shot names.

The shot table: one entry per shot id, each pointing at the shot's exported
shot_made_<name> handler.  It is found by those handlers' addresses in the game's own
non-code segments (one stride, the id a fixed distance from the pointer, counting up
one per entry) - shot_table() below and read_shot_table() in jjpmodes.c are the same
rule, and a shot keeps its handler's name unless several shots share one handler
(Wonka: the slings, the jets, the 3-bank), where each takes the game's own display
name if those are distinct, else <name>_<id>.
"""
import argparse
import collections
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_SHOT_MADE = re.compile(r"^_Z\d+shot_made_(\w+)v$")


def normalise(text):
    """'LEFT SLING' -> 'left_sling' (jjpmodes.c normalise)."""
    out = re.sub(r"[^a-z0-9]+", "_", (text or "").lower())
    return out.strip("_")


def shot_handlers(syms):
    """{address: name} of the exported shot_made_<name>() handlers."""
    out = {}
    for n, (a, _s) in syms.items():
        m = _SHOT_MADE.match(n)
        if m and a:
            out[a] = m.group(1)
    return out


def shot_table(segments, handlers, display=None):
    """segments: [(lo, bytes)] of the game's non-code memory; handlers: {addr: name};
    display: (id, address of the entry's handler pointer, stride) -> the game's own display
    name (in the game: get_shot_name), or None.
    -> [{"id", "name", "display"}] in table order, [] when no table is found."""
    hits = []
    for lo, data in segments:
        for off in range((-lo) % 8, len(data) - 7, 8):
            v = struct.unpack_from("<Q", data, off)[0]
            if v in handlers:
                hits.append((lo + off, handlers[v], lo, data))
    if len(hits) < 4:
        return []
    gaps = collections.Counter(b[0] - a[0] for a, b in zip(hits, hits[1:]) if 16 <= b[0] - a[0] <= 512)
    if not gaps:
        return []
    # the most common gap; the runtime takes the first gap with the highest count
    best_n = max(gaps.values())
    stride = next(b[0] - a[0] for a, b in zip(hits, hits[1:]) if gaps.get(b[0] - a[0]) == best_n)
    runs, i = [], 0
    while i < len(hits):
        j = i + 1
        while j < len(hits) and (hits[j][0] - hits[j - 1][0]) % stride == 0 and (hits[j][0] - hits[j - 1][0]) // stride <= 8:
            j += 1
        runs.append((i, j))
        i = j
    bs, be = max(runs, key=lambda r: r[1] - r[0])   # first longest, as the runtime
    run = hits[bs:be]

    def int_at(h, d):
        a, _n, lo, data = h
        o = a - lo + d
        if o < 0 or o + 4 > len(data):
            return None
        return struct.unpack_from("<i", data, o)[0]

    id_at = None
    for d in range(-stride + 4, stride, 4):
        if d in (0, 4):
            continue
        base = int_at(run[0], d)
        if base is None or not 0 <= base < 256:
            continue
        if all(int_at(h, d) == base + (h[0] - run[0][0]) // stride for h in run):
            id_at = d
            break
    shots = []
    for h in run:
        sid = int_at(h, id_at) if id_at is not None else (h[0] - run[0][0]) // stride
        shots.append({"id": sid, "name": h[1], "display": (display(sid, h[0], stride) if display else "") or "",
                      "addr": h[0]})
    names = [s["name"] for s in shots]
    done = set()
    for i, s in enumerate(shots):
        if s["name"] in done or names.count(s["name"]) < 2:
            continue
        done.add(s["name"])
        grp = [k for k, t in enumerate(shots) if t["name"] == s["name"]]
        dn = [normalise(shots[k]["display"]) for k in grp]
        distinct = display is not None and all(dn) and len(set(dn)) == len(dn) and not set(dn) & set(names)
        for g, k in enumerate(grp):
            if distinct:
                shots[k]["name"] = dn[g]
            elif g:
                shots[k]["name"] = "%s_%d" % (shots[k]["name"][:40], shots[k]["id"])
    return shots


class LiveGame:
    """Read-only view of the running JJP game (swdump.find_pid: the renderer in the jail)."""

    def __init__(self, elf, pid=None):
        import swdump
        from jjpelf import GameElf
        self.e = GameElf(elf)
        self.pid = pid or swdump.find_pid()
        if not self.pid:
            raise SystemExit("no JJP game running")
        self.mem = open("/proc/%d/mem" % self.pid, "rb")

    def read(self, a, n):
        self.mem.seek(a)
        return self.mem.read(n)

    def segments(self):
        exe = os.readlink("/proc/%d/exe" % self.pid)
        root = os.readlink("/proc/%d/root" % self.pid)
        out = []
        for line in open("/proc/%d/maps" % self.pid):
            f = line.split()
            if len(f) < 6 or f[1][0] != "r":     # the Envelope maps the game's data rwx
                continue
            path = f[5]
            if path != exe and root + path != exe and path != exe[len(root):]:
                continue
            lo, hi = (int(x, 16) for x in f[0].split("-"))
            out.append((lo, self.read(lo, hi - lo)))
        return out

    def display(self, sid, at, stride):
        """The entry's display name: the first qword after the handler pointer that points at
        a printable string (Wonka 03.03: +0x38 from it, the string get_shot_name returns)."""
        for d in range(8, stride - 8 + 1, 8):
            p = struct.unpack("<Q", self.read(at + d, 8))[0]
            if p < 0x400000 or p > 0x7fffffffffff:
                continue
            t = self.cstr(p)
            if t and all(32 <= ord(c) < 127 for c in t) and t.upper() == t:
                return t
        return ""

    def cstr(self, a):
        try:
            return self.read(a, 64).split(b"\0")[0].decode("latin1")
        except (OSError, ValueError):
            return ""

    def objects(self, classes):
        """{global: class} for every global whose vtable is one of `classes` (demangled)."""
        vts = {}
        for n, (a, _s) in self.e.syms.items():
            if n.startswith("_ZTV"):
                m = re.match(r"^(\d+)(.*)$", n[4:])
                if m:
                    c = m.group(2)[:int(m.group(1))]
                    if c in classes:
                        vts[a + 16] = c
        out = {}
        for n, (a, s) in self.e.syms.items():
            if s < 0x60 or n.startswith("_Z"):
                continue
            try:
                w = struct.unpack("<Q", self.read(a, 8))[0]
            except (OSError, ValueError, struct.error):
                continue
            if w in vts:
                out[n] = vts[w]
        return dict(sorted(out.items()))


def live(a):
    import jjpport
    g = LiveGame(a.elf, a.pid)
    modes, _ = jjpport.derived_classes(g.e)
    classes = set(jjpport._demangled_class(m) for m in modes)
    segs = g.segments()
    shots = shot_table(segs, shot_handlers(g.e.syms), g.display)
    for s_ in shots:
        s_.pop("addr", None)
    out = collections.OrderedDict([
        ("source", "jjpstock.py live, %s pid %d" % (os.path.basename(a.elf), g.pid)),
        ("objects", g.objects(classes)),
        ("shots", shots),
    ])
    with open(a.out, "w", newline="\n") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    print("%s: %d mode globals, %d shots -> %s" % (os.path.basename(a.elf), len(out["objects"]), len(shots), a.out))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("live", help="read a running game's mode globals and shot table (root, WSL)")
    s.add_argument("--elf", required=True, help="the title's game program (the same build as the running game)")
    s.add_argument("--out", required=True)
    s.add_argument("--pid", type=int)
    a = ap.parse_args(argv)
    return live(a)


if __name__ == "__main__":
    sys.exit(main())
