#!/usr/bin/env python3
"""swpoke.py <id> [ms] - press and release a switch through the SAME shared
memory channel the keyboard uses.

This exists to test the chain without a human at the keyboard: it writes the
script half of the switch block and bumps its generation exactly as padglhost
does its own half on a key event, so everything downstream - the shim's merge
and cache invalidation, the cabinet SPI word or the node bus 0x11 reply, the
game's own debounce - is exercised identically. If swpoke works and the keyboard
does not, the fault is in the X11 event handling and nowhere else, which is
worth a lot when something eventually goes wrong.

  swpoke.py 59 150            # a PLAYFIELD switch: a real 150 ms press
  swpoke.py --tap 25 [reads]  # a MENU button: made for exactly `reads` SPI
                              # transfers, which is deterministic where a
                              # millisecond press is not - see tap() below

IT WRITES scr_held[], NOT held[], and that is the fix for the bug where a press
from here lasted until David's next keypress instead of for the time asked. See
padsw.py / padsw.h for the three regions and the last-edge-wins merge.
"""
import struct
import sys
import time

import padsw

PATH = padsw.PATH
MAGIC = padsw.MAGIC

#: Kept as module-level names because other scripts and the handoff refer to
#: them; padsw.py is the definition.
OFF_GEN = padsw.OFF_SCR_GEN
OFF_HELD = padsw.OFF_SCR_HELD
OFF_TAP_GEN = padsw.OFF_TAP_GEN
OFF_TAP_ID = padsw.OFF_TAP_ID
OFF_TAP_READS = padsw.OFF_TAP_READS


def tap(sw, reads):
    """Press for exactly `reads` SPI transfers, not for a length of time.

    USE THIS FOR MENUS. A held cabinet switch auto-repeats, and how many times
    depends on how many transfers land inside the hold, so a wall-clock press is
    a lottery: on the Main Menu, 120 ms and 200 ms moved the cursor 0 rows,
    250 ms moved 1 or 2, and 300 ms moved 3. Counting transfers gives the same
    answer every run. The plain press below is still right for a PLAYFIELD
    switch, where a real duration is what is being modelled.

    The tap fields are their own little region and the guest only ever reads
    them, so the keyboard/script split does not touch this path at all.
    """
    m = padsw.open_block()
    if m is None:
        return 1
    struct.pack_into('<I', m, OFF_TAP_ID, sw)
    struct.pack_into('<I', m, OFF_TAP_READS, reads)
    gen = struct.unpack_from('<I', m, OFF_TAP_GEN)[0] + 1
    struct.pack_into('<I', m, OFF_TAP_GEN, gen)   # bump LAST: it arms it
    m.flush()
    print('TAP id=%d for %d transfer(s) (tap_gen=%d)' % (sw, reads, gen))
    m.close()
    return 0


def main():
    if sys.argv[1] == '--tap':
        return tap(int(sys.argv[2]),
                   int(sys.argv[3]) if len(sys.argv) > 3 else 1)
    sw = int(sys.argv[1])
    ms = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    m = padsw.open_block()
    if m is None:
        return 1
    # Own it at whatever the game currently sees, so the PRESS below is a real
    # edge even for a switch the keyboard is also holding.
    padsw.take(m, (sw,))
    for state in (1, 0):
        padsw.set_held(m, sw, state)
        print('%s id=%d (scr_gen=%d)'
              % ('PRESS  ' if state else 'RELEASE', sw,
                 struct.unpack_from('<I', m, OFF_GEN)[0]))
        if state:
            time.sleep(ms / 1000.0)
    m.close()
    return 0


sys.exit(main())
