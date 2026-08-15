#!/usr/bin/env python3
"""swspin.py <id> <0|1> - RIP a switch (item 26): spin a spinner while held.

swhold.py latches a LEVEL; this one cannot be a level, because the game counts
spins by DIFFING successive 0x11 scans of the switch's own node - a switch held
made is exactly ONE closure however long it stays made. And no pulse loop on
this side can beat the scan either: each host action is a ~80 ms wsl.exe spawn
(item 24, measured), so pulsing tops out near 6 closures/s while saturating
SwitchDriver's queue.

So this sets ONE flag and the guest shim does the ripping: it ALTERNATES the
level it reports on each scan of that node for as long as the flag is set - a
closure per two scans, the maximum rate a diffed level can carry, whatever the
game's scan rate turns out to be. One interop call on press, one on release,
exactly like swhold.py.

NO take() AND NO scr_held[], deliberately. The rip has its own single-writer
region (spin_gen/spin[] - padsw.h) and never touches the merge, so clearing the
flag leaves the switch OPEN by construction; a rip cannot strand a switch
closed the way a lost release could. The shim's `[swspin] rip END` line states
the closures actually delivered and the node's own scan rate - the game-side
number, not this side's intent.
"""
import sys

import padsw

sw = int(sys.argv[1])
val = int(sys.argv[2])
m = padsw.open_block()
if m is None:
    sys.exit(1)
print('id=%d spin was %d -> %d' % (sw, padsw.spinning(m, sw), val))
padsw.set_spin(m, sw, val)
m.close()
