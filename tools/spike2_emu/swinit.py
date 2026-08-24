#!/usr/bin/env python3
"""swinit.py - create the switch shared-memory file WITHOUT padglhost.

Normally padglhost creates /dump/padsw and publishes held[] when its window
opens. A measurement run (runbridge.sh / nbrun.sh) has no window, so there is no
keyboard - but the shim will read the file if PAD_SW_SHM is exported to the
guest, whoever wrote it. This writes a valid header plus the machine-at-rest set
(coin door shut, six balls in the trough) so a headless run can still be driven
with swpoke.py / swhold.py.

Run it BEFORE the guest starts.

It writes the SCRIPT half of the block and leaves the keyboard half at zero,
which is the honest description of a run with no keyboard in it. padglhost, if
one ever does open a window over this file, no longer wipes what it finds: it
checks the magic and clears only its own region.

THE IDS ARE PER TITLE (item 73). The compiled set below is GODZILLA's - its
door is 33 and its trough 66..71, but an id is the title's own table index
(aerosmith's door is 34, munsters' 198, jaws's trough 60..65). So this
resolves from the title's derived switch list the same way the shim's own
sw_rest_resolve does: the door by WIRE (node 0 bit 23 is universal across
every list on this disk), the trough by NAME (TROUGH 1..6). No list, or no
resolvable rows, keeps the compiled set - labelled, never silent (item 49's
rule).
"""
import struct

import gameinfo
import padsw
import trough

padsw.set_source('i')   # who the [sw] log says moved a switch;
                        # PAD_SW_SRC overrides. See padsw.h.

REST = [33, 66, 67, 68, 69, 70, 71]     # godzilla's: door + TROUGH 1..6


def resolve():
    """The per-title rest set, or godzilla's with a warning string."""
    try:
        rows = trough.load_list(gameinfo.table("switch_list.txt"))
    except Exception:
        rows = []
    if not rows:
        return list(REST), "no switch list - GODZILLA'S ids, may be WRONG"
    door = next((r["id"] for r in rows
                 if r.get("node") == 0 and r.get("bit") == 23), REST[0])
    positions, how = trough.find(rows)
    if positions:
        return [door] + [p["id"] for p in positions], None if how == "named" \
            else "trough ids assumed from the node-8 bit shape"
    return [door] + REST[1:], "no trough rows resolved - godzilla's trough ids"


rest, warn = resolve()
buf = bytearray(4096)
struct.pack_into('<I', buf, padsw.OFF_MAGIC, padsw.MAGIC)
struct.pack_into('<I', buf, padsw.OFF_SCR_GEN, 1)
for i in rest:
    buf[padsw.OFF_SCR_HELD + i] = 1
open(padsw.PATH, 'wb').write(bytes(buf))
print('wrote %s  magic ok, scr_gen=1, held: %s%s'
      % (padsw.PATH, rest, '  (%s)' % warn if warn else ''))
