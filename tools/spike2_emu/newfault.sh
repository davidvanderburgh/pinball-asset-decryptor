#!/bin/bash
cd /home/david
L=${1:-gz75.log}
PC=0x40a6a858
echo "=== which library contains $PC ? ==="
grep -a 'r-xp' $L | awk -v pc=$((PC)) '{
  split($1, a, "-"); lo = strtonum("0x" a[1]); hi = strtonum("0x" a[2]);
  if (pc >= lo && pc < hi) printf "  %s  base=0x%x  offset=0x%x\n", $NF, lo, pc - lo
}'
echo
echo "=== game code at the call site lr=0x4db77c ==="
arm-linux-gnueabihf-objdump -d --start-address=0x4db730 --stop-address=0x4db790 \
  spike2root/games/godzilla_pro/game | sed -n '7,60p'
