#!/bin/bash
# callers.sh <hexaddr> [...] - list every `bl <addr>` site in game.dis.
#
# Written as a file on purpose: `wsl -e bash -c "...$t..."` loses the variable
# to the outer shell, which silently produced "callers of <empty>" three times
# in a row and looked like three functions sharing a caller set.
D=/home/david/game.dis
for t in "$@"; do
  t=${t#0x}
  echo "== callers of 0x$t =="
  grep -aoE "^ *[0-9a-f]+:.*bl[[:space:]]+$t <" "$D" | sed 's/:.*//' | tr -d ' ' | sort -u
done
