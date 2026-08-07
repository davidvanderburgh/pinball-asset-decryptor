#!/bin/bash
. "$(dirname "$0")/padpath.sh"
cd $HOME
LOG=${1:-gz50.log}
S=$(date +%s)
bash $RIG/run_game.sh > "$LOG" 2>&1
E=$(date +%s)
echo "elapsed: $((E-S)) s   lines: $(wc -l < "$LOG")   log: $LOG"
