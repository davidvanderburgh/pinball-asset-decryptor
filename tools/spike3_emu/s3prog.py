#!/usr/bin/env python3
"""s3prog.py SLOT_DIR - how far a Spike 3 run's boot has got, for the
Emulate tab's footer (PAD-1090), as Spike 2's status.sh boot_pct is.

Prints one line each time the boot moves, then exits once the game is up:

    [s3run] progress boot  PCT  TEXT    the game starting, until it asks for
                                        its node boards
    [s3run] progress nodes PCT  TEXT    node boards claimed / declared
    [s3run] progress run   100  TEXT    the lamps are lit: attract

Read off the run's own files - the bridge log (the node directory, each
board's claim) and dump/padled (lamp writes) - so nothing in the game is
touched. The boot share is by time: a game on this rig asks for its first
board ~6 s after it starts (BOOT_S), and its lamps light ~50 s after the
boards are claimed (NODES_S); both only steer the bar inside a step.
"""
import os
import re
import struct
import sys
import time

BOOT_S = float(os.environ.get("PAD_S3_PROG_BOOT_S", "8"))
NODES_S = float(os.environ.get("PAD_S3_PROG_NODES_S", "50"))
GIVE_UP_S = 600
#: after the lamps light, how long Guided Setup may take to appear before the
#: run is called ready anyway (a title that never shows it)
GUIDED_WAIT_S = float(os.environ.get("PAD_S3_PROG_GUIDED_S", "25"))


def guided(sd):
    """s3press.py autoguide's SLOT/guided.state, or "" (not running)."""
    try:
        with open(os.path.join(sd, "guided.state")) as f:
            return f.read().strip()
    except OSError:
        return ""


def state(sd):
    """(declared boards, claimed boards, lamps written)"""
    declared = claimed = 0
    try:
        with open(os.path.join(sd, "bridge.log"), errors="replace") as f:
            for line in f:
                if line.startswith("# node directory"):
                    declared = len(re.findall(r"\d+=\w+", line.split(":", 1)[-1]))
                elif line.startswith("# [node]") and " claims " in line:
                    claimed += 1
    except OSError:
        pass
    lamps = 0
    try:
        with open(os.path.join(sd, "dump", "padled"), "rb") as f:
            hdr = f.read(20)
        if len(hdr) == 20 and struct.unpack_from("<I", hdr, 0)[0] == 0x44454C50:
            lamps = struct.unpack_from("<I", hdr, 12)[0]
    except OSError:
        pass
    return declared, claimed, lamps


def main():
    sd = sys.argv[1]
    t0 = time.time()
    last = None
    t_claimed = None
    t_lamps = None
    while time.time() - t0 < GIVE_UP_S:
        declared, claimed, lamps = state(sd)
        now = time.time()
        g = guided(sd)
        if lamps:
            t_lamps = t_lamps or now
        if lamps and g == "walking":
            line = ("nodes", 97, "Getting past Guided Setup (automatic - "
                    "hands off for a moment)")
        elif lamps and g == "watching" and now - t_lamps < GUIDED_WAIT_S:
            line = ("nodes", 96, "The game is starting")
        elif lamps:
            line = ("run", 100, "Running - the game is in attract")
        elif declared and claimed >= declared:
            t_claimed = t_claimed or now
            pct = 75 + min(20, int(20 * (now - t_claimed) / NODES_S))
            line = ("nodes", pct, "Node boards found (%d of %d); the game is starting" % (claimed, declared))
        elif claimed:
            pct = 60 + int(15 * claimed / max(1, declared))
            line = ("nodes", pct, "Locating node boards (%d of %d)" % (claimed, declared or claimed))
        else:
            pct = 45 + min(15, int(15 * (now - t0) / BOOT_S))
            line = ("boot", pct, "Booting the game")
        if line != last:
            print("[s3run] progress %s %d %s" % line, flush=True)
            last = line
        if line[0] == "run":
            return 0
        time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
