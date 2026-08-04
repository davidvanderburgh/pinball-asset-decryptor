#!/bin/bash
cd /home/david
L=${1:-gz75.log}
S=$(date +%s); ./run_gz.sh > $L 2>&1; E=$(date +%s)
echo "elapsed: $((E-S)) s"
echo "=== milestone ==="
printf '  scenes with bytes read > 0 : %s / %s\n' \
  "$(awk '/\[scenebytes\]/ && $2+0>0' $L | wc -l)" "$(grep -c '\[scenebytes\]' $L)"
printf '  Radium warnings            : %s (was 45)\n' "$(grep -c 'Radium Warning' $L)"
echo "=== state ==="
printf '  ExchangeData errors : %s\n' "$(grep -c ExchangeData $L)"
printf '  exceptions thrown   : %s\n' "$(grep -c '\[throw\]' $L)"
printf '  fault               : %s\n' "$(grep -o 'pc=0x[0-9a-f]* lr=0x[0-9a-f]* r0=0x[0-9a-f]*' $L | head -1)"
echo "=== segv detail ==="
grep '\[segv\]' $L | head -14
echo "=== new numbered fatals this run ==="
grep 'FATAL' spike2root/dump/debug_log.txt | tail -3
echo "=== last non-warning output lines ==="
grep -vE '\[scenebytes\]|\[hdr\]|\[fb\]|\[read\]|\[fread\]|\[sync\]|\[branch\]|\[new\]|\[ifs\]|\[scene\]|\[sleep\]|\[hwshim\]|\[i2c\]|\[maps\]|^[0-9a-f]+-' $L | tail -25
