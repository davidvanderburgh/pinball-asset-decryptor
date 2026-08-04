#!/bin/bash
# Q15: 0x33a3c0 enables the voice (+0x35=1) and 0x33a3c4 sets the stream desc
# (+0x00) -- both are true in the live dump -- but 0x33a478, the only store to
# +0x38, left it NULL. Read everything in between.
G=/home/david/spike2root/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "############ 0x33a400 .. 0x33a4a0 : the acquire + store ############"
$OD -d --start-address=0x33a400 --stop-address=0x33a4a0 $G | sed -n '7,60p'

echo
echo "############ head of the function: 0x33a1d0 .. 0x33a2a0 ############"
$OD -d --start-address=0x33a1d0 --stop-address=0x33a2a0 $G | sed -n '7,80p'
