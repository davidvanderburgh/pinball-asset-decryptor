#!/bin/bash
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump
echo "########## event-93 handler[0] = 0x53020 ##########"
$OD -d --start-address=0x53020 --stop-address=0x53140 $G | sed -n '7,140p'
