#!/bin/bash
D=$HOME/game.dis

echo "### head of game.dis (sanity) ###"
head -6 $D

echo
echo "### all references to the event table 0x7e4d48 (movw #19784) ###"
grep -n 'movw.*#19784' $D | head -40

echo
echo "### all bl 4bb42c call sites ###"
grep -n 'bl	4bb42c' $D | head -60
