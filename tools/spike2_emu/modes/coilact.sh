#!/bin/bash
# coilact.sh <trigger> <content> [wait_s] - which coil fires when the probe calls something (item 125)
#
# Reads the shim's coil counters from dump/padled (padled.h: coil[16][16] wrapping fire
# counts at 1556, lvl[16][16] last drive byte at 1812, coil_gen at 2068) before and after
# dropping /dump/padmode.<trigger>, and prints every (node, coil) whose count moved.
#   coilact.sh fx "2000 3 0"      does 0x185e9c(2000, 3, 0) fire a device, and which?
# A rig action beside a live run with PAD_TRACE_SO=/lib/padmode.so, under the lock.
. "$(dirname "$0")/../padpath.sh"
D=$ROOT/dump
snap() {
  python3 - "$D/padled" << 'PY'
import struct, sys
b = open(sys.argv[1], "rb").read(4096)
gen = struct.unpack_from("<I", b, 2068)[0]
coil = b[1556:1556 + 256]
lvl = b[1812:1812 + 256]
print(gen, coil.hex(), lvl.hex())
PY
}
read -r g0 c0 l0 <<< "$(snap)"
printf '%s\n' "$2" > "$D/padmode.$1"
sleep "${3:-3}"
read -r g1 c1 l1 <<< "$(snap)"
echo "coil frames decoded during the window: $((g1 - g0))"
python3 - "$c0" "$c1" "$l1" << 'PY'
import sys
c0, c1, l1 = (bytes.fromhex(x) for x in sys.argv[1:4])
moved = [(i // 16, i % 16, (c1[i] - c0[i]) & 0xFF, l1[i]) for i in range(256) if c0[i] != c1[i]]
for node, coil, n, lvl in moved:
    print("  node %2d coil %2d fired %3d times, last drive byte %d" % (node, coil, n, lvl))
if not moved:
    print("  no coil counter moved")
PY
grep -a '\[trigger\]' "$D/padmode.log" | tail -1
