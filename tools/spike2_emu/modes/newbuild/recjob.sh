#!/bin/bash
# recjob.sh <key> <card> - a `stack no` mode waits for one of the game's modes it can tell only by its live records
# (PAD-1555; PAD-306's Metallica proof, re-made: STACK_RECORDS_PROVEN's evidence).
#
#   ID=<mode>      the game's mode that creates the records (Metallica: Enter Sandman 1)
#   SO=<object>    built with modes/sdk/gamemode_test_mode.c (gm.start)
#   PORT=<port>    the port (default: modes/sdk/ports/<key>.port)
#
# In a game (its ball scored first) STACK TEST (`stack no`) is asked with nothing of the game's running - a second ball
# the rig served is drained until it starts (then it is stopped); the game's start of ID (gm.start, PAD_TEST_PLAIN_START);
# STACK TEST asked again. Pass: it starts the first time and, the second, `not started (...): <a mode_records name> is
# running` - not a multiball.
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: recjob.sh <key> <card>}" "${2:?usage: recjob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] && [ -f "${SO:-}" ] && [ -n "${ID:-}" ] || job_fail "needs PORT, SO and ID"
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$SO" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" || job_fail "could not stage"
printf 'name STACK TEST\ngame_modes stack\nseconds 10\ntrigger 0x1 99\nshots 0xffffffff\naward 100\nstack no\n' > "$S/mode.cfg"
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
export PAD_MODE_SO=/lib/pad_mode.so PAD_TEST_PLAIN_START=1
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
for id in "${ids[@]:0:6}"; do job_press "$id"; job_sleep 0.5; done     # the ball scores first (stock_base_until)
job_sleep 4
ask() {
    local mark
    mark=$(grep -c "" "$log")
    bash "$MODES/tryit.sh" start 0 > /dev/null 2>&1 < /dev/null
    job_sleep 3
    tail -n +"$((mark + 1))" "$log" | grep -a -m1 -Eo 'STACK TEST (not started \([^)]*\): .*|START \([^)]*\))' | cut -c1-160
}
first=""
for k in 1 2 3; do
    first=$(ask)
    echo "ask $k: $first" >> "$JOB_OUT/play.txt"
    echo "$first" | grep -q "START" && break
    echo "drain: $(python3 "$RIG/plunge.py" drain 2>&1 < /dev/null | head -1)" >> "$JOB_OUT/play.txt"
    job_sleep 4
done
bash "$MODES/tryit.sh" stop > /dev/null 2>&1 < /dev/null
job_sleep 3
printf '%s' "$ID" > "$DUMP/gm.start"
job_sleep 3
second=$(ask)
cp "$log" "$JOB_OUT/mode.log"
started=$(grep -a -m1 -Eo "gm start $ID: -?[0-9]+" "$log")
echo "$first" | grep -q "START" || job_fail "with nothing of the game's running: ${first:-nothing said}"
echo "$second" | grep -q "not started" && ! echo "$second" | grep -q "multiball" \
    || job_fail "$first; ${started:-no gm start}; then: ${second:-nothing said}"
job_pass "attract=${JOB_ATTRACT_S}s nothing running: $first; $started; then: $second"
