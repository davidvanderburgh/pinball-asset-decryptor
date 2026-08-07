#!/bin/bash
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump
echo "############ 0x459184 : the streaming worker thread body ############"
$OD -d --start-address=0x459184 --stop-address=0x4592e0 $G | sed -n '7,110p'
