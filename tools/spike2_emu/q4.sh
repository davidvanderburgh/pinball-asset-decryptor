#!/bin/bash
# Q4: the binary keeps .dynsym, and objdump is naming things off it.
# Dump every dynsym with an address, sorted, and show the neighbourhood of each
# frame in the crash stack.
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

$OD -T $G | awk '$1 ~ /^[0-9a-f]{8}$/ && $1 != "00000000" {print $1, $NF}' | sort -u > $HOME/dynsym.txt
echo "dynsyms with addresses: $(wc -l < $HOME/dynsym.txt)"

echo
echo "### SoLoud symbols present ###"
grep -c SoLoud $HOME/dynsym.txt
grep SoLoud $HOME/dynsym.txt | head -60

echo
echo "### nearest preceding dynsym for each crash-stack address ###"
python3 - <<'PY'
import bisect
rows=[]
import os
for line in open(os.path.expanduser('~/dynsym.txt')):
    a,n=line.split()
    rows.append((int(a,16),n))
rows.sort()
addrs=[r[0] for r in rows]
for name,a in [('faulting fn 0x4db74c',0x4db74c),
               ('frame 0x458e98',0x458e98),
               ('caller fn 0x30ed20',0x30ed20),
               ('frame 0x33a1d0',0x33a1d0),
               ('frame 0x2a212c',0x2a212c),
               ('table 0x674f28',0x674f28),
               ('table 0x67af10',0x67af10),
               ('table 0x67b810',0x67b810),
               ('global 0x7b8990',0x7b8990),
               ('global 0x7b9458',0x7b9458)]:
    i=bisect.bisect_right(addrs,a)-1
    j=bisect.bisect_left(addrs,a)
    prev='%s+0x%x'%(rows[i][1],a-rows[i][0]) if i>=0 else '?'
    nxt ='%s-0x%x'%(rows[j][1],rows[j][0]-a) if j<len(rows) else '?'
    print('  %-24s 0x%08x  prev=%-64s next=%s'%(name,a,prev,nxt))
PY
