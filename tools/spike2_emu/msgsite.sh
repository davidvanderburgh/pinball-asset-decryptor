#!/bin/bash
# msgsite.sh - the six "GAME VALIDATION ERROR #N UPDATE SD CARD" messages are
# rows 151..156 of the 302-row message table at 0x752658, and nothing in .text
# builds the table address with movw/movt or a literal pool, so the rows must be
# reached by index. Find code windows that mention several of 151..156 as
# immediates - that is the function that decides which one to raise.
D=$HOME/game.dis
awk '
/^ *[0-9a-f]+:/ {
  addr = $0; sub(/:.*/, "", addr); gsub(/ /, "", addr)
  a = strtonum("0x" addr)
  while (match($0, /#1(5[1-6])\b/)) {
    v = substr($0, RSTART + 1, RLENGTH - 1) + 0
    hit[n] = a; val[n] = v; n++
    $0 = substr($0, RSTART + RLENGTH)
  }
}
END {
  for (i = 0; i < n; i++) {
    delete seen; c = 0
    for (j = i; j < n && hit[j] - hit[i] < 0x400; j++)
      if (!(val[j] in seen)) { seen[val[j]] = 1; c++ }
    if (c >= 4) printf "0x%08x .. 0x%08x : %d distinct of 151..156\n", hit[i], hit[j-1], c
  }
}
' $D | head -20
