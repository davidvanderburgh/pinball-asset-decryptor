#!/bin/bash
cd /home/david
LOG=${1:-gz58.log}
SECS=${2:-25}
export PAD_BOOT_DELAY=$SECS
S=$(date +%s)
./run_game.sh > "$LOG" 2>&1
E=$(date +%s)
echo "elapsed: $((E-S)) s   log: $LOG"
echo
echo "=== boot hold applied? ==="
grep 'boot hold' "$LOG"
echo
echo "=== scenes with bytes read > 0 ==="
awk '/^\[scene\]/ && $2+0>0' "$LOG" | head -15
echo "count: $(awk '/^\[scene\]/ && $2+0>0' "$LOG" | wc -l) of $(grep -c '^\[scene\]' "$LOG") closes"
echo
echo "=== Radium warnings: $(grep -c 'Radium Warning' "$LOG") ==="
grep -E 'loader_gate|pc=0x' "$LOG" | head -4
