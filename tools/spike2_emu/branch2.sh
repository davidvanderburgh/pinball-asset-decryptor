#!/bin/bash
cd /home/david
L=${1:-gz66.log}
echo "=== loader string-literal sequence (radium vs json) ==="
grep '\[branch\]' "$L" | head -20
echo
echo "=== allocations proving how far the loader got ==="
grep '\[new\]' "$L" | head -12
echo
echo "=== exceptions ==="
grep -c '\[throw\]' "$L"
echo "scenes with bytes>0: $(awk '/^\[scene\]/ && $2+0>0' "$L" | wc -l) of $(grep -c '^\[scene\]' "$L")"
