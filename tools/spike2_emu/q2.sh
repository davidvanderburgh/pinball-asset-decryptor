#!/bin/bash
# Q2: build the set of real function entry points (every bl/blx target in the
# whole binary), then map each stack return address to its enclosing function.
D=$HOME/game.dis
F=$HOME/bltargets.txt

if [ ! -s $F ]; then
  echo "building bl-target set (once)..."
  awk -F'\t' '$3=="bl" || $3=="blx" { t=$4; sub(/ .*/,"",t); if (t ~ /^[0-9a-f]+$/) print t }' $D \
    | sort -u > $F
fi
echo "distinct call targets: $(wc -l < $F)"

echo
echo "### enclosing function for each frame address ###"
python3 - <<'PY'
import bisect
import os
t=sorted(int(x,16) for x in open(os.path.expanduser('~/bltargets.txt')))
frames=[('faulting fn (bl pthread_mutex_lock)',0x4db778),
        ('frame  stack[4]  ret 0x458fec', 0x458fe8),
        ('frame  stack[16] ret 0x30ed84', 0x30ed80),
        ('frame  stack[18] ret 0x33a5e4', 0x33a5e0),
        ('frame  stack[44] ret 0x2a24ac', 0x2a24a8)]
for name,a in frames:
    i=bisect.bisect_right(t,a)-1
    nxt = t[i+1] if i+1 < len(t) else 0
    print('  %-38s addr=0x%x  enclosing=0x%x  (next entry 0x%x)' % (name,a,t[i],nxt))
PY
