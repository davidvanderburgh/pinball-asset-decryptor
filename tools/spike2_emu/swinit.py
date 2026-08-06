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
"""
import struct

import padsw

padsw.set_source('i')   # who the [sw] log says moved a switch;
                        # PAD_SW_SRC overrides. See padsw.h.

REST = [33, 66, 67, 68, 69, 70, 71]

buf = bytearray(4096)
struct.pack_into('<I', buf, padsw.OFF_MAGIC, padsw.MAGIC)
struct.pack_into('<I', buf, padsw.OFF_SCR_GEN, 1)
for i in REST:
    buf[padsw.OFF_SCR_HELD + i] = 1
open(padsw.PATH, 'wb').write(bytes(buf))
print('wrote %s  magic ok, scr_gen=1, held: %s' % (padsw.PATH, REST))
