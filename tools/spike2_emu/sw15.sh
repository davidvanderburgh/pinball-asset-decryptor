#!/bin/bash
# sw15.sh - what sets bit 4 (0x10) of a ball device's flag word at (u16)[obj+20]?
# Bit 0 is MALFUNCTION (set at 0x395d58, cleared at 0x395c1c). The verification
# run reads 0x0010 on Auto Plunger and Scoop, which is NOT the malfunction bit,
# so name it rather than guess.
. "$(dirname "$0")/padpath.sh"
D=$HOME/game.dis
awk -v lo=$(printf '%d' 0x395300) -v hi=$(printf '%d' 0x396200) '
/^ *[0-9a-f]+:/ {
  a = $0; sub(/:.*/, "", a); gsub(/ /, "", a)
  v = strtonum("0x" a)
  if (v >= lo && v <= hi) print
}' "$D" > $RIG/dev.dis
echo "dev.dis: $(wc -l < $RIG/dev.dis) lines"
echo "== halfword stores into +20 in the device module =="
grep -aE 'strh.*\[r[0-9a-z]+, #20\]' $RIG/dev.dis
echo "== orr/bic with #16 in the device module =="
grep -aE '(orr|bic).*#16$|(orr|bic).*#16\b' $RIG/dev.dis
echo "== context around every +20 halfword access =="
grep -naE '(ldrh|strh).*\[r[0-9a-z]+, #20\]' $RIG/dev.dis | head -20
