#!/bin/bash
. "$(dirname "$0")/padpath.sh"
D=$HOME/game.dis
echo "=== all callers of 0x447538 (SceneCache start) ==="
grep -n 'bl	447538' $D
echo
echo "=== all callers of 0x4475a8 (SceneCache resume, sets the gate) ==="
grep -n 'bl	4475a8' $D
echo
echo "=== all callers of 0x4f0720 (the boot step) ==="
grep -n '	4f0720' $D
echo
echo "=== who references the thread entry 0x447440 ==="
bash "$RIG/findref.sh" 0x447440
