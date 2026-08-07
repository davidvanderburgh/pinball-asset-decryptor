#!/bin/bash
cd $HOME
L=${1:-gz72.log}
N=$(grep -c '\[scenebytes\]' "$L")
echo "=== per-scene byte accounting: $N scenes reported ==="
echo "with asked > 0 : $(awk '/\[scenebytes\]/ && $2+0>0' "$L" | wc -l)"
echo
echo "--- distribution of bytes asked ---"
grep '\[scenebytes\]' "$L" | awk '{print $2}' | sort -n | uniq -c | tail -15
echo
echo "--- the scene that owns all 45 warnings ---"
grep '\[scenebytes\]' "$L" | grep 9d57875196c613785a1eee010c55223a0f1aa821
echo
echo "--- biggest readers ---"
grep '\[scenebytes\]' "$L" | sort -k2 -n -r | head -5
echo
echo "Radium warnings: $(grep -c 'Radium Warning' "$L")"
