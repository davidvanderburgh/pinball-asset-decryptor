#!/bin/bash
. "$(dirname "$0")/padpath.sh"
D=$HOME/game.dis
G=$ROOT/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "### refs to the boot-ready flag 0x7e1974 (movw #6516) ###"
grep -n 'movw.*#6516' $D
echo
echo "### and #6516 as movt-126 pairs, show context ###"
for a in $(grep -n 'movw.*#6516' $D | sed 's/:.*//'); do
  echo "--- game.dis line $a ---"
  sed -n "$((a-3)),$((a+8))p" $D
done
