#!/bin/bash
# Q10: the 8 x 64-byte voice slots live at the GLOBAL 0x7b90c0, so the null
# queue is voice[n]+0x38 of a static array. Find every site that builds that
# address, and every store to +0x38 in the audio translation unit.
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
D=$HOME/game.dis
OD=arm-linux-gnueabihf-objdump

echo "############ sites building the voice-array address 0x7b90c0 ############"
bash $RIG/findref.sh 0x7b90c0

echo
echo "############ sites building 0x7b8990 (the TU's state block) ############"
bash $RIG/findref.sh 0x7b8990

echo
echo "############ every 'str rX,[rY,#56]' between 0x29e000 and 0x2a8000 ############"
$OD -d --start-address=0x29e000 --stop-address=0x2a8000 $G | grep -aE 'str	.*#56\]' | head -40

echo
echo "############ real start of the function holding the mixer loop ############"
$OD -d --start-address=0x2a2238 --stop-address=0x2a22b0 $G | sed -n '7,40p'
