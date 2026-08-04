#!/bin/bash
cd /home/david
L=${1:-gz64.log}
echo "=== which branch does the scene loader take? ==="
grep '\[branch\]' "$L"
echo
echo "scenes with bytes>0: $(awk '/^\[scene\]/ && $2+0>0' "$L" | wc -l) of $(grep -c '^\[scene\]' "$L")"
echo "Radium warnings: $(grep -c 'Radium Warning' "$L")"
