#!/bin/bash
# disval.sh - disassemble around the two sites that construct the
# "GAME VALIDATION ERROR" strings (found live with PAD_STR_WATCH, because
# nothing in the binary references the message table statically).
D=/home/david/game.dis
LO=${1:-0x4dec00}
HI=${2:-0x4df040}
awk -v lo=$(printf '%d' $LO) -v hi=$(printf '%d' $HI) '
/^ *[0-9a-f]+:/ {
  a = $0; sub(/:.*/, "", a); gsub(/ /, "", a)
  v = strtonum("0x" a)
  if (v >= lo && v <= hi) print
}' $D
