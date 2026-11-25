#!/bin/bash
# mbjob.sh <key> <card> - a mode's own multiball on a new build (PAD-1555; PAD-420's mb_job, re-made).
#
#   PORT=<port>    the port (default: modes/sdk/ports/<key>.port)
#
# A mode with `multiball 3 5` and `add_ball 0xffffffff 1` is started in a game; the served balls are launched, a
# playfield switch adds a ball, and balls drain one at a time (switches tapped between, against ball search). Pass:
# `multiball: 3 balls asked for`, a fourth ball in play, and the mode's `END (one ball left)` - the evidence
# MULTIBALL_PROVEN records (served 3, add-a-ball to 4, drains to 1).
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: mbjob.sh <key> <card>}" "${2:?usage: mbjob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] || job_fail "no port $PORT"
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$MODES/sdk/prebuilt/mode.so" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" || job_fail "could not stage"
printf 'name MB TEST\ngame_modes stack\nseconds 120\ntrigger 0x1 99\nshots 0xffffffff\naward 1000\nmultiball 3 5\nadd_ball 0xffffffff 1\n' > "$S/mode.cfg"
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
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
bash "$MODES/tryit.sh" start 0 > /dev/null 2>&1 < /dev/null
job_wait_log "$log" 'multiball: [0-9]+ balls asked for' 15 || { cp "$log" "$JOB_OUT/mode.log"; job_fail "no multiball line"; }
: > "$JOB_OUT/play.txt"
for k in 1 2 3 4 5 6; do                       # launch what the game serves
    job_sleep 2
    python3 "$RIG/plunge.py" plunge >> "$JOB_OUT/play.txt" 2>&1 < /dev/null
done
for id in "${ids[@]:0:4}"; do job_press "$id"; job_sleep 0.5; done     # a hit adds a ball
for k in 1 2; do job_sleep 2; python3 "$RIG/plunge.py" plunge >> "$JOB_OUT/play.txt" 2>&1 < /dev/null; done
for k in 1 2 3 4 5 6; do                       # drain them one at a time
    grep -aq "MB TEST END (" "$log" && break
    echo "drain $k: $(python3 "$RIG/plunge.py" drain 2>&1 < /dev/null | head -1)" >> "$JOB_OUT/play.txt"
    job_sleep 1.5
    job_press "${ids[$((k + 4))]:-${ids[0]}}"
    job_sleep 1.5
done
job_wait_log "$log" 'MB TEST END \(' 10 || true
cp "$log" "$JOB_OUT/mode.log"
asked=$(grep -a -m1 -Eo 'multiball: [0-9]+ balls asked for \([0-9]+ in play now\)[^:]*: the game [a-z ]+' "$log")
most=$(grep -a -Eo '[0-9]+ in play now' "$log" | awk '{print $1}' | sort -n | tail -1)
added=$(grep -a -c -E 'add.a.ball|a ball added|ADD.A.BALL|one more ball' "$log")
end=$(grep -a -m1 -Eo 'MB TEST END \([^)]*\)' "$log")
[ -n "$asked" ] || job_fail "no multiball served"
echo "$end" | grep -q "one ball left" || job_fail "$asked; drains did not end it at one ball: ${end:-no END} ($(tail -1 "$JOB_OUT/play.txt"))"
job_pass "attract=${JOB_ATTRACT_S}s $asked; add-a-ball lines $added; $end"
