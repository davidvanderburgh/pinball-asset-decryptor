#!/bin/bash
# nav.sh <id> [<id> ...] - walk the operator menu through the shared-memory
# switch channel, then repack the next host frame into now.png.
#
# ids: 25 Select, 26 Plus/down, 27 Minus/up, 28 Back.
#
# The gap matters. Four presses 0.6 s apart moved the cursor two rows - the
# game debounces and the menu itself has a repeat delay - so this uses a 400 ms
# hold and a 1.5 s gap, which has not dropped one yet. If a press is dropped the
# whole rest of the sequence lands on the wrong screen, so slow is cheap here.
. "$(dirname "$0")/padpath.sh"
set -u
D=$HOME/shots
for id in "$@"; do
    python3 $RIG/swpoke.py "$id" 400 >/dev/null
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
python3 $RIG/repack.py "$F" $RIG/now.png 1
