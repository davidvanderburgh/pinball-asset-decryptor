#!/usr/bin/env python3
"""swwidth.py <gamelog> [ladder_manifest] - how WIDE does a switch closure have
to be before the game sees it?

  swwidth.py /home/david/gz_item17.log /home/david/ladder.txt

Reads two traces out of one run log and joins them:

  [sw]     <ms> ms +34 / -34     what the SHIM handed the game - the merged
                                 array's own edges, so this is the closure the
                                 emulator delivered, not the one asked for.
  [swpend] <ms> ms id=34 ... lvl=1
                                 what the GAME recorded - entry[+24], written by
                                 its own scan drain on the far side of its
                                 debounce. THIS is the oracle. A press that
                                 moved `lvl` was received; one that did not was
                                 not, whatever the screen did.

THE LEVELS ARE ACTIVE LOW AND THE FIRST VERSION OF THIS TOOL GOT IT BACKWARDS.
At rest a switch reads `sent=1 cur=1 lvl=1`; MADE is 0. Testing "is lvl 1 in the
window" therefore answered "did any line get logged", which produced a table
where 10 ms registered and 400 ms did not - an ordering with no physical meaning,
which is how the mistake was caught. The oracle is `lvl` DIFFERING from its own
resting value, taken per closure from the last line before the press.

`samples` IS THE SECOND HALF OF THE ANSWER and is why "not seen" is not one
outcome but two. `[swpend]` only prints when something moved, and `sent` only
moves when the shim answers a bus scan for that switch's NODE - so zero samples
inside a closure means the game never looked at that node while the switch was
made, which is a sampling-rate fault. Samples with no `lvl` move would be a
debounce rejecting it, which is a different bug with a different fix.

The manifest (swladder.py's stdout) supplies what was ASKED for. It is joined by
ORDER per id, because nothing in the guest's log knows the intent - so a run
where the ladder was interrupted will mis-align, and the tool says so rather
than quietly reporting nonsense.

WITHOUT a manifest it still works and reports delivered width against seen/not
seen, which is the honest fallback when the ladder was not the thing driving the
switch.

WHY `lvl` AND NOT THE SCREEN: item 17's first data point was "150 ms did nothing
and 900 ms started a game", taken with the trough in a different state each time.
That oracle moves. This one cannot.
"""
import re
import sys
from collections import defaultdict

RE_SW = re.compile(r'^\[sw\]\s+(\d+)\s+ms\s+(.*)$')
RE_EDGE = re.compile(r'([+-])(\d+)')
RE_PEND = re.compile(r'^\[swpend\]\s+(\d+)\s+ms\s+id=(\d+)\b.*?\blvl=(\d+)')
RE_ASK = re.compile(r'^\[ladder\]\s+\d+/\d+\s+round=(\d+)\s+id=(\d+)\s+ask=(\d+)ms')

#: A closure the game debounces can land in `lvl` a little after the release, so
#: the window is widened rather than closed at the release edge. 250 ms is well
#: past any debounce this machine has shown and still far short of the 1 s gap
#: swladder.py leaves between pokes, so it cannot borrow the next poke's answer.
TAIL_MS = 250


def parse(path):
    edges = defaultdict(list)          # id -> [(ms, +1/0)]
    pend = defaultdict(list)           # id -> [(ms, lvl)]
    with open(path, 'r', errors='replace') as fh:
        for line in fh:
            m = RE_SW.match(line)
            if m:
                t = int(m.group(1))
                for sign, sw in RE_EDGE.findall(m.group(2)):
                    edges[int(sw)].append((t, 1 if sign == '+' else 0))
                continue
            m = RE_PEND.match(line)
            if m:
                pend[int(m.group(2))].append((int(m.group(1)), int(m.group(3))))
    return edges, pend


def pairs(seq):
    """(press_ms, release_ms) for each 0->1->0 in one id's edge list."""
    out, open_at = [], None
    for t, up in seq:
        if up and open_at is None:
            open_at = t
        elif not up and open_at is not None:
            out.append((open_at, t))
            open_at = None
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    edges, pend = parse(sys.argv[1])
    asks = defaultdict(list)
    if len(sys.argv) > 2:
        with open(sys.argv[2], 'r', errors='replace') as fh:
            for line in fh:
                m = RE_ASK.match(line)
                if m:
                    asks[int(m.group(2))].append(int(m.group(3)))

    if not edges:
        print('no [sw] lines in %s - was PAD_SW_LOG off?' % sys.argv[1])
        return 1
    if not pend:
        print('NO [swpend] LINES. The oracle is missing, so this can only say '
              'what was delivered and not what the game saw.')
        print('Re-run with PAD_SW_PEND=<ids> set before watch.sh.')

    for sw in sorted(edges):
        ps = pairs(edges[sw])
        if not ps:
            continue
        ask = asks.get(sw, [])
        aligned = len(ask) == len(ps)
        print()
        print('=== switch %d: %d closure(s) delivered, %d asked for%s'
              % (sw, len(ps), len(ask),
                 '' if aligned or not ask else '  *** MIS-ALIGNED ***'))
        if ask and not aligned:
            print('    The manifest and the log disagree on how many pokes '
                  'happened, so ask-vs-seen below is NOT trustworthy. A lost '
                  'closure would itself be the finding - check the ladder ran '
                  'to completion before reading anything into it.')
        by_ask = defaultdict(lambda: [0, 0, 0])
        rows = []
        trace = pend.get(sw, [])
        for i, (t0, t1) in enumerate(ps):
            # The resting level for THIS closure, not a constant: take the last
            # thing the game recorded before the press. Assuming 1 would be
            # wrong the moment a switch is left held by something else.
            base = 1
            for t, lvl in trace:
                if t < t0 - 2:
                    base = lvl
                else:
                    break
            window = [(t, lvl) for t, lvl in trace
                      if t0 - 2 <= t <= t1 + TAIL_MS]
            seen = any(lvl != base for _, lvl in window)
            a = ask[i] if aligned else None
            rows.append((a, t1 - t0, len(window), seen))
            if a is not None:
                by_ask[a][0] += 1
                by_ask[a][1] += 1 if seen else 0
                by_ask[a][2] += len(window)
        print('    %-8s %-10s %-8s %s'
              % ('asked', 'delivered', 'samples', 'game saw it'))
        for a, d, ns, seen in rows:
            print('    %-8s %-10s %-8d %s'
                  % ('%d ms' % a if a is not None else '?', '%d ms' % d, ns,
                     'yes' if seen else ('NO (never scanned)' if not ns
                                         else 'NO (scanned, ignored)')))
        if by_ask:
            print('    --- by asked duration ---')
            floor = None
            for a in sorted(by_ask):
                n, ok, ns = by_ask[a]
                print('    %4d ms  %d/%d seen, %.1f samples/closure'
                      % (a, ok, n, ns / float(n)))
                if ok == n and floor is None:
                    floor = a
                elif ok != n:
                    floor = None
            print('    shortest duration clean on EVERY poke: %s'
                  % ('%d ms' % floor if floor is not None else 'none of them'))
    return 0


sys.exit(main())
