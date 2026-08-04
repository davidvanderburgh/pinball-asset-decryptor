#!/bin/bash
# burepeat.sh <n> - run nbrun.sh n times and report, per run, the two numbers
# that say whether node bus bring-up completed. The stall this is testing for
# hit 7 of 11 runs, so a single pass proves nothing; three in a row is ~5%.
#
# Never uses `timeout` - nbrun.sh -> runbridge.sh already setsids the children
# and kills the whole process group itself.
set -u
N=${1:-3}
for i in $(seq 1 "$N"); do
  L="gzr$i.log"
  bash /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/nbrun.sh "$L" 115 \
      PAD_SW_PEND=60,84 PAD_SW_TAP=60,84 PAD_SW_TAP_AT_S=55 \
      PAD_SW_DUMP=6000 PAD_GL_FRAME_EVERY=6000 PAD_GL_MAX_FRAMES=1 \
      > "/home/david/$L.out" 2>&1
  S=$(grep -ac 'TX len=[0-9]* 8.0211' "/home/david/$L" || true)
  F=$(grep -aoE '\[nb\] TX len=[0-9]+ 8[0-9a-f]0[0-9a-f]ff' "/home/david/$L" | wc -l)
  P=$(grep -ac '\[swpend\]' "/home/david/$L" || true)
  A=$(pgrep -c -x game 2>/dev/null); A=${A:-0}
  H=$(pgrep -c -x padglhost 2>/dev/null); H=${H:-0}
  printf 'run %d  0x11=%-7s ff=%-6s swpend=%-4s leftover game=%s host=%s  %s\n' \
     "$i" "$S" "$F" "$P" "$A" "$H" \
     "$( [ "$S" -gt 1000 ] && echo OK || echo '<-- STALLED' )"
done
