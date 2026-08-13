# correlate8.py <ringwatch.log> <manifest.csv> - join run 8's press train
# against the ringwatch capture and put every press in exactly one bucket of
# the trichotomy (item 17):
#   CONSUMED  value word 0x7c908c flipped
#   (c) DISPATCHED-CANCELLED  coroutine ran (current-event moved / pane busy
#       cycled) but the value never flipped
#   (b) POSTED-NOT-DISPATCHED  a node armed / the freelist popped, but no
#       dispatch inside the window
#   (a) NEVER-POSTED  the edge reached the entry struct or producer list and
#       nothing downstream moved at all
#   NOT-DELIVERED  nothing moved anywhere (should not happen; runs 5-7b
#       proved delivery on both transports)
import collections
import re
import sys

LOG, MANIFEST = sys.argv[1], sys.argv[2]
WIN_MS = int(sys.argv[3]) if len(sys.argv) > 3 else 4000

# named words, by absolute live address
VALUE = 0x7c908c
BUSY = (0x7c90b4, 0x7c9174)
RING_HEAD, RING_CUR = 0x7c7e80, 0x7c7e84
FREE_HEAD = 0x7c7f54
RETIRE = 0x9dc54c
LVL = 0x852108
PARITY = 0x852106

line_re = re.compile(r'^(\d{13}) (\w+)\+(0x[0-9a-f]+) \((0x[0-9a-f]+)\) '
                     r'([0-9a-f]+) -> ([0-9a-f]+)$')

events = []          # (ms, region, abs_addr, old, new)
for ln in open(LOG, errors='replace'):
    m = line_re.match(ln.strip())
    if m:
        events.append((int(m.group(1)), m.group(2), int(m.group(4), 16),
                       m.group(5), m.group(6)))
events.sort()
print(f"{len(events)} change records, "
      f"{events[0][0] if events else 0}..{events[-1][0] if events else 0}")


def touched(lo, hi, region=None, addr=None, span=None):
    """First timestamp in [lo,hi] matching region/addr/span, else None."""
    for ms, reg, a, ob, nb in events:
        if ms < lo or ms > hi:
            continue
        if region and reg != region:
            continue
        if addr is not None and not (a <= addr < a + max(1, len(ob) // 2)):
            continue
        if span and not (span[0] <= a < span[1]):
            continue
        return ms
    return None


presses = []
for ln in open(MANIFEST, errors='replace'):
    parts = ln.strip().split(',')
    if len(parts) < 4 or not parts[0].isdigit():
        continue
    presses.append((int(parts[0]), int(parts[1]), int(parts[2]),
                    int(parts[3])))

buckets = collections.Counter()
print()
print("ord btn  t_rel   lvl  par  prod  ev  free  head  cur  busy  RETIRE "
      " value   VERDICT")
t_zero = presses[0][3] if presses else 0
for ord_, width, btn, t0 in presses:
    lo, hi = t0 - 200, t0 + WIN_MS
    # the door bits live in BYTE 1 of the level word (id 25-28 = bits 8-11),
    # so match the whole word as a span - keying on 0x852108 alone matched
    # nothing and read as "not delivered" for every press.
    lvl = touched(lo, hi, span=(0x852108, 0x85210c))
    par = touched(lo, hi, span=(0x852104, 0x852108))
    prod = touched(lo, hi, region='prod')
    ev = touched(lo, hi, region='ev')
    free = touched(lo, hi, addr=FREE_HEAD)
    head = touched(lo, hi, addr=RING_HEAD)
    cur = touched(lo, hi, addr=RING_CUR)
    busy = min([t for t in (touched(lo, hi, addr=BUSY[0]),
                            touched(lo, hi, addr=BUSY[1])) if t], default=None)
    ret = touched(lo, hi, addr=RETIRE)
    val = touched(lo, hi, addr=VALUE)

    if val:
        verdict = "CONSUMED"
    elif cur or busy:
        verdict = "(c) DISPATCHED-CANCELLED"
    elif ev or free:
        verdict = "(b) POSTED-NOT-DISPATCHED"
    elif lvl or par or prod:
        verdict = "(a) NEVER-POSTED"
    else:
        verdict = "NOT-DELIVERED"
    buckets[verdict] += 1

    def d(t):
        return f"{t-t0:+5d}" if t else "    ."
    print(f"{ord_:3d} {btn:3d} {(t0-t_zero)/1000:7.1f}s {d(lvl)} {d(par)} "
          f"{d(prod)} {d(ev)} {d(free)} {d(head)} {d(cur)} {d(busy)} "
          f"{d(ret)} {d(val)}  {verdict}")

print()
for k, v in buckets.most_common():
    print(f"{v:3d}  {k}")

# Band structure: gaps in engine activity, so deaf/awake stretches are visible
print()
print("engine-activity gaps > 1500 ms (deaf bands):")
last = None
for ms, reg, a, ob, nb in events:
    if reg not in ('ev', 'pane', 'sched', 'free'):
        continue
    if last and ms - last > 1500:
        print(f"  {(last-t_zero)/1000:7.1f}s .. {(ms-t_zero)/1000:7.1f}s "
              f"({(ms-last)/1000:.1f} s quiet)")
    last = ms
