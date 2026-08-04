#!/bin/bash
G=/home/david/spike2root/games/godzilla_pro/game
D=/home/david/game.dis
OD=arm-linux-gnueabihf-objdump

echo "### prologue of the faulting function 0x30ed30 ###"
$OD -d --start-address=0x30ed30 --stop-address=0x30ed84 $G | sed -n '7,40p'
echo
echo "### callers of 0x30ed30 ###"
grep -n 'bl	30ed30' $D
echo
echo "### what is the global 0x7b8990 used for? (first 12 refs) ###"
bash /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/findref.sh 0x7b8990 | head -12
echo
echo "### 0x4db74c full: the queue push ###"
$OD -d --start-address=0x4db74c --stop-address=0x4db7d0 $G | sed -n '7,40p'
