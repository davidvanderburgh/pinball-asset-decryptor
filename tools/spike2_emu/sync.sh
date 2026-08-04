#!/bin/bash
for f in hwshim.c alsastub.c glstub.c; do
  if diff -q /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/$f /home/david/emusrc/$f >/dev/null 2>&1; then
    echo "$f SAME"
  else
    echo "$f DIFFER"
  fi
done
echo "--- libs the game needs ---"
arm-linux-gnueabihf-readelf -d /home/david/spike2root/games/godzilla_pro/game | grep NEEDED
