#!/bin/bash
cd $HOME
L=${1:-gz71.log}
echo "=== libstdc++ read-path hook activity ==="
grep '\[fb\]' "$L" | head -25
echo
echo "=== totals at crash ==="
grep 'filebuf::xsgetn=' "$L"
echo
echo "=== ifstream rdbuf pointers (first 3) ==="
grep '\[ifs\]' "$L" | head -3
echo
echo "scenes with bytes>0: $(awk '/^\[scene\]/ && $2+0>0' "$L" | wc -l) of $(grep -c '^\[scene\]' "$L")"
echo "Radium warnings: $(grep -c 'Radium Warning' "$L")"
