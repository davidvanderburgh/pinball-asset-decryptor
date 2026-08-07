#!/bin/bash
# Q16: 0x458e98(pool, name, ...) is the queue allocator; 0x33a478 stores its
# result unconditionally, so it returned NULL. Read it.
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
D=$HOME/game.dis
OD=arm-linux-gnueabihf-objdump

echo "############ 0x458e98 : the queue allocator ############"
$OD -d --start-address=0x458e98 --stop-address=0x459070 $G | sed -n '7,140p'

echo
echo "############ callers of 0x458e98 ############"
grep -naE 'bl	458e98' $D | head
