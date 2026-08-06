#!/usr/bin/env python3
"""swladder.py <id>[,<id>...] [durations_ms] [rounds] [gap_s] - press a switch
at a LADDER of durations and let the log say which ones the game actually saw.

  swladder.py 34,46 10,20,30,50,80,120,200,400,900 4 1.0

WHY THIS EXISTS. Item 17: a normal-length keystroke sometimes does not register
and the key has to be held noticeably longer. The obvious test - "press Start
for N ms and see whether a game starts" - was tried on 2026-08-06 and is worth
almost nothing, because its oracle moves: the trough state was not identical
across the four presses, so 150 ms doing nothing and 900 ms starting a game is
not a controlled comparison and must not be quoted as one.

SO THE ORACLE HERE IS `lvl`, NOT THE SCREEN. Run with PAD_SW_PEND=<the same
ids>: the shim then logs `[swpend] ... sent= prev= cur= pend= lvl=` every
millisecond a watched switch changes, and `lvl` is the game's OWN entry[+24] -
what its scan drain wrote, on the far side of its debounce. A press either moved
that or it did not, and credits, ball state and what screen the machine is on
cannot change the answer. swwidth.py reads the pair back out.

IT INTERLEAVES BY ROUND, not by duration: all nine durations once, then all nine
again. A descending sweep would confound "shorter presses fail" with "the
machine drifted while we swept", which is the same trap in a different coat.

AND IT JITTERS THE GAP, which the first version did not and which cost a reading.
With a flat 1.0 s gap the pokes are phase-locked to whatever samples them, and
the 2026-08-06 run came back with 400 ms missed 4 times out of 4 on one node
while 10 ms landed 4 times out of 4 on another - an ordering that is impossible
for a sampler with a random phase and obvious for one with a fixed one. The
jitter is what turns "seen or not" into a probability that means something.

Durations are asked for through the SAME scr_held[] channel swpoke.py uses, so
what this measures is the script path. If short presses land here and the
keyboard still needs holding, the fault is in padglhost's X handling and not in
the guest - which is the split item 17 needs and could not make.
"""
import random
import sys
import time

import padsw

DEF_MS = (10, 20, 30, 50, 80, 120, 200, 400, 900)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    ids = [int(x) for x in sys.argv[1].replace(',', ' ').split()]
    durs = ([int(x) for x in sys.argv[2].replace(',', ' ').split()]
            if len(sys.argv) > 2 else list(DEF_MS))
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    gap = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0

    m = padsw.open_block()
    if m is None:
        print('[ladder] no switch block - is a run up?')
        return 1

    # Own every id at whatever the game currently sees, so the first press of
    # each is a real edge rather than a re-assertion of a byte already set.
    padsw.take(m, ids)

    total = len(ids) * len(durs) * rounds
    print('[ladder] %d pokes: ids=%s durations=%s rounds=%d gap=%.2fs '
          '(~%.0fs)' % (total, ids, durs, rounds, gap,
                        total * (gap + 0.5 + sum(durs) / len(durs) / 1000.0)))
    # The manifest is the ONLY record of what was asked for. The guest's log
    # says what was delivered and knows nothing about the intent, so the two are
    # matched by ORDER per id - which is why nothing here may skip a poke.
    n = 0
    for r in range(rounds):
        for ms in durs:
            for sw in ids:
                n += 1
                print('[ladder] %d/%d round=%d id=%d ask=%dms'
                      % (n, total, r + 1, sw, ms), flush=True)
                padsw.set_held(m, sw, 1)
                time.sleep(ms / 1000.0)
                padsw.set_held(m, sw, 0)
                # Uniform over [gap, gap + 1s). Seeded from the clock, so two
                # runs are not the same sequence - the point is to break the
                # phase lock, not to be reproducible.
                time.sleep(gap + random.random())
    m.close()
    print('[ladder] done')
    return 0


sys.exit(main())
