#!/bin/bash
D=/home/david/game.dis
G=/home/david/spike2root/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "### refs to /proc/meminfo (0x689708 -> movw #38664) ###"
grep -n 'movw.*#38664' $D
echo "### refs to MemFree (0x6896d4 -> movw #38612) ###"
grep -n 'movw.*#38612' $D
echo "### refs to MemAvailable (0x6896dc -> movw #38620) ###"
grep -n 'movw.*#38620' $D
