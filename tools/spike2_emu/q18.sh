#!/bin/bash
# Q18: 0x2a4a64 writes the pool into [0x7b8990+0x100]. Read the construction
# site, and the ring push side (0x4596e0/0x4596f0 set head AND tail = init).
G=/home/david/spike2root/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "############ pool construction: 0x2a49c0 .. 0x2a4a90 ############"
$OD -d --start-address=0x2a49c0 --stop-address=0x2a4a90 $G | sed -n '7,70p'

echo
echo "############ ring init/grow: 0x459690 .. 0x459700 ############"
$OD -d --start-address=0x459690 --stop-address=0x459700 $G | sed -n '7,40p'

echo
echo "############ ring push: 0x4592e0 .. 0x459340 ############"
$OD -d --start-address=0x4592e0 --stop-address=0x459340 $G | sed -n '7,40p'
