#!/bin/bash
# ownjob.sh <key> <card> - a whole-game mode (PAD-1400's `game_modes own_game`) through a full game on a new build
# (PAD-1555): the pinned mode object, the build's port and a mode file that IS the game, staged through tryit.sh
# install; the job plays three balls (the playfield switches gamecheck.sh presses, then drains until the whole
# game logs the ball's end, playing past the ball saver). Pass: the runtime armed the whole game with the port's scanned callers (`refused but from the callers
# that use them`), at least two balls ended under it, and the game never died (a refused award screen or light show
# that a caller used would crash it: the reason each port lists those callers).
#
#   PORT=<port file>   the port (default: modes/sdk/ports/<key>.port)
#
# Writes $JOB_OUT/play.txt (each drain's answer) and $JOB_OUT/mode.log. Run through rigbatch.sh.
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: ownjob.sh <key> <card>}" "${2:?usage: ownjob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] || job_fail "no port $PORT"
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$MODES/sdk/prebuilt/mode.so" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" || job_fail "could not stage"
printf 'name WHOLE GAME\ngame_modes own_game\nshots 0xffffffff\naward 1000\naward_ladder fixed\n' > "$S/mode.cfg"
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
export PAD_MODE_SO=/lib/pad_mode.so
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
job_sleep 5
job_start_game || job_fail "$JOB_WHY"
# the playfield switches gamecheck.sh presses (its own skip pattern: no trough, lane, flippers, locks, mechanisms)
pat=$(grep -o "grep -qiE '[^']*'" "$MODES/gamecheck.sh" | head -1 | sed "s/^grep -qiE '//; s/'\$//")
ids=()
while read -r id _num _node _bit name; do
    case "$id" in ""|\#*|*[!0-9]*) continue ;; esac
    echo "$name" | grep -qiE "$pat" && continue
    ids+=("$id")
done < "$DUMP/tables/$GAME/switch_list.txt"
job_say "${#ids[@]} playfield switches"
: > "$JOB_OUT/play.txt"
for ball in 1 2 3; do
    job_sleep 3
    python3 "$RIG/plunge.py" plunge >> "$JOB_OUT/play.txt" 2>&1 < /dev/null
    for id in "${ids[@]:0:40}"; do job_press "$id"; job_sleep 0.4; done
    ended=""
    for n in 1 2 3 4 5; do
        echo "ball $ball drain $n: $(python3 "$RIG/plunge.py" drain 2>&1 < /dev/null | head -1)" >> "$JOB_OUT/play.txt"
        if job_wait_log "$DUMP/mode.log" "own game: .* - ball $ball ended" 12; then ended=1; break; fi
        job_dead && break
        python3 "$RIG/plunge.py" plunge >> "$JOB_OUT/play.txt" 2>&1 < /dev/null      # the ball saver's ball
        for id in "${ids[@]:0:3}"; do job_press "$id"; done
        job_sleep $(( 10 * n + 10 ))
    done
    job_dead && break
    [ -n "$ended" ] || { echo "ball $ball never ended" >> "$JOB_OUT/play.txt"; break; }
done
cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null
job_shot "$JOB_OUT/end.png"
log=$JOB_OUT/mode.log
job_dead && job_fail "the game died under the whole game: $(job_died_why)"
grep -q "own game: award screens and light shows refused but from the callers that use them" "$log" \
    || job_fail "the whole game never armed with the port's callers: $(grep -m1 'own game:\|cannot switch' "$log")"
balls=$(grep -c "own game: .* - ball [0-9]* ended" "$log")
[ "$balls" -ge 2 ] || job_fail "only $balls ball(s) ended under the whole game: $(tail -1 "$JOB_OUT/play.txt")"
job_pass "attract=${JOB_ATTRACT_S}s whole game: $balls balls ended, $(grep -o 'show_start [0-9]* refused' "$log" | awk '{n+=$2} END {print n+0}') light shows and $(grep -o 'award_screen [0-9]* refused' "$log" | awk '{n+=$2} END {print n+0}') award screens refused"
