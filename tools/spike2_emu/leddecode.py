#!/usr/bin/env python3
"""leddecode.py <nblog> [t] - decode LED state off the node bus.

Turns the wire into "this named insert, at this playfield position, is at this
brightness". Position and (node, index) come from ledio.py; this decodes the
runtime writes that carry the values.

THE FRAME FAMILY. Several commands are "set N LEDs", and they are recognisable
because every one of the N leading bytes is a valid LED index for that node -
which is checkable, because ledio.py knows the exact index set from the boot
enumeration. Two shapes, both with the count implied by the length:

    body = [N indices][B][N values][C]           len(body) = 2N + 2
    body = [N indices][B][0x0f][N values][C]     len(body) = 2N + 3

`cmd 97` is the degenerate single-LED case of the second shape, always 8 bytes:
[idx][0x0f][value]. It is the one that proved the whole chain - node 9 index 44
decodes to SKILL SHOT, 29 to NY, 42 to TANK 3, 35 to GLOBE FLASH, 60 to TESLA
STRIKE, and node 8 index 4 to RIGHT OUTLANE. Those are real Godzilla Pro inserts,
so a byte on the wire resolves to a named fixture at a known position.

WHAT IS NOT DECODED, and it is deliberate. The high-volume frames on nodes 7, 12
and 14 (cmd 92, a6, 86 - hundreds of frames each, 36..64 bytes) use a different
encoding: a header, a mask that is constant across frames, and two-byte entries
whose high byte ramps with time. `popcount(mask) == len(data)` does not hold for
any header/mask split, so it is NOT the shape above and is left alone rather than
guessed at. Those boards are most likely the ws2812 strip/GI channels - the
firmware set includes ws2812node, ws2812pinnode and hdmi_ws2812node - while nodes
8 and 9 are the coil4_lednode boards driving individual inserts. That last part
is a hypothesis, not a finding.

Coverage is printed. Do not read a decoded playfield as complete.
"""
import collections
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import devicexy
import ledframes
import ledio

#: Commands whose payload starts with LED indices. Established empirically:
#: for each of these, every frame's leading byte is a valid index for its node.
INDEXED = (0x97, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xB4, 0xB5)

#: THE INSERT BOARDS, and this restriction is load-bearing. The SAME COMMAND
#: BYTE MEANS DIFFERENT THINGS ON DIFFERENT BOARD TYPES: cmd a6 on node 8 is the
#: indexed shape below, and cmd a6 on node 14 is the masked strip encoding - 1272
#: frames of it, which is most of what a first version of this decoder failed on
#: and would have mis-decoded if the shape check had been any looser. Nodes 7, 12
#: and 14 are excluded here and left to whoever cracks the strip format.
INSERT_NODES = (1, 8, 9)

#: Body layouts, as (extra, offset-of-values). All have the count implied by the
#: length: len(body) = k*N + extra.
_SHAPES = ((1, 1),      # [N idx][0x0f][N val]              len = 2N+1
           (2, 1),      # [N idx][B][N val][C]              len = 2N+2
           (3, 2))      # [N idx][B][0x0f][N val][C]        len = 2N+3


def decode_frame(b, valid):
    """[(index, value)] for one frame, or None if it is not this shape."""
    if b[2] not in INDEXED or (b[0] & 0x3F) not in INSERT_NODES:
        return None
    body = b[3:-2]
    for extra, gap in _SHAPES:
        if len(body) < extra + 2 or (len(body) - extra) % 2:
            continue
        n = (len(body) - extra) // 2
        if n < 1:
            continue
        idx = body[:n]
        if any(i not in valid for i in idx):
            continue
        vals = body[n + gap:n + gap + n]
        if len(vals) != n:
            continue
        return list(zip(idx, vals))
    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    log = sys.argv[1]
    until = float(sys.argv[2]) if len(sys.argv) > 2 else 1e9

    frames = ledframes.read(log)
    wire = ledio.wire_enumeration(log)
    d, cs = devicexy.load()
    recs = devicexy.records(d, cs)

    GROUP = {1: 5, 8: 6, 9: 7}
    info = {}
    for node, group in GROUP.items():
        for r in recs:
            if r["kind"] == "led" and r["group"] == group:
                info[(node, r["index"])] = r

    state, tried, ok = {}, 0, 0
    for t, b in frames:
        if t > until:
            break
        node = b[0] & 0x3F
        if node not in INSERT_NODES or node not in wire or b[2] not in INDEXED:
            continue
        tried += 1
        got = decode_frame(b, wire[node])
        if got is None:
            continue
        ok += 1
        for i, v in got:
            state[(node, i)] = v

    print("indexed-command frames: %d seen, %d decoded (%d%%)"
          % (tried, ok, 100 * ok // max(tried, 1)))
    named = [(k, v) for k, v in state.items() if k in info]
    print("LEDs with a value: %d, of which %d resolve to a named fixture"
          % (len(state), len(named)))
    print()
    for (node, i), v in sorted(named, key=lambda kv: -kv[1])[:25]:
        r = info[(node, i)]
        print("  node %d idx %-3d val %3d  %-32s x=%3d y=%3d %s"
              % (node, i, v, r["name"], r["x"], r["y"], r["image"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
