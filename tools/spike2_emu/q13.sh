#!/bin/bash
# Q13: voice[2].mixA=0x339204 mixB=0x336c6c, but execution reached 0x30ed20
# (table 0x67e1c0 index 147) with lr still 0x2a24ac -- so 0x336c6c must TAIL
# BRANCH through the table. Confirm, and find the queue's allocator.
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
D=$HOME/game.dis
OD=arm-linux-gnueabihf-objdump

echo "############ 0x336c6c : the mix dispatcher (mixB) ############"
$OD -d --start-address=0x336c6c --stop-address=0x336d10 $G | sed -n '7,60p'

echo
echo "############ 0x339204 : mixA ############"
$OD -d --start-address=0x339204 --stop-address=0x339260 $G | sed -n '7,40p'

echo
echo "############ 0x458674 : release-queue-to-pool, and its neighbours ############"
$OD -d --start-address=0x458674 --stop-address=0x458720 $G | sed -n '7,50p'

echo
echo "############ callers of 0x458674 ############"
grep -naE 'bl	458674' $D | head
