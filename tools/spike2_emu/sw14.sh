#!/bin/bash
# sw14.sh - the 0x11 switch read, both halves.
# [swpend] shows NodeRec.cur[] carrying the INVERSE of the bit the shim put on
# the wire for node 8 bit 25, while node 9 bit 28 round-trips correctly. That
# is a per-byte XOR difference, i.e. the shim and the game disagree about the
# obfuscation key schedule. Read the game's own deobfuscator rather than fit a
# rotation to two data points.
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

dis 0x59ef60 0x59f120 $O/swread.dis
