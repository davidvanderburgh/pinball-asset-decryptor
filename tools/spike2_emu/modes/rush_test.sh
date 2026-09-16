#!/bin/bash
# rush_test.sh [shots...] - play one mode in a LIVE run (items 125, 126).
#
# Needs a run with PAD_MODE_SO=/lib/mode.so (and, for the independent record,
# PAD_TRACE_SO=/lib/padmode.so) and a game in progress (plunge.py game). Starts the
# mode the way the mode file says to, then pokes each given switch once (default: the
# three powerline targets and both ramps), waits out the mode's own clock, and prints
# the mode's log, what the probe saw it call, and the score peek. A rig action: only
# against a run this session started, under the rig lock.
#
# ITEM 126: the rules are DATA, so this reads them instead of hard-coding them. The
# old version poked switch 48 three times and waited 36 s because KAIJU RUSH's maser
# trigger and 30 s clock were compiled in; a mode file can say anything.
. "$(dirname "$0")/../padpath.sh"
D=$ROOT/dump
CFG=${PAD_MODE_CFG:-$D/mode.cfg}
[ $# -gt 0 ] || set -- 78 79 80 73 81

# What the running mode says about itself. A trigger the file gives as a shot MASK
# cannot be poked directly - swpoke speaks switch ids - so the start goes through the
# mode.start trigger file, which is what soak.sh does too.
secs=$(grep -m1 '^seconds' "$CFG" 2>/dev/null | awk '{ print $2 }')
name=$(grep -m1 '^name' "$CFG" 2>/dev/null | cut -d' ' -f2- | sed 's/^ *//')
: "${secs:=30}"
echo "=== mode \"${name:-unknown}\": ${secs} s, from $CFG"

m0=$(wc -l < "$D/mode.log" 2>/dev/null || echo 0)
p0=$(wc -l < "$D/padmode.log" 2>/dev/null || echo 0)
g0=$(grep -ac '\[peek\]' "$D/game.out")
t0=$(date +%s)
poke() { python3 "$RIG/swpoke.py" "$1" 150 > /dev/null 2>&1 || echo "swpoke $1 failed"; sleep 1.2; }
echo 1 > "$D/mode.start"
sleep 2
for sw in "$@"; do poke "$sw"; done
left=$(( secs + 6 - ($(date +%s) - t0) ))
[ "$left" -gt 0 ] && sleep "$left"
echo "=== mode.log"
tail -n +$((m0 + 1)) "$D/mode.log"
echo "=== what the probe saw: scores, sound, ball end"
tail -n +$((p0 + 1)) "$D/padmode.log" 2>/dev/null | grep -E '\[(score|sound|ball)\]'
echo "=== score peek (new lines)"
grep -a '\[peek\]' "$D/game.out" | tail -n +$((g0 + 1)) | tail -12
