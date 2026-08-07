#!/bin/bash
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "### 0x268ea0 - the extension comparison used at 0x26aac0 ###"
$OD -d --start-address=0x268ea0 --stop-address=0x268f10 $G | sed -n '7,60p'
echo
echo "### 0x26abfc .. 0x26ad00 - rest of the loader body ###"
$OD -d --start-address=0x26abfc --stop-address=0x26ad00 $G | sed -n '7,200p'
