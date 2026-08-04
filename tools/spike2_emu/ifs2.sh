#!/bin/bash
cd /home/david
L=${1:-gz55.log}
echo "=== ifstream ctor calls: total $(grep -c '\[ifs\]' "$L") ==="
echo "auto_loaded  : $(grep '\[ifs\]' "$L" | grep -c auto_loaded)"
echo "demand_loaded: $(grep '\[ifs\]' "$L" | grep -c demand_loaded)"
echo
echo "=== any with rdstate != 0 ==="
grep '\[ifs\]' "$L" | grep -v 'rdstate=0 ' | head -10
echo "(count: $(grep '\[ifs\]' "$L" | grep -vc 'rdstate=0 '))"
echo
echo "=== distinct mode/rdstate combos ==="
grep -o 'mode=[0-9]* rdstate=[0-9]*' "$L" | sort | uniq -c
echo
echo "=== the scene that owns the missing elements ==="
grep '9d57875196c613785a1eee010c55223a0f1aa821' "$L" | head -5
