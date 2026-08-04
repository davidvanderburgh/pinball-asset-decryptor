#!/bin/bash
# bu2.sh - the bring-up's "are we done yet" test and the enumerator it waits on.
# Loop A at 0x1d73e4 runs 0x1d6ee8 (enumerate) then 0x1d6c54 (done?) up to 30
# times. A stalled run is still in that loop when the run ends: it never reaches
# the ff poll at 0x1d7630, so the per-node scan gate at 0x7a908c+276+node is
# never written and no 0x11 is ever sent.
D=/home/david/game.dis
O=/mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu

dis() {
  awk -v lo=$(printf '%d' $1) -v hi=$(printf '%d' $2) '
  /^ *[0-9a-f]+:/ {
    a = $0; sub(/:.*/, "", a); gsub(/ /, "", a)
    v = strtonum("0x" a)
    if (v >= lo && v <= hi) print
  }' "$D" > "$3"
  echo "$3: $(wc -l < "$3") lines"
}

dis 0x1d6c54 0x1d6d58 $O/done.dis      # 0x1d6c54  "is enumeration complete?"
dis 0x1d6ee8 0x1d6fb8 $O/walk.dis      # 0x1d6ee8  the 00-poll discovery walk
dis 0x1d6fb8 0x1d7050 $O/reset.dis     # 0x1d6fb8  called before each retry
