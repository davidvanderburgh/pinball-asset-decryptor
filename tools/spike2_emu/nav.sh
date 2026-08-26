#!/bin/bash
# nav.sh <id> [<id> ...] - walk the operator menu through the shared-memory
# switch channel, then repack the next host frame into now.png.
#
# ids are PER TITLE (item 73) - read them from dump/tables/<game>/
# switch_list.txt: Select is the (node 0, bit 8) row, Plus/down (0,9),
# Minus/up (0,10), Back (0,11). On the godzilla generation that is 25/26/27/
# 28; on aerosmith it is 26/27/28/29, on batman 28/29/30/31.
#
# The gap matters. Four presses 0.6 s apart moved the cursor two rows - the
# game debounces and the menu itself has a repeat delay - so this uses a 400 ms
# hold and a 1.5 s gap, which has not dropped one yet. If a press is dropped the
# whole rest of the sequence lands on the wrong screen, so slow is cheap here.
. "$(dirname "$0")/padpath.sh"
# WHERE SCRATCH OUTPUT GOES. Not beside the scripts: the rig now ships
# in the installer and can live under Program Files, which is read-only
# for the user. PAD_OUT moves it; $HOME is the default.
OUT_DIR=${PAD_OUT:-$HOME}
set -u
D=$HOME/shots
for id in "$@"; do
    python3 "$RIG/swpoke.py" "$id" 400 >/dev/null
    echo "  press $id"
    sleep 1.5
done
BEFORE=$(ls -t $D/*.png 2>/dev/null | head -1)
for i in $(seq 1 160); do
    F=$(ls -t $D/*.png 2>/dev/null | head -1)
    [ -n "$F" ] && [ "$F" != "$BEFORE" ] && break
    sleep 0.25
done
echo "frame: $F"
python3 "$RIG/repack.py" "$F" "$OUT_DIR/now.png" 1
