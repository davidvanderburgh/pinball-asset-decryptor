#!/bin/bash
# sw12.sh - the rest of the tick's switch work.
# 0x4605e8 runs immediately BEFORE the drain in the game tick at 0x4ec828, and
# 0x1e6860 is called BY the drain for every entry with a non-zero id. Either
# could be re-arming entry[+22].
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

dis 0x4605e8 0x4606e0 $O/pretick.dis
dis 0x1e6800 0x1e6900 $O/f6860.dis
dis 0x1e6d90 0x1e6e00 $O/reader.dis

echo
echo "== every strh into +22 anywhere in .text (the pending counter) =="
grep -aE 'strh.*\[r[0-9a-z]+, #22\]' "$D" | head -40
echo
echo "== every ldrh of +22 =="
grep -aE 'ldrh.*\[r[0-9a-z]+, #22\]' "$D" | head -40
