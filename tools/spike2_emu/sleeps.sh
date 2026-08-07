#!/bin/bash
cd $HOME
L=${1:-gz60.log}
echo "=== all logged usleep calls ==="
grep '\[sleep\]' "$L" | head -45
echo
echo "=== distinct usleep return addresses ==="
grep -o 'from=0x[0-9a-f]*' "$L" | sort | uniq -c | sort -rn | head -15
