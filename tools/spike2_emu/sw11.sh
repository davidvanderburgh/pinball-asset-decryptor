#!/bin/bash
# sw11.sh - the third consumer of the 8 scan bytes.
# 0x1d6d94 calls 0x4e7718(node, buf8) BEFORE 0x1e78f4, and only on the
# PLAYFIELD path (0x1d6d58, the cabinet path, does not call it). The drain's
# only caller, 0x4ec8b8, is in the same module. Dump both.
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

dis 0x4e7700 0x4e7a00 $O/third.dis
dis 0x4ec700 0x4ec9c0 $O/tick.dis

echo
for t in 4e7718 4ec8b8 4ec738 4ec7d8; do
  echo "== callers of 0x$t =="
  grep -aoE "^ *[0-9a-f]+:.*bl[[:space:]]+$t <" "$D" | sed 's/:.*//' | tr -d ' ' | sort -u
done
