#!/bin/bash
. "$(dirname "$0")/padpath.sh"
A=$ROOT/games/godzilla_pro/assets/lcd
echo "=== scene.radium header (first 64 bytes, hex + ascii) ==="
F=$(find $A/auto_loaded -name scene.radium | head -1)
echo "$F"
xxd -l 64 "$F"
echo
echo "=== which scenes mention TopPanel_Instance ==="
grep -rl 'TopPanel_Instance' $A --include=scene.radium 2>/dev/null
echo
echo "=== which scenes mention BallAndCredits_Instance ==="
grep -rl 'BallAndCredits_Instance' $A --include=scene.radium 2>/dev/null
echo
echo "=== which scenes mention NetUser1 ==="
grep -rl 'NetUser1' $A --include=scene.radium 2>/dev/null
