#!/bin/bash
# fnstart.sh <hexaddr> [...] - the largest `bl`/`blx` target <= addr, i.e. the
# most likely start of the function containing it.
#
# Caveat from the handoff, still true: this FAILS inside 0x2a4b24..0x33a030,
# a 610 KB region with no bl targets at all because everything there is
# dispatched indirectly through data tables.
D=$HOME/game.dis
T=$HOME/bltargets.txt
if [ ! -s "$T" ]; then
  grep -aoE 'bl[x]?[[:space:]]+[0-9a-f]+ <' "$D" \
    | grep -aoE '[0-9a-f]+ <' | tr -d ' <' | sort -u > "$T"
fi
for a in "$@"; do
  a=${a#0x}
  printf '%s -> ' "0x$a"
  awk -v t="$a" '
    BEGIN { tv = strtonum("0x" t); best = "" }
    { v = strtonum("0x" $1); if (v <= tv && v > bestv) { bestv = v; best = $1 } }
    END { printf "0x%s\n", best }' "$T"
done
