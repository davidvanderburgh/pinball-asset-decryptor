"""parttbl.py - dump the 28-entry node board MCU part table at VA 0x69cc24.

Each entry is 28 bytes: +0 part id, +4 name ptr, +8 CPU CLASS INDEX, +0x10 flash
size, +0x14 core clock, +0x18 page size.

The class index at +8 is the field the hex image lookup uses as its second key
(0x44880c compares it against the registry node's [+4]), and it is also what
picks the middle of the firmware filename via 0x59e9bc:
    0 UNSUPPORTED  1 LPC1112_101  2 LPC1112_201  3 LPC1113_302
    4 LPC1124_303  5 LPC1313      6 LPC812       7 RP235x
So a board can only ever match a <nodetype>-<CLASS>-*.hex file whose CLASS name
corresponds to the class of the part id it claims in its identity reply.

This is .rodata, so VA = file offset + 0x8000.
"""
import struct
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gameinfo

GAME = gameinfo.elf()
BASE = 0x69CC24
DELTA = 0x8000
CLASS = ["UNSUPPORTED", "LPC1112_101", "LPC1112_201", "LPC1113_302",
         "LPC1124_303", "LPC1313", "LPC812", "RP235x"]

blob = open(GAME, "rb").read()


def cstr(va):
    if not va:
        return ""
    p = va - DELTA
    end = blob.index(b"\x00", p)
    return blob[p:end].decode("latin1")


print("%-10s  %-24s %-3s %-12s" % ("part id", "name", "cls", "class name"))
for i in range(28):
    off = BASE - DELTA + i * 28
    pid, namep, cls = struct.unpack("<III", blob[off:off + 12])
    name = cstr(namep)
    cname = CLASS[cls] if cls < len(CLASS) else "?"
    print("%08x    %-24s %-3d %-12s" % (pid, name, cls, cname))

want = sys.argv[1:] or ["5", "4", "6"]
print()
print("--- part ids by class (what to claim for a given firmware file) ---")
for w in want:
    hits = []
    for i in range(28):
        off = BASE - DELTA + i * 28
        pid, namep, cls = struct.unpack("<III", blob[off:off + 12])
        if str(cls) == w:
            hits.append("%08x %s" % (pid, cstr(namep)))
    print("class %s (%s): %s" % (w, CLASS[int(w)], ", ".join(hits) or "NONE"))
