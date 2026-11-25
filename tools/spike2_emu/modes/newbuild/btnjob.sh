#!/bin/bash
# btnjob.sh <key> <card> - the cabinet buttons as shots on a new build (PAD-1555; PAD-1403's job.sh, re-made:
# BUTTON_SHOTS_PROVEN's evidence).
#
#   CFG=<buttons.cfg>  the card's own buttons.cfg, as Write puts it beside the mode files (a mediabuild.py set's)
#   PORT=<port>        the port (default: modes/sdk/ports/<key>.port)
#
# Run with rigbatch --speed 1. Staged: the pinned object, the port, the buttons.cfg and an idle mode. In attract the
# first button is pressed (no shot may come); in a game each line's own action is played - a press or release a 200 ms
# press, a hold the button held its ms + 600, a combo the first held and the second pressed - and the runtime's
# `button shot: <name> (0x<mask>, ...)` lines read after it. Pass: every line's shot exactly once at its own action,
# none in attract. Writes $JOB_OUT/buttons.txt.
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: btnjob.sh <key> <card>}" "${2:?usage: btnjob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] && [ -f "${CFG:-}" ] || job_fail "needs PORT and CFG"
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$MODES/sdk/prebuilt/mode.so" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" && cp "$CFG" "$S/buttons.cfg" \
    || job_fail "could not stage"
printf 'name IDLE TEST\ngame_modes stack\nseconds 5\ntrigger 0x1 99\nshots 0x1\naward 100\n' > "$S/mode.cfg"
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
[ -f "$DUMP/buttons.cfg" ] || cp "$CFG" "$DUMP/buttons.cfg"
export PAD_MODE_SO=/lib/pad_mode.so
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
log=$DUMP/mode.log
first=$(awk '$1 == "button" {print $4; exit}' "$CFG")
mark=$(grep -c "" "$log")
job_press "$first" 200; job_sleep 2
attract=$(tail -n +"$((mark + 1))" "$log" | grep -a -c 'button shot: ')
job_start_game || job_fail "$JOB_WHY"
job_sleep 3
python3 "$RIG/plunge.py" plunge > /dev/null 2>&1 < /dev/null
job_sleep 8
: > "$JOB_OUT/buttons.txt"
bad=0
while read -r key mask kind a b rest; do
    [ "$key" = button ] || continue
    case "$kind" in
        press|release) name="$b $rest" ;;
        *) name="$rest" ;;
    esac
    name=$(echo "$name" | sed 's/ *$//')
    mark=$(grep -c "" "$log")
    case "$kind" in
        press|release) job_press "$a" 200 ;;
        hold) job_press "$a" $((b + 600)) ;;
        combo) job_press "$a" 1500 & job_sleep 0.4; job_press "$b" 300; wait ;;
    esac
    job_sleep 1.5
    n=$(tail -n +"$((mark + 1))" "$log" | grep -a -c -F "button shot: $name (")
    if [ "$n" = 1 ]; then echo "pass $kind $name" >> "$JOB_OUT/buttons.txt"
    else echo "fail $kind $name: $n shot line(s)" >> "$JOB_OUT/buttons.txt"; bad=$((bad + 1)); fi
done < "$CFG"
cp "$log" "$JOB_OUT/mode.log"
total=$(grep -c "" "$JOB_OUT/buttons.txt")
[ "$attract" = 0 ] || job_fail "$attract button shot(s) in attract"
[ "$bad" = 0 ] || job_fail "$bad of $total not once: $(grep '^fail' "$JOB_OUT/buttons.txt" | tr '\n' ';' | cut -c1-300)"
job_pass "attract=${JOB_ATTRACT_S}s none in attract; $total of $total button shots once each at their own action"
