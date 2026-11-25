#!/bin/bash
# stjob.sh <key> <card> - a `stack no` mode waits for a multiball on a new build (PAD-1555; PAD-420's st_job, re-made:
# STACK_BALLS_PROVEN's evidence).
#
#   PORT=<port>    the port (default: modes/sdk/ports/<key>.port)
#
# Slot 0, MB TEST: `multiball 3 5`, 10 s - its clock ends it with its balls still in play. Slot 1, STACK TEST: `stack
# no`. STACK TEST asked while the balls are out: refused (`not started (...): ... is running`); the balls drained to
# one, asked again: START. Pass: both.
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: stjob.sh <key> <card>}" "${2:?usage: stjob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] || job_fail "no port $PORT"
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$MODES/sdk/prebuilt/mode.so" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" || job_fail "could not stage"
printf 'name MB TEST\ngame_modes stack\nseconds 10\ntrigger 0x1 99\nshots 0xffffffff\naward 1000\nmultiball 3 5\n' > "$S/mode.cfg"
printf 'name STACK TEST\ngame_modes stack\nseconds 10\ntrigger 0x2 99\nshots 0xffffffff\naward 1000\nstack no\n' > "$S/mode1.cfg"
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
[ -f "$DUMP/mode1.cfg" ] || cp "$S/mode1.cfg" "$DUMP/mode1.cfg"
export PAD_MODE_SO=/lib/pad_mode.so
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
log=$DUMP/mode.log
pat=$(grep -o "grep -qiE '[^']*'" "$MODES/gamecheck.sh" | head -1 | sed "s/^grep -qiE '//; s/'\$//")
ids=()
while read -r id _num _node _bit name; do
    case "$id" in ""|\#*|*[!0-9]*) continue ;; esac
    echo "$name" | grep -qiE "$pat" && continue
    ids+=("$id")
done < "$DUMP/tables/$GAME/switch_list.txt"
job_start_game || job_fail "$JOB_WHY"
job_sleep 3
python3 "$RIG/plunge.py" plunge > /dev/null 2>&1 < /dev/null
job_sleep 20
for id in "${ids[@]:0:4}"; do job_press "$id"; job_sleep 0.5; done     # the ball scores first (stock_base_until)
bash "$MODES/tryit.sh" start 0 > /dev/null 2>&1 < /dev/null
job_wait_log "$log" 'multiball: [0-9]+ balls asked for' 15 || { cp "$log" "$JOB_OUT/mode.log"; job_fail "no multiball line"; }
: > "$JOB_OUT/play.txt"
for k in 1 2 3 4; do job_sleep 2; python3 "$RIG/plunge.py" plunge >> "$JOB_OUT/play.txt" 2>&1 < /dev/null; done
job_wait_log "$log" 'MB TEST END \(' 15 || true
end=$(grep -a -m1 -Eo 'MB TEST END \([^)]*\)' "$log")
job_sleep 2
mark=$(grep -c "" "$log")
bash "$MODES/tryit.sh" start 1 > /dev/null 2>&1 < /dev/null
job_sleep 3
refused=$(tail -n +"$((mark + 1))" "$log" | grep -a -m1 -Eo 'STACK TEST (not started \([^)]*\): .*|START \([^)]*\))' | cut -c1-160)
for k in 1 2; do                               # three balls drained to one
    echo "drain $k: $(python3 "$RIG/plunge.py" drain 2>&1 < /dev/null | head -1)" >> "$JOB_OUT/play.txt"
    job_sleep 2; job_press "${ids[$((k + 4))]:-${ids[0]}}"; job_sleep 1
done
job_sleep 3
mark=$(grep -c "" "$log")
bash "$MODES/tryit.sh" start 1 > /dev/null 2>&1 < /dev/null
job_sleep 3
later=$(tail -n +"$((mark + 1))" "$log" | grep -a -m1 -Eo 'STACK TEST (not started \([^)]*\): .*|START \([^)]*\))' | cut -c1-160)
cp "$log" "$JOB_OUT/mode.log"
echo "$refused" | grep -q "not started" || job_fail "${end:-no MB END}; with the balls out: ${refused:-nothing said}"
echo "$later" | grep -q "START" || job_fail "$end; $refused; at one ball: ${later:-nothing said}"
job_pass "attract=${JOB_ATTRACT_S}s $end; asked with the balls out: $refused; at one ball: $later"
