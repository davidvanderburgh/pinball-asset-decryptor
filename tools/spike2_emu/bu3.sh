#!/bin/bash
# bu3.sh - the unbounded wait at the END of bring-up.
#
#   1d7750  bl usleep(100000)
#   1d7760  bl 0x3ba5e4(18, 0x6fa618)
#   1d7764  cmp r0, #0
#   1d7770  bne 1d7750          <- loops FOREVER while non-zero
#
# It sits just before 1d77bc (mov r4,#1) and the success return, so a guest
# stuck here has finished every identity exchange and still never starts the
# service loop: no ff, no 0x11, no scan gate. That is the stall exactly.
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

dis 0x3ba5e4 0x3ba7c0 $O/wait18.dis

echo "== who else calls 0x3ba5e4 =="
grep -aoE "^ *[0-9a-f]+:.*bl[[:space:]]+3ba5e4 <" "$D" | sed 's/:.*//' | tr -d ' ' | sort -u

echo "== what lives at VA 0x6fa618 (RW: file = VA - 0x10000) =="
G=$ROOT/games/godzilla_pro/game
python3 - "$G" <<'EOF'
import sys, struct
g = open(sys.argv[1], 'rb').read()
def rd(va, n=32):
    off = va - 0x10000 if va >= 0x6f52c0 else va - 0x8000
    return g[off:off+n]
w = struct.unpack('<8I', rd(0x6fa618, 32))
print('words at 0x6fa618:', ' '.join('%08x' % x for x in w))
for x in w[:4]:
    if 0x8000 <= x < 0x800000:
        off = x - 0x8000
        s = g[off:off+64].split(b'\0')[0]
        print('  0x%08x -> %r' % (x, s[:60]))
EOF
