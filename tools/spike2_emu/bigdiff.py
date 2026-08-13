#!/usr/bin/env python3
"""bigdiff.py <pid|game-name> [seconds] [hz] - full-window transient differ:
snapshot the game's ENTIRE rw region every poll, diff against the previous
snapshot with numpy, and log every changed word with a timestamp. The
item-43 method (ask the game causally) applied to time instead of state:
press a switch mid-recording and the words that change ONLY after presses
are the live input path, whatever the disassembly says they should be.

    sudo python3 bigdiff.py godzilla_pro 120 30 > /var/tmp/bigdiff.log &

Built 2026-08-12 (item 17, run 6) after every desk-read address failed the
live test: the per-switch record array @0x7b7d10, the "trackers"
@0x7b130c, the "mask" @0x7aba5a and the recorder head @0x7aa9b8 all sat
BYTE-STABLE through a consumed Select that switched the whole screen.
Numbers that make this viable: the 12.6MB window preads in ~9ms, and a
menu screen's idle churn is ~120 words/s, so press-correlated words are
signal, not needles.

Output: one line per poll that saw changes -
    <epoch_ms> n=<count> <addr>:<old>-><new> <addr>:<old>-><new> ...
capped at MAXSHOW entries per line (count is always exact). Heartbeat
every 5s. Timestamps join swpoke/swpend logs via press edges.

Needs root (ptrace_scope). The guest argument is REQUIRED (a PID, or a
game name matched against /proc cwd) - pgrep-first-match read the wrong
guest once already; this tool refuses to guess.
"""
import os
import subprocess
import sys
import time

import numpy as np

LO, HI = 0x7a5000, 0x13ad000
MAXSHOW = 60


def candidates():
    pids = set()
    for cmd in (["pgrep", "-x", "game"], ["pgrep", "-f", "qemu-arm"]):
        try:
            pids.update(p for p in
                        subprocess.run(cmd, capture_output=True,
                                       text=True).stdout.split()
                        if p.isdigit())
        except OSError:
            pass
    out = []
    for p in sorted(pids, key=int):
        try:
            cwd = os.readlink(f"/proc/{p}/cwd")
        except OSError:
            continue
        out.append((int(p), cwd))
    return out


def resolve(arg):
    if arg.isdigit():
        return int(arg)
    hits = [(p, cwd) for p, cwd in candidates() if f"/games/{arg}" in cwd]
    if len(hits) == 1:
        return hits[0][0]
    print(f"cannot resolve '{arg}' to one guest; candidates:", file=sys.stderr)
    for p, cwd in candidates():
        print(f"  pid {p}  cwd {cwd}", file=sys.stderr)
    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    pid = resolve(sys.argv[1])
    if pid is None:
        return 2
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
    hz = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
    period = 1.0 / hz
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)
    size = HI - LO
    prev = np.frombuffer(os.pread(fd, size, LO), dtype=np.uint32).copy()
    polls = 0
    lines = 0
    t0 = time.time()
    t_end = t0 + secs
    t_beat = t0 + 5.0
    print(f"bigdiff pid {pid} ({sys.argv[1]}) window {LO:#x}-{HI:#x} "
          f"({size/1e6:.1f}MB) {secs:.0f}s @{hz:.0f}Hz", flush=True)
    while time.time() < t_end:
        t_next = time.time() + period
        polls += 1
        now = int(time.time() * 1000)
        try:
            cur = np.frombuffer(os.pread(fd, size, LO), dtype=np.uint32)
        except OSError:
            print(f"{now} guest gone", flush=True)
            return 1
        idx = np.flatnonzero(cur != prev)
        if idx.size:
            lines += 1
            shown = idx[:MAXSHOW]
            parts = " ".join(
                f"{LO + 4*int(i):#x}:{int(prev[i]):#x}->{int(cur[i]):#x}"
                for i in shown)
            extra = "" if idx.size <= MAXSHOW else f" (+{idx.size-MAXSHOW})"
            print(f"{now} n={idx.size} {parts}{extra}", flush=True)
            prev[idx] = cur[idx]
        if time.time() >= t_beat:
            print(f"{now} beat polls={polls} rate="
                  f"{polls/(time.time()-t0):.0f}/s difflines={lines}",
                  flush=True)
            t_beat += 5.0
        rest = t_next - time.time()
        if rest > 0:
            time.sleep(rest)
    print(f"{int(time.time()*1000)} done polls={polls} difflines={lines}",
          flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
