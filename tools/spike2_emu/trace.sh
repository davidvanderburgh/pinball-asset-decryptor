#!/bin/bash
# Ask qemu-user itself which basic blocks of the scene loader actually execute.
# QEMU_DFILTER keeps the log to just the ranges of interest.
cd /home/david
R=/home/david/spike2root
rm -f $R/dump/tb.log
export QEMU_LOG=exec,nochain
export QEMU_LOG_FILENAME=/dump/tb.log
export QEMU_DFILTER=0x444014..0x444160,0x26aa58..0x26ad00,0x27316c..0x2731b0
./run_gz.sh > gz68.log 2>&1
echo "log size: $(du -h $R/dump/tb.log 2>/dev/null | cut -f1)"
echo
echo "=== distinct basic blocks executed, in the loader ranges ==="
grep -ao 'Trace [0-9]*: 0x[0-9a-f]* *\[[^]]*\]' $R/dump/tb.log 2>/dev/null | \
  grep -o '\[[^]]*\]' | sort | uniq -c | sort -rn | head -30
echo
echo "=== raw head ==="
head -20 $R/dump/tb.log 2>/dev/null
