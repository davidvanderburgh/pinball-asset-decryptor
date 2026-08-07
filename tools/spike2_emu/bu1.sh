#!/bin/bash
# bu1.sh - the node bus BRING-UP stall.
# 0x1d734c is the enumeration; it runs exactly once per process on its own
# thread and then falls into the service loop 0x1d7d88. In a stalled run it
# never gets out: only fe/f9/fc/fa/f2/f0 are ever sent, never ff and never 0x11.
# Dump it whole, plus the service loop, plus the thread body that owns them.
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

dis 0x1d734c 0x1d7d88 $O/enum.dis          # the enumeration
dis 0x1d7d88 0x1d8400 $O/svc.dis           # the service loop + its ff fault read
dis 0x59ef00 0x59ef60 $O/poll.dis          # 0x59ef30, the bare 00 poll

echo
for t in 1d734c 1d7d88 59ef30 1d8230 1d582c 39cbbc; do
  echo "== callers of 0x$t =="
  grep -aoE "^ *[0-9a-f]+:.*bl[[:space:]]+$t <" "$D" | sed 's/:.*//' | tr -d ' ' | sort -u
done
