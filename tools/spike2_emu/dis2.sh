#!/bin/bash
G=/home/david/spike2root/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump
$OD -d --start-address=0x4f0720 --stop-address=0x4f08c0 $G | sed -n '7,400p'
