#!/bin/bash
# Q3: the enclosing-function heuristic broke in 0x2a4b24..0x33a030 (a 610 KB
# region with no bl targets at all = virtual functions only). Find the real
# function start containing 0x30ed80 by scanning back for the previous return.
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "############ 0x30ec00 .. 0x30ee40 ############"
$OD -d --start-address=0x30ec00 --stop-address=0x30ee40 $G | sed -n '7,300p'
