#!/bin/bash
G=/home/david/spike2root/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump
D=/home/david/game.dis

echo "### registrar region 0x4bb320 - 0x4bb42c ###"
$OD -d --start-address=0x4bb320 --stop-address=0x4bb430 $G | sed -n '7,200p'

echo
echo "### other table users 0x1d5320 and 0x2a21bc (context) ###"
$OD -d --start-address=0x1d52f0 --stop-address=0x1d5360 $G | sed -n '7,60p'
echo "---"
$OD -d --start-address=0x2a2190 --stop-address=0x2a21f0 $G | sed -n '7,60p'
