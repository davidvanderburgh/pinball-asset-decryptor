#!/usr/bin/env python3
"""gatewatch.py <pid|game-name> [seconds] - run 7's discriminator: one
passive watcher that separates the four candidate freeze-gate mechanisms
in a single freeze->wake capture (item 17, protocol from the 2026-08-13
gate-hunt synthesis; full report C:\\tmp\\item17\\run6\\
gate_workflow_report.txt).

All addresses are LIVE (= ELF + 0x10000, the qemu guest_base).

ONE-SHOT at start: dump hook chain 0x37's registration list (slot
0x7f4e24): if the sole node is the static callback 0x1c728c with a null
next, the tick-body veto (F2) is dead code; a second node names the
dynamic vetoer.

THEN at ~200 Hz, byte-diff these regions through a freeze->wake:
  sched   0x7c7e80+0x30 : pass counter +0x1c, ring head/current
  free    0x7c7f54      : LIFO freelist head (F4: pinned 0 = exhausted)
  ptmr    0x7c9310+0x60 : pump timer slots (frozen countdowns = body
                          vetoed = F2; moving = body runs)
  pane    0x7c9080+0x100: value +0xc / busy +0x34 / blink +0xf4
  mask    0x7bba50+0x10 : drain post-gate halfword @0x7bba5a (F3) -
                          NEVER actually read before: run 5 read raw
                          0x7aba5a (unshifted) and saw rodata
  lvlraw  0x852100+0x10 : device-reader thread's bitmap (off-tick)
  parity* deref [0x7eb21c] -> pointee +0xa0..0xc0 (bytes +0xb0/b1/b2/b5
                          are the ring half-rate parity source; F1:
                          stuck odd through the freeze)
  snap*   deref [0x7b958c] -> pointee +0..0x40 (game-side switch
                          snapshot the 0x23b4d0 recheck reads; updating
                          during a freeze = drain ran = F2 dead)

Decision tree on the freeze interval:
  ptmr frozen                          -> F2 (body vetoed; chain dump names it)
  ptmr moving + blink frozen + parity odd -> F1 (ring parity stick)
  ptmr moving + parity even + mask bit missing -> F3 (drain post-gate)
  all normal + freelist pinned 0       -> F4 (pool exhaustion)

Needs root. Guest argument REQUIRED (PID or game name vs /proc cwd).
Heartbeat every 5s. Timestamps host epoch ms.
"""
import os
import struct
import subprocess
import sys
import time

GUEST_BASE = 0x10000

STATIC_REGIONS = (
    ('sched',  0x7c7e80, 0x30),
    ('free',   0x7c7f54, 0x4),
    ('ptmr',   0x7c9310, 0x60),
    ('pane',   0x7c9080, 0x100),
    ('mask',   0x7bba50, 0x10),
    ('lvlraw', 0x852100, 0x10),
)
DEREF_REGIONS = (
    # (name, pointer addr, pointee offset, length)
    ('parity', 0x7eb21c, 0xa0, 0x20),
    ('snap',   0x7b958c, 0x0,  0x40),
)
HOOK55_SLOT = 0x7f4e24
STATIC_CB = 0x1c728c


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


def u32(fd, addr):
    return struct.unpack("<I", os.pread(fd, 4, addr))[0]


def dump_hook55(fd):
    node = u32(fd, HOOK55_SLOT)
    print(f"hook55 slot [{HOOK55_SLOT:#x}] = {node:#x}", flush=True)
    seen = 0
    while node and seen < 8:
        try:
            cb, arg, nxt = struct.unpack("<III", os.pread(fd, 12, node))
        except OSError:
            print(f"  node {node:#x}: unreadable", flush=True)
            return
        tag = " (the static return-1 callback)" if cb == STATIC_CB else \
              "  <-- DYNAMIC: disassemble ELF %#x" % (cb - GUEST_BASE)
        print(f"  node {node:#x}: cb={cb:#x} arg={arg:#x} next={nxt:#x}{tag}",
              flush=True)
        node = nxt
        seen += 1
    if seen == 0:
        print("  chain EMPTY - veto impossible this instant", flush=True)


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    pid = resolve(sys.argv[1])
    if pid is None:
        return 2
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 300.0
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)
    dump_hook55(fd)
    regions = list(STATIC_REGIONS)
    for name, ptr, off, length in DEREF_REGIONS:
        try:
            base = u32(fd, ptr)
        except OSError:
            base = 0
        if base:
            print(f"{name}: [{ptr:#x}] -> {base:#x}, watching "
                  f"{base+off:#x}+{length:#x}", flush=True)
            regions.append((name, base + off, length))
        else:
            print(f"{name}: pointer [{ptr:#x}] is NULL - skipped", flush=True)
    last = {}
    changes = 0
    polls = 0
    t0 = time.time()
    t_end = t0 + secs
    t_beat = t0 + 5.0
    print(f"gatewatch pid {pid} ({sys.argv[1]}) {secs:.0f}s "
          f"{len(regions)} regions", flush=True)
    while time.time() < t_end:
        polls += 1
        now = int(time.time() * 1000)
        for name, base, length in regions:
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
            print(f"{now} beat polls={polls} "
                  f"rate={polls/(time.time()-t0):.0f}/s changes={changes}",
                  flush=True)
            t_beat += 5.0
        time.sleep(0.005)
    print(f"{int(time.time()*1000)} done polls={polls} changes={changes}",
          flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
