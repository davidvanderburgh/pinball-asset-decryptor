#!/bin/bash
# rush_test.sh [shots...] - play one KAIJU RUSH in a LIVE run (item 125).
#
# Needs a run with PAD_MODE_SO=/lib/mode.so (and, for the independent record,
# PAD_TRACE_SO=/lib/padmode.so) and a game in progress (plunge.py game). Pokes the
# maser target three times to start the mode, then each given switch once (default:
# the three powerline targets and both ramps), waits out the 30 s clock, and prints
# the mode's log, what the probe saw it call, and the score peek. A rig action:
# only against a run this session started, under the rig lock.
. "$(dirname "$0")/../padpath.sh"
D=$ROOT/dump
[ $# -gt 0 ] || set -- 78 79 80 73 81
m0=$(wc -l < "$D/mode.log" 2>/dev/null || echo 0)
p0=$(wc -l < "$D/padmode.log" 2>/dev/null || echo 0)
g0=$(grep -ac '\[peek\]' "$D/game.out")
t0=$(date +%s)
poke() { python3 "$RIG/swpoke.py" "$1" 150 > /dev/null 2>&1 || echo "swpoke $1 failed"; sleep 1.2; }
for i in 1 2 3; do poke 48; done
for sw in "$@"; do poke "$sw"; done
left=$((36 - ($(date +%s) - t0)))
[ "$left" -gt 0 ] && sleep "$left"
echo "=== mode.log"
tail -n +$((m0 + 1)) "$D/mode.log"
echo "=== what the probe saw: scores, sound, ball end"
tail -n +$((p0 + 1)) "$D/padmode.log" 2>/dev/null | grep -E '\[(score|sound|ball)\]'
echo "=== score peek (new lines)"
grep -a '\[peek\]' "$D/game.out" | tail -n +$((g0 + 1)) | tail -12
