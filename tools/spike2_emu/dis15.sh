#!/bin/bash
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump
echo "### function boundary scan before 0x3a2f94 ###"
$OD -d --start-address=0x3a2e00 --stop-address=0x3a2fa0 $G | grep push | tail -5
echo
echo "### /proc/meminfo reader around 0x3a2f94 ###"
$OD -d --start-address=0x3a2f60 --stop-address=0x3a3130 $G | sed -n '7,200p'
