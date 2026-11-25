#!/bin/bash
# scoopjob.sh <key> <card> - a mode holds the ball in the scoop on a new build (PAD-1555; PAD-420's scoop_job, re-made).
#
#   SW=<switch id>  the scoop's switch (the earlier proof's: King Kong's KONG CAVE VUK 49, Metallica's RT EJECT OPTO 57)
#   PORT=<port>     the port (default: modes/sdk/ports/<key>.port)
#
# A mode with `scoop_hold 4000` is started in a game; the scoop's switch is held closed (a ball settled there) until
# the game kicks. Pass: the runtime's `scoop: a ball settled - holding it 4000 ms`, `scoop: let go after <ms>` with
# <ms> of at least 3900, and a coil fired (the game's kick) after the let-go (PAD_COIL_PROBE=1, the slot's gzwatch.log).
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: scoopjob.sh <key> <card>}" "${2:?usage: scoopjob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] && [ -n "${SW:-}" ] || job_fail "needs PORT and SW"
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$MODES/sdk/prebuilt/mode.so" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" || job_fail "could not stage"
printf 'name SCOOP TEST\ngame_modes stack\nseconds 30\ntrigger 0x1 99\nshots 0x1\naward 100\nscoop_hold 4000\n' > "$S/mode.cfg"
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
export PAD_MODE_SO=/lib/pad_mode.so PAD_COIL_PROBE=1
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
log=$DUMP/mode.log
GZ=${LOG:-$PAD_LOGDIR/gzwatch.log}
job_start_game || job_fail "$JOB_WHY"
job_sleep 3
python3 "$RIG/plunge.py" plunge > /dev/null 2>&1 < /dev/null
job_sleep 20
bash "$MODES/tryit.sh" start 0 > /dev/null 2>&1 < /dev/null
job_wait_log "$log" 'SCOOP TEST START' 10 || { cp "$log" "$JOB_OUT/mode.log"; job_fail "the mode did not start"; }
job_sleep 2
mark=$(grep -c "" "$GZ")
job_press "$SW" 8000                                   # the ball sits in the scoop until the game kicks it out
job_wait_log "$log" 'scoop: let go after' 12 || true
job_sleep 2
cp "$log" "$JOB_OUT/mode.log"
tail -n +"$mark" "$GZ" | grep -a '\[coildrive\]' > "$JOB_OUT/coildrive.txt"
held=$(grep -a -m1 -Eo 'scoop: a ball settled - holding it [0-9]+ ms' "$log")
gone=$(grep -a -m1 -Eo 'scoop: let go after [0-9]+ ms \([^)]*\)' "$log")
ms=$(grep -Eo 'after [0-9]+' <<<"$gone" | grep -Eo '[0-9]+')
kick=$(grep -a -m1 -Eo '\[coildrive\] [0-9]+ ms node 8 coil [0-9]+: pulse [0-9]+/255 for [0-9]+ ms' "$JOB_OUT/coildrive.txt")
[ -n "$held" ] || job_fail "no ball settled for the mode: $(grep -a 'scoop:' "$log" | tail -1 | cut -c1-140)"
[ "${ms:-0}" -ge 3900 ] || job_fail "$held; ${gone:-never let go}"
job_pass "attract=${JOB_ATTRACT_S}s $held; $gone; the kick: ${kick:-no node 8 pulse logged}"
