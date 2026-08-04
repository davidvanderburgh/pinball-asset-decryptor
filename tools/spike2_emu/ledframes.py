#!/usr/bin/env python3
"""ledframes.py <log> [node] [cmd] - the LED frames on the node bus, decomposed.

Run the game with PAD_NB_LOG raised (400000; the default 400-line budget hides
almost all of this) and PAD_LOG_TIME=1, then point this at the log.

  ledframes.py ~/gzwatch.log              # census: every (node, command)
  ledframes.py ~/gzwatch.log 14 92        # one command, byte by byte

WHAT IT IS FOR. The LED output map is the last big unknown in this rig, and the
frames carrying it are not reachable statically: co2.py finds no sender for any
of them, because it recognises the per-command pattern (command byte stored as
an immediate) and these are sent by a generic function that takes the command
from data. So the way in is the wire.

WHAT THE CENSUS ALREADY ESTABLISHED, so nobody re-derives it:

  * Frames are capped at 64 bytes TOTAL and a long update is split, so a run of
    lengths like 39..62 on one command is chunking, not different messages.
  * The high-volume LED traffic is node 14 cmd 92 and cmd a6, node 7 cmd 86.
  * They arrive in PAIRS at one timestamp, ~33 ms apart from the next pair, i.e.
    a ~30 Hz refresh. The two frames of a pair differ in the first header byte
    (0x24 vs 0x44), so that byte selects a bank.
  * Layout, for node 14 cmd 92: 3 header bytes (`24 8f 0b` / `44 8f 0a`), then a
    mask that is CONSTANT across frames (`db b6 6d` repeated - read LSB-first
    that is `110` eight times per three bytes, so 3 bits per entry, 32 entries
    in 12 bytes), then two-byte entries, about 23 of them.
  * The two-byte entries are NOT plain brightness. Read big-endian they run
    0x038c, 0x0798, 0x0ba5, 0x10b1 on successive frames - past the 4095 a 12-bit
    PWM channel could hold. The HIGH byte ramps steadily with time (+4 or 5 per
    33 ms frame) while the LOW byte oscillates smoothly, so it is more likely a
    (ramp, value) or (time, target) fade instruction than a level.

WHAT IS STILL MISSING is the channel mapping, and guessing it from these numbers
is exactly the trap this project keeps falling into. The oracle is the game's own
**LED Tests** screen, which lights fixtures one at a time BY NAME: light one,
diff the frames, and the byte that moved is that fixture. led_names.txt has the
241 fixtures to match against.
"""
import collections
import re
import sys

FRAME = re.compile(r"TX len=\d+ ([0-9a-f]+)")
STAMP = re.compile(r"^\[([0-9.]+)\]")


def read(path):
    """[(t, frame_bytes)] for every addressed frame in the log."""
    out = []
    for line in open(path, "rb"):
        line = line.decode("latin-1")
        m = FRAME.search(line)
        if not m:
            continue
        h = m.group(1)
        if len(h) < 6 or len(h) % 2:
            continue
        b = bytes.fromhex(h)
        if not (b[0] & 0x80):          # unaddressed housekeeping, not a board
            continue
        s = STAMP.match(line)
        out.append((float(s.group(1)) if s else 0.0, b))
    return out


def census(frames):
    c = collections.Counter()
    lens = collections.defaultdict(set)
    for _, b in frames:
        key = (b[0] & 0x3F, b[2])
        c[key] += 1
        lens[key].add(len(b))
    for (node, cmd), n in sorted(c.items()):
        sizes = sorted(lens[(node, cmd)])
        span = "%d" % sizes[0] if len(sizes) == 1 else "%d..%d" % (sizes[0], sizes[-1])
        print("node %2d  cmd %02x  %6d frames  %s bytes%s"
              % (node, cmd, n, span, "  <- chunked" if len(sizes) > 3 else ""))


def detail(frames, node, cmd):
    fs = [(t, b) for t, b in frames if (b[0] & 0x3F) == node and b[2] == cmd]
    if not fs:
        print("no frames for node %d cmd %02x" % (node, cmd))
        return
    print("node %d cmd %02x: %d frames" % (node, cmd, len(fs)))

    # Which byte positions are header (few values) and which are payload (many)?
    longest = max(len(b) for _, b in fs)
    print("\nper-position distinct values (header settles low, data goes to 256):")
    for pos in range(3, min(longest, 24)):
        vals = {b[pos] for _, b in fs if len(b) > pos}
        print("   byte %2d: %3d distinct  %s"
              % (pos, len(vals), " ".join("%02x" % v for v in sorted(vals)[:10])))

    print("\nfirst frames in time order, with the gap to the previous one:")
    prev = None
    for t, b in fs[:8]:
        gap = "" if prev is None else "  (+%.0f ms)" % ((t - prev) * 1000)
        prev = t
        print("   %8.3f%s  hdr=%s  rest=%s"
              % (t, gap, b[3:6].hex(), b[6:].hex()))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    frames = read(sys.argv[1])
    print("%d addressed frames\n" % len(frames))
    if len(sys.argv) >= 4:
        detail(frames, int(sys.argv[2]), int(sys.argv[3], 16))
    else:
        census(frames)
    return 0


if __name__ == "__main__":
    sys.exit(main())
