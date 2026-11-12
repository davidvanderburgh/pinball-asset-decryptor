#!/usr/bin/env python3
"""sw.py - press switches on this slot's Chicago Gaming rig (cgcshim.so's
control FIFO, $CGC_RIG/ctl).

  sw.py tap <switch> [ms]     close and open (a target, Start, a coin)
  sw.py on|off <switch>       hold closed / open
  sw.py coin [n]              n credits' worth of left-coin presses (default 1)
  sw.py plunge | drain        the ball model: shooter lane -> play, play -> trough
  sw.py hole <switch>         the ball in play drops into a kickout
  sw.py state                 switches, lamps, coils, balls (JSON)
  sw.py list                  every switch by the ROM's own name

<switch> is a WPC number (13), a coin-door or flipper switch (D8, F2), or a
name from the ROM's switch table ("START BUTTON", start, enter, "l. flipper
button").  PAD_SLOT picks the rig (default 0); CGC_ROOT as in cgcpath.sh.
"""
import json
import os
import sys
import time


def rig_dir():
    root = os.environ.get("CGC_ROOT", "/var/tmp/pad_cgc")
    return os.path.join(root, "rig%s" % os.environ.get("PAD_SLOT", "0"))


def names():
    try:
        with open(os.path.join(rig_dir(), "names.json")) as f:
            n = json.load(f)
    except (OSError, ValueError):
        return {}
    out = dict(n.get("switches", {}))
    out.update(n.get("flippers", {}))
    return out


def resolve(sw):
    """-> the WPC key: "13", "D8", "F2" """
    s = sw.upper().replace("_", " ")
    if s.isdigit() or (s[:1] in "DF" and s[1:].isdigit()):
        return s
    table = names()
    exact = [k for k, v in table.items() if v == s]
    if exact:
        return exact[0]
    part = [k for k, v in table.items() if s in v]
    if len(part) == 1:
        return part[0]
    raise SystemExit("sw.py: %r matches %s" % (
        sw, ", ".join(table[p] for p in part) or "no switch"))


def line(key, closed):
    """the shim's command for one switch"""
    if key[0] == "D":                     # coin door: bank 0, D1 = bit 0
        return "sys 0 %d %d" % (int(key[1:]) - 1, closed)
    if key[0] == "F":                     # flippers: bank 1
        return "sys 1 %d %d" % (int(key[1:]) - 1, closed)
    return "sw %s %d" % (key, closed)


def send(*lines):
    with open(os.path.join(rig_dir(), "ctl"), "w") as f:
        for ln in lines:
            f.write(ln + "\n")


def tap(key, ms=200):
    send(line(key, 1))
    time.sleep(ms / 1000.0)
    send(line(key, 0))


def state():
    out = {}
    try:
        with open(os.path.join(rig_dir(), "state")) as f:
            for ln in f:
                k, _, v = ln.strip().partition(" ")
                out[k] = v
    except OSError:
        return {}
    b = dict(kv.split("=", 1) for kv in out.get("balls", "").split() if "=" in kv)

    def bits(hexs, base):
        on = []
        for c in range(len(hexs) // 2):
            v = int(hexs[2 * c:2 * c + 2], 16)
            on += [base(c, r) for r in range(8) if v >> r & 1]
        return on

    sols = int(out.get("sols", "0"), 16)
    return {
        "switches_raw": bits(out.get("sw", ""), lambda c, r: (c + 1) * 10 + r + 1),
        "lamps_on": bits(out.get("lamps", ""), lambda c, r: (c + 1) * 10 + r + 1),
        "coils_on": [n + 1 for n in range(32) if sols >> n & 1],
        "frames": int(out.get("frames", "0")),
        "balls": {"trough": int(b.get("trough", 0)), "shooter": int(b.get("shooter", 0) or 0) > 0,
                  "in_play": int(b.get("play", 0)),
                  "held": [int(x) for x in b.get("held", "").split(",") if x]},
    }


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "list":
        for k, v in sorted(names().items(), key=lambda kv: (kv[0][0].isdigit(), kv[0])):
            print("%4s  %s" % (k, v))
        return 0
    if cmd == "state":
        print(json.dumps(state()))
        return 0
    if cmd in ("plunge", "drain"):
        send(cmd)
        return 0
    if cmd == "hole" and len(argv) == 2:
        send("hole %s" % resolve(argv[1]))
        return 0
    if cmd == "coin":
        for _ in range(int(argv[1]) if len(argv) > 1 else 1):
            tap("D1", 150)
            time.sleep(0.3)
        return 0
    if cmd == "tap" and len(argv) >= 2:
        tap(resolve(argv[1]), int(argv[2]) if len(argv) > 2 else 200)
        return 0
    if cmd in ("on", "off") and len(argv) == 2:
        send(line(resolve(argv[1]), 1 if cmd == "on" else 0))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
