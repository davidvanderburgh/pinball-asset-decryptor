#!/bin/bash
# nb7.sh - find the per-command bus functions for 0xf9 and 0xfc.
# Small negative constants are built with mvn, never mov: 0xf9 = mvn #6,
# 0xfc = mvn #3, 0xfe = mvn #1. Grepping for #249 or #252 finds nothing.
D=/home/david/game.dis
awk '
/^ *[0-9a-f]+:/ {
  a = $0; sub(/:.*/, "", a); gsub(/ /, "", a); v = strtonum("0x" a)
  if (v < 0x59d000 || v > 0x5a8000) next
  if ($0 ~ /mvn\t[a-z0-9]+, #6$/)  print "F9  " $0
  if ($0 ~ /mvn\t[a-z0-9]+, #3$/)  print "FC  " $0
}' $D
