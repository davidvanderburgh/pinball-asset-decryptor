# queuewatch.py <pid> [secs] - producer-starvation discriminator (item 17
# run 7b). RESULT: it FALSIFIED producer starvation - the switch producer
# list head 0x7ba9b8 fired on deaf presses too, so the drop is downstream
# of the producer list, in event post->dispatch->recheck. Kept as the
# reusable watcher shell. Needs root; all addresses LIVE (= ELF+0x10000).
# Watches the switch producer list head, pump queue ptrs+mutex,
# body pass-proof counters (RNG state, tween countdown, scan divider),
# pane cluster, and raw level word.
import os
import struct
import sys
import time

PID = int(sys.argv[1])
SECS = float(sys.argv[2]) if len(sys.argv) > 2 else 240.0
REGIONS = (
    ('swq',   0x7ba9b0, 0x10),   # switch producer list head @0x7ba9b8
    ('pumpq', 0x7c8a90, 0x10),   # pump queue head/tail @0x7c8a94/98
    ('qmux',  0x714bf0, 0x10),   # pump queue mutex word @0x714bf4
    ('rng',   0x716440, 0x18),   # xorshift state - changes EVERY pass
    ('tween', 0x7bc6b0, 0x8),    # 20fb28 countdown - every pass
    ('div',   0x7f3534, 0x8),    # 46b478 divider halfword @0x7f3538
    ('pane',  0x7c9080, 0x100),  # value +0xc / busy +0x34 / blink +0xf4
    ('lvl',   0x852100, 0x10),   # device-reader bitmap (off-tick)
)
fd = os.open(f"/proc/{PID}/mem", os.O_RDONLY)


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


last = {}
polls = 0
changes = 0
t0 = time.time()
t_end = t0 + SECS
t_beat = t0 + 5.0
suppress = {'rng'}   # rng changes every pass; log per-beat only
print(f"queuewatch pid {PID} {SECS:.0f}s", flush=True)
while time.time() < t_end:
    polls += 1
    now = int(time.time() * 1000)
    for name, base, length in REGIONS:
        try:
            buf = os.pread(fd, length, base)
        except OSError:
            print(f"{now} guest gone", flush=True)
            sys.exit(1)
        prev = last.get(name)
        if prev is not None and prev != buf and name not in suppress:
            for off, ob, nb in runs(prev, buf):
                print(f"{now} {name}+{off:#x} ({base+off:#x}) "
                      f"{ob.hex()} -> {nb.hex()}", flush=True)
                changes += 1
        last[name] = buf
    if time.time() >= t_beat:
        rngstate = last.get('rng', b'').hex()[:16]
        print(f"{now} beat polls={polls} rate={polls/(time.time()-t0):.0f}/s "
              f"changes={changes} rng={rngstate}", flush=True)
        t_beat += 5.0
    time.sleep(0.005)
print(f"{int(time.time()*1000)} done polls={polls} changes={changes}",
      flush=True)
