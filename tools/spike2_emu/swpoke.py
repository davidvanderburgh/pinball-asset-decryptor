#!/usr/bin/env python3
"""swpoke.py <id> [ms] - press and release a switch through the SAME shared
memory channel the keyboard uses.

This exists to test the chain without a human at the keyboard: it writes
held[id] and bumps gen exactly as padglhost does on a key event, so everything
downstream - the shim's cache invalidation, the cabinet SPI word or the node bus
0x11 reply, the game's own debounce - is exercised identically. If swpoke works
and the keyboard does not, the fault is in the X11 event handling and nowhere
else, which is worth a lot when something eventually goes wrong.

  wsl -e bash -c 'python3 /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/swpoke.py 27 400'
"""
import mmap
import struct
import sys
import time

PATH = '/home/david/spike2root/dump/padsw'
MAGIC = 0x53444150


def main():
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
