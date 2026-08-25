#!/usr/bin/env python3
"""lcdring.py [block] - print the VILLAIN VISION command ring.

Item 83. The shim rings the last 64 cmd-f2 frames the lcdnode was sent -
EVERY selector, decoded or not - and watch.sh preserves the page at run end
as dump/padlcd.last. This prints it: one line per frame, newest last, with
the decode beside the raw bytes so a wrong decode is visible next to the
evidence against it.

    lcdring.py                  # dump/padlcd.last, or the live block
    lcdring.py dump/padlcd      # a running game's block, right now

WHY THIS EXISTS. Two mis-decodes of this protocol shipped (three displays,
then an invented "range"), and both survived live captures because nothing
could show what the wire actually carried. The panel shows the CURRENT
state; this shows the sequence, which is the only thing that can answer
"why did that clip play then" or "did the game ever ask for asset N".

padlcd.h owns the frame table and the offsets; this file must follow it.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import padpath

MAGIC = 0x44434C50
HDR = 60                    # magic..ms, then ring_head at 56, ring at 60
RING = 64
RAW = 22
#: Ring entry stride per block version. v4 coalesces identical consecutive
#: frames (ms, last, rep u16, sel, len, payload, pad to 36); v3 - still met
#: in preserved padlcd.last files - was one slot per frame (ms, sel, len,
#: payload). The header layout is identical in both.
STRIDE = {3: 4 + 1 + 1 + RAW, 4: 4 + 4 + 2 + 1 + 1 + RAW + 2}

#: Frame periods at 0x5c9340, in 1/1280 s. A rate byte carries the PERIOD,
#: not an fps, which is why 106 (= 12 fps) can never be an asset id.
FPS = {43: 30, 53: 24, 64: 20, 80: 16, 84: 15, 106: 12, 128: 10, 160: 8}


def le32(b, i):
    return b[i] | (b[i + 1] << 8) | (b[i + 2] << 16) | (b[i + 3] << 24)


def decode(sel, b, n):
    """One frame's meaning, or an honest '?'.

    `b` is the payload AFTER the selector, so the game's payload offset 1
    (the asset) is b[1]. Lengths are the wire's ilen minus 3.
    """
    if (sel & 0xF8) == 0x98:
        if n == 1:
            v = {1: "play loop", 2: "play once"}.get(b[0])
            return "verb %d%s" % (b[0], " (%s)" % v if v else " (unnamed)")
        if n == 5:
            return "asset %d" % le32(b, 1)
        if n in (11, 21):
            per = b[9] | (b[10] << 8)
            out = "asset %d  aux %d  rate %s" % (
                le32(b, 1), le32(b, 5),
                "%d fps" % FPS[per] if per in FPS else "?%d" % per)
            if n == 21:
                out += "  x %d/%d/%d" % (le32(b, 11), le32(b, 15),
                                         b[19] | (b[20] << 8))
            return out + "  flags %d" % b[0]
        return "? play family, %d payload bytes" % n
    if (sel & 0xF8) == 0x80:
        return "brightness %d fade %d" % (b[0], b[1]) if n >= 2 else "?"
    if sel == 0x90:
        return "status poll (wants a 12-byte reply; we answer zeros)"
    return "? selector"


def main():
    if len(sys.argv) > 2:
        raise SystemExit("usage: lcdring.py [block]")
    if len(sys.argv) == 2:
        path = sys.argv[1]
    else:
        # LIVE FIRST, then the preserved copy. The first cut preferred
        # padlcd.last, which mid-game shadows the running title's block
        # with the PREVIOUS run's transcript - plausible output, wrong
        # run, the exact class of quiet error this tool exists to end.
        dump = padpath.dump() or ""
        live = os.path.join(dump, "padlcd")
        kept = os.path.join(dump, "padlcd.last")
        path = live if os.path.isfile(live) else kept
        if not os.path.isfile(path):
            # Its debut ended here - "[Errno 2] ... padlcd" with no hint of
            # why. Both absences have a plain meaning; say them.
            raise SystemExit(
                "lcdring.py: nothing to read in %s\n"
                "  padlcd       - absent: no run is live right now\n"
                "  padlcd.last  - absent: no lcdnode run has ENDED since the\n"
                "                 preserve landed (Stop used to delete the\n"
                "                 block; killgame.sh keeps it now)\n"
                "Run the title, and read the ring live or after it ends."
                % (dump or "."))
    try:
        with open(path, "rb") as f:
            d = f.read(4096)
    except OSError as e:
        raise SystemExit("lcdring.py: %s" % e)
    if len(d) < HDR or struct.unpack_from("<I", d)[0] != MAGIC:
        raise SystemExit("lcdring.py: %s carries no PLCD block "
                         "(no lcdnode title has run, or the run predates "
                         "the ring)" % path)

    (_m, ver, gen, dec, asset, aux, rate, verb,
     x1, x2, x3, bright, fade, ms) = struct.unpack_from("<14I", d)
    head = struct.unpack_from("<I", d, 56)[0]
    print("%s  version %d  gen %d  decoded %d  ring slots %d"
          % (path, ver, gen, dec, head))
    print("last state: asset %d  aux %d  rate %d  verb %d  x %d/%d/%d  "
          "bright %d  fade %d  at %d ms"
          % (asset, aux, rate, verb, x1, x2, x3, bright, fade, ms))
    if ver not in STRIDE:
        raise SystemExit("lcdring.py: block version %d has no known ring "
                         "layout (this reader knows %s) - the shim moved on;"
                         " update this file from padlcd.h"
                         % (ver, sorted(STRIDE)))
    if not head:
        print("(ring empty - the node was never sent a cmd-f2 frame)")
        return 0

    # Oldest first, so the sequence reads downward like a transcript. A ring
    # that has not wrapped has entries only in slots 0..head-1.
    stride = STRIDE[ver]
    n = min(head, RING)
    start = head - n
    print()
    # The GAP gets its own column. Squeezing it into the timestamp made the
    # rows ragged the moment one appeared, and the gap is the whole point of
    # the transcript - a command re-sent every 250 ms reads very differently
    # from one sent once.
    print("%10s %7s  %-3s  %-44s %s"
          % ("ms", "gap", "sel", "decode", "raw"))
    prev = None
    for k in range(n):
        slot = (start + k) % RING
        off = HDR + slot * stride
        if off + stride > len(d):
            break
        if ver >= 4:
            fms, last, rep, sel, ln = struct.unpack_from("<IIHBB", d, off)
            b = d[off + 12:off + 12 + min(ln, RAW)]
        else:
            fms, sel, ln = struct.unpack_from("<IBB", d, off)
            last, rep = fms, 1
            b = d[off + 6:off + 6 + min(ln, RAW)]
        ln = min(ln, RAW)
        what = decode(sel, b, ln)
        if rep > 1:
            # A coalesced slot IS a measurement: 421 polls over 7 s names
            # the cadence without eating 421 lines. Saturated counts say so
            # rather than pose as exact.
            what += "  x%s over %d ms" % \
                ("65535+" if rep == 0xFFFF else rep, last - fms)
        gap = "" if prev is None else "+%d" % (fms - prev)
        prev = last
        print("%10d %7s  %-3s  %-44s %s"
              % (fms, gap, "%02x" % sel, what,
                 " ".join("%02x" % c for c in b)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
