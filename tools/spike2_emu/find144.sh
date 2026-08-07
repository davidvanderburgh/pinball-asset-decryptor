#!/bin/bash
# find144.sh - who writes board[+144]?
#
# 0x39d554 special-cases SLOT 2 when setting board[+4]:
#     if (board[+0] == 2) flags = (halfword at board[+144] != 0) ? 1 : 0;
#     else                flags = 1;
# so node board slot 2 is the only board whose "registered" bit is conditional,
# and it is the last board still producing a Tech Alerts line. Everything else
# is suppressed once (flags & 3) == 3.
#
# The board init at 0x39d3ac..0x39d3d4 zeroes +124 through +143 and deliberately
# stops short of +144, so +144 is written somewhere else - or never.
D=$HOME/game.dis

echo "=== stores to offset 144 (0x90) ==="
grep -nE 'str[bh]?[[:space:]]+r[0-9a-z]+, \[r[0-9a-z]+, #144\]' $D | head -20

echo
echo "=== loads from offset 144 ==="
grep -nE 'ldr[bh]?[[:space:]]+r[0-9a-z]+, \[r[0-9a-z]+, #144\]' $D | head -20

echo
echo "=== any mention of #144 in the node board module 0x39c600-0x39d600 ==="
awk -v lo=$((0x39c600)) -v hi=$((0x39d600)) '
/^ *[0-9a-f]+:/ {
  a = $0; sub(/:.*/, "", a); gsub(/ /, "", a)
  v = strtonum("0x" a)
  if (v >= lo && v <= hi && /#144/) print
}' $D

echo
echo "=== stores to 146 (0x92) and 148 (0x94), the neighbours ==="
grep -nE 'str[bh]?[[:space:]]+r[0-9a-z]+, \[r[0-9a-z]+, #(146|148)\]' $D | head -20
