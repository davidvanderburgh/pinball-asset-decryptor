#!/bin/bash
G=/home/david/spike2root/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "########## 0x447538 (called from the big-init list) ##########"
$OD -d --start-address=0x447538 --stop-address=0x4475b0 $G | sed -n '7,60p'

echo
echo "########## rest of 0x4f0720 fn: 0x4f08c0 .. 0x4f0a90 ##########"
$OD -d --start-address=0x4f08c0 --stop-address=0x4f0a90 $G | sed -n '7,300p'
