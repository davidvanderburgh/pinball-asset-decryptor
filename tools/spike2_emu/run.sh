#!/bin/bash
cd /home/david
LOG=${1:-gz50.log}
S=$(date +%s)
bash /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/run_game.sh > "$LOG" 2>&1
E=$(date +%s)
echo "elapsed: $((E-S)) s   lines: $(wc -l < "$LOG")   log: $LOG"
