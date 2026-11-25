#!/bin/bash
# lightsjob.sh <key> <card> - a mode's light_all on a new build (PAD-1555; item 164's proof, re-made).
#
#   PORT=<port>    the port (default: modes/sdk/ports/<key>.port)
#
# In a game a mode with `light_all ff00ff solid` runs 12 s; the shim's LED view (dump/padled) is copied before it, 3 s
# and 8 s into it, and 4 s after its END. Pass (newbuild/lightcheck.py): every insert the port names that the rig's
# led_io.txt places is magenta (R >= 200, G <= 40, B >= 200; a title with no RGB insert: its single ones at >= 200) in
# both copies while the mode ran, and not before or after beyond the game's own lights.
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: lightsjob.sh <key> <card>}" "${2:?usage: lightsjob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] || job_fail "no port $PORT"
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$MODES/sdk/prebuilt/mode.so" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" || job_fail "could not stage"
printf 'name LIGHT TEST\ngame_modes stack\nseconds 12\ntrigger 0x1 99\nshots 0x1\naward 100\nlight_all ff00ff solid\n' > "$S/mode.cfg"
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
export PAD_MODE_SO=/lib/pad_mode.so
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
log=$DUMP/mode.log
job_start_game || job_fail "$JOB_WHY"
job_sleep 3
python3 "$RIG/plunge.py" plunge > /dev/null 2>&1 < /dev/null
job_sleep 10
cp "$DUMP/padled" "$JOB_OUT/led_before.bin"
bash "$MODES/tryit.sh" start 0 > /dev/null 2>&1 < /dev/null
job_wait_log "$log" 'LIGHT TEST START' 10 || { cp "$log" "$JOB_OUT/mode.log"; job_fail "the mode did not start"; }
job_sleep 3; cp "$DUMP/padled" "$JOB_OUT/led_during1.bin"
job_sleep 5; cp "$DUMP/padled" "$JOB_OUT/led_during2.bin"
job_wait_log "$log" 'LIGHT TEST END' 10 || true
job_sleep 4; cp "$DUMP/padled" "$JOB_OUT/led_after.bin"
cp "$log" "$JOB_OUT/mode.log"
IO=$DUMP/tables/$GAME/led_io.txt
said=$(python3 "$RIG/modes/newbuild/lightcheck.py" "$PORT" "$IO" "$JOB_OUT"/led_before.bin "$JOB_OUT"/led_during1.bin \
       "$JOB_OUT"/led_during2.bin "$JOB_OUT"/led_after.bin 2>&1 < /dev/null)
rc=$?
echo "$said" > "$JOB_OUT/lights.txt"
lamps=$(grep -a -m1 -Eo 'light_all[^;]{0,100}' "$log")
[ "$rc" = 0 ] || job_fail "$(tr '\n' ';' <<<"$said" | cut -c1-300) | ${lamps:-the runtime said nothing of light_all}"
job_pass "attract=${JOB_ATTRACT_S}s $(tr '\n' ';' <<<"$said" | cut -c1-300)"
