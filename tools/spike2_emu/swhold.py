#!/usr/bin/env python3
"""swhold.py <id> <0|1> - LATCH a switch on or off in the shared-memory channel.

swpoke.py pulses (press then release). Some switches are latching state, not
events: the coin door (33) and the six trough balls (66..71) are held for
minutes, and padglhost models them as toggles. This sets one and leaves it set.

Note padglhost REBUILDS held[] from its own key state on any key event, so a
latch written here survives only until the next keypress in the window.
"""
import mmap
import struct
import sys

PATH = '/home/david/spike2root/dump/padsw'
MAGIC = 0x53444150

sw = int(sys.argv[1])
val = int(sys.argv[2])
with open(PATH, 'r+b') as f:
    m = mmap.mmap(f.fileno(), 4096)
    magic, gen = struct.unpack_from('<II', m, 0)
    if magic != MAGIC:
        print('bad magic 0x%08x - is the emulator running?' % magic)
        sys.exit(1)
    print('id=%d was %d -> %d (gen %d)' % (sw, m[8 + sw], val, gen + 1))
    m[8 + sw] = val
    struct.pack_into('<I', m, 4, gen + 1)
    m.flush()
    m.close()
