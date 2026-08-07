#!/usr/bin/env python3
"""ledrate.py - how often does the LED block ACTUALLY change? Ground truth.

RUN THIS INSIDE WSL, next to the guest, while the game is up:

    python3 ledrate.py 30            # 30 seconds
    python3 ledrate.py 30 --csv /tmp/ledrate.csv

WHY IT EXISTS, and it is one subtraction. The playfield window reports its own
LED rate now (see playfield.py), but it reads `dump/padled` from WINDOWS, across
the VM boundary, out of a p9 redirector nobody in this rig has ever measured for
freshness. So a slow picture there has two completely different causes - the
guest is not publishing any faster, or the read is stale - and the window cannot
tell them apart from its own side. This reads the SAME block from inside WSL,
where the mapping is the guest's own page cache and there is no boundary left to
blame. Two numbers from the same run settle it:

  * they agree  -> the game really does drive the lamps in bursts, and the
                   window is showing everything it is given. Do not go looking
                   for a transport bug.
  * WSL is much faster -> the crossing is dropping updates, and the window's
                   rate is an artefact of the read rather than of the game.

WHAT IT COUNTS, and the two are deliberately different questions:

  * `gen`     - bumped once per LED FRAME the shim decodes (hwshim.c:5394), so
                this is how often new lamp data arrives at all.
  * `decoded` - bumped once per LAMP WRITE inside those frames, so
                decoded/gen is how many lamps a frame carries.

Neither is the rate a human sees: a frame that rewrites the same values changes
nothing on screen. That is what the window's own `LED n.n Hz` measures, and
comparing the two is the point.

POLLS AT 200 Hz BY DEFAULT, well above the 30 fps the window runs at, because a
sampler that runs at the rate it is measuring cannot tell a burst from a steady
stream - which is the aliasing that made the first reading of this fault look
like a uniform 2.6 Hz when it is really bursts and 2.8 s freezes.
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import padpath

MAGIC = 0x44454C50
#: Offsets are padled.h's own, listed there next to the struct because a Python
#: reader cannot include the header. APPEND ONLY, so these stay valid.
OFF_GEN, OFF_DECODED, OFF_SKIPPED = 8, 12, 16
OFF_COIL_GEN = 2068
HEAD = 2076

#: Faster than the thing being measured, on purpose - see the docstring.
POLL_HZ = float(os.environ.get("PAD_LEDRATE_HZ", "200"))


def read(path):
    try:
        with open(path, "rb") as f:
            d = f.read(HEAD)
    except OSError:
        return None
    if len(d) < HEAD or struct.unpack_from("<I", d, 0)[0] != MAGIC:
        return None
    return struct.unpack_from("<III", d, OFF_GEN) + (
        struct.unpack_from("<I", d, OFF_COIL_GEN)[0],)


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    csv = None
    if "--csv" in sys.argv:
        csv = sys.argv[sys.argv.index("--csv") + 1]
    path = os.path.join(padpath.dump() or "", "padled")

    first = read(path)
    if first is None:
        sys.exit("ledrate: %s is not a readable padled block - is a run up?"
                 % path)
    print("reading %s at %g Hz for %g s" % (path, POLL_HZ, secs))

    t0 = time.perf_counter()
    prev, prev_t = first, t0
    events = []          # (t, d_gen, d_decoded) each time gen moved
    polls = 0
    step = 1.0 / POLL_HZ
    nxt = t0
    while True:
        now = time.perf_counter()
        if now - t0 >= secs:
            break
        if now < nxt:
            time.sleep(min(step, nxt - now))
            continue
        nxt += step
        cur = read(path)
        polls += 1
        if cur is None:
            continue
        if cur[0] != prev[0]:
            events.append((now - t0, cur[0] - prev[0], cur[1] - prev[1],
                           now - prev_t))
            prev_t = now
        prev = cur

    span = time.perf_counter() - t0
    last = read(path) or prev
    d_gen = last[0] - first[0]
    d_dec = last[1] - first[1]
    d_skip = last[2] - first[2]

    print("\n%.2f s, %d polls (%.0f Hz achieved)" % (span, polls, polls / span))
    print("  LED frames (gen)   %6d  = %6.2f Hz" % (d_gen, d_gen / span))
    print("  lamp writes        %6d  = %6.2f Hz  (%.1f per frame)"
          % (d_dec, d_dec / span, (d_dec / d_gen) if d_gen else 0.0))
    print("  undecoded frames   %6d  = %6.2f Hz" % (d_skip, d_skip / span))
    print("  coil frames        %6d" % (last[3] - first[3]))

    if events:
        gaps = sorted(e[3] for e in events)
        over = [round(e[3], 2) for e in events if e[3] > 1.0]
        print("\n  gap between LED frames: median %.3f s  max %.2f s"
              % (gaps[len(gaps) // 2], gaps[-1]))
        print("  gaps over 1 s: %s" % (over or "none"))
        # A rate is not a rhythm. Printing the spread is what stops "2.6 Hz"
        # being read as "one update every 385 ms" when it is really a stall and
        # a scramble - the fault David reported is the SHAPE, not the mean.
        burst = sum(1 for e in events if e[3] < 0.05)
        print("  frames arriving within 50 ms of the previous one: %d of %d"
              % (burst, len(events)))

    if csv:
        with open(csv, "w") as f:
            f.write("t,d_gen,d_decoded,gap_s\n")
            for e in events:
                f.write("%.4f,%d,%d,%.4f\n" % e)
        print("\n  per-event csv: %s" % csv)


if __name__ == "__main__":
    main()
