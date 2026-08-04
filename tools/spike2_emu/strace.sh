#!/bin/bash
cd /home/david
rm -f gz17.log            # 1.6 GB from an earlier strace run, no longer needed
df -h /home | tail -1
S=$(date +%s)
QEMU_STRACE=1 ./run_gz.sh > gz52.strace 2>&1
E=$(date +%s)
echo "elapsed: $((E-S)) s   size: $(du -h gz52.strace | cut -f1)"
