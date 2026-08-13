#!/usr/bin/env python3
"""doortrack.py <pid|game-name> [seconds] - watch the game's four
door-button HELD-TRACKER objects and print every change, timestamped, so a
press's fate past entry[+24] is finally observable.

    python3 doortrack.py godzilla_pro 240 > ~/doortrack.log &

The guest argument is REQUIRED: pgrep's first match read the WRONG GUEST
during the 2026-08-12 two-run collision (a hidden turtles run) and produced
garbage that looked like bad addresses. A game name is matched against each
candidate's /proc cwd; anything ambiguous is refused with the candidate
list. pumpwatch.py watches these trackers PLUS the event pump words on one
clock - prefer it for new measurements.

WHY THESE FOUR ADDRESSES (godzilla_pro 1.15.0, found in the ELF 2026-08-12,
item 17's desk-read pass). The menu never polls switch levels: a door-button
press becomes an EVENT whose coroutine (0x23b8f0 -> 0x23b4d0) RE-READS the
live level at dispatch time and silently cancels if the button already reads
released; a press that survives starts a tracker object at a fixed global,
count = 1 immediately, and menu screens consume by decrementing the count.
So the tracker moving IS "the game acted", independent of anything the
screen draws - the oracle run 3 did not have:

    0x7b130c  code 19      0x7b1320  code 18
    0x7b133c  code 17      0x7b1350  code 20
    (+0 press count, +4 held ticks, +12 cancel flag byte)

Which action param (1/2/4/8) is which physical button (25/26/27/28) is not
yet mapped - watching all four answers it for free on the first press that
lands.

Poll is ~100 Hz through /proc/<pid>/mem (same access pattern as guestmem.py,
same reason it must be a host tool: the guest cannot read its own globals).
Timestamps are host epoch ms, so lines join against swpoke output and the
shim log's guest-ms via the press edges both sides see.
"""
import os
import struct
import subprocess
import sys
import time

TRACKERS = {
    0x7b130c: 'code19',
    0x7b1320: 'code18',
    0x7b133c: 'code17',
    0x7b1350: 'code20',
}
FIELDS = (0, 4, 12)   # count u32, held-ticks u32, cancel byte


def guest_pid(arg):
    if arg.isdigit():
        return int(arg)
    cands = []
    for cmd in (["pgrep", "-x", "game"], ["pgrep", "-f", "qemu-arm"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True).stdout.split()
        except OSError:
            continue
        for p in out:
            if p.isdigit() and os.path.exists(f"/proc/{p}/mem"):
                try:
                    cwd = os.readlink(f"/proc/{p}/cwd")
                except OSError:
                    continue
                if (int(p), cwd) not in cands:
                    cands.append((int(p), cwd))
    hits = [(p, cwd) for p, cwd in cands if f"/games/{arg}" in cwd]
    if len(hits) == 1:
        return hits[0][0]
    print(f"cannot resolve '{arg}' to one guest; candidates:", file=sys.stderr)
    for p, cwd in cands:
        print(f"  pid {p}  cwd {cwd}", file=sys.stderr)
    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 300.0
    pid = guest_pid(sys.argv[1])
    if not pid:
        return 2
    m = open(f"/proc/{pid}/mem", "rb", buffering=0)
    last = {}
    t_end = time.time() + secs
    print(f"watching pid {pid}, {len(TRACKERS)} trackers, {secs:.0f}s",
          flush=True)
    while time.time() < t_end:
        for addr, name in TRACKERS.items():
            try:
                m.seek(addr)
                buf = m.read(16)
            except OSError:
                print(f"{int(time.time()*1000)} guest gone", flush=True)
                return 1
            cnt, ticks = struct.unpack_from('<II', buf, 0)[0], \
                struct.unpack_from('<I', buf, 4)[0]
            cancel = buf[12]
            cur = (cnt, ticks, cancel)
            if last.get(addr) != cur:
                print(f"{int(time.time()*1000)} {name}@{addr:#x} "
                      f"count={cnt} ticks={ticks} cancel={cancel}",
                      flush=True)
                last[addr] = cur
        time.sleep(0.01)
    return 0


if __name__ == '__main__':
    sys.exit(main())
