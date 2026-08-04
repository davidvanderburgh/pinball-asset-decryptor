#!/bin/bash
cd /home/david
L=gz52.strace
echo "=== read(51, ...) occurrences ==="
grep -ao 'read(51,[^)]*) = [0-9-]*' $L | sort | uniq -c | sort -rn | head -20
echo
echo "=== total ==="
grep -aoc 'read(51,' $L
echo
echo "=== other I/O syscalls on fd 51 ==="
grep -ao '\(pread64\|readv\|lseek\|_llseek\|mmap2\)([^)]*51[^)]*)' $L | head -10
echo
echo "=== was the throw path 0x2731ac ever translated? ==="
grep -ac '0x002731ac' /home/david/spike2root/dump/tb.log
echo "=== block after loadBinary returns (0x273198)? ==="
grep -ac '0x00273198' /home/david/spike2root/dump/tb.log
