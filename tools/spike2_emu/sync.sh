#!/bin/bash
. "$(dirname "$0")/padpath.sh"
for f in hwshim.c alsastub.c glstub.c; do
  if diff -q "$RIG/$f" "$HOME/emusrc/$f" >/dev/null 2>&1; then
    echo "$f SAME"
  else
    echo "$f DIFFER"
  fi
done
echo "--- libs the game needs ---"
arm-linux-gnueabihf-readelf -d "$ROOT/games/godzilla_pro/game" | grep NEEDED
