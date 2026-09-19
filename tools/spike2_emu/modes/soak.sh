#!/bin/bash
# soak.sh [minutes] - keep KAIJU RUSH cycling in a LIVE run: item 125's soak.
#
# The acceptance: "a 10-minute soak with no SEGV and alive.sh 0" after. Every ~45 s:
# keep a game going (attract -> plunge.py game; otherwise plunge.py plunge, which
# launches only a ball the game already served), start the mode (mode.start), play
# the powerline targets and both ramps, and tick the counters. Needs a run with
# PAD_MODE_SO=/lib/mode.so and PAD_PEEK carrying the mode mask, e.g.
#   PAD_PEEK=0x7e4968:8,0x7aba5a:2
# (0x7aba5a is global_mode_mask; bit 0x10 = attract). A rig action, under the lock.
# At the end: cycles, mode starts/ends, new [segv] lines, and whether the guest is up.
. "$(dirname "$0")/../padpath.sh"
D=$ROOT/dump
MIN=${1:-10}
t_end=$(( $(date +%s) + MIN * 60 ))
segv0=$(grep -ac '\[segv\] pc' "$D/game.out")
sig0=$(grep -ac 'uncaught target signal' "$D/game.out")
m0=$(wc -l < "$D/mode.log")
cycles=0 games=0
poke() { python3 "$RIG/swpoke.py" "$1" 150 > /dev/null 2>&1; sleep 1.4; }
mask_now() {
  # "[peek] t=... 0x007aba5a: lo hi" -> the u16 (shell arithmetic: Ubuntu's awk is
  # mawk, which has no strtonum)
  local l
  l=$(grep -a '\[peek\] .* 0x007aba5a:' "$D/game.out" | tail -1)
  [ -n "$l" ] || return 0
  set -- $l
  echo $(( 0x$5 * 256 + 0x$4 ))
}
while [ "$(date +%s)" -lt "$t_end" ]; do
  t_cycle=$(date +%s)
  mask=$(mask_now)
  if [ -z "$mask" ] || [ $(( ${mask:-16} & 16 )) -ne 0 ]; then
    python3 "$RIG/plunge.py" game > /dev/null 2>&1
    games=$((games + 1))
    sleep 8
  else
    python3 "$RIG/plunge.py" plunge > /dev/null 2>&1
    sleep 2
  fi
  echo 1 > "$D/mode.start"
  sleep 2
  for sw in 78 79 80 73 81; do poke "$sw"; done
  cycles=$((cycles + 1))
  if ! pgrep -x game > /dev/null; then echo "GUEST GONE after $cycles cycles"; break; fi
  left=$(( 45 - ($(date +%s) - t_cycle) ))
  [ "$left" -gt 0 ] && sleep "$left"
  echo "cycle $cycles  mask=$mask  games started=$games  $(tail -n +$((m0 + 1)) "$D/mode.log" | grep -c 'KAIJU RUSH START') starts / $(tail -n +$((m0 + 1)) "$D/mode.log" | grep -c 'KAIJU RUSH END') ends"
done
echo "=== soak: $MIN min, $cycles cycles, $games games started"
tail -n +$((m0 + 1)) "$D/mode.log" | grep -E 'START|END' | awk '{ $1=""; print }' | sort | uniq -c | sort -rn | head -12
echo "new [segv] lines: $(( $(grep -ac '\[segv\] pc' "$D/game.out") - segv0 )), new fatal signals: $(( $(grep -ac 'uncaught target signal' "$D/game.out") - sig0 ))"
pgrep -x game > /dev/null && echo "guest still up" || echo "GUEST NOT RUNNING"
