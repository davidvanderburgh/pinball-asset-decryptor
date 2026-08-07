#!/bin/bash
# Q23: the worker's opening construct reads 0x7acb54 once and spins on the
# register. Find every site that WRITES that byte and what value it writes.
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump
for a in 1d7d1c 21cf28 21d03c 21d07c 21d0b8 21d118 21d174 3bba14 3bfdc0 4e7e6c; do
  echo "===== around 0x$a ====="
  s=$((0x$a - 16)); e=$((0x$a + 28))
  $OD -d --start-address=$s --stop-address=$e $G | sed -n '7,30p'
done
