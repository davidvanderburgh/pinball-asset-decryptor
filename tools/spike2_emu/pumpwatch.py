#!/usr/bin/env python3
"""pumpwatch.py <pid|game-name> [seconds] - byte-diff watch of the game's
service-input state through /proc/<pid>/mem, timestamped, so the event
pipeline's LIVE cadence - the one number item 17 still needs - is read
directly instead of inferred from consumption lotteries.

    sudo python3 pumpwatch.py godzilla_pro 300 > /var/tmp/pumpwatch.log &

WHAT IS WATCHED (godzilla_pro 1.15.0, live-verified in run 6 and corrected
2026-08-13): the LIVE addresses of the scheduler engine. qemu-user loads
this guest with GUEST_BASE=+0x10000, so live = ELF + 0x10000 - run 5 read
raw ELF addresses and every one of its live claims was garbage for exactly
that reason. Current regions: the scheduler block (live 0x7c7e80: ring
head/current event/pass counter +0x1c/LIFO freelist +0xd4), the SIGEV
generation word (live 0x7f6658, 60 Hz when the beat flows), the QA edit
pane cluster (live 0x7c9080: value +0xc, busy +0x34, blink +0xf4), and the
pump timer table (live 0x7c9310).

Any byte changing in these regions prints as a contiguous-run diff line.
The first argument is REQUIRED and names the guest: a PID, or a game name
matched against each candidate's /proc cwd (pgrep-first-match read the
WRONG GUEST during the 2026-08-12 two-run collision; this tool refuses to
guess). Needs root (ptrace_scope). Timestamps are host epoch ms - they
join swpoke output and shim swpend lines via the press edges both sides
see. A heartbeat prints every 5 s with cumulative counts and the measured
poll rate, so a log that stopped moving is distinguishable from a pipeline
that stopped moving.
"""
import os
import struct
import subprocess
import sys
import time

# GUEST_BASE (2026-08-13): qemu-user loads this guest shifted +0x10000, so a
# LIVE /proc address = ELF address + GUEST_BASE. Region addresses below are
# LIVE. Run 5 read raw ELF addresses and got garbage; do not repeat that.
GUEST_BASE = 0x10000

REGIONS = (
    # Live-verified set (run 6): sched is the scheduler block (ELF 0x7b7e80):
    # +0 ring head, +4 current event, +0x1c pass counter (60Hz when alive),
    # +0xd4 LIFO freelist. gen is the SIGEV generation word (ELF 0x7e6658).
    # val is the QA edit pane cluster (ELF 0x7b9080): +0xc value state,
    # +0x34 busy, +0xf4 blink. ptmr is the pump timer table (ELF 0x7b9310).
    ('sched', 0x7c7e80, 0xe0),
    ('gen',   0x7f6650, 0x10),
    ('val',   0x7c9080, 0x100),
    ('ptmr',  0x7c9310, 0x60),
)


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


def runs(old, new):
    """Contiguous changed-byte runs as (offset, oldbytes, newbytes)."""
    out = []
    i, n = 0, len(new)
    while i < n:
        if old[i] != new[i]:
            j = i
            while j < n and old[j] != new[j]:
                j += 1
            out.append((i, old[i:j], new[i:j]))
            i = j
        else:
            i += 1
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    pid = resolve(sys.argv[1])
    if pid is None:
        return 2
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 300.0
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)
    last = {}
    changes = 0
    polls = 0
    t0 = time.time()
    t_end = t0 + secs
    t_beat = t0 + 5.0
    print(f"pumpwatch pid {pid} ({sys.argv[1]}) {secs:.0f}s "
          f"regions={[(n, hex(a), hex(l)) for n, a, l in REGIONS]}",
          flush=True)
    while time.time() < t_end:
        polls += 1
        now = int(time.time() * 1000)
        for name, base, length in REGIONS:
            try:
                buf = os.pread(fd, length, base)
            except OSError:
                print(f"{now} guest gone", flush=True)
                return 1
            prev = last.get(name)
            if prev is not None and prev != buf:
                for off, ob, nb in runs(prev, buf):
                    print(f"{now} {name}+{off:#x} ({base+off:#x}) "
                          f"{ob.hex()} -> {nb.hex()}", flush=True)
                    changes += 1
            last[name] = buf
        if time.time() >= t_beat:
            rate = polls / (time.time() - t0)
            print(f"{now} beat polls={polls} rate={rate:.0f}/s "
                  f"changes={changes}", flush=True)
            t_beat += 5.0
        time.sleep(0.005)
    print(f"{int(time.time()*1000)} done polls={polls} changes={changes}",
          flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
