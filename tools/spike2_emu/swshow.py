#!/usr/bin/env python3
"""swshow.py [ids...] - print all THREE regions of the switch block side by side.

    python3 swshow.py                 # the trough, the shooter lane and the door
    python3 swshow.py 71 70 36        # whichever ids you name
    python3 swshow.py --label "after plunge"

WHY THIS EXISTS AND WHY IT PRINTS THREE COLUMNS RATHER THAN ONE. Every other
helper reads `mrg[]`, which is the right answer to "what does the game see" and
the wrong one for "why does it see that". The block has three regions with one
writer each (padsw.h), and a fault in the merge looks IDENTICAL from mrg[] alone
whichever half caused it:

    kbd=1 scr=0 mrg=1   the keyboard still holds it - nothing is wrong
    kbd=1 scr=0 mrg=1   ...and also what a DROPPED SCRIPT EDGE looks like, when
                        a script wrote 1 and then 0 between two of the shim's
                        merges and neither was ever observed.

The two are told apart by the generations, which is why they are printed too:
scr_gen counts what the scripts have PUBLISHED and mrg_gen counts what the shim
has ADOPTED, so a scr_gen that has moved with mrg_gen standing still is the
shim never having seen it. That pair is the whole diagnosis for item 20.

Reads only. It never writes the block, so it is safe to run against a live game
and against a run somebody else started.
"""
import sys

import padsw

#: The machine-at-rest set, which is what this is nearly always pointed at:
#: six trough balls nearest-the-eject first, the shooter lane, the coin door,
#: the trough jam opto and Start.
DEFAULT = (71, 70, 69, 68, 67, 66, 62, 72, 33, 36)

NAMES = {
    71: "Trough 1 (eject end)", 70: "Trough 2", 69: "Trough 3",
    68: "Trough 4", 67: "Trough 5", 66: "Trough 6 (far end)",
    62: "Shooter Lane", 72: "Trough Jam", 33: "Coin Door", 36: "Start",
    39: "Left Coin", 28: "Service Back",
}


def main():
    args = [a for a in sys.argv[1:]]
    label = ""
    if "--label" in args:
        i = args.index("--label")
        label = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    ids = [int(a) for a in args] or list(DEFAULT)

    m = padsw.open_block()
    if m is None:
        return 1
    import struct
    kg = struct.unpack_from("<I", m, padsw.OFF_GEN)[0]
    sg = struct.unpack_from("<I", m, padsw.OFF_SCR_GEN)[0]
    mg = struct.unpack_from("<I", m, padsw.OFF_MRG_GEN)[0]
    gms = padsw.guest_ms(m)

    print("[swshow] %sguest %s ms  gen kbd=%u scr=%u mrg=%u"
          % (label + " " if label else "", gms if gms is not None else "-",
             kg, sg, mg))
    print("[swshow]  id  kbd  scr  mrg  name")
    for sw in ids:
        print("[swshow] %3d %4d %4d %4d  %s"
              % (sw, m[padsw.OFF_HELD + sw], m[padsw.OFF_SCR_HELD + sw],
                 m[padsw.OFF_MRG + sw], NAMES.get(sw, "")))
    trough = [s for s in (71, 70, 69, 68, 67, 66) if m[padsw.OFF_MRG + s]]
    if set(ids) >= {71, 66}:
        print("[swshow] balls the GAME sees in the trough: %d %s"
              % (len(trough), trough))
    m.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
