#!/bin/bash
cd $HOME
L=gz52.strace
echo "=== does it contain qemu strace lines? ==="
grep -cE '^[0-9]+ (open|openat|read|close)' $L
echo
echo "=== first auto_loaded scene.radium open, with 30 following lines ==="
N=$(grep -n 'auto_loaded.*scene.radium' $L | grep -E 'open' | head -1 | cut -d: -f1)
echo "line $N"
sed -n "${N},$((N+30))p" $L
echo
echo "=== fdstat.py ==="
python3 fdstat.py $L
