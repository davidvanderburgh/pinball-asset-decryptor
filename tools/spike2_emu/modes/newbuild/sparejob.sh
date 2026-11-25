#!/bin/bash
# sparejob.sh <key> <card> - a spare switch input and a spare driver output on a new build (PAD-1555; PAD-826's
# spare_sweep_job, re-made).
#
#   SO=<object>    built with modes/sdk/spare_sweep_mode.c (build_mode.sh -o spare.so spare_sweep_mode.c)
#   PORT=<port>    the port (default: modes/sdk/ports/<key>.port)
#
# The instrument names its input and output (`sweep: input N:B output N:O`); in a game the input is closed through
# /dump/spare_in (pullup: open inputs read 1). Pass: the instrument's `sweep: pulse N:O -> 1` and the output on the
# node bus, `[coildrive] ... node N coil O: pulse 200/255 for 30 ms` (PAD_COIL_PROBE=1, the slot's gzwatch.log).
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: sparejob.sh <key> <card>}" "${2:?usage: sparejob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] && [ -f "${SO:-}" ] || job_fail "needs PORT and SO"
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$SO" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" || job_fail "could not stage"
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
export PAD_MODE_SO=/lib/pad_mode.so PAD_COIL_PROBE=1
echo pullup > "$DUMP/spare_in"
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
log=$DUMP/mode.log
GZ=${LOG:-$PAD_LOGDIR/gzwatch.log}
job_start_game || job_fail "$JOB_WHY"
job_sleep 3
python3 "$RIG/plunge.py" plunge > /dev/null 2>&1 < /dev/null
job_wait_log "$log" 'sweep: input [0-9]+:[0-9]+ output' 40 || { cp "$log" "$JOB_OUT/mode.log"; job_fail "the instrument named no spare input: $(grep -a -m1 'spare' "$log" | cut -c1-140)"; }
read -r inode ibit onode oout < <(grep -a -m1 -Eo 'sweep: input [0-9]+:[0-9]+ output [0-9]+:[0-9]+' "$log" | sed 's/sweep: input //; s/ output / /; s/:/ /g')
mark=$(grep -c "" "$GZ")
printf 'pullup\n%s %s 0\n' "$inode" "$ibit" > "$DUMP/spare_in"
job_sleep 2
printf 'pullup\n%s %s 1\n' "$inode" "$ibit" > "$DUMP/spare_in"
job_sleep 3
cp "$log" "$JOB_OUT/mode.log"
pulse=$(grep -a -m1 -Eo 'sweep: pulse [0-9]+:[0-9]+ -> -?[0-9]+' "$log")
drive=$(tail -n +"$mark" "$GZ" | grep -a -m1 -Eo "\[coildrive\] [0-9]+ ms node $onode coil $oout: pulse 200/255 for 30 ms")
echo "$pulse" | grep -q -- '-> 1$' || job_fail "input $inode:$ibit, output $onode:$oout: ${pulse:-no pulse - the close of the input was not seen}"
[ -n "$drive" ] || job_fail "$pulse, but node $onode coil $oout was not driven"
job_pass "attract=${JOB_ATTRACT_S}s input $inode:$ibit closed -> $pulse; $drive"
