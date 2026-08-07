#!/bin/bash
# burest.sh - the control for the bring-up fix.
#
# PAD_SW_REST=0 removes the machine-at-rest defaults, so the game latches
# [0x706464] from a coin door it believes is OPEN and bring-up sits in
# 0x1d6fb8's 60 s wait. If that run stalls and the default run does not, the
# diagnosis is proven rather than merely correlated.
. "$(dirname "$0")/padpath.sh"
set -u
for kv in "PAD_SW_REST=1" "PAD_SW_REST=0"; do
  L="gzrest${kv#PAD_SW_REST=}.log"
  bash "$RIG/nbrun.sh" "$L" 115 "$kv" \
      PAD_SW_PEND=60,84 PAD_SW_TAP=60,84 PAD_SW_TAP_AT_S=55 \
      PAD_SW_DUMP=6000 PAD_GL_FRAME_EVERY=3000 PAD_GL_MAX_FRAMES=2 \
      > "$HOME/$L.out" 2>&1
  cp -f "$HOME/shots/"*.png "$HOME/$L.frames" 2>/dev/null || true
  S=$(grep -ac 'TX len=[0-9]* 8.0211' "$HOME/$L" || true)
  F=$(grep -aoE '\[nb\] TX len=[0-9]+ 8[0-9a-f]0[0-9a-f]ff' "$HOME/$L" | wc -l)
  printf '%-14s 0x11=%-7s ff=%-6s  %s\n' "$kv" "$S" "$F" \
     "$( [ "$S" -gt 1000 ] && echo OK || echo '<-- STALLED' )"
done
