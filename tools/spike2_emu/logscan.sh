#!/bin/bash
cd $HOME
echo "=== logs containing [trace] ==="
grep -l '\[trace\]' gz*.log 2>/dev/null
echo
echo "=== the [trace] lines themselves ==="
grep -h '\[trace\]' gz*.log 2>/dev/null | sort -u | head -30
echo
echo "=== logs mentioning auto_loaded / demand_loaded ==="
grep -l 'auto_loaded\|demand_loaded' gz*.log 2>/dev/null
echo
echo "=== Radium warning count in the newest few logs ==="
for f in gz42.log gz43.log gz45.log; do
  printf '%-12s warnings=%s  segv=%s\n' "$f" \
    "$(grep -c 'Radium Warning' $f)" "$(grep -c 'segv' $f)"
done
