#!/bin/bash
# clipjob.sh <key> <card> - a mode's clip comes back after the game's, where it would be by then (PAD-530/725), on a
# new build (PAD-1555: the November 2026 builds moved the video surface's seek / duration / position).
#
#   SO=<object>    a mode object built with modes/sdk/clipback_test_mode.c (build_mode.sh -o clipback.so ...)
#   PORT=<port>    the port (default: modes/sdk/ports/<key>.port)
#
# The clips the game asks for are logged (cliplog.on: the clip census); in a game two of them are taken from that log: the first is played as
# the instrument mode's clip, CUT_S (2) game seconds on, the second is put on as the game's. Pass: the runtime puts the mode's
# clip back at W ms of a length it read (duration), and a second on it plays at P ms with P at or after W and within 1600 ms of it (a busy rig plays video slower than its game clock;
# a seek that did not take plays from 0)
# (the seek took and the position reads right).
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: clipjob.sh <key> <card>}" "${2:?usage: clipjob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "${SO:-}" ] || job_fail "no instrument object (SO=)"
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$SO" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" || job_fail "could not stage"
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
export PAD_MODE_SO=/lib/pad_mode.so
: > "$DUMP/cliplog.on"                 # the clip census (PAD-723) reads it at start-up
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
log=$DUMP/mode.log
grep -q "clip: a mode's clip comes back" "$log" || { cp "$log" "$JOB_OUT/mode.log"; job_fail "the runtime did not arm the clip's return: $(grep -m1 'clip' "$log")"; }
grep -q "mine .*clip 0" "$log" && job_fail "the bank has no clip by that name"
job_start_game || job_fail "$JOB_WHY"
job_sleep 2
python3 "$RIG/plunge.py" plunge > /dev/null 2>&1 < /dev/null
job_wait_log "$log" 'clip census: "[^"]*" asked for \(the bank' 90 || true
job_sleep 20
# the clips the game asked for by name (the census), those on the video bank's own surface first
names=$( { grep -o 'clip census: "[^"]*" asked for (the bank[^)]*' "$log"; grep -o 'clip census: "[^"]*" asked for' "$log"; }          | sed 's/^clip census: "//; s/" asked for.*//' | awk 'NF && !seen[$0]++' | head -2)
mine=$(sed -n 1p <<<"$names")
game=$(sed -n 2p <<<"$names")
[ -n "$mine" ] || { cp "$log" "$JOB_OUT/mode.log"; job_fail "the game set no clip on the bank's surface to borrow"; }
[ -n "$game" ] || game=$mine
job_say "mode's clip \"$mine\", the game's \"$game\""
printf '%s' "$mine" > "$DUMP/clipback.mine"
job_sleep "${CUT_S:-2}"
printf '%s' "$game" > "$DUMP/clipback.game"
job_wait_log "$log" 'clip: ".*" plays at [0-9]+ ms, 1 s after it was put back at' 90
cp "$log" "$JOB_OUT/mode.log"
job_shot "$JOB_OUT/end.png"
back=$(grep -o 'is back on the surface at [0-9]* ms of [0-9]*' "$log" | head -1)
line=$(grep -o 'plays at [0-9]* ms, 1 s after it was put back at [0-9]* ms' "$log" | head -1)
[ -n "$back" ] || job_fail "the mode's clip never came back: $(grep 'clip' "$log" | tail -1)"
len=${back##* of }
p=$(sed 's/plays at \([0-9]*\) ms.*/\1/' <<<"$line")
w=$(sed 's/.*put back at \([0-9]*\) ms/\1/' <<<"$line")
[ -n "$line" ] || job_fail "back ($back) but no position a second on"
d=$(( p - w ))
[ "$len" -gt 0 ] && [ "$d" -ge 0 ] && [ "$d" -le 1600 ] || job_fail "$back; then $line (d=${d} ms)"
job_pass "attract=${JOB_ATTRACT_S}s $back ms; $line (+${d} ms)"
