#!/usr/bin/env python3
"""vidroute.py - WHICH CLIP DID EACH VIDEO CHANNEL ACTUALLY GET? (item 15)

    python3 vidroute.py /home/david/padvid.log [split_seconds]

Reads padvidhost's own log and answers the one question item 15 turns on: is
the game being served DISTINCT clips, or is a channel nailed to a single file
while the game keeps asking for others?

WHY A COUNT AND NOT A PICTURE. "Every video element plays the same footage" is
a thing you see, and this rig has been burned repeatedly by metrics that score
the CONTENT instead of the DEFECT. This one does not look at pixels at all: it
counts how many DIFFERENT files each channel was asked to open, and when each
channel last CHANGED file. A channel that serves one clip sixty-one times over
three minutes is the fault, stated as a number, whatever the screen looks like.

VALIDATED ON A LABELLED EXAMPLE FIRST, which is the rule here. Run against the
2026-08-06 gameplay log that David reported the fault from, it says:

    ch0: 75 requests, 4 distinct clips, last CHANGE of clip at 127.7
         (182.2 s of the run after that)
           2.asset/383.asset  x61   127.7 .. 309.9

and the second pipeline was created at ~134.8 s - so ch0 stopped receiving
filenames seven seconds BEFORE the pipeline that stole them existed, which is
the whole bug in two lines. The `split` argument prints the same breakdown for
everything after a given timestamp, which is how that boundary was found.
"""
import re
import sys
from collections import OrderedDict

LINE = re.compile(
    r"\[padvid\s+([\d.]+)\]\s+ch(\d+) serving (\d+)x(\d+) (\d+) frames (\S+)")


def short(p):
    """The clip, without the 40-hex-digit scene hash nobody can read."""
    i = p.find("scene.assets/")
    return p[i + len("scene.assets/"):] if i >= 0 else p


def main(path, split=None):
    rows = []
    for ln in open(path, encoding="utf-8", errors="replace"):
        m = LINE.search(ln)
        if m:
            rows.append((float(m.group(1)), int(m.group(2)), int(m.group(5)),
                         short(m.group(6))))
    if not rows:
        print("no 'serving' lines in %s" % path)
        return 1
    print("%d serve requests, t=%.1f..%.1f s" % (len(rows), rows[0][0], rows[-1][0]))

    chans = OrderedDict()
    for t, ch, n, p in rows:
        chans.setdefault(ch, []).append((t, p, n))

    print("\n--- per channel ---")
    for ch in sorted(chans):
        ev = chans[ch]
        paths = OrderedDict()
        for t, p, n in ev:
            paths.setdefault(p, [0, t, t])
            paths[p][0] += 1
            paths[p][2] = t
        last_change, prev = ev[0][0], None
        for t, p, n in ev:
            if p != prev:
                last_change, prev = t, p
        print("ch%d: %d requests, %d distinct clips, first %.1f last %.1f, "
              "last CHANGE of clip at %.1f (%.1f s of the run after that)"
              % (ch, len(ev), len(paths), ev[0][0], ev[-1][0], last_change,
                 rows[-1][0] - last_change))
        for p, (n, t0, t1) in paths.items():
            print("       %-28s x%-4d  %.1f .. %.1f" % (p, n, t0, t1))

    if split is not None:
        print("\n--- after t=%.1f ---" % split)
        for ch in sorted(chans):
            after = [e for e in chans[ch] if e[0] >= split]
            if not after:
                print("ch%d: nothing" % ch)
                continue
            distinct = OrderedDict((p, 0) for _, p, _ in after)
            for _, p, _ in after:
                distinct[p] += 1
            print("ch%d: %d requests, %d distinct: %s"
                  % (ch, len(after), len(distinct),
                     ", ".join("%s x%d" % (p, n) for p, n in distinct.items())))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1],
                  float(sys.argv[2]) if len(sys.argv) > 2 else None))
