#!/bin/bash
G=/home/david/spike2root/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump
echo "############ 0x4db74c : the thing that faults ############"
$OD -d --start-address=0x4db74c --stop-address=0x4db8c0 $G | sed -n '7,300p'
