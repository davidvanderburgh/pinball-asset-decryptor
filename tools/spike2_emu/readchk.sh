#!/bin/bash
cd $HOME
L=gz52.strace
echo "=== fds assigned to scene.radium opens ==="
grep -ao 'scene.radium",O_RDONLY|O_LARGEFILE) = [0-9]*' $L | sort | uniq -c | sort -rn | head
echo
echo "=== every read() on fd 13 anywhere in the log ==="
grep -ao 'read(13,[^)]*) = [0-9-]*' $L | sort | uniq -c | head -20
echo
echo "=== every read() on fd 15/16/18 ==="
for f in 15 16 18; do
  echo "-- fd $f --"
  grep -ao "read($f,[^)]*) = [0-9-]*" $L | sort | uniq -c | head -5
done
echo
echo "=== total read() calls in the log ==="
grep -aoc 'read([0-9]*,' $L
echo
echo "=== close() calls right after a scene open (sample) ==="
grep -a -A2 'auto_loaded/9d57875196c613785a1eee010c55223a0f1aa821/scene.radium",O_RDONLY' $L | head -12
