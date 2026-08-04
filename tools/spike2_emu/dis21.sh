#!/bin/bash
G=/home/david/spike2root/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump
echo "########## 0x27316c (called by the archive ctor with size=1) ##########"
$OD -d --start-address=0x27316c --stop-address=0x273260 $G | sed -n '7,120p'
echo
echo "########## 0x273bb8 (builds the returned string) ##########"
$OD -d --start-address=0x273bb8 --stop-address=0x273c60 $G | sed -n '7,100p'
