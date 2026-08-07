#!/bin/bash
# Q12: only four instructions in the whole audio TU store to +0x38.
# 0x2a209c sits inside 0x2a2044, which the wrapper 0x2a212c calls under the
# global audio mutex 0x704bf4 -- i.e. the "start a voice" path.
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "############ 0x2a2044 .. 0x2a212c  (called under the audio mutex) ############"
$OD -d --start-address=0x2a2044 --stop-address=0x2a212c $G | sed -n '7,80p'

echo
echo "############ around 0x2a0e04 / 0x2a0e28 ############"
$OD -d --start-address=0x2a0dc0 --stop-address=0x2a0e40 $G | sed -n '7,60p'

echo
echo "############ around 0x2a1074 ############"
$OD -d --start-address=0x2a1030 --stop-address=0x2a1090 $G | sed -n '7,40p'
