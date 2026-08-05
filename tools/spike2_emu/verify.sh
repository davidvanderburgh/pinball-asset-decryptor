#!/bin/bash
cd /home/david
L=gz70.log
./run_game.sh > $L 2>&1
echo "=== validation bar ==="
printf '  ExchangeData errors : %s (want 0)\n'  "$(grep -c ExchangeData $L)"
printf '  Radium warnings     : %s (want 45)\n' "$(grep -c 'Radium Warning' $L)"
printf '  scene opens         : %s (want 194)\n' "$(grep -o 'scene_opens=[0-9]*' $L | head -1 | cut -d= -f2)"
printf '  scenes w/ bytes > 0 : %s (milestone: > 0)\n' "$(awk '/^\[scene\]/ && $2+0>0' $L | wc -l)"
printf '  exceptions thrown   : %s\n' "$(grep -c '\[throw\]' $L)"
printf '  final fault         : %s\n' "$(grep -o 'pc=0x[0-9a-f]* lr=0x[0-9a-f]*' $L | head -1)"
echo "  new numbered fatal  : $(find spike2root/dump/debug_log.txt -newermt '-5 minutes' | wc -l) (0 = none written this run)"
