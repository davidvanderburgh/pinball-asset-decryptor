#!/bin/bash
# co1.sh - find the per-command bus function that sends 0x70 (the per-drive
# write), plus 0x86 / 0x14 / 0x41, by scanning the node bus command region for
# the immediate that builds the command byte.
#
# 0x70 = 112 (mov #112), 0x86 = mvn #121? no - 0x86 = 134, built as mov #134.
# Small NEGATIVE constants use mvn; 0x86 and 0x70 are both representable as
# 8-bit rotated immediates so they come out as mov.
D=/home/david/game.dis
awk '
/^ *[0-9a-f]+:/ {
  a = $0; sub(/:.*/, "", a); gsub(/ /, "", a); v = strtonum("0x" a)
  if (v < 0x59d000 || v > 0x5a9000) next
  if ($0 ~ /mov(\.w)?\t[a-z0-9]+, #112/) print "70  " $0
  if ($0 ~ /mov(\.w)?\t[a-z0-9]+, #134/) print "86  " $0
  if ($0 ~ /mov(\.w)?\t[a-z0-9]+, #20$/) print "14  " $0
  if ($0 ~ /mov(\.w)?\t[a-z0-9]+, #65$/) print "41  " $0
  if ($0 ~ /mov(\.w)?\t[a-z0-9]+, #132/) print "84  " $0
  if ($0 ~ /mov(\.w)?\t[a-z0-9]+, #144/) print "90  " $0
  if ($0 ~ /mov(\.w)?\t[a-z0-9]+, #164/) print "a4  " $0
  if ($0 ~ /mov(\.w)?\t[a-z0-9]+, #167/) print "a7  " $0
  if ($0 ~ /mov(\.w)?\t[a-z0-9]+, #77$/) print "4d  " $0
}' $D
