#!/bin/bash
# servejob.sh <key> <card> - the music a stock game asks for at ball 1's serve, for a port's `value serve_music`
# (PAD-1555; PAD-1449 round 4's measure: "request 66, 7 ms into a stock game ... emulator sound log").
#
#   PORT=<port>    the port (default: modes/sdk/ports/<key>.port)
#
# The runtime with the card's port and no mode (an idle one) and /dump/soundlog.on (PAD-1071's sound log: `[pad] sound
# <id> <n>` in mode.log for every request); a stock game started; the requests from the Start on are kept in
# $JOB_OUT/sounds.txt with the runtime's ball-start lines. Pass: requests were logged (read them against the controls:
# King Kong 124, Metallica 65).
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: servejob.sh <key> <card>}" "${2:?usage: servejob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] || job_fail "no port $PORT"
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$MODES/sdk/prebuilt/mode.so" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" || job_fail "could not stage"
printf 'name IDLE TEST\ngame_modes stack\nseconds 5\ntrigger 0x1 99\nshots 0x1\naward 100\n' > "$S/mode.cfg"
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
: > "$DUMP/soundlog.on"
export PAD_MODE_SO=/lib/pad_mode.so PAD_SOUNDLOG=1      # soundlog.sh keeps /dump/soundlog.on only with it
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
log=$DUMP/mode.log
job_sleep 5
mark=$(grep -c "" "$log")
job_start_game || job_fail "$JOB_WHY"
job_sleep 12
cp "$log" "$JOB_OUT/mode.log"
tail -n +"$mark" "$log" | grep -a -E '\[pad\] sound [0-9]+ [0-9]+$|ball start|serve|game start' | head -60 > "$JOB_OUT/sounds.txt"
n=$(grep -c '\[pad\] sound ' "$JOB_OUT/sounds.txt")
[ "$n" -gt 0 ] || job_fail "no sound request logged from the Start on"
job_pass "attract=${JOB_ATTRACT_S}s $n request(s): $(grep -a -Eo 'sound [0-9]+' "$JOB_OUT/sounds.txt" | awk '{print $2}' | head -14 | tr '\n' ' ')"
