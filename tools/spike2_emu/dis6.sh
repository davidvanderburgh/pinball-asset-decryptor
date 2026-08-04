#!/bin/bash
G=/home/david/spike2root/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "########## event-93 handler 0x564cc ##########"
$OD -d --start-address=0x564cc --stop-address=0x56620 $G | sed -n '7,300p'

echo
echo "########## registration block around 0x5bae0..0x5bb40 ##########"
$OD -d --start-address=0x5bad0 --stop-address=0x5bb50 $G | sed -n '7,120p'
