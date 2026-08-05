"""coilread.py - print every nonzero coil fire counter from the padled block.

One line per addressed coil: `node index count lvl`. Diffing two invocations
around a Coil Test fire names the (node, index) the highlighted row drives.
Offsets are padled.h's, same hard-coded values playfield.py carries.
"""
import struct
import sys

PATH = r"\\wsl.localhost\Ubuntu\home\david\spike2root\dump\padled"
MAGIC = 0x44454C50
COIL_OFF, COIL_N, NODES = 1556, 16, 16
LVL_OFF = COIL_OFF + NODES * COIL_N
GEN_OFF = LVL_OFF + NODES * COIL_N

d = open(PATH, "rb").read(GEN_OFF + 8)
if struct.unpack_from("<I", d, 0)[0] != MAGIC:
    print("NO MAGIC - emulator not up")
    sys.exit(2)
print("coil_gen=%d coil_decoded=%d" % struct.unpack_from("<II", d, GEN_OFF))
for node in range(NODES):
    for idx in range(COIL_N):
        c = d[COIL_OFF + node * COIL_N + idx]
        if c:
            print("%2d %2d  count=%3d lvl=%3d"
                  % (node, idx, c, d[LVL_OFF + node * COIL_N + idx]))
