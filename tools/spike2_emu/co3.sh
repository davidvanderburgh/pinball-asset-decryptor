#!/bin/bash
# co3.sh - every global address a VA range builds with movw/movt, counted.
# The driver (coil) subsystem's own tables show up as the ones it touches most.
D=/home/david/game.dis
LO=${1:-0x250000}
HI=${2:-0x256000}
awk -v lo=$(printf '%d' $LO) -v hi=$(printf '%d' $HI) '
/^ *[0-9a-f]+:/ {
  a = $0; sub(/:.*/, "", a); gsub(/ /, "", a); v = strtonum("0x" a)
  if (v < lo || v > hi) next
  line = $0
  if (line ~ /movw\t/) { split(line, t, "#"); split(t[2], u, "\t"); lowv[$0] = 0
      reg = line; sub(/.*movw\t/, "", reg); sub(/,.*/, "", reg)
      val = t[2]; sub(/[^0-9].*/, "", val); lw[reg] = val + 0; next }
  if (line ~ /movt\t/) { reg = line; sub(/.*movt\t/, "", reg); sub(/,.*/, "", reg)
      split(line, t, "#"); val = t[2]; sub(/[^0-9].*/, "", val)
      if (reg in lw) printf "0x%06x\n", (val + 0) * 65536 + lw[reg] }
}' $D | sort | uniq -c | sort -rn | head -30
