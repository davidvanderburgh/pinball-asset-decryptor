#!/bin/bash
# padmode_trig.sh <trigger> <content> [wait_s] - drive a LIVE padmode.so run (item 125).
#
# Drops $ROOT/dump/padmode.<trigger> (start|stop|shot|score|sound, see padmode.c),
# waits, and prints the probe lines and PAD_PEEK changes that followed. A rig action:
# only against a run this session started, under the rig lock.
#   padmode_trig.sh start 23            # force tesla strike
#   padmode_trig.sh shot "23 0x400000"  # inject a shot into mode 23's v[15]
#   padmode_trig.sh score 12345         # score_add(current player, 12345)
. "$(dirname "$0")/../padpath.sh"
D=$ROOT/dump
LOG=$D/padmode.log
n=$(wc -l < "$LOG")
p=$(grep -ac '\[peek\]' "$D/game.out")
printf '%s\n' "$2" > "$D/padmode.$1"
sleep "${3:-4}"
tail -n +$((n + 1)) "$LOG"
echo "--- peek (new lines)"
grep -a '\[peek\]' "$D/game.out" | tail -n +$((p + 1)) | tail -8
if [ -e "$D/padmode.$1" ]; then echo "(trigger file still present - not consumed)"; fi
