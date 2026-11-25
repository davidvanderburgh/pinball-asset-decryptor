#!/bin/bash
# wizjob.sh <key> <card> - the game's own mini-wizards handed over by a mode on a new build (PAD-1555; PAD-473's
# wizexp_job, re-made).
#
#   PORT=<port>    the port (default: modes/sdk/ports/<key>.port)
#
# Two mode files, `game_wizard start <the port's wizard_name_1>` (slot 0) and `<wizard_name_2>` (slot 1), started one
# after the other in a game. Pass: `game wizard 1 (<name>): the game started it` and then wizard 2 held back while
# it runs (waiting, lit, or refused with the first in its way) - the evidence WIZARDS_PROVEN records.
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: wizjob.sh <key> <card>}" "${2:?usage: wizjob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] || job_fail "no port $PORT"
n1=$(awk '$1 == "text" && $2 == "wizard_name_1" {$1 = $2 = ""; sub(/^ +/, ""); print; exit}' "$PORT")
n2=$(awk '$1 == "text" && $2 == "wizard_name_2" {$1 = $2 = ""; sub(/^ +/, ""); print; exit}' "$PORT")
[ -n "$n1" ] && [ -n "$n2" ] || job_fail "the port names fewer than two mini-wizards"
cfg() { printf 'name %s\ngame_modes stack\nseconds 30\ntrigger 0x1 99\nshots 0x1\naward 100\ngame_wizard start %s\n' "$1" "$2"; }
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$MODES/sdk/prebuilt/mode.so" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" || job_fail "could not stage"
cfg "WIZ ONE" "$n1" > "$S/mode.cfg"
cfg "WIZ TWO" "$n2" > "$S/mode1.cfg"
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
export PAD_MODE_SO=/lib/pad_mode.so
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
log=$DUMP/mode.log
job_start_game || job_fail "$JOB_WHY"
job_sleep 3
python3 "$RIG/plunge.py" plunge > /dev/null 2>&1 < /dev/null
job_sleep 3
bash "$MODES/tryit.sh" start 0 > /dev/null 2>&1 < /dev/null
job_wait_log "$log" "game wizard 1 \\(" 20 || true
job_sleep 4
bash "$MODES/tryit.sh" start 1 > /dev/null 2>&1 < /dev/null
job_wait_log "$log" "game wizard 2 \\(" 20 || true
job_sleep 3
cp "$log" "$JOB_OUT/mode.log"
one=$(grep -a -m1 -E "game wizard 1 \(.*\): (started|the game started it)" "$log")
two=$(grep -a -E "game wizard 2 \(.*\): " "$log" | grep -av "rules still light" | tail -1)
[ -n "$one" ] || job_fail "wizard 1 not started: $(grep -a -m1 'game wizard 1' "$log" | cut -c1-160)"
echo "$two" | grep -qE "in its way|wait|refused|lit|holds" || job_fail "wizard 2 not held back: ${two:-no line}"
job_pass "attract=${JOB_ATTRACT_S}s ${one#*] } | ${two#*] }"
