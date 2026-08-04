#!/bin/bash
G=/home/david/spike2root/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "### enclosing function of 0x30ed50: scan back for a prologue ###"
$OD -d --start-address=0x30ea00 --stop-address=0x30ed54 $G | grep -E 'push' | tail -4
echo
echo "### frame above: call site 0x33a5e0 ###"
$OD -d --start-address=0x33a590 --stop-address=0x33a5f8 $G | sed -n '7,50p'
echo
echo "### and 0x2a24a8 ###"
$OD -d --start-address=0x2a2470 --stop-address=0x2a24b8 $G | sed -n '7,40p'
