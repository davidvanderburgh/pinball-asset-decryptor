#!/bin/bash
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "### function boundaries (push) in 0x443c00..0x444200 ###"
$OD -d --start-address=0x443c00 --stop-address=0x444200 $G | grep -E 'push' | tail -20
echo
echo "### 0x443fXX .. 0x444180 (the auto_loaded opener frame) ###"
$OD -d --start-address=0x443fa0 --stop-address=0x444180 $G | sed -n '7,300p'
