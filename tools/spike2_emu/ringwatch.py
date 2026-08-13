#!/usr/bin/env python3
"""ringwatch.py <pid|game-name> [seconds] [--evbase 0xADDR] - run 8's
TRICHOTOMY discriminator for item 17.

Runs 6/7/7b left the drop in ONE window with THREE possible branches. The
press is recorded (producer list fires even on deaf presses) and the tick
body calls the drain every pass, yet the menu ignores the press for
multi-second bands. The press can die in exactly one of:

  (a) NEVER POSTED   - the drain saw the edge and did not call the event
                       post 0x2551dc. Signature: producer list head moved,
                       but NO event node changed state and the freelist
                       head did not pop.
  (b) POSTED, NEVER DISPATCHED - a node is allocated and armed, but the
                       ring walker never swapcontexts into it for seconds.
                       Signature: freelist pops + a node arms, ring head
                       moves, but `current` (0x7c7e84) never becomes that
                       node until seconds later.
  (c) DISPATCHED, CANCELLED AT RECHECK - the coroutine runs while the
                       button is already released, so 0x23b4d0's recheck
                       (game-side snapshot behind [0x7b958c], NOT the raw
                       bitmap) cancels it. Signature: `current` becomes the
                       node, pane busy words cycle, value 0x7c908c does NOT
                       flip.

Each branch has a completely different fix, which is why this one capture
is the whole remaining question.

WHAT IT ANSWERED (run 8, 24 presses + run 8b, 16 presses, 2026-08-13):
  (b) IS EMPTY. Nothing is ever posted-and-left-undispatched: on every
      press that posts, the freelist pop, the ring-head move, the node
      write and the pane's busy words all land in the SAME 5 ms sample.
      Dispatch latency does not exist - which retires the "event pump
      cadence" framing runs 5 and 6 built on top of it.
  (c) is a small minority - 3 of 24.
  (a) IS THE DEFECT, and it is further upstream than (a) was defined:
      on a dead press the switch-entry PENDING COUNT (+0x16) never
      increments at all, so the recorder never ran. The drain, the post,
      the ring and the coroutine recheck are all innocent - they were
      never given anything to do.
  Delivery as this item measured it for five runs was measuring the WRONG
  WORD: 0x852108 is the device-level word, and it carries a textbook
  300 ms closure 16/16 on dead and live presses alike. The game's own
  switch layer (*(0x7b958c) + id*32) sees only 10/16.

WHY THIS TOOL EXISTS AND gatewatch.py DOES NOT ANSWER IT: every previous
watcher could only see .data. The event NODES are not in .data - the pool
is one 0x145000 malloc (64 x 320 B events + 64 x 20 KB stacks) mmapped up
near 0xbaa00000 - so "posted" and "dispatched" were both invisible and
looked identical from the globals. This tool follows the live freelist /
ring pointers into the heap and diffs the node array itself.

ALL ADDRESSES ARE LIVE (= ELF + 0x10000, the qemu-user guest_base). Read
reference_spike2_qemu_guest_base before changing any constant here; run 5
was lost to reading raw ELF addresses.

Needs root (ptrace scope). Guest argument REQUIRED - never pgrep's first
match, which in run 4 read the WRONG GUEST's memory.

Output: `<epoch_ms> <name>+<off> (<abs>) <oldhex> -> <newhex>`, plus a
5 s heartbeat carrying poll rate and the three ring pointers. A word that
changes on nearly every poll (an armed event's +0x88 countdown, the RNG)
is AUTOSUPPRESSed after AUTOSUP_AT hits so the log stays readable; its
running total still appears in every heartbeat and in the final line.
"""
import os
import struct
import subprocess
import sys
import time

GUEST_BASE = 0x10000
AUTOSUP_AT = 150          # per-word changes before it stops being printed
POLL_SLEEP = 0.004        # ~200 Hz. The 60 Hz engine cannot hide from this
                          # and it leaves the rig's cores to the game.
EV_WINDOW = 0x10000       # bytes of heap watched around the event pool
EV_BACKOFF = 0x1000       # start the window this far below the lowest ptr

# name, live addr, length
STATIC_REGIONS = (
    ('entry',  0x8520c0, 0xc0),   # switch-entry struct: +0x16 parity byte
                                  # (0x852106), +0x18 level word (0x852108)
    ('prod',   0x7ba9a0, 0x30),   # switch producer list head @0x7ba9b8
    ('sched',  0x7c7e70, 0x40),   # ring head 0x7c7e80 / current 0x7c7e84 /
                                  # ctx 0x7c7e8c / pass counter 0x7c7e9c
    ('free',   0x7c7f50, 0x10),   # event LIFO freelist head @0x7c7f54
    ('mask',   0x7bba50, 0x10),   # global category mask @0x7bba5a: nonzero
                                  # makes the drain a strict whitelist and
                                  # skips the post entirely (0x1e75a0)
    ('pane',   0x7c9080, 0x100),  # value +0xc (0x7c908c) / busy +0x34 /
                                  # busy +0xf4 - the consumption oracle
)
# name, pointer addr, offset into pointee, length
#
# RUN 8b. Run 8 answered the trichotomy and moved the question upstream, so
# these follow the structures the RECORDER touches, from the 2026-08-13
# drain/ring disassembly (C:\tmp\item17\run8\drain_ring_report.txt):
#   entries  the real switch-entry array is *(0x7b958c) + id*32, stride
#            proven three ways - NOT the 0x8520f0 the earlier passes
#            assumed. ids 25-28 (Select/Plus/Minus/Back) start at 25*32.
#            +0x16 = PENDING EDGE COUNT, incremented by the recorder
#            0x1e78f4 and decremented by the drain; +0x18 = the debounced
#            level byte, the ONLY thing 0x23b4d0's recheck reads; +0x04 =
#            the producer-list link. If a dead press never bumps +0x16 the
#            recorder swallowed it and nothing downstream ever had a
#            chance.
#   rgate    *(0x7b9594)[auxid] - one of the recorder's two swallow gates
#            (0x1e79e4); nonzero absorbs the edge silently.
#   mgate    *(0x7b93a0) - the SECOND, independent switch bitmap that the
#            menu handler's two undocumented early exits read (0x23b4d8 /
#            0x23b4f0, switches 3 and 4). Set = every menu press is
#            discarded before the level recheck.
DEREF_REGIONS = (
    ('entries', 0x7b958c, 25 * 32, 0x80),
    ('rgate',   0x7b9594, 0x0, 0x40),
    ('mgate',   0x7b93a0, 0x0, 0x10),
    ('snap',    0x7b958c, 0x0, 0x40),
)
RING_HEAD, RING_CUR, RING_PASS, FREE_HEAD = 0x7c7e80, 0x7c7e84, 0x7c7e9c, \
    0x7c7f54


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
            out.append((int(p), os.readlink(f"/proc/{p}/cwd")))
        except OSError:
            continue
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
    """Raw word at a LIVE address."""
    try:
        return struct.unpack("<I", os.pread(fd, 4, addr))[0]
    except OSError:
        return 0


def deref(fd, addr):
    """Follow a pointer stored in guest memory and return a LIVE address.

    THE TRAP THIS FUNCTION EXISTS FOR: a pointer VALUE held in guest memory
    is a GUEST address, so it needs the +0x10000 guest_base shift before
    /proc/<pid>/mem can read it - exactly like the static addresses do.
    Run 8's first capture pointed its heap window at an unshifted ring
    pointer, landed 0x10000 low, and read a mapping that had nothing to do
    with the event pool - while the read SUCCEEDED, so nothing complained.
    gatewatch.py's DEREF_REGIONS has the same defect: its run-7 'parity'
    and 'snap' regions were 0x10000 low, which is why they "never changed
    once" - so run 7's F1 verdict rests on a bad read and is REOPENED.
    """
    p = u32(fd, addr)
    return p + GUEST_BASE if p else 0


def pool_maps(pid):
    """Every writable mapping. NO size filter: the run-8 first attempt
    filtered to 0x100000..0x400000, the pool's mapping was outside it, the
    window was placed in an unmapped hole, and os.pread returned b'' - a
    SHORT READ, not an error, so the node half went silently blind. Read
    the whole table and pick by containment."""
    out = []
    try:
        with open(f"/proc/{pid}/maps") as f:
            for line in f:
                rng, perms = line.split()[0], line.split()[1]
                lo, hi = (int(x, 16) for x in rng.split('-'))
                if 'w' in perms:
                    out.append((lo, hi, line.rstrip()))
    except OSError:
        pass
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    argv = [a for a in sys.argv[1:] if not a.startswith('--')]
    evbase = None
    for i, a in enumerate(sys.argv):
        if a == '--evbase':
            evbase = int(sys.argv[i + 1], 0)
    pid = resolve(argv[0])
    if pid is None:
        return 2
    secs = float(argv[1]) if len(argv) > 1 else 300.0
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)

    # ...as LIVE addresses: the stored values are guest pointers.
    head, cur, free = (deref(fd, a) for a in (RING_HEAD, RING_CUR, FREE_HEAD))
    print(f"ring head [{RING_HEAD:#x}]={head:#x}  current "
          f"[{RING_CUR:#x}]={cur:#x}  freelist [{FREE_HEAD:#x}]={free:#x}"
          f"  (live, guest_base already added)", flush=True)
    poolmap = None
    for lo, hi, line in pool_maps(pid):
        if not any(p and lo <= p < hi for p in (head, cur, free)):
            continue
        poolmap = (lo, hi)
        print(f"  pool map {lo:#x}-{hi:#x} ({hi-lo:#x}) holds a ring pointer",
              flush=True)

    regions = list(STATIC_REGIONS)
    for name, ptr, off, length in DEREF_REGIONS:
        base = deref(fd, ptr)
        if base > 0x100000:   # below that it is a small int, not a pointer
            print(f"{name}: [{ptr:#x}] -> {base:#x}, watching "
                  f"{base+off:#x}+{length:#x}", flush=True)
            regions.append((name, base + off, length))
        else:
            print(f"{name}: pointer [{ptr:#x}] = {base:#x} - skipped",
                  flush=True)

    evlen = EV_WINDOW
    if evbase is None:
        live = [p for p in (head, cur, free) if p > 0x10000000]
        if live:
            # The 64-node array is at the START of the one 0x145000 pool
            # malloc (the 20 KB stacks follow it), so anchor on the mapping
            # when the pointers sit near its base - that catches all 64
            # nodes. Only fall back to centring on the pointers when they
            # are too deep in for the window to reach back.
            if poolmap and 0 <= min(live) - poolmap[0] <= EV_WINDOW - 0x1000:
                evbase = poolmap[0]
            else:
                evbase = (min(live) & ~0xFFF) - EV_BACKOFF
            if poolmap:   # never let the window leave the mapping
                evbase = max(evbase, poolmap[0])
                evlen = min(EV_WINDOW, poolmap[1] - evbase)
    if evbase:
        got = len(os.pread(fd, evlen, evbase))
        if got != evlen:
            print(f"events: SHORT READ {got:#x} of {evlen:#x} at "
                  f"{evbase:#x} - refusing to run half-blind", flush=True)
            return 2
        print(f"events: watching {evbase:#x}+{evlen:#x} "
              f"(node stride 0x140 - group offsets by it in analysis)",
              flush=True)
        regions.append(('ev', evbase, evlen))
    else:
        print("events: NO heap pointer found - node half of the "
              "trichotomy is BLIND this run", flush=True)

    last, hits, supp = {}, {}, set()
    polls = changes = 0
    t0 = time.time()
    t_end, t_beat = t0 + secs, t0 + 5.0
    print(f"ringwatch pid {pid} ({argv[0]}) {secs:.0f}s "
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
                    key = (name, off)
                    n = hits.get(key, 0) + 1
                    hits[key] = n
                    changes += 1
                    if key in supp:
                        continue
                    if n > AUTOSUP_AT:
                        supp.add(key)
                        print(f"{now} AUTOSUPPRESS {name}+{off:#x} "
                              f"({base+off:#x}) after {n}", flush=True)
                        continue
                    print(f"{now} {name}+{off:#x} ({base+off:#x}) "
                          f"{ob.hex()} -> {nb.hex()}", flush=True)
            last[name] = buf
        if time.time() >= t_beat:
            h, c, f_ = (deref(fd, a) for a in
                        (RING_HEAD, RING_CUR, FREE_HEAD))
            p = u32(fd, RING_PASS)
            print(f"{now} beat polls={polls} "
                  f"rate={polls/(time.time()-t0):.0f}/s changes={changes} "
                  f"head={h:#x} cur={c:#x} free={f_:#x} pass={p}", flush=True)
            t_beat += 5.0
        # PACE IT. Without this the loop free-runs at ~146 kHz, pegs a core
        # and perturbs the very timing the run is measuring - which is
        # exactly how run 8's first capture had to be thrown away.
        time.sleep(POLL_SLEEP)
    top = sorted(hits.items(), key=lambda kv: -kv[1])[:12]
    print(f"{int(time.time()*1000)} done polls={polls} changes={changes}",
          flush=True)
    for (name, off), n in top:
        print(f"  top {name}+{off:#x} {n}", flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
