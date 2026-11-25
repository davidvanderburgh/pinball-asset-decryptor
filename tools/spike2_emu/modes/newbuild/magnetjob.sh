#!/bin/bash
# magnetjob.sh <key> <card> - a mode holds the ball on the magnet on a new build (PAD-1555; PAD-420's magnet_job, re-made).
#
#   SW=<switch id>  the switch of the shot the magnet sits at (the port's `value magnet_shot`; the check's switch list)
#   PORT=<port>     the port (default: modes/sdk/ports/<key>.port)
#
# A mode file with `magnet 2000` is started in a game; the switch is pressed twice, 4 game seconds apart; the shim
# logs every coil command (PAD_COIL_PROBE=1). Pass: the mode's "magnet shot ... holding the ball" line for each press
# and, after the first, the magnet's coil (`text magnet_hold_drive <node> <coil> ...`) driven on the node bus.
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: magnetjob.sh <key> <card>}" "${2:?usage: magnetjob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] && [ -n "${SW:-}" ] || job_fail "no port $PORT or no SW="
coil=$(awk '$1 == "text" && $2 == "magnet_coil" {print $3}' "$PORT")
read -r node out _ < <(awk -v c="${coil}_drive" '$1 == "text" && $2 == c {print $3, $4}' "$PORT")
[ -n "$node" ] || job_fail "the port names no magnet coil drive"
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$MODES/sdk/prebuilt/mode.so" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" || job_fail "could not stage"
printf 'name MAGNET TEST\ngame_modes stack\nseconds 30\ntrigger 0x1 99\nshots 0x1\naward 100\nmagnet 2000\n' > "$S/mode.cfg"
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
bash "$MODES/tryit.sh" start 0 > /dev/null 2>&1 < /dev/null
job_wait_log "$log" 'MAGNET TEST.*(START|started)|START .*MAGNET TEST|"MAGNET TEST"' 20 || true
job_sleep 2
mark=$(grep -c "" "$GZ")
job_press "$SW"
job_sleep 4
job_press "$SW"
job_sleep 3
cp "$log" "$JOB_OUT/mode.log"
grabs=$(grep -c "magnet shot .* - holding the ball" "$log")
[ "$grabs" -ge 1 ] || job_fail "no grab: $(grep -m1 'magnet' "$log")"
drive=$(tail -n +"$mark" "$GZ" | grep -a -m1 -o "\[coildrive\] [0-9]* ms node $node coil $out: [^,]*")
[ -n "$drive" ] || job_fail "$grabs grab(s) said, but node $node coil $out was not driven"
job_pass "attract=${JOB_ATTRACT_S}s $grabs grab(s) on switch $SW; $drive"
