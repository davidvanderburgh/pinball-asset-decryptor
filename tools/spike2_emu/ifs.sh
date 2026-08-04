#!/bin/bash
cd /home/david
L=${1:-gz54.log}
grep '\[ifs\]' "$L"
echo
echo "closes: $(grep -c '^\[scene\]' "$L")   nonzero-byte scenes: $(awk '/^\[scene\]/ && $2+0>0' "$L" | wc -l)"
echo "Radium warnings: $(grep -c 'Radium Warning' "$L")"
