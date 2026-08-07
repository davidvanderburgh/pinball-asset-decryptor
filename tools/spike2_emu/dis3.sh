#!/bin/bash
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "############ 0x4bb42c (called with r0=93 then r0=94) ############"
$OD -d --start-address=0x4bb42c --stop-address=0x4bb520 $G | sed -n '7,200p'

echo
echo "############ main 0x1c2d0 ############"
$OD -d --start-address=0x1c2d0 --stop-address=0x1c460 $G | sed -n '7,300p'
