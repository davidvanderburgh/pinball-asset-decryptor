#!/bin/bash
# shakejob.sh <key> <card> - a mode shakes the cabinet through the game's own shake on a new build (PAD-1555; PAD-474's
# proof, re-made: the job that made SHAKER_PROVEN lived in C:/tmp and is gone).
#
#   PORT=<port>    the port (default: modes/sdk/ports/<key>.port)
#
# A mode file with `shake start 1500 2` is started in a game (tryit.sh start); the shim logs every coil command
# (PAD_COIL_PROBE=1: the shim writes them to the game's own output, the slot's gzwatch.log). Pass: the runtime's `shaker: shake start - N step(s) ... through the game's own shake (setting S)`
# and, after it, the shaker's coil driven on the node bus (`[coildrive] ... node N coil C: pulse/fired`), then OFF.
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: shakejob.sh <key> <card>}" "${2:?usage: shakejob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] || job_fail "no port $PORT"
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$MODES/sdk/prebuilt/mode.so" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" || job_fail "could not stage"
printf 'name SHAKE TEST\ngame_modes stack\nseconds 12\ntrigger 0x1 99\nshots 0x1\naward 100\nshake start 1500 %s\n' "${SHAKE_STRENGTH:-2}" > "$S/mode.cfg"   # SHAKE_STRENGTH=0: a one-power shake
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
export PAD_MODE_SO=/lib/pad_mode.so PAD_COIL_PROBE=1
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
log=$DUMP/mode.log
GZ=${LOG:-$PAD_LOGDIR/gzwatch.log}      # the game's stderr: the shim's [coildrive] lines
job_start_game || job_fail "$JOB_WHY"
job_sleep 3
python3 "$RIG/plunge.py" plunge > /dev/null 2>&1 < /dev/null
job_sleep 3
mark=$(grep -c "" "$GZ")
bash "$MODES/tryit.sh" start 0 > /dev/null 2>&1 < /dev/null
job_wait_log "$log" 'shaker: (shake [0-9]+ ms at|no shake)' 30 || { cp "$log" "$JOB_OUT/mode.log"; job_fail "no shaker line: $(grep -m1 'shaker\|not started' "$log")"; }
job_sleep 4
cp "$log" "$JOB_OUT/mode.log"
tail -n +"$mark" "$GZ" | grep -a '\[coildrive\]' > "$JOB_OUT/coildrive.txt"
said=$(grep -m1 -Eo 'shaker: (shake [0-9]+ ms at|no shake).*' "$log")
grep -Eq 'shaker: shake [0-9]+ ms at [0-9] - ' "$log" || job_fail "$said"
# the shaker's own command: a pulse as long as the shake the runtime asked for (other coils the game fires meanwhile
# are not it - King Kong's posts, Avengers' tower)
total=$(grep -m1 -Eo '[0-9]+ ms of shaking in all' "$log" | grep -Eo '^[0-9]+')
drive=$(awk -v t="${total:-0}" 'match($0, /\[coildrive\] [0-9]+ ms node [0-9]+ coil [0-9]+: pulse [0-9]+\/255 for [0-9]+ ms/) {
            s = substr($0, RSTART, RLENGTH); n = split(s, w, " "); ms = w[n - 1]
            if (ms + 30 >= t && ms <= t + 30) { print s; exit } }' "$JOB_OUT/coildrive.txt")
[ -n "$drive" ] || job_fail "$said; but no coil was driven for ${total:-?} ms on the node bus after it"
off=$(tail -n +"$mark" "$GZ" | grep -a -c '\[coildrive\] .*: OFF')
job_pass "attract=${JOB_ATTRACT_S}s ${said:0:140} | $drive | OFF x$off"
