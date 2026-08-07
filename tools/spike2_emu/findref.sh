#!/bin/bash
# Resolve movw/movt immediate pairs per register and report the sites that
# build the given absolute addresses. String refs in this binary exist ONLY as
# movw/movt pairs, so this is the only way to find them.
D=$HOME/game.dis
TARGETS="$*"

awk -v targets="$TARGETS" '
BEGIN { n = split(targets, t, " "); for (i = 1; i <= n; i++) want[strtonum(t[i])] = 1 }
/^ *[0-9a-f]+:/ {
  addr = $0; sub(/:.*/, "", addr); gsub(/ /, "", addr)
  if (match($0, /movw\t[a-z0-9]+, #[0-9]+/)) {
    s = substr($0, RSTART, RLENGTH)
    split(s, p, "\t"); split(p[2], q, ",")
    reg = q[1]; v = p[2]; sub(/.*#/, "", v)
    lo[reg] = v + 0; loat[reg] = addr
  }
  if (match($0, /movt\t[a-z0-9]+, #[0-9]+/)) {
    s = substr($0, RSTART, RLENGTH)
    split(s, p, "\t"); split(p[2], q, ",")
    reg = q[1]; v = p[2]; sub(/.*#/, "", v)
    full = (v + 0) * 65536 + lo[reg]
    if (full in want)
      printf "0x%x  built at %s (movw at %s) reg %s\n", full, addr, loat[reg], reg
  }
}
' $D
