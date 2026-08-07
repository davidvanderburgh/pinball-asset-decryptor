#!/bin/bash
cd $HOME
L=${1:-gz62.log}
echo "=== [boot] marker: did the big init tail run? ==="
grep '\[boot\]' "$L"
echo
echo "=== scenes with bytes read > 0: $(awk '/^\[scene\]/ && $2+0>0' "$L" | wc -l) of $(grep -c '^\[scene\]' "$L") ==="
awk '/^\[scene\]/ && $2+0>0' "$L" | head -10
echo "=== Radium warnings: $(grep -c 'Radium Warning' "$L") ==="
