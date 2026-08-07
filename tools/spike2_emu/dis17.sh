#!/bin/bash
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "########## 0x4475a8 (called from the big init at 0x4f0918) ##########"
$OD -d --start-address=0x4475a8 --stop-address=0x447630 $G | sed -n '7,80p'
echo
echo "########## 0x1d5d10..0x1d5d60 ##########"
$OD -d --start-address=0x1d5d10 --stop-address=0x1d5d60 $G | sed -n '7,60p'
