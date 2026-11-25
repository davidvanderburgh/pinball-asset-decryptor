#!/bin/bash
# bsjob.sh <key> <card> - a mode's ball save on a new build (PAD-1555; PAD-420's bs_job, re-made).
#
#   PORT=<port>    the port (default: modes/sdk/ports/<key>.port)
#
# A mode with `ball_save 10` is started in a game; three playfield switches score; a drain inside the save; then the
# save is waited out, three more switches, and a drain. Pass: the runtime's `ball save: 10 s ... the game is saving`,
# the mode still running after the first drain (no END), and `END (ball ended)` after the second - the evidence
# BALL_SAVE_PROVEN records.
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: bsjob.sh <key> <card>}" "${2:?usage: bsjob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] || job_fail "no port $PORT"
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$MODES/sdk/prebuilt/mode.so" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" || job_fail "could not stage"
printf 'name BS TEST\ngame_modes stack\nseconds 90\ntrigger 0x1 99\nshots 0xffffffff\naward 1000\nball_save 10\n' > "$S/mode.cfg"
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
job_sleep 25                                   # the game's own ball saver runs out first
bash "$MODES/tryit.sh" start 0 > /dev/null 2>&1 < /dev/null
job_wait_log "$log" 'ball save: [0-9]+ s' 15 || { cp "$log" "$JOB_OUT/mode.log"; job_fail "no ball save line: $(grep -a -m1 'BS TEST' "$log" | tail -1)"; }
for id in "${ids[@]:0:3}"; do job_press "$id"; job_sleep 0.5; done
echo "drain 1: $(python3 "$RIG/plunge.py" drain 2>&1 < /dev/null | head -1)" > "$JOB_OUT/play.txt"
job_sleep 6
grep -aq "BS TEST END (" "$log" && { cp "$log" "$JOB_OUT/mode.log"; job_fail "the drain inside the save ended it: $(grep -a 'BS TEST END' "$log")"; }
python3 "$RIG/plunge.py" plunge >> "$JOB_OUT/play.txt" 2>&1 < /dev/null
# the mode's save runs out (and the game's own saver of a ball it launched itself): a switch tapped every 2 game
# seconds meanwhile - a saver that counts only while the ball is seen in play (Metallica, D&D LE) runs out too
for ((t = 0; t < ${SAVE_WAIT:-12}; t += 2)); do job_press "${ids[$(( (t / 2) % ${#ids[@]} ))]}"; job_sleep 2; done
for id in "${ids[@]:3:3}"; do job_press "$id"; job_sleep 0.5; done
# every ball out drains (a title that put a second ball out after the save - Metallica, D&D LE - has one more)
for k in 2 3 4 5 6 7 8 9; do
    said=$(python3 "$RIG/plunge.py" drain 2>&1 < /dev/null | head -1)
    echo "drain $k: $said" >> "$JOB_OUT/play.txt"
    case "$said" in *"shooter lane"*) python3 "$RIG/plunge.py" plunge >> "$JOB_OUT/play.txt" 2>&1 < /dev/null;; esac
    job_wait_log "$log" 'BS TEST END \(' 8 && break
done
cp "$log" "$JOB_OUT/mode.log"
save=$(grep -a -m1 -Eo 'ball save: [0-9]+ s with [0-9]+ ball\(s\) in play: the game [a-z ]+' "$log")
end=$(grep -a -m1 -Eo 'BS TEST END \([^)]*\): [0-9]+ shots, awarded [0-9]+' "$log")
echo "$save" | grep -q "is saving" || job_fail "${save:-no save line}"
echo "$end" | grep -q "(ball ended)" || job_fail "the second drain did not end the ball: ${end:-no END}"
job_pass "attract=${JOB_ATTRACT_S}s $save; a drain inside it served back; $end"
