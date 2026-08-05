#!/usr/bin/env python3
"""swhold.py <id> <0|1> - LATCH a switch on or off in the shared-memory channel.

swpoke.py pulses (press then release). Some switches are latching state, not
events: the coin door (33) and the six trough balls (66..71) are held for
minutes, and padglhost models them as toggles. This sets one and leaves it set.

A LATCH SET HERE NOW SURVIVES A KEYPRESS. It used to not: padglhost rebuilds its
own array on any key event, both scripts and keyboard wrote the same array, and
so `swhold.py 33 1` lasted until David next touched the keyboard. The two now
have an array each and the guest merges them by last edge wins - see padsw.py.

Because the merge needs an EDGE, this takes ownership at the current merged
value first (padsw.take). Without that, latching 33 to the value the keyboard
already holds would write a byte and change nothing.
"""
import sys

import padsw

sw = int(sys.argv[1])
val = int(sys.argv[2])
m = padsw.open_block()
if m is None:
    sys.exit(1)
padsw.take(m, (sw,))
print('id=%d was %d -> %d' % (sw, padsw.merged(m, sw), val))
padsw.set_held(m, sw, val)
m.close()
