"""coilread.py - print every nonzero coil fire counter from the padled block.

One line per addressed coil: `node index count lvl`. Diffing two invocations
around a Coil Test fire names the (node, index) the highlighted row drives.
The offsets and the magic are coilmap.py's, which is now the one place they
live - this file, playfield.py and ledrate.py each used to carry a copy.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coilmap
import gameinfo
import padpath

#: Runs on WINDOWS, so this is the rootfs seen over `\\wsl.localhost`. Asked of
#: padpath rather than written out: the literal named a distro ("Ubuntu") and a
#: user that need not exist, under a prefix older WSL spells `\\wsl$`.
PATH = os.path.join(padpath.dump(), "padled")

d = open(PATH, "rb").read(coilmap.PADLED_READ)
if not coilmap.has_magic(d):
    print("NO MAGIC - emulator not up")
    sys.exit(2)
print("coil_gen=%d coil_decoded=%d"
      % struct.unpack_from("<II", d, coilmap.GEN_OFF))
#: Named where the table allows it. A title with no device table (star_wars_le
#: has none) still prints every counter, just without the name column.
names = coilmap.load(gameinfo.table("device_xy.txt") or "")
for node in range(coilmap.NODES):
    for idx in range(coilmap.COIL_N):
        c = coilmap.counter(d, node, idx)
        if c:
            named = next((k["name"] for k in names
                          if k["node"] == node and k["index"] == idx), "")
            print("%2d %2d  count=%3d lvl=%3d  %s"
                  % (node, idx, c,
                     d[coilmap.LVL_OFF + node * coilmap.COIL_N + idx], named))
