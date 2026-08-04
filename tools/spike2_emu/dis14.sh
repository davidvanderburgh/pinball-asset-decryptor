#!/bin/bash
G=/home/david/spike2root/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "############ MemFree use at 0x14c320 ############"
$OD -d --start-address=0x14c2c0 --stop-address=0x14c3d0 $G | sed -n '7,120p'
echo
echo "############ /proc/meminfo open at 0x1a8414 ############"
$OD -d --start-address=0x1a83d0 --stop-address=0x1a8460 $G | sed -n '7,60p'
