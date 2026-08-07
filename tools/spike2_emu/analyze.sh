#!/bin/bash
cd $HOME
LOG=${1:-gz50.log}
echo "########## [maps] ##########"
grep -E '^\[maps\]|r-xp' "$LOG" | head -30
echo
echo "########## [sleep] ##########"
grep '\[sleep\]' "$LOG" | head -20
echo
echo "########## [scene] summary ##########"
echo "scene closes logged: $(grep -c '^\[scene\]' "$LOG")"
echo "with bytes > 0     : $(awk '/^\[scene\]/ && $2+0 > 0' "$LOG" | wc -l)"
echo "auto_loaded opens  : $(grep -c 'auto_loaded.*scene.radium' "$LOG")"
echo "demand_loaded opens: $(grep -c 'demand_loaded.*scene.radium' "$LOG")"
echo
echo "--- first 12 [scene] lines ---"
grep '^\[scene\]' "$LOG" | head -12
echo "--- any with nonzero bytes ---"
awk '/^\[scene\]/ && $2+0 > 0' "$LOG" | head -12
echo
echo "########## Radium warnings: $(grep -c 'Radium Warning' "$LOG") ##########"
echo "########## segv ##########"
grep 'segv' "$LOG" | head -20
echo "########## errors ##########"
grep -E '^\[ERR\]|mount:|Unable to open' "$LOG" | sort | uniq -c | head -20
