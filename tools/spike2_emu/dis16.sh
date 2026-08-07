#!/bin/bash
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "########## LoadSceneCache thread start routine 0x447440 ##########"
$OD -d --start-address=0x447440 --stop-address=0x447538 $G | sed -n '7,120p'
echo
echo "########## enumerator thread 0x444e14 ##########"
$OD -d --start-address=0x444e14 --stop-address=0x444f40 $G | sed -n '7,150p'
