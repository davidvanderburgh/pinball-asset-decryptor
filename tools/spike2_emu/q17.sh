#!/bin/bash
# Q17: 0x458e98 bailed at the "free ring empty" test ([pool+0x84]==[pool+0x74]).
# Find who PUSHES onto that ring (+0x84) and who builds the pool at [0x7b8a90].
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
D=$HOME/game.dis
OD=arm-linux-gnueabihf-objdump

echo "############ stores to +0x84 (ring tail) in 0x450000-0x462000 ############"
$OD -d --start-address=0x450000 --stop-address=0x462000 $G | grep -aE '	str	r[0-9a-z]+, \[r[0-9a-z]+, #132\]' | head -20

echo
echo "############ stores to +0x74 (ring head) in 0x450000-0x462000 ############"
$OD -d --start-address=0x450000 --stop-address=0x462000 $G | grep -aE '	str	r[0-9a-z]+, \[r[0-9a-z]+, #116\]' | head -20

echo
echo "############ who writes the pool global at 0x7b8990+0x100 ? ############"
$OD -d --start-address=0x2a0000 --stop-address=0x2b0000 $G | grep -aE '	str	r[0-9a-z]+, \[r[0-9a-z]+, #256\]' | head -20
$OD -d --start-address=0x330000 --stop-address=0x345000 $G | grep -aE '	str	r[0-9a-z]+, \[r[0-9a-z]+, #256\]' | head -20

echo
echo "############ is 'Thread create failed' from THIS run? ############"
date -u +'now      : %Y-%m-%dT%H:%M:%SZ'
tail -6 $ROOT/dump/debug_log.txt
