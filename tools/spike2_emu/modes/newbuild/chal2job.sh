#!/bin/bash
# chal2job.sh <key> <card> - a mode in the place of one of the game's challenges on a GamePlayModes build (PAD-1555;
# PAD-619's jobgpm.sh, re-made).
#
#   SO=<object>    built with modes/sdk/gpmset_mode.c (build_mode.sh -o gpm.so mode_file.c gpmset_mode.c)
#   SLOT=<n>       the challenge the mode takes (default 0: the port's challenge_mode_0)
#   PORT=<port>    the port (default: modes/sdk/ports/<key>.port)
#
# A mode file `challenge <n>` (CH TEST, 30 s); in attract the game-play mode index is set to the challenge's
# (gpm.set: the port's `data game_play_modes` + `value game_play_mode_at`), as the start menu's pick sets it; a game
# started. Pass: the runtime's `challenge <n> (...) picked` / `CH TEST START (challenge pick)` - the mode in the
# challenge's place - the evidence CHALLENGE_PROVEN records. CONTROL=1: no mode file, the game's own challenge plays.
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: chal2job.sh <key> <card>}" "${2:?usage: chal2job.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] && [ -f "${SO:-}" ] || job_fail "needs PORT and SO"
n=${SLOT:-0}
at=$(awk '$1 == "data" && $2 == "game_play_modes" {print $3; exit}' "$PORT")
off=$(awk '$1 == "value" && $2 == "game_play_mode_at" {print $3; exit}' "$PORT")
idx=$(awk -v k="challenge_mode_$n" '$1 == "value" && $2 == k {print $3; exit}' "$PORT")
[ -n "$at" ] && [ -n "$off" ] && [ -n "$idx" ] || job_fail "the port names no game_play_modes / game_play_mode_at / challenge_mode_$n"
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$SO" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" || job_fail "could not stage"
if [ "${CONTROL:-0}" = 1 ]; then
    printf 'name IDLE TEST\ngame_modes stack\nseconds 5\ntrigger 0x1 99\nshots 0x1\naward 100\n' > "$S/mode.cfg"
else
    printf 'name CH TEST\ngame_modes stack\nseconds 30\nchallenge %s\nshots 0xffffffff\naward 1000\n' "$n" > "$S/mode.cfg"
fi
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
export PAD_MODE_SO=/lib/pad_mode.so
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
log=$DUMP/mode.log
job_sleep 5
printf '%s %s %s\n' "$at" "$off" "$idx" > "$DUMP/gpm.set"
job_wait_log "$log" 'gpm set: now' 10 || { cp "$log" "$JOB_OUT/mode.log"; job_fail "the instrument did not set the index"; }
set1=$(grep -a -m1 -Eo 'gpm set: the game-play mode at [^ ]+ was [0-9]+' "$log")
job_start_game || job_fail "$JOB_WHY"
job_sleep 3
python3 "$RIG/plunge.py" plunge > /dev/null 2>&1 < /dev/null
job_sleep 15
cp "$log" "$JOB_OUT/mode.log"
picked=$(grep -a -m1 -Eo "challenge $n \([^)]*\)[^;]{0,80}" "$log")
start=$(grep -a -m1 -Eo 'CH TEST START \(challenge pick\)[^;]{0,60}' "$log")
if [ "${CONTROL:-0}" = 1 ]; then
    job_pass "attract=${JOB_ATTRACT_S}s control: $set1 -> $idx; $(grep -a -m1 -Eo 'challenge [0-9]+ [^;]{0,80}' "$log")"
fi
[ -n "$start" ] || job_fail "$set1 -> $idx; ${picked:-no pick line}; no CH TEST START (challenge pick)"
job_pass "attract=${JOB_ATTRACT_S}s $set1 -> $idx; $picked; $start"
