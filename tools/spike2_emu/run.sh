#!/bin/bash
cd /home/david
LOG=${1:-gz50.log}
S=$(date +%s)
./run_gz.sh > "$LOG" 2>&1
E=$(date +%s)
echo "elapsed: $((E-S)) s   lines: $(wc -l < "$LOG")   log: $LOG"
