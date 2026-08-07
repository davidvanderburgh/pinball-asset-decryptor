#!/bin/bash
cd $HOME
L=gz52.strace
echo "=== mmap calls referencing fd 51 (the scene fd) ==="
grep -ao 'mmap2\?([^)]*,51,[^)]*)[^,]*' $L | head -10
echo
echo "=== all mmap2 calls with a real (non -1) fd, counted by fd ==="
grep -ao 'mmap2\?([^)]*)' $L | grep -o ',[0-9]*,[0-9]*)$' | sort | uniq -c | sort -rn | head -15
echo
echo "=== raw sample of mmap lines near a scene open ==="
grep -an 'mmap' $L | grep -v '4294967295' | head -20
