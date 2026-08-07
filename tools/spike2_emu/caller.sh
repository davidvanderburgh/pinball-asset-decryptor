#!/bin/bash
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump
echo "########## caller: around 0x458fec ##########"
$OD -d --start-address=0x458fa0 --stop-address=0x459000 $G | sed -n '7,60p'
echo
echo "########## next frame up: around 0x30ed84 ##########"
$OD -d --start-address=0x30ed50 --stop-address=0x30ed90 $G | sed -n '7,40p'
