#!/bin/bash
# sw13.sh - the remaining entry[+22] reader inside the switch module, and the
# small function just before the drain that owns 0x4ec738 / 0x4ec7d8.
. "$(dirname "$0")/padpath.sh"
D=$HOME/game.dis
O=$RIG

dis() {
  awk -v lo=$(printf '%d' $1) -v hi=$(printf '%d' $2) '
  /^ *[0-9a-f]+:/ {
    a = $0; sub(/:.*/, "", a); gsub(/ /, "", a)
    v = strtonum("0x" a)
    if (v >= lo && v <= hi) print
  }' "$D" > "$3"
  echo "$3: $(wc -l < "$3") lines"
}

dis 0x1e7340 0x1e7540 $O/f73b4.dis
