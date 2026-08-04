#!/bin/bash
cd /home/david
L=${1:-gz53.log}
grep '\[scenebt\]' "$L"
echo
echo "=== scene byte totals ==="
echo "closes: $(grep -c '^\[scene\]' "$L")   nonzero: $(awk '/^\[scene\]/ && $2+0>0' "$L" | wc -l)"
