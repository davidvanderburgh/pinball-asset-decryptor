#!/usr/bin/env python3
"""pumpwatch.py <pid|game-name> [seconds] - byte-diff watch of the game's
service-input state through /proc/<pid>/mem, timestamped, so the event
pipeline's LIVE cadence - the one number item 17 still needs - is read
directly instead of inferred from consumption lotteries.

    sudo python3 pumpwatch.py godzilla_pro 300 > /var/tmp/pumpwatch.log &

WHAT IS WATCHED (godzilla_pro 1.15.0, live-probed 2026-08-12 on run 6):

  records   0x7b7d10..0x7b8020: a per-switch record ARRAY, stride 0x70,
            vtable 0x6243d8, switch id at +0x14 - ids 0x17..0x1d (23..29,
            the door/service inputs; Select=0x19, Plus=0x1a, Minus=0x1b,
            Back=0x1c). +0x20/+0x24 are byte-packed live state; config
            words at +0x28 read 60,30,30,125 (the 30 matches the
            repeat-onset constant). THE DESK-READ'S "event pool @0x7b7e80 /
            current-event @0x7b7e84" WAS A MISREAD OF THIS ARRAY: those
            addresses are +0x20/+0x24 of the Plus record. Flippers (59/60)
            are NOT in the array - consistent with flippers never driving
            menus.
  trackers  0x7b1300..0x7b1360: the four door-button held trackers
            (0x7b130c/0x7b1320/0x7b133c/0x7b1350: +0 count, +4 ticks,
            +12 cancel).
  mask      0x7aba50..0x7aba60: service class mask u16 @0x7aba5a (bit8
            arms the repeat tracker; read 0 in the rig's menu on run 5).
  recorder  0x7aa9b0..0x7aa9e0: the edge recorder's list head @0x7aa9b8.

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

REGIONS = (
    # Discriminator set (2026-08-12 late night): does the PUMP run during a
    # coroutine stall? ptmr is the pump's 8-entry timer table (decremented
    # once per pump pass, per the ELF read); tickctr is the desk-read's
    # cond-wait counter; cnt/cnt2 churn at ~60Hz through stalls (owner
    # unknown); val covers the QA edit pane's value/busy/blink words.
    ('ptmr',    0x7b9318, 0x60),
    ('tickctr', 0x7e6650, 0x10),
    ('cnt',     0x7c7e98, 0x8),
    ('val',     0x7c9080, 0xd0),
    ('retire',  0x9dc548, 0x8),
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
