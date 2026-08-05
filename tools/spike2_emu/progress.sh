#!/bin/bash
cd /home/david
L=${1:-gz75.log}
echo "=== game-emitted lines (not shim/instrumentation) ==="
grep -vaE '\[scenebytes\]|\[hdr\]|\[fb\]|\[read\]|\[fread\]|\[sync\]|\[branch\]|\[new\]|\[ifs\]|\[scene\]|\[sleep\]|\[hwshim\]|\[i2c\]|\[maps\]|\[nb\]|\[segv\]|\[trace\]|\[thread\]|\[glstub\]|\[alsa\]|\[gst\]|\[boot\]|\[run\]|^[0-9a-f]+-[0-9a-f]+ ' $L | sort | uniq -c | sort -rn | head -25
echo
echo "=== node bus: distinct frames sent ==="
grep -a '\[nb\] TX len' $L | awk '{print $3, $4}' | sort | uniq -c | sort -rn | head -12
echo
echo "=== is the new fault deterministic? (3 runs) ==="
for i in 1 2 3; do
  ./run_game.sh > /tmp/r$i.log 2>&1
  printf '  run %d: %s  warnings=%s\n' $i \
    "$(grep -ao 'pc=0x[0-9a-f]* lr=0x[0-9a-f]*' /tmp/r$i.log | head -1)" \
    "$(grep -ca 'Radium Warning' /tmp/r$i.log)"
done
