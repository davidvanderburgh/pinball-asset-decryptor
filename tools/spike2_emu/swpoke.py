#!/usr/bin/env python3
"""swpoke.py <id> [ms] - press and release a switch through the SAME shared
memory channel the keyboard uses.

This exists to test the chain without a human at the keyboard: it writes
held[id] and bumps gen exactly as padglhost does on a key event, so everything
downstream - the shim's cache invalidation, the cabinet SPI word or the node bus
0x11 reply, the game's own debounce - is exercised identically. If swpoke works
and the keyboard does not, the fault is in the X11 event handling and nowhere
else, which is worth a lot when something eventually goes wrong.

  swpoke.py 59 150            # a PLAYFIELD switch: a real 150 ms press
  swpoke.py --tap 25 [reads]  # a MENU button: made for exactly `reads` SPI
                              # transfers, which is deterministic where a
                              # millisecond press is not - see tap() below
"""
import mmap
import struct
import sys
import time

PATH = '/home/david/spike2root/dump/padsw'
MAGIC = 0x53444150


#: Field offsets, which must match struct padsw_shm in padsw.h.
OFF_GEN = 4
OFF_HELD = 8
OFF_TAP_GEN = OFF_HELD + 256
OFF_TAP_ID = OFF_TAP_GEN + 4
OFF_TAP_READS = OFF_TAP_ID + 4


def tap(sw, reads):
    """Press for exactly `reads` SPI transfers, not for a length of time.

    USE THIS FOR MENUS. A held cabinet switch auto-repeats, and how many times
    depends on how many transfers land inside the hold, so a wall-clock press is
    a lottery: on the Main Menu, 120 ms and 200 ms moved the cursor 0 rows,
    250 ms moved 1 or 2, and 300 ms moved 3. Counting transfers gives the same
    answer every run. The plain press below is still right for a PLAYFIELD
    switch, where a real duration is what is being modelled.
    """
    with open(PATH, 'r+b') as f:
        m = mmap.mmap(f.fileno(), 4096)
        magic = struct.unpack_from('<I', m, 0)[0]
        if magic != MAGIC:
            print('bad magic 0x%08x - is the emulator running?' % magic)
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
    with open(PATH, 'r+b') as f:
        m = mmap.mmap(f.fileno(), 4096)
        magic, gen = struct.unpack_from('<II', m, 0)
        if magic != MAGIC:
            print('bad magic 0x%08x - is the emulator running?' % magic)
            return 1
        for state in (1, 0):
            m[8 + sw] = state
            gen += 1
            struct.pack_into('<I', m, 4, gen)
            m.flush()
            print('%s id=%d (gen=%d)' % ('PRESS  ' if state else 'RELEASE', sw, gen))
            if state:
                time.sleep(ms / 1000.0)
        m.close()
    return 0


sys.exit(main())
