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

THE OTHER DIALECT lives in wide_decode() at the bottom of this file, and it is
a different generation's, not a different shape of this one. The titles this
rig calls swelf-generation (batman and its siblings) drive every lamp through
one builder whose COMMAND BYTE IS A BITFIELD describing the body - so there is
one grammar there rather than a family of shapes, it needs no node restriction,
and it decodes the boards this decoder is forbidden to touch. Neither function
should ever be pointed at the other's frames: they disagree about what the same
bytes mean, which is the whole reason they are separate.

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


# ---- THE SWELF GENERATION (batman) --------------------------------------
#
# The Python twin of hwshim.c's led_wide_walk, and it must stay a twin: same
# grammar, same exact-close refusal, same "no level byte means no level".
# hwshim.c's header carries the reverse-engineering - the single builder at
# 0x51896c, the command byte assembled as a bitfield at 0x518ac4, and the block
# order read off 0x518ad4/0x518bb0 - and this file does not repeat it.
#
# The one thing worth restating here, because it is what makes both sides safe:
# the index-bitmap length is NOT on the wire. It is ASSUMED to be the span the
# group nibbles describe, and every frame then has to consume its body EXACTLY
# or it is refused. A mis-parse fails that test by itself, which is why this
# needs no node gate where decode_frame above cannot live without one.

def wide_decode(b):
    """Decode one swelf-generation lamp frame.

    Returns (indices, levels) - one channel-A level per addressed LED - or
    None when this grammar does not fit the frame.

    THE COMMAND BYTE IS THE GRAMMAR:

        A = cmd & 0x03   how the LEVEL is carried
        B = cmd & 0x1c   how channel B is carried (walked, then dropped)
        M = cmd & 0x20   index LIST rather than a single index (short body)

    ★ A == 0 AND A == 1 CARRY A LEVEL WITHOUT SPENDING A BYTE ON IT, which is
    the one thing here that cannot be guessed from a capture and is decisive
    for how much of the show renders. At 0x51667c the planner reads the shared
    level and branches on its VALUE: 0x00 takes 0x5169f8 and stores mode 0,
    0xff takes 0x5169f4 and stores mode 1, anything else keeps mode 3 and sends
    the byte. So all-off and all-on - much the commonest two states in a light
    show - are compressed into the command byte itself. Reading modes 0 and 1
    as "this frame says nothing about brightness" costs every lamp the game
    turns fully ON with one, and that is most of batman's node 8.
    """
    if len(b) < 6 or not b[0] & 0x80:
        return None
    cmd, body = b[2], b[3:-2]
    if not cmd & 0x80 or not body:
        return None
    A, B, M = cmd & 0x03, cmd & 0x1C, cmd & 0x20
    #: Path B of the builder (0x518b78) prefixes a BANK byte and addresses
    #: lamp `bank * 96 + index`, which does not fit a [16][96] plane at all.
    #: Its commands are exactly the ones with B == 0x10; refusing them is what
    #: keeps this from writing a bank-4 lamp over a bank-0 one.
    if B == 0x10:
        return None
    idxs, p, sel = [], 0, None

    if body[0] & 0x80:                      # the index-BITMAP body (0x518bb0)
        if len(body) < 2 or M:
            #: M here means a further flags byte at body[2] whose bit base is
            #: not established. Refused rather than skipped past.
            return None
        first_g, last_g = body[1] >> 4, body[1] & 0x0F
        if last_g < first_g or last_g > 11:
            return None
        span = last_g - first_g + 1
        #: ★ THE BITMAP IS SPARSE. body[0]'s low bits say which of the MIDDLE
        #: bytes were actually transmitted, and bit 6 is what the omitted ones
        #: are: all-set or all-clear. A run of identical bytes therefore costs
        #: nothing, which is exactly how a 45-lamp frame fits in 59 bytes. The
        #: first and last bytes of the window are always sent.
        fill, flags = 0xFF if body[0] & 0x40 else 0x00, body[0] & 0x3F
        if span > 8:
            return None                     # would need more than 6 flag bits
        blk = 1 if span == 1 else 2 + bin(flags).count("1")
        if 2 + blk > len(body):
            return None
        win, t = [], 0
        for j in range(span):
            if j == 0 or j == span - 1 or flags >> (j - 1) & 1:
                win.append(body[2 + t])
                t += 1
            else:
                win.append(fill)
        if t != blk:
            return None
        p = 2 + blk
        for j in range(span):
            for k in range(8):
                if win[j] >> k & 1:
                    e = (first_g + j) * 8 + k
                    if e >= 96:
                        return None
                    idxs.append(e)
        if not idxs:
            return None
        #: The window must really be the span it claims, or the nibbles and the
        #: bitmap disagree and one of them was misread.
        if idxs[0] >> 3 != first_g or idxs[-1] >> 3 != last_g:
            return None
    elif M:                                 # [first][middles...][last|0x80]
        while True:
            if p >= len(body) or len(idxs) >= 96:
                return None
            idxs.append(body[p] & 0x7F)
            p += 1
            if body[p - 1] & 0x80:
                break
        if len(idxs) < 2:
            return None
    else:                                   # a single index, no terminator
        if body[0] > 95:
            return None
        idxs.append(body[0])
        p = 1
    if any(idxs[i] <= idxs[i - 1] for i in range(1, len(idxs))):
        return None                         # the planner splits, never reorders

    cnt = len(idxs)
    if B & 0x08:                            # channel-B selector bitmap
        sl = (cnt + 7) // 8
        if p + sl > len(body):
            return None
        sel = body[p:p + sl]
        for k in range(cnt, sl * 8):        # padding bits must be clear
            if sel[k >> 3] >> (k & 7) & 1:
                return None
        p += sl

    if A == 0:                              # 0x51667c: the shared level was 0
        vals = [0x00] * cnt
    elif A == 1:                            # ...or 0xff
        vals = [0xFF] * cnt
    elif A == 2:                            # one byte each (0x518c1c)
        if p + cnt > len(body):
            return None
        vals = list(body[p:p + cnt])
        p += cnt
    else:                                   # one byte shared (0x518af4)
        if p + 1 > len(body):
            return None
        vals = [body[p]] * cnt
        p += 1

    # Channel B is walked for its LENGTH and then dropped - see the header.
    if B == 0:
        p += cnt
    else:
        if B & 0x10:
            p += 1
        if B & 0x0C == 0x08:
            p += 1
        elif B & 0x0C == 0x0C:
            if sel is None:
                return None
            p += sum(sel[k >> 3] >> (k & 7) & 1 for k in range(cnt))
    if p != len(body):
        return None
    return idxs, vals


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
