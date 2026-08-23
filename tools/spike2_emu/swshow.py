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
import os
import sys

import gameinfo
import padsw
import trough

#: The machine-at-rest set for GODZILLA, which is what this was written
#: against: six trough balls nearest-the-eject first, the shooter lane, the
#: coin door, the trough jam opto and Start. Used only when the title's own
#: switch list cannot be read - see at_rest().
GZ_DEFAULT = (71, 70, 69, 68, 67, 66, 62, 72, 33, 36)

NAMES = {
    71: "Trough 1 (eject end)", 70: "Trough 2", 69: "Trough 3",
    68: "Trough 4", 67: "Trough 5", 66: "Trough 6 (far end)",
    62: "Shooter Lane", 72: "Trough Jam", 33: "Coin Door", 36: "Start",
    39: "Left Coin", 28: "Service Back",
}


def at_rest():
    """(ids, names, trough_ids, note) - the machine-at-rest set for the LIVE
    title, plus a WARNING string when the set is not the title's own.

    THE IDS ARE PER TITLE AND THIS TOOL IS THE CROSS-CHECK, which is exactly
    why it must not keep Godzilla's. The playfield window draws the trough
    from the title's own switch list (trough.py); printing 71..66 against
    Jaws - whose trough is 65..60 - would have the two disagreeing about
    WHICH SWITCHES they are discussing, and that disagreement reads as a
    fault in the window. Same module, same rule, one trough.

    ★ ITEM 49: THE FALLBACK IS LABELLED, NEVER SILENT - trough.py's own
    contract, which this file broke. On james_bond_60th's first run this
    tool printed a confident `6 of 6 [71..66]` under Godzilla's names while
    Bond's real trough (72..77) sat open, so every instrument agreed with
    itself and was wrong. The ids may still be printed (they are the only
    set there is), but the caller must SAY they are a guess.
    """
    game = gameinfo.active(None)
    tdir = gameinfo.table_dir(game) if game else None
    rows = (trough.load_list(os.path.join(tdir, "switch_list.txt"))
            if tdir else [])
    positions, how = trough.find(rows)
    if not positions:
        return (list(GZ_DEFAULT), dict(NAMES), [71, 70, 69, 68, 67, 66],
                "NO switch table for %s - ids and names below are the "
                "COMPILED FALLBACK (godzilla_pro's) and may be WRONG for "
                "this title" % (game or "this title"))
    names, ids = dict(NAMES), []
    for P in positions:
        ids.append(P["id"])
        end = (" (eject end)" if P["pos"] == 1 else
               " (far end)" if P is positions[-1] else "")
        names[P["id"]] = "%s%s" % (P["name"] or "Trough %d" % P["pos"], end)
    trough_ids = list(ids)
    # The rest of the at-rest set, by name where the list carries one.
    for want, label in (("SHOOTER LANE", "Shooter Lane"),
                        ("TROUGH JAM", "Trough Jam")):
        for r in rows:
            if (r.get("name") or "").upper().strip() == want:
                ids.append(r["id"])
                names[r["id"]] = label
                break
    # The coin door and Start resolve by WIRE, not by compiled id (item 73):
    # (0,23) and (1,11) are universal across every derived list, the ids are
    # table indexes (aerosmith's door is 34, batman's 36 - and batman's 36
    # being the door while godzilla's 36 is Start is exactly why the compiled
    # pair below is a fallback, not a truth).
    for node, bit, fallback, label in ((0, 23, 33, "Coin Door"),
                                       (1, 11, 36, "Start")):
        sid = next((r["id"] for r in rows
                    if r.get("node") == node and r.get("bit") == bit),
                   fallback)
        ids.append(sid)
        names.setdefault(sid, label)
    return ids, names, trough_ids, (
        None if how == "named" else
        "trough ids are ASSUMED from the node-8 bit shape, not named by "
        "this title's own table - treat them as a guess")


def main():
    args = [a for a in sys.argv[1:]]
    label = ""
    if "--label" in args:
        i = args.index("--label")
        label = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    default_ids, names, trough_ids, note = at_rest()
    ids = [int(a) for a in args] or default_ids
    if note:
        print("[swshow] !! %s" % note)

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
                 m[padsw.OFF_MRG + sw], names.get(sw, "")))
    home = [s for s in trough_ids if m[padsw.OFF_MRG + s]]
    if trough_ids and set(ids) >= set(trough_ids):
        # In trough ORDER, eject end first - the same order the playfield
        # window draws, so the two can be read against each other directly.
        print("[swshow] balls the GAME sees in the trough: %d of %d %s"
              % (len(home), len(trough_ids), home))
    m.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
