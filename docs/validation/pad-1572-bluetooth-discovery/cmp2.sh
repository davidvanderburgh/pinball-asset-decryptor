#!/bin/bash
B=/tmp/pad1572probe
run(){ c=$(mktemp -d); chmod 700 $c; $B/probe "$1" $c "$(sha256sum "$1"|cut -c1-64)"; }
for k in pro le; do for kind in text menu all; do
  f=/mnt/c/tmp/PAD-1572/elf/gz${k}116_main_$kind.elf
  first=$(run $f | head -1); d=$(diff <(run /mnt/c/tmp/gz${k}116_stock.elf | tail -n +2) <(run $f | tail -n +2) | grep -c '^>')
  echo "gz${k}116_main_$kind: $first; addresses differing from stock: $d"
done; done
